from __future__ import annotations

import pytest
from item_helpers import metadata_list_values
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.models import Item, ItemIdentifier, User


@pytest.mark.anyio
async def test_item_rich_metadata_fields(async_db):
    db = async_db
    user1 = User(username="user1", password_hash="hash")
    user2 = User(username="user2", password_hash="hash")
    db.add_all([user1, user2])
    await db.flush()
    await provision_initial_workspace(db, user1)
    await provision_initial_workspace(db, user2)

    item = Item(
        title="Deep Learning for Science",
        workspace_id=fixture_workspace_id(user1),
        created_by=user1.id,
        updated_by=user2.id,
        volume="12",
        issue="4",
        pages="100-110",
        publisher="Nature Publishing Group",
        place_published="London",
        journal_abbreviation="Nat. Mach. Intell.",
        citation_key="Smith2026Deep",
        reference_type="article",
        urls=metadata_list_values(
            "https://nature.com/articles/123\nhttps://arxiv.org/abs/2601.00001", urls=True
        ),
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
    assert "affiliation" not in Item.__table__.columns
    assert "affiliations" not in Item.__table__.columns
    assert loaded.publisher == "Nature Publishing Group"
    assert loaded.place_published == "London"
    assert loaded.journal_abbreviation == "Nat. Mach. Intell."
    assert loaded.citation_key == "Smith2026Deep"
    assert loaded.reference_type == "article"
    assert loaded.urls == metadata_list_values(
        "https://nature.com/articles/123\nhttps://arxiv.org/abs/2601.00001", urls=True
    )
    assert loaded.creator.username == "user1"
    assert loaded.updater.username == "user2"


@pytest.mark.anyio
async def test_item_contributors_preserve_order_and_corresponding_status(async_db):
    db = async_db
    user = User(username="author_user", password_hash="hash")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)

    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Graph Neural Networks",
        created_by=user.id,
    )
    item.authors = [
        {
            "display_name": "Smith, Alice",
            "family_name": "Smith",
            "given_name": "Alice",
            "is_corresponding": False,
        },
        {
            "display_name": "Jones, Bob",
            "family_name": "Jones",
            "given_name": "Bob",
            "is_corresponding": True,
        },
    ]
    db.add(item)
    await db.flush()
    await db.refresh(item)
    assert [row["family_name"] for row in item.authors] == ["Smith", "Jones"]
    assert not item.authors[0]["is_corresponding"]
    assert item.authors[1]["is_corresponding"]


@pytest.mark.anyio
async def test_item_identifier_relations(async_db):
    db = async_db
    user = User(username="ident_user", password_hash="hash")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)

    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Quantum Computation",
        created_by=user.id,
    )
    db.add(item)
    await db.flush()

    id1 = ItemIdentifier(
        workspace_id=item.workspace_id, item_id=item.id, provider="doi", value="10.1038/nature12345"
    )
    id2 = ItemIdentifier(
        workspace_id=item.workspace_id, item_id=item.id, provider="arxiv", value="2401.12345"
    )
    id3 = ItemIdentifier(
        workspace_id=item.workspace_id, item_id=item.id, provider="pmid", value="12345678"
    )
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
