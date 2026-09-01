from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from quirebase.access.documents import require_attachment, require_revision
from quirebase.access.items import can_edit_item, require_editable_item, require_readable_item
from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
    VersionConflict,
)
from quirebase.core.storage import (
    ObjectMetadata,
    ObjectResponse,
    ObjectSource,
    ObjectStore,
    StagedObject,
    get_object_store,
)
from quirebase.models import (
    Attachment,
    AttachmentRole,
    FileRevision,
    ImportBatch,
    Item,
    Job,
    JobState,
    Project,
    ProjectItem,
    ProjectMember,
    User,
)
from quirebase.pipeline.derived_state import propagate_file_revision_change
from quirebase.pipeline.inspection import job_payload, validate_pdf_container

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


class UnsupportedMediaType(DomainError):
    pass


GRAPHICAL_ABSTRACT_MEDIA_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}


@dataclass
class StagedPdf:
    object_key: str
    sha256: str
    size: int
    original_name: str
    _staged: StagedObject = field(repr=False)

    def revision_data(self) -> tuple[str, str, int, str]:
        return self.object_key, self.sha256, self.size, self.original_name

    async def release(self) -> None:
        await self._staged.release()


@dataclass(frozen=True)
class ItemThumbnail:
    response: ObjectResponse
    media_type: str
    source_kind: str
    source_id: str


async def _validate_staged_pdf(store: ObjectStore, object_key: str) -> None:
    """Own materialization until the validator thread has actually stopped."""
    async with store.materialize(object_key) as path:
        await asyncio.to_thread(validate_pdf_container, path)


async def stage_pdf(
    db: AsyncSession, source: ObjectSource, filename: str, max_bytes: int
) -> StagedPdf:
    if not filename or not filename.lower().endswith(".pdf"):
        raise UnsupportedMediaType("a PDF file is required")
    store = get_object_store()
    try:
        staged = await store.put_cas(
            source,
            suffix=".pdf",
            max_bytes=max_bytes,
            required_prefix=b"%PDF-",
        )
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    staged_pdf = StagedPdf(
        staged.key,
        staged.sha256,
        staged.size,
        Path(filename).name,
        staged,
    )
    validation = asyncio.create_task(_validate_staged_pdf(store, staged.key))
    try:
        await asyncio.shield(validation)
    except asyncio.CancelledError:
        _consume_current_cancellation()
        with suppress(Exception):
            await _finish_task_despite_cancellation(validation)
        cleanup = asyncio.create_task(_release_staged_pdf(db, staged_pdf))
        await _finish_task_despite_cancellation(cleanup)
        raise
    except ValueError as error:
        await _release_staged_pdf(db, staged_pdf)
        raise ValidationFailure(str(error)) from error
    except Exception:
        await _release_staged_pdf(db, staged_pdf)
        raise
    return staged_pdf


def _consume_current_cancellation() -> None:
    task = asyncio.current_task()
    if task is not None:
        task.uncancel()


async def _finish_task_despite_cancellation[StagedResult](
    task: asyncio.Task[StagedResult],
) -> StagedResult:
    """Wait for an ownership-bearing task even if more cancellations arrive."""
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            _consume_current_cancellation()


async def _release_staged_pdf(db: AsyncSession, staged: StagedPdf) -> None:
    await staged.release()
    await discard_staged_object(db, staged.object_key)


async def _release_staged_attachment(db: AsyncSession, staged: StagedObject) -> None:
    await staged.release()
    await discard_staged_object(db, staged.key)


async def _rollback_and_release_pdf(db: AsyncSession, staged: StagedPdf) -> None:
    await db.rollback()
    await _release_staged_pdf(db, staged)


async def _rollback_and_release_attachment(db: AsyncSession, staged: StagedObject) -> None:
    await db.rollback()
    await _release_staged_attachment(db, staged)


