"""Own generation requests, Item text assembly, and recommendation persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from quirebase.access.items import require_editable_item
from quirebase.core.config import Settings, get_settings
from quirebase.models import (
    FileRevision,
    FileRevisionProcessingState,
    Item,
    ItemTagRecommendation,
    Job,
    JobState,
    User,
)
from quirebase.recommendations.engine import (
    RecommendationDocument,
    RecommendationLimits,
    YakeRecommendationEngine,
    load_local_keybert,
)
from quirebase.recommendations.processing import (
    clean_recommendation_text,
    describe_engine,
    input_fingerprint,
    validate_engine_configuration,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _item_text(db: Session, item: Item, settings: Settings) -> str:
    full_text = db.scalar(
        select(FileRevision.full_text)
        .where(
            FileRevision.item_id == item.id,
            FileRevision.processing_state == FileRevisionProcessingState.ready,
        )
        .order_by(FileRevision.created_at.desc())
        .limit(1)
    )
    return clean_recommendation_text(
        item.title,
        item.abstract,
        full_text,
        settings.recommendation_max_chars,
    )


def _linked_job(db: Session, record: ItemTagRecommendation) -> Job | None:
    return db.get(Job, record.job_id) if record.job_id else None


def request_item_tag_recommendation(
    db: Session,
    item_id: str,
    *,
    owner_id: str | None = None,
    force: bool = False,
    settings: Settings | None = None,
) -> ItemTagRecommendation:
    """Create an idempotent generation request without committing its caller's transaction."""
    effective = settings or get_settings()
    if force:
        # Make locking the first database operation in this request. PostgreSQL
        # provides a row lock; SQLite needs a no-op write to reserve its writer
        # slot. Explicitly preserving updated_at prevents this coordination from
        # appearing as an Item metadata edit.
        if db.get_bind().dialect.name == "sqlite":
            locked_item_id = db.scalar(
                update(Item)
                .where(Item.id == item_id)
                .values(updated_at=Item.updated_at)
                .returning(Item.id)
            )
        else:
            locked_item_id = db.scalar(select(Item.id).where(Item.id == item_id).with_for_update())
        if locked_item_id is None:
            raise ValueError("Item no longer exists")
    item = db.get(Item, item_id)
    if item is None:
        raise ValueError("Item no longer exists")
    descriptor = describe_engine(effective)
    fingerprint = input_fingerprint(
        _item_text(db, item, effective),
        descriptor,
        max_chars=effective.recommendation_max_chars,
    )
    record = db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
    )
    if record is not None and record.input_fingerprint == fingerprint and not force:
        job = _linked_job(db, record)
        if record.generated_at is not None or (
            job is not None
            and job.state in {JobState.pending, JobState.running, JobState.succeeded}
        ):
            return record

    token = (record.generation_token + 1) if record else 1
    if record is None:
        record = ItemTagRecommendation(
            item_id=item_id,
            input_fingerprint=fingerprint,
            generation_token=token,
            engine=descriptor.name,
            engine_version=descriptor.version,
            model_fingerprint=descriptor.model_fingerprint,
        )
        db.add(record)
    else:
        record.input_fingerprint = fingerprint
        record.generation_token = token
        record.engine = descriptor.name
        record.engine_version = descriptor.version
        record.model_fingerprint = descriptor.model_fingerprint
        record.single_words = None
        record.phrases = None
        record.generated_at = None
    job = Job(
        kind="item.recommend_tags",
        payload=json.dumps({"item_id": item_id, "generation_token": token}),
        idempotency_key=f"item.recommend_tags:{item_id}:{token}:{fingerprint}",
        owner_id=owner_id,
    )
    db.add(job)
    db.flush()
    record.job_id = job.id
    db.flush()
    return record


def force_item_tag_recommendation(
    db: Session,
    user: User,
    item_id: str,
    *,
    settings: Settings | None = None,
) -> ItemTagRecommendation:
    require_editable_item(db, user, item_id)
    try:
        record = request_item_tag_recommendation(
            db, item_id, owner_id=user.id, force=True, settings=settings
        )
        db.commit()
        return record
    except Exception:
        db.rollback()
        raise


def _engine(settings: Settings):
    validate_engine_configuration(settings)
    name = settings.recommendation_engine.strip().casefold()
    if name == "yake":
        return YakeRecommendationEngine()
    if name == "keybert":
        if settings.keybert_model_path is None:
            raise RuntimeError("QUIREBASE_KEYBERT_MODEL_PATH is required for the keybert engine")
        return load_local_keybert(str(settings.keybert_model_path))
    raise RuntimeError(f"unsupported recommendation engine: {settings.recommendation_engine}")


def handle_item_tag_recommendation(
    db: Session,
    job: Job,
    payload: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    effective = settings or get_settings()
    item_id = str(payload["item_id"])
    token = int(payload["generation_token"])
    record = db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
    )
    if record is None or record.generation_token != token or record.job_id != job.id:
        return {"stale": True}
    item = db.get(Item, item_id)
    if item is None:
        raise ValueError("Item no longer exists")
    text = _item_text(db, item, effective)
    descriptor = describe_engine(effective)
    fingerprint = input_fingerprint(text, descriptor, max_chars=effective.recommendation_max_chars)
    if fingerprint != record.input_fingerprint:
        request_item_tag_recommendation(db, item_id, owner_id=job.owner_id, settings=effective)
        return {"stale": True, "replacement_enqueued": True}
    result = _engine(effective).recommend(
        (RecommendationDocument(identifier=item_id, text=text),),
        RecommendationLimits(single_words=10, phrases=10),
    )[0]
    # Re-check the optimistic generation token immediately before persistence.
    db.refresh(record)
    if record.generation_token != token or record.job_id != job.id:
        return {"stale": True}
    record.single_words = json.dumps(result.single_words, ensure_ascii=False)
    record.phrases = json.dumps(result.phrases, ensure_ascii=False)
    record.generated_at = datetime.now(UTC)
    return {
        "single_words": len(result.single_words),
        "phrases": len(result.phrases),
    }


def recommendation_state(db: Session, record: ItemTagRecommendation | None) -> str:
    if record is None:
        return "empty"
    if record.generated_at is not None:
        return "ready"
    job = _linked_job(db, record)
    if job is None:
        return "failed"
    if job.state == JobState.failed:
        return "failed"
    return "pending"


def decoded_candidates(
    record: ItemTagRecommendation | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if record is None or record.generated_at is None:
        return (), ()
    try:
        words = tuple(str(value) for value in json.loads(record.single_words or "[]"))
        phrases = tuple(str(value) for value in json.loads(record.phrases or "[]"))
    except (TypeError, json.JSONDecodeError):
        return (), ()
    return words, phrases


def enqueue_all_item_tag_recommendations(
    db: Session,
    *,
    owner_id: str | None = None,
    settings: Settings | None = None,
) -> int:
    item_ids = tuple(db.scalars(select(Item.id).order_by(Item.id)).all())
    for item_id in item_ids:
        request_item_tag_recommendation(
            db, item_id, owner_id=owner_id, force=True, settings=settings
        )
    return len(item_ids)
