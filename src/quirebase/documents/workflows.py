from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from dbos import DBOS
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import selectinload

from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal
from quirebase.core.storage import ObjectSuffix, get_object_store, object_key
from quirebase.core.timezones import annotation_export_timezone
from quirebase.models import (
    AnnotationScope,
    Attachment,
    AttachmentRole,
    FileRevision,
    FileRevisionProcessingState,
    Item,
    PdfAnnotation,
    ProjectItem,
    ProjectMember,
    User,
)

from .pdf import create_thumbnail, export_annotations, inspect_pdf, validate_pdf_container

REVISION_UPLOAD_WORKFLOW = "documents.upload_revision"
ATTACHMENT_UPLOAD_WORKFLOW = "documents.upload_attachment"
FILE_REVISION_CHANGED_WORKFLOW = "library.file_revision_changed"
ANNOTATION_EXPORT_WORKFLOW = "documents.export_annotations"
IMPORTED_REVISION_INSPECTION_WORKFLOW = "documents.inspect_imported_revision"


@DBOS.step(retries_allowed=True, max_attempts=3)
async def remove_owned_object(key: str) -> None:
    await get_object_store().delete(key)


@DBOS.step(retries_allowed=True, max_attempts=3)
async def inspect_uploaded_pdf(
    revision_id: str,
    object_id: str,
    thumbnail_object_id: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    expected_key = object_key(UUID(object_id), ObjectSuffix.PDF)
    if receipt.get("key") != expected_key:
        raise ValueError("upload receipt does not own the expected object")
    metadata = await get_object_store().head(expected_key)
    if metadata.size != int(receipt.get("size", -1)):
        raise ValueError("uploaded object size mismatch")
    thumbnail_key = object_key(UUID(thumbnail_object_id), ObjectSuffix.PNG)
    async with get_object_store().materialize(expected_key) as source:
        await asyncio.to_thread(validate_pdf_container, source)
        page_count, text, geometry = await asyncio.to_thread(inspect_pdf, source)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
            thumbnail_path = Path(temporary.name)
        try:
            await asyncio.to_thread(create_thumbnail, source, thumbnail_path)
            await get_object_store().put_object(
                UUID(thumbnail_object_id),
                ObjectSuffix.PNG,
                thumbnail_path,
                max_bytes=32 * 1024 * 1024,
            )
        finally:
            await asyncio.to_thread(thumbnail_path.unlink, missing_ok=True)
    return {
        "revision_id": revision_id,
        "object_key": expected_key,
        "thumbnail_object_key": thumbnail_key,
        "size": metadata.size,
        "page_count": page_count,
        "full_text": text,
        "page_geometry": json.dumps(geometry, separators=(",", ":")),
    }


@DBOS.step(retries_allowed=True, max_attempts=3)
async def commit_uploaded_revision(
    item_id: str,
    owner_id: str,
    filename: str,
    inspected: dict[str, Any],
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        existing = await db.get(FileRevision, inspected["revision_id"])
        if existing is not None:
            if existing.processing_state == FileRevisionProcessingState.pending:
                existing.object_key = inspected["object_key"]
                existing.thumbnail_object_key = inspected["thumbnail_object_key"]
                existing.size = inspected["size"]
                existing.page_count = inspected["page_count"]
                existing.page_geometry = inspected["page_geometry"]
                existing.full_text = inspected["full_text"]
                existing.processing_state = FileRevisionProcessingState.ready
                await db.commit()
            return {"revision_id": existing.id, "item_id": existing.item_id}
        if await db.get(Item, item_id) is None:
            raise ValueError("Item no longer exists")
        revision = FileRevision(
            id=inspected["revision_id"],
            item_id=item_id,
            object_key=inspected["object_key"],
            thumbnail_object_key=inspected["thumbnail_object_key"],
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
        await db.commit()
        return {"revision_id": revision.id, "item_id": item_id}


@DBOS.workflow(name=REVISION_UPLOAD_WORKFLOW)
async def upload_revision_workflow(
    item_id: str,
    owner_id: str,
    revision_id: str,
    object_id: str,
    thumbnail_object_id: str,
    filename: str,
) -> dict[str, Any]:
    key = object_key(UUID(object_id), ObjectSuffix.PDF)
    thumbnail_key = object_key(UUID(thumbnail_object_id), ObjectSuffix.PNG)
    receipt = await DBOS.recv_async(
        "upload-complete", timeout_seconds=get_settings().workflow_upload_timeout_seconds
    )
    committed = False
    try:
        if not isinstance(receipt, dict) or receipt.get("status") != "complete":
            raise TimeoutError("PDF upload did not complete")
        inspected = await inspect_uploaded_pdf(revision_id, object_id, thumbnail_object_id, receipt)
        result = await commit_uploaded_revision(item_id, owner_id, filename, inspected)
        committed = True
        await DBOS.enqueue_workflow_with_options_async(
            {
                "workflow_name": FILE_REVISION_CHANGED_WORKFLOW,
                "queue_name": "library",
                "workflow_id": f"file-revision-changed:{revision_id}",
                "application_name": "quirebase",
            },
            item_id,
            owner_id,
        )
        return result
    except BaseException:
        if not committed:
            await remove_owned_object(key)
            await remove_owned_object(thumbnail_key)
        raise


@DBOS.workflow(name=IMPORTED_REVISION_INSPECTION_WORKFLOW)
async def inspect_imported_revision_workflow(
    revision_id: str, owner_id: str, object_key_value: str, thumbnail_object_id: str
) -> dict[str, Any]:
    thumbnail_key = object_key(UUID(thumbnail_object_id), ObjectSuffix.PNG)
    committed = False
    try:
        inspected = await inspect_imported_pdf(revision_id, object_key_value, thumbnail_object_id)
        result = await commit_imported_revision(inspected)
        committed = True
        await DBOS.enqueue_workflow_with_options_async(
            {
                "workflow_name": FILE_REVISION_CHANGED_WORKFLOW,
                "queue_name": "library",
                "workflow_id": f"file-revision-changed:{revision_id}",
                "application_name": "quirebase",
            },
            result["item_id"],
            owner_id,
        )
        return {"revision_id": revision_id, "owner_id": owner_id}
    except BaseException:
        if not committed:
            await remove_owned_object(thumbnail_key)
        raise


@DBOS.step(retries_allowed=True, max_attempts=3)
async def inspect_imported_pdf(
    revision_id: str, object_key_value: str, thumbnail_object_id: str
) -> dict[str, Any]:
    metadata = await get_object_store().head(object_key_value)
    thumbnail_key = object_key(UUID(thumbnail_object_id), ObjectSuffix.PNG)
    async with get_object_store().materialize(object_key_value) as source:
        await asyncio.to_thread(validate_pdf_container, source)
        page_count, text, geometry = await asyncio.to_thread(inspect_pdf, source)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
            thumbnail_path = Path(temporary.name)
        try:
            await asyncio.to_thread(create_thumbnail, source, thumbnail_path)
            await get_object_store().put_object(
                UUID(thumbnail_object_id),
                ObjectSuffix.PNG,
                thumbnail_path,
                max_bytes=32 * 1024 * 1024,
            )
        finally:
            await asyncio.to_thread(thumbnail_path.unlink, missing_ok=True)
    return {
        "revision_id": revision_id,
        "thumbnail_object_key": thumbnail_key,
        "size": metadata.size,
        "page_count": page_count,
        "full_text": text,
        "page_geometry": json.dumps(geometry, separators=(",", ":")),
    }


@DBOS.step(retries_allowed=True, max_attempts=3)
async def commit_imported_revision(inspected: dict[str, Any]) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        revision = await db.get(FileRevision, inspected["revision_id"])
        if revision is None:
            raise ValueError("imported revision no longer exists")
        if revision.processing_state == FileRevisionProcessingState.pending:
            revision.thumbnail_object_key = inspected["thumbnail_object_key"]
            revision.size = inspected["size"]
            revision.page_count = inspected["page_count"]
            revision.full_text = inspected["full_text"]
            revision.page_geometry = inspected["page_geometry"]
            revision.processing_state = FileRevisionProcessingState.ready
            await db.commit()
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
    object_id: str, content_type: str, graphical_abstract: bool, receipt: dict[str, Any]
) -> dict[str, Any]:
    key = object_key(UUID(object_id), ObjectSuffix.BINARY)
    if receipt.get("key") != key:
        raise ValueError("upload receipt does not own the expected object")
    metadata = await get_object_store().head(key)
    if metadata.size != int(receipt.get("size", -1)):
        raise ValueError("uploaded object size mismatch")
    if graphical_abstract:
        response = await get_object_store().get_range(key, 0, min(12, metadata.size))
        header = b"".join([bytes(chunk) async for chunk in response.body])
        if not _is_image_header(header, content_type):
            raise ValueError("graphical abstract content does not match its image type")
    return {"object_key": key, "size": metadata.size}


@DBOS.step(retries_allowed=True, max_attempts=3)
async def commit_uploaded_attachment(
    item_id: str,
    owner_id: str,
    attachment_id: str,
    filename: str,
    content_type: str,
    role_value: str | None,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
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
        await db.commit()
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
) -> dict[str, Any]:
    key = object_key(UUID(object_id), ObjectSuffix.BINARY)
    receipt = await DBOS.recv_async(
        "upload-complete", timeout_seconds=get_settings().workflow_upload_timeout_seconds
    )
    try:
        if not isinstance(receipt, dict) or receipt.get("status") != "complete":
            raise TimeoutError("attachment upload did not complete")
        validated = await validate_attachment_upload(
            object_id, content_type, role_value == AttachmentRole.graphical_abstract.value, receipt
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
) -> dict[str, Any]:
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
                        select(PdfAnnotation)
                        .options(selectinload(PdfAnnotation.segments))
                        .where(
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
) -> dict[str, Any]:
    return await build_annotation_export(
        owner_id, revision_id, object_id, project_id, include_private, timezone
    )
