"""Workspace-scoped document aggregate loaders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.access.scope import workspace_select
from quirebase.models import FileRevision

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.access.context import WorkspaceContext


async def get_revision(
    db: AsyncSession, ctx: WorkspaceContext, revision_id: UUID
) -> FileRevision | None:
    return await db.scalar(
        workspace_select(FileRevision, ctx).where(FileRevision.id == revision_id)
    )
