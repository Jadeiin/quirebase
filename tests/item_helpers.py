from __future__ import annotations

from uuid import uuid4

from commonmeta.author_utils import get_one_author
from inquiro.work import work_doi, work_schema
from workspace_helpers import fixture_workspace_id_or_create

from quirebase.library import create_item
from quirebase.models import Item, User


def contributor_values(raw: str, *, is_corresponding: bool | None = False) -> list[dict]:
    result = []
    for name in raw.split(";"):
        if not name.strip():
            continue
        credit = get_one_author(name.strip())
        if credit:
            if is_corresponding:
                credit["roles"].append("CorrespondingAuthor")
            result.append(credit)
    return result


def metadata_list_values(raw: str, *, urls: bool = False) -> list:
    values = [
        value.strip() for value in (raw.splitlines() if urls else raw.split(";")) if value.strip()
    ]
    return [{"url": value} for value in values] if urls else values


def contributor(
    family_name: str, given_name: str | None = None, is_corresponding: bool = False, **values
) -> dict:
    person = {"family_name": family_name, **({"given_name": given_name} if given_name else {})}
    roles = ["Author", *(["CorrespondingAuthor"] if is_corresponding else [])]
    return {"type": "Person", "person": person, "roles": roles}


async def create_item_record(
    db, actor: User, *, title: str, abstract: str = "", authors: str = ""
) -> Item:
    workspace_id = await fixture_workspace_id_or_create(db, actor)
    metadata = {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": title}
    if abstract:
        metadata["description"] = abstract
    if authors:
        metadata["contributors"] = contributor_values(authors)
    result = await create_item(db, actor, workspace_id, metadata)
    item = await db.get(Item, result.item_id)
    assert item is not None
    return item


def stored_doi(item: Item) -> str | None:
    return work_doi(item.work)


def work_identifier(namespace: str, value: str) -> dict:
    types = work_schema()["$defs"]["identifier"]["properties"]["identifier_type"]["enum"]
    kind = next((name for name in types if name.lower() == namespace.lower()), "Other")
    return {
        "identifier_type": kind,
        "identifier": value,
        **({"scheme": namespace} if kind == "Other" else {}),
    }
