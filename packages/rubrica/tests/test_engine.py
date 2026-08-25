import json

import pytest
from rubrica import (
    KeyBertRecommendationEngine,
    RecommendationDocument,
    RecommendationLimits,
    YakeRecommendationEngine,
    build_recommendation_prompt,
)


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
