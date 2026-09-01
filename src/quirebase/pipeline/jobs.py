from __future__ import annotations

import asyncio
import json
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.core.storage import get_object_store
from quirebase.core.timezones import annotation_export_timezone
from quirebase.models import (
    AnnotationScope,
    FileRevision,
    FileRevisionProcessingState,
    Job,
    JobState,
    PdfAnnotation,
    ProjectItem,
    ProjectMember,
    User,
)
from quirebase.operations.maintenance import check_objects, cleanup_exports
from quirebase.pipeline.derived_state import propagate_file_revision_change
from quirebase.pipeline.inspection import create_thumbnail, export_annotations, inspect_pdf
from quirebase.search import reindex_all

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

JobHandler = Callable[["AsyncSession", Job, dict[str, Any]], Awaitable[dict[str, Any]]]
JOB_HANDLERS: dict[str, JobHandler] = {}


def normalize_job_kind(kind: str) -> str:
    normalized = kind.strip()
    if not normalized or len(normalized) > 40:
        raise ValidationFailure("job kind must contain 1 to 40 characters")
    return normalized


def complete_revision_inspection(
    revision: FileRevision,
    *,
    page_count: int,
    page_geometry: str,
    full_text: str,
) -> None:
    revision.page_count = page_count
    revision.page_geometry = page_geometry
    revision.full_text = full_text
    revision.processing_state = FileRevisionProcessingState.ready


def reset_job_for_retry(job: Job) -> None:
    job.state = JobState.pending
    job.attempts = 0
    job.error = None
    job.lease_until = None


def mark_job_running(job: Job, now: datetime) -> None:
    job.state = JobState.running
    job.lease_until = now + timedelta(minutes=10)
    job.attempts += 1


def mark_job_succeeded(job: Job, result: dict[str, Any]) -> None:
    job.result = json.dumps(result)
    job.state = JobState.succeeded
    job.error = None
    job.lease_until = None


def record_job_failure(job: Job, error: Exception, attempts: int) -> None:
    job.error = f"{type(error).__name__}: {error}"[:4000]
    job.state = JobState.pending if attempts < 3 else JobState.failed
    job.lease_until = None


def register_job_handler(kind: str, handler: JobHandler) -> None:
    if kind in JOB_HANDLERS:
        raise ValueError(f"job handler already registered: {kind}")
    JOB_HANDLERS[kind] = handler


def get_job_handler(kind: str) -> JobHandler:
    handler = JOB_HANDLERS.get(kind)
    if handler is None:
        raise ValueError(f"unknown job kind: {kind}")
    return handler


