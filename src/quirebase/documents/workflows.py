from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TypedDict, cast
from uuid import UUID, uuid4

from dbos import DBOS
from sqlalchemy import and_, or_, select, update

from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal
from quirebase.core.errors import ValidationFailure
from quirebase.core.storage import ObjectSuffix, get_object_store, object_key
from quirebase.core.timezones import annotation_export_timezone
from quirebase.core.workflows import (
    DOCUMENT_CLEANUP_QUEUE,
    LIBRARY_QUEUE,
    ads,
    enqueue_child_workflow,
)
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
    PdfAnnotationMode,
    ProjectItem,
    ProjectMember,
    User,
)

from .pdf import create_thumbnail, export_annotations, inspect_pdf, validate_pdf_container
from .schemas import AnnotationCreate

REVISION_UPLOAD_WORKFLOW = "documents.upload_revision"
ATTACHMENT_UPLOAD_WORKFLOW = "documents.upload_attachment"
ANNOTATION_EXPORT_WORKFLOW = "documents.export_annotations"
IMPORTED_REVISION_INSPECTION_WORKFLOW = "documents.inspect_imported_revision"

_MAX_THUMBNAIL_BYTES = 32 * 1024 * 1024


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
    object_key: str
    source_object_key: str
    pdf_annotation_mode: str
    imported_annotations: list[dict[str, Any]]
    annotation_diagnostics: list[dict[str, Any]]


class PdfInspection(PdfInspectionData):
    revision_id: str


class UploadedPdfInspection(PdfInspection):
    pass


class RevisionWorkflowResult(TypedDict):
    revision_id: str
    item_id: str


class ImportedRevisionCommitResult(RevisionWorkflowResult):
    annotation_diagnostics: list[dict[str, Any]]


class ImportedRevisionWorkflowResult(TypedDict):
    revision_id: str
    owner_id: str
    annotation_diagnostics: list[dict[str, Any]]


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
    object_keys: list[str], ignore_workflow_id: str | None = None
) -> list[str]:
    from quirebase.documents.revisions import delete_unreferenced_objects

    async with AsyncSessionLocal() as db:
        return list(
            await delete_unreferenced_objects(
                db, object_keys, ignore_workflow_id=ignore_workflow_id
            )
        )


@DBOS.workflow(name=OBJECT_CLEANUP_WORKFLOW)
async def cleanup_objects_workflow(
    object_keys: list[str], ignore_workflow_id: str | None = None
) -> list[str]:
    return await delete_unreferenced_objects_step(object_keys, ignore_workflow_id)


