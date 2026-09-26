from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TypedDict, cast
from uuid import UUID

from dbos import DBOS
from sqlalchemy import and_, or_, select

from quirebase.access import (
    Capability,
    require_project_context,
    require_workspace_capability,
)
from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal
from quirebase.core.storage import ObjectSuffix, get_object_store, object_key
from quirebase.core.timezones import annotation_export_timezone
from quirebase.core.workflows import LIBRARY_QUEUE, ads, enqueue_child_workflow
from quirebase.documents.events import FILE_REVISION_CHANGED_WORKFLOW, OBJECT_CLEANUP_WORKFLOW
from quirebase.models import (
    AnnotationScope,
    Attachment,
    AttachmentRole,
    ExportArtifact,
    FileRevision,
    FileRevisionProcessingState,
    Item,
    PdfAnnotation,
    ProjectItem,
    User,
    Workspace,
)
from quirebase.search import search_index

from .pdf import create_thumbnail, export_annotations, inspect_pdf, validate_pdf_container

REVISION_UPLOAD_WORKFLOW = "documents.upload_revision"
ATTACHMENT_UPLOAD_WORKFLOW = "documents.upload_attachment"
ANNOTATION_EXPORT_WORKFLOW = "documents.export_annotations"
IMPORTED_REVISION_INSPECTION_WORKFLOW = "documents.inspect_imported_revision"

_MAX_THUMBNAIL_BYTES = 32 * 1024 * 1024


async def _lock_upload_authority(
    db,
    actor_id: str,
    workspace_id: str,
    item_id: str,
    *,
    role: AttachmentRole | None = None,
) -> tuple[User, Item]:
    actor = await db.scalar(
        select(User).where(User.id == actor_id, User.active.is_(True)).with_for_update(read=True)
    )
    if actor is None:
        raise ValueError("Item is no longer writable")
    workspace = await db.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    if workspace is None:
        raise ValueError("Workspace is no longer writable")
    lock = (
        select(Item)
        .where(Item.id == item_id, Item.workspace_id == workspace_id)
        .execution_options(populate_existing=True)
    )
    if role is AttachmentRole.graphical_abstract:
        lock = lock.with_for_update(key_share=True)
    else:
        lock = lock.with_for_update(read=True, key_share=True)
    item = await db.scalar(lock)
    if item is None:
        raise ValueError("Item is no longer writable")
    try:
        await require_workspace_capability(db, actor, workspace_id, Capability.files_manage)
    except Exception as error:
        raise ValueError("Item is no longer writable") from error
    return actor, item


class UploadReceipt(TypedDict):
    status: Literal["complete"]
    key: str
    size: int


class PdfInspectionData(TypedDict):
    thumbnail_object_key: str
    thumbnail_size: int
    size: int
    page_count: int
    full_text: str
    page_geometry: str


class PdfInspection(PdfInspectionData):
    revision_id: str


class UploadedPdfInspection(PdfInspection):
    object_key: str


class RevisionWorkflowResult(TypedDict):
    revision_id: str
    item_id: str


class ImportedRevisionWorkflowResult(TypedDict):
    revision_id: str
    actor_id: str
    workspace_id: str


class ValidatedAttachment(TypedDict):
    object_key: str
    size: int


class AttachmentWorkflowResult(TypedDict):
    attachment_id: str
    item_id: str


class AnnotationExportResult(TypedDict):
    filename: str
    object_key: str
    size_bytes: int
    revision_id: str
    project_id: str | None
    project_item_id: str | None


def _require_upload_receipt(value: Any, *, description: str) -> UploadReceipt:
    if not isinstance(value, dict) or value.get("status") != "complete":
        raise TimeoutError(f"{description} upload did not complete")
    key = value.get("key")
    size = value.get("size")
    if not isinstance(key, str) or not isinstance(size, int) or isinstance(size, bool):
        raise TypeError(f"invalid {description} upload receipt")
    return cast("UploadReceipt", value)


