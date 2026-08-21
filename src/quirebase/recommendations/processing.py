"""Text assembly and reproducible configuration fingerprints."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from quirebase.core.config import Settings

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
