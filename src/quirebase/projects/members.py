from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.audit import record_event
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.models import Project, ProjectMember, ProjectRole, User

from ._locking import lock_project_root

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ProjectMemberConflict(DomainError):
    pass


async def add_project_member(
    db: AsyncSession,
    user: User,
    project_id: str,
    username: str,
    role: ProjectRole | str = ProjectRole.viewer,
) -> ProjectMember:
    await lock_project_root(db, project_id)
    project = await db.get(Project, project_id, populate_existing=True)
    if project is None or user.id != project.owner_id:
        raise ResourceUnavailable("project not found or owner role required")
    try:
        requested_role = ProjectRole(role)
    except ValueError as error:
        raise ValidationFailure("invalid project role") from error
    if requested_role is ProjectRole.owner:
        raise ValidationFailure("use ownership transfer to assign the owner role")
    target = await db.scalar(
        select(User).where(User.username == username.strip(), User.active.is_(True))
    )
    if target is None:
        raise ResourceNotFound("user not found")
    if target.id == project.owner_id:
        raise ProjectMemberConflict("the owner role can only change through ownership transfer")
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
    await lock_project_root(db, project_id)
    project = await db.get(Project, project_id, populate_existing=True)
    target = await db.get(ProjectMember, (project_id, member_id), populate_existing=True)
    if project is None or user.id != project.owner_id or target is None:
        raise ResourceUnavailable("project or member not found")
    if target.user_id == project.owner_id:
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