async def _inspect_pdf_object(
    object_key_value: str,
    thumbnail_object_id: str,
    *,
    expected_size: int | None = None,
    annotation_mode: PdfAnnotationMode | str = PdfAnnotationMode.preserve,
    derived_object_id: str | None = None,
    max_pdf_bytes: int | None = None,
) -> PdfInspectionData:
    annotation_mode = PdfAnnotationMode(annotation_mode)
    metadata = await get_object_store().head(object_key_value)
    if expected_size is not None and metadata.size != expected_size:
        raise ValueError("uploaded object size mismatch")
    thumbnail_key = object_key(UUID(thumbnail_object_id), ObjectSuffix.PNG)
    imported_annotations: list[dict[str, Any]] = []
    annotation_diagnostics: list[dict[str, Any]] = []
    derived_key = object_key_value
    pdf_size = metadata.size
    async with get_object_store().materialize(object_key_value) as source:
        await asyncio.to_thread(validate_pdf_container, source)
        if annotation_mode is PdfAnnotationMode.import_:
            from .pdf import parse_pdf_annotations

            imported_annotations, annotation_diagnostics = await asyncio.to_thread(
                parse_pdf_annotations, source
            )
        if annotation_mode is not PdfAnnotationMode.preserve:
            from .pdf import strip_native_annotations

            if not derived_object_id:
                raise ValueError("derived PDF object id is required for annotation stripping")
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as derived:
                derived_path = Path(derived.name)
            try:
                await asyncio.to_thread(strip_native_annotations, source, derived_path)
                stored = await get_object_store().put_object(
                    UUID(derived_object_id),
                    ObjectSuffix.PDF,
                    derived_path,
                    max_bytes=(
                        max_pdf_bytes if max_pdf_bytes is not None else get_settings().max_pdf_bytes
                    ),
                )
                derived_key = stored.key
                pdf_size = stored.size
            finally:
                await asyncio.to_thread(derived_path.unlink, missing_ok=True)
        inspection_source = source
        if derived_key != object_key_value:
            async with get_object_store().materialize(derived_key) as derived_source:
                page_count, text, geometry = await asyncio.to_thread(inspect_pdf, derived_source)
                inspection_source = derived_source
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
                    thumbnail_path = Path(temporary.name)
                try:
                    await asyncio.to_thread(create_thumbnail, inspection_source, thumbnail_path)
                    thumbnail = await get_object_store().put_object(
                        UUID(thumbnail_object_id),
                        ObjectSuffix.PNG,
                        thumbnail_path,
                        max_bytes=_MAX_THUMBNAIL_BYTES,
                    )
                finally:
                    await asyncio.to_thread(thumbnail_path.unlink, missing_ok=True)
        else:
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
        "size": pdf_size,
        "page_count": page_count,
        "full_text": text,
        "page_geometry": json.dumps(geometry, separators=(",", ":")),
        "object_key": derived_key,
        "source_object_key": object_key_value,
        "pdf_annotation_mode": annotation_mode.value,
        "imported_annotations": imported_annotations,
        "annotation_diagnostics": annotation_diagnostics,
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
    item_id: str,
    owner_id: str,
    filename: str,
    inspected: UploadedPdfInspection,
) -> RevisionWorkflowResult:
    db = ads.sql_session()
    existing = await db.get(FileRevision, inspected["revision_id"])
    if existing is not None:
        if existing.processing_state == FileRevisionProcessingState.pending:
            existing.object_key = inspected["object_key"]
            existing.thumbnail_object_key = inspected["thumbnail_object_key"]
            existing.thumbnail_size = inspected["thumbnail_size"]
            existing.size = inspected["size"]
            existing.page_count = inspected["page_count"]
            existing.page_geometry = inspected["page_geometry"]
            existing.full_text = inspected["full_text"]
            existing.processing_state = FileRevisionProcessingState.ready
        return {"revision_id": existing.id, "item_id": existing.item_id}
    if await db.get(Item, item_id) is None:
        raise ValueError("Item no longer exists")
    revision = FileRevision(
        id=inspected["revision_id"],
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
        created_by=owner_id,
    )
    db.add(revision)
    record_event(db, owner_id, "pdf.upload", "file_revision", revision.id)
    return {"revision_id": revision.id, "item_id": item_id}


async def _enqueue_file_revision_changed(
    revision_id: str, item_id: str, owner_id: str | None
) -> str:
    return await enqueue_child_workflow(
        FILE_REVISION_CHANGED_WORKFLOW,
        item_id,
        owner_id,
        queue_name=LIBRARY_QUEUE,
        workflow_id=f"file-revision-changed:{revision_id}",
    )


