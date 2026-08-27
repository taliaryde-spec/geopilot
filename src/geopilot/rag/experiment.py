"""Controlled experiments for comparing RAG chunking parameters."""

from collections.abc import Callable, Sequence
from pathlib import Path
from statistics import fmean
from time import perf_counter

from geopilot.rag.chunker import chunk_knowledge_documents
from geopilot.rag.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingProvider,
    FastEmbedProvider,
    TokenCounter,
)
from geopilot.rag.evaluation import evaluate_retrieval
from geopilot.rag.loader import load_knowledge_documents
from geopilot.rag.models import (
    ChunkingExperimentResult,
    ChunkingExperimentRun,
    ChunkingExperimentVariant,
    RetrievalEvaluationCase,
)
from geopilot.rag.service import DEFAULT_MODEL_CACHE, KnowledgeRetriever
from geopilot.rag.tokenization import (
    DEFAULT_TOKEN_WARNING_RATIO,
    summarize_token_usage,
)
from geopilot.rag.vector_store import LocalVectorStore

DEFAULT_CHUNKING_VARIANTS = (
    ChunkingExperimentVariant(chunk_size=300, chunk_overlap=50),
    ChunkingExperimentVariant(chunk_size=500, chunk_overlap=80),
    ChunkingExperimentVariant(chunk_size=700, chunk_overlap=100),
    ChunkingExperimentVariant(chunk_size=900, chunk_overlap=120),
)


def run_chunking_experiment(
    sources: Sequence[str | Path],
    cases: list[RetrievalEvaluationCase],
    *,
    variants: Sequence[ChunkingExperimentVariant] = DEFAULT_CHUNKING_VARIANTS,
    output_directory: str | Path = Path("artifacts") / "rag" / "chunk_experiments",
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    cache_directory: str | Path = DEFAULT_MODEL_CACHE,
    top_k: int = 3,
    embedding_provider: EmbeddingProvider | None = None,
    token_counter: TokenCounter | None = None,
    token_warning_ratio: float = DEFAULT_TOKEN_WARNING_RATIO,
    working_directory: str | Path | None = None,
    timer: Callable[[], float] = perf_counter,
) -> ChunkingExperimentResult:
    """Evaluate chunk variants while holding corpus and retrieval settings fixed."""
    selected_variants = list(variants)
    if len(selected_variants) < 2:
        raise ValueError("At least two chunking variants are required.")
    variant_pairs = [
        (variant.chunk_size, variant.chunk_overlap) for variant in selected_variants
    ]
    if len(set(variant_pairs)) != len(variant_pairs):
        raise ValueError("Chunking experiment variants must be unique.")
    if not cases:
        raise ValueError("At least one retrieval evaluation case is required.")

    documents = load_knowledge_documents(
        sources,
        working_directory=working_directory,
    )
    provider = embedding_provider or FastEmbedProvider(
        model_name,
        cache_directory=cache_directory,
    )
    selected_token_counter = token_counter
    if selected_token_counter is None and isinstance(provider, TokenCounter):
        selected_token_counter = provider
    if selected_token_counter is None:
        raise ValueError(
            "Chunking experiments require a token counter for the embedding model."
        )
    if selected_token_counter.model_name != provider.model_name:
        raise ValueError("Token counter model must match the embedding provider model.")
    selected_output_directory = Path(output_directory).resolve()
    runs: list[ChunkingExperimentRun] = []

    for variant in selected_variants:
        chunks = chunk_knowledge_documents(
            documents,
            chunk_size=variant.chunk_size,
            chunk_overlap=variant.chunk_overlap,
        )
        index_path = selected_output_directory / f"{variant.label}.json"
        store = LocalVectorStore(index_path, provider)

        build_started = timer()
        build = store.build(chunks)
        build_duration_ms = max(0.0, (timer() - build_started) * 1000)

        evaluation_started = timer()
        evaluation = evaluate_retrieval(
            KnowledgeRetriever(store),
            cases,
            top_k=top_k,
        )
        evaluation_duration_ms = max(0.0, (timer() - evaluation_started) * 1000)
        chunk_lengths = [len(chunk.text) for chunk in chunks]
        token_usage = summarize_token_usage(
            [chunk.embedding_text for chunk in chunks],
            selected_token_counter,
            warning_threshold_ratio=token_warning_ratio,
        )
        runs.append(
            ChunkingExperimentRun(
                variant=variant,
                index_path=build.index_path,
                document_count=build.document_count,
                chunk_count=build.chunk_count,
                mean_chunk_characters=fmean(chunk_lengths),
                max_chunk_characters=max(chunk_lengths),
                token_usage=token_usage,
                index_size_bytes=index_path.stat().st_size,
                build_duration_ms=build_duration_ms,
                evaluation_duration_ms=evaluation_duration_ms,
                evaluation=evaluation,
            )
        )

    return ChunkingExperimentResult(
        model_name=provider.model_name,
        top_k=top_k,
        case_count=len(cases),
        sources=sorted(document.source for document in documents),
        runs=runs,
    )
