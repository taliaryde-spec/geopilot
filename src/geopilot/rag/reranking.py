"""Cross-Encoder reranking for candidates recalled by Hybrid Search."""

from collections.abc import Iterable
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Protocol

from fastembed.rerank.cross_encoder import TextCrossEncoder

from geopilot.rag.hybrid import HybridSearcher
from geopilot.rag.models import (
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    RetrievalMode,
)

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-base"
DEFAULT_RERANK_CANDIDATE_K = 12


class RerankerErrorCode(StrEnum):
    """Stable identifiers for reranker contract failures."""

    EMPTY_INPUT = "empty_reranker_input"
    RESULT_COUNT_MISMATCH = "reranker_result_count_mismatch"
    INVALID_SCORE = "invalid_reranker_score"


class RerankerError(ValueError):
    """Raised when a reranker input or result violates its contract."""

    def __init__(self, code: RerankerErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class Reranker(Protocol):
    """Minimal query-document scoring interface used by the retrieval layer."""

    @property
    def model_name(self) -> str:
        """Return the stable reranker model identifier."""
        ...

    def score(self, query: str, documents: list[str]) -> list[float]:
        """Return one relevance score for each query-document pair."""
        ...


def _materialize_scores(
    scores: Iterable[float],
    *,
    expected_count: int,
) -> list[float]:
    materialized = [float(score) for score in scores]
    if len(materialized) != expected_count:
        raise RerankerError(
            RerankerErrorCode.RESULT_COUNT_MISMATCH,
            "Reranker result count does not match candidate count.",
        )
    if any(not isfinite(score) for score in materialized):
        raise RerankerError(
            RerankerErrorCode.INVALID_SCORE,
            "Reranker returned a non-finite relevance score.",
        )
    return materialized


class FastEmbedReranker:
    """Lazy CPU Cross-Encoder adapter backed by FastEmbed and ONNX Runtime."""

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        *,
        cache_directory: str | Path | None = None,
        threads: int | None = None,
    ) -> None:
        cleaned_model_name = model_name.strip()
        if not cleaned_model_name:
            raise ValueError("Reranker model_name must not be empty.")
        self._model_name = cleaned_model_name
        self._cache_directory = (
            str(Path(cache_directory).resolve())
            if cache_directory is not None
            else None
        )
        self._threads = threads
        self._model: TextCrossEncoder | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def score(self, query: str, documents: list[str]) -> list[float]:
        cleaned_query = query.strip()
        cleaned_documents = [document.strip() for document in documents]
        if (
            not cleaned_query
            or not cleaned_documents
            or any(not document for document in cleaned_documents)
        ):
            raise RerankerError(
                RerankerErrorCode.EMPTY_INPUT,
                "Reranker query and candidate documents must not be empty.",
            )
        return _materialize_scores(
            self._get_model().rerank(cleaned_query, cleaned_documents),
            expected_count=len(cleaned_documents),
        )

    def _get_model(self) -> TextCrossEncoder:
        if self._model is None:
            if self._cache_directory is not None:
                Path(self._cache_directory).mkdir(parents=True, exist_ok=True)
            self._model = TextCrossEncoder(
                model_name=self._model_name,
                cache_dir=self._cache_directory,
                threads=self._threads,
                lazy_load=True,
            )
        return self._model


class RerankSearcher:
    """Apply a Cross-Encoder to a bounded Hybrid Search candidate pool."""

    def __init__(
        self,
        hybrid_searcher: HybridSearcher,
        reranker: Reranker,
        *,
        candidate_k: int = DEFAULT_RERANK_CANDIDATE_K,
    ) -> None:
        if candidate_k < 1 or candidate_k > 20:
            raise ValueError("Rerank candidate_k must be between 1 and 20.")
        self._hybrid_searcher = hybrid_searcher
        self._reranker = reranker
        self._candidate_k = candidate_k

    def search(self, query: str, *, top_k: int) -> KnowledgeSearchResult:
        """Recall Hybrid candidates, score query-document pairs, and reorder."""
        if top_k < 1 or top_k > 20:
            raise ValueError("Rerank top_k must be between 1 and 20.")
        candidate_k = max(top_k, self._candidate_k)
        candidates = self._hybrid_searcher.search(query, top_k=candidate_k)
        documents = [
            f"{hit.title}\n{hit.section}\n{hit.text}" for hit in candidates.hits
        ]
        scores = self._reranker.score(query, documents)
        ranked = sorted(
            zip(candidates.hits, scores, strict=True),
            key=lambda item: (-item[1], item[0].chunk_id),
        )
        hits: list[KnowledgeSearchHit] = []
        for rank, (hit, score) in enumerate(ranked[:top_k], start=1):
            hits.append(
                hit.model_copy(
                    update={
                        "score": score,
                        "rerank_score": score,
                        "rerank_rank": rank,
                    }
                )
            )
        return KnowledgeSearchResult(
            query=candidates.query,
            model_name=candidates.model_name,
            retrieval_mode=RetrievalMode.HYBRID_RERANK,
            reranker_model_name=self._reranker.model_name,
            hits=hits,
        )
