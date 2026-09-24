"""Project aggregate loaders scoped to a resolved Workspace context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.access.scope import workspace_select
from quirebase.access.workspaces import (
    ProjectContext,
    WorkspaceContext,
    require_project_access,
    visible_project_ids_query,
)
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import Project, ProjectItem, ProjectState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_project(db: AsyncSession, ctx: WorkspaceContext, project_id: str) -> Project | None:
    return await db.scalar(
        workspace_select(Project, ctx).where(
            Project.id == project_id,
            Project.state != ProjectState.deleted,
            Project.id.in_(visible_project_ids_query(ctx)),
        )
    )


async def get_project_for_update(
    db: AsyncSession, ctx: WorkspaceContext, project_id: str
) -> Project | None:
    return await db.scalar(
        workspace_select(Project, ctx)
        .where(Project.id == project_id, Project.state != ProjectState.deleted)
        .where(Project.id.in_(visible_project_ids_query(ctx)))
        .with_for_update()
    )


async def get_project_item(
    db: AsyncSession, ctx: WorkspaceContext, project_item_id: str
) -> ProjectItem | None:
    return await db.scalar(
        workspace_select(ProjectItem, ctx)
        .join(Project, Project.id == ProjectItem.project_id)
        .where(
            ProjectItem.id == project_item_id,
            Project.id.in_(visible_project_ids_query(ctx)),
        )
    )


async def require_project(
    db: AsyncSession,
    ctx: WorkspaceContext,
    project_id: str,
    *,
    write: bool = False,
) -> ProjectContext:
    project = await get_project(db, ctx, project_id)
    if project is None:
        raise ResourceUnavailable("Project not found")
    return await require_project_access(db, ctx, project, write=write)


async def require_project_item(
    db: AsyncSession,
    ctx: WorkspaceContext,
    project_item_id: str,
    *,
    write: bool = False,
) -> tuple[ProjectContext, ProjectItem]:
    project_item = await get_project_item(db, ctx, project_item_id)
    if project_item is None:
        raise ResourceUnavailable("Project item not found")
    project_ctx = await require_project(db, ctx, project_item.project_id, write=write)
    return project_ctx, project_item
