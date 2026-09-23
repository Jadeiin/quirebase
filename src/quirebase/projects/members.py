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
from .sharing import fork_owned_project_items

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
    actor = await db.get(ProjectMember, (project_id, user.id))
    if (
        project is None
        or project.state.value == "archived"
        or (actor is None or actor.role is not ProjectRole.admin)
    ):
        raise ResourceUnavailable("project not found or project admin role required")
    try:
        requested_role = ProjectRole(role)
    except ValueError as error:
        raise ValidationFailure("invalid project role") from error
    if requested_role not in (ProjectRole.admin, ProjectRole.editor, ProjectRole.viewer):
        raise ValidationFailure("invalid project role")
    target = await db.scalar(
        select(User).where(User.username == username.strip(), User.active.is_(True))
    )
    if target is None:
        raise ResourceNotFound("user not found")
    existing = await db.get(ProjectMember, (project_id, target.id), populate_existing=True)
    if existing:
        if (
            existing.role in (ProjectRole.admin, ProjectRole.editor)
            and requested_role is ProjectRole.viewer
        ):
            await fork_owned_project_items(db, project_id, target.id, user)
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
    actor = await db.get(ProjectMember, (project_id, user.id))
    if (
        project is None
        or project.state.value == "archived"
        or actor is None
        or actor.role is not ProjectRole.admin
        or target is None
    ):
        raise ResourceUnavailable("project or member not found")
    if target.role is ProjectRole.admin:
        remaining = await db.scalar(
            select(ProjectMember.user_id)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.role == ProjectRole.admin,
                ProjectMember.user_id != target.user_id,
                User.active.is_(True),
            )
            .limit(1)
        )
        if remaining is None:
            raise ProjectMemberConflict("a project must retain an active admin")
    if target.role in (ProjectRole.admin, ProjectRole.editor):
        await fork_owned_project_items(db, project_id, target.user_id, user)
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
