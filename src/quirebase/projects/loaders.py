"""Project aggregate loaders scoped to a resolved Workspace context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.access import (
    ProjectContext,
    ResourceAction,
    WorkspaceContext,
    project_discovery_predicate,
    require_action,
)
from quirebase.access.scope import workspace_select
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import Project, ProjectItem

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def get_project(db: AsyncSession, ctx: WorkspaceContext, project_id: UUID) -> Project | None:
    return await db.scalar(
        workspace_select(Project, ctx).where(
            Project.id == project_id,
            project_discovery_predicate(ctx),
        )
    )


async def get_project_item(
    db: AsyncSession, ctx: WorkspaceContext, project_item_id: UUID
) -> ProjectItem | None:
    return await db.scalar(
        workspace_select(ProjectItem, ctx)
        .join(Project, Project.id == ProjectItem.project_id)
        .where(
            ProjectItem.id == project_item_id,
            project_discovery_predicate(ctx),
        )
    )


async def require_project(
    db: AsyncSession,
    ctx: WorkspaceContext,
    project_id: UUID,
) -> ProjectContext:
    """Load a readable Project; commands authorize their exact operation under locks."""
    require_action(ctx, ResourceAction.workspace_read)
    project = await get_project(db, ctx, project_id)
    if project is None:
        raise ResourceUnavailable("Project not found")
    return ProjectContext(ctx, project)
