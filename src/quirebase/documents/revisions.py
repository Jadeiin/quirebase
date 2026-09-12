from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select, update

from quirebase.access.documents import require_attachment, require_revision
from quirebase.access.items import (
    lock_item_edit_authority,
    require_editable_item,
    require_readable_item,
)
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
    WorkflowState,
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
from quirebase.search import enqueue_search_changed

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


class UnsupportedMediaType(DomainError):
    pass


def _upload_identity(value: str | UUID | None) -> str:
    if value is None:
        return str(uuid4())
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as error:
        raise ValidationFailure("upload operation_id must be a UUID") from error


def _upload_object_id(kind: str, user_id: str, item_id: str, operation_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"quirebase:{kind}:{user_id}:{item_id}:{operation_id}")


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


_TERMINAL_UPLOAD_STATES: frozenset[WorkflowState] = frozenset({"succeeded", "failed", "cancelled"})


async def _existing_upload_workflow(
    workflow_id: str,
    workflow_name: str,
    object_id: UUID,
    object_key_value: str,
    expected_attributes: dict[str, Any],
) -> tuple[UploadWorkflow, WorkflowState] | None:
    workflow = await durable_operations().get(workflow_id)
    if workflow is None:
        return None
    attributes = workflow.attributes or {}
    required = {**expected_attributes, "object_key": object_key_value}
    if workflow.name != workflow_name or any(
        attributes.get(key) != value for key, value in required.items()
    ):
        raise ValidationFailure("upload operation_id was already used for a different request")
    return UploadWorkflow(workflow_id, object_id, object_key_value), workflow.state