@DBOS.step(retries_allowed=True, max_attempts=3)
async def remove_owned_object(key: str) -> None:
    await get_object_store().delete(key)


@DBOS.step(retries_allowed=True, max_attempts=3)
async def delete_unreferenced_objects_step(
    actor_id: str,
    workspace_id: str,
    object_keys: list[str],
    ignore_workflow_id: str | None = None,
) -> list[str]:
    from quirebase.documents.revisions import delete_unreferenced_objects

    async with AsyncSessionLocal() as db:
        # The resource deletion was authorized in the enqueue transaction. Cleanup
        # must survive later membership and Workspace lifecycle changes; the
        # reference check below remains the authority for deleting each key.
        return list(
            await delete_unreferenced_objects(
                db, object_keys, ignore_workflow_id=ignore_workflow_id
            )
        )


@DBOS.workflow(name=OBJECT_CLEANUP_WORKFLOW)
async def cleanup_objects_workflow(
    actor_id: str,
    workspace_id: str,
    object_keys: list[str],
    ignore_workflow_id: str | None = None,
) -> list[str]:
    return await delete_unreferenced_objects_step(
        actor_id, workspace_id, object_keys, ignore_workflow_id
    )


async def _inspect_pdf_object(
    object_key_value: str,
    thumbnail_object_id: str,
    *,
    expected_size: int | None = None,
) -> PdfInspectionData:
    metadata = await get_object_store().head(object_key_value)
    if expected_size is not None and metadata.size != expected_size:
        raise ValueError("uploaded object size mismatch")
    thumbnail_key = object_key(UUID(thumbnail_object_id), ObjectSuffix.PNG)
    async with get_object_store().materialize(object_key_value) as source:
        await asyncio.to_thread(validate_pdf_container, source)
        page_count, text, geometry = await asyncio.to_thread(inspect_pdf, source)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
            thumbnail_path = Path(temporary.name)
        try:
            await asyncio.to_thread(create_thumbnail, source, thumbnail_path)
            thumbnail = await get_object_store().put_object(
                UUID(thumbnail_object_id),
                ObjectSuffix.PNG,
                thumbnail_path,
                max_bytes=_MAX_THUMBNAIL_BYTES,
            )
        finally:
            await asyncio.to_thread(thumbnail_path.unlink, missing_ok=True)
    return {
        "thumbnail_object_key": thumbnail_key,
        "thumbnail_size": thumbnail.size,
        "size": metadata.size,
        "page_count": page_count,
        "full_text": text,
        "page_geometry": json.dumps(geometry, separators=(",", ":")),
    }


@DBOS.step(retries_allowed=True, max_attempts=3)
async def inspect_uploaded_pdf(
    revision_id: str,
    object_id: str,
    thumbnail_object_id: str,
    receipt: UploadReceipt,
) -> UploadedPdfInspection:
    expected_key = object_key(UUID(object_id), ObjectSuffix.PDF)
    if receipt["key"] != expected_key:
        raise ValueError("upload receipt does not own the expected object")
    inspected = await _inspect_pdf_object(
        expected_key,
        thumbnail_object_id,
        expected_size=receipt["size"],
    )
    return {
        "revision_id": revision_id,
        "object_key": expected_key,
        **inspected,
    }


