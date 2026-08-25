from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from quirebase.core.config import Settings
from quirebase.library.item_metadata import ItemMetadata, create_item
from quirebase.library.tag_recommendations import (
    force_item_tag_recommendation,
    handle_item_tag_recommendation,
    request_item_tag_recommendation,
)
from quirebase.models import Item, ItemTagRecommendation, Job, JobState, User
from quirebase.pipeline.jobs import run_job


def test_request_is_idempotent_and_item_keywords_do_not_change_fingerprint(db):
    user = User(username="recommend-owner", password_hash="hash")
    db.add(user)
    db.flush()
    item = Item(
        title="Graph representation learning for molecules",
        abstract="A robust neural method for molecular prediction.",
        keywords="provider supplied keyword",
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    settings = Settings(_env_file=None, recommendation_engine="yake")

    first = request_item_tag_recommendation(db, item.id, owner_id=user.id, settings=settings)
    first_job_id = first.job_id
    item.keywords = "entirely different upstream keywords"
    second = request_item_tag_recommendation(db, item.id, owner_id=user.id, settings=settings)

    assert second.id == first.id
    assert second.generation_token == 1
    assert second.job_id == first_job_id


def test_item_creation_enqueues_and_worker_persists_yake_results(db, monkeypatch):
    user = User(username="automatic-owner", password_hash="hash")
    db.add(user)
    db.commit()
    settings = Settings(_env_file=None, recommendation_engine="yake")
    monkeypatch.setattr("quirebase.library.tag_recommendations.get_settings", lambda: settings)

    item_result = create_item(
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
    record = db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_result.item_id)
    )
    job = db.get(Job, record.job_id)
    job.state = JobState.running
    job.attempts = 1

    run_job(db, job)

    db.refresh(record)
    db.refresh(job)
    assert job.state == JobState.succeeded
    assert record.generated_at is not None
    assert len(json.loads(record.single_words or "[]")) <= 10
    assert len(json.loads(record.phrases or "[]")) <= 10


def test_stale_job_cannot_overwrite_new_generation(db):
    user = User(username="stale-owner", password_hash="hash")
    db.add(user)
    db.flush()
    item = Item(title="Stable title", abstract="Enough English content", created_by=user.id)
    db.add(item)
    db.flush()
    settings = Settings(_env_file=None, recommendation_engine="yake")
    first = request_item_tag_recommendation(db, item.id, owner_id=user.id, settings=settings)
    first_job = db.get(Job, first.job_id)
    request_item_tag_recommendation(db, item.id, owner_id=user.id, force=True, settings=settings)

    result = handle_item_tag_recommendation(
        db,
        first_job,
        {"item_id": item.id, "generation_token": 1},
        settings=settings,
    )

    current = db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item.id)
    )
    assert result == {"stale": True}
    assert current.generation_token == 2
    assert current.single_words is None


def test_concurrent_force_requests_receive_distinct_generation_tokens(db):
    user = User(username="concurrent-recommend-owner", password_hash="hash")
    db.add(user)
    db.flush()
    item = Item(title="Concurrent recommendation requests", created_by=user.id)
    db.add(item)
    db.flush()
    settings = Settings(_env_file=None, recommendation_engine="yake")
    request_item_tag_recommendation(db, item.id, owner_id=user.id, settings=settings)
    db.commit()
    original_updated_at = item.updated_at

    factory = sessionmaker(db.bind, class_=Session, expire_on_commit=False)
    start = Barrier(2)

    def force_request() -> tuple[int, str]:
        with factory() as worker_db:
            start.wait()
            worker_user = worker_db.get(User, user.id)
            assert worker_user is not None
            record = force_item_tag_recommendation(
                worker_db,
                worker_user,
                item.id,
                settings=settings,
            )
            assert record.job_id is not None
            return record.generation_token, record.job_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: force_request(), range(2)))

    assert {token for token, _job_id in results} == {2, 3}
    assert len({job_id for _token, job_id in results}) == 2
    db.refresh(item)
    assert item.updated_at.replace(tzinfo=original_updated_at.tzinfo) == original_updated_at


def test_missing_keybert_configuration_fails_explicitly(db):
    user = User(username="keybert-owner", password_hash="hash")
    db.add(user)
    db.flush()
    item = Item(title="Local semantic extraction", created_by=user.id)
    db.add(item)
    db.flush()
    settings = Settings(
        _env_file=None,
        recommendation_engine="keybert",
        keybert_model_path=None,
    )
    record = request_item_tag_recommendation(db, item.id, owner_id=user.id, settings=settings)
    job = db.get(Job, record.job_id)
    job.state = JobState.running

    with pytest.raises(RuntimeError, match="KEYBERT_MODEL_PATH"):
        handle_item_tag_recommendation(
            db,
            job,
            {"item_id": item.id, "generation_token": record.generation_token},
            settings=settings,
        )
