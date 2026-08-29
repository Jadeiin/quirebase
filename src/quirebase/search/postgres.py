from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, false, select, text

from quirebase.models import Item
from quirebase.search.content import search_text_for_item

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.selectable import SelectBase


class PostgreSQLSearchIndex:
    def ensure_schema(self, db: Session) -> None:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS item_search (
                    item_id varchar(36) PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
                    document tsvector NOT NULL
                )
                """
            )
        )
        db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_item_search_document "
                "ON item_search USING gin(document)"
            )
        )

    def index_item(self, db: Session, item_id: str) -> None:
        self.ensure_schema(db)
        item = db.get(Item, item_id)
        self.remove_item(db, item_id)
        if item is not None:
            db.execute(
                text(
                    """
                    INSERT INTO item_search(item_id, document)
                    VALUES (:item_id, to_tsvector('simple', :content))
                    """
                ),
                {"item_id": item.id, "content": search_text_for_item(db, item)},
            )

    def remove_item(self, db: Session, item_id: str) -> None:
        self.ensure_schema(db)
        db.execute(text("DELETE FROM item_search WHERE item_id = :item_id"), {"item_id": item_id})

    def search(self, db: Session, query: str, limit: int = 200) -> list[str]:
        self.ensure_schema(db)
        if not query.strip():
            return []
        return list(
            db.scalars(
                text(
                    """
                    SELECT item_id FROM item_search
                    WHERE document @@ websearch_to_tsquery('simple', :query)
                    ORDER BY ts_rank(document, websearch_to_tsquery('simple', :query)) DESC
                    LIMIT :limit
                    """
                ),
                {"query": query, "limit": limit},
            ).all()
        )

    def matching_item_ids(self, db: Session, query: str) -> SelectBase:
        """Return an unbounded full-text match as a database-side ID query."""
        self.ensure_schema(db)
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
