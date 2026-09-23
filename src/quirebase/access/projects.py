from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.access.scope import workspace_select
from quirebase.access.workspaces import (
    Capability,
    WorkspaceContext,
    require_project_context,
    require_workspace_capability,
)
from quirebase.models import Project, ProjectMember, ProjectState, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def visible_projects(db: AsyncSession, user: User, workspace_id: str) -> list[Project]:
    context = await require_workspace_capability(db, user, workspace_id, Capability.workspace_read)
    return await visible_projects_for_context(db, context)


async def visible_projects_for_context(db: AsyncSession, ctx: WorkspaceContext) -> list[Project]:
    """List visible Projects without re-resolving Workspace membership."""

    member_ids = (
        workspace_select(ProjectMember, ctx)
        .where(ProjectMember.user_id == ctx.actor.id)
        .with_only_columns(ProjectMember.project_id)
    )
    return list(
        (
            await db.scalars(
                workspace_select(Project, ctx)
                .where(
                    Project.state != ProjectState.deleted,
                    (Project.visibility == "workspace") | Project.id.in_(member_ids),
                )
                .order_by(Project.name)
            )
        ).all()
    )


async def editable_projects(db: AsyncSession, user: User, workspace_id: str) -> list[Project]:
    await require_workspace_capability(db, user, workspace_id, Capability.projects_manage)
    visible = await visible_projects(db, user, workspace_id)
    return [project for project in visible if project.state is ProjectState.active]


async def project_member(
    db: AsyncSession, user: User, workspace_id: str, project_id: str | None
) -> ProjectMember | None:
    if project_id is None:
        return None
    return await db.scalar(
        select(ProjectMember).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )


async def require_project_member(
    db: AsyncSession, user: User, workspace_id: str, project_id: str
) -> ProjectMember:
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.workspace_read
    )
    if context.membership is None:
        from quirebase.core.errors import ResourceUnavailable

        raise ResourceUnavailable("Project membership required")
    return context.membership
