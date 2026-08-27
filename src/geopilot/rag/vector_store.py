"""A transparent JSON + NumPy vector index for small local knowledge bases."""

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from geopilot.rag.embeddings import EmbeddingProvider
from geopilot.rag.models import (
    IndexedKnowledgeChunk,
    KnowledgeBuildResult,
    KnowledgeChunk,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    RetrievalMode,
    StoredVectorIndex,
    VectorIndexManifest,
)


class VectorStoreErrorCode(StrEnum):
    """Stable identifiers for local vector index failures."""

    INDEX_NOT_FOUND = "vector_index_not_found"
    CORRUPT_INDEX = "corrupt_vector_index"
    MODEL_MISMATCH = "embedding_model_mismatch"
    VECTOR_COUNT_MISMATCH = "vector_count_mismatch"
    VECTOR_DIMENSION_MISMATCH = "vector_dimension_mismatch"
    INVALID_VECTOR = "invalid_embedding_vector"
    INVALID_TOP_K = "invalid_top_k"


class VectorStoreError(ValueError):
    """Raised when a vector index cannot be built or queried safely."""

    def __init__(self, code: VectorStoreErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _normalized_vector(
    vector: list[float], *, dimension: int | None = None
) -> list[float]:
    if not vector or any(not isfinite(value) for value in vector):
        raise VectorStoreError(
            VectorStoreErrorCode.INVALID_VECTOR,
            "Embedding vectors must contain finite numeric values.",
        )
    if dimension is not None and len(vector) != dimension:
        raise VectorStoreError(
            VectorStoreErrorCode.VECTOR_DIMENSION_MISMATCH,
            f"Embedding dimension {len(vector)} does not match index dimension {dimension}.",
        )
    array = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(array))
    if not isfinite(norm) or norm <= 0:
        raise VectorStoreError(
            VectorStoreErrorCode.INVALID_VECTOR,
            "Embedding vectors must have a positive finite norm.",
        )
    return [float(value) for value in array / norm]


class LocalVectorStore:
    """Build and search a durable exact cosine-similarity index."""

    def __init__(
        self,
        index_path: str | Path,
        embedding_provider: EmbeddingProvider,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._index_path = Path(index_path).resolve()
        self._embedding_provider = embedding_provider
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def index_path(self) -> Path:
        return self._index_path

    def build(self, chunks: list[KnowledgeChunk]) -> KnowledgeBuildResult:
        """Embed chunks, normalize vectors, and atomically replace the index."""
        if not chunks:
            raise ValueError("At least one knowledge chunk is required.")
        vectors = self._embedding_provider.embed_documents(
            [chunk.embedding_text for chunk in chunks]
        )
        if len(vectors) != len(chunks):
            raise VectorStoreError(
                VectorStoreErrorCode.VECTOR_COUNT_MISMATCH,
                "Embedding count does not match knowledge chunk count.",
            )
        dimension = len(vectors[0]) if vectors else 0
        normalized_vectors = [
            _normalized_vector(vector, dimension=dimension) for vector in vectors
        ]
        indexed_chunks = [
            IndexedKnowledgeChunk(
                **chunk.model_dump(),
                vector=vector,
            )
            for chunk, vector in zip(chunks, normalized_vectors, strict=True)
        ]
        manifest = VectorIndexManifest(
            model_name=self._embedding_provider.model_name,
            dimension=dimension,
            document_count=len({chunk.document_id for chunk in chunks}),
            chunk_count=len(chunks),
            created_at=self._clock(),
        )
        index = StoredVectorIndex(manifest=manifest, chunks=indexed_chunks)
        self._write(index)
        return KnowledgeBuildResult(
            index_path=str(self._index_path),
            model_name=manifest.model_name,
            dimension=manifest.dimension,
            document_count=manifest.document_count,
            chunk_count=manifest.chunk_count,
            sources=sorted({chunk.source for chunk in chunks}),
        )

    def load(self) -> StoredVectorIndex:
        """Load and validate the complete portable index."""
        if not self._index_path.is_file():
            raise VectorStoreError(
                VectorStoreErrorCode.INDEX_NOT_FOUND,
                f"Knowledge vector index does not exist: {self._index_path}",
            )
        try:
            return StoredVectorIndex.model_validate_json(
                self._index_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as error:
            raise VectorStoreError(
                VectorStoreErrorCode.CORRUPT_INDEX,
                f"Knowledge vector index is unreadable or invalid: {self._index_path}",
            ) from error

    def search(
        self,
        query: str,
        *,
        top_k: int = 4,
        minimum_score: float = -1.0,
    ) -> KnowledgeSearchResult:
        """Return exact cosine-ranked chunks with source citations."""
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("Knowledge search query must not be empty.")
        if top_k < 1 or top_k > 20:
            raise VectorStoreError(
                VectorStoreErrorCode.INVALID_TOP_K,
                "top_k must be between 1 and 20.",
            )
        if not -1.0 <= minimum_score <= 1.0:
            raise ValueError("minimum_score must be between -1 and 1.")
        index = self.load()
        if index.manifest.model_name != self._embedding_provider.model_name:
            raise VectorStoreError(
                VectorStoreErrorCode.MODEL_MISMATCH,
                "Query embedding model does not match the stored index: "
                f"{self._embedding_provider.model_name!r} != "
                f"{index.manifest.model_name!r}.",
            )
        query_vector = np.asarray(
            _normalized_vector(
                self._embedding_provider.embed_query(cleaned_query),
                dimension=index.manifest.dimension,
            ),
            dtype=np.float64,
        )
        ranked: list[tuple[float, IndexedKnowledgeChunk]] = []
        for chunk in index.chunks:
            score = float(np.dot(query_vector, np.asarray(chunk.vector)))
            if score >= minimum_score:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: (-item[0], item[1].chunk_id))
        hits = [
            KnowledgeSearchHit(
                chunk_id=chunk.chunk_id,
                source=chunk.source,
                title=chunk.title,
                section=chunk.section,
                citation=chunk.citation,
                text=chunk.text,
                score=max(-1.0, min(1.0, score)),
                dense_score=max(-1.0, min(1.0, score)),
                dense_rank=rank,
            )
            for rank, (score, chunk) in enumerate(ranked[:top_k], start=1)
        ]
        return KnowledgeSearchResult(
            query=cleaned_query,
            model_name=index.manifest.model_name,
            retrieval_mode=RetrievalMode.DENSE,
            hits=hits,
        )

    def _write(self, index: StoredVectorIndex) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._index_path.with_suffix(self._index_path.suffix + ".tmp")
        try:
            temporary_path.write_text(
                index.model_dump_json(indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(self._index_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
