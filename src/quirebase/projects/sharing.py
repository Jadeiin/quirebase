from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import inspect, select

from quirebase.core.errors import ResourceUnavailable
from quirebase.models import (
    Item,
    ItemAttachment,
    ItemAuthor,
    ItemFileRevision,
    ItemIdentifier,
    ProjectItem,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_COPY_EXCLUDED_COLUMNS = {
    "id",
    "owner_id",
    "created_by",
    "updated_by",
    "version",
    "created_at",
    "updated_at",
}


async def clone_item_for_project(
    db: AsyncSession, source: Item, actor: User, *, owner_id: str | None = None
) -> Item:
    """Materialize an Independent Copy without copying immutable object bytes."""
    # Mapper inspection keeps this aligned with the canonical ORM mapping without
    # mutating the source instance or copying SQLAlchemy relationship state.
    values = {
        attribute.key: getattr(source, attribute.key)
        for attribute in inspect(Item).mapper.column_attrs
        if attribute.key not in _COPY_EXCLUDED_COLUMNS
    }
    copy = Item(
        **values,
        owner_id=owner_id,
        created_by=actor.id,
        updated_by=actor.id,
        version=1,
    )
    db.add(copy)
    await db.flush()

    authors = list(
        (await db.scalars(select(ItemAuthor).where(ItemAuthor.item_id == source.id))).all()
    )
    db.add_all([
        ItemAuthor(
            item_id=copy.id,
            author_id=row.author_id,
            position=row.position,
            role=row.role,
            is_corresponding=row.is_corresponding,
        )
        for row in authors
    ])
    identifiers = list(
        (await db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == source.id))).all()
    )
    db.add_all([
        ItemIdentifier(item_id=copy.id, provider=row.provider, value=row.value)
        for row in identifiers
    ])
    revisions = list(
        (
            await db.scalars(select(ItemFileRevision).where(ItemFileRevision.item_id == source.id))
        ).all()
    )
    db.add_all([
        ItemFileRevision(item_id=copy.id, file_revision_id=row.file_revision_id)
        for row in revisions
    ])
    attachments = list(
        (await db.scalars(select(ItemAttachment).where(ItemAttachment.item_id == source.id))).all()
    )
    db.add_all([
        ItemAttachment(item_id=copy.id, attachment_id=row.attachment_id, role=row.role)
        for row in attachments
    ])
    await db.flush()
    return copy


async def require_item_for_extension(db: AsyncSession, actor: User, item_id: str) -> Item:
    item = await db.get(Item, item_id, populate_existing=True)
    if item is None:
        raise ResourceUnavailable("item not found")
    if item.owner_id != actor.id:
        raise ResourceUnavailable("only the Item Owner may extend a Live Copy")
    return item


async def fork_owned_project_items(
    db: AsyncSession, project_id: str, owner_id: str, actor: User
) -> int:
    """Fork every Live Copy in a Project before an Item Owner loses edit access."""
    assignments = list(
        (
            await db.scalars(
                select(ProjectItem)
                .join(Item, Item.id == ProjectItem.item_id)
                .where(ProjectItem.project_id == project_id, Item.owner_id == owner_id)
                .order_by(ProjectItem.id)
                .with_for_update()
            )
        ).all()
    )
    for assignment in assignments:
        source = await db.get(Item, assignment.item_id, populate_existing=True)
        if source is None:
            continue
        copy = await clone_item_for_project(db, source, actor)
        assignment.item_id = copy.id
    return len(assignments)