async def attach_staged_pdf(
    db: AsyncSession,
    user: User,
    item: Item,
    staged: tuple[str, str, int, str],
) -> FileRevision:
    key, digest, size, original_name = staged
    revision = FileRevision(
        item_id=item.id,
        object_key=key,
        sha256=digest,
        size=size,
        original_name=original_name,
        created_by=user.id,
    )
    db.add(revision)
    await db.flush()
    db.add(
        Job(
            kind="pdf.inspect",
            payload=job_payload(revision_id=revision.id),
            idempotency_key=f"pdf.inspect:{revision.id}",
            owner_id=user.id,
        )
    )
    record_event(db, user.id, "pdf.upload", "file_revision", revision.id)
    return revision


def _pdf_import_object_keys(records_json: str) -> set[str]:
    try:
        records = json.loads(records_json)
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(records, list):
        return set()
    return {
        object_key
        for record in records
        if isinstance(record, dict)
        and isinstance((pdf := record.get("_pdf")), dict)
        and isinstance((object_key := pdf.get("object_key")), str)
    }


async def _object_is_referenced(db: AsyncSession, object_key: str) -> bool:
    if await db.scalar(
        select(FileRevision.object_key).where(FileRevision.object_key == object_key)
    ):
        return True
    if await db.scalar(select(Attachment.object_key).where(Attachment.object_key == object_key)):
        return True
    return any(
        object_key in _pdf_import_object_keys(records)
        for records in (
            await db.scalars(select(ImportBatch.records).where(ImportBatch.file_format == "pdf"))
        )
    )


async def delete_unreferenced_objects(
    db: AsyncSession, object_keys: Iterable[str]
) -> tuple[str, ...]:
    """Delete objects only when no committed, pending, or in-flight record references them."""
    keys = tuple(dict.fromkeys(key for key in object_keys if key))
    if not keys:
        return ()
    store = get_object_store()
    actually_deleted: list[str] = []
    for object_key in keys:
        if await _object_is_referenced(db, object_key):
            continue
        if await store.delete(object_key):
            actually_deleted.append(object_key)
    return tuple(actually_deleted)


async def discard_staged_object(db: AsyncSession, object_key: str) -> None:
    await delete_unreferenced_objects(db, (object_key,))


async def store_pdf_revision(
    db: AsyncSession,
    user: User,
    item_id: str,
    source: ObjectSource,
    filename: str,
    max_bytes: int | None = None,
) -> FileRevision:
    from quirebase.operations.settings import get_effective_setting

    item = await require_editable_item(db, user, item_id)
    if max_bytes is None:
        max_bytes = await get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
    staged = await stage_pdf(db, source, filename, max_bytes)
    try:
        revision = await attach_staged_pdf(db, user, item, staged.revision_data())
        await db.commit()
    except asyncio.CancelledError:
        _consume_current_cancellation()
        cleanup_task = asyncio.create_task(_rollback_and_release_pdf(db, staged))
        await _finish_task_despite_cancellation(cleanup_task)
        raise
    except Exception:
        await _rollback_and_release_pdf(db, staged)
        raise
    await staged.release()
    return revision


def _is_image_header(header: bytes, content_type: str) -> bool:
    return {
        "image/gif": header.startswith((b"GIF87a", b"GIF89a")),
        "image/jpeg": header.startswith(b"\xff\xd8\xff"),
        "image/png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
    }.get(content_type, False)


async def _lock_item_for_attachment_role_replacement(db: AsyncSession, item_id: str) -> None:
    if db.get_bind().dialect.name == "sqlite":
        locked_item_id = await db.scalar(
            update(Item)
            .where(Item.id == item_id)
            .values(updated_at=Item.updated_at)
            .returning(Item.id)
        )
    else:
        locked_item_id = await db.scalar(
            select(Item.id).where(Item.id == item_id).with_for_update()
        )
    if locked_item_id is None:
        raise ResourceUnavailable("item not accessible")


