from __future__ import annotations

import json
import re
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from quirebase.access.items import require_editable_item
from quirebase.core.config import get_settings
from quirebase.documents import (
    acquire_remote_attachment,
    create_attachment,
    create_item_document_bundle,
    delete_attachment,
    delete_file_revision,
    export_revision_pdf,
    get_attachment_file,
    get_item_thumbnail,
    get_pdf_viewer_data,
    get_revision_file,
    get_revision_thumbnail,
    head_attachment_file,
    head_item_thumbnail,
    head_revision_file,
    head_revision_thumbnail,
    resolve_item_thumbnail,
    store_pdf_revision,
)
from quirebase.library import (
    FilesWorkspace,
    WorkspaceSection,
    acquire_remote_pdf,
    open_item_workspace,
)
from quirebase.models import AttachmentRole
from quirebase.operations.settings import get_effective_setting, get_effective_settings_model
from quirebase.web.api.annotation_schemas import DocumentListView, document_list_view
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.item_schemas import (
    PdfViewerView,
    RemoteAttachmentRequest,
    RemoteRevisionRequest,
)
from quirebase.web.api.library_schemas import item_search_view
from quirebase.web.api.serialization import enum_value
from quirebase.web.errors import ApiHTTPException
from quirebase.web.responses import content_disposition
from quirebase.web.uploads import upload_chunks

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Documents"])

RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)$")
THUMBNAIL_CONTENT_TYPES = {
    "image/png": {"schema": {"type": "string", "format": "binary"}},
    "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
    "image/webp": {"schema": {"type": "string", "format": "binary"}},
    "image/gif": {"schema": {"type": "string", "format": "binary"}},
}


def _etag_header(metadata) -> str:
    value = metadata.etag or metadata.key
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith('W/"') and value.endswith('"')
    ):
        return value
    return f'"{value}"'


def _if_none_match_matches(value: str | None, etag: str) -> bool:
    if value is None:
        return False
    value = value.strip()
    if value == "*":
        return True

    validators: list[str] = []
    position = 0
    while position < len(value):
        while position < len(value) and value[position] in " \t":
            position += 1
        if validators:
            if position >= len(value) or value[position] != ",":
                return False
            position += 1
            while position < len(value) and value[position] in " \t":
                position += 1

        start = position
        if value.startswith("W/", position):
            position += 2
        if position >= len(value) or value[position] != '"':
            return False
        position += 1
        while position < len(value) and value[position] != '"':
            character = ord(value[position])
            if (
                character != 0x21
                and not 0x23 <= character <= 0x7E
                and not 0x80 <= character <= 0xFF
            ):
                return False
            position += 1
        if position >= len(value):
            return False
        position += 1
        validators.append(value[start:position])

        while position < len(value) and value[position] in " \t":
            position += 1

    weak_etag = etag.removeprefix("W/")
    return any(candidate.removeprefix("W/") == weak_etag for candidate in validators)


def _not_modified(request: Request, metadata) -> Response | None:
    etag = _etag_header(metadata)
    if _if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(
            status_code=304, headers={"ETag": etag, "Cache-Control": "private, no-cache"}
        )
    return None


async def ranged_object(request: Request, metadata, filename: str, object_get):
    size = metadata.size
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": _etag_header(metadata),
        "Cache-Control": "private, no-cache",
        "Content-Disposition": content_disposition(filename, "inline"),
    }
    if (not_modified := _not_modified(request, metadata)) is not None:
        return not_modified
    value = request.headers.get("range")
    if not value:
        response = await object_get(None)
        headers["Content-Length"] = str(size)
        return StreamingResponse(response.body, media_type="application/pdf", headers=headers)
    match = RANGE_PATTERN.fullmatch(value.strip())
    if not match:
        raise ApiHTTPException(
            416,
            "range_not_satisfiable",
            "requested byte range is not satisfiable",
            headers={"Content-Range": f"bytes */{size}"},
        )
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise ApiHTTPException(
            416,
            "range_not_satisfiable",
            "requested byte range is not satisfiable",
            headers={"Content-Range": f"bytes */{size}"},
        )
    if not start_text:
        length = int(end_text)
        start, end = max(0, size - length), size - 1
    else:
        start = int(start_text)
        end = min(int(end_text) if end_text else size - 1, size - 1)
    if start >= size or start > end:
        raise ApiHTTPException(
            416,
            "range_not_satisfiable",
            "requested byte range is not satisfiable",
            headers={"Content-Range": f"bytes */{size}"},
        )

    ranged = await object_get((start, end + 1))
    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(end - start + 1),
    })
    return StreamingResponse(
        ranged.body, status_code=206, media_type="application/pdf", headers=headers
    )


