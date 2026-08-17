from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import selectinload

from quirebase.access.items import require_editable_item
from quirebase.core.errors import ValidationFailure
from quirebase.models import Author, Item, ItemAuthor, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def parse_author_name(name_str: str) -> tuple[str, str | None]:
    cleaned = " ".join(name_str.split())
    if not cleaned:
        raise ValidationFailure("author name cannot be empty")
    if "," in cleaned:
        parts = cleaned.split(",", 1)
        last = parts[0].strip()
        first = parts[1].strip() or None
        return last, first
    parts = cleaned.split()
    if len(parts) == 1:
        return parts[0], None
    return parts[-1], " ".join(parts[:-1])


def parse_author_list_string(raw: str | None) -> list[dict[str, str | None]]:
    if not raw or not raw.strip():
        return []
    authors: list[dict[str, str | None]] = []
    for part in raw.split(";"):
        cleaned = part.strip()
        if cleaned:
            last, first = parse_author_name(cleaned)
            authors.append({"last_name": last, "first_name": first})
    return authors


def find_or_create_author(db: Session, last_name: str, first_name: str | None = None) -> Author:
    last = " ".join(last_name.split())
    if not last:
        raise ValidationFailure("author last name is required")
    first = " ".join(first_name.split()) if first_name else None

    stmt = select(Author).where(
        Author.last_name.ilike(last),
        Author.first_name.ilike(first) if first else Author.first_name.is_(None),
    )
    author = db.scalar(stmt)
    if author is None:
        author = Author(last_name=last, first_name=first)
        db.add(author)
        db.flush()
    return author


def set_item_authors(
    db: Session,
    user: User,
    item_id: str,
    authors_data: list[dict],
    role: str = "author",
) -> list[ItemAuthor]:
    item = require_editable_item(db, user, item_id)

    db.execute(delete(ItemAuthor).where(ItemAuthor.item_id == item_id, ItemAuthor.role == role))
    db.flush()

    links: list[ItemAuthor] = []
    formatted_names: list[str] = []

    for pos, entry in enumerate(authors_data, start=1):
        last = entry.get("last_name", "").strip()
        first = entry.get("first_name")
        if first:
            first = first.strip() or None
        if not last:
            continue
        author = find_or_create_author(db, last_name=last, first_name=first)
        is_corr = bool(entry.get("is_corresponding", False))
        link = ItemAuthor(
            item_id=item_id,
            author_id=author.id,
            position=pos,
            role=role,
            is_corresponding=is_corr,
        )
        db.add(link)
        links.append(link)
        if first:
            formatted_names.append(f"{last}, {first}")
        else:
            formatted_names.append(last)

    joined_str = "; ".join(formatted_names) or None
    if role == "author":
        item.authors = joined_str
    elif role == "editor":
        item.editors = joined_str

    db.flush()
    return links


def set_item_authors_from_string(
    db: Session,
    user: User,
    item: Item,
    role: str = "author",
) -> list[ItemAuthor]:
    raw = item.authors if role == "author" else item.editors
    parsed_authors = parse_author_list_string(raw)
    if not parsed_authors:
        return []
    return set_item_authors(db, user, item.id, parsed_authors, role=role)


def get_item_authors(db: Session, item_id: str, role: str = "author") -> list[ItemAuthor]:
    return list(
        db.scalars(
            select(ItemAuthor)
            .options(selectinload(ItemAuthor.author))
            .where(ItemAuthor.item_id == item_id, ItemAuthor.role == role)
            .order_by(ItemAuthor.position)
        ).all()
    )


def search_authors_typeahead(db: Session, query: str, limit: int = 10) -> list[dict]:
    term = query.strip()
    if not term:
        return []
    pattern = f"{term}%"
    stmt = (
        select(Author)
        .where(
            or_(
                Author.last_name.ilike(pattern),
                Author.first_name.ilike(pattern),
            )
        )
        .order_by(Author.last_name, Author.first_name)
        .limit(limit)
    )
    authors = list(db.scalars(stmt).all())
    return [
        {
            "id": a.id,
            "last_name": a.last_name,
            "first_name": a.first_name,
            "full_name": f"{a.last_name}, {a.first_name}" if a.first_name else a.last_name,
        }
        for a in authors
    ]
