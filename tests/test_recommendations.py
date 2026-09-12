from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select

from quirebase.core.config import Settings
from quirebase.library.item_metadata import ItemMetadata, create_item
from quirebase.library.tag_recommendations import recommend_item_tags
from quirebase.library.tags import set_item_tags
from quirebase.library.workflows import (
    commit_item_tag_recommendation_step,
    request_item_tag_recommendation,
)
from quirebase.models import Item, ItemTagRecommendation, User


@pytest.mark.anyio
async def test_request_is_idempotent_until_explicitly_superseded(async_db, fake_durable_operations):
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
    first = await request_item_tag_recommendation(db, item.id, owner_id=user.id)
    first_workflow_id = first.workflow_id
    item.keywords = "entirely different upstream keywords"
    second = await request_item_tag_recommendation(db, item.id, owner_id=user.id)

    assert second.id == first.id
    assert second.generation_token == 1
    assert second.workflow_id == first_workflow_id
    assert fake_durable_operations.enqueues[-1]["queue_name"] == "library.recommendation"


@pytest.mark.anyio
async def test_tag_selection_does_not_invalidate_in_flight_recommendation(async_db):
    db = async_db
    user = User(username="recommend-tag-editor", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Independent recommendation input", created_by=user.id)
    db.add(item)
    await db.flush()

    record = await request_item_tag_recommendation(db, item.id, owner_id=user.id)
    assert record.workflow_id is not None
    await db.commit()
    await set_item_tags(
        db,
        user,
        item.id,
        [],
        ["Selected"],
        expected_collection_version=item.tag_collection_version,
    )
    await db.refresh(item)
    assert item.aggregate_sequence == 2
    assert item.recommendation_sequence == 1

    result = await commit_item_tag_recommendation_step(
        item.id,
        record.generation_token,
        record.workflow_id,
        {"single_words": ["candidate"], "phrases": []},
        record.source_sequence,
    )
    assert result == {"single_words": 1, "phrases": 0}


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
    candidates = await recommend_item_tags(db, item_result.item_id, settings=settings)
    await commit_item_tag_recommendation_step(
        item_result.item_id,
        record.generation_token,
        record.workflow_id,
        candidates,
        record.source_sequence,
    )

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
    first = await request_item_tag_recommendation(db, item.id, owner_id=user.id)
    assert first.workflow_id is not None
    await request_item_tag_recommendation(db, item.id, owner_id=user.id, force=True)
    await db.commit()

    candidates = await recommend_item_tags(db, item.id, settings=settings)
    result = await commit_item_tag_recommendation_step(
        item.id,
        1,
        first.workflow_id,
        candidates,
        1,
    )

    current = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item.id)
    )
    assert current is not None
    assert result == {"stale": True}
    assert current.generation_token == 2
    assert current.single_words is None


@pytest.mark.anyio
@pytest.mark.skip(reason="SQLite does not provide the supported PostgreSQL concurrency contract")
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
    await request_item_tag_recommendation(db, item.id, owner_id=user.id)
    await db.commit()
    user_id, item_id = user.id, item.id
    original_updated_at = item.updated_at

    start = asyncio.Barrier(2)

    async def force_request() -> tuple[int, str]:
        async with async_session_factory() as worker_db:
            await start.wait()
            record = await request_item_tag_recommendation(
                worker_db, item_id, owner_id=user_id, force=True
            )
            await worker_db.commit()
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
    record = await request_item_tag_recommendation(db, item.id, owner_id=user.id)
    assert record.workflow_id is not None

    with pytest.raises(RuntimeError, match="KEYBERT_MODEL_PATH"):
        await recommend_item_tags(db, item.id, settings=settings)


@pytest.mark.anyio
async def test_generation_result_does_not_include_source_text(async_db, monkeypatch):
    from types import SimpleNamespace

    from quirebase.models import FileRevision, FileRevisionProcessingState

    db = async_db
    user = User(username="compact-generation-owner", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Compact checkpoint", created_by=user.id)
    db.add(item)
    await db.flush()
    db.add(
        FileRevision(
            item_id=item.id,
            object_key="aa/bb/full-text.pdf",
            size=1,
            original_name="full-text.pdf",
            full_text="checkpoint sentinel " * 20_000,
            processing_state=FileRevisionProcessingState.ready,
            created_by=user.id,
        )
    )
    settings = Settings(
        _env_file=None,
        recommendation_engine="yake",
        recommendation_max_chars=200_000,
    )

    class Engine:
        def recommend(self, _documents, _limits):
            return (SimpleNamespace(single_words=("compact",), phrases=("compact result",)),)

    monkeypatch.setattr("quirebase.library.tag_recommendations._engine", lambda _settings: Engine())
    candidates = await recommend_item_tags(db, item.id, settings=settings)

    assert candidates == {"single_words": ["compact"], "phrases": ["compact result"]}
    assert "checkpoint sentinel" not in json.dumps(candidates)


@pytest.mark.anyio
async def test_result_is_rejected_when_item_moves_past_the_carried_sequence(
    async_db, fake_durable_operations
):
    db = async_db
    user = User(username="stale-seq-owner", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Moving aggregate", created_by=user.id)
    db.add(item)
    await db.flush()

    await request_item_tag_recommendation(db, item.id, owner_id=user.id)
    await db.commit()
    record = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item.id)
    )
    assert record is not None and record.source_sequence == 1

    # While the Item is still at the carried sequence the result lands.
    result = await commit_item_tag_recommendation_step(
        item.id,
        record.generation_token,
        record.workflow_id,
        {"single_words": ["fresh"], "phrases": []},
        source_sequence=1,
    )
    assert result == {"single_words": 1, "phrases": 0}

    # A PDF commit advances the aggregate before the follow-up request
    # refreshes the record; the old generation must no longer be accepted.
    item.recommendation_sequence = 2
    await db.commit()

    stale = await commit_item_tag_recommendation_step(
        item.id,
        record.generation_token,
        record.workflow_id,
        {"single_words": ["stale"], "phrases": []},
        source_sequence=1,
    )
    assert stale == {"stale": True}

    await db.refresh(record)
    assert json.loads(record.single_words) == ["fresh"]
