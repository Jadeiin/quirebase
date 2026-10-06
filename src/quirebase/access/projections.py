from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from quirebase.access.authorization import (
    SystemAction,
    effective_system_actions,
)
from quirebase.access.context import WorkspaceContext, require_action
from quirebase.access.workspace_policy import (
    ResourceAction,
    action_allowed,
    effective_resource_actions,
    workspace_member_relation,
    workspace_resource_action_allowed,
)
from quirebase.models import (
    Project,
    ProjectParticipation,
    ProjectState,
    WorkspaceInvitationRole,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)


@dataclass(frozen=True, slots=True)
class AuthorizationProjection:
    """Resolved resource-action capabilities for a loaded resource."""

    allowed: tuple[ResourceAction | SystemAction, ...]


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
    return AuthorizationProjection(allowed=tuple(sorted(allowed, key=lambda action: action.value)))


def workspace_project_participations(
    role: WorkspaceRole,
    state: WorkspaceState,
    *,
    governance_suspended: bool = False,
) -> tuple[ProjectParticipation, ...]:
    """Project concrete creation choices without exposing Casbin relations."""
    return tuple(
        participation
        for participation in ProjectParticipation
        if workspace_resource_action_allowed(
            role,
            state,
            ResourceAction.project_create,
            governance_suspended=governance_suspended,
            relation=participation.value,
        )
    )


def system_decisions(role: str) -> AuthorizationProjection:
    return AuthorizationProjection(
        allowed=tuple(sorted(effective_system_actions(role), key=lambda action: action.value)),
    )


def workspace_invitation_roles(
    role: WorkspaceRole,
    state: WorkspaceState,
    *,
    governance_suspended: bool = False,
) -> tuple[WorkspaceInvitationRole, ...]:
    """Project allowed admission roles without exposing policy classifications to clients."""
    return tuple(
        target
        for target in WorkspaceInvitationRole
        if workspace_resource_action_allowed(
            role,
            state,
            ResourceAction.workspace_invitation_create,
            governance_suspended=governance_suspended,
            relation=workspace_member_relation(target.value),
        )
    )


def item_decisions(context: WorkspaceContext) -> AuthorizationProjection:
    """Project independent capabilities for an Item already loaded in this Workspace."""
    actions = context.allowed_actions.intersection({
        ResourceAction.item_update,
        ResourceAction.item_delete,
        ResourceAction.file_manage,
        ResourceAction.file_delete,
        ResourceAction.tag_use,
        ResourceAction.tag_create,
        ResourceAction.project_item_manage,
        ResourceAction.workspace_export,
    })
    return AuthorizationProjection(
        allowed=tuple(sorted(actions, key=lambda action: action.value)),
    )


def tag_decisions(context: WorkspaceContext) -> AuthorizationProjection:
    allowed = (
        (ResourceAction.tag_manage,) if action_allowed(context, ResourceAction.tag_manage) else ()
    )
    return AuthorizationProjection(allowed=allowed)


def _project_participation_change_requirements(
    current: ProjectParticipation,
    target: ProjectParticipation,
) -> tuple[tuple[ResourceAction, str], ...]:
    """One capability requirement set for both choices and command enforcement."""
    requirements = ((ResourceAction.project_update, "any"),)
    if current is not target and ProjectParticipation.managed in {current, target}:
        return (*requirements, (ResourceAction.project_membership_manage, "managed"))
    return requirements


def project_participation_change_allowed(
    context: WorkspaceContext,
    current: ProjectParticipation,
    target: ProjectParticipation,
) -> bool:
    return all(
        action_allowed(context, action, relation=relation)
        for action, relation in _project_participation_change_requirements(current, target)
    )


def project_participation_changes(
    context: WorkspaceContext, project: Project
) -> tuple[ProjectParticipation, ...]:
    if project.state is not ProjectState.active:
        return ()
    return tuple(
        target
        for target in ProjectParticipation
        if project_participation_change_allowed(context, project.participation, target)
    )


def require_project_participation_change(
    context: WorkspaceContext,
    current: ProjectParticipation,
    target: ProjectParticipation,
) -> None:
    for action, relation in _project_participation_change_requirements(current, target):
        require_action(context, action, relation=relation)


def project_decisions(
    context: WorkspaceContext,
    project: Project,
    *,
    is_participating: bool,
) -> AuthorizationProjection:
    allowed: set[ResourceAction] = set()
    actions = context.allowed_actions

    if ResourceAction.project_update in actions and project.state is ProjectState.active:
        allowed.add(ResourceAction.project_update)
    if ResourceAction.project_item_manage in actions and project.state is ProjectState.active:
        allowed.add(ResourceAction.project_item_manage)
    if project.state is ProjectState.active and ResourceAction.project_archive in actions:
        allowed.add(ResourceAction.project_archive)
    elif project.state is ProjectState.archived and ResourceAction.project_restore in actions:
        allowed.add(ResourceAction.project_restore)
    if (
        action_allowed(context, ResourceAction.project_membership_manage, relation="managed")
        and project.state is ProjectState.active
        and project.participation is ProjectParticipation.managed
    ):
        allowed.add(ResourceAction.project_membership_manage)
    if project.state is ProjectState.active and project.participation is ProjectParticipation.open:
        if is_participating and action_allowed(
            context,
            ResourceAction.project_membership_leave,
            relation=project.participation.value,
        ):
            allowed.add(ResourceAction.project_membership_leave)
        elif not is_participating and action_allowed(
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
    )


def workspace_member_decisions(
    context: WorkspaceContext,
    member: WorkspaceMember,
) -> AuthorizationProjection:
    relation = workspace_member_relation(member.role)
    candidates = [ResourceAction.workspace_member_terminate]
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
    )


def workspace_member_role_action(
    current: WorkspaceRole, requested: WorkspaceRole
) -> ResourceAction:
    """Select the authority needed for one concrete role transition."""
    return (
        ResourceAction.workspace_member_promote
        if requested is WorkspaceRole.admin and current is not WorkspaceRole.admin
        else ResourceAction.workspace_member_change_role
    )


def workspace_member_roles(
    context: WorkspaceContext, member: WorkspaceMember
) -> tuple[WorkspaceInvitationRole, ...]:
    if member.role is WorkspaceRole.owner or member.terminated_at is not None:
        return ()
    return tuple(
        target
        for target in WorkspaceInvitationRole
        if action_allowed(
            context,
            workspace_member_role_action(member.role, WorkspaceRole(target.value)),
            relation=workspace_member_relation(member.role),
        )
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
        return AuthorizationProjection(allowed=())
    resource = "project_discussion" if project_id is not None else "item_discussion"
    action = ResourceAction(f"{resource}.delete")
    allowed = (action,) if action_allowed(context, action, relation=relation) else ()
    return AuthorizationProjection(allowed=allowed)
