from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, false, select, text

from quirebase.models import Item
from quirebase.search.content import search_text_for_item

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.selectable import SelectBase


class PostgreSQLSearchIndex:
    async def ensure_schema(self, db: AsyncSession) -> None:
        await db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS item_search (
                    item_id varchar(36) PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
                    document tsvector NOT NULL,
                    source_sequence integer NOT NULL DEFAULT 0
                )
                """
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_item_search_document "
                "ON item_search USING gin(document)"
            )
        )
        columns = {
            row[0]
            for row in (
                await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'item_search' AND table_schema = current_schema()"
                    )
                )
            ).all()
        }
        if "source_sequence" not in columns:
            # The probe avoids re-locking the table on every call; IF NOT
            # EXISTS closes the race between two first requests that both
            # observe the missing column.
            await db.execute(
                text(
                    "ALTER TABLE item_search ADD COLUMN IF NOT EXISTS "
                    "source_sequence integer NOT NULL DEFAULT 0"
                )
            )

    async def index_item(
        self, db: AsyncSession, item_id: str, source_sequence: int | None = None
    ) -> None:
        await self.ensure_schema(db)
        item = await db.get(Item, item_id, populate_existing=True)
        if item is None:
            await self.remove_item(db, item_id)
            return
        if source_sequence is None:
            source_sequence = item.aggregate_sequence
        # One conditional upsert: a concurrent transaction can no longer read
        # the old sequence and then delete or overwrite a newer projection.
        # Stale results (lower sequence) lose the comparison inside the same
        # statement and leave the stored projection untouched.
        await db.execute(
            text(
                """
                INSERT INTO item_search(item_id, document, source_sequence)
                VALUES (:item_id, to_tsvector('simple', :content), :source_sequence)
                ON CONFLICT (item_id) DO UPDATE
                SET document = EXCLUDED.document,
                    source_sequence = EXCLUDED.source_sequence
                WHERE item_search.source_sequence <= EXCLUDED.source_sequence
                """
            ),
            {
                "item_id": item.id,
                "content": await search_text_for_item(db, item),
                "source_sequence": source_sequence or 0,
            },
        )

    async def remove_item(self, db: AsyncSession, item_id: str) -> None:
        await self.ensure_schema(db)
        await db.execute(
            text("DELETE FROM item_search WHERE item_id = :item_id"), {"item_id": item_id}
        )

    async def search(self, db: AsyncSession, query: str, limit: int = 200) -> list[str]:
        await self.ensure_schema(db)
        if not query.strip():
            return []
        return list(
            (
                await db.scalars(
                    text(
                        """
                    SELECT item_id FROM item_search
                    WHERE document @@ websearch_to_tsquery('simple', :query)
                    ORDER BY ts_rank(document, websearch_to_tsquery('simple', :query)) DESC
                    LIMIT :limit
                    """
                    ),
                    {"query": query, "limit": limit},
                )
            ).all()
        )

    async def matching_item_ids(self, db: AsyncSession, query: str) -> SelectBase:
        """Return an unbounded full-text match as a database-side ID query."""
        await self.ensure_schema(db)
        if not query.strip():
            return select(Item.id).where(false())
        return (
            text(
                """
                SELECT item_id FROM item_search
                WHERE document @@ websearch_to_tsquery('simple', :query)
                """
            )
            .bindparams(query=query)
            .columns(item_id=String)
        )
