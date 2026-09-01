from __future__ import annotations

import pytest
from inquiro.bibliography import Contributor as BibliographyContributor
from inquiro.bibliography import parse_bibliography_records
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from quirebase.library.authors import (
    find_or_create_author,
    get_item_authors,
    parse_author_name,
    search_authors_typeahead,
    set_item_authors,
    set_item_authors_from_string,
)
from quirebase.library.citations import format_standard_export
from quirebase.models import Item, ItemAuthor, User


def test_parse_author_name():
    assert parse_author_name("Smith, Alice") == ("Smith", "Alice")
    assert parse_author_name("Alice Smith") == ("Smith", "Alice")
    assert parse_author_name("Einstein") == ("Einstein", None)
    assert parse_author_name("  Turing,  Alan M. ") == ("Turing", "Alan M.")


@pytest.mark.anyio
async def test_set_and_get_item_authors(async_db):
    db = async_db
    user = User(username="author_test_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Information Theory", created_by=user.id)
    db.add(item)
    await db.flush()

    authors_data = [
        {"last_name": "Shannon", "first_name": "Claude", "is_corresponding": True},
        {"last_name": "Weaver", "first_name": "Warren", "is_corresponding": False},
    ]
    await set_item_authors(db, user, item.id, authors_data, role="author")
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
    user = User(username="string_author_user", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Computing Machinery", authors="Turing, Alan", created_by=user.id)
    db.add(item)
    await db.flush()

    await set_item_authors_from_string(db, user, item)

    assert item.authors == "Turing, Alan"
    assert [link.author.last_name for link in await get_item_authors(db, item.id)] == ["Turing"]


@pytest.mark.anyio
async def test_set_item_authors_from_string_preserves_parser_compatible_names(async_db):
    db = async_db
    user = User(username="structured-author-user", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(
        title="Structured contributors",
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
    user = User(username="structured-identity-user", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Simplified contributor identities", created_by=user.id)
    db.add(item)
    await db.flush()

    await set_item_authors(
        db,
        user,
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
    await find_or_create_author(db, last_name="Shannon", first_name="Claude")
    await find_or_create_author(db, last_name="Shaw", first_name="George")
    await find_or_create_author(db, last_name="Turing", first_name="Alan")
    await db.commit()

    results = await search_authors_typeahead(db, "Sha")
    assert len(results) == 2
    assert any(r["last_name"] == "Shannon" for r in results)
    assert any(r["last_name"] == "Shaw" for r in results)