@router.get("/items/{item_id}/documents", response_model=DocumentListView)
async def list_documents(
    workspace_id: str, item_id: str, user: ApiUser, db: Database
) -> DocumentListView:
    workspace = await open_item_workspace(db, user, workspace_id, item_id, WorkspaceSection.files)
    if not isinstance(workspace, FilesWorkspace):  # pragma: no cover
        raise TypeError("item files workspace mismatch")
    return document_list_view(item_id, workspace)


@router.get(
    "/items/{item_id}/archive",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/zip": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
async def download_item_archive(
    workspace_id: str,
    item_id: str,
    user: ApiUser,
    db: Database,
    revisions: str | None = None,
    include_annotations: bool = False,
    include_supplements: bool = False,
    timezone: str | None = None,
) -> StreamingResponse:
    revision_ids = (
        [value.strip() for value in revisions.split(",") if value.strip()] if revisions else None
    )
    bundle = await create_item_document_bundle(
        db,
        user,
        workspace_id,
        item_id,
        revision_ids=revision_ids,
        include_annotations=include_annotations,
        include_supplements=include_supplements,
        timezone=timezone,
    )
    return StreamingResponse(
        bundle.body,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition(bundle.filename),
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/items/{item_id}/attachments", response_model=WriteResult, status_code=status.HTTP_202_ACCEPTED
)
async def upload_item_attachment(
    workspace_id: str,
    item_id: str,
    user: ApiUser,
    db: Database,
    attachment: Annotated[UploadFile, File()],
    graphical_abstract: Annotated[bool, Form()] = False,
) -> WriteResult:
    workflow = await create_attachment(
        db,
        user,
        workspace_id,
        item_id,
        upload_chunks(attachment),
        attachment.filename or "",
        attachment.content_type or "application/octet-stream",
        await get_effective_setting(
            db, "max_attachment_bytes", get_settings().max_attachment_bytes
        ),
        role=AttachmentRole.graphical_abstract if graphical_abstract else None,
    )
    return WriteResult(id=workflow.workflow_id)


@router.post(
    "/items/{item_id}/attachments/remote",
    response_model=WriteResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_remote_item_attachment(
    workspace_id: str,
    item_id: str,
    data: RemoteAttachmentRequest,
    user: ApiUser,
    db: Database,
) -> WriteResult:
    max_bytes = await get_effective_setting(
        db, "max_attachment_bytes", get_settings().max_attachment_bytes
    )
    await require_editable_item(db, user, workspace_id, item_id)
    await db.rollback()
    async with acquire_remote_attachment(data.source, max_bytes) as attachment:
        workflow = await create_attachment(
            db,
            user,
            workspace_id,
            item_id,
            attachment.content,
            attachment.filename,
            attachment.media_type,
            max_bytes,
            role=AttachmentRole.graphical_abstract if data.graphical_abstract else None,
        )
    return WriteResult(id=workflow.workflow_id)


@router.get(
    "/items/{item_id}/attachments/{attachment_id}/content",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
async def download_item_attachment(
    request: Request,
    workspace_id: str,
    item_id: str,
    attachment_id: str,
    user: ApiUser,
    db: Database,
) -> Response:
    metadata, original_name, media_type = await head_attachment_file(
        db, user, workspace_id, item_id, attachment_id
    )
    if (not_modified := _not_modified(request, metadata)) is not None:
        return not_modified
    response, _original_name, _media_type = await get_attachment_file(
        db, user, workspace_id, item_id, attachment_id
    )
    return StreamingResponse(
        response.body,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(original_name),
            "Cache-Control": "private, no-cache",
            "ETag": _etag_header(metadata),
            "Content-Length": str(metadata.size),
        },
    )


@router.delete("/items/{item_id}/attachments/{attachment_id}", response_model=OkView)
async def delete_item_attachment(
    workspace_id: str, item_id: str, attachment_id: str, user: ApiUser, db: Database
) -> OkView:
    await delete_attachment(db, user, workspace_id, item_id, attachment_id)
    return OkView()


@router.post(
    "/items/{item_id}/revisions", response_model=WriteResult, status_code=status.HTTP_202_ACCEPTED
)
async def upload_item_pdf(
    workspace_id: str,
    item_id: str,
    user: ApiUser,
    db: Database,
    pdf: Annotated[UploadFile, File()],
) -> WriteResult:
    workflow = await store_pdf_revision(
        db,
        user,
        workspace_id,
        item_id,
        upload_chunks(pdf),
        pdf.filename or "",
        await get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes),
    )
    return WriteResult(id=workflow.workflow_id)


@router.post(
    "/items/{item_id}/revisions/remote",
    response_model=WriteResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_remote_item_pdf(
    workspace_id: str,
    item_id: str,
    data: RemoteRevisionRequest,
    user: ApiUser,
    db: Database,
) -> WriteResult:
    settings = await get_effective_settings_model(db)
    max_bytes = await get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
    await require_editable_item(db, user, workspace_id, item_id)
    await db.rollback()
    async with acquire_remote_pdf(data.source, settings, max_bytes) as document:
        workflow = await store_pdf_revision(
            db, user, workspace_id, item_id, document.content, document.filename, max_bytes
        )
    return WriteResult(id=workflow.workflow_id)


@router.delete("/items/{item_id}/revisions/{revision_id}", response_model=OkView)
async def delete_item_pdf(
    workspace_id: str, item_id: str, revision_id: str, user: ApiUser, db: Database
) -> OkView:
    await delete_file_revision(db, user, workspace_id, item_id, revision_id)
    return OkView()


@router.get("/items/{item_id}/revisions/{revision_id}/viewer", response_model=PdfViewerView)
async def pdf_viewer_configuration(
    workspace_id: str, item_id: str, revision_id: str, user: ApiUser, db: Database
):
    data = await get_pdf_viewer_data(db, user, workspace_id, item_id, revision_id)
    revision = data["revision"]
    return {
        "item": item_search_view(data["item"]),
        # Reaching the viewer proves readable revision access. Annotation writes have
        # their own ownership/scope checks and intentionally do not require Item edits.
        "editable": True,
        "annotation_author": user.username,
        "revision": {
            "id": revision.id,
            "original_name": revision.original_name,
            "page_count": revision.page_count,
            "processing_state": enum_value(revision.processing_state),
            "page_geometry": json.loads(revision.page_geometry or "[]"),
            "content_url": (
                f"/api/v1/workspaces/{workspace_id}/items/{item_id}/revisions/{revision_id}/content"
            ),
        },
        "projects": [{"id": project.id, "name": project.name} for project in data["projects"]],
    }


@router.get(
    "/items/{item_id}/revisions/{revision_id}/content",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            }
        },
        206: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            }
        },
    },
)
async def pdf_content(
    request: Request,
    workspace_id: str,
    item_id: str,
    revision_id: str,
    user: ApiUser,
    db: Database,
):
    metadata, original_name, _media_type = await head_revision_file(
        db, user, workspace_id, item_id, revision_id
    )

    async def object_get(byte_range: tuple[int, int] | None):
        response, _name, _sha = await get_revision_file(
            db, user, workspace_id, item_id, revision_id, byte_range=byte_range
        )
        return response

    return await ranged_object(request, metadata, original_name, object_get)


