from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from quirebase.access.items import can_read_item
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import Attachment, FileRevision, Item, ItemAuthor, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def require_revision(db: AsyncSession, user: User, revision_id: str) -> FileRevision:
    revision = await db.scalar(
        select(FileRevision)
        .options(
            selectinload(FileRevision.item)
            .selectinload(Item.author_links)
            .selectinload(ItemAuthor.author),
            selectinload(FileRevision.item).selectinload(Item.identifier_links),
        )
        .where(FileRevision.id == revision_id)
    )
    if revision is None or not await can_read_item(db, user, revision.item_id):
        raise ResourceUnavailable("PDF revision not found")
    return revision


async def require_attachment(
    db: AsyncSession, user: User, item_id: str, attachment_id: str
) -> Attachment:
    attachment = await db.get(Attachment, attachment_id)
    if (
        attachment is None
        or attachment.item_id != item_id
        or not await can_read_item(db, user, item_id)
    ):
        raise ResourceUnavailable("attachment not found")
    return attachment
