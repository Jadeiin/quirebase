"""Bounded retirement of audit history, independent of resource cleanup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete

from quirebase.core.persistence import delete_page
from quirebase.models import AuditEvent

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


async def purge_audit_events(db: AsyncSession, *, before: datetime, limit: int = 500) -> int:
    """Retire one oldest-first page inside the caller's transaction."""
    return await delete_page(
        db,
        delete(AuditEvent).where(AuditEvent.created_at <= before),
        order_by=(AuditEvent.created_at,),
        limit=limit,
    )
