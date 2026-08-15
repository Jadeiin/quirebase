from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from quirebase.access.projects import project_member, require_project_member
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.models import AuditEvent, ProjectMember, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ProjectMemberConflict(DomainError):
    pass


def list_project_members(db: Session, user: User, project_id: str) -> list[tuple[User, str]]:
    require_project_member(db, user, project_id)
    rows = db.execute(
        select(User, ProjectMember.role)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.username)
    ).all()
    return [(row[0], row[1]) for row in rows]


def add_project_member(
    db: Session,
    user: User,
    project_id: str,
    username: str,
    role: str = "viewer",
) -> ProjectMember:
    actor = project_member(db, user, project_id)
    if actor is None or actor.role != "owner":
        raise ResourceUnavailable("project not found or owner role required")
    if role not in ("owner", "editor", "viewer"):
        raise ValidationFailure("invalid project role")
    target = db.scalar(select(User).where(User.username == username.strip(), User.active.is_(True)))
    if target is None:
        raise ResourceNotFound("user not found")
    existing = db.get(ProjectMember, (project_id, target.id))
    if existing:
        existing.role = role
        member = existing
    else:
        member = ProjectMember(project_id=project_id, user_id=target.id, role=role)
        db.add(member)
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="project.member.set",
            target_type="project",
            target_id=project_id,
            detail=json.dumps({"user_id": target.id, "role": role}),
        )
    )
    db.commit()
    return member


def remove_project_member(
    db: Session,
    user: User,
    project_id: str,
    member_id: str,
) -> None:
    actor = project_member(db, user, project_id)
    target = db.get(ProjectMember, (project_id, member_id))
    if actor is None or actor.role != "owner" or target is None:
        raise ResourceUnavailable("project or member not found")
    owner_count = db.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(ProjectMember.project_id == project_id, ProjectMember.role == "owner")
    )
    if target.role == "owner" and (owner_count or 0) <= 1:
        raise ProjectMemberConflict("a project must retain an owner")
    db.delete(target)
    db.commit()
