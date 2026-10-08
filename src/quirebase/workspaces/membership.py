from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from quirebase.access import (
    ResourceAction,
    require_action,
    require_workspace_membership,
    workspace_member_relation,
    workspace_member_role_action,
)
from quirebase.audit import record_event
from quirebase.core.errors import (
    PermissionDenied,
    ValidationFailure,
)
from quirebase.models import (
    ProjectParticipant,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

from ._locking import _current_member, _lock_workspace
from .invitations import _revoke_pending_invitations


async def set_workspace_member_role(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    membership_id: UUID,
    role: WorkspaceRole | str,
) -> WorkspaceMember:
    requested = WorkspaceRole(role)
    await _lock_workspace(db, workspace_id)
    context = await require_workspace_membership(db, actor, workspace_id)
    member = await _current_member(db, workspace_id, membership_id)
    if member.role is WorkspaceRole.owner or requested is WorkspaceRole.owner:
        raise ValidationFailure("use ownership transfer for the owner role")
    relation = workspace_member_relation(member.role)
    resource_action = workspace_member_role_action(member.role, requested)
    require_action(context, resource_action, relation=relation)
    if member.role is requested:
        await db.commit()
        return member
    member.role = requested
    record_event(
        db,
        actor.id,
        "workspace.member.role",
        "workspace_member",
        member.id,
        detail={"role": requested.value},
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=resource_action.value,
    )
    await db.commit()
    return member


async def suspend_workspace_member(
    db: AsyncSession, actor: User, workspace_id: UUID, membership_id: UUID
) -> WorkspaceMember:
    await _lock_workspace(db, workspace_id)
    context = await require_workspace_membership(db, actor, workspace_id)
    member = await _current_member(db, workspace_id, membership_id)
    if member.role is WorkspaceRole.owner:
        raise PermissionDenied("transfer Workspace ownership before suspending the owner")
    require_action(
        context,
        ResourceAction.workspace_member_suspend,
        relation=workspace_member_relation(member.role),
    )
    if member.state is WorkspaceMemberState.suspended:
        await db.commit()
        return member
    member.state = WorkspaceMemberState.suspended
    member.suspended_at = datetime.now(UTC)
    await _revoke_pending_invitations(db, workspace_id, member.user_id)
    record_event(
        db,
        actor.id,
        "workspace.member.suspend",
        "workspace_member",
        member.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_member_suspend.value,
    )
    await db.commit()
    return member


async def reactivate_workspace_member(
    db: AsyncSession, actor: User, workspace_id: UUID, membership_id: UUID
) -> WorkspaceMember:
    await _lock_workspace(db, workspace_id)
    context = await require_workspace_membership(db, actor, workspace_id)
    member = await _current_member(db, workspace_id, membership_id)
    require_action(
        context,
        ResourceAction.workspace_member_reactivate,
        relation=workspace_member_relation(member.role),
    )
    if member.state is WorkspaceMemberState.active:
        await db.commit()
        return member
    member.state = WorkspaceMemberState.active
    member.suspended_at = None
    record_event(
        db,
        actor.id,
        "workspace.member.reactivate",
        "workspace_member",
        member.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_member_reactivate.value,
    )
    await db.commit()
    return member


async def terminate_workspace_member(
    db: AsyncSession, actor: User, workspace_id: UUID, membership_id: UUID
) -> None:
    await _lock_workspace(db, workspace_id)
    context = await require_workspace_membership(db, actor, workspace_id)
    member = await _current_member(db, workspace_id, membership_id)
    if member.role is WorkspaceRole.owner:
        raise PermissionDenied("transfer Workspace ownership before removing the owner")
    require_action(
        context,
        ResourceAction.workspace_member_terminate,
        relation=workspace_member_relation(member.role),
    )
    await db.execute(
        delete(ProjectParticipant).where(
            ProjectParticipant.workspace_id == workspace_id,
            ProjectParticipant.workspace_member_id == member.id,
        )
    )
    member.terminated_at = datetime.now(UTC)
    await _revoke_pending_invitations(db, workspace_id, member.user_id)
    record_event(
        db,
        actor.id,
        "workspace.member.terminate",
        "workspace_member",
        member.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_member_terminate.value,
    )
    await db.commit()


async def transfer_workspace_ownership(
    db: AsyncSession, actor: User, workspace_id: UUID, target_membership_id: UUID
) -> Workspace:
    # Account deactivation locks the User before every Workspace where it has a
    # current membership. Take the same order here so transferring ownership cannot
    # deadlock with the foreign-key check against a concurrently deactivated User.
    target_user = await db.scalar(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            WorkspaceMember.id == target_membership_id,
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.terminated_at.is_(None),
        )
        .execution_options(populate_existing=True)
        .with_for_update(read=True, of=User)
    )
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_membership(db, actor, workspace_id)
    target = await _current_member(db, workspace_id, target_membership_id)
    require_action(
        context,
        ResourceAction.workspace_member_transfer_ownership,
        relation=workspace_member_relation(target.role),
    )
    if target.state is not WorkspaceMemberState.active:
        raise ValidationFailure("new owner must be an active Workspace member")
    if target_user is None or target_user.id != target.user_id or not target_user.active:
        raise ValidationFailure("new owner must be an active User")
    current = await db.scalar(
        select(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.owner,
            WorkspaceMember.terminated_at.is_(None),
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if current is None:
        raise ValidationFailure("Workspace owner membership is inconsistent")
    current.role = WorkspaceRole.admin
    await db.flush()
    target.role = WorkspaceRole.owner
    record_event(
        db,
        actor.id,
        "workspace.ownership.transfer",
        "workspace",
        workspace.id,
        detail={"previous_owner_id": current.user_id, "owner_id": target.user_id},
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_member_transfer_ownership.value,
    )
    await db.commit()
    return workspace
