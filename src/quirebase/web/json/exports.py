from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from quirebase.core.database import get_db
from quirebase.discovery import (
    list_custom_citation_styles,
    select_builtin_citation_styles,
)
from quirebase.documents import (
    create_export_job,
    get_export_file_path,
    get_export_status,
)
from quirebase.documents.schemas import ExportCreate
from quirebase.models import User
from quirebase.web.deps import current_user, require_csrf

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/api/citation-styles")
def citation_styles(
    query: str = "",
    limit: int = 50,
    include: str = "",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    normalized = query.strip().casefold()
    builtin_selection = select_builtin_citation_styles(query, limit=limit, include=include)
    owned_custom_styles = list_custom_citation_styles(db, user)
    custom = [
        {"key": style.id, "name": style.name, "scope": "custom"}
        for style in owned_custom_styles
        if style.id != include and (not normalized or normalized in style.name.casefold())
    ]
    exact_custom = next(
        (
            {"key": style.id, "name": style.name, "scope": "custom"}
            for style in owned_custom_styles
            if include and style.id == include
        ),
        None,
    )
    included = []
    if builtin_selection.included is not None:
        included.append({
            "key": builtin_selection.included.key,
            "name": builtin_selection.included.name,
            "scope": "builtin",
        })
    if exact_custom is not None:
        included.append(exact_custom)
    styles = [
        {"key": style.key, "name": style.name, "scope": "builtin"}
        for style in builtin_selection.matches
    ][:limit] + custom[:limit]
    included = [
        style for style in included if not any(style["key"] == item["key"] for item in styles)
    ]
    return {
        "styles": styles + included,
    }


@router.post("/documents/{item_id}/annotation-exports", dependencies=[Depends(require_csrf)])
def create_export(
    item_id: str,
    data: ExportCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    job = create_export_job(db, user, item_id, data)
    return JSONResponse({"id": job.id, "state": job.state}, status_code=202)


@router.get("/annotation-exports/{job_id}")
def export_status(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_export_status(db, user, job_id)


@router.get("/annotation-exports/{job_id}/content")
def export_content(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    path = get_export_file_path(db, user, job_id)
    return FileResponse(path, media_type="application/pdf", filename="annotated.pdf")
