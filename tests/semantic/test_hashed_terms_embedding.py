"""HashedTermEmbedding: deterministic, normalised, and lexically meaningful."""
from __future__ import annotations

import math

from app.embeddings.factory import create_embedding_provider
from app.embeddings.hashed_terms import HashedTermEmbedding


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_deterministic_and_unit_length():
    e = HashedTermEmbedding()
    v1, v2 = e.embed_text("Servo fault on Robot R-17"), e.embed_text("Servo fault on Robot R-17")
    assert v1 == v2
    assert len(v1) == 128
    assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0, rel_tol=1e-9)


def test_shared_vocabulary_ranks_higher():
    e = HashedTermEmbedding()
    q = e.embed_text("servo fault robot")
    related = e.embed_text("Repeated servo fault on Robot R-17 during panel transfer")
    unrelated = e.embed_text("Accumulator pre-charge specification for hydraulic press")
    assert _cos(q, related) > _cos(q, unrelated) + 0.2


def test_empty_text_is_stable_nonzero():
    v = HashedTermEmbedding().embed_text("")
    assert any(v)


def test_factory_selects_provider():
    assert isinstance(create_embedding_provider("hashed_terms"), HashedTermEmbedding)
    assert create_embedding_provider("fake").__class__.__name__ == "DeterministicFakeEmbedding"
