from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from quirebase.access.authorization import ResourceActionKey, workspace_action_allowed
from quirebase.models import ProjectParticipation, WorkspaceRole, WorkspaceState

if TYPE_CHECKING:
    from quirebase.access.context import WorkspaceContext


class ResourceAction(ResourceActionKey):
    """One canonical Workspace-scoped authorization resource/action pair."""

    workspace_read = "workspace.read"
    workspace_export = "workspace.export"
    workspace_update = "workspace.update"
    workspace_maintenance_run = "workspace_maintenance.run"
    workspace_archive = "workspace.archive"
    workspace_restore = "workspace.restore"
    workspace_delete = "workspace.delete"
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
    project_governance_read = "project_governance.read"
    project_participation_join = "project_participation.join"
    project_participation_leave = "project_participation.leave"
    project_participation_manage = "project_participation.manage"
    workspace_invitation_read = "workspace_invitation.read"
    workspace_invitation_create = "workspace_invitation.create"
    workspace_invitation_revoke = "workspace_invitation.revoke"
    workspace_membership_read = "workspace_membership.read"
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


@dataclass(frozen=True, slots=True)
class ActionSpec:
    mutating: bool
    policy_relations: tuple[str, ...] = ("any",)


_READ = ActionSpec(mutating=False)
_WRITE = ActionSpec(mutating=True)
_AUTHOR_RELATIONS = ("own", "other")
_MEMBER_RELATIONS = ("owner", "admin", "member")
_PARTICIPATION_RELATIONS = tuple(value.value for value in ProjectParticipation)

# This registry describes command shape and mutation semantics. Casbin remains the only grant source.
ACTION_SPECS: dict[ResourceAction, ActionSpec] = {
    ResourceAction.workspace_read: _READ,
    ResourceAction.workspace_export: _READ,
    ResourceAction.workspace_update: _WRITE,
    ResourceAction.workspace_maintenance_run: _WRITE,
    ResourceAction.workspace_archive: _WRITE,
    ResourceAction.workspace_restore: _WRITE,
    ResourceAction.workspace_delete: _WRITE,
    ResourceAction.item_create: _WRITE,
    ResourceAction.item_update: _WRITE,
    ResourceAction.item_delete: _WRITE,
    ResourceAction.file_manage: _WRITE,
    ResourceAction.file_delete: _WRITE,
    ResourceAction.tag_use: _WRITE,
    ResourceAction.tag_create: _WRITE,
    ResourceAction.tag_manage: _WRITE,
    ResourceAction.citation_style_manage: _WRITE,
    ResourceAction.project_create: ActionSpec(
        mutating=True,
        policy_relations=_PARTICIPATION_RELATIONS,
    ),
    ResourceAction.project_update: _WRITE,
    ResourceAction.project_archive: _WRITE,
    ResourceAction.project_restore: _WRITE,
    ResourceAction.project_delete: _WRITE,
    ResourceAction.project_item_manage: _WRITE,
    ResourceAction.project_governance_read: _READ,
    ResourceAction.project_participation_join: ActionSpec(True, ("open",)),
    ResourceAction.project_participation_leave: ActionSpec(True, ("open",)),
    ResourceAction.project_participation_manage: ActionSpec(True, ("managed",)),
    ResourceAction.workspace_invitation_read: _READ,
    ResourceAction.workspace_invitation_create: ActionSpec(
        mutating=True,
        policy_relations=_MEMBER_RELATIONS,
    ),
    ResourceAction.workspace_invitation_revoke: _WRITE,
    ResourceAction.workspace_membership_read: _READ,
    ResourceAction.workspace_member_change_role: ActionSpec(True, _MEMBER_RELATIONS),
    ResourceAction.workspace_member_promote: ActionSpec(True, _MEMBER_RELATIONS),
    ResourceAction.workspace_member_suspend: ActionSpec(True, _MEMBER_RELATIONS),
    ResourceAction.workspace_member_reactivate: ActionSpec(True, _MEMBER_RELATIONS),
    ResourceAction.workspace_member_terminate: ActionSpec(True, _MEMBER_RELATIONS),
    ResourceAction.workspace_member_transfer_ownership: ActionSpec(True, _MEMBER_RELATIONS),
    ResourceAction.item_discussion_create: _WRITE,
    ResourceAction.item_discussion_delete: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_discussion_create: _WRITE,
    ResourceAction.project_discussion_delete: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.private_annotation_create: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.private_annotation_read: ActionSpec(False, _AUTHOR_RELATIONS),
    ResourceAction.private_annotation_update: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.private_annotation_delete: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.private_annotation_restore: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_create: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_read: ActionSpec(False, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_review: _READ,
    ResourceAction.project_annotation_update: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_delete: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_restore: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_hide: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_archive: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_lock: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_unlock: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.private_annotation_reply_create: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.private_annotation_reply_update: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.private_annotation_reply_delete: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.private_annotation_reply_restore: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_reply_create: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_reply_update: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_reply_delete: ActionSpec(True, _AUTHOR_RELATIONS),
    ResourceAction.project_annotation_reply_restore: ActionSpec(True, _AUTHOR_RELATIONS),
}


def action_spec(resource_action: ResourceAction) -> ActionSpec:
    return ACTION_SPECS[resource_action]


def validate_action_relation(resource_action: ResourceAction, relation: str) -> None:
    """Reject malformed request facts before a programming error becomes a denial."""
    if relation not in action_spec(resource_action).policy_relations:
        raise ValueError(f"{resource_action.value} does not accept relation {relation!r}")


def validate_action_specs() -> None:
    missing = set(ResourceAction) - ACTION_SPECS.keys()
    extra = ACTION_SPECS.keys() - set(ResourceAction)
    if missing or extra:
        raise RuntimeError(
            f"incomplete Workspace action metadata: missing={missing}, extra={extra}"
        )


def workspace_resource_action_allowed(
    role: WorkspaceRole,
    state: WorkspaceState,
    resource_action: ResourceAction,
    *,
    governance_frozen: bool = False,
    relation: str = "any",
) -> bool:
    """Evaluate one resource/action pair through the sole Casbin policy source."""

    validate_action_relation(resource_action, relation)
    lifecycle = "frozen" if governance_frozen else state
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
    governance_frozen: bool = False,
) -> frozenset[ResourceAction]:
    """Return relation-free resource actions available in a Workspace state."""

    return frozenset(
        resource_action
        for resource_action in ResourceAction
        if "any" in action_spec(resource_action).policy_relations
        and workspace_resource_action_allowed(
            role,
            state,
            resource_action,
            governance_frozen=governance_frozen,
        )
    )


def action_allowed(
    ctx: WorkspaceContext,
    resource_action: ResourceAction,
    *,
    relation: str = "any",
) -> bool:
    """Evaluate a resource action without moving canonical fact loading into policy."""

    validate_action_relation(resource_action, relation)
    lifecycle = "frozen" if ctx.workspace.governance_frozen_at is not None else ctx.workspace.state
    return workspace_action_allowed(
        ctx.role,
        resource_action.resource,
        resource_action.action,
        lifecycle,
        relation,
    )


type WorkspaceMemberRelation = Literal["owner", "admin", "member"]


def workspace_member_relation(role: WorkspaceRole | str) -> WorkspaceMemberRelation:
    """Normalize persistent Workspace roles to policy relation classes."""

    normalized = WorkspaceRole(role)
    if normalized is WorkspaceRole.owner:
        return "owner"
    if normalized is WorkspaceRole.admin:
        return "admin"
    return "member"