@ads.transaction()
async def commit_uploaded_revision(
    actor_id: str,
    workspace_id: str,
    item_id: str,
    filename: str,
    inspected: UploadedPdfInspection,
) -> RevisionWorkflowResult:
    db = ads.sql_session()
    _actor, _item = await _lock_upload_authority(db, actor_id, workspace_id, item_id)
    existing = await db.get(FileRevision, inspected["revision_id"])
    if existing is not None:
        if existing.workspace_id != workspace_id or existing.item_id != item_id:
            raise ValueError("uploaded revision does not belong to the requested item")
        if existing.processing_state == FileRevisionProcessingState.pending:
            existing.object_key = inspected["object_key"]
            existing.thumbnail_object_key = inspected["thumbnail_object_key"]
            existing.thumbnail_size = inspected["thumbnail_size"]
            existing.size = inspected["size"]
            existing.page_count = inspected["page_count"]
            existing.page_geometry = inspected["page_geometry"]
            existing.full_text = inspected["full_text"]
            existing.processing_state = FileRevisionProcessingState.ready
            await search_index(db).index_revision(db, existing.id)
        return {"revision_id": existing.id, "item_id": existing.item_id}
    revision = FileRevision(
        id=inspected["revision_id"],
        workspace_id=workspace_id,
        item_id=item_id,
        object_key=inspected["object_key"],
        thumbnail_object_key=inspected["thumbnail_object_key"],
        thumbnail_size=inspected["thumbnail_size"],
        size=inspected["size"],
        original_name=Path(filename).name[:255],
        page_count=inspected["page_count"],
        page_geometry=inspected["page_geometry"],
        full_text=inspected["full_text"],
        processing_state=FileRevisionProcessingState.ready,
        created_by=actor_id,
    )
    db.add(revision)
    await db.flush()
    await search_index(db).index_revision(db, revision.id)
    record_event(
        db,
        actor_id,
        "pdf.upload",
        "file_revision",
        revision.id,
        workspace_id=workspace_id,
        authorization_capability=Capability.files_manage.value,
    )
    return {"revision_id": revision.id, "item_id": item_id}


async def _enqueue_file_revision_changed(
    revision_id: str, actor_id: str, workspace_id: str, item_id: str
) -> str:
    return await enqueue_child_workflow(
        FILE_REVISION_CHANGED_WORKFLOW,
        actor_id,
        workspace_id,
        revision_id,
        item_id,
        queue_name=LIBRARY_QUEUE,
        workflow_id=f"file-revision-changed:{revision_id}",
    )


@DBOS.workflow(name=REVISION_UPLOAD_WORKFLOW)
async def upload_revision_workflow(
    actor_id: str,
    workspace_id: str,
    item_id: str,
    revision_id: str,
    object_id: str,
    thumbnail_object_id: str,
    filename: str,
) -> RevisionWorkflowResult:
    key = object_key(UUID(object_id), ObjectSuffix.PDF)
    thumbnail_key = object_key(UUID(thumbnail_object_id), ObjectSuffix.PNG)
    receipt = await DBOS.recv_async(
        "upload-complete", timeout_seconds=get_settings().workflow_upload_timeout_seconds
    )
    committed = False
    try:
        completed_receipt = _require_upload_receipt(receipt, description="PDF")
        inspected = await inspect_uploaded_pdf(
            revision_id, object_id, thumbnail_object_id, completed_receipt
        )
        result = await commit_uploaded_revision(
            actor_id, workspace_id, item_id, filename, inspected
        )
        committed = True
        await _enqueue_file_revision_changed(revision_id, actor_id, workspace_id, item_id)
        return result
    except BaseException:
        if not committed:
            await remove_owned_object(key)
            await remove_owned_object(thumbnail_key)
        raise


@DBOS.workflow(name=IMPORTED_REVISION_INSPECTION_WORKFLOW)
async def inspect_imported_revision_workflow(
    actor_id: str,
    workspace_id: str,
    revision_id: str,
    object_key_value: str,
    thumbnail_object_id: str,
) -> ImportedRevisionWorkflowResult:
    thumbnail_key = object_key(UUID(thumbnail_object_id), ObjectSuffix.PNG)
    committed = False
    try:
        inspected = await inspect_imported_pdf(revision_id, object_key_value, thumbnail_object_id)
        result = await commit_imported_revision(actor_id, workspace_id, inspected)
        committed = True
        await _enqueue_file_revision_changed(revision_id, actor_id, workspace_id, result["item_id"])
        return {
            "revision_id": revision_id,
            "actor_id": actor_id,
            "workspace_id": workspace_id,
        }
    except BaseException:
        if not committed:
            await remove_owned_object(thumbnail_key)
        raise


