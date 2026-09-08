from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, exists, or_, select, update
from sqlalchemy.orm import selectinload

from quirebase.core.errors import ResourceNotFound, ResourceUnavailable, ValidationFailure
from quirebase.models import (
    Item,
    ItemAuthor,
    ItemLifecycleState,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    SystemRole,
    User,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


def visible_items_query(user: User) -> Select[tuple[Item]]:
    query = select(Item).where(Item.lifecycle_state == ItemLifecycleState.active)
    if user.role == SystemRole.administrator.value:
        return query
    project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    shared_ids = select(ProjectItem.item_id).where(ProjectItem.project_id.in_(project_ids))
    return query.where(or_(Item.created_by == user.id, Item.id.in_(shared_ids)))


async def can_read_item(db: AsyncSession, user: User, item_id: str) -> bool:
    if user.role == SystemRole.administrator.value:
        return bool(
            await db.scalar(
                select(Item.id).where(
                    Item.id == item_id, Item.lifecycle_state == ItemLifecycleState.active
                )
            )
        )
    own = exists().where(
        Item.id == item_id,
        Item.created_by == user.id,
        Item.lifecycle_state == ItemLifecycleState.active,
    )
    # The shared branch must restate the Item conditions: without them the
    # ProjectItem link alone would keep a persistently deleting Item readable
    # to project members during durable deletion and recovery.
    shared = exists().where(
        Item.id == item_id,
        Item.lifecycle_state == ItemLifecycleState.active,
        ProjectItem.item_id == Item.id,
        ProjectMember.project_id == ProjectItem.project_id,
        ProjectMember.user_id == user.id,
    )
    return bool(await db.scalar(select(or_(own, shared))))


async def can_edit_item(db: AsyncSession, user: User, item_id: str) -> bool:
    item = await db.get(Item, item_id)
    if item is None or item.lifecycle_state != ItemLifecycleState.active:
        return False
    if user.role == SystemRole.administrator.value or item.created_by == user.id:
        return True
    editable = exists().where(
        ProjectItem.item_id == item_id,
        ProjectMember.project_id == ProjectItem.project_id,
        ProjectMember.user_id == user.id,
        ProjectMember.role.in_([ProjectRole.owner, ProjectRole.editor]),
    )
    return bool(await db.scalar(select(editable)))


def can_delete_item(db: AsyncSession, user: User, item: Item) -> bool:
    if item.lifecycle_state != ItemLifecycleState.active:
        return False
    if user.role == SystemRole.administrator.value:
        return True
    return item.created_by == user.id


async def require_readable_item(db: AsyncSession, user: User, item_id: str) -> Item:
    if not await can_read_item(db, user, item_id):
        raise ResourceUnavailable("item not found")
    item = await db.scalar(
        select(Item)
        .options(
            selectinload(Item.author_links).selectinload(ItemAuthor.author),
            selectinload(Item.identifier_links),
        )
        .where(Item.id == item_id)
    )
    if item is None:
        raise ResourceNotFound("item not found")
    return item


async def require_editable_item(db: AsyncSession, user: User, item_id: str) -> Item:
    if not await can_edit_item(db, user, item_id):
        raise ResourceUnavailable("item not found")
    item = await db.scalar(
        select(Item)
        .options(
            selectinload(Item.author_links).selectinload(ItemAuthor.author),
            selectinload(Item.identifier_links),
        )
        .where(Item.id == item_id)
    )
    if item is None:
        raise ResourceNotFound("item not found")
    return item


async def require_accessible_items(db: AsyncSession, user: User, item_ids: list[str]) -> list[Item]:
    requested_ids = tuple(dict.fromkeys(item_ids))
    rows = list(
        (
            await db.scalars(
                select(Item)
                .options(
                    selectinload(Item.author_links).selectinload(ItemAuthor.author),
                    selectinload(Item.identifier_links),
                )
                .where(Item.id.in_(requested_ids))
            )
        ).all()
    )
    by_id = {item.id: item for item in rows}
    selected = [by_id.get(item_id) for item_id in requested_ids]
    items = [
        item for item in selected if item is not None and await can_read_item(db, user, item.id)
    ]
    if not items or len(items) != len(selected):
        raise ValidationFailure("select one or more accessible items")
    return items


async def validate_item_lifecycle_fence(
    db: AsyncSession,
    item_id: str,
    lifecycle_fence: int,
    *,
    require_active: bool = True,
) -> Item | None:
    """Return the current Item only when a workflow fence is still valid."""

    predicates = [Item.id == item_id, Item.lifecycle_fence == lifecycle_fence]
    if require_active:
        predicates.append(Item.lifecycle_state == ItemLifecycleState.active)
    if db.get_bind().dialect.name == "sqlite":
        # Validation is intentionally read-only. A no-op UPDATE would acquire
        # SQLite's writer lock and starve an independently running workflow.
        return await db.scalar(select(Item).where(*predicates))
    return await db.scalar(select(Item).where(*predicates).with_for_update())


async def lock_item_edit_scope(db: AsyncSession, item_id: str, lifecycle_fence: int) -> Item | None:
    """Acquire Project authorization gates before the Item lifecycle gate.

    Project membership and assignment mutations lock their Project first and
    may then update the Item. Final workflow authorization must use that same
    order to avoid a PostgreSQL Project/Item deadlock.
    """

    await lock_item_project_gates(db, (item_id,))
    return await lock_item_lifecycle_fence(db, item_id, lifecycle_fence)


async def lock_item_project_gates(db: AsyncSession, item_ids: Sequence[str]) -> tuple[str, ...]:
    """Lock Projects associated with Items in canonical Project-ID order."""

    project_ids = tuple(
        sorted(
            set(
                await db.scalars(
                    select(ProjectItem.project_id).where(ProjectItem.item_id.in_(item_ids))
                )
            )
        )
    )
    for project_id in project_ids:
        await db.scalar(select(Project.id).where(Project.id == project_id).with_for_update())
    return project_ids


async def lock_active_item(db: AsyncSession, item_id: str) -> Item | None:
    """Acquire the active Item row after any required Project gates."""

    predicates = [Item.id == item_id, Item.lifecycle_state == ItemLifecycleState.active]
    if db.get_bind().dialect.name == "sqlite":
        row_id = await db.scalar(
            update(Item)
            .where(*predicates)
            .values(updated_at=Item.updated_at)
            .returning(Item.id)
            .execution_options(synchronize_session=False)
        )
        return await db.get(Item, row_id, populate_existing=True) if row_id else None
    return await db.scalar(select(Item).where(*predicates).with_for_update())


async def lock_item_lifecycle_fence(
    db: AsyncSession, item_id: str, lifecycle_fence: int
) -> Item | None:
    """Validate and acquire the lifecycle row lock for a final workflow write."""

    predicates = [
        Item.id == item_id,
        Item.lifecycle_fence == lifecycle_fence,
        Item.lifecycle_state == ItemLifecycleState.active,
    ]
    if db.get_bind().dialect.name == "sqlite":
        row_id = await db.scalar(
            update(Item)
            .where(*predicates)
            .values(updated_at=Item.updated_at)
            .returning(Item.id)
            .execution_options(synchronize_session=False)
        )
        return await db.get(Item, row_id, populate_existing=True) if row_id else None
    return await db.scalar(select(Item).where(*predicates).with_for_update())
