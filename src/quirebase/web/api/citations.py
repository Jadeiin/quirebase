from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from quirebase.library import (
    DEFAULT_CITATION_KEY_FORMULA,
    BibliographyExportOptions,
    get_item_citation_response,
    get_item_citation_text_response,
)
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.responses import content_disposition

router = APIRouter(tags=["Citations"])

BIBLIOGRAPHY_CONTENT_TYPES = {
    "text/plain": {"schema": {"type": "string"}},
    "application/x-bibtex": {"schema": {"type": "string"}},
    "application/x-research-info-systems": {"schema": {"type": "string"}},
    "application/x-endnote-refer": {"schema": {"type": "string"}},
}


@router.get(
    "/items/{item_id}/bibliography",
    response_class=Response,
    responses={200: {"content": BIBLIOGRAPHY_CONTENT_TYPES}},
)
async def export_item_bibliography(
    item_id: str,
    file_format: str,
    user: ApiUser,
    db: Database,
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
        headers={
            "Content-Disposition": content_disposition(filename),
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/items/{item_id}/bibliography/content",
    response_class=Response,
    responses={
        200: {
            "content": {
                "text/plain": {"schema": {"type": "string"}},
            }
        }
    },
)
async def copy_citation(
    item_id: str,
    user: ApiUser,
    db: Database,
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
    item_id: str,
    user: ApiUser,
    db: Database,
    style: str = "apa",
    output: str = "text",
):
    rendered, media_type = await get_item_citation_text_response(
        db, user, item_id, style_key=style, output=output
    )
    return Response(rendered, media_type=f"{media_type}; charset=utf-8")
