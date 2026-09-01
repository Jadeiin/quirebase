from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from quirebase.core.database import get_db
from quirebase.documents import (
    export_revision_pdf,
    get_item_thumbnail,
    get_revision_file,
    get_revision_thumbnail,
    head_revision_file,
)
from quirebase.library import (
    DEFAULT_CITATION_KEY_FORMULA,
    BibliographyExportOptions,
    get_item_citation_response,
    get_item_citation_text_response,
)
from quirebase.models import User
from quirebase.web.deps import current_user, protected_router
from quirebase.web.responses import content_disposition

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = protected_router()

RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)$")


def _etag_header(metadata) -> str:
    value = metadata.etag or metadata.key
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith('W/"') and value.endswith('"')
    ):
        return value
    return f'"{value}"'


async def ranged_object(request: Request, metadata, filename: str, object_get):
    size = metadata.size
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": _etag_header(metadata),
        "Content-Disposition": content_disposition(filename, "inline"),
    }
    value = request.headers.get("range")
    if not value:
        response = await object_get(None)
        headers["Content-Length"] = str(size)
        return StreamingResponse(response.body, media_type="application/pdf", headers=headers)
    match = RANGE_PATTERN.fullmatch(value.strip())
    if not match:
        raise HTTPException(416, headers={"Content-Range": f"bytes */{size}"})
    start_text, end_text = match.groups()
    if not start_text:
        length = int(end_text)
        start, end = max(0, size - length), size - 1
    else:
        start = int(start_text)
        end = min(int(end_text) if end_text else size - 1, size - 1)
    if start >= size or start > end:
        raise HTTPException(416, headers={"Content-Range": f"bytes */{size}"})

    ranged = await object_get((start, end + 1))
    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(end - start + 1),
    })
    return StreamingResponse(
        ranged.body, status_code=206, media_type="application/pdf", headers=headers
    )


@router.get("/documents/{item_id}/citation")
async def export_item_bibliography(
    item_id: str,
    file_format: str,
    style: str = "apa",
    include_abstract: bool = True,
    preserve_case: bool = False,
    include_identifiers: bool = False,
    include_custom_fields: bool = False,
    encoding: str = "unicode",
    journal_mode: str = "full",
    doi_policy: str = "include",
    url_policy: str = "include",
    excluded_fields: str = "",
    sort_by: str = "input",
    citation_key_formula: str = "",
    citation_key_force_ascii: bool = False,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    contents, media_type, filename = await get_item_citation_response(
        db,
        user,
        item_id,
        file_format,
        style_key=style,
        options=BibliographyExportOptions(
            include_abstract=include_abstract,
            preserve_case=preserve_case,
            include_identifiers=include_identifiers,
            include_custom_fields=include_custom_fields,
            encoding=encoding,
            journal_mode=journal_mode,
            doi_policy=doi_policy,
            url_policy=url_policy,
            excluded_fields=tuple(
                part.strip() for part in excluded_fields.split(",") if part.strip()
            ),
            sort_by=sort_by,
            citation_key_formula=citation_key_formula.strip() or DEFAULT_CITATION_KEY_FORMULA,
            citation_key_force_ascii=citation_key_force_ascii,
        ),
    )
    return Response(
        contents,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.get("/documents/{item_id}/citation-copy")
async def copy_citation(
    item_id: str,
    file_format: str = "csl",
    style: str = "apa",
    include_abstract: bool = True,
    preserve_case: bool = False,
    include_identifiers: bool = False,
    include_custom_fields: bool = False,
    encoding: str = "unicode",
    journal_mode: str = "full",
    doi_policy: str = "include",
    url_policy: str = "include",
    excluded_fields: str = "",
    sort_by: str = "input",
    citation_key_formula: str = "",
    citation_key_force_ascii: bool = False,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    contents, _media_type, _filename = await get_item_citation_response(
        db,
        user,
        item_id,
        file_format,
        style_key=style,
        options=BibliographyExportOptions(
            include_abstract=include_abstract,
            preserve_case=preserve_case,
            include_identifiers=include_identifiers,
            include_custom_fields=include_custom_fields,
            encoding=encoding,
            journal_mode=journal_mode,
            doi_policy=doi_policy,
            url_policy=url_policy,
            excluded_fields=tuple(
                part.strip() for part in excluded_fields.split(",") if part.strip()
            ),
            sort_by=sort_by,
            citation_key_formula=citation_key_formula.strip() or DEFAULT_CITATION_KEY_FORMULA,
            citation_key_force_ascii=citation_key_force_ascii,
        ),
    )
    return Response(contents, media_type="text/plain; charset=utf-8")


@router.get("/documents/{item_id}/citation-text")
async def citation_text(
    item_id: str,
    style: str = "apa",
    output: str = "text",
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    rendered, media_type = await get_item_citation_text_response(
        db, user, item_id, style_key=style, output=output
    )
    return Response(rendered, media_type=f"{media_type}; charset=utf-8")


@router.get("/documents/{item_id}/revisions/{revision_id}/content")
async def pdf_content(
    request: Request,
    item_id: str,
    revision_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    metadata, original_name, _media_type = await head_revision_file(db, user, item_id, revision_id)

    async def object_get(byte_range: tuple[int, int] | None):
        response, _name, _sha = await get_revision_file(
            db, user, item_id, revision_id, byte_range=byte_range
        )
        return response

    return await ranged_object(request, metadata, original_name, object_get)


@router.get("/documents/{item_id}/revisions/{revision_id}/thumbnail")
async def pdf_thumbnail(
    item_id: str,
    revision_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    response = await get_revision_thumbnail(db, user, item_id, revision_id)
    return StreamingResponse(response.body, media_type="image/png")


@router.get("/documents/{item_id}/thumbnail")
async def item_thumbnail(
    item_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    thumbnail = await get_item_thumbnail(db, user, item_id)
    return StreamingResponse(thumbnail.response.body, media_type=thumbnail.media_type)


@router.get("/documents/{item_id}/revisions/{revision_id}/export")
async def export_revision_pdf_route(
    item_id: str,
    revision_id: str,
    include_annotations: bool = True,
    project_id: str | None = None,
    timezone: str | None = None,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    exported = await export_revision_pdf(
        db,
        user,
        item_id,
        revision_id,
        include_annotations=include_annotations,
        project_id=project_id,
        timezone=timezone,
    )
    return StreamingResponse(
        exported.body,
        media_type=exported.media_type,
        headers={"Content-Disposition": content_disposition(exported.filename)},
    )
