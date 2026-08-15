from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from quirebase.core.config import get_settings
from quirebase.core.database import SessionLocal
from quirebase.core.errors import ResourceUnavailable
from quirebase.core.storage import LocalObjectStore
from quirebase.library.audit import record_audit_event
from quirebase.models import (
    FileRevision,
    Job,
    PdfAnnotation,
    ProjectItem,
    ProjectMember,
    User,
)
from quirebase.operations.maintenance import check_objects, cleanup_exports
from quirebase.pipeline.inspection import create_thumbnail, export_annotations, inspect_pdf
from quirebase.search import reindex_all, search_index

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

JobHandler = Callable[["Session", Job, dict[str, Any]], dict[str, Any]]
JOB_HANDLERS: dict[str, JobHandler] = {}


def register_job_handler(kind: str, handler: JobHandler) -> None:
    if kind in JOB_HANDLERS:
        raise ValueError(f"job handler already registered: {kind}")
    JOB_HANDLERS[kind] = handler


def get_job_handler(kind: str) -> JobHandler:
    handler = JOB_HANDLERS.get(kind)
    if handler is None:
        raise ValueError(f"unknown job kind: {kind}")
    return handler


def handle_pdf_inspect(db: Session, job: Job, payload: dict[str, Any]) -> dict[str, Any]:
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
    create_thumbnail(path, get_settings().object_dir / "thumbnails" / f"{revision.id}.png")
    search_index(db).index_item(db, revision.item_id)
    revision.processing_state = "ready"
    return {"page_count": pages}


def handle_pdf_export_annotations(db: Session, job: Job, payload: dict[str, Any]) -> dict[str, Any]:
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
    return {"filename": filename}


def handle_system_reindex(db: Session, job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    count = reindex_all(db)
    return {"reindexed_items": count}


def handle_system_check_objects(db: Session, job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    errors = check_objects(db)
    return {"errors": errors, "checked_status": "ok" if not errors else "inconsistencies_found"}


def handle_system_backup(db: Session, job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    from quirebase.operations.maintenance import create_backup

    filename = f"backup_{job.id}.zip"
    dest_path = get_settings().export_dir / filename
    create_backup(dest_path)
    return {"filename": filename, "size_bytes": dest_path.stat().st_size}


JOB_HANDLERS.update({
    "pdf.inspect": handle_pdf_inspect,
    "pdf.export_annotations": handle_pdf_export_annotations,
    "system.reindex_all": handle_system_reindex,
    "system.check_objects": handle_system_check_objects,
    "system.backup": handle_system_backup,
})


def enqueue_job(
    db: Session,
    kind: str,
    payload: dict[str, Any],
    owner_id: str | None = None,
    idempotency_key: str | None = None,
) -> Job:
    import uuid

    key = idempotency_key or f"{kind}:{uuid.uuid4()}"
    job = Job(
        kind=kind,
        payload=json.dumps(payload, ensure_ascii=False),
        owner_id=owner_id,
        idempotency_key=key,
    )
    db.add(job)
    db.flush()
    return job


def dispatch_maintenance_job(db: Session, admin: User, kind: str) -> Job:
    from quirebase.core.errors import ValidationFailure

    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    if kind not in ("system.reindex_all", "system.check_objects", "system.backup"):
        raise ValidationFailure(f"unknown maintenance job kind: {kind}")
    job = enqueue_job(db, kind, {}, owner_id=admin.id)
    record_audit_event(
        db,
        admin.id,
        f"admin.maintenance.{kind.removeprefix('system.')}",
        "job",
        job.id,
    )
    db.commit()
    return job


def list_jobs_admin(
    db: Session,
    admin: User,
    state: str = "",
    kind_prefix: str = "",
    limit: int = 50,
) -> list[Job]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    query = select(Job)
    if state.strip():
        query = query.where(Job.state == state.strip())
    if kind_prefix.strip():
        query = query.where(Job.kind.startswith(kind_prefix.strip()))
    return list(db.scalars(query.order_by(Job.created_at.desc()).limit(limit)).all())


def retry_all_failed_jobs(db: Session, admin: User) -> int:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    failed = list(db.scalars(select(Job).where(Job.state == "failed")).all())
    for job in failed:
        job.state = "pending"
        job.attempts = 0
        job.error = None
        job.lease_until = None
    if failed:
        record_audit_event(
            db,
            admin.id,
            "admin.jobs.retry_all",
            "job",
            None,
            detail={"count": len(failed)},
        )
        db.commit()
    return len(failed)


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
    job_id = job.id
    attempts = job.attempts
    try:
        payload = json.loads(job.payload)
        if not isinstance(payload, dict):
            raise TypeError("job payload must be a JSON object")
        handler = get_job_handler(job.kind)
        result = handler(db, job, payload)
        job.result = json.dumps(result)
        job.state = "succeeded"
        job.error = None
        job.lease_until = None
        db.commit()
    except Exception as error:
        db.rollback()
        failed_job = db.get(Job, job_id)
        if failed_job:
            failed_job.error = f"{type(error).__name__}: {error}"[:4000]
            failed_job.state = "pending" if attempts < 3 else "failed"
            failed_job.lease_until = None
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
