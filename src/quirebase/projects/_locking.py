from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.core.errors import ResourceUnavailable
from quirebase.models import Project, ProjectState, ProjectVisibility, Workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def lock_project_membership_workspace(db: AsyncSession, workspace_id: str) -> None:
    """Serialize Project participation with Workspace membership and User deactivation.

    Call before locking a Project root. Both commands can change the set of active
    participants in a members-visible Project, so they need one common root lock.
    """
    workspace = await db.scalar(
        select(Workspace.id).where(Workspace.id == workspace_id).with_for_update()
    )
    if workspace is None:
        raise ResourceUnavailable("Workspace not found")


async def lock_project_root(
    db: AsyncSession,
    project_id: str,
    workspace_id: str,
    *,
    state: ProjectState | None = None,
    visibility: ProjectVisibility | None = None,
    message: str = "project not found",
) -> Project:
    """Lock the Project root at a command's linearization point.

    This is deliberately private to the Projects owning module; callers never
    assemble a cross-aggregate lock graph.
    """
    predicates = [Project.id == project_id, Project.workspace_id == workspace_id]
    if state is not None:
        predicates.append(Project.state == state)
    if visibility is not None:
        predicates.append(Project.visibility == visibility)
    project = await db.scalar(
        select(Project)
        .where(*predicates)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if project is None:
        raise ResourceUnavailable(message)
    return project


async def lock_project_delete(
    db: AsyncSession,
    project_id: str,
    workspace_id: str,
    *,
    message: str = "project not found",
) -> Project:
    """Lock a Project that is about to be deleted with a full UPDATE lock."""
    project = await db.scalar(
        select(Project)
        .where(Project.id == project_id, Project.workspace_id == workspace_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if project is None:
        raise ResourceUnavailable(message)
    return project


async def guard_project(
    db: AsyncSession,
    project_id: str,
    *,
    state: ProjectState | None = None,
    visibility: ProjectVisibility | None = None,
    message: str = "project not found",
) -> Project:
    """Acquire a shared root lock for short-lived association commands."""
    predicates = [Project.id == project_id]
    if state is not None:
        predicates.append(Project.state == state)
    if visibility is not None:
        predicates.append(Project.visibility == visibility)
    project = await db.scalar(
        select(Project)
        .where(*predicates)
        .execution_options(populate_existing=True)
        .with_for_update(read=True)
    )
    if project is None:
        raise ResourceUnavailable(message)
    return project
