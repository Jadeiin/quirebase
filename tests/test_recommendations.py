from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from quirebase.core.config import Settings
from quirebase.library.item_metadata import ItemMetadata, create_item
from quirebase.models import Item, ItemTagRecommendation, Job, JobState, User
from quirebase.pipeline.jobs import run_job
from quirebase.recommendations.engine import (
    KeyBertRecommendationEngine,
    RecommendationDocument,
    RecommendationLimits,
    YakeRecommendationEngine,
)
from quirebase.recommendations.persistence import (
    force_item_tag_recommendation,
    handle_item_tag_recommendation,
    request_item_tag_recommendation,
)
from quirebase.recommendations.prompt import build_recommendation_prompt


class FakeYakeExtractor:
    def __init__(self, **options):
        self.options = options

    def extract_keywords(self, text: str):
        if self.options["n"] == 1:
            return [
                ("Abstract", 0.01),
                ("Nanotube", 0.7),
                ("Zeolite", 0.1),
                ("zeolite", 0.2),
                ("two words", 0.05),
            ]
        return [
            ("IEEE transactions", 0.01),
            ("supplementary material", 0.02),
            ("one", 0.01),
            ("Ranked phrase", 0.2),
            ("Quantum lattice", 0.1),
            ("Neural graph encoder", 0.08),
            ("five word phrases are not valid", 0.05),
        ]


def test_yake_adapter_sorts_low_scores_and_separates_candidate_groups():
    engine = YakeRecommendationEngine(FakeYakeExtractor)

    result = engine.recommend(
        (RecommendationDocument("first", "text"), RecommendationDocument("second", "other")),
        RecommendationLimits(),
    )

    assert len(result) == 2
    assert result[0].single_words == ("Zeolite", "Nanotube")
    assert result[0].phrases == ("Neural graph encoder", "Quantum lattice", "Ranked phrase")
    assert result[1] == result[0]


def test_yake_adapter_excludes_standard_stopwords_inside_phrases():
    text = (
        "The graph method is compared to the baseline. A graph method and a baseline method "
        "are evaluated. Graph learning or the baseline approach improves prediction."
    )
    result = YakeRecommendationEngine().recommend(
        (RecommendationDocument("stopword-repro", text),), RecommendationLimits()
    )[0]
    stopwords = {"a", "an", "and", "or", "the", "to"}

    assert not [phrase for phrase in result.phrases if set(phrase.casefold().split()) & stopwords]


class FakeKeyBert:
    def __init__(self):
        self.calls = []

    def extract_keywords(self, documents, **options):
        self.calls.append((documents, options))
        if options["keyphrase_ngram_range"] == (1, 1):
            return [[("abstract", 0.99), ("alpha", 0.9)], [("ieee", 0.9), ("beta", 0.8)]]
        return [
            [("supplementary material", 0.9), ("alpha method", 0.7)],
            [("ieee transactions", 0.8), ("beta model", 0.6)],
        ]


def test_keybert_adapter_uses_one_batch_per_group_and_mmr():
    backend = FakeKeyBert()
    engine = KeyBertRecommendationEngine(backend)
    documents = (
        RecommendationDocument("a", "first text"),
        RecommendationDocument("b", "second text"),
    )

    results = engine.recommend(documents, RecommendationLimits())

    assert [result.single_words for result in results] == [("alpha",), ("beta",)]
    assert [result.phrases for result in results] == [("alpha method",), ("beta model",)]
    assert len(backend.calls) == 2
    assert [call[1]["keyphrase_ngram_range"] for call in backend.calls] == [
        (1, 1),
        (2, 4),
    ]
    for texts, options in backend.calls:
        assert texts == ["first text", "second text"]
        assert options["top_n"] == 10
        assert options["use_mmr"] is True
        assert options["diversity"] == pytest.approx(0.5)
        assert {"abstract", "supplementary", "ieee"} <= set(options["stop_words"])


def test_prompt_builder_keeps_fixed_json_contract():
    prompt = build_recommendation_prompt(
        (RecommendationDocument("item", "body"),), RecommendationLimits()
    )
    assert json.loads(prompt.as_json())["output_contract"] == {
        "single_words": [],
        "phrases": [],
    }


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
    monkeypatch.setattr("quirebase.recommendations.persistence.get_settings", lambda: settings)

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
