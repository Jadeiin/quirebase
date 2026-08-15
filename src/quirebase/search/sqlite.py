from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import text

from quirebase.models import Item
from quirebase.search.content import search_text_for_item

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class SQLiteSearchIndex:
    def ensure_schema(self, db: Session) -> None:
        db.execute(
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

    def index_item(self, db: Session, item_id: str) -> None:
        self.ensure_schema(db)
        item = db.get(Item, item_id)
        self.remove_item(db, item_id)
        if item is not None:
            db.execute(
                text("INSERT INTO item_search(item_id, content) VALUES (:item_id, :content)"),
                {"item_id": item.id, "content": search_text_for_item(db, item)},
            )

    def remove_item(self, db: Session, item_id: str) -> None:
        self.ensure_schema(db)
        db.execute(text("DELETE FROM item_search WHERE item_id = :item_id"), {"item_id": item_id})

    def search(self, db: Session, query: str, limit: int = 200) -> list[str]:
        self.ensure_schema(db)
        tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if not tokens:
            return []
        expression = " AND ".join(f'"{token}"' for token in tokens)
        return list(
            db.scalars(
                text(
                    """
                    SELECT item_id FROM item_search
                    WHERE item_search MATCH :query
                    ORDER BY bm25(item_search)
                    LIMIT :limit
                    """
                ),
                {"query": expression, "limit": limit},
            ).all()
        )
