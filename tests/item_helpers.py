from __future__ import annotations

from workspace_helpers import fixture_workspace_id_or_create

from quirebase.library import (
    Contributor,
    ItemMetadata,
    create_item,
    parse_author_list_string,
)
from quirebase.models import Item, User


async def create_item_record(
    db,
    actor: User,
    *,
    title: str,
    abstract: str = "",
    authors: str = "",
) -> Item:
    workspace_id = await fixture_workspace_id_or_create(db, actor)
    contributors = tuple(
        Contributor(
            last_name=str(person.get("last_name") or ""),
            first_name=str(person["first_name"]) if person.get("first_name") else None,
        )
        for person in parse_author_list_string(authors)
    )
    result = await create_item(
        db,
        actor,
        workspace_id,
        ItemMetadata(title=title, abstract=abstract, authors=contributors),
    )
    item = await db.get(Item, result.item_id)
    assert item is not None
    return item
