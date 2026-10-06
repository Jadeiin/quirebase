from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sqlalchemy import and_, or_, select

from quirebase.access.context import (
    ProjectContext,
    WorkspaceContext,
    lock_workspace_context,
    require_action,
    require_workspace_membership,
)
from quirebase.access.scope import workspace_select
from quirebase.access.workspace_policy import ResourceAction, action_allowed, action_spec
from quirebase.core.errors import ProjectLifecycleError, ResourceUnavailable
from quirebase.models import Project, ProjectMember, ProjectParticipation, ProjectState, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement


def project_visibility_predicate(ctx: WorkspaceContext) -> ColumnElement[bool]:
    """One domain scope predicate for collection, direct and locked Project reads.

    Participation defines ordinary discovery; policy grants only the additional
    capability to inspect managed Projects for Workspace governance.
    """
    discoverable: ColumnElement[bool] = Project.participation.in_((
        ProjectParticipation.workspace,
        ProjectParticipation.open,
    ))
    if action_allowed(ctx, ResourceAction.project_governance_read):
        discoverable = or_(discoverable, Project.participation == ProjectParticipation.managed)
    else:
        member_project_ids = select(ProjectMember.project_id).where(
            ProjectMember.workspace_id == ctx.workspace_id,
            ProjectMember.user_id == ctx.actor_id,
        )
        discoverable = or_(
            discoverable,
            (Project.participation == ProjectParticipation.managed)
            & Project.id.in_(member_project_ids),
        )
    return and_(
        Project.workspace_id == ctx.workspace_id,
        Project.state != ProjectState.deleted,
        discoverable,
    )


def visible_project_ids_query(ctx: WorkspaceContext):
    return select(Project.id).where(project_visibility_predicate(ctx))


async def require_project_visibility(
    db: AsyncSession,
    ctx: WorkspaceContext,
    project: Project,
) -> ProjectContext:
    """Recheck discovery in a fresh statement after a root lock is acquired.

    A statement waiting for a Project lock can have a membership snapshot from
    before the prior transaction removed that participant.
    """
    visible = await db.scalar(
        select(Project.id).where(Project.id == project.id, project_visibility_predicate(ctx))
    )
    if visible is None:
        raise ResourceUnavailable("Project not found")
    return ProjectContext(ctx, project)


async def require_project_context(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
    project_id: str,
    operation: ResourceAction,
    *,
    relation: str = "any",
    lock: Literal["shared", "update"] | None = None,
) -> ProjectContext:
    mutating = action_spec(operation).mutating
    if mutating and lock is None:
        raise ValueError("Project mutations must explicitly select a root lock")
    workspace = (
        await lock_workspace_context(db, actor, workspace_id)
        if lock is not None
        else await require_workspace_membership(db, actor, workspace_id)
    )
    project_query = (
        workspace_select(Project, workspace)
        .where(
            Project.id == project_id,
            project_visibility_predicate(workspace),
        )
        .execution_options(populate_existing=True)
    )
    if lock is not None:
        project_query = project_query.with_for_update(read=lock == "shared")
    project = await db.scalar(project_query)
    if project is None:
        raise ResourceUnavailable("Project not found")
    project_context = (
        await require_project_visibility(db, workspace, project)
        if lock is not None
        else ProjectContext(workspace, project)
    )
    require_action(workspace, operation, relation=relation)
    if mutating and project.state is not ProjectState.active:
        raise ProjectLifecycleError("Project is read-only")
    return project_context
