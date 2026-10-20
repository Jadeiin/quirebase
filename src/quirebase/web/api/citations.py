from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response

from quirebase.library import (
    BIBLIOGRAPHY_MEDIA_TYPES,
    BibliographyExport,
    export_item_bibliography,
)
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.export_schemas import BibliographyExportQuery
from quirebase.web.responses import content_disposition

router = APIRouter(tags=["Citations"])
BIBLIOGRAPHY_CONTENT_TYPES = {
    "text/plain": {"schema": {"type": "string"}},
    **{
        media_type: {"schema": {"type": "string"}}
        for media_type in BIBLIOGRAPHY_MEDIA_TYPES.values()
    },
}


def bibliography_response(export: BibliographyExport) -> Response:
    return Response(
        export.content,
        media_type=f"{export.media_type}; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition(export.filename),
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/items/{item_id}/bibliography",
    response_class=Response,
    responses={200: {"content": BIBLIOGRAPHY_CONTENT_TYPES}},
)
async def download_item_bibliography(
    workspace_id: UUID,
    item_id: UUID,
    user: ApiUser,
    db: Database,
    data: Annotated[BibliographyExportQuery, Query()],
) -> Response:
    export = await export_item_bibliography(
        db,
        user,
        workspace_id,
        item_id,
        data.file_format,
        style_key=data.style,
        options=data.to_options(),
    )
    return bibliography_response(export)
