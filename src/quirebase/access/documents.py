from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from quirebase.access.items import can_read_item
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import (
    Attachment,
    FileRevision,
    Item,
    ItemAttachment,
    ItemAuthor,
    ItemFileRevision,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def require_revision(db: AsyncSession, user: User, revision_id: str) -> FileRevision:
    revision = await db.scalar(
        select(FileRevision)
        .options(
            selectinload(FileRevision.items)
            .selectinload(Item.author_links)
            .selectinload(ItemAuthor.author),
            selectinload(FileRevision.items).selectinload(Item.identifier_links),
        )
        .where(FileRevision.id == revision_id)
    )
    item_id = await db.scalar(
        select(ItemFileRevision.item_id)
        .where(ItemFileRevision.file_revision_id == revision_id)
        .limit(1)
    )
    if revision is None or item_id is None or not await can_read_item(db, user, item_id):
        raise ResourceUnavailable("PDF revision not found")
    return revision


async def require_attachment(
    db: AsyncSession, user: User, item_id: str, attachment_id: str
) -> Attachment:
    attachment = await db.get(Attachment, attachment_id)
    linked = (
        attachment is not None
        and await db.scalar(
            select(ItemAttachment.id).where(
                ItemAttachment.item_id == item_id,
                ItemAttachment.attachment_id == attachment_id,
            )
        )
        is not None
    )
    if attachment is None or not linked or not await can_read_item(db, user, item_id):
        raise ResourceUnavailable("attachment not found")
    return attachment
