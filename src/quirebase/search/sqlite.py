from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import String, false, select, text

from quirebase.models import Item
from quirebase.search.content import search_text_for_item

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.selectable import SelectBase


class SQLiteSearchIndex:
    async def ensure_schema(self, db: AsyncSession) -> None:
        await db.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS item_search USING fts5(
                    item_id UNINDEXED,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
        )

    async def index_item(self, db: AsyncSession, item_id: str) -> None:
        await self.ensure_schema(db)
        item = await db.get(Item, item_id)
        await self.remove_item(db, item_id)
        if item is not None:
            await db.execute(
                text("INSERT INTO item_search(item_id, content) VALUES (:item_id, :content)"),
                {"item_id": item.id, "content": await search_text_for_item(db, item)},
            )

    async def remove_item(self, db: AsyncSession, item_id: str) -> None:
        await self.ensure_schema(db)
        await db.execute(
            text("DELETE FROM item_search WHERE item_id = :item_id"), {"item_id": item_id}
        )

    async def search(self, db: AsyncSession, query: str, limit: int = 200) -> list[str]:
        await self.ensure_schema(db)
        tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if not tokens:
            return []
        expression = " AND ".join(f'"{token}"' for token in tokens)
        return list(
            (
                await db.scalars(
                    text(
                        """
                    SELECT item_id FROM item_search
                    WHERE item_search MATCH :query
                    ORDER BY bm25(item_search)
                    LIMIT :limit
                    """
                    ),
                    {"query": expression, "limit": limit},
                )
            ).all()
        )

    async def matching_item_ids(self, db: AsyncSession, query: str) -> SelectBase:
        """Return an unbounded FTS match as a database-side ID query."""
        await self.ensure_schema(db)
        tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if not tokens:
            return select(Item.id).where(false())
        expression = " AND ".join(f'"{token}"' for token in tokens)
        return (
            text(
                """
                SELECT item_id FROM item_search
                WHERE item_search MATCH :query
                """
            )
            .bindparams(query=expression)
            .columns(item_id=String)
        )
