from importlib.util import find_spec

import pytest
from excerpo import RecommendationDocument, RecommendationLimits, load_local_keybert


def test_local_model_extracts_keywords_and_phrases_in_a_batch(tmp_path, monkeypatch):
    if find_spec("keybert") is None or find_spec("model2vec") is None:
        pytest.skip("Install the keybert extra to run the local model contract")

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    import numpy as np
    from model2vec import StaticModel
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    vocabulary = ["[UNK]", "graph", "neural", "networks", "quantum", "lattice", "materials"]
    tokenizer = Tokenizer(
        WordLevel(dict(zip(vocabulary, range(len(vocabulary)))), unk_token="[UNK]")
    )
    tokenizer.pre_tokenizer = Whitespace()
    model = StaticModel(
        vectors=np.array(
            [
                [0, 0, 0],
                [1, 0, 0],
                [0.9, 0.1, 0],
                [0.8, 0.2, 0],
                [0, 0, 1],
                [0, 0.1, 0.9],
                [0, 0.2, 0.8],
            ],
            dtype=np.float32,
        ),
        tokenizer=tokenizer,
    )
    model_path = tmp_path / "model"
    model.save_pretrained(model_path)

    documents = (
        RecommendationDocument("graph", "graph neural networks"),
        RecommendationDocument("quantum", "quantum lattice materials"),
    )
    results = load_local_keybert(str(model_path)).recommend(
        documents, RecommendationLimits(single_words=2, phrases=2)
    )

    assert len(results) == len(documents)
    for document, result in zip(documents, results, strict=True):
        assert len(result.single_words) == 2
        assert set(result.single_words) <= set(document.text.split())
        assert len(result.phrases) == 2
        assert all(2 <= len(phrase.split()) <= 4 for phrase in result.phrases)
        assert all(phrase in document.text for phrase in result.phrases)
