from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.models import Item
from quirebase.search.postgres import PostgreSQLSearchIndex
from quirebase.search.sqlite import SQLiteSearchIndex

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from quirebase.search.protocol import SearchIndex


def search_index(db: Session) -> SearchIndex:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return PostgreSQLSearchIndex()
    return SQLiteSearchIndex()


def reindex_all(db: Session) -> int:
    index = search_index(db)
    item_ids = list(db.scalars(select(Item.id)).all())
    for item_id in item_ids:
        index.index_item(db, item_id)
    return len(item_ids)
