from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy import Nullable, func, inspect, or_, select

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
    WorkspaceState,
)

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

from ._locking import _lock_workspace
from .directory import _workspace_owners_query
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


def _governance_workspace_query() -> Select[tuple[Workspace, User | None]]:
    owners = _workspace_owners_query().subquery()
    return (
        select(Workspace, Nullable(User))
        .select_from(Workspace)
        .join(owners, owners.c.id == Workspace.id)
        .outerjoin(User, User.id == owners.c.owner_id)
    )


async def list_workspaces_for_governance(
    db: AsyncSession,
    actor: User,
    *,
    search: str = "",
    state: Literal["", "active", "archived"] = "",
    frozen: bool | None = None,
    owner_active: bool | None = None,
    sort: Literal["name", "owner", "created"] = "name",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[tuple[Workspace, User]], int]:
    await require_system_action(
        db,
        actor,
        SystemAction.workspaces_governance_read,
        message="Workspace not found",
        denied_error=ResourceNotFound,
    )
    if not 1 <= limit <= 100 or offset < 0:
        raise ValidationFailure(
            "Workspace page limit must be between 1 and 100; offset must be nonnegative"
        )
    columns = {"name": Workspace.name, "owner": User.username, "created": Workspace.created_at}
    if sort not in columns:
        raise ValidationFailure(f"unknown Workspace sort: {sort}")
    if direction not in {"asc", "desc"}:
        raise ValidationFailure(f"unknown sort direction: {direction}")
    if state and state not in WorkspaceState:
        raise ValidationFailure(f"unknown Workspace state: {state}")
    query = _governance_workspace_query()
    if term := search.strip():
        matches: list[ColumnElement[bool]] = [
            Workspace.name.icontains(term, autoescape=True),
            User.username.icontains(term, autoescape=True),
        ]
        with contextlib.suppress(ValueError):
            identity = UUID(term)
            matches.extend([Workspace.id == identity, User.id == identity])
        query = query.where(or_(*matches))
    if state:
        query = query.where(Workspace.state == state)
    if frozen is not None:
        query = query.where(
            Workspace.governance_frozen_at.is_not(None)
            if frozen
            else Workspace.governance_frozen_at.is_(None)
        )
    if owner_active is not None:
        query = query.where(User.active == owner_active)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.execute(
        query
        .order_by(
            columns[sort].desc() if direction == "desc" else columns[sort].asc(),
            Workspace.id.desc() if direction == "desc" else Workspace.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    workspaces = []
    for workspace, owner in rows.tuples():
        if owner is None:
            raise RuntimeError(f"Workspace owner invariant failed for: {workspace.id}")
        workspaces.append((workspace, owner))
    return workspaces, total


async def get_workspace_for_governance(
    db: AsyncSession, actor: User, workspace_id: UUID
) -> tuple[Workspace, User]:
    await require_system_action(
        db,
        actor,
        SystemAction.workspaces_governance_read,
        message="Workspace not found",
        denied_error=ResourceNotFound,
    )
    row = (
        await db.execute(_governance_workspace_query().where(Workspace.id == workspace_id))
    ).one_or_none()
    if row is None:
        raise ResourceNotFound("Workspace not found")
    workspace, owner = row
    if owner is None:
        raise RuntimeError(f"Workspace owner invariant failed for: {workspace.id}")
    return workspace, owner


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
