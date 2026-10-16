from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response

from quirebase.library import (
    BIBLIOGRAPHY_MEDIA_TYPES,
    get_item_citation_response,
    get_item_citation_text_response,
)
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.export_schemas import BibliographyCopyQuery, BibliographyExportQuery
from quirebase.web.responses import content_disposition

router = APIRouter(tags=["Citations"])
BIBLIOGRAPHY_CONTENT_TYPES = {
    "text/plain": {"schema": {"type": "string"}},
    **{
        media_type: {"schema": {"type": "string"}}
        for media_type in BIBLIOGRAPHY_MEDIA_TYPES.values()
    },
}


@router.get(
    "/items/{item_id}/bibliography",
    response_class=Response,
    responses={200: {"content": BIBLIOGRAPHY_CONTENT_TYPES}},
)
async def export_item_bibliography(
    workspace_id: UUID,
    item_id: UUID,
    user: ApiUser,
    db: Database,
    data: Annotated[BibliographyExportQuery, Query()],
):
    contents, media_type, filename = await get_item_citation_response(
        db,
        user,
        workspace_id,
        item_id,
        data.file_format,
        style_key=data.style,
        options=data.to_options(),
    )
    return Response(
        contents,
        media_type=f"{media_type}; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition(filename),
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/items/{item_id}/bibliography/content",
    response_class=Response,
    responses={200: {"content": {"text/plain": {"schema": {"type": "string"}}}}},
)
async def copy_citation(
    workspace_id: UUID,
    item_id: UUID,
    user: ApiUser,
    db: Database,
    data: Annotated[BibliographyCopyQuery, Query()],
):
    contents, _media_type, _filename = await get_item_citation_response(
        db,
        user,
        workspace_id,
        item_id,
        data.file_format,
        style_key=data.style,
        options=data.to_options(),
    )
    return Response(contents, media_type="text/plain; charset=utf-8")


@router.get(
    "/items/{item_id}/citation/content",
    response_class=Response,
    responses={
        200: {
            "content": {
                "text/plain": {"schema": {"type": "string"}},
                "text/html": {"schema": {"type": "string"}},
            }
        }
    },
)
async def citation_text(
    workspace_id: UUID,
    item_id: UUID,
    user: ApiUser,
    db: Database,
    style: str = "apa",
    output: str = "text",
):
    rendered, media_type = await get_item_citation_text_response(
        db, user, workspace_id, item_id, style_key=style, output=output
    )
    return Response(rendered, media_type=f"{media_type}; charset=utf-8")