async def create_attachment(
    db: AsyncSession,
    user: User,
    item_id: str,
    source: ObjectSource,
    filename: str,
    content_type: str = "application/octet-stream",
    max_bytes: int | None = None,
    role: AttachmentRole | None = None,
) -> Attachment:
    from quirebase.operations.settings import get_effective_setting

    if not await can_edit_item(db, user, item_id) or not filename:
        raise ResourceUnavailable("item not accessible or filename missing")
    if max_bytes is None:
        max_bytes = await get_effective_setting(
            db, "max_attachment_bytes", get_settings().max_attachment_bytes
        )
    if role == AttachmentRole.graphical_abstract and content_type not in (
        GRAPHICAL_ABSTRACT_MEDIA_TYPES
    ):
        raise ValidationFailure("graphical abstract must be a PNG, JPEG, WebP, or GIF image")
    store = get_object_store()
    try:
        staged = await store.put_cas(source, suffix=".bin", max_bytes=max_bytes)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    key, digest, size = staged.key, staged.sha256, staged.size
    try:
        if role == AttachmentRole.graphical_abstract:
            if size:
                response = await store.get_range(key, 0, min(12, size))
                header = b"".join([bytes(chunk) async for chunk in response.body])
            else:
                header = b""
            if not _is_image_header(header, content_type):
                raise ValidationFailure("graphical abstract content does not match its image type")
    except asyncio.CancelledError:
        _consume_current_cancellation()
        cleanup_task = asyncio.create_task(_release_staged_attachment(db, staged))
        await _finish_task_despite_cancellation(cleanup_task)
        raise
    except Exception:
        await _release_staged_attachment(db, staged)
        raise
    try:
        if role is not None:
            await _lock_item_for_attachment_role_replacement(db, item_id)
            current = await db.scalar(
                select(Attachment).where(
                    Attachment.item_id == item_id,
                    Attachment.role == role,
                )
            )
            if current is not None:
                current.role = None
                await db.flush()
        record = Attachment(
            item_id=item_id,
            object_key=key,
            sha256=digest,
            size=size,
            mime_type=content_type[:100],
            original_name=Path(filename).name[:255],
            role=role,
            created_by=user.id,
        )
        db.add(record)
        await db.flush()
        record_event(db, user.id, "attachment.upload", "attachment", record.id)
        await db.commit()
    except asyncio.CancelledError:
        _consume_current_cancellation()
        cleanup_task = asyncio.create_task(_rollback_and_release_attachment(db, staged))
        await _finish_task_despite_cancellation(cleanup_task)
        raise
    except Exception:
        await _rollback_and_release_attachment(db, staged)
        raise
    await staged.release()
    return record


async def get_attachment_file(
    db: AsyncSession, user: User, item_id: str, attachment_id: str
) -> tuple[ObjectResponse, str, str]:
    record = await require_attachment(db, user, item_id, attachment_id)
    return (
        await get_object_store().get(record.object_key),
        record.original_name,
        record.mime_type or "application/octet-stream",
    )


async def get_revision_file(
    db: AsyncSession,
    user: User,
    item_id: str,
    revision_id: str,
    *,
    byte_range: tuple[int, int] | None = None,
) -> tuple[ObjectResponse, str, str]:
    revision = await require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    store = get_object_store()
    response = (
        await store.get_range(revision.object_key, *byte_range)
        if byte_range is not None
        else await store.get(revision.object_key)
    )
    return response, revision.original_name, revision.sha256


async def head_revision_file(
    db: AsyncSession, user: User, item_id: str, revision_id: str
) -> tuple[ObjectMetadata, str, str]:
    revision = await require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    return (
        await get_object_store().head(revision.object_key),
        revision.original_name,
        revision.sha256,
    )


async def get_revision_thumbnail(
    db: AsyncSession, user: User, item_id: str, revision_id: str
) -> ObjectResponse:
    revision = await require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    key = f"thumbnails/{revision.id}.png"
    if not await get_object_store().exists(key):
        raise ResourceNotFound("revision thumbnail not found")
    return await get_object_store().get(key)


