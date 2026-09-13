from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, false, select, text

from quirebase.models import FileRevision, Item
from quirebase.search.content import search_text_for_item, search_text_for_revision

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
        await db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS revision_search (
                    revision_id varchar(36) PRIMARY KEY REFERENCES file_revisions(id) ON DELETE CASCADE,
                    item_id varchar(36) NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    document tsvector NOT NULL
                )
                """
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_revision_search_document "
                "ON revision_search USING gin(document)"
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
                {"item_id": item.id, "content": search_text_for_item(item)},
            )

    async def remove_item(self, db: AsyncSession, item_id: str) -> None:
        await self.ensure_schema(db)
        await db.execute(
            text("DELETE FROM item_search WHERE item_id = :item_id"), {"item_id": item_id}
        )
        await db.execute(
            text("DELETE FROM revision_search WHERE item_id = :item_id"), {"item_id": item_id}
        )

    async def index_revision(self, db: AsyncSession, revision_id: str) -> None:
        await self.ensure_schema(db)
        revision = await db.get(FileRevision, revision_id)
        await self.remove_revision(db, revision_id)
        if revision is not None and revision.full_text:
            await db.execute(
                text(
                    """
                    INSERT INTO revision_search(revision_id, item_id, document)
                    VALUES (:revision_id, :item_id, to_tsvector('simple', :content))
                    """
                ),
                {
                    "revision_id": revision.id,
                    "item_id": revision.item_id,
                    "content": search_text_for_revision(revision),
                },
            )

    async def remove_revision(self, db: AsyncSession, revision_id: str) -> None:
        await self.ensure_schema(db)
        await db.execute(
            text("DELETE FROM revision_search WHERE revision_id = :revision_id"),
            {"revision_id": revision_id},
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
                    SELECT item_id FROM (
                        SELECT item_id,
                               ts_rank(document, websearch_to_tsquery('simple', :query)) AS rank
                        FROM item_search
                        WHERE document @@ websearch_to_tsquery('simple', :query)
                        UNION ALL
                        SELECT item_id,
                               ts_rank(document, websearch_to_tsquery('simple', :query)) AS rank
                        FROM revision_search
                        WHERE document @@ websearch_to_tsquery('simple', :query)
                    ) matches
                    GROUP BY item_id
                    ORDER BY MAX(rank) DESC
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
                UNION
                SELECT item_id FROM revision_search
                WHERE document @@ websearch_to_tsquery('simple', :query)
                """
            )
            .bindparams(query=query)
            .columns(item_id=String)
        )