@DBOS.step(retries_allowed=True, max_attempts=3)
async def inspect_imported_pdf(
    revision_id: str, object_key_value: str, thumbnail_object_id: str
) -> PdfInspection:
    inspected = await _inspect_pdf_object(object_key_value, thumbnail_object_id)
    return {
        "revision_id": revision_id,
        **inspected,
    }


@ads.transaction()
async def commit_imported_revision(
    actor_id: str, workspace_id: str, inspected: PdfInspection
) -> RevisionWorkflowResult:
    db = ads.sql_session()
    revision = await db.get(FileRevision, inspected["revision_id"])
    if revision is None or revision.workspace_id != workspace_id:
        raise ValueError("imported revision no longer exists")
    await _lock_upload_authority(db, actor_id, workspace_id, revision.item_id)
    revision = await db.get(FileRevision, inspected["revision_id"], populate_existing=True)
    if revision is None or revision.workspace_id != workspace_id:
        raise ValueError("imported revision no longer exists")
    if revision.processing_state == FileRevisionProcessingState.pending:
        revision.thumbnail_object_key = inspected["thumbnail_object_key"]
        revision.thumbnail_size = inspected["thumbnail_size"]
        revision.size = inspected["size"]
        revision.page_count = inspected["page_count"]
        revision.full_text = inspected["full_text"]
        revision.page_geometry = inspected["page_geometry"]
        revision.processing_state = FileRevisionProcessingState.ready
        await search_index(db).index_revision(db, revision.id)
    return {"revision_id": revision.id, "item_id": revision.item_id}


def _is_image_header(header: bytes, content_type: str) -> bool:
    return {
        "image/gif": header.startswith((b"GIF87a", b"GIF89a")),
        "image/jpeg": header.startswith(b"\xff\xd8\xff"),
        "image/png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
    }.get(content_type, False)


@DBOS.step(retries_allowed=True, max_attempts=3)
async def validate_attachment_upload(
    object_id: str,
    content_type: str,
    graphical_abstract: bool,
    receipt: UploadReceipt,
) -> ValidatedAttachment:
    key = object_key(UUID(object_id), ObjectSuffix.BINARY)
    if receipt["key"] != key:
        raise ValueError("upload receipt does not own the expected object")
    metadata = await get_object_store().head(key)
    if metadata.size != receipt["size"]:
        raise ValueError("uploaded object size mismatch")
    if graphical_abstract:
        if metadata.size <= 0:
            raise ValueError("graphical abstract content does not match its image type")
        response = await get_object_store().get_range(key, 0, min(12, metadata.size))
        header = b"".join([bytes(chunk) async for chunk in response.body])
        if not _is_image_header(header, content_type):
            raise ValueError("graphical abstract content does not match its image type")
    return {"object_key": key, "size": metadata.size}


