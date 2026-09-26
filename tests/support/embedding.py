"""An embedder for tests: fast, deterministic, no download."""

from __future__ import annotations

import hashlib
import math
import re
from typing import TYPE_CHECKING, final, override

from forbql.knowledge import Embedder

if TYPE_CHECKING:
    from collections.abc import Sequence

DIMENSIONS = 64


@final
class WordEmbedder(Embedder):
    """Hashes words into buckets: texts sharing words point the same way."""

    def __init__(self, name: str = "test/words") -> None:
        self.name = name

    @override
    def documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    @override
    def query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * DIMENSIONS
        for word in re.findall(r"\w+", text.lower()):
            bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMENSIONS
            vector[bucket] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]
