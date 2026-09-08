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
                    source_sequence UNINDEXED,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
        )
        # FTS virtual tables cannot be altered with ADD COLUMN. A database
        # created before source sequencing is rebuilt once on first use.
        columns = {
            row[1] for row in (await db.execute(text("PRAGMA table_info(item_search)"))).all()
        }
        if "source_sequence" not in columns:
            await db.execute(text("ALTER TABLE item_search RENAME TO item_search_legacy"))
            await db.execute(
                text("""
                CREATE VIRTUAL TABLE item_search USING fts5(
                    item_id UNINDEXED, content, source_sequence UNINDEXED,
                    tokenize='unicode61 remove_diacritics 2'
                )
            """)
            )
            await db.execute(
                text(
                    "INSERT INTO item_search(item_id, content, source_sequence) "
                    "SELECT item_id, content, 0 FROM item_search_legacy"
                )
            )
            await db.execute(text("DROP TABLE item_search_legacy"))

    async def index_item(
        self, db: AsyncSession, item_id: str, source_sequence: int | None = None
    ) -> None:
        # The read-guard plus delete+insert is safe on SQLite because writers
        # serialize at the database level: this sequence runs inside the
        # caller's write-locked transaction. FTS5 tables cannot carry the
        # ON CONFLICT guard the PostgreSQL adapter uses (item_id is UNINDEXED).
        await self.ensure_schema(db)
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
