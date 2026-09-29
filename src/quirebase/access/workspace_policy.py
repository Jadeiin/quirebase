from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from quirebase.access.authorization import ResourceActionKey, workspace_action_allowed
from quirebase.models import ProjectParticipation, WorkspaceRole, WorkspaceState

if TYPE_CHECKING:
    from quirebase.access.context import WorkspaceContext


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


# Relation vocabularies whose alternatives are useful to generic API consumers. They describe
# canonical request facts, not grants; Casbin remains the only source of allow/deny decisions.
_RESOURCE_ACTION_RELATIONS = {
    ResourceAction.project_create: tuple(
        participation.value for participation in ProjectParticipation
    ),
    ResourceAction.workspace_invitation_create: ("member", "admin"),
}


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
