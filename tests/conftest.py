"""Settings for every test."""

from __future__ import annotations

import forbql.session._knowledge as knowledge
from support.embedding import WordEmbedder


def pytest_configure() -> None:
    # The real model is 1.1 GB; tests that need it pass FastEmbedder() themselves.
    knowledge.DEFAULT_EMBEDDER = WordEmbedder()
