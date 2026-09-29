from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import false, or_, select

from quirebase.access.context import (
    ProjectContext,
    WorkspaceContext,
    lock_workspace_context,
    require_action,
    require_workspace_membership,
)
from quirebase.access.scope import workspace_select
from quirebase.access.workspace_policy import ResourceAction, action_allowed, action_spec
from quirebase.core.errors import ResourceUnavailable, WorkspaceLifecycleError
from quirebase.models import Project, ProjectMember, ProjectParticipation, ProjectState, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def visible_project_ids_query(ctx: WorkspaceContext):
    """Select Projects discoverable to this active Workspace member.

    SQL applies the canonical Workspace and participation facts. Casbin decides which relation
    classes the current Workspace role may discover in the current lifecycle state.
    """
    query = select(Project.id).where(
        Project.workspace_id == ctx.workspace_id,
        Project.state != ProjectState.deleted,
    )
    relation_predicates = [
        Project.participation == participation
        for participation in (ProjectParticipation.workspace, ProjectParticipation.open)
        if action_allowed(
            ctx,
            ResourceAction.project_discover,
            relation=participation.value,
        )
    ]
    if action_allowed(ctx, ResourceAction.project_discover, relation="managed"):
        relation_predicates.append(Project.participation == ProjectParticipation.managed)
    if action_allowed(ctx, ResourceAction.project_discover, relation="participant"):
        member_project_ids = select(ProjectMember.project_id).where(
            ProjectMember.workspace_id == ctx.workspace_id,
            ProjectMember.user_id == ctx.actor_id,
        )
        relation_predicates.append(Project.id.in_(member_project_ids))
    return query.where(or_(*relation_predicates) if relation_predicates else false())


async def require_project_access(
    db: AsyncSession,
    ctx: WorkspaceContext,
    project: Project,
    *,
    write: bool = False,
) -> ProjectContext:
    """Apply Project lineage/lifecycle after Workspace authorization.

    `ProjectMember` gates discoverability only for managed Projects. It never grants Workspace
    authority or access to canonical Workspace Items.
    """

    require_action(
        ctx,
        ResourceAction.project_update if write else ResourceAction.workspace_read,
    )
    return await require_project_visibility(db, ctx, project, write=write)


async def require_project_visibility(
    db: AsyncSession,
    ctx: WorkspaceContext,
    project: Project,
    *,
    write: bool = False,
) -> ProjectContext:
    """Check target lineage, lifecycle and discoverability without a second action gate."""
    if project.workspace_id != ctx.workspace.id or project.state is ProjectState.deleted:
        raise ResourceUnavailable("Project not found")
    # Governance discoverability comes from the managed-discovery decision. Every other
    # Workspace member must be an explicit Project participant before ordinary
    # Project reads or mutations proceed.
    discoverable = action_allowed(
        ctx,
        ResourceAction.project_discover,
        relation=project.participation.value,
    )
    if not discoverable and project.participation is ProjectParticipation.managed:
        member_id = await db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.workspace_id == ctx.workspace_id,
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == ctx.actor_id,
            )
        )
        discoverable = member_id is not None and action_allowed(
            ctx,
            ResourceAction.project_discover,
            relation="participant",
        )
    if not discoverable:
        raise ResourceUnavailable("Project not found")
    if write and project.state is not ProjectState.active:
        raise WorkspaceLifecycleError("Project is read-only")
    return ProjectContext(ctx, project)


async def require_project_context(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
    project_id: str,
    operation: ResourceAction,
    *,
    relation: str = "any",
) -> ProjectContext:
    mutating = action_spec(operation).mutating
    workspace = (
        await lock_workspace_context(db, actor, workspace_id)
        if mutating
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
    if mutating:
        # Project lifecycle changes take an exclusive root lock. Keep a shared
        # lock until the scoped write commits, then inspect the refreshed state.
        project_query = project_query.with_for_update(read=True)
    project = await db.scalar(project_query)
    if project is None:
        raise ResourceUnavailable("Project not found")
    project_context = await require_project_visibility(
        db,
        workspace,
        project,
        write=False,
    )
    require_action(workspace, operation, relation=relation)
    if mutating and project.state is not ProjectState.active:
        raise WorkspaceLifecycleError("Project is read-only")
    return project_context
