from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from quirebase.access.authorization import (
    ResourceActionKey,
    SystemAction,
    effective_system_actions,
)
from quirebase.access.context import WorkspaceContext, require_action
from quirebase.access.workspace_policy import (
    ResourceAction,
    action_allowed,
    action_spec,
    effective_resource_action_relations,
    effective_resource_actions,
    workspace_member_relation,
)
from quirebase.models import (
    Project,
    ProjectParticipation,
    ProjectState,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)

if TYPE_CHECKING:
    from collections.abc import Collection


@dataclass(frozen=True, slots=True)
class AuthorizationProjection:
    allowed: tuple[ResourceAction | SystemAction, ...]
    relations: dict[ResourceActionKey, tuple[str, ...]]


class ItemDecisionSource(Protocol):
    @property
    def can_edit(self) -> bool: ...

    @property
    def can_delete(self) -> bool: ...


class DiscussionDecisionSource(Protocol):
    author_id: str
    project_id: str | None


def workspace_decisions(
    role: WorkspaceRole,
    state: WorkspaceState,
    *,
    governance_suspended: bool = False,
) -> AuthorizationProjection:
    allowed = effective_resource_actions(
        role,
        state,
        governance_suspended=governance_suspended,
    )
    relations = {
        action: tuple(
            sorted(
                effective_resource_action_relations(
                    role,
                    state,
                    action,
                    governance_suspended=governance_suspended,
                )
            )
        )
        for action in ResourceAction
    }
    return AuthorizationProjection(
        allowed=tuple(sorted(allowed, key=lambda action: action.value)),
        relations={action: values for action, values in relations.items() if values},
    )


def system_decisions(role: str) -> AuthorizationProjection:
    return AuthorizationProjection(
        allowed=tuple(sorted(effective_system_actions(role), key=lambda action: action.value)),
        relations={},
    )


def item_decisions(
    view: ItemDecisionSource,
    allowed_actions: Collection[ResourceActionKey],
) -> AuthorizationProjection:
    actions: set[ResourceAction] = set()
    if view.can_edit:
        actions.add(ResourceAction.item_update)
        actions.update(
            action
            for action in (
                ResourceAction.file_manage,
                ResourceAction.tag_use,
                ResourceAction.tag_create,
                ResourceAction.project_item_manage,
            )
            if action in allowed_actions
        )
    if ResourceAction.file_delete in allowed_actions:
        actions.add(ResourceAction.file_delete)
    if view.can_delete:
        actions.add(ResourceAction.item_delete)
    if ResourceAction.workspace_export in allowed_actions:
        actions.add(ResourceAction.workspace_export)
    return AuthorizationProjection(
        allowed=tuple(sorted(actions, key=lambda action: action.value)),
        relations={},
    )


def copy_target_decisions(*, can_copy_into: bool) -> AuthorizationProjection:
    return AuthorizationProjection(
        allowed=(ResourceAction.item_copy,) if can_copy_into else (),
        relations={},
    )


def tag_decisions(context: WorkspaceContext) -> AuthorizationProjection:
    allowed = (
        (ResourceAction.tag_manage,) if action_allowed(context, ResourceAction.tag_manage) else ()
    )
    return AuthorizationProjection(allowed=allowed, relations={})


def project_participation_change_allowed(
    context: WorkspaceContext,
    current: ProjectParticipation,
    target: ProjectParticipation,
) -> bool:
    if not action_allowed(context, ResourceAction.project_update):
        return False
    if current is target:
        return True
    if ProjectParticipation.managed in {current, target}:
        return action_allowed(
            context,
            ResourceAction.project_membership_manage,
            relation="managed",
        )
    return True


def require_project_participation_change(
    context: WorkspaceContext,
    current: ProjectParticipation,
    target: ProjectParticipation,
) -> None:
    require_action(context, ResourceAction.project_update)
    if current is target:
        return
    if ProjectParticipation.managed in {current, target}:
        require_action(
            context,
            ResourceAction.project_membership_manage,
            relation="managed",
        )


def project_decisions(
    context: WorkspaceContext,
    project: Project,
    *,
    is_member: bool,
) -> AuthorizationProjection:
    allowed: set[ResourceAction] = set()
    relations: dict[ResourceActionKey, tuple[str, ...]] = {}
    actions = context.allowed_actions

    if ResourceAction.project_update in actions and project.state is ProjectState.active:
        allowed.add(ResourceAction.project_update)
        relations[ResourceAction.project_update] = tuple(
            relation
            for relation in action_spec(ResourceAction.project_update).relations
            if project_participation_change_allowed(
                context, project.participation, ProjectParticipation(relation)
            )
        )
    if ResourceAction.project_item_manage in actions and project.state is ProjectState.active:
        allowed.add(ResourceAction.project_item_manage)
    if project.state is ProjectState.active and ResourceAction.project_archive in actions:
        allowed.add(ResourceAction.project_archive)
    elif ResourceAction.project_restore in actions:
        allowed.add(ResourceAction.project_restore)
    if (
        action_allowed(context, ResourceAction.project_membership_manage, relation="managed")
        and project.state is ProjectState.active
        and project.participation is ProjectParticipation.managed
    ):
        allowed.add(ResourceAction.project_membership_manage)
    if project.state is ProjectState.active and project.participation is ProjectParticipation.open:
        if is_member and action_allowed(
            context,
            ResourceAction.project_membership_leave,
            relation=project.participation.value,
        ):
            allowed.add(ResourceAction.project_membership_leave)
        elif not is_member and action_allowed(
            context,
            ResourceAction.project_membership_join,
            relation=project.participation.value,
        ):
            allowed.add(ResourceAction.project_membership_join)
    if ResourceAction.project_delete in actions:
        allowed.add(ResourceAction.project_delete)
    if ResourceAction.project_discussion_create in actions and project.state is ProjectState.active:
        allowed.add(ResourceAction.project_discussion_create)
    if project.state is ProjectState.active and action_allowed(
        context,
        ResourceAction.project_discussion_delete,
        relation="other",
    ):
        allowed.add(ResourceAction.project_discussion_delete)
    return AuthorizationProjection(
        allowed=tuple(sorted(allowed, key=lambda action: action.value)),
        relations=relations,
    )


def workspace_member_decisions(
    context: WorkspaceContext,
    member: WorkspaceMember,
) -> AuthorizationProjection:
    relation = workspace_member_relation(member.role)
    candidates = [
        ResourceAction.workspace_member_change_role,
        ResourceAction.workspace_member_promote,
        ResourceAction.workspace_member_terminate,
    ]
    if member.state is WorkspaceMemberState.active:
        candidates.extend([
            ResourceAction.workspace_member_suspend,
            ResourceAction.workspace_member_transfer_ownership,
        ])
    else:
        candidates.append(ResourceAction.workspace_member_reactivate)
    return AuthorizationProjection(
        allowed=tuple(
            action for action in candidates if action_allowed(context, action, relation=relation)
        ),
        relations={},
    )


def discussion_message_decisions(
    context: WorkspaceContext,
    message: DiscussionDecisionSource,
    *,
    writable: bool = True,
) -> AuthorizationProjection:
    author_id = message.author_id
    project_id = message.project_id
    relation = "own" if author_id == context.actor_id else "other"
    if not writable:
        return AuthorizationProjection(allowed=(), relations={})
    resource = "project_discussion" if project_id is not None else "item_discussion"
    action = ResourceAction(f"{resource}.delete")
    allowed = (action,) if action_allowed(context, action, relation=relation) else ()
    return AuthorizationProjection(allowed=allowed, relations={})
