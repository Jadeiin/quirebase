from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.core.errors import (
    ResourceNotFound,
    WorkspaceUnavailable,
)
from quirebase.models import (
    Workspace,
    WorkspaceMember,
    WorkspaceState,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def _lock_workspace(db: AsyncSession, workspace_id: UUID) -> Workspace:
    workspace = await db.scalar(
        select(Workspace)
        .where(Workspace.id == workspace_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if workspace is None or workspace.state is WorkspaceState.deleted:
        raise WorkspaceUnavailable("Workspace not found")
    return workspace


async def _current_member(
    db: AsyncSession, workspace_id: UUID, membership_id: UUID
) -> WorkspaceMember:
    member = await db.scalar(
        select(WorkspaceMember)
        .where(
            WorkspaceMember.id == membership_id,
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.terminated_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    if member is None:
        raise ResourceNotFound("Workspace member not found")
    return member
