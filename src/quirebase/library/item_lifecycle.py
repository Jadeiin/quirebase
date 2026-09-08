"""The Library-owned lifecycle boundary for an Item aggregate.

Long-running Documents and Library workflows must never infer lifecycle from a
stale ORM object.  They carry the fence captured at enqueue time and validate it
in their final short transaction through this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, update

from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.models import Item, ItemLifecycleState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def require_item_lifecycle_gate(
    db: AsyncSession,
    item_id: str,
    *,
    expected_fence: int | None = None,
    active_only: bool = True,
    message: str = "item not found",
) -> Item:
    """Acquire the Item write gate and return fresh lifecycle state.

    PostgreSQL obtains a row lock with ``FOR UPDATE``.  SQLite's no-op UPDATE
    acquires the database writer lock, giving the same business serialization
    semantics without process-global locks.
    """

    predicates = [Item.id == item_id]
    if active_only:
        predicates.append(Item.lifecycle_state == ItemLifecycleState.active)
    if expected_fence is not None:
        predicates.append(Item.lifecycle_fence == expected_fence)
    if db.get_bind().dialect.name == "sqlite":
        gated_id = await db.scalar(
            update(Item)
            .where(*predicates)
            .values(updated_at=Item.updated_at)
            .returning(Item.id)
            .execution_options(synchronize_session=False)
        )
        if gated_id is None:
            raise ResourceUnavailable(message)
        item = await db.get(Item, gated_id, populate_existing=True)
    else:
        item = await db.scalar(select(Item).where(*predicates).with_for_update())
    if item is None:
        raise ResourceUnavailable(message)
    return item


async def get_item_lifecycle_fence(db: AsyncSession, item_id: str) -> int:
    value = await db.scalar(select(Item.lifecycle_fence).where(Item.id == item_id))
    if value is None:
        raise ResourceNotFound("item not found")
    return int(value)


async def begin_item_deletion(db: AsyncSession, item_id: str, *, commit: bool = True) -> int:
    """Transition an active Item to ``deleting`` and advance its fence."""

    item = await require_item_lifecycle_gate(db, item_id)
    new_fence = await db.scalar(
        update(Item)
        .where(
            Item.id == item.id,
            Item.lifecycle_state == ItemLifecycleState.active,
            Item.lifecycle_fence == item.lifecycle_fence,
        )
        .values(
            lifecycle_state=ItemLifecycleState.deleting,
            lifecycle_fence=Item.lifecycle_fence + 1,
            aggregate_sequence=Item.aggregate_sequence + 1,
        )
        .returning(Item.lifecycle_fence)
    )
    if new_fence is None:
        raise ResourceUnavailable("item is no longer active")
    await db.flush()
    # A lifecycle transition is itself a durable state-machine edge. The
    # standalone interface commits it so independently running workflows can
    # observe the fence immediately. Commands that also remove children pass
    # ``commit=False`` and commit the complete deletion transaction together.
    if commit:
        await db.commit()
    return int(new_fence)


async def bump_item_aggregate_sequence(db: AsyncSession, item_id: str) -> int:
    """Advance the projection source sequence for an Item-owned mutation."""

    result = await db.scalar(
        update(Item)
        .where(Item.id == item_id, Item.lifecycle_state == ItemLifecycleState.active)
        .values(aggregate_sequence=Item.aggregate_sequence + 1)
        .returning(Item.aggregate_sequence)
        .execution_options(synchronize_session=False)
    )
    if result is None:
        raise ResourceUnavailable("item not found")
    return int(result)


async def validate_item_lifecycle_fence(
    db: AsyncSession,
    item_id: str,
    lifecycle_fence: int,
    *,
    require_active: bool = True,
) -> Item | None:
    predicates = [Item.id == item_id, Item.lifecycle_fence == lifecycle_fence]
    if require_active:
        predicates.append(Item.lifecycle_state == ItemLifecycleState.active)
    if db.get_bind().dialect.name == "sqlite":
        return await db.scalar(select(Item).where(*predicates))
    return await db.scalar(select(Item).where(*predicates).with_for_update())


# Short aliases make the boundary easy to discover for callers and tests.
item_lifecycle_gate = require_item_lifecycle_gate
start_item_deletion = begin_item_deletion
check_item_lifecycle_fence = validate_item_lifecycle_fence
