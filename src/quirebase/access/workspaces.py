from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import inspect, select

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


class Capability(StrEnum):
    workspace_read = "workspace.read"
    workspace_export = "workspace.export"
    workspace_settings_manage = "workspace.settings.manage"
    workspace_members_manage = "workspace.members.manage"
    workspace_admins_manage = "workspace.admins.manage"
    workspace_transfer = "workspace.ownership.transfer"
    workspace_archive = "workspace.archive"
    workspace_delete = "workspace.delete"
    items_create = "items.create"
    items_edit = "items.edit"
    items_delete = "items.delete"
    files_manage = "files.manage"
    tags_use = "tags.use"
    tags_create = "tags.create"
    tags_manage = "tags.manage"
    citation_styles_manage = "citation_styles.manage"
    projects_manage = "projects.manage"
    projects_delete = "projects.delete"
    projects_members_manage = "projects.members.manage"
    discussion_write = "discussion.write"
    annotations_private_write = "annotations.private.write"
    annotations_project_write = "annotations.project.write"
    annotations_moderate = "annotations.moderate"


_READ_CAPABILITIES = frozenset({Capability.workspace_read, Capability.workspace_export})
_VIEWER = _READ_CAPABILITIES | {Capability.annotations_private_write}
_REVIEWER = _VIEWER | {
    Capability.discussion_write,
    Capability.annotations_project_write,
}
_EDITOR = _REVIEWER | {
    Capability.items_create,
    Capability.items_edit,
    Capability.files_manage,
    Capability.tags_use,
    Capability.tags_create,
    Capability.citation_styles_manage,
    Capability.projects_manage,
}
_ADMIN = _EDITOR | {
    Capability.workspace_settings_manage,
    Capability.workspace_members_manage,
    Capability.workspace_archive,
    Capability.items_delete,
    Capability.tags_manage,
    Capability.projects_delete,
    Capability.projects_members_manage,
    Capability.annotations_moderate,
}
_OWNER = _ADMIN | {
    Capability.workspace_admins_manage,
    Capability.workspace_transfer,
    Capability.workspace_delete,
}

ROLE_CAPABILITIES: dict[WorkspaceRole, frozenset[Capability]] = {
    WorkspaceRole.owner: frozenset(_OWNER),
    WorkspaceRole.admin: frozenset(_ADMIN),
    WorkspaceRole.editor: frozenset(_EDITOR),
    WorkspaceRole.reviewer: frozenset(_REVIEWER),
    WorkspaceRole.viewer: frozenset(_VIEWER),
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
    def capabilities(self) -> frozenset[Capability]:
        return ROLE_CAPABILITIES[self.role]


@dataclass(frozen=True, slots=True)
class ProjectContext:
    workspace: WorkspaceContext
    project: Project
    membership: ProjectMember | None


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


def require(ctx: WorkspaceContext, capability: Capability) -> WorkspaceContext:
    """Evaluate a capability against an already-resolved context."""

    if capability not in _READ_CAPABILITIES and (
        ctx.workspace.state is not WorkspaceState.active
        or ctx.workspace.governance_suspended_at is not None
    ):
        raise WorkspaceLifecycleError("Workspace is read-only")
    if not role_has_capability(ctx.role, capability):
        raise PermissionDenied(f"Workspace capability required: {capability.value}")
    return ctx


def role_has_capability(role: WorkspaceRole, capability: Capability) -> bool:
    return capability in ROLE_CAPABILITIES[role]


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


async def require_workspace_capability(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
    capability: Capability,
) -> WorkspaceContext:
    context = await require_workspace_membership(db, actor, workspace_id)
    require(context, capability)
    if capability in _READ_CAPABILITIES:
        return context
    # PostgreSQL holds this shared root lock through commit. Governance takes
    # an exclusive lock on the same root, while unrelated writers may proceed
    # concurrently. SQLite follows its ordinary single-process semantics.
    await db.scalar(
        select(Workspace.id).where(Workspace.id == workspace_id).with_for_update(read=True)
    )
    return require(await require_workspace_membership(db, actor, workspace_id), capability)


async def require_project_access(
    db: AsyncSession,
    ctx: WorkspaceContext,
    project: Project,
    *,
    write: bool = False,
) -> ProjectContext:
    """Apply Project visibility/lifecycle after Workspace authorization."""

    require(ctx, Capability.projects_manage if write else Capability.workspace_read)
    if project.workspace_id != ctx.workspace.id or project.state is ProjectState.deleted:
        raise ResourceUnavailable("Project not found")
    if write and project.state is not ProjectState.active:
        raise WorkspaceLifecycleError("Project is read-only")
    membership = await db.scalar(
        workspace_select(ProjectMember, ctx)
        .where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == ctx.actor.id,
        )
        .execution_options(populate_existing=True)
    )
    if project.visibility is ProjectVisibility.members and membership is None:
        raise ResourceUnavailable("Project not found")
    return ProjectContext(ctx, project, membership)


async def require_project_context(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
    project_id: str,
    operation: Capability,
) -> ProjectContext:
    workspace = await require_workspace_capability(db, actor, workspace_id, operation)
    project_query = (
        workspace_select(Project, workspace)
        .where(
            Project.id == project_id,
            Project.state != ProjectState.deleted,
        )
        .execution_options(populate_existing=True)
    )
    if operation not in _READ_CAPABILITIES:
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
        # ``operation`` may be a Project-scoped capability such as discussion
        # or annotation write.  Those operations need the Project visibility
        # gate but must not require the structural ``projects.manage`` role.
        write=False,
    )
    if operation not in _READ_CAPABILITIES and project.state is not ProjectState.active:
        raise WorkspaceLifecycleError("Project is read-only")
    return project_context
