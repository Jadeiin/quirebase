from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import false, inspect, or_, select

from quirebase.access.authorization import (
    ResourceActionKey,
    workspace_action_allowed,
)
from quirebase.access.scope import workspace_select
from quirebase.core.errors import (
    PermissionDenied,
    ResourceUnavailable,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
)
from quirebase.models import (
    Project,
    ProjectMember,
    ProjectState,
    ProjectVisibility,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ResourceAction(ResourceActionKey):
    """One canonical Workspace-scoped authorization resource/action pair."""

    workspace_read = "workspace.read"
    workspace_export = "workspace.export"
    workspace_update = "workspace.update"
    workspace_archive = "workspace.archive"
    workspace_restore = "workspace.restore"
    workspace_delete = "workspace.delete"
    item_copy = "item.copy"
    item_create = "item.create"
    item_update = "item.update"
    item_delete = "item.delete"
    file_manage = "file.manage"
    file_delete = "file.delete"
    tag_use = "tag.use"
    tag_create = "tag.create"
    tag_manage = "tag.manage"
    citation_style_manage = "citation_style.manage"
    project_create = "project.create"
    project_update = "project.update"
    project_archive = "project.archive"
    project_restore = "project.restore"
    project_delete = "project.delete"
    project_item_manage = "project_item.manage"
    project_discover = "project.discover"
    project_membership_join = "project_membership.join"
    project_membership_leave = "project_membership.leave"
    project_membership_manage = "project_membership.manage"
    workspace_invitation_read = "workspace_invitation.read"
    workspace_invitation_create = "workspace_invitation.create"
    workspace_invitation_revoke = "workspace_invitation.revoke"
    workspace_member_read = "workspace_member.read"
    workspace_member_change_role = "workspace_member.change_role"
    workspace_member_promote = "workspace_member.promote"
    workspace_member_suspend = "workspace_member.suspend"
    workspace_member_reactivate = "workspace_member.reactivate"
    workspace_member_terminate = "workspace_member.terminate"
    workspace_member_transfer_ownership = "workspace_member.transfer_ownership"
    item_discussion_create = "item_discussion.create"
    item_discussion_delete = "item_discussion.delete"
    project_discussion_create = "project_discussion.create"
    project_discussion_delete = "project_discussion.delete"
    private_annotation_create = "private_annotation.create"
    private_annotation_read = "private_annotation.read"
    private_annotation_update = "private_annotation.update"
    private_annotation_delete = "private_annotation.delete"
    private_annotation_restore = "private_annotation.restore"
    project_annotation_create = "project_annotation.create"
    project_annotation_read = "project_annotation.read"
    project_annotation_review = "project_annotation.review"
    project_annotation_update = "project_annotation.update"
    project_annotation_delete = "project_annotation.delete"
    project_annotation_restore = "project_annotation.restore"
    project_annotation_hide = "project_annotation.hide"
    project_annotation_archive = "project_annotation.archive"
    project_annotation_lock = "project_annotation.lock"
    project_annotation_unlock = "project_annotation.unlock"
    private_annotation_reply_create = "private_annotation_reply.create"
    private_annotation_reply_update = "private_annotation_reply.update"
    private_annotation_reply_delete = "private_annotation_reply.delete"
    private_annotation_reply_restore = "private_annotation_reply.restore"
    project_annotation_reply_create = "project_annotation_reply.create"
    project_annotation_reply_update = "project_annotation_reply.update"
    project_annotation_reply_delete = "project_annotation_reply.delete"
    project_annotation_reply_restore = "project_annotation_reply.restore"


# These sets classify database locking and Project visibility behavior. They do not grant access;
# every allow/deny result comes from Casbin.
_NON_MUTATING_ACTIONS = frozenset({
    ResourceAction.workspace_read,
    ResourceAction.workspace_export,
    ResourceAction.project_discover,
    ResourceAction.private_annotation_read,
    ResourceAction.project_annotation_read,
    ResourceAction.project_annotation_review,
})
_PROJECT_CONTENT_WRITE_ACTIONS = frozenset({
    ResourceAction.project_discussion_create,
    ResourceAction.project_discussion_delete,
    ResourceAction.project_annotation_create,
    ResourceAction.project_annotation_update,
    ResourceAction.project_annotation_delete,
    ResourceAction.project_annotation_restore,
    ResourceAction.project_annotation_reply_create,
    ResourceAction.project_annotation_reply_update,
    ResourceAction.project_annotation_reply_delete,
    ResourceAction.project_annotation_reply_restore,
})

# Relation vocabularies whose alternatives are useful to generic API consumers. They describe
# canonical request facts, not grants; Casbin remains the only source of allow/deny decisions.
_RESOURCE_ACTION_RELATIONS = {
    ResourceAction.project_create: tuple(visibility.value for visibility in ProjectVisibility),
}


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    actor: User
    workspace: Workspace
    membership: WorkspaceMember
    role: WorkspaceRole

    @property
    def actor_id(self) -> str:
        return self.actor.id

    @property
    def workspace_id(self) -> str:
        return self.workspace.id

    @property
    def allowed_actions(self) -> frozenset[ResourceAction]:
        return effective_resource_actions(
            self.role,
            self.workspace.state,
            governance_suspended=self.workspace.governance_suspended_at is not None,
        )


@dataclass(frozen=True, slots=True)
class ProjectContext:
    workspace: WorkspaceContext
    project: Project


async def resolve_workspace_context(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
) -> WorkspaceContext:
    """Resolve active Workspace context at a request/workflow boundary.

    Durable workflows must resolve this again during finalization; a previously
    resolved context is not a durable authorization checkpoint.
    """

    return await require_workspace_membership(db, actor, workspace_id)


def require_action(
    ctx: WorkspaceContext,
    resource_action: ResourceAction,
    *,
    relation: str = "any",
    message: str | None = None,
) -> WorkspaceContext:
    """Require one canonical resource/action decision from loaded facts."""

    return _require_workspace_decision(
        ctx,
        allowed=workspace_resource_action_allowed(
            ctx.role,
            ctx.workspace.state,
            resource_action,
            governance_suspended=ctx.workspace.governance_suspended_at is not None,
            relation=relation,
        ),
        active_allowed=workspace_action_allowed(
            ctx.role,
            resource_action.resource,
            resource_action.action,
            WorkspaceState.active,
            relation,
        ),
        message=message or f"Resource action required: {resource_action.value}",
    )


def workspace_resource_action_allowed(
    role: WorkspaceRole,
    state: WorkspaceState,
    resource_action: ResourceAction,
    *,
    governance_suspended: bool = False,
    relation: str = "any",
) -> bool:
    """Evaluate one resource/action pair through the sole Casbin policy source."""

    lifecycle = "suspended" if governance_suspended else state
    return workspace_action_allowed(
        role,
        resource_action.resource,
        resource_action.action,
        lifecycle,
        relation,
    )


# The packaged policy is immutable during a process, so Workspaces with the same role and
# lifecycle facts can share these immutable authorization projections.
@lru_cache(maxsize=128)
def effective_resource_actions(
    role: WorkspaceRole,
    state: WorkspaceState,
    *,
    governance_suspended: bool = False,
) -> frozenset[ResourceAction]:
    """Return relation-free resource actions available in a Workspace state."""

    return frozenset(
        resource_action
        for resource_action in ResourceAction
        if workspace_resource_action_allowed(
            role,
            state,
            resource_action,
            governance_suspended=governance_suspended,
        )
        or effective_resource_action_relations(
            role,
            state,
            resource_action,
            governance_suspended=governance_suspended,
        )
    )


@lru_cache(maxsize=128)
def effective_resource_action_relations(
    role: WorkspaceRole,
    state: WorkspaceState,
    resource_action: ResourceAction,
    *,
    governance_suspended: bool = False,
) -> frozenset[str]:
    """Return allowed canonical relations for a relation-constrained action."""

    return frozenset(
        relation
        for relation in _RESOURCE_ACTION_RELATIONS.get(resource_action, ())
        if workspace_resource_action_allowed(
            role,
            state,
            resource_action,
            governance_suspended=governance_suspended,
            relation=relation,
        )
    )


def action_allowed(
    ctx: WorkspaceContext,
    resource_action: ResourceAction,
    *,
    relation: str = "any",
) -> bool:
    """Evaluate a resource action without moving canonical fact loading into policy."""

    lifecycle = (
        "suspended" if ctx.workspace.governance_suspended_at is not None else ctx.workspace.state
    )
    return workspace_action_allowed(
        ctx.role,
        resource_action.resource,
        resource_action.action,
        lifecycle,
        relation,
    )


def workspace_member_relation(role: WorkspaceRole | str) -> str:
    """Normalize persistent Workspace roles to policy relation classes."""

    normalized = WorkspaceRole(role)
    if normalized is WorkspaceRole.owner:
        return "owner"
    if normalized is WorkspaceRole.admin:
        return "admin"
    return "member"


def _require_workspace_decision(
    ctx: WorkspaceContext,
    *,
    allowed: bool,
    active_allowed: bool,
    message: str,
) -> WorkspaceContext:
    if allowed:
        return ctx
    if active_allowed and (
        ctx.workspace.state is not WorkspaceState.active
        or ctx.workspace.governance_suspended_at is not None
    ):
        raise WorkspaceLifecycleError("Workspace is read-only")
    raise PermissionDenied(message)


async def require_workspace_membership(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
) -> WorkspaceContext:
    # Reload the credential subject so a prior transaction rollback or a
    # durable retry cannot leave an expired ORM instance as the authority
    # source.  The active User check is intentionally the first database gate.
    actor_identity = inspect(actor).identity
    actor_id = actor_identity[0] if actor_identity else actor.id
    current_actor = await db.get(User, actor_id, populate_existing=True)
    if current_actor is None or not current_actor.active:
        raise WorkspaceMembershipRequired("active User required")
    workspace = await db.get(Workspace, workspace_id, populate_existing=True)
    membership = await db.scalar(
        select(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_actor.id,
            WorkspaceMember.terminated_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    if (
        workspace is None
        or membership is None
        or membership.state is not WorkspaceMemberState.active
    ):
        raise WorkspaceMembershipRequired("active Workspace membership required")
    if workspace.state is WorkspaceState.deleted:
        raise ResourceUnavailable("Workspace not found")
    return WorkspaceContext(current_actor, workspace, membership, membership.role)


async def require_workspace_action(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
    resource_action: ResourceAction,
    *,
    relation: str = "any",
) -> WorkspaceContext:
    context = await require_workspace_membership(db, actor, workspace_id)
    require_action(context, resource_action, relation=relation)
    if resource_action in _NON_MUTATING_ACTIONS:
        return context
    # PostgreSQL holds this shared root lock through commit. Governance takes
    # an exclusive lock on the same root, while unrelated writers may proceed
    # concurrently. SQLite follows its ordinary single-process semantics.
    await db.scalar(
        select(Workspace.id).where(Workspace.id == workspace_id).with_for_update(read=True)
    )
    return require_action(
        await require_workspace_membership(db, actor, workspace_id),
        resource_action,
        relation=relation,
    )


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
        Project.visibility == visibility
        for visibility in (ProjectVisibility.workspace, ProjectVisibility.open)
        if action_allowed(
            ctx,
            ResourceAction.project_discover,
            relation=visibility.value,
        )
    ]
    if action_allowed(ctx, ResourceAction.project_discover, relation="managed"):
        relation_predicates.append(Project.visibility == ProjectVisibility.managed)
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
    require_participation: bool = True,
) -> ProjectContext:
    """Apply Project lineage/lifecycle after Workspace authorization.

    `ProjectMember` gates discoverability only for managed Projects. It never grants Workspace
    authority or access to canonical Workspace Items.
    """

    require_action(
        ctx,
        ResourceAction.project_update if write else ResourceAction.workspace_read,
    )
    if project.workspace_id != ctx.workspace.id or project.state is ProjectState.deleted:
        raise ResourceUnavailable("Project not found")
    if require_participation and not write:
        discoverable = action_allowed(
            ctx,
            ResourceAction.project_discover,
            relation=project.visibility.value,
        )
        if not discoverable and project.visibility is ProjectVisibility.managed:
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
    workspace = await require_workspace_action(
        db,
        actor,
        workspace_id,
        operation,
        relation=relation,
    )
    project_query = (
        workspace_select(Project, workspace)
        .where(
            Project.id == project_id,
            Project.state != ProjectState.deleted,
        )
        .execution_options(populate_existing=True)
    )
    if operation not in _NON_MUTATING_ACTIONS:
        # Project lifecycle changes take an exclusive root lock. Keep a shared
        # lock until the scoped write commits, then inspect the refreshed state.
        project_query = project_query.with_for_update(read=True)
    project = await db.scalar(project_query)
    if project is None:
        raise ResourceUnavailable("Project not found")
    project_context = await require_project_access(
        db,
        workspace,
        project,
        write=False,
        # Project lifecycle and management actions do not require participation.
        # Project content remains subject to managed-Project participation, like reads.
        require_participation=(
            operation in _NON_MUTATING_ACTIONS or operation in _PROJECT_CONTENT_WRITE_ACTIONS
        ),
    )
    if operation not in _NON_MUTATING_ACTIONS and project.state is not ProjectState.active:
        raise WorkspaceLifecycleError("Project is read-only")
    return project_context
