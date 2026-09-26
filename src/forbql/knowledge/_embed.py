"""Turning text into vectors, locally: nothing leaves the host."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, final, override

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastembed import TextEmbedding

MODEL = "Qwen/Qwen3-Embedding-0.6B-Q"
"""Chosen by recall on the evaluation set: multilingual, 1.1 GB, 1024 dimensions."""

_TASK = (
    "Given a question about data, "
    "retrieve the database tables and columns needed to answer it"
)
"""The instruction Qwen3 embeddings expect before a query; documents take none."""


class Embedder(ABC):
    """Embeds documents and queries into one vector space.

    Attributes:
        name: str - The model, kept beside every vector so a change is noticed.

    """

    name: str

    @abstractmethod
    def documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed documents.

        Args:
            texts: Sequence[str] - Their bodies.

        Returns:
            list[list[float]] - One vector per text.

        """

    @abstractmethod
    def query(self, text: str) -> list[float]:
        """Embed a question.

        Args:
            text: str - What the caller asks.

        Returns:
            list[float] - Its vector.

        """


@final
class FastEmbedder(Embedder):
    """The chosen model through fastembed; the model loads on first use.

    The first use downloads it (about 1.1 GB) into fastembed's cache, which
    `FASTEMBED_CACHE_PATH` moves.

    """

    _model: TextEmbedding | None

    def __init__(self) -> None:
        self.name = MODEL
        self._model = None

    @override
    def documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed documents.

        Args:
            texts: Sequence[str] - Their bodies.

        Returns:
            list[list[float]] - One vector per text.

        """
        vectors = self._load().embed(list(texts))
        return [[float(x) for x in vector] for vector in vectors]  # pyright: ignore[reportAny]

    @override
    def query(self, text: str) -> list[float]:
        """Embed a question with the instruction the model expects.

        Args:
            text: str - What the caller asks.

        Returns:
            list[float] - Its vector.

        """
        [vector] = self.documents([f"Instruct: {_TASK}\nQuery:{text}"])
        return vector

    def _load(self) -> TextEmbedding:
        """Load the model once.

        Returns:
            TextEmbedding - The model.

        """
        if self._model is None:
            import onnxruntime  # ruff: ignore[import-outside-top-level] - loads with the model
            from fastembed import TextEmbedding  # ruff: ignore[import-outside-top-level] - loading takes seconds and a download

            # Its macOS build uploads telemetry from a thread that can abort the
            # process at exit; and nothing is to leave the host.
            onnxruntime.disable_telemetry_events()  # pyright: ignore[reportUnknownMemberType]
            self._model = TextEmbedding(MODEL)
        return self._model
