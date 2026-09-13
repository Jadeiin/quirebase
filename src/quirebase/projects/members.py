from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from quirebase.audit import record_event
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.models import Project, ProjectMember, ProjectRole, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ProjectMemberConflict(DomainError):
    pass


async def _active_user(db: AsyncSession, user: User) -> User:
    current = await db.get(User, user.id, populate_existing=True)
    if current is None or not current.active:
        raise ResourceUnavailable("user is not active")
    return current


async def add_project_member(
    db: AsyncSession,
    user: User,
    project_id: str,
    username: str,
    role: ProjectRole | str = ProjectRole.viewer,
) -> ProjectMember:
    user = await _active_user(db, user)
    project = await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise ResourceUnavailable("project not found or owner role required")
    actor = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    if actor is None or actor.role != ProjectRole.owner:
        raise ResourceUnavailable("project not found or owner role required")
    try:
        requested_role = ProjectRole(role)
    except ValueError as error:
        raise ValidationFailure("invalid project role") from error
    target = await db.scalar(
        select(User).where(User.username == username.strip(), User.active.is_(True))
    )
    if target is None:
        raise ResourceNotFound("user not found")
    existing = await db.get(ProjectMember, (project_id, target.id), populate_existing=True)
    if existing:
        existing.role = requested_role
        member = existing
    else:
        member = ProjectMember(project_id=project_id, user_id=target.id, role=requested_role)
        db.add(member)
    record_event(
        db,
        user.id,
        "project.member.set",
        "project",
        project_id,
        detail={"user_id": target.id, "role": requested_role},
    )
    await db.commit()
    return member


async def remove_project_member(
    db: AsyncSession,
    user: User,
    project_id: str,
    member_id: str,
) -> None:
    user = await _active_user(db, user)
    project = await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise ResourceUnavailable("project not found or owner role required")
    actor = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    target = await db.get(ProjectMember, (project_id, member_id), populate_existing=True)
    if actor is None or actor.role != ProjectRole.owner or target is None:
        raise ResourceUnavailable("project or member not found")
    if target.role == ProjectRole.owner:
        owner_count = await db.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.role == ProjectRole.owner)
        )
        if (owner_count or 0) <= 1:
            raise ProjectMemberConflict("a project must retain an owner")
    await db.delete(target)
    record_event(
        db,
        user.id,
        "project.member.remove",
        "project",
        project_id,
        detail={"user_id": member_id},
    )
    await db.commit()
