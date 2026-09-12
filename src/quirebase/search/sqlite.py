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
    async def index_item(
        self, db: AsyncSession, item_id: str, source_sequence: int | None = None
    ) -> None:
        # FTS5 cannot express the PostgreSQL conditional upsert because
        # ``item_id`` is UNINDEXED. SQLite is a single-process development
        # profile without a supported multi-worker concurrency guarantee, so
        # this adapter performs the functional sequence check without trying
        # to emulate a database writer lock.
        item = await db.get(Item, item_id, populate_existing=True)
        if item is None:
            await self.remove_item(db, item_id)
            return
        if source_sequence is None:
            source_sequence = item.aggregate_sequence
        source_sequence = source_sequence or 0
        current = await db.scalar(
            text("SELECT source_sequence FROM item_search WHERE item_id = :item_id"),
            {"item_id": item_id},
        )
        if current is not None and int(current) > source_sequence:
            return
        await self.remove_item(db, item_id)
        await db.execute(
            text(
                "INSERT INTO item_search(item_id, content, source_sequence) VALUES (:item_id, :content, :source_sequence)"
            ),
            {
                "item_id": item.id,
                "content": await search_text_for_item(db, item),
                "source_sequence": source_sequence,
            },
        )

    async def remove_item(self, db: AsyncSession, item_id: str) -> None:
        await db.execute(
            text("DELETE FROM item_search WHERE item_id = :item_id"), {"item_id": item_id}
        )

    async def search(self, db: AsyncSession, query: str, limit: int = 200) -> list[str]:
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
