from __future__ import annotations

import json

import pytest
from inquiro.bibliography import parse_bibliography_records
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.library import BibliographyFormat, create_item, export_workspace_bibliography
from quirebase.models import Item, User

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


@pytest.mark.parametrize("file_format", ["bibtex", "ris", "csl-json", "commonmeta", "csl"])
@pytest.mark.parametrize("keys", [["ManualKey", "ManualKey"], ["Café", "Cafe\u0301"]])
async def test_duplicate_items_export_from_work_in_fresh_session(persistence_db, file_format, keys):
    db = persistence_db
    actor = User(username="export-owner", password_hash="hash")
    db.add(actor)
    await db.flush()
    await provision_initial_workspace(db, actor)
    await db.commit()
    workspace_id = fixture_workspace_id(actor)
    values = {
        "id": "https://doi.org/10.1234/shared",
        "type": "JournalArticle",
        "title": "Research",
        "contributors": [
            {
                "type": "Person",
                "person": {"family_name": "Smith", "given_name": "Jane"},
                "roles": ["Author"],
            }
        ],
        "date_published": "2024",
    }
    ids = []
    for index in range(2):
        result = await create_item(
            db,
            actor,
            workspace_id,
            values | {"title": f"Research {index}"},
            citation_key=keys[index],
        )
        ids.append(result.item_id)
    db.expunge_all()
    actor = await db.get(User, actor.id)
    export = await export_workspace_bibliography(
        db, actor, workspace_id, BibliographyFormat(file_format)
    )
    contents = export.content
    if file_format == "csl":
        assert "Smith" in contents and "Research 0" in contents and "Research 1" in contents
    else:
        records, diagnostics = parse_bibliography_records(contents, file_format)
        assert len(records) == 2 and not any(row["severity"] == "error" for row in diagnostics)
        valid_keys = [[keys[0], f"{keys[1]}a"], [keys[1], f"{keys[0]}a"]]
        if file_format == "bibtex":
            assert {row.citation_key for row in records} in [set(value) for value in valid_keys]
        if file_format == "csl-json":
            from citeproc.source.json import CiteProcJSON

            entries = json.loads(contents)
            assert [entry["id"] for entry in entries] in valid_keys
            assert len(CiteProcJSON(entries)) == 2
    assert [(await db.get(Item, item_id)).citation_key for item_id in ids] == keys
