"""Own generation requests, Item text assembly, and tag recommendation persistence."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from inquiro.richtext import convert_rich_text
from rubrica import (
    RecommendationDocument,
    RecommendationLimits,
    YakeRecommendationEngine,
    load_local_keybert,
)
from sqlalchemy import select, update

from quirebase.access.items import require_editable_item
from quirebase.core.config import Settings, get_settings
from quirebase.core.workflows import LIBRARY_QUEUE, durable_operations
from quirebase.models import (
    FileRevision,
    FileRevisionProcessingState,
    Item,
    ItemTagRecommendation,
    User,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_DOI = re.compile(r"\b(?:doi\s*:\s*)?10\.\d{4,9}/\S+", re.IGNORECASE)
_REFERENCES = re.compile(r"(?im)^\s*(?:references|bibliography)\s*$")
_LAYOUT_LINE = re.compile(r"(?im)^\s*(?:page\s+)?\d+\s*(?:of\s+\d+)?\s*$")


@dataclass(frozen=True)
class EngineDescriptor:
    name: str
    version: str
    model_fingerprint: str | None


def clean_recommendation_text(
    title: str, abstract: str | None, full_text: str | None, limit: int
) -> str:
    body = full_text or ""
    reference = _REFERENCES.search(body)
    if reference:
        body = body[: reference.start()]
    text = "\n\n".join(value for value in (title.strip(), (abstract or "").strip(), body) if value)
    text = _URL.sub(" ", text)
    text = _DOI.sub(" ", text)
    text = _LAYOUT_LINE.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit].strip()


def _package_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


@lru_cache(maxsize=8)
def _fingerprint_model_directory(resolved_path: str) -> str:
    from pathlib import Path

    resolved = Path(resolved_path)
    if not resolved.is_dir():
        return f"missing:{resolved}"
    digest = hashlib.sha256()
    files = sorted(candidate for candidate in resolved.rglob("*") if candidate.is_file())
    for candidate in files:
        digest.update(candidate.relative_to(resolved).as_posix().encode())
        with candidate.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def fingerprint_model_directory(path: Path) -> str:
    return _fingerprint_model_directory(str(path.expanduser().resolve()))


def describe_engine(settings: Settings) -> EngineDescriptor:
    engine = settings.recommendation_engine.strip().casefold()
    if engine == "yake":
        return EngineDescriptor("yake", _package_version("yake"), None)
    if engine == "keybert":
        model = settings.keybert_model_path
        return EngineDescriptor(
            "keybert",
            _package_version("keybert"),
            fingerprint_model_directory(model) if model else "missing:unconfigured",
        )
    return EngineDescriptor(engine, "unsupported", None)


def input_fingerprint(text: str, descriptor: EngineDescriptor, *, max_chars: int = 200_000) -> str:
    digest = hashlib.sha256()
    for value in (
        "tag-recommendation-v1",
        descriptor.name,
        descriptor.version,
        descriptor.model_fingerprint or "",
        (
            "single=1;phrases=2-4;top=10;mmr=0.5;yake-dedup=0.9;"
            f"stopwords=v2;language=en;max={max_chars}"
        ),
        text,
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def validate_engine_configuration(settings: Settings) -> EngineDescriptor:
    descriptor = describe_engine(settings)
    if descriptor.name not in {"yake", "keybert"}:
        raise RuntimeError(f"unsupported recommendation engine: {settings.recommendation_engine}")
    if descriptor.name == "yake":
        if importlib.util.find_spec("yake") is None:
            raise RuntimeError("YAKE is not installed")
        return descriptor
    path = settings.keybert_model_path
    if path is None:
        raise RuntimeError("QUIREBASE_KEYBERT_MODEL_PATH is required for the keybert engine")
    resolved = path.expanduser().resolve()
    if not resolved.is_dir() or not os.access(resolved, os.R_OK):
        raise RuntimeError(f"KeyBERT model directory is not readable: {resolved}")
    missing = [name for name in ("keybert", "model2vec") if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(
            "KeyBERT optional dependencies are missing; install quirebase[keybert]: "
            + ", ".join(missing)
        )
    expected = (settings.keybert_model_sha256 or "").strip().casefold()
    if expected and descriptor.model_fingerprint != expected:
        raise RuntimeError("KeyBERT model checksum does not match QUIREBASE_KEYBERT_MODEL_SHA256")
    return descriptor


async def _item_text(db: AsyncSession, item: Item, settings: Settings) -> str:
    full_text = await db.scalar(
        select(FileRevision.full_text)
        .where(
            FileRevision.item_id == item.id,
            FileRevision.processing_state == FileRevisionProcessingState.ready,
        )
        .order_by(FileRevision.created_at.desc())
        .limit(1)
    )
    return clean_recommendation_text(
        convert_rich_text(item.title, source="html", target="text"),
        convert_rich_text(item.abstract, source="html", target="text"),
        full_text,
        settings.recommendation_max_chars,
    )


async def _linked_workflow(record: ItemTagRecommendation):
    return await durable_operations().get(record.workflow_id) if record.workflow_id else None


async def request_item_tag_recommendation(
    db: AsyncSession,
    item_id: str,
    *,
    owner_id: str | None = None,
    force: bool = False,
    settings: Settings | None = None,
) -> ItemTagRecommendation:
    """Create an idempotent generation request without committing its caller's transaction."""
    effective = settings or get_settings()
    if force:
        if db.get_bind().dialect.name == "sqlite":
            locked_item_id = await db.scalar(
                update(Item)
                .where(Item.id == item_id)
                .values(updated_at=Item.updated_at)
                .returning(Item.id)
            )
        else:
            locked_item_id = await db.scalar(
                select(Item.id).where(Item.id == item_id).with_for_update()
            )
        if locked_item_id is None:
            raise ValueError("Item no longer exists")
    item = await db.get(Item, item_id)
    if item is None:
        raise ValueError("Item no longer exists")
    descriptor = await asyncio.to_thread(describe_engine, effective)
    fingerprint = input_fingerprint(
        await _item_text(db, item, effective),
        descriptor,
        max_chars=effective.recommendation_max_chars,
    )
    record = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
    )
    if record is not None and record.input_fingerprint == fingerprint and not force:
        workflow = await _linked_workflow(record)
        if record.generated_at is not None or (
            workflow is not None
            and workflow.state in {"pending", "running", "succeeded"}
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
    workflow_id = f"item-recommend-tags:{item_id}:{token}:{fingerprint}"
    await db.flush()
    await durable_operations().enqueue_in_transaction(
        db,
        "library.recommend_tags",
        item_id,
        token,
        workflow_id,
        owner_id,
        queue_name=LIBRARY_QUEUE,
        workflow_id=workflow_id,
        attributes={"capability": "library", "owner_id": owner_id, "item_id": item_id},
    )
    record.workflow_id = workflow_id
    await db.flush()
    return record


async def force_item_tag_recommendation(
    db: AsyncSession,
    user: User,
    item_id: str,
    *,
    settings: Settings | None = None,
) -> ItemTagRecommendation:
    await require_editable_item(db, user, item_id)
    try:
        record = await request_item_tag_recommendation(
            db, item_id, owner_id=user.id, force=True, settings=settings
        )
        await db.commit()
        return record
    except Exception:
        await db.rollback()
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


async def handle_item_tag_recommendation(
    db: AsyncSession,
    item_id: str,
    generation_token: int,
    workflow_id: str,
    owner_id: str | None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    effective = settings or get_settings()
    token = generation_token
    record = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
    )
    if record is None or record.generation_token != token or record.workflow_id != workflow_id:
        return {"stale": True}
    item = await db.get(Item, item_id)
    if item is None:
        raise ValueError("Item no longer exists")
    text = await _item_text(db, item, effective)
    descriptor = await asyncio.to_thread(describe_engine, effective)
    fingerprint = input_fingerprint(text, descriptor, max_chars=effective.recommendation_max_chars)
    if fingerprint != record.input_fingerprint:
        await request_item_tag_recommendation(
            db, item_id, owner_id=owner_id, settings=effective
        )
        return {"stale": True, "replacement_enqueued": True}
    result = (
        await asyncio.to_thread(
            lambda: _engine(effective).recommend(
                (RecommendationDocument(identifier=item_id, text=text),),
                RecommendationLimits(single_words=10, phrases=10),
            )
        )
    )[0]
    await db.refresh(record)
    if record.generation_token != token or record.workflow_id != workflow_id:
        return {"stale": True}
    record.single_words = json.dumps(result.single_words, ensure_ascii=False)
    record.phrases = json.dumps(result.phrases, ensure_ascii=False)
    record.generated_at = datetime.now(UTC)
    return {
        "single_words": len(result.single_words),
        "phrases": len(result.phrases),
    }


async def recommendation_state(db: AsyncSession, record: ItemTagRecommendation | None) -> str:
    if record is None:
        return "empty"
    if record.generated_at is not None:
        return "ready"
    workflow = await _linked_workflow(record)
    if workflow is None:
        return "failed"
    if workflow.state in {"failed", "cancelled"}:
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


async def enqueue_all_item_tag_recommendations(
    db: AsyncSession,
    *,
    owner_id: str | None = None,
    settings: Settings | None = None,
) -> int:
    item_ids = tuple((await db.scalars(select(Item.id).order_by(Item.id))).all())
    for item_id in item_ids:
        await request_item_tag_recommendation(
            db, item_id, owner_id=owner_id, force=True, settings=settings
        )
    return len(item_ids)


__all__ = [
    "EngineDescriptor",
    "clean_recommendation_text",
    "decoded_candidates",
    "describe_engine",
    "enqueue_all_item_tag_recommendations",
    "fingerprint_model_directory",
    "force_item_tag_recommendation",
    "handle_item_tag_recommendation",
    "input_fingerprint",
    "recommendation_state",
    "request_item_tag_recommendation",
    "validate_engine_configuration",
]
