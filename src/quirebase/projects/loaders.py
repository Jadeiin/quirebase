"""Project aggregate loaders scoped to a resolved Workspace context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.access import (
    ProjectContext,
    ResourceAction,
    WorkspaceContext,
    project_visibility_predicate,
    require_action,
    require_project_visibility,
)
from quirebase.access.scope import workspace_select
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import Project, ProjectItem, ProjectState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_project(db: AsyncSession, ctx: WorkspaceContext, project_id: str) -> Project | None:
    return await db.scalar(
        workspace_select(Project, ctx).where(
            Project.id == project_id,
            Project.state != ProjectState.deleted,
            project_visibility_predicate(ctx),
        )
    )


async def get_project_for_update(
    db: AsyncSession, ctx: WorkspaceContext, project_id: str
) -> Project | None:
    project = await db.scalar(
        workspace_select(Project, ctx)
        .where(Project.id == project_id, Project.state != ProjectState.deleted)
        .where(project_visibility_predicate(ctx))
        .with_for_update()
    )

    if project is not None:
        await require_project_visibility(db, ctx, project)
    return project


async def get_project_item(
    db: AsyncSession, ctx: WorkspaceContext, project_item_id: str
) -> ProjectItem | None:
    return await db.scalar(
        workspace_select(ProjectItem, ctx)
        .join(Project, Project.id == ProjectItem.project_id)
        .where(
            ProjectItem.id == project_item_id,
            project_visibility_predicate(ctx),
        )
    )


async def require_project(
    db: AsyncSession,
    ctx: WorkspaceContext,
    project_id: str,
) -> ProjectContext:
    """Load a readable Project; commands authorize their exact operation under locks."""
    require_action(ctx, ResourceAction.workspace_read)
    project = await get_project(db, ctx, project_id)
    if project is None:
        raise ResourceUnavailable("Project not found")
    return ProjectContext(ctx, project)


async def require_project_item(
    db: AsyncSession,
    ctx: WorkspaceContext,
    project_item_id: str,
) -> tuple[ProjectContext, ProjectItem]:
    project_item = await get_project_item(db, ctx, project_item_id)
    if project_item is None:
        raise ResourceUnavailable("Project item not found")
    project_ctx = await require_project(db, ctx, project_item.project_id)
    return project_ctx, project_item
