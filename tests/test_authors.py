from __future__ import annotations

import pytest
from inquiro.bibliography import Contributor as BibliographyContributor
from inquiro.bibliography import parse_bibliography_records
from item_helpers import contributor
from workspace_helpers import provision_initial_workspace

from quirebase.core.errors import WorkspaceMembershipRequired
from quirebase.library import ItemMetadata, create_item, search_authors_typeahead
from quirebase.library.citations import format_standard_export
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
            ItemMetadata(
                "Names", authors=(contributor(family, given), contributor("Research; Council"))
            ),
        )
        item = await db.get(Item, result.item_id)
        await db.refresh(item)
        await db.refresh(item, attribute_names=["identifier_links"])
        assert item.authors == [
            {
                "display_name": str(family) + (", " + str(given) if given else ""),
                "family_name": family,
                "given_name": given,
                "is_corresponding": False,
            },
            {
                "display_name": "Research; Council",
                "family_name": "Research; Council",
                "given_name": None,
                "is_corresponding": False,
            },
        ]
        content, _, _ = format_standard_export([item], "bibtex")
        records, errors = parse_bibliography_records(content, "bibtex")
        assert errors == []
        assert records[0].authors == (
            BibliographyContributor(family, given),
            BibliographyContributor("Research; Council"),
        )
        snapshots.append(item.authors)
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
            ItemMetadata(
                "Suggestions",
                authors=(contributor("Shannon", "Claude"), contributor("Shapiro", "Alex"))
                if actor is reader
                else (contributor("Shaw", "George"),),
                editors=(contributor("Shaver", "Editor"),),
            ),
        )
    results = await search_authors_typeahead(db, reader, workspace, "Sha")
    assert results == [
        {
            "last_name": "Shannon",
            "first_name": "Claude",
            "suffix": None,
            "full_name": "Shannon, Claude",
        },
        {
            "last_name": "Shapiro",
            "first_name": "Alex",
            "suffix": None,
            "full_name": "Shapiro, Alex",
        },
    ]
    assert await search_authors_typeahead(db, reader, workspace, "Sha", limit=1) == results[:1]
    assert await search_authors_typeahead(db, reader, workspace, " ") == []
    assert await search_authors_typeahead(db, reader, workspace, "%") == []
    with pytest.raises(WorkspaceMembershipRequired):
        await search_authors_typeahead(db, reader, other_workspace, "Sha")
