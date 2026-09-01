from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from quirebase.access.documents import require_revision
from quirebase.access.projects import project_member
from quirebase.core.config import get_settings
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.models import FileRevision, Job, JobState, ProjectItem, User
from quirebase.pipeline.inspection import job_payload

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.documents.schemas import ExportCreate


async def create_export_job(db: AsyncSession, user: User, item_id: str, data: ExportCreate) -> Job:
    revision = await require_revision(db, user, data.revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    locked_revision = await db.scalar(
        select(FileRevision).where(FileRevision.id == revision.id).with_for_update()
    )
    if locked_revision is None:
        raise ResourceNotFound("revision not found for item")
    revision = locked_revision
    if data.project_id and (
        await project_member(db, user, data.project_id) is None
        or await db.get(ProjectItem, (data.project_id, item_id)) is None
    ):
        raise ResourceUnavailable("project membership or project item not found")
    job = Job(
        kind="pdf.export_annotations",
        payload=job_payload(
            revision_id=data.revision_id,
            project_id=data.project_id,
            include_private=data.include_private,
            timezone=data.timezone,
        ),
        idempotency_key=f"pdf.export:{user.id}:{data.revision_id}:{data.project_id}:{datetime.now(UTC).isoformat()}",
        owner_id=user.id,
    )
    db.add(job)
    await db.commit()
    return job


async def get_export_status(db: AsyncSession, user: User, job_id: str) -> dict[str, Any]:
    job = await db.get(Job, job_id)
    if job is None or job.kind != "pdf.export_annotations" or job.owner_id != user.id:
        raise ResourceNotFound("export job not found")
    return {"id": job.id, "state": job.state, "error": job.error}


async def get_export_file_path(db: AsyncSession, user: User, job_id: str) -> Path:
    job = await db.get(Job, job_id)
    if (
        job is None
        or job.kind != "pdf.export_annotations"
        or job.owner_id != user.id
        or job.state != JobState.succeeded
    ):
        raise ResourceNotFound("export job not found or not ready")
    result = json.loads(job.result or "{}")
    payload = json.loads(job.payload)
    revision = await require_revision(db, user, payload["revision_id"])
    if payload.get("project_id") and (
        await project_member(db, user, payload["project_id"]) is None
        or await db.get(ProjectItem, (payload["project_id"], revision.item_id)) is None
    ):
        raise ResourceUnavailable("project membership or project item not found")
    return get_settings().export_dir / result["filename"]