async def handle_pdf_inspect(db: AsyncSession, job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    revision = await db.get(FileRevision, payload["revision_id"])
    if revision is None:
        raise ValueError("revision no longer exists")
    store = get_object_store()
    async with store.materialize(revision.object_key) as path:
        pages, text, geometry = await asyncio.to_thread(inspect_pdf, path)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as thumbnail:
            thumbnail_path = Path(thumbnail.name)
        try:
            await asyncio.to_thread(create_thumbnail, path, thumbnail_path)
            await store.put(f"thumbnails/{revision.id}.png", thumbnail_path)
        finally:
            await asyncio.to_thread(thumbnail_path.unlink, missing_ok=True)
    if pages < 1:
        raise ValueError("PDF contains no pages")
    geometry_json = json.dumps(geometry, separators=(",", ":"))
    complete_revision_inspection(
        revision,
        page_count=pages,
        page_geometry=geometry_json,
        full_text=text,
    )
    await propagate_file_revision_change(db, revision.item_id, owner_id=job.owner_id)
    return {"page_count": pages}


async def handle_pdf_export_annotations(
    db: AsyncSession, job: Job, payload: dict[str, Any]
) -> dict[str, Any]:
    revision = await db.get(FileRevision, payload["revision_id"])
    if revision is None:
        raise ValueError("revision no longer exists")
    scopes = []
    if payload.get("include_private"):
        scopes.append(
            and_(
                PdfAnnotation.scope == AnnotationScope.private,
                PdfAnnotation.author_id == job.owner_id,
            )
        )
    if payload.get("project_id"):
        membership = await db.get(ProjectMember, (payload["project_id"], job.owner_id))
        assignment = await db.get(ProjectItem, (payload["project_id"], revision.item_id))
        if membership is None or assignment is None:
            raise PermissionError("project membership no longer exists")
        scopes.append(
            and_(
                PdfAnnotation.scope == AnnotationScope.project,
                PdfAnnotation.project_id == payload["project_id"],
            )
        )
    records = (
        []
        if not scopes
        else list(
            (
                await db.scalars(
                    select(PdfAnnotation)
                    .options(selectinload(PdfAnnotation.segments))
                    .where(
                        PdfAnnotation.file_revision_id == revision.id,
                        PdfAnnotation.deleted_at.is_(None),
                        or_(*scopes),
                    )
                )
            ).all()
        )
    )
    filename = f"{job.id}.pdf"
    object_key = f"artifacts/annotation-exports/{filename}"
    author_rows = (
        await db.execute(
            select(User.id, User.username).where(
                User.id.in_({record.author_id for record in records})
            )
        )
    ).all()
    author_names: dict[str, str] = {row[0]: row[1] for row in author_rows}
    display_timezone = annotation_export_timezone(payload.get("timezone"))
    store = get_object_store()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output:
        output_path = Path(output.name)
    try:
        async with store.materialize(revision.object_key) as source:
            await asyncio.to_thread(
                export_annotations,
                source,
                output_path,
                records,
                author_names=author_names,
                display_timezone=display_timezone,
            )
        metadata = await store.put(object_key, output_path)
    finally:
        await asyncio.to_thread(output_path.unlink, missing_ok=True)
    return {"filename": filename, "object_key": object_key, "size_bytes": metadata.size}


async def handle_system_reindex(
    db: AsyncSession, job: Job, payload: dict[str, Any]
) -> dict[str, Any]:
    count = await reindex_all(db)
    return {"reindexed_items": count}


async def handle_system_check_objects(
    db: AsyncSession, job: Job, payload: dict[str, Any]
) -> dict[str, Any]:
    errors = await check_objects(db)
    return {"errors": errors, "checked_status": "ok" if not errors else "inconsistencies_found"}


async def handle_system_backup(
    db: AsyncSession, job: Job, payload: dict[str, Any]
) -> dict[str, Any]:
    from quirebase.operations.maintenance import create_backup

    filename = f"backup_{job.id}.zip"
    dest_path = get_settings().export_dir / filename
    await create_backup(dest_path)
    size_bytes = await asyncio.to_thread(lambda: dest_path.stat().st_size)
    return {"filename": filename, "size_bytes": size_bytes}


async def handle_system_recommend_tags_all(
    db: AsyncSession, job: Job, payload: dict[str, Any]
) -> dict[str, Any]:
    from quirebase.library import enqueue_all_item_tag_recommendations

    return {"enqueued_items": await enqueue_all_item_tag_recommendations(db, owner_id=job.owner_id)}


async def handle_item_recommend_tags(
    db: AsyncSession, job: Job, payload: dict[str, Any]
) -> dict[str, Any]:
    from quirebase.library import handle_item_tag_recommendation

    return await handle_item_tag_recommendation(db, job, payload)


JOB_HANDLERS.update({
    "pdf.inspect": handle_pdf_inspect,
    "pdf.export_annotations": handle_pdf_export_annotations,
    "system.reindex_all": handle_system_reindex,
    "system.check_objects": handle_system_check_objects,
    "system.backup": handle_system_backup,
    "system.recommend_tags_all": handle_system_recommend_tags_all,
    "item.recommend_tags": handle_item_recommend_tags,
})


async def enqueue_job(
    db: AsyncSession,
    kind: str,
    payload: dict[str, Any],
    owner_id: str | None = None,
    idempotency_key: str | None = None,
) -> Job:
    import uuid

    normalized_kind = normalize_job_kind(kind)
    key = idempotency_key or f"{normalized_kind}:{uuid.uuid4()}"
    job = Job(
        kind=normalized_kind,
        payload=json.dumps(payload, ensure_ascii=False),
        owner_id=owner_id,
        idempotency_key=key,
    )
    db.add(job)
    await db.flush()
    return job


async def dispatch_maintenance_job(db: AsyncSession, admin: User, kind: str) -> Job:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    if kind not in (
        "system.reindex_all",
        "system.check_objects",
        "system.backup",
        "system.recommend_tags_all",
    ):
        raise ValidationFailure(f"unknown maintenance job kind: {kind}")
    job = await enqueue_job(db, kind, {}, owner_id=admin.id)
    record_event(
        db,
        admin.id,
        f"admin.maintenance.{kind.removeprefix('system.')}",
        "job",
        job.id,
    )
    await db.commit()
    return job


async def list_jobs_admin(
    db: AsyncSession,
    admin: User,
    state: str = "",
    limit: int = 50,
    *,
    kind_prefix: str = "",
) -> list[Job]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    query = select(Job)
    if state.strip():
        try:
            requested_state = JobState(state.strip())
        except ValueError as error:
            raise ValidationFailure(f"unknown job state: {state.strip()}") from error
        query = query.where(Job.state == requested_state)
    if kind_prefix.strip():
        query = query.where(Job.kind.startswith(kind_prefix.strip()))
    return list((await db.scalars(query.order_by(Job.created_at.desc()).limit(limit))).all())


async def retry_all_failed_jobs(db: AsyncSession, admin: User) -> int:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    failed = list((await db.scalars(select(Job).where(Job.state == JobState.failed))).all())
    for job in failed:
        reset_job_for_retry(job)
    if failed:
        record_event(
            db,
            admin.id,
            "admin.jobs.retry_all",
            "job",
            None,
            detail={"count": len(failed)},
        )
        await db.commit()
    return len(failed)


async def claim_job(db: AsyncSession) -> Job | None:
    now = datetime.now(UTC)
    query = (
        select(Job)
        .where(
            Job.state.in_([JobState.pending, JobState.running]),
            or_(Job.lease_until.is_(None), Job.lease_until < now),
            Job.attempts < 3,
        )
        .order_by(Job.created_at)
        .limit(1)
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    job = await db.scalar(query)
    if job:
        mark_job_running(job, now)
        await db.commit()
    return job


async def run_job(db: AsyncSession, job: Job) -> None:
    job_id = job.id
    attempts = job.attempts
    try:
        payload = json.loads(job.payload)
        if not isinstance(payload, dict):
            raise TypeError("job payload must be a JSON object")
        handler = get_job_handler(job.kind)
        result = await handler(db, job, payload)
        mark_job_succeeded(job, result)
        await db.commit()
    except Exception as error:
        await db.rollback()
        failed_job = await db.get(Job, job_id)
        if failed_job:
            record_job_failure(failed_job, error, attempts)
            await db.commit()


async def run_once() -> bool:
    async with AsyncSessionLocal() as db:
        job = await claim_job(db)
        if job is None:
            return False
        await run_job(db, job)
        return True


async def run_forever() -> None:
    last_cleanup = 0.0
    while True:
        if time.monotonic() - last_cleanup >= 3600:
            await cleanup_exports()
            last_cleanup = time.monotonic()
        if not await run_once():
            await asyncio.sleep(get_settings().worker_poll_seconds)