@ads.transaction()
async def commit_uploaded_attachment(
    actor_id: str,
    workspace_id: str,
    item_id: str,
    attachment_id: str,
    filename: str,
    content_type: str,
    role_value: str | None,
    receipt: ValidatedAttachment,
) -> AttachmentWorkflowResult:
    db = ads.sql_session()
    role = AttachmentRole(role_value) if role_value else None
    _actor, _item = await _lock_upload_authority(db, actor_id, workspace_id, item_id, role=role)
    existing = await db.get(Attachment, attachment_id)
    if existing is not None:
        if existing.workspace_id != workspace_id or existing.item_id != item_id:
            raise ValueError("uploaded attachment does not belong to the requested item")
        return {"attachment_id": existing.id, "item_id": existing.item_id}
    if role is not None:
        current = await db.scalar(
            select(Attachment).where(
                Attachment.workspace_id == workspace_id,
                Attachment.item_id == item_id,
                Attachment.role == role,
            )
        )
        if current is not None:
            current.role = None
            await db.flush()
    attachment = Attachment(
        id=attachment_id,
        workspace_id=workspace_id,
        item_id=item_id,
        object_key=receipt["object_key"],
        size=receipt["size"],
        mime_type=content_type[:100],
        original_name=Path(filename).name[:255],
        role=role,
        created_by=actor_id,
    )
    db.add(attachment)
    record_event(
        db,
        actor_id,
        "attachment.upload",
        "attachment",
        attachment.id,
        workspace_id=workspace_id,
        authorization_capability=Capability.files_manage.value,
    )
    return {"attachment_id": attachment.id, "item_id": item_id}


@DBOS.workflow(name=ATTACHMENT_UPLOAD_WORKFLOW)
async def upload_attachment_workflow(
    actor_id: str,
    workspace_id: str,
    item_id: str,
    attachment_id: str,
    object_id: str,
    filename: str,
    content_type: str,
    role_value: str | None,
) -> AttachmentWorkflowResult:
    key = object_key(UUID(object_id), ObjectSuffix.BINARY)
    receipt = await DBOS.recv_async(
        "upload-complete", timeout_seconds=get_settings().workflow_upload_timeout_seconds
    )
    try:
        completed_receipt = _require_upload_receipt(receipt, description="attachment")
        validated = await validate_attachment_upload(
            object_id,
            content_type,
            role_value == AttachmentRole.graphical_abstract.value,
            completed_receipt,
        )
        return await commit_uploaded_attachment(
            actor_id,
            workspace_id,
            item_id,
            attachment_id,
            filename,
            content_type,
            role_value,
            validated,
        )
    except BaseException:
        await remove_owned_object(key)
        raise


@DBOS.step(retries_allowed=True, max_attempts=3)
async def build_annotation_export(
    actor_id: str,
    workspace_id: str,
    revision_id: str,
    object_id: str,
    project_id: str | None,
    include_private: bool,
    timezone: str | None,
) -> AnnotationExportResult:
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, actor_id)
        if actor is None:
            raise PermissionError("actor no longer exists")
        await require_workspace_capability(db, actor, workspace_id, Capability.workspace_export)
        revision = await db.scalar(
            select(FileRevision).where(
                FileRevision.id == revision_id,
                FileRevision.workspace_id == workspace_id,
            )
        )
        if revision is None:
            raise ValueError("revision no longer exists")
        scopes = []
        project_item_id: str | None = None
        if include_private:
            scopes.append(
                and_(
                    PdfAnnotation.scope == AnnotationScope.private,
                    PdfAnnotation.author_id == actor_id,
                )
            )
        if project_id:
            await require_project_context(
                db, actor, workspace_id, project_id, Capability.workspace_export
            )
            assignment = await db.scalar(
                select(ProjectItem).where(
                    ProjectItem.workspace_id == workspace_id,
                    ProjectItem.project_id == project_id,
                    ProjectItem.item_id == revision.item_id,
                )
            )
            if assignment is None:
                raise PermissionError("project assignment no longer exists")
            project_item_id = assignment.id
            scopes.append(
                and_(
                    PdfAnnotation.scope == AnnotationScope.project,
                    PdfAnnotation.project_item_id == assignment.id,
                )
            )
        records = (
            []
            if not scopes
            else list(
                (
                    await db.scalars(
                        select(PdfAnnotation).where(
                            PdfAnnotation.file_revision_id == revision.id,
                            PdfAnnotation.workspace_id == workspace_id,
                            PdfAnnotation.deleted_at.is_(None),
                            PdfAnnotation.hidden_at.is_(None),
                            PdfAnnotation.archived_at.is_(None),
                            or_(*scopes),
                        )
                    )
                ).all()
            )
        )
        author_rows = (
            await db.execute(
                select(User.id, User.username).where(
                    User.id.in_({record.author_id for record in records})
                )
            )
        ).all()
        author_names = {row[0]: row[1] for row in author_rows}
        revision_key = revision.object_key
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output:
        output_path = Path(output.name)
    try:
        async with get_object_store().materialize(revision_key) as source:
            await asyncio.to_thread(
                export_annotations,
                source,
                output_path,
                records,
                author_names=author_names,
                display_timezone=annotation_export_timezone(timezone),
            )
        stored = await get_object_store().put_object(
            UUID(object_id),
            ObjectSuffix.PDF,
            output_path,
            max_bytes=get_settings().max_pdf_bytes,
        )
        return {
            "filename": f"{object_id}.pdf",
            "object_key": stored.key,
            "size_bytes": stored.size,
            "revision_id": revision_id,
            "project_id": project_id,
            "project_item_id": project_item_id,
        }
    finally:
        await asyncio.to_thread(output_path.unlink, missing_ok=True)


