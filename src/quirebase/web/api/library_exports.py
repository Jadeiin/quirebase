from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response, StreamingResponse

from quirebase.library import (
    DEFAULT_CITATION_KEY_FORMULA,
    BibliographyExportOptions,
    download_selected_item_documents,
    export_accessible_bibliography,
    export_selected_bibliography,
)
from quirebase.web.api.content import BIBLIOGRAPHY_CONTENT_TYPES
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.export_schemas import BibliographyExportRequest, DocumentArchiveRequest
from quirebase.web.responses import content_disposition

router = APIRouter(prefix="/api/v1", tags=["Library exports"])


def _bibliography_options(data: BibliographyExportRequest) -> BibliographyExportOptions:
    return BibliographyExportOptions(
        include_abstract=data.include_abstract,
        preserve_case=data.preserve_case,
        include_identifiers=data.include_identifiers,
        include_custom_fields=data.include_custom_fields,
        encoding=data.encoding,
        journal_mode=data.journal_mode,
        doi_policy=data.doi_policy,
        url_policy=data.url_policy,
        excluded_fields=tuple(data.excluded_fields),
        sort_by=data.sort_by,
        citation_key_formula=data.citation_key_formula.strip() or DEFAULT_CITATION_KEY_FORMULA,
        citation_key_force_ascii=data.citation_key_force_ascii,
    )


@router.post(
    "/items/bibliography",
    response_class=Response,
    responses={200: {"content": BIBLIOGRAPHY_CONTENT_TYPES}},
)
async def export_item_selection(
    data: BibliographyExportRequest, user: ApiUser, db: Database
) -> Response:
    contents, media_type, filename = await export_selected_bibliography(
        db,
        user,
        data.item_ids,
        data.file_format,
        style_key=data.style,
        options=_bibliography_options(data),
    )
    return Response(
        contents,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post(
    "/items/documents/archive",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/zip": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
async def download_item_selection(
    data: DocumentArchiveRequest, user: ApiUser, db: Database
) -> StreamingResponse:
    archive = await download_selected_item_documents(
        db,
        user,
        data.item_ids,
        include_annotations=data.include_annotations,
        include_supplements=data.include_supplements,
        timezone=data.timezone,
    )
    return StreamingResponse(
        archive.body,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition(archive.filename)},
    )


@router.get(
    "/bibliography",
    response_class=Response,
    responses={200: {"content": BIBLIOGRAPHY_CONTENT_TYPES}},
)
async def export_library_bibliography(
    user: ApiUser, db: Database, file_format: str, style: str = "apa"
) -> Response:
    contents, media_type, filename = await export_accessible_bibliography(
        db, user, file_format, style_key=style
    )
    return Response(
        contents,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename)},
    )
