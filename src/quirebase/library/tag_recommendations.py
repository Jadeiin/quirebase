"""Assemble Item text and compute Item Tag Recommendations."""

from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import json
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from inquiro.richtext import convert_rich_text
from rubrica import (
    RecommendationDocument,
    RecommendationLimits,
    YakeRecommendationEngine,
    load_local_keybert,
)
from sqlalchemy import select

from quirebase.core.config import Settings, get_settings
from quirebase.models import (
    FileRevision,
    FileRevisionProcessingState,
    Item,
    ItemTagRecommendation,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_DOI = re.compile(r"\b(?:doi\s*:\s*)?10\.\d{4,9}/\S+", re.IGNORECASE)
_REFERENCES = re.compile(r"(?im)^\s*(?:references|bibliography)\s*$")
_LAYOUT_LINE = re.compile(r"(?im)^\s*(?:page\s+)?\d+\s*(?:of\s+\d+)?\s*$")


@dataclass(frozen=True)
class EngineDescriptor:
    name: str
    version: str


class RecommendationCandidates(TypedDict):
    single_words: list[str]
    phrases: list[str]


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


def describe_engine(settings: Settings) -> EngineDescriptor:
    engine = settings.recommendation_engine.strip().casefold()
    if engine == "yake":
        return EngineDescriptor("yake", _package_version("yake"))
    if engine == "keybert":
        return EngineDescriptor("keybert", _package_version("keybert"))
    return EngineDescriptor(engine, "unsupported")


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


async def recommend_item_tags(
    db: AsyncSession,
    item_id: str,
    *,
    settings: Settings | None = None,
) -> RecommendationCandidates:
    effective = settings or get_settings()
    item = await db.get(Item, item_id)
    if item is None:
        raise ValueError("Item no longer exists")
    text = await _item_text(db, item, effective)
    result = await asyncio.to_thread(
        lambda: _engine(effective).recommend(
            (RecommendationDocument(identifier=item_id, text=text),),
            RecommendationLimits(single_words=10, phrases=10),
        )
    )
    recommendation = result[0]
    return {
        "single_words": list(recommendation.single_words),
        "phrases": list(recommendation.phrases),
    }


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


__all__ = [
    "EngineDescriptor",
    "clean_recommendation_text",
    "decoded_candidates",
    "describe_engine",
    "recommend_item_tags",
    "validate_engine_configuration",
]
