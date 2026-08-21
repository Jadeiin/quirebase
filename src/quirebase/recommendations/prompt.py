"""Typed prompt input reserved for a future LLM Recommendation Engine adapter."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quirebase.recommendations.engine import RecommendationDocument, RecommendationLimits


@dataclass(frozen=True)
class RecommendationPrompt:
    instruction: str
    documents: tuple[RecommendationDocument, ...]
    limits: RecommendationLimits
    output_contract: dict[str, list[str]]

    def as_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def build_recommendation_prompt(
    documents: tuple[RecommendationDocument, ...], limits: RecommendationLimits
) -> RecommendationPrompt:
    return RecommendationPrompt(
        instruction="Return English Tag candidates, ranked independently within each group.",
        documents=documents,
        limits=limits,
        output_contract={"single_words": [], "phrases": []},
    )
