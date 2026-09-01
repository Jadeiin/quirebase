from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from quirebase.models import Author, Item, ItemAuthor, ItemIdentifier, User


@pytest.mark.anyio
async def test_item_rich_metadata_fields(async_db):
    db = async_db
    user1 = User(username="user1", password_hash="hash")
    user2 = User(username="user2", password_hash="hash")
    db.add_all([user1, user2])
    await db.flush()

    item = Item(
        title="Deep Learning for Science",
        created_by=user1.id,
        updated_by=user2.id,
        volume="12",
        issue="4",
        pages="100-110",
        affiliation="MIT AI Lab",
        publisher="Nature Publishing Group",
        place_published="London",
        journal_abbreviation="Nat. Mach. Intell.",
        bibtex_id="Smith2026Deep",
        bibtex_type="article",
        urls="https://nature.com/articles/123\nhttps://arxiv.org/abs/2601.00001",
    )
    db.add(item)
    await db.flush()

    loaded = await db.scalar(
        select(Item)
        .options(selectinload(Item.creator), selectinload(Item.updater))
        .where(Item.id == item.id)
    )
    assert loaded is not None
    assert loaded.volume == "12"
    assert loaded.issue == "4"
    assert loaded.pages == "100-110"
    assert loaded.affiliation == "MIT AI Lab"
    assert loaded.publisher == "Nature Publishing Group"
    assert loaded.place_published == "London"
    assert loaded.journal_abbreviation == "Nat. Mach. Intell."
    assert loaded.bibtex_id == "Smith2026Deep"
    assert loaded.bibtex_type == "article"
    assert loaded.urls == "https://nature.com/articles/123\nhttps://arxiv.org/abs/2601.00001"
    assert loaded.creator.username == "user1"
    assert loaded.updater.username == "user2"


@pytest.mark.anyio
async def test_author_and_item_author_relations(async_db):
    db = async_db
    user = User(username="author_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Graph Neural Networks", created_by=user.id)
    author1 = Author(first_name="Alice", last_name="Smith")
    author2 = Author(first_name="Bob", last_name="Jones")
    db.add_all([item, author1, author2])
    await db.flush()

    link1 = ItemAuthor(
        item_id=item.id, author_id=author1.id, position=1, role="author", is_corresponding=False
    )
    link2 = ItemAuthor(
        item_id=item.id, author_id=author2.id, position=2, role="author", is_corresponding=True
    )
    db.add_all([link1, link2])
    await db.flush()

    loaded_item = await db.scalar(
        select(Item)
        .options(selectinload(Item.author_links).selectinload(ItemAuthor.author))
        .where(Item.id == item.id)
    )
    assert loaded_item is not None
    assert len(loaded_item.author_links) == 2
    assert loaded_item.author_links[0].author.last_name == "Smith"
    assert loaded_item.author_links[0].position == 1
    assert not loaded_item.author_links[0].is_corresponding
    assert loaded_item.author_links[1].author.last_name == "Jones"
    assert loaded_item.author_links[1].position == 2
    assert loaded_item.author_links[1].is_corresponding


@pytest.mark.anyio
async def test_item_identifier_relations(async_db):
    db = async_db
    user = User(username="ident_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Quantum Computation", created_by=user.id)
    db.add(item)
    await db.flush()

    id1 = ItemIdentifier(item_id=item.id, provider="doi", value="10.1038/nature12345")
    id2 = ItemIdentifier(item_id=item.id, provider="arxiv", value="2401.12345")
    id3 = ItemIdentifier(item_id=item.id, provider="pmid", value="12345678")
    db.add_all([id1, id2, id3])
    await db.flush()

    loaded_item = await db.scalar(
        select(Item).options(selectinload(Item.identifier_links)).where(Item.id == item.id)
    )
    assert loaded_item is not None
    assert len(loaded_item.identifier_links) == 3
    providers = {link.provider: link.value for link in loaded_item.identifier_links}
    assert providers["doi"] == "10.1038/nature12345"
    assert providers["arxiv"] == "2401.12345"
    assert providers["pmid"] == "12345678"
