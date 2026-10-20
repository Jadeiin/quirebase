from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response, StreamingResponse

from quirebase.library import (
    download_selected_item_documents,
    export_selected_bibliography,
    export_workspace_bibliography,
)
from quirebase.web.api.citations import BIBLIOGRAPHY_CONTENT_TYPES, bibliography_response
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.export_schemas import (
    BibliographyExportQuery,
    BibliographyExportRequest,
    DocumentArchiveRequest,
)
from quirebase.web.responses import content_disposition

router = APIRouter(tags=["Library exports"])


@router.post(
    "/items/bibliography",
    response_class=Response,
    responses={200: {"content": BIBLIOGRAPHY_CONTENT_TYPES}},
)
async def download_selected_bibliography(
    workspace_id: UUID, data: BibliographyExportRequest, user: ApiUser, db: Database
) -> Response:
    export = await export_selected_bibliography(
        db,
        user,
        workspace_id,
        data.item_ids,
        data.file_format,
        style_key=data.style,
        options=data.to_options(),
    )
    return bibliography_response(export)


@router.post(
    "/items/documents/archive",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def download_item_selection(
    workspace_id: UUID, data: DocumentArchiveRequest, user: ApiUser, db: Database
) -> StreamingResponse:
    archive = await download_selected_item_documents(
        db,
        user,
        workspace_id,
        data.item_ids,
        include_annotations=data.include_annotations,
        include_supplements=data.include_supplements,
        timezone=data.timezone,
    )
    return StreamingResponse(
        archive.body,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition(archive.filename),
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/bibliography",
    response_class=Response,
    responses={200: {"content": BIBLIOGRAPHY_CONTENT_TYPES}},
)
async def download_workspace_bibliography(
    workspace_id: UUID,
    user: ApiUser,
    db: Database,
    data: Annotated[BibliographyExportQuery, Query()],
) -> Response:
    export = await export_workspace_bibliography(
        db,
        user,
        workspace_id,
        data.file_format,
        style_key=data.style,
        options=data.to_options(),
    )
    return bibliography_response(export)
