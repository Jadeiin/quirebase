from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select

from quirebase.core.config import Settings
from quirebase.library.item_metadata import ItemMetadata, create_item
from quirebase.library.tag_recommendations import (
    force_item_tag_recommendation,
    handle_item_tag_recommendation,
    request_item_tag_recommendation,
)
from quirebase.models import Item, ItemTagRecommendation, User


@pytest.mark.anyio
async def test_request_is_idempotent_and_item_keywords_do_not_change_fingerprint(async_db):
    db = async_db
    user = User(username="recommend-owner", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(
        title="Graph representation learning for molecules",
        abstract="A robust neural method for molecular prediction.",
        keywords="provider supplied keyword",
        created_by=user.id,
    )
    db.add(item)
    await db.flush()
    settings = Settings(_env_file=None, recommendation_engine="yake")

    first = await request_item_tag_recommendation(db, item.id, owner_id=user.id, settings=settings)
    first_workflow_id = first.workflow_id
    item.keywords = "entirely different upstream keywords"
    second = await request_item_tag_recommendation(db, item.id, owner_id=user.id, settings=settings)

    assert second.id == first.id
    assert second.generation_token == 1
    assert second.workflow_id == first_workflow_id


@pytest.mark.anyio
async def test_item_creation_enqueues_and_worker_persists_yake_results(async_db, monkeypatch):
    db = async_db
    user = User(username="automatic-owner", password_hash="hash")
    db.add(user)
    await db.commit()
    settings = Settings(_env_file=None, recommendation_engine="yake")
    monkeypatch.setattr("quirebase.library.tag_recommendations.get_settings", lambda: settings)

    item_result = await create_item(
        db,
        user,
        ItemMetadata(
            title="Graph neural networks for molecular property prediction",
            abstract=(
                "Graph neural networks learn molecular representations and improve "
                "property prediction with robust message passing methods."
            ),
        ),
    )
    record = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_result.item_id)
    )
    assert record is not None
    assert record.workflow_id is not None
    await handle_item_tag_recommendation(
        db,
        item_result.item_id,
        record.generation_token,
        record.workflow_id,
        user.id,
        settings=settings,
    )
    await db.commit()

    await db.refresh(record)
    assert record.generated_at is not None
    assert len(json.loads(record.single_words or "[]")) <= 10
    assert len(json.loads(record.phrases or "[]")) <= 10


@pytest.mark.anyio
async def test_stale_job_cannot_overwrite_new_generation(async_db):
    db = async_db
    user = User(username="stale-owner", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Stable title", abstract="Enough English content", created_by=user.id)
    db.add(item)
    await db.flush()
    settings = Settings(_env_file=None, recommendation_engine="yake")
    first = await request_item_tag_recommendation(db, item.id, owner_id=user.id, settings=settings)
    assert first.workflow_id is not None
    await request_item_tag_recommendation(
        db, item.id, owner_id=user.id, force=True, settings=settings
    )

    result = await handle_item_tag_recommendation(
        db,
        item.id,
        1,
        first.workflow_id,
        user.id,
        settings=settings,
    )

    current = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item.id)
    )
    assert current is not None
    assert result == {"stale": True}
    assert current.generation_token == 2
    assert current.single_words is None


@pytest.mark.anyio
async def test_concurrent_force_requests_receive_distinct_generation_tokens(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="concurrent-recommend-owner", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Concurrent recommendation requests", created_by=user.id)
    db.add(item)
    await db.flush()
    settings = Settings(_env_file=None, recommendation_engine="yake")
    await request_item_tag_recommendation(db, item.id, owner_id=user.id, settings=settings)
    await db.commit()
    user_id, item_id = user.id, item.id
    original_updated_at = item.updated_at

    start = asyncio.Barrier(2)

    async def force_request() -> tuple[int, str]:
        async with async_session_factory() as worker_db:
            await start.wait()
            worker_user = await worker_db.get(User, user_id)
            assert worker_user is not None
            record = await force_item_tag_recommendation(
                worker_db,
                worker_user,
                item_id,
                settings=settings,
            )
            assert record.workflow_id is not None
            return record.generation_token, record.workflow_id

    results = await asyncio.gather(force_request(), force_request())

    assert {token for token, _job_id in results} == {2, 3}
    assert len({workflow_id for _token, workflow_id in results}) == 2
    await db.refresh(item)
    assert item.updated_at.replace(tzinfo=original_updated_at.tzinfo) == original_updated_at


@pytest.mark.anyio
async def test_missing_keybert_configuration_fails_explicitly(async_db):
    db = async_db
    user = User(username="keybert-owner", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Local semantic extraction", created_by=user.id)
    db.add(item)
    await db.flush()
    settings = Settings(
        _env_file=None,
        recommendation_engine="keybert",
        keybert_model_path=None,
    )
    record = await request_item_tag_recommendation(db, item.id, owner_id=user.id, settings=settings)
    assert record.workflow_id is not None

    with pytest.raises(RuntimeError, match="KEYBERT_MODEL_PATH"):
        await handle_item_tag_recommendation(
            db,
            item.id,
            record.generation_token,
            record.workflow_id,
            user.id,
            settings=settings,
        )
