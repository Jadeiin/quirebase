from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sqlalchemy import or_, select

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


def visible_project_ids_query(ctx: WorkspaceContext):
    """Select Projects discoverable to this active Workspace member.

    Participation defines ordinary discovery. Policy grants only the additional ability to
    inspect managed Projects for Workspace governance.
    """
    query = select(Project.id).where(
        Project.workspace_id == ctx.workspace_id,
        Project.state != ProjectState.deleted,
    )
    relation_predicates: list[ColumnElement[bool]] = [
        Project.participation.in_((ProjectParticipation.workspace, ProjectParticipation.open))
    ]
    if action_allowed(ctx, ResourceAction.project_governance_read):
        relation_predicates.append(Project.participation == ProjectParticipation.managed)
    else:
        member_project_ids = select(ProjectMember.project_id).where(
            ProjectMember.workspace_id == ctx.workspace_id,
            ProjectMember.user_id == ctx.actor_id,
        )
        relation_predicates.append(
            (Project.participation == ProjectParticipation.managed)
            & Project.id.in_(member_project_ids)
        )
    return query.where(or_(*relation_predicates))


async def require_project_visibility(
    db: AsyncSession,
    ctx: WorkspaceContext,
    project: Project,
) -> ProjectContext:
    """Check target lineage, lifecycle and discoverability without a second action gate."""
    if project.workspace_id != ctx.workspace.id or project.state is ProjectState.deleted:
        raise ResourceUnavailable("Project not found")
    discoverable = project.participation is not ProjectParticipation.managed or action_allowed(
        ctx, ResourceAction.project_governance_read
    )
    if not discoverable and project.participation is ProjectParticipation.managed:
        member_id = await db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.workspace_id == ctx.workspace_id,
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == ctx.actor_id,
            )
        )
        discoverable = member_id is not None
    if not discoverable:
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
            Project.state != ProjectState.deleted,
        )
        .execution_options(populate_existing=True)
    )
    if lock is not None:
        project_query = project_query.with_for_update(read=lock == "shared")
    project = await db.scalar(project_query)
    if project is None:
        raise ResourceUnavailable("Project not found")
    project_context = await require_project_visibility(
        db,
        workspace,
        project,
    )
    require_action(workspace, operation, relation=relation)
    if mutating and project.state is not ProjectState.active:
        raise ProjectLifecycleError("Project is read-only")
    return project_context
