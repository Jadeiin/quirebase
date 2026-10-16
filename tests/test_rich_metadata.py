from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.models import Item, User


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
        workspace_id=fixture_workspace_id(user1),
        created_by=user1.id,
        updated_by=user2.id,
        citation_key="Smith2026Deep",
        work={
            "id": f"urn:uuid:{uuid4()}",
            "type": "JournalArticle",
            "title": "Deep Learning for Science",
            "container": {
                "volume": "12",
                "issue": "4",
                "first_page": "100-110",
                "location": "London",
                "additional_titles": ["Nat. Mach. Intell."],
            },
            "publisher": {"name": "Nature Publishing Group"},
        },
    )
    db.add(item)
    await db.flush()
    loaded = await db.scalar(
        select(Item)
        .options(selectinload(Item.creator), selectinload(Item.updater))
        .where(Item.id == item.id)
    )
    assert loaded is not None
    assert loaded.work.get("container", {}).get("volume") == "12"
    assert loaded.work.get("container", {}).get("issue") == "4"
    assert loaded.work.get("container", {}).get("first_page") == "100-110"
    assert "affiliation" not in Item.__table__.columns
    assert "affiliations" not in Item.__table__.columns
    assert loaded.work.get("publisher", {}).get("name") == "Nature Publishing Group"
    assert loaded.work.get("container", {}).get("location") == "London"
    assert loaded.work.get("container", {}).get("additional_titles") == ["Nat. Mach. Intell."]
    assert loaded.citation_key == "Smith2026Deep"
    assert loaded.work.get("type") == "JournalArticle"
    assert loaded.creator.username == "user1"
    assert loaded.updater.username == "user2"


@pytest.mark.anyio
async def test_item_contributors_preserve_order_and_corresponding_status(async_db):
    from item_helpers import contributor

    user = User(username="credit-owner", password_hash="hash")
    async_db.add(user)
    await async_db.flush()
    await provision_initial_workspace(async_db, user)
    credits = [contributor("Smith", "Alice"), contributor("Jones", "Bob", True)]
    item = Item(
        workspace_id=fixture_workspace_id(user),
        created_by=user.id,
        work={
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Credits",
            "contributors": credits,
        },
    )
    async_db.add(item)
    await async_db.commit()
    async_db.expunge_all()
    reloaded = await async_db.get(Item, item.id)
    assert reloaded.work["contributors"] == credits
