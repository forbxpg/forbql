"""The embedder keeps onnxruntime quiet: no telemetry leaves the host."""

from __future__ import annotations

from typing import TYPE_CHECKING

import fastembed
import onnxruntime

from forbql.knowledge import FastEmbedder

if TYPE_CHECKING:
    import pytest


def test_telemetry_is_off_before_the_model_loads(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    class Model:
        def __init__(self, name: str) -> None:
            calls.append(f"load {name}")

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] for _ in texts]

    monkeypatch.setattr(fastembed, "TextEmbedding", Model)
    monkeypatch.setattr(
        onnxruntime,
        "disable_telemetry_events",
        lambda: calls.append("telemetry off"),
    )

    _ = FastEmbedder().query("x")

    assert calls == ["telemetry off", "load Qwen/Qwen3-Embedding-0.6B-Q"]
