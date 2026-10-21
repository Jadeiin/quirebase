from __future__ import annotations

from uuid import uuid4

import pytest
from inquiro.bibliography import parse_bibliography_records
from item_helpers import contributor
from workspace_helpers import provision_initial_workspace

from quirebase.core.errors import WorkspaceMembershipRequired
from quirebase.library import create_item, search_authors_typeahead
from quirebase.library.citations import BibliographyFormat, export_item_bibliography
from quirebase.models import Item, User

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


async def _user(db, username: str):
    user = User(username=username, password_hash="unused")
    db.add(user)
    await db.flush()
    workspace = await provision_initial_workspace(db, user)
    await db.commit()
    return user, workspace.id


async def test_contributors_keep_each_records_spelling_and_literal_punctuation(persistence_db):
    db = persistence_db
    first, first_workspace = await _user(db, "first-contributor-workspace")
    second, second_workspace = await _user(db, "second-contributor-workspace")
    snapshots = []
    for actor, workspace, family, given in (
        (first, first_workspace, "Straße", "Ada"),
        (second, second_workspace, "STRASSE", "ADA"),
    ):
        result = await create_item(
            db,
            actor,
            workspace,
            {
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": "Names",
                "contributors": (contributor(family, given), contributor("Research; Council")),
            },
        )
        item = await db.get(Item, result.item_id)
        await db.refresh(item)
        assert item.work["contributors"] == [
            contributor(family, given),
            contributor("Research; Council"),
        ]
        export = await export_item_bibliography(
            db, actor, workspace, item.id, BibliographyFormat.bibtex
        )
        records, errors = parse_bibliography_records(export.content, "bibtex")
        assert not any(row["severity"] == "error" for row in errors)
        assert len(records[0].work["contributors"]) == 2
        snapshots.append(item.work["contributors"])
    assert snapshots[0] is not snapshots[1]
    assert snapshots[0][0] is not snapshots[1][0]


async def test_search_authors_typeahead_uses_only_workspace_item_names(persistence_db):
    db = persistence_db
    reader, workspace = await _user(db, "typeahead-reader")
    other, other_workspace = await _user(db, "typeahead-other")
    for actor, target in ((reader, workspace), (reader, workspace), (other, other_workspace)):
        await create_item(
            db,
            actor,
            target,
            {
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": "Suggestions",
                "contributors": (
                    (contributor("Shannon", "Claude"), contributor("Shapiro", "Alex"))
                    if actor is reader
                    else (contributor("Shaw", "George"),)
                )
                + ({**contributor("Shaver", "Editor"), "roles": ["Editor"]},),
            },
        )
    results = await search_authors_typeahead(db, reader, workspace, "Sha")
    assert results == [
        {
            "last_name": "Shannon",
            "first_name": "Claude",
            "full_name": "Claude Shannon",
        },
        {
            "last_name": "Shapiro",
            "first_name": "Alex",
            "full_name": "Alex Shapiro",
        },
    ]
    assert await search_authors_typeahead(db, reader, workspace, "Sha", limit=1) == results[:1]
    assert await search_authors_typeahead(db, reader, workspace, " ") == []
    assert await search_authors_typeahead(db, reader, workspace, "%") == []
    with pytest.raises(WorkspaceMembershipRequired):
        await search_authors_typeahead(db, reader, other_workspace, "Sha")
