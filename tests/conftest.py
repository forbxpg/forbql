"""Settings for every test."""

from __future__ import annotations

import os

from hypothesis import settings

import forbql.session._knowledge as knowledge
from support.embedding import WordEmbedder

# A pull request spoils a few hundred queries; the nightly run many thousands.
settings.register_profile("pr", max_examples=300, deadline=None)
settings.register_profile("nightly", max_examples=20_000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "pr"))


def pytest_configure() -> None:
    # The real model is 1.1 GB; tests that need it pass FastEmbedder() themselves.
    knowledge.DEFAULT_EMBEDDER = WordEmbedder()
