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
                    document tsvector NOT NULL
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

    async def index_item(self, db: AsyncSession, item_id: str) -> None:
        await self.ensure_schema(db)
        item = await db.get(Item, item_id)
        await self.remove_item(db, item_id)
        if item is not None:
            await db.execute(
                text(
                    """
                    INSERT INTO item_search(item_id, document)
                    VALUES (:item_id, to_tsvector('simple', :content))
                    """
                ),
                {"item_id": item.id, "content": await search_text_for_item(db, item)},
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
