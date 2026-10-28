"""
Term-hashing embedding: a dependency-free, deterministic *lexical* embedding.

Each text is tokenised (lower-cased words plus character trigrams of each word),
tokens are hashed into a fixed number of buckets with a sign hash ("feature
hashing"), weighted by sub-linear term frequency, and L2-normalised. Cosine
similarity therefore reflects shared vocabulary between query and record, so
"servo fault on robot" ranks servo-fault records first.

It is NOT a semantic model: synonyms ("stall" vs "jam") don't match. Use a real
embedding model for semantic retrieval. Select with EMBEDDING_PROVIDER=hashed_terms.
"""
from __future__ import annotations

import hashlib
import math
import re

from app.embeddings.provider import EmbeddingProvider

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be by for from has have in is it of on or the this that to was were with".split()
)


class HashedTermEmbedding(EmbeddingProvider):
    def __init__(self, dimension: int = 128) -> None:
        self.dimension = dimension

    def _tokens(self, text: str) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        for word in _WORD.findall((text or "").lower()):
            if word in _STOP:
                continue
            out.append((f"w:{word}", 1.0))
            padded = f"^{word}$"
            for i in range(len(padded) - 2):
                out.append((f"c:{padded[i:i + 3]}", 0.35))
        return out

    def embed_text(self, text: str) -> list[float]:
        counts: dict[str, float] = {}
        for tok, weight in self._tokens(text):
            counts[tok] = counts.get(tok, 0.0) + weight
        vec = [0.0] * self.dimension
        for tok, tf in counts.items():
            digest = hashlib.blake2b(tok.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[bucket] += sign * (1.0 + math.log(tf)) if tf >= 1 else sign * tf
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            vec[0] = 1.0  # stable non-zero vector for empty text
            return vec
        return [v / norm for v in vec]

    def get_dimension(self) -> int:
        return self.dimension
