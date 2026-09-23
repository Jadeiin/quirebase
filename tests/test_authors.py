from __future__ import annotations

import pytest
from inquiro.bibliography import Contributor as BibliographyContributor
from inquiro.bibliography import parse_bibliography_records
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import WorkspaceMembershipRequired
from quirebase.library.authors import (
    find_or_create_author,
    get_item_authors,
    parse_author_name,
    search_authors_typeahead,
    set_item_authors,
    set_item_authors_from_string,
)
from quirebase.library.citations import format_standard_export
from quirebase.models import Author, Item, ItemAuthor, User


async def _user(db, username: str) -> User:
    user = User(username=username, password_hash="hash")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.flush()
    return user


def test_parse_author_name():
    assert parse_author_name("Smith, Alice") == ("Smith", "Alice")
    assert parse_author_name("Alice Smith") == ("Smith", "Alice")
    assert parse_author_name("Einstein") == ("Einstein", None)
    assert parse_author_name("  Turing,  Alan M. ") == ("Turing", "Alan M.")


@pytest.mark.anyio
async def test_set_and_get_item_authors(async_db):
    db = async_db
    user = await _user(db, "author_test_user")

    item = Item(
        workspace_id=fixture_workspace_id(user), title="Information Theory", created_by=user.id
    )
    db.add(item)
    await db.flush()

    authors_data = [
        {"last_name": "Shannon", "first_name": "Claude", "is_corresponding": True},
        {"last_name": "Weaver", "first_name": "Warren", "is_corresponding": False},
    ]
    await set_item_authors(
        db, user, fixture_workspace_id(user), item.id, authors_data, role="author"
    )
    await db.commit()

    links = await get_item_authors(db, item.id, role="author")
    assert len(links) == 2
    assert links[0].author.last_name == "Shannon"
    assert links[0].position == 1
    assert links[0].is_corresponding
    assert links[1].author.last_name == "Weaver"
    assert links[1].position == 2
    assert not links[1].is_corresponding

    # Check cache string on Item
    loaded_item = await db.get(Item, item.id)
    assert loaded_item is not None
    assert loaded_item.authors == "Shannon, Claude; Weaver, Warren"


@pytest.mark.anyio
async def test_set_item_authors_from_string(async_db):
    db = async_db
    user = await _user(db, "string_author_user")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Computing Machinery",
        authors="Turing, Alan",
        created_by=user.id,
    )
    db.add(item)
    await db.flush()

    await set_item_authors_from_string(db, user, item)

    assert item.authors == "Turing, Alan"
    assert [link.author.last_name for link in await get_item_authors(db, item.id)] == ["Turing"]


@pytest.mark.anyio
async def test_set_item_authors_from_string_preserves_parser_compatible_names(async_db):
    db = async_db
    user = await _user(db, "structured-author-user")
    item = Item(
        title="Structured contributors",
        workspace_id=fixture_workspace_id(user),
        authors="{World Health Organization}; de la Cruz, Jr., Juan",
        created_by=user.id,
    )
    db.add(item)
    await db.flush()

    await set_item_authors_from_string(db, user, item)

    assert item.authors == "World Health Organization; de la Cruz Jr., Juan"
    contributors = await get_item_authors(db, item.id)
    assert [(link.author.last_name, link.author.first_name) for link in contributors] == [
        ("World Health Organization", None),
        ("de la Cruz Jr.", "Juan"),
    ]


@pytest.mark.anyio
async def test_set_item_authors_projects_suffix_names_into_first_last_identity(async_db):
    db = async_db
    user = await _user(db, "structured-identity-user")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Simplified contributor identities",
        created_by=user.id,
    )
    db.add(item)
    await db.flush()

    await set_item_authors(
        db,
        user,
        fixture_workspace_id(user),
        item.id,
        [
            {"last_name": "Smith", "first_name": "John"},
            {"last_name": "Example Institute"},
        ],
    )
    await db.flush()

    links = await get_item_authors(db, item.id)
    assert [(link.author.last_name, link.author.first_name) for link in links] == [
        ("Smith", "John"),
        ("Example Institute", None),
    ]
    assert item.authors == "Smith, John; Example Institute"

    loaded_item = await db.scalar(
        select(Item)
        .options(selectinload(Item.author_links).selectinload(ItemAuthor.author))
        .where(Item.id == item.id)
        .execution_options(populate_existing=True)
    )
    assert loaded_item is not None
    contents, _media_type, _filename = format_standard_export([loaded_item], "bibtex")
    records, errors = parse_bibliography_records(contents, "bibtex")
    assert errors == []
    assert records[0].authors == (
        BibliographyContributor("Smith", "John"),
        BibliographyContributor("Example Institute"),
    )


@pytest.mark.anyio
async def test_search_authors_typeahead(async_db):
    db = async_db
    reader = await _user(db, "typeahead-reader")
    other = await _user(db, "typeahead-other")
    reader_item = Item(
        workspace_id=fixture_workspace_id(reader), title="Reader", created_by=reader.id
    )
    other_item = Item(workspace_id=fixture_workspace_id(other), title="Other", created_by=other.id)
    db.add_all([reader_item, other_item])
    await db.flush()
    local = await find_or_create_author(db, last_name="Shannon", first_name="Claude")
    remote = await find_or_create_author(db, last_name="Shaw", first_name="George")
    shared = await find_or_create_author(db, last_name="Shapiro", first_name="Alex")
    await find_or_create_author(db, last_name="Shaver", first_name="Unlinked")
    db.add_all([
        ItemAuthor(item_id=reader_item.id, author_id=local.id),
        ItemAuthor(item_id=other_item.id, author_id=remote.id),
        ItemAuthor(item_id=reader_item.id, author_id=shared.id),
        ItemAuthor(item_id=other_item.id, author_id=shared.id),
    ])
    await db.commit()

    results = await search_authors_typeahead(db, reader, fixture_workspace_id(reader), "Sha")
    assert [row["id"] for row in results] == [local.id, shared.id]
    assert await search_authors_typeahead(db, reader, fixture_workspace_id(reader), "Sha", 1) == [
        results[0]
    ]
    with pytest.raises(WorkspaceMembershipRequired):
        await search_authors_typeahead(db, reader, fixture_workspace_id(other), "Sha")


@pytest.mark.anyio
async def test_find_or_create_author_uses_casefolded_null_safe_identity(async_db):
    first = await find_or_create_author(async_db, last_name=" Smith ", first_name=None)
    second = await find_or_create_author(async_db, last_name="smith", first_name="")
    assert first.id == second.id

    direct = Author(last_name="  World  Health ", first_name=" Organization ")
    async_db.add(direct)
    await async_db.flush()
    assert direct.identity_key == "world health\x1forganization"
