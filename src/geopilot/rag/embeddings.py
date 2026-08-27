"""Embedding provider contracts and a local FastEmbed implementation."""

from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from fastembed import TextEmbedding

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"


class EmbeddingErrorCode(StrEnum):
    """Stable identifiers for local embedding failures."""

    EMPTY_INPUT = "empty_embedding_input"
    RESULT_COUNT_MISMATCH = "embedding_result_count_mismatch"
    EMPTY_VECTOR = "empty_embedding_vector"


class EmbeddingError(ValueError):
    """Raised when an embedding provider violates its output contract."""

    def __init__(self, code: EmbeddingErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class EmbeddingProvider(Protocol):
    """Minimal provider interface used by indexing and retrieval."""

    @property
    def model_name(self) -> str:
        """Return the stable model identifier stored in the index."""
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed retrieval passages in the source-document role."""
        ...

    def embed_query(self, query: str) -> list[float]:
        """Embed one retrieval query in the query role."""
        ...


def _materialize_vectors(
    vectors: Iterable[object],
    *,
    expected_count: int,
) -> list[list[float]]:
    materialized: list[list[float]] = []
    for vector in vectors:
        values = getattr(vector, "tolist", None)
        raw_values = values() if callable(values) else vector
        if not isinstance(raw_values, list) or not raw_values:
            raise EmbeddingError(
                EmbeddingErrorCode.EMPTY_VECTOR,
                "Embedding provider returned an empty or unsupported vector.",
            )
        materialized.append([float(value) for value in raw_values])
    if len(materialized) != expected_count:
        raise EmbeddingError(
            EmbeddingErrorCode.RESULT_COUNT_MISMATCH,
            "Embedding result count does not match input count.",
        )
    return materialized


class FastEmbedProvider:
    """CPU-friendly ONNX embeddings with lazy model initialization."""

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        *,
        cache_directory: str | Path | None = None,
        threads: int | None = None,
    ) -> None:
        cleaned_model_name = model_name.strip()
        if not cleaned_model_name:
            raise ValueError("Embedding model_name must not be empty.")
        self._model_name = cleaned_model_name
        self._cache_directory = (
            str(Path(cache_directory).resolve())
            if cache_directory is not None
            else None
        )
        self._threads = threads
        self._model: TextEmbedding | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        cleaned_texts = _validate_texts(texts)
        return _materialize_vectors(
            self._get_model().passage_embed(cleaned_texts),
            expected_count=len(cleaned_texts),
        )

    def embed_query(self, query: str) -> list[float]:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise EmbeddingError(
                EmbeddingErrorCode.EMPTY_INPUT,
                "Embedding query must not be empty.",
            )
        return _materialize_vectors(
            self._get_model().query_embed(cleaned_query),
            expected_count=1,
        )[0]

    def _get_model(self) -> TextEmbedding:
        if self._model is None:
            if self._cache_directory is not None:
                Path(self._cache_directory).mkdir(parents=True, exist_ok=True)
            self._model = TextEmbedding(
                model_name=self._model_name,
                cache_dir=self._cache_directory,
                threads=self._threads,
                lazy_load=True,
            )
        return self._model


def _validate_texts(texts: list[str]) -> list[str]:
    if not texts:
        raise EmbeddingError(
            EmbeddingErrorCode.EMPTY_INPUT,
            "At least one document is required for embedding.",
        )
    cleaned = [text.strip() for text in texts]
    if any(not text for text in cleaned):
        raise EmbeddingError(
            EmbeddingErrorCode.EMPTY_INPUT,
            "Embedding documents must not contain empty text.",
        )
    return cleaned
