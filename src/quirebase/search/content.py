from __future__ import annotations

from typing import TYPE_CHECKING

from inquiro.richtext import convert_rich_text
from sqlalchemy import select

from quirebase.models import FileRevision, Item

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def search_text_for_item(db: AsyncSession, item: Item) -> str:
    full_text = await db.scalar(
        select(FileRevision.full_text)
        .where(FileRevision.item_id == item.id, FileRevision.full_text.is_not(None))
        .order_by(FileRevision.created_at.desc())
        .limit(1)
    )
    return "\n".join(
        value
        for value in (
            convert_rich_text(item.title, source="html", target="text"),
            convert_rich_text(item.abstract, source="html", target="text"),
            item.authors,
            item.editors,
            item.keywords,
            item.custom_fields,
            item.identifiers,
            full_text,
        )
        if value
    )
