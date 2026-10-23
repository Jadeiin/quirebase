"""Recommendation Engine interface and local extraction adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


@dataclass(frozen=True)
class RecommendationDocument:
    identifier: str
    text: str


@dataclass(frozen=True)
class RecommendationLimits:
    single_words: int = 10
    phrases: int = 10


@dataclass(frozen=True)
class RecommendationResult:
    single_words: tuple[str, ...]
    phrases: tuple[str, ...]


class RecommendationEngine(Protocol):
    def recommend(
        self,
        documents: Sequence[RecommendationDocument],
        limits: RecommendationLimits,
    ) -> tuple[RecommendationResult, ...]: ...


_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9+'-]*[A-Za-z0-9])?")
_DOMAIN_STOPWORDS = frozenset({
    "abstract",
    "acm",
    "appendices",
    "appendix",
    "article",
    "bibliography",
    "copyright",
    "doi",
    "elsevier",
    "fig",
    "figure",
    "figures",
    "ieee",
    "issue",
    "journal",
    "page",
    "pages",
    "proceedings",
    "publication",
    "publisher",
    "references",
    "section",
    "sections",
    "springer",
    "supplement",
    "supplemental",
    "supplementary",
    "supplements",
    "table",
    "tables",
    "transactions",
    "volume",
    "wiley",
})


@lru_cache(maxsize=1)
def _english_stopwords() -> frozenset[str]:
    from yake import KeywordExtractor

    extractor = KeywordExtractor(lan="en", n=1, top=1)
    return frozenset(extractor.stopword_set) | _DOMAIN_STOPWORDS


def _keybert_stopwords() -> tuple[str, ...]:
    return tuple(sorted(_english_stopwords()))


def _extend_yake_stopwords(extractor: Any) -> Any:
    stopwords = getattr(extractor, "stopword_set", None)
    if isinstance(stopwords, set):
        stopwords.update(_english_stopwords())
    return extractor


def _normalize_candidates(
    candidates: Sequence[tuple[str, float]], *, minimum_words: int, maximum_words: int, limit: int
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw, _score in candidates:
        candidate = " ".join(_TOKEN.findall(raw))
        words = candidate.split()
        folded = candidate.casefold()
        folded_words = {word.casefold() for word in words}
        if (
            not minimum_words <= len(words) <= maximum_words
            or not candidate
            or len(candidate) > 120
        ):
            continue
        if folded_words & _english_stopwords():
            continue
        if folded in seen:
            continue
        seen.add(folded)
        result.append(candidate)
        if len(result) == limit:
            break
    return tuple(result)


class YakeRecommendationEngine:
    """Run YAKE independently for each document; lower YAKE scores rank first."""

    def __init__(self, extractor_factory: Callable[..., Any] | None = None) -> None:
        if extractor_factory is None:
            from yake import KeywordExtractor

            extractor_factory = KeywordExtractor
        self._extractor_factory = extractor_factory

    def recommend(
        self,
        documents: Sequence[RecommendationDocument],
        limits: RecommendationLimits,
    ) -> tuple[RecommendationResult, ...]:
        results: list[RecommendationResult] = []
        for document in documents:
            words_extractor = _extend_yake_stopwords(
                self._extractor_factory(lan="en", n=1, top=limits.single_words, dedupLim=0.9)
            )
            phrases_extractor = _extend_yake_stopwords(
                self._extractor_factory(
                    lan="en",
                    n=4,
                    top=max(limits.phrases * 5, limits.phrases),
                    dedupLim=0.9,
                )
            )
            word_rows = sorted(
                words_extractor.extract_keywords(document.text), key=lambda row: row[1]
            )
            phrase_rows = sorted(
                phrases_extractor.extract_keywords(document.text), key=lambda row: row[1]
            )
            results.append(
                RecommendationResult(
                    single_words=_normalize_candidates(
                        word_rows,
                        minimum_words=1,
                        maximum_words=1,
                        limit=limits.single_words,
                    ),
                    phrases=_normalize_candidates(
                        phrase_rows,
                        minimum_words=2,
                        maximum_words=4,
                        limit=limits.phrases,
                    ),
                )
            )
        return tuple(results)


class KeyBertRecommendationEngine:
    """Batch extraction using a caller-provided, already-local KeyBERT backend."""

    def __init__(
        self,
        backend: Any,
        *,
        diversity: float = 0.5,
        shared_options: Mapping[str, Any] | None = None,
    ) -> None:
        self._backend = backend
        self._diversity = diversity
        self._shared_options = dict(shared_options or {})
        fixed = {
            "keyphrase_ngram_range",
            "top_n",
            "use_mmr",
            "diversity",
        }
        if fixed & self._shared_options.keys():
            raise ValueError("shared KeyBERT options cannot override ranking contract")

    def _extract(
        self, texts: list[str], ngram_range: tuple[int, int], top_n: int
    ) -> list[list[tuple[str, float]]]:
        rows = self._backend.extract_keywords(
            texts,
            keyphrase_ngram_range=ngram_range,
            stop_words=_keybert_stopwords(),
            top_n=top_n,
            use_mmr=True,
            diversity=self._diversity,
            **self._shared_options,
        )
        if texts and rows and isinstance(rows[0], tuple):
            return [rows]
        return rows

    def recommend(
        self,
        documents: Sequence[RecommendationDocument],
        limits: RecommendationLimits,
    ) -> tuple[RecommendationResult, ...]:
        if not documents:
            return ()
        texts = [document.text for document in documents]
        words = self._extract(texts, (1, 1), limits.single_words)
        phrases = self._extract(texts, (2, 4), limits.phrases)
        return tuple(
            RecommendationResult(
                single_words=_normalize_candidates(
                    word_rows,
                    minimum_words=1,
                    maximum_words=1,
                    limit=limits.single_words,
                ),
                phrases=_normalize_candidates(
                    phrase_rows,
                    minimum_words=2,
                    maximum_words=4,
                    limit=limits.phrases,
                ),
            )
            for word_rows, phrase_rows in zip(words, phrases, strict=True)
        )


@lru_cache(maxsize=4)
def load_local_keybert(model_path: str) -> KeyBertRecommendationEngine:
    path = Path(model_path).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError(f"KeyBERT model directory does not exist: {path}")
    from keybert import KeyBERT
    from model2vec import StaticModel

    model = StaticModel.from_pretrained(str(path))
    return KeyBertRecommendationEngine(KeyBERT(model=model))
