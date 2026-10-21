"""Retirement of completed admission records without changing current authority."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, delete, func, or_

from quirebase.core.persistence import delete_page
from quirebase.models import WorkspaceInvitation, WorkspaceMember

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


async def purge_workspace_history(
    db: AsyncSession, *, before: datetime, limit: int = 500
) -> dict[str, int]:
    """Delete bounded terminal history; never retire a current membership generation."""
    invitation_terminal_at = func.coalesce(
        WorkspaceInvitation.accepted_at,
        WorkspaceInvitation.revoked_at,
        WorkspaceInvitation.expires_at,
    )
    return {
        "workspace_invitations": await delete_page(
            db,
            delete(WorkspaceInvitation).where(
                or_(
                    WorkspaceInvitation.accepted_at <= before,
                    and_(
                        WorkspaceInvitation.accepted_at.is_(None),
                        WorkspaceInvitation.revoked_at <= before,
                    ),
                    and_(
                        WorkspaceInvitation.accepted_at.is_(None),
                        WorkspaceInvitation.revoked_at.is_(None),
                        WorkspaceInvitation.expires_at <= before,
                    ),
                )
            ),
            order_by=(invitation_terminal_at,),
            limit=limit,
        ),
        "workspace_members": await delete_page(
            db,
            delete(WorkspaceMember).where(WorkspaceMember.terminated_at <= before),
            order_by=(WorkspaceMember.terminated_at,),
            limit=limit,
        ),
    }
