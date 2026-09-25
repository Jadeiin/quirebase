from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import inspect, or_, select

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
    projects_create = "projects.create"
    projects_create_managed = "projects.create_managed"
    projects_manage = "projects.manage"
    projects_delete = "projects.delete"
    projects_members_manage = "projects.members.manage"
    discussion_write = "discussion.write"
    discussion_moderate = "discussion.moderate"
    annotations_private_write = "annotations.private.write"
    annotations_project_write = "annotations.project.write"
    annotations_moderate = "annotations.moderate"


_READ_CAPABILITIES = frozenset({Capability.workspace_read, Capability.workspace_export})
_PROJECT_CONTENT_WRITE_CAPABILITIES = frozenset({
    Capability.discussion_write,
    Capability.annotations_project_write,
})
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
    Capability.projects_create,
    Capability.projects_manage,
}
_ADMIN = _EDITOR | {
    Capability.workspace_settings_manage,
    Capability.workspace_members_manage,
    Capability.workspace_archive,
    Capability.items_delete,
    Capability.tags_manage,
    Capability.projects_delete,
    Capability.projects_create_managed,
    Capability.projects_members_manage,
    Capability.annotations_moderate,
    Capability.discussion_moderate,
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
        return effective_capabilities(
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


def effective_capabilities(
    role: WorkspaceRole,
    state: WorkspaceState,
    *,
    governance_suspended: bool = False,
) -> frozenset[Capability]:
    """Return capabilities currently available in a Workspace lifecycle state."""

    role_capabilities = ROLE_CAPABILITIES[role]
    if governance_suspended:
        return _READ_CAPABILITIES & role_capabilities
    if state is WorkspaceState.active:
        return role_capabilities
    lifecycle_capabilities = _READ_CAPABILITIES | {Capability.workspace_archive}
    if Capability.workspace_delete in role_capabilities:
        lifecycle_capabilities |= {Capability.workspace_delete}
    return role_capabilities & lifecycle_capabilities


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


def visible_project_ids_query(ctx: WorkspaceContext):
    """Select Projects discoverable to this active Workspace member.

    `workspace` and `open` Projects are visible to all active Workspace members. A `managed`
    Project is visible to its explicit participants and Workspace governors. The role preset is
    used only inside Access to preserve governor discovery in read-only Workspace lifecycle
    states; mutations still require effective capabilities through `require`.
    """
    query = select(Project.id).where(
        Project.workspace_id == ctx.workspace_id,
        Project.state != ProjectState.deleted,
    )
    if role_has_capability(ctx.role, Capability.projects_members_manage):
        return query
    member_project_ids = select(ProjectMember.project_id).where(
        ProjectMember.workspace_id == ctx.workspace_id,
        ProjectMember.user_id == ctx.actor_id,
    )
    return query.where(
        or_(
            Project.visibility != ProjectVisibility.managed,
            Project.id.in_(member_project_ids),
        )
    )


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
    capabilities or access to canonical Workspace Items.
    """

    require(ctx, Capability.projects_manage if write else Capability.workspace_read)
    if project.workspace_id != ctx.workspace.id or project.state is ProjectState.deleted:
        raise ResourceUnavailable("Project not found")
    if (
        require_participation
        and not write
        and project.visibility is ProjectVisibility.managed
        and not role_has_capability(ctx.role, Capability.projects_members_manage)
    ):
        member_id = await db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.workspace_id == ctx.workspace_id,
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == ctx.actor_id,
            )
        )
        if member_id is None:
            raise ResourceUnavailable("Project not found")
    if write and project.state is not ProjectState.active:
        raise WorkspaceLifecycleError("Project is read-only")
    return ProjectContext(ctx, project)


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
        write=False,
        # Project lifecycle and management operations are capability-only. Project
        # content remains subject to managed-Project participation, just like reads.
        require_participation=(
            operation in _READ_CAPABILITIES or operation in _PROJECT_CONTENT_WRITE_CAPABILITIES
        ),
    )
    if operation not in _READ_CAPABILITIES and project.state is not ProjectState.active:
        raise WorkspaceLifecycleError("Project is read-only")
    return project_context
