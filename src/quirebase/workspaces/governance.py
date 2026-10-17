from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import inspect, select

from quirebase.access import (
    SystemAction,
    require_system_action,
)
from quirebase.audit import record_event
from quirebase.core.errors import (
    ResourceNotFound,
    ValidationFailure,
    VersionConflict,
    WorkspaceLifecycleError,
)
from quirebase.models import (
    Item,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

from ._locking import _lock_workspace
from .invitations import _revoke_pending_invitations


async def reassign_workspace_owner(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    new_owner_user_id: UUID,
    expected_owner_user_id: UUID,
    reason: str,
) -> Workspace:
    """Explicit, audited instance governance; caller receives no implicit membership."""
    identity = inspect(actor).identity
    actor_id = identity[0] if identity else actor.id
    # User guards precede the root, matching account deactivation and admission.
    users: dict[UUID, User] = {}
    for user_id in sorted({actor_id, new_owner_user_id}):
        user = await db.scalar(
            select(User)
            .where(User.id == user_id)
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        if user is not None:
            users[user_id] = user
    actor = await require_system_action(
        db,
        users.get(actor_id, actor),
        SystemAction.workspaces_governance_reassign_owner,
        message="Workspace not found",
        denied_error=ResourceNotFound,
    )
    reason = reason.strip()
    if not 10 <= len(reason) <= 1000:
        raise ValidationFailure("reason must contain 10 to 1000 characters")
    receiver = users.get(new_owner_user_id)
    if receiver is None or not receiver.active:
        raise ValidationFailure("new Workspace owner must be an active User")
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.governance_frozen_at is not None:
        raise WorkspaceLifecycleError("unfreeze Workspace writes before reassigning ownership")
    current = await db.scalar(
        select(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.owner,
            WorkspaceMember.terminated_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    if current is None or current.state is not WorkspaceMemberState.active:
        raise ValidationFailure("Workspace owner membership is inconsistent")
    if current.user_id != expected_owner_user_id:
        raise VersionConflict(message="Workspace owner changed; refresh before reassigning")
    if current.user_id == new_owner_user_id:
        await db.commit()
        return workspace
    target = await db.scalar(
        select(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == new_owner_user_id,
            WorkspaceMember.terminated_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    membership_effect = "promoted"
    if target is None:
        target = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=new_owner_user_id,
            role=WorkspaceRole.admin,
            state=WorkspaceMemberState.active,
            invited_by=actor.id,
        )
        db.add(target)
        membership_effect = "admitted"
    elif target.state is WorkspaceMemberState.suspended:
        target.state = WorkspaceMemberState.active
        target.suspended_at = None
        membership_effect = "reactivated"
    previous_owner_id = current.user_id
    current.role = WorkspaceRole.admin
    # Release the unique current-owner slot before promoting the receiving membership.
    await db.flush()
    target.role = WorkspaceRole.owner
    if membership_effect in {"admitted", "reactivated"}:
        await _revoke_pending_invitations(db, workspace_id, new_owner_user_id)
    record_event(
        db,
        actor.id,
        "admin.workspace.owner_reassign",
        "workspace",
        workspace_id,
        detail={
            "previous_owner_id": previous_owner_id,
            "owner_id": new_owner_user_id,
            "membership_id": target.id,
            "membership_effect": membership_effect,
            "reason": reason,
        },
        workspace_id=workspace_id,
        authorization_role=actor.role,
        authorization_resource_action=SystemAction.workspaces_governance_reassign_owner.value,
    )
    await db.commit()
    return workspace


async def list_workspaces_for_governance(db: AsyncSession, actor: User) -> list[Workspace]:
    await require_system_action(
        db,
        actor,
        SystemAction.workspaces_governance_read,
        message="Workspace not found",
        denied_error=ResourceNotFound,
    )
    return list((await db.scalars(select(Workspace).order_by(Workspace.created_at.desc()))).all())


async def freeze_workspace_governance(
    db: AsyncSession, actor: User, workspace_id: UUID
) -> Workspace:
    current_actor = await require_system_action(
        db,
        actor,
        SystemAction.workspaces_governance_freeze,
        lock="shared",
        message="Workspace not found",
        denied_error=ResourceNotFound,
    )
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.governance_frozen_at is not None:
        await db.commit()
        return workspace
    workspace.governance_frozen_at = datetime.now(UTC)
    workspace.governance_frozen_by = current_actor.id
    record_event(
        db,
        current_actor.id,
        "admin.workspace.freeze",
        "workspace",
        workspace.id,
        workspace_id=workspace.id,
        authorization_role=current_actor.role,
        authorization_resource_action=SystemAction.workspaces_governance_freeze.value,
    )
    await db.commit()
    return workspace


async def unfreeze_workspace_governance(
    db: AsyncSession, actor: User, workspace_id: UUID
) -> Workspace:
    current_actor = await require_system_action(
        db,
        actor,
        SystemAction.workspaces_governance_unfreeze,
        lock="shared",
        message="Workspace not found",
        denied_error=ResourceNotFound,
    )
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.governance_frozen_at is None:
        await db.commit()
        return workspace
    workspace.governance_frozen_at = None
    workspace.governance_frozen_by = None
    record_event(
        db,
        current_actor.id,
        "admin.workspace.unfreeze",
        "workspace",
        workspace.id,
        workspace_id=workspace.id,
        authorization_role=current_actor.role,
        authorization_resource_action=SystemAction.workspaces_governance_unfreeze.value,
    )
    await db.commit()
    return workspace


async def read_workspace_items_break_glass(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    reason: str,
    *,
    limit: int = 100,
) -> list[Item]:
    """Perform one reason-bound, read-only administrative content access."""
    current_actor = await require_system_action(
        db,
        actor,
        SystemAction.workspaces_break_glass_read,
        lock="shared",
        message="Workspace not found",
        denied_error=ResourceNotFound,
    )
    reason = reason.strip()
    if len(reason) < 10:
        raise ValidationFailure("break-glass reason must contain at least 10 characters")
    if not 1 <= limit <= 100:
        raise ValidationFailure("break-glass inspection limit must be between 1 and 100")
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise ResourceNotFound("Workspace not found")
    items = list(
        (
            await db.scalars(
                select(Item)
                .where(Item.workspace_id == workspace_id)
                .order_by(Item.updated_at.desc())
                .limit(limit)
            )
        ).all()
    )
    record_event(
        db,
        current_actor.id,
        "admin.workspace.break_glass.read",
        "workspace",
        workspace_id,
        detail={"reason": reason, "resource": "items", "result_count": len(items)},
        workspace_id=workspace_id,
        authorization_role=current_actor.role,
        authorization_resource_action=SystemAction.workspaces_break_glass_read.value,
        result="succeeded",
    )
    await db.commit()
    return items
