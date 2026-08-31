from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from quirebase.core.database import get_db
from quirebase.documents import (
    export_revision_pdf,
    get_item_thumbnail,
    get_revision_file,
    get_revision_thumbnail,
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
    from pathlib import Path

    from sqlalchemy.orm import Session

router = protected_router()

RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)$")


def ranged_file(request: Request, path: Path, etag: str, filename: str):
    size = path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"{etag}"',
        "Content-Disposition": content_disposition(filename, "inline"),
    }
    value = request.headers.get("range")
    if not value:
        return FileResponse(path, media_type="application/pdf", headers=headers)
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

    def chunks():
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(end - start + 1),
    })
    return StreamingResponse(
        chunks(), status_code=206, media_type="application/pdf", headers=headers
    )


@router.get("/documents/{item_id}/citation")
def export_item_bibliography(
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
    db: Session = Depends(get_db),
):
    contents, media_type, filename = get_item_citation_response(
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
def copy_citation(
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
    db: Session = Depends(get_db),
):
    contents, _media_type, _filename = get_item_citation_response(
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
def citation_text(
    item_id: str,
    style: str = "apa",
    output: str = "text",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rendered, media_type = get_item_citation_text_response(
        db, user, item_id, style_key=style, output=output
    )
    return Response(rendered, media_type=f"{media_type}; charset=utf-8")


@router.get("/documents/{item_id}/revisions/{revision_id}/content")
def pdf_content(
    request: Request,
    item_id: str,
    revision_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    path, original_name, sha256 = get_revision_file(db, user, item_id, revision_id)
    return ranged_file(request, path, sha256, original_name)


@router.get("/documents/{item_id}/revisions/{revision_id}/thumbnail")
def pdf_thumbnail(
    item_id: str,
    revision_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    path = get_revision_thumbnail(db, user, item_id, revision_id)
    return FileResponse(path, media_type="image/png")


@router.get("/documents/{item_id}/thumbnail")
def item_thumbnail(
    item_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    thumbnail = get_item_thumbnail(db, user, item_id)
    return FileResponse(thumbnail.path, media_type=thumbnail.media_type)


@router.get("/documents/{item_id}/revisions/{revision_id}/export")
def export_revision_pdf_route(
    item_id: str,
    revision_id: str,
    include_annotations: bool = True,
    project_id: str | None = None,
    timezone: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    path, filename, media_type, temporary = export_revision_pdf(
        db,
        user,
        item_id,
        revision_id,
        include_annotations=include_annotations,
        project_id=project_id,
        timezone=timezone,
    )
    cleanup_task = BackgroundTask(path.unlink, missing_ok=True) if temporary else None
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="attachment",
        background=cleanup_task,
    )
