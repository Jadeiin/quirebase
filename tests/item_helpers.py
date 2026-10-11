from __future__ import annotations

from inquiro.bibliography import Contributor as BibliographyContributor
from workspace_helpers import fixture_workspace_id_or_create

from quirebase.library import (
    Contributor,
    ItemMetadata,
    create_item,
)
from quirebase.models import Item, User


def contributor_values(raw: str, *, is_corresponding: bool | None = False) -> list[dict]:
    """Convenient readable fixtures; production persistence accepts structured names only."""
    return [
        {
            "display_name": str(person.family_name)
            + (", " + str(person.given_name) if person.given_name else ""),
            "family_name": person.family_name,
            "given_name": person.given_name,
            "is_corresponding": is_corresponding,
        }
        for part in raw.split(";")
        if part.strip()
        for person in (BibliographyContributor.parse(part.strip()),)
    ]


def metadata_list_values(raw: str, *, urls: bool = False) -> list:
    values = [
        value.strip() for value in (raw.splitlines() if urls else raw.split(";")) if value.strip()
    ]
    return [{"url": value} for value in values] if urls else values


def contributor(
    family_name: str, given_name: str | None = None, is_corresponding: bool = False, **values
) -> Contributor:
    return Contributor(
        display_name=BibliographyContributor(family_name, given_name).display_name(),
        family_name=family_name,
        given_name=given_name,
        is_corresponding=is_corresponding,
        **values,
    )


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
        contributor(
            family_name=str(person.get("family_name") or ""),
            given_name=str(person["given_name"]) if person.get("given_name") else None,
        )
        for person in contributor_values(authors)
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


async def stored_doi(db, item: Item) -> str | None:
    from sqlalchemy import select

    from quirebase.models import ItemIdentifier

    return await db.scalar(
        select(ItemIdentifier.value).where(
            ItemIdentifier.item_id == item.id, ItemIdentifier.provider == "doi"
        )
    )


def bibliography_record_from_item(item: Item):
    from quirebase.library.citations import _item_to_bibliography_record

    return _item_to_bibliography_record(item, item.identifier_links)
