from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from quirebase.access.items import require_readable_item
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import Attachment, FileRevision, Item, ItemAuthor, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def require_revision(
    db: AsyncSession, user: User, workspace_id: str, revision_id: str
) -> FileRevision:
    revision = await db.scalar(
        select(FileRevision)
        .options(
            selectinload(FileRevision.item)
            .selectinload(Item.author_links)
            .selectinload(ItemAuthor.author),
            selectinload(FileRevision.item).selectinload(Item.identifier_links),
        )
        .where(
            FileRevision.id == revision_id,
            FileRevision.workspace_id == workspace_id,
        )
    )
    if revision is None:
        raise ResourceUnavailable("File Revision not found")
    await require_readable_item(db, user, workspace_id, revision.item_id)
    return revision


async def require_attachment(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    attachment_id: str,
) -> Attachment:
    attachment = await db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.workspace_id == workspace_id,
            Attachment.item_id == item_id,
        )
    )
    if attachment is None:
        raise ResourceUnavailable("Attachment not found")
    await require_readable_item(db, user, workspace_id, item_id)
    return attachment
