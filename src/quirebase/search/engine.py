from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.models import Item
from quirebase.search.postgres import PostgreSQLSearchIndex
from quirebase.search.sqlite import SQLiteSearchIndex

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.search.protocol import SearchIndex


def search_index(db: AsyncSession) -> SearchIndex:
    if db.get_bind().dialect.name == "postgresql":
        return PostgreSQLSearchIndex()
    return SQLiteSearchIndex()


async def reindex_all(db: AsyncSession) -> int:
    index = search_index(db)
    item_ids = list((await db.scalars(select(Item.id))).all())
    for item_id in item_ids:
        await index.index_item(db, item_id)
    return len(item_ids)
