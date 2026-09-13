"""The Library-owned lifecycle boundary for an Item aggregate.

Long-running Documents and Library workflows re-read and lock the Item row in
their final short transaction. Item UUIDs are never reused, so the row itself is
the lifecycle boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.core.errors import ResourceUnavailable
from quirebase.models import Item, ItemLifecycleState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def require_item_lifecycle_gate(
    db: AsyncSession,
    item_id: str,
    *,
    active_only: bool = True,
    message: str = "item not found",
) -> Item:
    """Acquire the Item write gate and return fresh lifecycle state.

    PostgreSQL obtains a row lock with ``FOR UPDATE``. SQLite accepts the same
    query for local single-process development but does not provide an
    equivalent multi-worker concurrency guarantee.
    """

    predicates = [Item.id == item_id]
    if active_only:
        predicates.append(Item.lifecycle_state == ItemLifecycleState.active)
    item = await db.scalar(select(Item).where(*predicates).with_for_update())
    if item is None:
        raise ResourceUnavailable(message)
    return item


async def begin_item_deletion(db: AsyncSession, item_id: str) -> None:
    """Lock an active Item and mark it deleting before hard deletion."""

    item = await require_item_lifecycle_gate(db, item_id)
    item.lifecycle_state = ItemLifecycleState.deleting
    await db.flush()


# Short aliases make the boundary easy to discover for callers and tests.
item_lifecycle_gate = require_item_lifecycle_gate
start_item_deletion = begin_item_deletion
