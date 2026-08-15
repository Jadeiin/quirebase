from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from quirebase.core.database import get_db
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
