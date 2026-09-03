from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

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
)
from quirebase.core.storage import (
    ObjectMetadata,
    ObjectResponse,
    ObjectSource,
    ObjectStore,
    ObjectSuffix,
    StoredObject,
    get_object_store,
    object_key,
)
from quirebase.core.workflows import (
    DOCUMENT_CLEANUP_QUEUE,
    DOCUMENTS_QUEUE,
    LIBRARY_QUEUE,
    UPLOAD_COMPLETE_TOPIC,
    UPLOAD_QUEUE,
    durable_operations,
    list_active_workflows,
)
from quirebase.documents.events import FILE_REVISION_CHANGED_WORKFLOW, OBJECT_CLEANUP_WORKFLOW
from quirebase.documents.pdf import validate_pdf_container
from quirebase.documents.workflows import (
    ATTACHMENT_UPLOAD_WORKFLOW,
    IMPORTED_REVISION_INSPECTION_WORKFLOW,
    REVISION_UPLOAD_WORKFLOW,
)
from quirebase.models import (
    Attachment,
    AttachmentRole,
    ExportArtifact,
    FileRevision,
    ImportBatch,
    Item,
    Project,
    ProjectItem,
    ProjectMember,
    User,
)

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
    size: int
    original_name: str

    def revision_data(self) -> tuple[str, int, str]:
        return self.object_key, self.size, self.original_name

    async def release(self) -> None:
        """Compatibility no-op: owned UUID objects do not require leases."""


