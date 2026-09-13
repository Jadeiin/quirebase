from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.core.errors import PermissionDenied, ResourceUnavailable
from quirebase.models import Project, ProjectMember, ProjectRole, ProjectState, SystemRole, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def visible_projects(db: AsyncSession, user: User) -> list[Project]:
    query = select(Project).where(Project.state == ProjectState.active).order_by(Project.name)
    if user.role != SystemRole.administrator.value:
        member_project_ids = select(ProjectMember.project_id).where(
            ProjectMember.user_id == user.id
        )
        query = query.where((Project.owner_id == user.id) | Project.id.in_(member_project_ids))
    return list((await db.scalars(query)).all())


async def editable_projects(db: AsyncSession, user: User) -> list[Project]:
    return list(
        (
            await db.scalars(
                select(Project)
                .where(
                    Project.state == ProjectState.active,
                    (Project.owner_id == user.id)
                    | Project.id.in_(
                        select(ProjectMember.project_id).where(
                            ProjectMember.user_id == user.id,
                            ProjectMember.role == ProjectRole.editor,
                        )
                    ),
                )
                .order_by(Project.name)
            )
        ).all()
    )


async def project_member(
    db: AsyncSession, user: User, project_id: str | None
) -> ProjectMember | None:
    if project_id is None:
        return None
    project = await db.get(Project, project_id)
    member = await db.get(ProjectMember, (project_id, user.id))
    if project is None:
        return None
    if project.owner_id == user.id:
        if member is not None and member.role == ProjectRole.owner:
            return member
        return ProjectMember(project_id=project_id, user_id=user.id, role=ProjectRole.owner)
    if member is None:
        return None
    # ``owner`` is only authoritative when it matches Project.owner_id. Treat
    # a stale mirror as an ordinary read membership rather than an owner grant.
    if member.role == ProjectRole.owner:
        return ProjectMember(project_id=project_id, user_id=user.id, role=ProjectRole.viewer)
    return member


async def require_project_member(
    db: AsyncSession, user: User, project_id: str, allowed_roles: set[str] | None = None
) -> ProjectMember:
    member = await project_member(db, user, project_id)
    if member is None:
        if user.role == SystemRole.administrator.value:
            project = await db.get(Project, project_id)
            if project is None:
                raise ResourceUnavailable("project not found")
            return ProjectMember(
                project_id=project_id, user_id=user.id, role=SystemRole.administrator.value
            )
        raise ResourceUnavailable("project not found or membership required")
    if allowed_roles and member.role not in allowed_roles:
        raise PermissionDenied("insufficient project role permissions")
    return member
