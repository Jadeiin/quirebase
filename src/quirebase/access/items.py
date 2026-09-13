from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, exists, or_, select
from sqlalchemy.orm import selectinload

from quirebase.core.errors import ResourceNotFound, ResourceUnavailable, ValidationFailure
from quirebase.models import (
    Item,
    ItemAuthor,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    SystemRole,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def visible_items_query(user: User) -> Select[tuple[Item]]:
    query = select(Item)
    if user.role == SystemRole.administrator.value:
        return query
    project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    shared_ids = select(ProjectItem.item_id).where(ProjectItem.project_id.in_(project_ids))
    return query.where(or_(Item.created_by == user.id, Item.id.in_(shared_ids)))


async def can_read_item(db: AsyncSession, user: User, item_id: str) -> bool:
    if user.role == SystemRole.administrator.value:
        return await db.get(Item, item_id) is not None
    own = exists().where(Item.id == item_id, Item.created_by == user.id)
    shared = exists().where(
        ProjectItem.item_id == item_id,
        ProjectMember.project_id == ProjectItem.project_id,
        ProjectMember.user_id == user.id,
    )
    return bool(await db.scalar(select(or_(own, shared))))


async def can_edit_item(db: AsyncSession, user: User, item_id: str) -> bool:
    item = await db.get(Item, item_id)
    if item is None:
        return False
    if user.role == SystemRole.administrator.value or item.created_by == user.id:
        return True
    editable = exists().where(
        ProjectItem.item_id == item_id,
        ProjectMember.project_id == ProjectItem.project_id,
        Project.state == "active",
        Project.id == ProjectItem.project_id,
        ProjectMember.user_id == user.id,
        ProjectMember.role.in_([ProjectRole.owner, ProjectRole.editor]),
    )
    return bool(await db.scalar(select(editable)))


def can_delete_item(db: AsyncSession, user: User, item: Item) -> bool:
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
        raise ResourceUnavailable("item not found")
    return item


async def require_editable_item(db: AsyncSession, user: User, item_id: str) -> Item:
    item = await db.scalar(
        select(Item)
        .options(
            selectinload(Item.author_links).selectinload(ItemAuthor.author),
            selectinload(Item.identifier_links),
        )
        .where(Item.id == item_id)
    )
    if item is None:
        raise ResourceUnavailable("item not found")
    if user.role == SystemRole.administrator.value or item.created_by == user.id:
        return item
    editable = exists().where(
        ProjectItem.item_id == item_id,
        ProjectMember.project_id == ProjectItem.project_id,
        Project.state == "active",
        Project.id == ProjectItem.project_id,
        ProjectMember.user_id == user.id,
        ProjectMember.role.in_([ProjectRole.owner, ProjectRole.editor]),
    )
    if not await db.scalar(select(editable)):
        raise ResourceUnavailable("item not found")
    return item


async def require_editable_item_for_mutation(db: AsyncSession, user: User, item_id: str) -> Item:
    """Authorize an Item mutation while holding its active Project grant.

    Project archival takes a no-key-update lock on the Project root.  Locking
    the granting Project with ``FOR SHARE`` here makes authorization and the
    subsequent Item/child mutation one linearization point.  Item owners and
    administrators do not depend on Project state and therefore need no
    additional root lock.
    """
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
    if user.role == SystemRole.administrator.value or item.created_by == user.id:
        return item
    project = await db.scalar(
        select(Project)
        .join(ProjectItem, ProjectItem.project_id == Project.id)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            ProjectItem.item_id == item_id,
            ProjectMember.user_id == user.id,
            ProjectMember.role.in_([ProjectRole.owner, ProjectRole.editor]),
            Project.state == "active",
        )
        .order_by(Project.id)
        .with_for_update(read=True, of=Project)
    )
    if project is None:
        raise ResourceUnavailable("item not found")
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
