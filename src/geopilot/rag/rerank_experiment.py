"""Controlled Hybrid Search versus Hybrid + Cross-Encoder experiments."""

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
    RerankExperimentResult,
    RetrievalEvaluationCase,
    RetrievalExperimentRun,
    RetrievalMode,
)
from geopilot.rag.reranking import (
    DEFAULT_RERANK_CANDIDATE_K,
    DEFAULT_RERANKER_MODEL,
    FastEmbedReranker,
    Reranker,
)
from geopilot.rag.service import (
    DEFAULT_MODEL_CACHE,
    DEFAULT_RERANKER_CACHE,
    KnowledgeRetriever,
)
from geopilot.rag.vector_store import LocalVectorStore


def run_rerank_experiment(
    index_path: str | Path,
    cases: list[RetrievalEvaluationCase],
    *,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: Reranker | None = None,
    cache_directory: str | Path = DEFAULT_MODEL_CACHE,
    reranker_cache_directory: str | Path = DEFAULT_RERANKER_CACHE,
    reranker_model_name: str = DEFAULT_RERANKER_MODEL,
    top_k: int = 3,
    hybrid_candidate_k: int = DEFAULT_HYBRID_CANDIDATE_K,
    rerank_candidate_k: int = DEFAULT_RERANK_CANDIDATE_K,
    rrf_k: int = DEFAULT_RRF_K,
    timer: Callable[[], float] = perf_counter,
) -> RerankExperimentResult:
    """Compare Hybrid and reranked results with one index, gold set, and Top-K."""
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
    selected_reranker = reranker or FastEmbedReranker(
        reranker_model_name,
        cache_directory=reranker_cache_directory,
    )
    store = LocalVectorStore(selected_path, provider)
    manifest = store.load().manifest
    provider.embed_query("GeoPilot rerank experiment warmup")
    selected_reranker.score(
        "GeoPilot rerank experiment warmup",
        ["GeoPilot rerank experiment warmup candidate"],
    )
    runs: list[RetrievalExperimentRun] = []

    for mode in (RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK):
        retriever = KnowledgeRetriever(
            store,
            retrieval_mode=mode,
            hybrid_candidate_k=hybrid_candidate_k,
            rrf_k=rrf_k,
            reranker=selected_reranker,
            rerank_candidate_k=rerank_candidate_k,
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

    hybrid_evaluation = runs[0].evaluation
    rerank_evaluation = runs[1].evaluation
    improved_case_count = 0
    regressed_case_count = 0
    unchanged_case_count = 0
    for hybrid_case, rerank_case in zip(
        hybrid_evaluation.cases,
        rerank_evaluation.cases,
        strict=True,
    ):
        delta = rerank_case.ndcg_at_k - hybrid_case.ndcg_at_k
        if delta > 1e-12:
            improved_case_count += 1
        elif delta < -1e-12:
            regressed_case_count += 1
        else:
            unchanged_case_count += 1

    return RerankExperimentResult(
        index_path=str(selected_path.resolve()),
        embedding_model_name=manifest.model_name,
        reranker_model_name=selected_reranker.model_name,
        top_k=top_k,
        case_count=len(cases),
        hybrid_candidate_k=hybrid_candidate_k,
        rerank_candidate_k=rerank_candidate_k,
        rrf_k=rrf_k,
        hit_rate_delta=(
            rerank_evaluation.hit_rate_at_k - hybrid_evaluation.hit_rate_at_k
        ),
        precision_delta=(
            rerank_evaluation.mean_precision_at_k
            - hybrid_evaluation.mean_precision_at_k
        ),
        recall_delta=(
            rerank_evaluation.mean_recall_at_k - hybrid_evaluation.mean_recall_at_k
        ),
        mrr_delta=(
            rerank_evaluation.mean_reciprocal_rank
            - hybrid_evaluation.mean_reciprocal_rank
        ),
        ndcg_delta=(
            rerank_evaluation.mean_ndcg_at_k - hybrid_evaluation.mean_ndcg_at_k
        ),
        improved_case_count=improved_case_count,
        regressed_case_count=regressed_case_count,
        unchanged_case_count=unchanged_case_count,
        runs=runs,
    )
