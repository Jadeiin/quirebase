from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from quirebase.core.database import get_db
from quirebase.discovery import (
    get_item_citation_response,
    get_item_citation_text_response,
)
from quirebase.documents import (
    get_revision_file,
)
from quirebase.models import User
from quirebase.web.deps import current_user

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()

RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)$")


def ranged_file(request: Request, path: Path, etag: str, filename: str):
    size = path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"{etag}"',
        "Content-Disposition": f'inline; filename="{Path(filename).name}"',
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
def export_item(
    item_id: str,
    file_format: str,
    style: str = "apa",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    contents, media_type, filename = get_item_citation_response(
        db, user, item_id, file_format, style_key=style
    )
    return Response(
        contents,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
