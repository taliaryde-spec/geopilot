"""Controlled Dense-only versus Hybrid Search retrieval experiments."""

from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from geopilot.rag.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingProvider,
    FastEmbedProvider,
)
from geopilot.rag.evaluation import evaluate_retrieval
from geopilot.rag.hybrid import DEFAULT_HYBRID_CANDIDATE_K, DEFAULT_RRF_K
from geopilot.rag.models import (
    RetrievalEvaluationCase,
    RetrievalExperimentResult,
    RetrievalExperimentRun,
    RetrievalMode,
)
from geopilot.rag.service import DEFAULT_MODEL_CACHE, KnowledgeRetriever
from geopilot.rag.vector_store import LocalVectorStore


def run_retrieval_experiment(
    index_path: str | Path,
    cases: list[RetrievalEvaluationCase],
    *,
    embedding_provider: EmbeddingProvider | None = None,
    cache_directory: str | Path = DEFAULT_MODEL_CACHE,
    top_k: int = 3,
    hybrid_candidate_k: int = DEFAULT_HYBRID_CANDIDATE_K,
    rrf_k: int = DEFAULT_RRF_K,
    timer: Callable[[], float] = perf_counter,
) -> RetrievalExperimentResult:
    """Compare retrieval modes while sharing index, model, queries, and Top-K."""
    if not cases:
        raise ValueError("At least one retrieval evaluation case is required.")
    selected_path = Path(index_path)
    provider = embedding_provider
    if provider is None:
        manifest = (
            LocalVectorStore(
                selected_path,
                FastEmbedProvider(
                    DEFAULT_EMBEDDING_MODEL,
                    cache_directory=cache_directory,
                ),
            )
            .load()
            .manifest
        )
        provider = FastEmbedProvider(
            manifest.model_name,
            cache_directory=cache_directory,
        )
    store = LocalVectorStore(selected_path, provider)
    manifest = store.load().manifest
    provider.embed_query("GeoPilot retrieval experiment warmup")
    runs: list[RetrievalExperimentRun] = []

    for mode in (RetrievalMode.DENSE, RetrievalMode.HYBRID):
        retriever = KnowledgeRetriever(
            store,
            retrieval_mode=mode,
            hybrid_candidate_k=hybrid_candidate_k,
            rrf_k=rrf_k,
        )
        started = timer()
        evaluation = evaluate_retrieval(retriever, cases, top_k=top_k)
        duration_ms = max(0.0, (timer() - started) * 1000)
        runs.append(
            RetrievalExperimentRun(
                retrieval_mode=mode,
                duration_ms=duration_ms,
                evaluation=evaluation,
            )
        )

    dense_evaluation = runs[0].evaluation
    hybrid_evaluation = runs[1].evaluation
    improved_case_count = 0
    regressed_case_count = 0
    unchanged_case_count = 0
    for dense_case, hybrid_case in zip(
        dense_evaluation.cases,
        hybrid_evaluation.cases,
        strict=True,
    ):
        dense_rank = dense_case.first_relevant_rank or (top_k + 1)
        hybrid_rank = hybrid_case.first_relevant_rank or (top_k + 1)
        if hybrid_rank < dense_rank:
            improved_case_count += 1
        elif hybrid_rank > dense_rank:
            regressed_case_count += 1
        else:
            unchanged_case_count += 1

    return RetrievalExperimentResult(
        index_path=str(Path(index_path).resolve()),
        model_name=manifest.model_name,
        top_k=top_k,
        case_count=len(cases),
        hybrid_candidate_k=hybrid_candidate_k,
        rrf_k=rrf_k,
        hit_rate_delta=(
            hybrid_evaluation.hit_rate_at_k - dense_evaluation.hit_rate_at_k
        ),
        precision_delta=(
            hybrid_evaluation.mean_precision_at_k - dense_evaluation.mean_precision_at_k
        ),
        recall_delta=(
            hybrid_evaluation.mean_recall_at_k - dense_evaluation.mean_recall_at_k
        ),
        mrr_delta=(
            hybrid_evaluation.mean_reciprocal_rank
            - dense_evaluation.mean_reciprocal_rank
        ),
        ndcg_delta=(hybrid_evaluation.mean_ndcg_at_k - dense_evaluation.mean_ndcg_at_k),
        improved_case_count=improved_case_count,
        regressed_case_count=regressed_case_count,
        unchanged_case_count=unchanged_case_count,
        runs=runs,
    )
