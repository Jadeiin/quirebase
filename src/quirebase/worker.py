from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import SessionLocal
from .maintenance import cleanup_exports
from .models import FileRevision, Job, PdfAnnotation, ProjectItem, ProjectMember
from .pdf_service import create_thumbnail, export_annotations, inspect_pdf
from .search import search_index
from .storage import LocalObjectStore


def claim_job(db: Session) -> Job | None:
    now = datetime.now(UTC)
    query = (
        select(Job)
        .where(
            Job.state.in_(["pending", "running"]),
            or_(Job.lease_until.is_(None), Job.lease_until < now),
            Job.attempts < 3,
        )
        .order_by(Job.created_at)
        .limit(1)
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    job = db.scalar(query)
    if job:
        job.state = "running"
        job.lease_until = now + timedelta(minutes=10)
        job.attempts += 1
        db.commit()
    return job


def run_job(db: Session, job: Job) -> None:
    payload = json.loads(job.payload)
    try:
        if job.kind == "pdf.inspect":
            revision = db.get(FileRevision, payload["revision_id"])
            if revision is None:
                raise ValueError("revision no longer exists")
            path = LocalObjectStore().path(revision.object_key)
            pages, text, geometry = inspect_pdf(path)
            if pages < 1:
                raise ValueError("PDF contains no pages")
            revision.page_count = pages
            revision.page_geometry = json.dumps(geometry, separators=(",", ":"))
            revision.full_text = text
            revision.processing_state = "ready"
            create_thumbnail(path, get_settings().object_dir / "thumbnails" / f"{revision.id}.png")
            search_index(db).index_item(db, revision.item_id)
            job.result = json.dumps({"page_count": pages})
        elif job.kind == "pdf.export_annotations":
            revision = db.get(FileRevision, payload["revision_id"])
            if revision is None:
                raise ValueError("revision no longer exists")
            scopes = []
            if payload.get("include_private"):
                scopes.append(
                    and_(PdfAnnotation.scope == "private", PdfAnnotation.author_id == job.owner_id)
                )
            if payload.get("project_id"):
                membership = db.get(ProjectMember, (payload["project_id"], job.owner_id))
                assignment = db.get(ProjectItem, (payload["project_id"], revision.item_id))
                if membership is None or assignment is None:
                    raise PermissionError("project membership no longer exists")
                scopes.append(
                    and_(
                        PdfAnnotation.scope == "project",
                        PdfAnnotation.project_id == payload["project_id"],
                    )
                )
            records = (
                []
                if not scopes
                else list(
                    db.scalars(
                        select(PdfAnnotation)
                        .options(selectinload(PdfAnnotation.segments))
                        .where(
                            PdfAnnotation.file_revision_id == revision.id,
                            PdfAnnotation.deleted_at.is_(None),
                            or_(*scopes),
                        )
                    ).all()
                )
            )
            filename = f"{job.id}.pdf"
            export_annotations(
                LocalObjectStore().path(revision.object_key),
                get_settings().export_dir / filename,
                records,
            )
            job.result = json.dumps({"filename": filename})
        else:
            raise ValueError(f"unknown job kind: {job.kind}")
        job.state = "succeeded"
        job.error = None
    except Exception as error:
        job.error = f"{type(error).__name__}: {error}"[:4000]
        job.state = "pending" if job.attempts < 3 else "failed"
    finally:
        job.lease_until = None
        db.commit()


def run_once() -> bool:
    with SessionLocal() as db:
        job = claim_job(db)
        if job is None:
            return False
        run_job(db, job)
        return True


def run_forever() -> None:
    last_cleanup = 0.0
    while True:
        if time.monotonic() - last_cleanup >= 3600:
            cleanup_exports()
            last_cleanup = time.monotonic()
        if not run_once():
            time.sleep(get_settings().worker_poll_seconds)
