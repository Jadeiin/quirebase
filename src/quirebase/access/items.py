from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload

from quirebase.access.context import WorkspaceContext, require_workspace_action
from quirebase.access.scope import workspace_select
from quirebase.access.workspace_policy import ResourceAction
from quirebase.core.errors import (
    PermissionDenied,
    ResourceUnavailable,
    ValidationFailure,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
    WorkspaceUnavailable,
)
from quirebase.models import Item, ItemAuthor, User

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def visible_items_query(workspace_id: UUID) -> Select[tuple[Item]]:
    return select(Item).where(Item.workspace_id == workspace_id)


def workspace_items_query(ctx: WorkspaceContext) -> Select[tuple[Item]]:
    """Return the Item lineage query for a resolved context."""

    return workspace_select(Item, ctx)


async def get_item(db: AsyncSession, ctx: WorkspaceContext, item_id: UUID) -> Item | None:
    """Load an Item by id inside an already-resolved Workspace context."""

    return await db.scalar(
        workspace_select(Item, ctx)
        .options(
            selectinload(Item.author_links).selectinload(ItemAuthor.author),
            selectinload(Item.identifier_links),
        )
        .where(Item.id == item_id)
    )


async def get_item_for_update(
    db: AsyncSession, ctx: WorkspaceContext, item_id: UUID
) -> Item | None:
    """Load an Item root with a row lock for a mutation boundary."""

    return await db.scalar(
        workspace_select(Item, ctx)
        .options(
            selectinload(Item.author_links).selectinload(ItemAuthor.author),
            selectinload(Item.identifier_links),
        )
        .where(Item.id == item_id)
        .with_for_update()
    )


async def can_read_item(db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID) -> bool:
    try:
        await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    except (PermissionDenied, WorkspaceMembershipRequired, WorkspaceUnavailable):
        return False
    return bool(
        await db.scalar(
            select(Item.id).where(Item.id == item_id, Item.workspace_id == workspace_id)
        )
    )


async def can_edit_item(db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID) -> bool:
    try:
        await require_workspace_action(db, user, workspace_id, ResourceAction.item_update)
    except (
        PermissionDenied,
        WorkspaceMembershipRequired,
        WorkspaceUnavailable,
        WorkspaceLifecycleError,
    ):
        return False
    return bool(
        await db.scalar(
            select(Item.id).where(Item.id == item_id, Item.workspace_id == workspace_id)
        )
    )


async def can_delete_item(db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID) -> bool:
    try:
        await require_workspace_action(db, user, workspace_id, ResourceAction.item_delete)
    except (
        PermissionDenied,
        WorkspaceMembershipRequired,
        WorkspaceUnavailable,
        WorkspaceLifecycleError,
    ):
        return False
    return bool(
        await db.scalar(
            select(Item.id).where(Item.id == item_id, Item.workspace_id == workspace_id)
        )
    )


async def require_item_action(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    action: ResourceAction,
) -> Item:
    context = await require_workspace_action(db, user, workspace_id, action)
    item = await get_item(db, context, item_id)
    if item is None:
        raise ResourceUnavailable("Item not found")
    return item


async def require_readable_item(
    db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID
) -> Item:
    return await require_item_action(db, user, workspace_id, item_id, ResourceAction.workspace_read)


async def require_editable_item(
    db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID
) -> Item:
    return await require_item_action(db, user, workspace_id, item_id, ResourceAction.item_update)


async def require_accessible_items(
    db: AsyncSession, user: User, workspace_id: UUID, item_ids: list[UUID]
) -> list[Item]:
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    requested = tuple(dict.fromkeys(item_ids))
    rows = list(
        (
            await db.scalars(
                select(Item)
                .options(
                    selectinload(Item.author_links).selectinload(ItemAuthor.author),
                    selectinload(Item.identifier_links),
                )
                .where(Item.workspace_id == workspace_id, Item.id.in_(requested))
            )
        ).all()
    )
    by_id = {item.id: item for item in rows}
    if not requested or any(item_id not in by_id for item_id in requested):
        raise ValidationFailure("select one or more accessible Items")
    return [by_id[item_id] for item_id in requested]
