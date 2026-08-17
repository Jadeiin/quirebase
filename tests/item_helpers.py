from __future__ import annotations

from quirebase.library import (
    Contributor,
    ItemMetadata,
    create_item,
    parse_author_list_string,
)
from quirebase.models import Item, User


def create_item_record(
    db,
    actor: User,
    *,
    title: str,
    abstract: str = "",
    authors: str = "",
) -> Item:
    contributors = tuple(
        Contributor(
            last_name=str(person.get("last_name") or ""),
            first_name=str(person["first_name"]) if person.get("first_name") else None,
        )
        for person in parse_author_list_string(authors)
    )
    result = create_item(
        db,
        actor,
        ItemMetadata(title=title, abstract=abstract, authors=contributors),
    )
    item = db.get(Item, result.item_id)
    assert item is not None
    return item
