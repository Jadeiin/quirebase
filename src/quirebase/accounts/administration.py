from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.models import Invitation, Job, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def list_users(db: Session, admin: User) -> list[User]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    return list(db.scalars(select(User).order_by(User.username)).all())


def list_invitations(db: Session, admin: User) -> list[Invitation]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    return list(db.scalars(select(Invitation).order_by(Invitation.created_at.desc())).all())


def list_failed_jobs(db: Session, admin: User) -> list[Job]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    return list(
        db.scalars(select(Job).where(Job.state == "failed").order_by(Job.updated_at.desc())).all()
    )


def retry_job(db: Session, admin: User, job_id: str) -> None:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    job = db.get(Job, job_id)
    if job is None or job.state != "failed":
        raise ResourceNotFound("failed job not found")
    job.state = "pending"
    job.attempts = 0
    job.error = None
    job.lease_until = None
    db.commit()
