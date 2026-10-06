from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, select

from quirebase.access import (
    ResourceAction,
    WorkspaceContext,
    require_action,
    require_workspace_action,
)
from quirebase.models import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def list_workspaces(db: AsyncSession, actor: User) -> list[tuple[Workspace, WorkspaceMember]]:
    if not actor.active:
        return []
    rows = await db.execute(
        select(Workspace, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == actor.id,
            WorkspaceMember.state == WorkspaceMemberState.active,
            WorkspaceMember.terminated_at.is_(None),
            Workspace.state != WorkspaceState.deleted,
        )
        .order_by(Workspace.name, Workspace.id)
    )
    return list(rows.tuples())


async def workspace_owner_ids(db: AsyncSession, workspace_ids: set[str]) -> dict[str, str]:
    """Return owners of surviving Workspaces, validating their owner membership."""
    if not workspace_ids:
        return {}
    rows = await db.execute(
        select(Workspace.id, WorkspaceMember.user_id)
        .outerjoin(
            WorkspaceMember,
            and_(
                WorkspaceMember.workspace_id == Workspace.id,
                WorkspaceMember.role == WorkspaceRole.owner,
                WorkspaceMember.state == WorkspaceMemberState.active,
                WorkspaceMember.terminated_at.is_(None),
            ),
        )
        .where(Workspace.id.in_(workspace_ids), Workspace.state != WorkspaceState.deleted)
    )
    # Read root existence and membership in one snapshot: a concurrent root
    # deletion also removes its owner and is not an invariant violation.
    owner_rows = rows.tuples().all()
    missing = {workspace_id for workspace_id, owner_id in owner_rows if owner_id is None}
    if missing:
        raise RuntimeError(f"Workspace owner membership invariant failed for: {sorted(missing)}")
    return {workspace_id: owner_id for workspace_id, owner_id in owner_rows if owner_id is not None}


async def get_workspace(
    db: AsyncSession, actor: User, workspace_id: str
) -> tuple[Workspace, WorkspaceMember]:
    context = await require_workspace_action(db, actor, workspace_id, ResourceAction.workspace_read)
    return context.workspace, context.membership


async def list_workspace_members(
    db: AsyncSession, context: WorkspaceContext
) -> list[WorkspaceMember]:
    require_action(context, ResourceAction.workspace_read)
    workspace_id = context.workspace_id
    return list(
        (
            await db.scalars(
                select(WorkspaceMember)
                .join(User, User.id == WorkspaceMember.user_id)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.state == WorkspaceMemberState.active,
                    WorkspaceMember.terminated_at.is_(None),
                    User.active.is_(True),
                )
                .order_by(WorkspaceMember.created_at, WorkspaceMember.id)
            )
        ).all()
    )


async def list_workspace_governance_members(
    db: AsyncSession, context: WorkspaceContext
) -> list[WorkspaceMember]:
    require_action(context, ResourceAction.workspace_member_read)
    workspace_id = context.workspace_id
    return list(
        (
            await db.scalars(
                select(WorkspaceMember)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.terminated_at.is_(None),
                )
                .order_by(WorkspaceMember.created_at, WorkspaceMember.id)
            )
        ).all()
    )