@DBOS.workflow(name=ANNOTATION_EXPORT_WORKFLOW)
async def annotation_export_workflow(
    actor_id: str,
    workspace_id: str,
    revision_id: str,
    object_id: str,
    project_id: str | None,
    include_private: bool,
    timezone: str | None,
) -> AnnotationExportResult:
    result: AnnotationExportResult | None = None
    try:
        result = await build_annotation_export(
            actor_id,
            workspace_id,
            revision_id,
            object_id,
            project_id,
            include_private,
            timezone,
        )
        workflow_id = DBOS.workflow_id
        if workflow_id is None:
            raise RuntimeError("annotation export must run within a DBOS workflow")
        await record_annotation_export_artifact(
            workflow_id, actor_id, workspace_id, project_id, result
        )
        return result
    except BaseException:
        if result is not None:
            await remove_owned_object(result["object_key"])
        raise


@ads.transaction(isolation_level="READ COMMITTED")
async def record_annotation_export_artifact(
    workflow_id: str,
    actor_id: str,
    workspace_id: str,
    project_id: str | None,
    result: AnnotationExportResult,
) -> None:
    from quirebase.operations.settings import get_effective_setting

    db = ads.sql_session()
    if await db.get(ExportArtifact, workflow_id) is not None:
        return
    workspace = await db.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    if workspace is None:
        raise PermissionError("Workspace no longer exists")
    actor = await db.get(User, actor_id)
    if actor is None:
        raise PermissionError("actor no longer exists")
    await require_workspace_capability(db, actor, workspace_id, Capability.workspace_export)
    revision = await db.scalar(
        select(FileRevision)
        .where(
            FileRevision.id == result["revision_id"],
            FileRevision.workspace_id == workspace_id,
        )
        .with_for_update(read=True, key_share=True)
    )
    if revision is None:
        raise ValueError("revision no longer exists")
    if result["project_id"] != project_id or (
        project_id is None and result["project_item_id"] is not None
    ):
        raise PermissionError("project assignment no longer exists")
    if project_id:
        await require_project_context(
            db, actor, workspace_id, project_id, Capability.workspace_export
        )
        if result["project_item_id"] is None:
            raise PermissionError("project assignment no longer exists")
        assignment = await db.scalar(
            select(ProjectItem)
            .where(
                ProjectItem.id == result["project_item_id"],
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.project_id == project_id,
                ProjectItem.item_id == revision.item_id,
            )
            .with_for_update(read=True, key_share=True)
        )
        if assignment is None:
            raise PermissionError("project assignment no longer exists")
    ttl_hours = await get_effective_setting(db, "export_ttl_hours", get_settings().export_ttl_hours)
    db.add(
        ExportArtifact(
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            object_key=result["object_key"],
            filename=result["filename"],
            size=result["size_bytes"],
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        )
    )
