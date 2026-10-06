from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import inspect, select

from quirebase.access.authorization import workspace_action_allowed
from quirebase.access.workspace_policy import (
    ResourceAction,
    action_spec,
    effective_resource_actions,
    workspace_resource_action_allowed,
)
from quirebase.core.errors import (
    PermissionDenied,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
    WorkspaceUnavailable,
)
from quirebase.models import (
    Project,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    """Loaded authority with the role captured when authorization was resolved.

    A command may change this membership, such as demoting the previous owner
    during ownership transfer. Audit must retain the role that authorized that
    command. A subsequent command resolves a fresh context under its own locks.
    """

    actor: User
    workspace: Workspace
    membership: WorkspaceMember
    role: WorkspaceRole

    @property
    def actor_id(self) -> UUID:
        return self.actor.id

    @property
    def workspace_id(self) -> UUID:
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
    workspace_id: UUID,
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
    workspace_id: UUID,
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
    if workspace is None or workspace.state is WorkspaceState.deleted:
        raise WorkspaceUnavailable("Workspace not found")
    if membership is None or membership.state is not WorkspaceMemberState.active:
        raise WorkspaceMembershipRequired("active Workspace membership required")
    return WorkspaceContext(current_actor, workspace, membership, membership.role)


async def require_workspace_action(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    resource_action: ResourceAction,
    *,
    relation: str = "any",
) -> WorkspaceContext:
    context = await require_workspace_membership(db, actor, workspace_id)
    require_action(context, resource_action, relation=relation)
    if not action_spec(resource_action).mutating:
        return context
    # PostgreSQL holds this shared root lock through commit. Governance takes
    # an exclusive lock on the same root, while unrelated writers may proceed
    # concurrently. SQLite follows its ordinary single-process semantics.
    return require_action(
        await lock_workspace_context(db, actor, workspace_id),
        resource_action,
        relation=relation,
    )


async def lock_workspace_context(
    db: AsyncSession, actor: User, workspace_id: UUID
) -> WorkspaceContext:
    """Hold the Workspace root while a command checks target facts and authority."""
    await db.scalar(
        select(Workspace.id).where(Workspace.id == workspace_id).with_for_update(read=True)
    )
    return await require_workspace_membership(db, actor, workspace_id)
