from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.access import (
    SystemAction,
    require_system_action,
)
from quirebase.audit import record_event
from quirebase.core.errors import (
    ResourceNotFound,
    ValidationFailure,
)
from quirebase.models import (
    Item,
    User,
    Workspace,
    WorkspaceState,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

from ._locking import _lock_workspace


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
    if workspace is None or workspace.state is WorkspaceState.deleted:
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
