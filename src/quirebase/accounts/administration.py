from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, or_, select

from quirebase.core.crypto import hash_password
from quirebase.core.errors import (
    PermissionDenied,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.library.audit import record_audit_event
from quirebase.models import Invitation, Job, LoginSession, SystemRole, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def list_users(db: Session, admin: User) -> list[User]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    return list(db.scalars(select(User).order_by(User.username)).all())


def list_users_paginated(
    db: Session,
    admin: User,
    search: str = "",
    role: str = "",
    active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[User], int]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    query = select(User)
    count_query = select(func.count(User.id))
    filters = []
    if search.strip():
        term = f"%{search.strip()}%"
        filters.append(or_(User.username.ilike(term), User.id == search.strip()))
    if role.strip() and role in ("administrator", "member"):
        filters.append(User.role == role)
    if active is not None:
        filters.append(User.active == active)
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    total = db.scalar(count_query) or 0
    offset = max(0, (page - 1) * page_size)
    users = list(db.scalars(query.order_by(User.username).offset(offset).limit(page_size)).all())
    return users, total


def create_user_admin(
    db: Session, admin: User, username: str, password: str, role: str = "member"
) -> User:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    cleaned_name = username.strip()
    if not cleaned_name or len(cleaned_name) > 120:
        raise ValidationFailure("username must contain 1 to 120 characters")
    if len(password) < 12:
        raise ValidationFailure("password must contain at least 12 characters")
    if role not in (SystemRole.administrator.value, SystemRole.member.value):
        raise ValidationFailure("invalid user role")
    existing = db.scalar(select(User).where(User.username == cleaned_name))
    if existing is not None:
        raise ValidationFailure(f"username '{cleaned_name}' is already taken")
    user = User(
        username=cleaned_name,
        password_hash=hash_password(password),
        role=role,
        active=True,
    )
    db.add(user)
    db.flush()
    record_audit_event(
        db,
        admin.id,
        "admin.user.create",
        "user",
        user.id,
        detail={"username": user.username, "role": user.role},
    )
    db.commit()
    return user


def update_user_status(db: Session, admin: User, user_id: str, active: bool) -> User:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    user = db.get(User, user_id)
    if user is None:
        raise ResourceNotFound("user not found")
    if user.id == admin.id and not active:
        raise PermissionDenied("administrators cannot deactivate their own account")
    user.active = active
    if not active:
        # Revoke all active sessions upon deactivation
        db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    record_audit_event(
        db,
        admin.id,
        "admin.user.status_update",
        "user",
        user.id,
        detail={"active": active},
    )
    db.commit()
    return user


def change_user_role(db: Session, admin: User, user_id: str, new_role: str) -> User:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    if new_role not in (SystemRole.administrator.value, SystemRole.member.value):
        raise ValidationFailure("invalid user role")
    user = db.get(User, user_id)
    if user is None:
        raise ResourceNotFound("user not found")
    if user.id == admin.id and new_role != SystemRole.administrator.value:
        raise PermissionDenied("administrators cannot demote their own account")
    user.role = new_role
    record_audit_event(
        db,
        admin.id,
        "admin.user.role_change",
        "user",
        user.id,
        detail={"new_role": new_role},
    )
    db.commit()
    return user


def reset_user_password(db: Session, admin: User, user_id: str, new_password: str) -> None:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    if len(new_password) < 12:
        raise ValidationFailure("password must contain at least 12 characters")
    user = db.get(User, user_id)
    if user is None:
        raise ResourceNotFound("user not found")
    user.password_hash = hash_password(new_password)
    # Revoke sessions after password reset
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    record_audit_event(
        db,
        admin.id,
        "admin.user.password_reset",
        "user",
        user.id,
    )
    db.commit()


def revoke_user_sessions(db: Session, admin: User, user_id: str) -> int:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    user = db.get(User, user_id)
    if user is None:
        raise ResourceNotFound("user not found")
    result = db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    deleted_count = result.rowcount if hasattr(result, "rowcount") else 1
    record_audit_event(
        db,
        admin.id,
        "admin.user.sessions_revoked",
        "user",
        user.id,
    )
    db.commit()
    return deleted_count


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
    record_audit_event(
        db,
        admin.id,
        "admin.job.retry",
        "job",
        job.id,
    )
    db.commit()