async def _complete_existing_upload(
    existing: tuple[UploadWorkflow, WorkflowState],
    *,
    object_key_value: str,
    object_id: UUID,
) -> UploadWorkflow:
    """Resume a previously-enqueued upload without replacing its object."""
    result, state = existing
    if state in _TERMINAL_UPLOAD_STATES:
        return result
    metadata = await get_object_store().head(object_key_value)
    await durable_operations().send(
        result.workflow_id,
        {"status": "complete", "key": object_key_value, "size": metadata.size},
        topic=UPLOAD_COMPLETE_TOPIC,
        idempotency_key=f"upload-complete:{object_id}",
    )
    return result


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
        lifecycle_fence=item.lifecycle_fence,
    )
    db.add(revision)
    await db.flush()
    revision.operation_id = f"revision:{revision.id}"
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
        select(ImportBatch.records).where(
            ImportBatch.file_format == "pdf",
            ImportBatch.status.not_in(ImportBatch.TERMINAL_STATUSES),
        )
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
    operation_id: str | UUID | None = None,
) -> UploadWorkflow:
    from quirebase.operations.settings import get_effective_setting

    item = await require_editable_item(db, user, item_id)
    lifecycle_fence = item.lifecycle_fence
    if not filename or not filename.lower().endswith(".pdf"):
        raise UnsupportedMediaType("a PDF file is required")
    if max_bytes is None:
        max_bytes = await get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
    await db.commit()
    upload_operation_id = _upload_identity(operation_id)
    original_name = Path(filename).name
    revision_id = _upload_object_id("revision", user.id, item_id, upload_operation_id)
    thumbnail_object_id = _upload_object_id(
        "revision-thumbnail", user.id, item_id, upload_operation_id
    )
    revision_key = object_key(revision_id, ObjectSuffix.PDF)
    thumbnail_key = object_key(thumbnail_object_id, ObjectSuffix.PNG)
    workflow_id = f"upload-revision:{user.id}:{item_id}:{upload_operation_id}"
    attributes = {
        "capability": "documents",
        "operation": "upload_revision",
        "owner_id": user.id,
        "item_id": item_id,
        "revision_id": str(revision_id),
        "original_name": original_name,
        "lifecycle_fence": lifecycle_fence,
        "object_key": revision_key,
        "object_keys": [revision_key, thumbnail_key],
    }
    existing = await _existing_upload_workflow(
        workflow_id, REVISION_UPLOAD_WORKFLOW, revision_id, revision_key, attributes
    )
    workflow_preexisting = existing is not None
    if existing is not None:
        existing_result, existing_state = existing
        if existing_state in _TERMINAL_UPLOAD_STATES:
            return existing_result
    else:
        try:
            await durable_operations().enqueue(
                REVISION_UPLOAD_WORKFLOW,
                item_id,
                user.id,
                str(revision_id),
                str(revision_id),
                str(thumbnail_object_id),
                original_name,
                upload_operation_id,
                lifecycle_fence,
                queue_name=UPLOAD_QUEUE,
                workflow_id=workflow_id,
                deduplication_id=workflow_id,
                duplication_policy="return-existing",
                attributes=attributes,
            )
            # DBOS may return an existing workflow under the return-existing
            # duplication policy. Resolve it before touching the deterministic
            # object key so retries never blindly replace the first payload.
            existing = await _existing_upload_workflow(
                workflow_id, REVISION_UPLOAD_WORKFLOW, revision_id, revision_key, attributes
            )
            if existing is not None:
                existing_result, existing_state = existing
                if existing_state in _TERMINAL_UPLOAD_STATES:
                    return existing_result
        except Exception:
            existing = await _existing_upload_workflow(
                workflow_id, REVISION_UPLOAD_WORKFLOW, revision_id, revision_key, attributes
            )
            if existing is not None:
                workflow_preexisting = True
                existing_result, existing_state = existing
                if existing_state in _TERMINAL_UPLOAD_STATES:
                    return existing_result
            else:
                raise
    try:
        stored = await get_object_store().put_object(
            revision_id,
            ObjectSuffix.PDF,
            source,
            max_bytes=max_bytes,
            required_prefix=b"%PDF-",
            overwrite=False,
        )
        await durable_operations().send(
            workflow_id,
            {"status": "complete", "key": stored.key, "size": stored.size},
            topic=UPLOAD_COMPLETE_TOPIC,
            idempotency_key=f"upload-complete:{revision_id}",
        )
    except FileExistsError:
        existing = await _existing_upload_workflow(
            workflow_id, REVISION_UPLOAD_WORKFLOW, revision_id, revision_key, attributes
        )
        if existing is None:
            raise
        return await _complete_existing_upload(
            existing, object_key_value=revision_key, object_id=revision_id
        )
    except BaseException as error:
        if not workflow_preexisting:
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
    locked_item_id = await db.scalar(select(Item.id).where(Item.id == item_id).with_for_update())
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
    operation_id: str | UUID | None = None,
) -> UploadWorkflow:
    from quirebase.operations.settings import get_effective_setting

    if not filename:
        raise ResourceUnavailable("item not accessible or filename missing")
    item = await require_editable_item(db, user, item_id)
    lifecycle_fence = item.lifecycle_fence
    if max_bytes is None:
        max_bytes = await get_effective_setting(
            db, "max_attachment_bytes", get_settings().max_attachment_bytes
        )
    await db.commit()
    if role == AttachmentRole.graphical_abstract and content_type not in (
        GRAPHICAL_ABSTRACT_MEDIA_TYPES
    ):
        raise ValidationFailure("graphical abstract must be a PNG, JPEG, WebP, or GIF image")
    upload_operation_id = _upload_identity(operation_id)
    original_name = Path(filename).name
    attachment_id = _upload_object_id("attachment", user.id, item_id, upload_operation_id)
    attachment_key = object_key(attachment_id, ObjectSuffix.BINARY)
    workflow_id = f"upload-attachment:{user.id}:{item_id}:{upload_operation_id}"
    attributes = {
        "capability": "documents",
        "operation": "upload_attachment",
        "owner_id": user.id,
        "item_id": item_id,
        "attachment_id": str(attachment_id),
        "original_name": original_name,
        "content_type": content_type,
        "role": role.value if role else None,
        "lifecycle_fence": lifecycle_fence,
        "object_key": attachment_key,
        "object_keys": [attachment_key],
    }
    existing = await _existing_upload_workflow(
        workflow_id, ATTACHMENT_UPLOAD_WORKFLOW, attachment_id, attachment_key, attributes
    )
    workflow_preexisting = existing is not None
    if existing is not None:
        existing_result, existing_state = existing
        if existing_state in _TERMINAL_UPLOAD_STATES:
            return existing_result
    else:
        try:
            await durable_operations().enqueue(
                ATTACHMENT_UPLOAD_WORKFLOW,
                item_id,
                user.id,
                str(attachment_id),
                str(attachment_id),
                original_name,
                content_type,
                role.value if role else None,
                upload_operation_id,
                lifecycle_fence,
                queue_name=UPLOAD_QUEUE,
                workflow_id=workflow_id,
                deduplication_id=workflow_id,
                duplication_policy="return-existing",
                attributes=attributes,
            )
            existing = await _existing_upload_workflow(
                workflow_id, ATTACHMENT_UPLOAD_WORKFLOW, attachment_id, attachment_key, attributes
            )
            if existing is not None:
                existing_result, existing_state = existing
                if existing_state in _TERMINAL_UPLOAD_STATES:
                    return existing_result
        except Exception:
            existing = await _existing_upload_workflow(
                workflow_id, ATTACHMENT_UPLOAD_WORKFLOW, attachment_id, attachment_key, attributes
            )
            if existing is not None:
                workflow_preexisting = True
                existing_result, existing_state = existing
                if existing_state in _TERMINAL_UPLOAD_STATES:
                    return existing_result
            else:
                raise
    try:
        stored = await get_object_store().put_object(
            attachment_id, ObjectSuffix.BINARY, source, max_bytes=max_bytes, overwrite=False
        )
        await durable_operations().send(
            workflow_id,
            {"status": "complete", "key": stored.key, "size": stored.size},
            topic=UPLOAD_COMPLETE_TOPIC,
            idempotency_key=f"upload-complete:{attachment_id}",
        )
    except FileExistsError:
        existing = await _existing_upload_workflow(
            workflow_id, ATTACHMENT_UPLOAD_WORKFLOW, attachment_id, attachment_key, attributes
        )
        if existing is None:
            raise
        return await _complete_existing_upload(
            existing, object_key_value=attachment_key, object_id=attachment_id
        )
    except BaseException as error:
        if not workflow_preexisting:
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
    await lock_item_edit_authority(db, user, item_id)
    revision = await db.scalar(
        select(FileRevision).where(FileRevision.id == revision_id).with_for_update()
    )
    if revision is None or revision.item_id != item_id:
        raise ResourceNotFound("file revision not found")
    object_key = revision.object_key
    thumbnail_key = revision.thumbnail_object_key
    await db.delete(revision)
    await db.flush()
    # Deleting a revision changes the Item's indexed and recommended content.
    # Advance both source sequences in the same transaction so an in-flight
    # recommendation generated from the deleted PDF fails its sequence check
    # instead of publishing candidates for content that no longer exists.
    await db.execute(
        update(Item)
        .where(Item.id == item_id, Item.lifecycle_state == "active")
        .values(
            aggregate_sequence=Item.aggregate_sequence + 1,
            recommendation_sequence=Item.recommendation_sequence + 1,
        )
    )
    await enqueue_search_changed(db, item_id)
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
    await enqueue_object_cleanup(
        db,
        (object_key, thumbnail_key or ""),
        owner_id=user.id,
        operation="file_revision.delete",
        target_id=revision.id,
    )
    await db.commit()


async def delete_attachment(db: AsyncSession, user: User, item_id: str, attachment_id: str) -> None:
    await lock_item_edit_authority(db, user, item_id)
    attachment = await db.scalar(
        select(Attachment).where(Attachment.id == attachment_id).with_for_update()
    )
    if attachment is None or attachment.item_id != item_id:
        raise ResourceNotFound("attachment not found")
    object_key = attachment.object_key
    await db.delete(attachment)
    await db.flush()
    await db.execute(
        update(Item)
        .where(Item.id == item_id, Item.lifecycle_state == "active")
        .values(aggregate_sequence=Item.aggregate_sequence + 1)
    )
    await enqueue_search_changed(db, item_id)
    record_event(db, user.id, "attachment.delete", "attachment", attachment.id)
    await enqueue_object_cleanup(
        db,
        (object_key,),
        owner_id=user.id,
        operation="attachment.delete",
        target_id=attachment.id,
    )
    await db.commit()


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