@dataclass(frozen=True)
class UploadWorkflow:
    workflow_id: str
    object_id: UUID
    object_key: str


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
        staged = await store.put_object(
            uuid4(),
            ObjectSuffix.PDF,
            source,
            max_bytes=max_bytes,
            required_prefix=b"%PDF-",
        )
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    staged_pdf = StagedPdf(
        staged.key,
        staged.size,
        Path(filename).name,
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


async def _release_staged_attachment(db: AsyncSession, staged: StoredObject) -> None:
    await discard_staged_object(db, staged.key)


async def _rollback_and_release_pdf(db: AsyncSession, staged: StagedPdf) -> None:
    await db.rollback()
    await _release_staged_pdf(db, staged)


async def _rollback_and_release_attachment(db: AsyncSession, staged: StoredObject) -> None:
    await db.rollback()
    await _release_staged_attachment(db, staged)


async def attach_staged_pdf(
    db: AsyncSession,
    user: User,
    item: Item,
    staged: tuple[str, int, str],
) -> FileRevision:
    key, size, original_name = staged
    revision = FileRevision(
        item_id=item.id,
        object_key=key,
        size=size,
        original_name=original_name,
        created_by=user.id,
    )
    db.add(revision)
    await db.flush()
    thumbnail_object_id = uuid4()
    thumbnail_key = object_key(thumbnail_object_id, ObjectSuffix.PNG)
    await durable_operations().enqueue_in_transaction(
        db,
        IMPORTED_REVISION_INSPECTION_WORKFLOW,
        revision.id,
        user.id,
        key,
        str(thumbnail_object_id),
        queue_name=DOCUMENTS_QUEUE,
        workflow_id=f"inspect-imported-revision:{revision.id}",
        partition_key=revision.id,
        attributes={
            "capability": "documents",
            "operation": "inspect_imported_revision",
            "owner_id": user.id,
            "item_id": item.id,
            "revision_id": revision.id,
            "object_key": key,
            "object_keys": [key, thumbnail_key],
        },
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


async def _referenced_candidates(db: AsyncSession, object_keys: tuple[str, ...]) -> set[str]:
    referenced = set(
        (
            await db.scalars(
                select(FileRevision.object_key).where(FileRevision.object_key.in_(object_keys))
            )
        ).all()
    )
    referenced.update(
        key
        for key in (
            await db.scalars(
                select(FileRevision.thumbnail_object_key).where(
                    FileRevision.thumbnail_object_key.in_(object_keys)
                )
            )
        ).all()
        if key
    )
    referenced.update(
        (
            await db.scalars(
                select(Attachment.object_key).where(Attachment.object_key.in_(object_keys))
            )
        ).all()
    )
    referenced.update(
        (
            await db.scalars(
                select(ExportArtifact.object_key).where(ExportArtifact.object_key.in_(object_keys))
            )
        ).all()
    )
    candidates = set(object_keys)
    for records in await db.scalars(
        select(ImportBatch.records).where(ImportBatch.file_format == "pdf")
    ):
        referenced.update(candidates & _pdf_import_object_keys(records))
    return referenced


async def _active_object_reservations(
    object_keys: tuple[str, ...], ignore_workflow_id: str | None
) -> set[str]:
    candidates = set(object_keys)
    reserved: set[str] = set()
    for workflow in await list_active_workflows():
        if workflow.id == ignore_workflow_id:
            continue
        # Cleanup workflows request deletion; they do not own their targets.
        if workflow.name == OBJECT_CLEANUP_WORKFLOW:
            continue
        attributes = workflow.attributes or {}
        raw_keys = attributes.get("object_keys")
        if isinstance(raw_keys, (list, tuple)):
            reserved.update(candidates & {key for key in raw_keys if isinstance(key, str)})
        if isinstance((key := attributes.get("object_key")), str) and key in candidates:
            reserved.add(key)
    return reserved


async def delete_unreferenced_objects(
    db: AsyncSession,
    object_keys: Iterable[str],
    *,
    ignore_workflow_id: str | None = None,
) -> tuple[str, ...]:
    """Delete objects only when no committed, pending, or in-flight record references them."""
    keys = tuple(dict.fromkeys(key for key in object_keys if key))
    if not keys:
        return ()
    referenced = await _referenced_candidates(db, keys)
    await db.rollback()
    referenced.update(await _active_object_reservations(keys, ignore_workflow_id))
    store = get_object_store()
    actually_deleted: list[str] = []
    for key in keys:
        if key in referenced:
            continue
        if await store.delete(key):
            actually_deleted.append(key)
    return tuple(actually_deleted)


async def enqueue_object_cleanup(
    db: AsyncSession,
    object_keys: Iterable[str],
    *,
    owner_id: str | None,
    operation: str,
    target_id: str | None = None,
) -> str | None:
    """Durably request post-commit deletion of currently unreferenced objects."""
    keys = list(dict.fromkeys(key for key in object_keys if key))
    if not keys:
        return None
    workflow_id = f"cleanup-objects:{uuid4()}"
    await durable_operations().enqueue_in_transaction(
        db,
        OBJECT_CLEANUP_WORKFLOW,
        keys,
        queue_name=DOCUMENT_CLEANUP_QUEUE,
        workflow_id=workflow_id,
        attributes={
            "capability": "documents",
            "operation": operation,
            "owner_id": owner_id,
            "target_id": target_id,
            "object_keys": keys,
        },
    )
    return workflow_id


async def discard_staged_object(db: AsyncSession, object_key: str) -> None:
    await delete_unreferenced_objects(db, (object_key,))


async def store_pdf_revision(
    db: AsyncSession,
    user: User,
    item_id: str,
    source: ObjectSource,
    filename: str,
    max_bytes: int | None = None,
) -> UploadWorkflow:
    from quirebase.operations.settings import get_effective_setting

    await require_editable_item(db, user, item_id)
    if not filename or not filename.lower().endswith(".pdf"):
        raise UnsupportedMediaType("a PDF file is required")
    if max_bytes is None:
        max_bytes = await get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
    revision_id = uuid4()
    thumbnail_object_id = uuid4()
    revision_key = object_key(revision_id, ObjectSuffix.PDF)
    thumbnail_key = object_key(thumbnail_object_id, ObjectSuffix.PNG)
    workflow_id = f"upload-revision:{revision_id}"
    await durable_operations().enqueue(
        REVISION_UPLOAD_WORKFLOW,
        item_id,
        user.id,
        str(revision_id),
        str(revision_id),
        str(thumbnail_object_id),
        Path(filename).name,
        queue_name=UPLOAD_QUEUE,
        workflow_id=workflow_id,
        attributes={
            "capability": "documents",
            "operation": "upload_revision",
            "owner_id": user.id,
            "item_id": item_id,
            "revision_id": str(revision_id),
            "object_key": revision_key,
            "object_keys": [revision_key, thumbnail_key],
        },
    )
    try:
        stored = await get_object_store().put_object(
            revision_id,
            ObjectSuffix.PDF,
            source,
            max_bytes=max_bytes,
            required_prefix=b"%PDF-",
        )
        await durable_operations().send(
            workflow_id,
            {"status": "complete", "key": stored.key, "size": stored.size},
            topic=UPLOAD_COMPLETE_TOPIC,
            idempotency_key=f"upload-complete:{revision_id}",
        )
    except BaseException as error:
        await durable_operations().send(
            workflow_id,
            {"status": "failed", "error": type(error).__name__},
            topic=UPLOAD_COMPLETE_TOPIC,
            idempotency_key=f"upload-failed:{revision_id}",
        )
        if isinstance(error, ValueError):
            raise ValidationFailure(str(error)) from error
        raise
    return UploadWorkflow(
        workflow_id,
        revision_id,
        revision_key,
    )


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
) -> UploadWorkflow:
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
    attachment_id = uuid4()
    attachment_key = object_key(attachment_id, ObjectSuffix.BINARY)
    workflow_id = f"upload-attachment:{attachment_id}"
    await durable_operations().enqueue(
        ATTACHMENT_UPLOAD_WORKFLOW,
        item_id,
        user.id,
        str(attachment_id),
        str(attachment_id),
        Path(filename).name,
        content_type,
        role.value if role else None,
        queue_name=UPLOAD_QUEUE,
        workflow_id=workflow_id,
        attributes={
            "capability": "documents",
            "operation": "upload_attachment",
            "owner_id": user.id,
            "item_id": item_id,
            "attachment_id": str(attachment_id),
            "object_key": attachment_key,
            "object_keys": [attachment_key],
        },
    )
    try:
        stored = await get_object_store().put_object(
            attachment_id, ObjectSuffix.BINARY, source, max_bytes=max_bytes
        )
        await durable_operations().send(
            workflow_id,
            {"status": "complete", "key": stored.key, "size": stored.size},
            topic=UPLOAD_COMPLETE_TOPIC,
            idempotency_key=f"upload-complete:{attachment_id}",
        )
    except BaseException as error:
        await durable_operations().send(
            workflow_id,
            {"status": "failed", "error": type(error).__name__},
            topic=UPLOAD_COMPLETE_TOPIC,
            idempotency_key=f"upload-failed:{attachment_id}",
        )
        if isinstance(error, ValueError):
            raise ValidationFailure(str(error)) from error
        raise
    return UploadWorkflow(
        workflow_id,
        attachment_id,
        attachment_key,
    )


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
    return response, revision.original_name, revision.mime_type or "application/pdf"


async def head_revision_file(
    db: AsyncSession, user: User, item_id: str, revision_id: str
) -> tuple[ObjectMetadata, str, str]:
    revision = await require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    return (
        await get_object_store().head(revision.object_key),
        revision.original_name,
        revision.mime_type or "application/pdf",
    )


async def get_revision_thumbnail(
    db: AsyncSession, user: User, item_id: str, revision_id: str
) -> ObjectResponse:
    revision = await require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    key = revision.thumbnail_object_key
    if key is None:
        raise ResourceNotFound("revision thumbnail not found")
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
        key = revision.thumbnail_object_key
        if key is None:
            continue
        store = get_object_store()
        if await store.exists(key):
            return ItemThumbnail(
                response=await store.get(key),
                media_type="image/png",
                source_kind="pdf_thumbnail",
                source_id=revision.id,
            )
    raise ResourceNotFound("item thumbnail not found")


async def delete_file_revision(
    db: AsyncSession, user: User, item_id: str, revision_id: str
) -> None:
    await require_editable_item(db, user, item_id)
    revision = await db.scalar(
        select(FileRevision).where(FileRevision.id == revision_id).with_for_update()
    )
    if revision is None or revision.item_id != item_id:
        raise ResourceNotFound("file revision not found")
    object_key = revision.object_key
    thumbnail_key = revision.thumbnail_object_key
    await db.delete(revision)
    await db.flush()
    event_workflow_id = f"file-revision-deleted:{revision_id}"
    await durable_operations().enqueue_in_transaction(
        db,
        FILE_REVISION_CHANGED_WORKFLOW,
        item_id,
        user.id,
        queue_name=LIBRARY_QUEUE,
        workflow_id=event_workflow_id,
        attributes={"capability": "library", "item_id": item_id},
    )
    record_event(db, user.id, "pdf.delete", "file_revision", revision.id)
    await db.commit()
    if thumbnail_key:
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