@router.get(
    "/items/{item_id}/revisions/{revision_id}/thumbnail",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "image/png": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
async def pdf_thumbnail(
    request: Request,
    workspace_id: str,
    item_id: str,
    revision_id: str,
    user: ApiUser,
    db: Database,
):
    metadata = await head_revision_thumbnail(db, user, workspace_id, item_id, revision_id)
    if (not_modified := _not_modified(request, metadata)) is not None:
        return not_modified
    response = await get_revision_thumbnail(db, user, workspace_id, item_id, revision_id)
    return StreamingResponse(
        response.body,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-cache",
            "ETag": _etag_header(metadata),
            "Content-Length": str(metadata.size),
        },
    )


@router.get(
    "/items/{item_id}/thumbnail",
    response_class=StreamingResponse,
    responses={200: {"content": THUMBNAIL_CONTENT_TYPES}},
)
async def item_thumbnail(
    request: Request,
    workspace_id: str,
    item_id: str,
    user: ApiUser,
    db: Database,
):
    source = await resolve_item_thumbnail(db, user, workspace_id, item_id)
    metadata = await head_item_thumbnail(source)
    if (not_modified := _not_modified(request, metadata)) is not None:
        return not_modified
    thumbnail = await get_item_thumbnail(source)
    response = thumbnail.response
    return StreamingResponse(
        response.body,
        media_type=source.media_type,
        headers={
            "Cache-Control": "private, no-cache",
            "ETag": _etag_header(metadata),
            "Content-Length": str(metadata.size),
        },
    )


@router.get(
    "/items/{item_id}/revisions/{revision_id}/export",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
async def export_revision_pdf_route(
    workspace_id: str,
    item_id: str,
    revision_id: str,
    user: ApiUser,
    db: Database,
    include_annotations: bool = True,
    project_id: str | None = None,
    timezone: str | None = None,
):
    exported = await export_revision_pdf(
        db,
        user,
        workspace_id,
        item_id,
        revision_id,
        include_annotations=include_annotations,
        project_id=project_id,
        timezone=timezone,
    )
    return StreamingResponse(
        exported.body,
        media_type=exported.media_type,
        headers={
            "Content-Disposition": content_disposition(exported.filename),
            "Cache-Control": "private, no-store",
        },
    )
