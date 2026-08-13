from __future__ import annotations

import re
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import FileRevision, Item, ItemTag, Project, ProjectItem, Tag


class SearchIndex(Protocol):
    def index_item(self, db: Session, item_id: str) -> None: ...

    def remove_item(self, db: Session, item_id: str) -> None: ...

    def search(self, db: Session, query: str, limit: int = 200) -> list[str]: ...


def _search_text(db: Session, item: Item) -> str:
    full_text = db.scalar(
        select(FileRevision.full_text)
        .where(FileRevision.item_id == item.id, FileRevision.full_text.is_not(None))
        .order_by(FileRevision.created_at.desc())
        .limit(1)
    )
    tags = db.scalars(
        select(Tag.name).join(ItemTag, ItemTag.tag_id == Tag.id).where(ItemTag.item_id == item.id)
    ).all()
    projects = db.scalars(
        select(Project.name)
        .join(ProjectItem, ProjectItem.project_id == Project.id)
        .where(ProjectItem.item_id == item.id)
    ).all()
    return "\n".join(
        value
        for value in (
            item.title, item.abstract, item.authors, item.editors, item.keywords,
            item.custom_fields, item.identifiers, full_text, " ".join(tags), " ".join(projects)
        )
        if value
    )


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
                {"item_id": item.id, "content": _search_text(db, item)},
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
                {"item_id": item.id, "content": _search_text(db, item)},
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