async def get_item_thumbnail(db: AsyncSession, user: User, item_id: str) -> ItemThumbnail:
    await require_readable_item(db, user, item_id)
    graphical_abstract = await db.scalar(
        select(Attachment).where(
            Attachment.item_id == item_id,
            Attachment.role == AttachmentRole.graphical_abstract,
        )
    )
    if graphical_abstract is not None:
        store = get_object_store()
        if await store.exists(graphical_abstract.object_key):
            return ItemThumbnail(
                response=await store.get(graphical_abstract.object_key),
                media_type=graphical_abstract.mime_type,
                source_kind="graphical_abstract",
                source_id=graphical_abstract.id,
            )
    revisions = (
        await db.scalars(
            select(FileRevision)
            .where(
                FileRevision.item_id == item_id,
                FileRevision.processing_state == "ready",
            )
            .order_by(FileRevision.created_at.desc())
        )
    ).all()
    for revision in revisions:
        key = f"thumbnails/{revision.id}.png"
        store = get_object_store()
        if await store.exists(key):
            return ItemThumbnail(
                response=await store.get(key),
                media_type="image/png",
                source_kind="pdf_thumbnail",
                source_id=revision.id,
            )
    raise ResourceNotFound("item thumbnail not found")


def _job_targets_revision(job: Job, revision_id: str) -> bool:
    try:
        payload = json.loads(job.payload)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(payload, dict) and payload.get("revision_id") == revision_id


async def delete_file_revision(
    db: AsyncSession, user: User, item_id: str, revision_id: str
) -> None:
    await require_editable_item(db, user, item_id)
    revision = await db.scalar(
        select(FileRevision).where(FileRevision.id == revision_id).with_for_update()
    )
    if revision is None or revision.item_id != item_id:
        raise ResourceNotFound("file revision not found")
    inspection_job = await db.scalar(
        select(Job)
        .where(
            Job.kind == "pdf.inspect",
            Job.idempotency_key == f"pdf.inspect:{revision_id}",
        )
        .with_for_update()
    )
    export_jobs = tuple(
        job
        for job in (
            await db.scalars(
                select(Job)
                .where(
                    Job.kind == "pdf.export_annotations",
                    Job.state.in_([JobState.pending, JobState.running, JobState.failed]),
                )
                .with_for_update()
            )
        ).all()
        if _job_targets_revision(job, revision_id)
    )
    revision_jobs = tuple(job for job in (inspection_job, *export_jobs) if job is not None)
    if any(job.state == JobState.running for job in revision_jobs):
        raise VersionConflict(
            message="PDF background work is still running; retry deletion shortly"
        )
    object_key = revision.object_key
    thumbnail_key = f"thumbnails/{revision.id}.png"
    for job in revision_jobs:
        if job.state in {JobState.pending, JobState.failed}:
            await db.delete(job)
    await db.delete(revision)
    await db.flush()
    await propagate_file_revision_change(db, item_id, owner_id=user.id)
    record_event(db, user.id, "pdf.delete", "file_revision", revision.id)
    await db.commit()
    await get_object_store().delete(thumbnail_key)
    await delete_unreferenced_objects(db, (object_key,))


async def delete_attachment(db: AsyncSession, user: User, item_id: str, attachment_id: str) -> None:
    await require_editable_item(db, user, item_id)
    attachment = await db.get(Attachment, attachment_id)
    if attachment is None or attachment.item_id != item_id:
        raise ResourceNotFound("attachment not found")
    object_key = attachment.object_key
    await db.delete(attachment)
    record_event(db, user.id, "attachment.delete", "attachment", attachment.id)
    await db.commit()
    await delete_unreferenced_objects(db, (object_key,))


async def get_pdf_viewer_data(
    db: AsyncSession, user: User, item_id: str, revision_id: str
) -> dict[str, Any]:
    revision = await require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    projects = list(
        (
            await db.scalars(
                select(Project)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .join(ProjectItem, ProjectItem.project_id == Project.id)
                .where(ProjectMember.user_id == user.id, ProjectItem.item_id == item_id)
                .order_by(Project.name)
            )
        ).all()
    )
    return {
        "item": revision.item,
        "revision": revision,
        "projects": projects,
    }