@DBOS.workflow(name=REVISION_UPLOAD_WORKFLOW)
async def upload_revision_workflow(
    item_id: str,
    owner_id: str,
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
        result = await commit_uploaded_revision(item_id, owner_id, filename, inspected)
        committed = True
        await _enqueue_file_revision_changed(revision_id, item_id, owner_id)
        return result
    except BaseException:
        if not committed:
            await remove_owned_object(key)
            await remove_owned_object(thumbnail_key)
        raise


@DBOS.workflow(name=IMPORTED_REVISION_INSPECTION_WORKFLOW)
async def inspect_imported_revision_workflow(
    revision_id: str,
    owner_id: str,
    object_key_value: str,
    thumbnail_object_id: str,
    derived_object_id: str | None = None,
    annotation_mode: str = PdfAnnotationMode.preserve.value,
    max_pdf_bytes: int | None = None,
) -> ImportedRevisionWorkflowResult:
    thumbnail_key = object_key(UUID(thumbnail_object_id), ObjectSuffix.PNG)
    committed = False
    try:
        if annotation_mode == PdfAnnotationMode.preserve.value and derived_object_id is None:
            inspected = await inspect_imported_pdf(
                revision_id, object_key_value, thumbnail_object_id
            )
        else:
            inspected = await inspect_imported_pdf(
                revision_id,
                object_key_value,
                thumbnail_object_id,
                annotation_mode=annotation_mode,
                derived_object_id=derived_object_id,
                max_pdf_bytes=max_pdf_bytes,
            )
        if annotation_mode == PdfAnnotationMode.import_.value:
            result = await commit_imported_revision(inspected, owner_id=owner_id)
        else:
            result = await commit_imported_revision(inspected)
        committed = True
        source_key = inspected.get("source_object_key")
        committed_key = inspected.get("object_key")
        if source_key and committed_key and source_key != committed_key:
            await enqueue_child_workflow(
                OBJECT_CLEANUP_WORKFLOW,
                [source_key],
                DBOS.workflow_id,
                queue_name=DOCUMENT_CLEANUP_QUEUE,
                workflow_id=f"inspect-imported-revision-cleanup:{revision_id}",
                attributes={
                    "capability": "documents",
                    "operation": "imported_revision_source_cleanup",
                    "object_keys": [source_key],
                    "revision_id": revision_id,
                },
            )
        await _enqueue_file_revision_changed(revision_id, result["item_id"], owner_id)
        return {
            "revision_id": revision_id,
            "owner_id": owner_id,
            "annotation_diagnostics": result.get(
                "annotation_diagnostics", inspected.get("annotation_diagnostics", [])
            ),
        }
    except BaseException:
        if not committed:
            await remove_owned_object(thumbnail_key)
            derived_key = (
                object_key(UUID(derived_object_id), ObjectSuffix.PDF) if derived_object_id else None
            )
            if derived_key and derived_key != object_key_value:
                await remove_owned_object(derived_key)
        raise


@DBOS.step(retries_allowed=True, max_attempts=3)
async def inspect_imported_pdf(
    revision_id: str,
    object_key_value: str,
    thumbnail_object_id: str,
    *,
    annotation_mode: str = PdfAnnotationMode.preserve.value,
    derived_object_id: str | None = None,
    max_pdf_bytes: int | None = None,
) -> PdfInspection:
    inspected = await _inspect_pdf_object(
        object_key_value,
        thumbnail_object_id,
        annotation_mode=annotation_mode,
        derived_object_id=derived_object_id,
        max_pdf_bytes=max_pdf_bytes,
    )
    return {
        "revision_id": revision_id,
        **inspected,
    }


@ads.transaction()
async def commit_imported_revision(
    inspected: PdfInspection, owner_id: str | None = None
) -> ImportedRevisionCommitResult:
    db = ads.sql_session()
    revision = await db.get(FileRevision, inspected["revision_id"])
    if revision is None:
        raise ValueError("imported revision no longer exists")
    if revision.processing_state == FileRevisionProcessingState.pending:
        source_object_key = revision.object_key
        revision.object_key = inspected.get("object_key", source_object_key)
        revision.thumbnail_object_key = inspected["thumbnail_object_key"]
        revision.thumbnail_size = inspected["thumbnail_size"]
        revision.size = inspected["size"]
        revision.page_count = inspected["page_count"]
        revision.full_text = inspected["full_text"]
        revision.page_geometry = inspected["page_geometry"]
        revision.processing_state = FileRevisionProcessingState.ready
        if inspected.get("pdf_annotation_mode") == PdfAnnotationMode.import_.value:
            annotation_rows = inspected.get("imported_annotations", [])
            valid_rows: list[tuple[AnnotationCreate, dict[str, Any]]] = []
            annotation_diagnostics = list(inspected.get("annotation_diagnostics", []))
            from .annotations import validate_payload

            for data in annotation_rows:
                try:
                    candidate = AnnotationCreate(
                        id=uuid4(),
                        revision_id=revision.id,
                        page_index=int(data["page_index"]),
                        kind=data["kind"],
                        scope=AnnotationScope.private,
                        body=data.get("body"),
                        selected_text=data.get("selected_text"),
                        payload=data["payload"],
                    )
                    validate_payload(candidate.page_index, candidate.payload, revision)
                except (TypeError, ValueError, KeyError, ValidationFailure) as error:
                    annotation_diagnostics.append({
                        "page": int(data.get("page_index", -1)) + 1
                        if isinstance(data, dict) and isinstance(data.get("page_index"), int)
                        else None,
                        "subtype": data.get("subtype") if isinstance(data, dict) else None,
                        "result": "skipped",
                        "reason": str(error),
                    })
                    continue
                valid_rows.append((candidate, data))
            for candidate, data in valid_rows:
                db.add(
                    PdfAnnotation(
                        id=str(candidate.id),
                        file_revision_id=revision.id,
                        page_index=candidate.page_index,
                        author_id=owner_id or data.get("author_id", ""),
                        kind=candidate.kind,
                        scope=AnnotationScope.private,
                        body=candidate.body,
                        selected_text=candidate.selected_text,
                        payload=candidate.payload.model_dump(mode="json"),
                    )
                )
            if owner_id:
                record_event(
                    db,
                    owner_id,
                    "pdf.import.annotations",
                    "file_revision",
                    revision.id,
                    detail={
                        "mode": PdfAnnotationMode.import_.value,
                        "imported_count": len(valid_rows),
                        "skipped_count": len(annotation_diagnostics),
                        "diagnostics": annotation_diagnostics,
                    },
                )
            return {
                "revision_id": revision.id,
                "item_id": revision.item_id,
                "annotation_diagnostics": annotation_diagnostics,
            }
    return {
        "revision_id": revision.id,
        "item_id": revision.item_id,
        "annotation_diagnostics": [],
    }


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
        response = await get_object_store().get_range(key, 0, min(12, metadata.size))
        header = b"".join([bytes(chunk) async for chunk in response.body])
        if not _is_image_header(header, content_type):
            raise ValueError("graphical abstract content does not match its image type")
    return {"object_key": key, "size": metadata.size}


@ads.transaction()
async def commit_uploaded_attachment(
    item_id: str,
    owner_id: str,
    attachment_id: str,
    filename: str,
    content_type: str,
    role_value: str | None,
    receipt: ValidatedAttachment,
) -> AttachmentWorkflowResult:
    db = ads.sql_session()
    existing = await db.get(Attachment, attachment_id)
    if existing is not None:
        return {"attachment_id": existing.id, "item_id": existing.item_id}
    if db.get_bind().dialect.name == "sqlite":
        locked = await db.scalar(
            update(Item)
            .where(Item.id == item_id)
            .values(updated_at=Item.updated_at)
            .returning(Item.id)
        )
    else:
        locked = await db.scalar(select(Item.id).where(Item.id == item_id).with_for_update())
    if locked is None:
        raise ValueError("Item no longer exists")
    role = AttachmentRole(role_value) if role_value else None
    if role is not None:
        current = await db.scalar(
            select(Attachment).where(Attachment.item_id == item_id, Attachment.role == role)
        )
        if current is not None:
            current.role = None
            await db.flush()
    attachment = Attachment(
        id=attachment_id,
        item_id=item_id,
        object_key=receipt["object_key"],
        size=receipt["size"],
        mime_type=content_type[:100],
        original_name=Path(filename).name[:255],
        role=role,
        created_by=owner_id,
    )
    db.add(attachment)
    record_event(db, owner_id, "attachment.upload", "attachment", attachment.id)
    return {"attachment_id": attachment.id, "item_id": item_id}


@DBOS.workflow(name=ATTACHMENT_UPLOAD_WORKFLOW)
async def upload_attachment_workflow(
    item_id: str,
    owner_id: str,
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
            item_id,
            owner_id,
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
    owner_id: str,
    revision_id: str,
    object_id: str,
    project_id: str | None,
    include_private: bool,
    timezone: str | None,
) -> AnnotationExportResult:
    async with AsyncSessionLocal() as db:
        revision = await db.get(FileRevision, revision_id)
        if revision is None:
            raise ValueError("revision no longer exists")
        scopes = []
        if include_private:
            scopes.append(
                and_(
                    PdfAnnotation.scope == AnnotationScope.private,
                    PdfAnnotation.author_id == owner_id,
                )
            )
        if project_id:
            membership = await db.get(ProjectMember, (project_id, owner_id))
            assignment = await db.get(ProjectItem, (project_id, revision.item_id))
            if membership is None or assignment is None:
                raise PermissionError("project membership no longer exists")
            scopes.append(
                and_(
                    PdfAnnotation.scope == AnnotationScope.project,
                    PdfAnnotation.project_id == project_id,
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
                            PdfAnnotation.deleted_at.is_(None),
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
        }
    finally:
        await asyncio.to_thread(output_path.unlink, missing_ok=True)


@DBOS.workflow(name=ANNOTATION_EXPORT_WORKFLOW)
async def annotation_export_workflow(
    owner_id: str,
    revision_id: str,
    object_id: str,
    project_id: str | None,
    include_private: bool,
    timezone: str | None,
) -> AnnotationExportResult:
    result = await build_annotation_export(
        owner_id, revision_id, object_id, project_id, include_private, timezone
    )
    workflow_id = DBOS.workflow_id
    if workflow_id is None:
        raise RuntimeError("annotation export must run within a DBOS workflow")
    await record_annotation_export_artifact(workflow_id, result)
    return result


@ads.transaction(isolation_level="READ COMMITTED")
async def record_annotation_export_artifact(
    workflow_id: str, result: AnnotationExportResult
) -> None:
    from quirebase.operations.settings import get_effective_setting

    db = ads.sql_session()
    if await db.get(ExportArtifact, workflow_id) is not None:
        return
    ttl_hours = await get_effective_setting(db, "export_ttl_hours", get_settings().export_ttl_hours)
    db.add(
        ExportArtifact(
            workflow_id=workflow_id,
            object_key=result["object_key"],
            filename=result["filename"],
            size=result["size_bytes"],
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        )
    )
