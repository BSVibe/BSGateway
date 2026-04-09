"""Tests for vector serialization and intent definition hydration."""

from __future__ import annotations

from bsgateway.embedding.serialization import (
    deserialize_embedding,
    hydrate_intent_definitions,
    serialize_embedding,
)


class TestSerialization:
    def test_roundtrip(self):
        vec = [0.1, 0.2, 0.3, -0.5, 1.0]
        result = deserialize_embedding(serialize_embedding(vec))
        assert len(result) == len(vec)
        for a, b in zip(vec, result, strict=True):
            assert abs(a - b) < 1e-6

    def test_empty_vector(self):
        assert deserialize_embedding(serialize_embedding([])) == []

    def test_byte_length(self):
        # 3 floats * 4 bytes each = 12 bytes
        assert len(serialize_embedding([1.0, 2.0, 3.0])) == 12


class TestHydration:
    def test_pairs_examples_with_matching_model(self):
        emb1 = serialize_embedding([0.1, 0.2])
        emb2 = serialize_embedding([0.3, 0.4])
        rows = [
            {
                "intent_name": "greeting",
                "embedding": emb1,
                "embedding_model": "text-embedding-3-small",
                "threshold": 0.7,
            },
            {
                "intent_name": "greeting",
                "embedding": emb2,
                "embedding_model": "text-embedding-3-small",
                "threshold": 0.7,
            },
        ]
        result = hydrate_intent_definitions(rows, active_model="text-embedding-3-small")
        assert len(result) == 1
        assert result[0].name == "greeting"
        assert len(result[0].example_embeddings) == 2

    def test_skips_stale_embeddings_from_different_model(self):
        emb_current = serialize_embedding([0.1, 0.2])
        emb_stale = serialize_embedding([0.5, 0.6, 0.7])  # different dimensions, different model
        rows = [
            {
                "intent_name": "topic",
                "embedding": emb_current,
                "embedding_model": "text-embedding-3-small",
                "threshold": 0.7,
            },
            {
                "intent_name": "topic",
                "embedding": emb_stale,
                "embedding_model": "ollama/nomic-embed-text",
                "threshold": 0.7,
            },
        ]
        result = hydrate_intent_definitions(rows, active_model="text-embedding-3-small")
        assert len(result) == 1
        assert len(result[0].example_embeddings) == 1
        # Mixed dimensions would crash cosine_similarity — proves we filtered cleanly
        assert len(result[0].example_embeddings[0]) == 2

    def test_excludes_intents_with_only_stale_embeddings(self):
        emb_stale = serialize_embedding([0.5, 0.6])
        rows = [
            {
                "intent_name": "abandoned",
                "embedding": emb_stale,
                "embedding_model": "old-model",
                "threshold": 0.7,
            },
        ]
        result = hydrate_intent_definitions(rows, active_model="new-model")
        assert result == []

    def test_skips_null_embeddings(self):
        emb = serialize_embedding([0.5, 0.6])
        rows = [
            {
                "intent_name": "topic",
                "embedding": emb,
                "embedding_model": "current-model",
                "threshold": 0.7,
            },
            {
                "intent_name": "topic",
                "embedding": None,
                "embedding_model": None,
                "threshold": 0.7,
            },
        ]
        result = hydrate_intent_definitions(rows, active_model="current-model")
        assert len(result) == 1
        assert len(result[0].example_embeddings) == 1

    def test_returns_empty_when_no_active_model(self):
        emb = serialize_embedding([0.1, 0.2])
        rows = [
            {
                "intent_name": "topic",
                "embedding": emb,
                "embedding_model": "any",
                "threshold": 0.7,
            },
        ]
        assert hydrate_intent_definitions(rows, active_model=None) == []
        assert hydrate_intent_definitions(rows, active_model="") == []

    def test_empty_rows(self):
        assert hydrate_intent_definitions([], active_model="any") == []

    def test_groups_multiple_intents(self):
        emb = serialize_embedding([0.1, 0.2])
        rows = [
            {
                "intent_name": "a",
                "embedding": emb,
                "embedding_model": "m",
                "threshold": 0.7,
            },
            {
                "intent_name": "b",
                "embedding": emb,
                "embedding_model": "m",
                "threshold": 0.7,
            },
        ]
        result = hydrate_intent_definitions(rows, active_model="m")
        names = sorted(d.name for d in result)
        assert names == ["a", "b"]
