"""High-level knowledge indexing and retrieval composition."""

from collections.abc import Sequence
from pathlib import Path

from geopilot.rag.chunker import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    chunk_knowledge_documents,
)
from geopilot.rag.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingError,
    EmbeddingErrorCode,
    EmbeddingProvider,
    FastEmbedProvider,
    TokenCounter,
)
from geopilot.rag.hybrid import (
    DEFAULT_HYBRID_CANDIDATE_K,
    DEFAULT_RRF_K,
    HybridSearcher,
)
from geopilot.rag.loader import load_knowledge_documents
from geopilot.rag.models import (
    KnowledgeBuildResult,
    KnowledgeSearchResult,
    RetrievalMode,
)
from geopilot.rag.reranking import (
    DEFAULT_RERANK_CANDIDATE_K,
    DEFAULT_RERANKER_MODEL,
    FastEmbedReranker,
    Reranker,
    RerankSearcher,
)
from geopilot.rag.tokenization import summarize_token_usage
from geopilot.rag.vector_store import LocalVectorStore

DEFAULT_KNOWLEDGE_INDEX = Path("artifacts") / "rag" / "index.json"
DEFAULT_MODEL_CACHE = Path("artifacts") / "models" / "fastembed"
DEFAULT_RERANKER_CACHE = Path("artifacts") / "models" / "fastembed-rerank"
DEFAULT_RETRIEVAL_MODE = RetrievalMode.HYBRID


class KnowledgeRetriever:
    """Small application-facing facade around the local vector store."""

    def __init__(
        self,
        store: LocalVectorStore,
        *,
        retrieval_mode: RetrievalMode = DEFAULT_RETRIEVAL_MODE,
        hybrid_candidate_k: int = DEFAULT_HYBRID_CANDIDATE_K,
        rrf_k: int = DEFAULT_RRF_K,
        reranker: Reranker | None = None,
        rerank_candidate_k: int = DEFAULT_RERANK_CANDIDATE_K,
    ) -> None:
        self._store = store
        self._retrieval_mode = retrieval_mode
        self._hybrid_searcher = HybridSearcher(
            store,
            candidate_k=hybrid_candidate_k,
            rrf_k=rrf_k,
        )
        self._rerank_searcher: RerankSearcher | None = None
        if retrieval_mode is RetrievalMode.HYBRID_RERANK:
            if reranker is None:
                raise ValueError("Hybrid rerank mode requires a reranker.")
            self._rerank_searcher = RerankSearcher(
                self._hybrid_searcher,
                reranker,
                candidate_k=rerank_candidate_k,
            )

    @property
    def retrieval_mode(self) -> RetrievalMode:
        return self._retrieval_mode

    def search(self, query: str, *, top_k: int = 4) -> KnowledgeSearchResult:
        if self._retrieval_mode is RetrievalMode.HYBRID_RERANK:
            if self._rerank_searcher is None:
                raise RuntimeError("Rerank searcher was not initialized.")
            return self._rerank_searcher.search(query, top_k=top_k)
        if self._retrieval_mode is RetrievalMode.HYBRID:
            return self._hybrid_searcher.search(query, top_k=top_k)
        return self._store.search(query, top_k=top_k)


def build_knowledge_index(
    sources: Sequence[str | Path],
    *,
    index_path: str | Path = DEFAULT_KNOWLEDGE_INDEX,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    cache_directory: str | Path = DEFAULT_MODEL_CACHE,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    embedding_provider: EmbeddingProvider | None = None,
    working_directory: str | Path | None = None,
) -> KnowledgeBuildResult:
    """Load, chunk, embed, and persist a knowledge corpus."""
    documents = load_knowledge_documents(
        sources,
        working_directory=working_directory,
    )
    chunks = chunk_knowledge_documents(
        documents,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    provider = embedding_provider or FastEmbedProvider(
        model_name,
        cache_directory=cache_directory,
    )
    token_usage = None
    if isinstance(provider, TokenCounter):
        token_usage = summarize_token_usage(
            [chunk.embedding_text for chunk in chunks],
            provider,
        )
        if token_usage.over_limit_chunk_count:
            raise EmbeddingError(
                EmbeddingErrorCode.INPUT_TOKEN_LIMIT_EXCEEDED,
                (
                    f"{token_usage.over_limit_chunk_count} embedding input(s) exceed "
                    f"the {token_usage.model_max_input_tokens}-token model limit; "
                    "reduce chunk_size before building the index."
                ),
            )
    build_result = LocalVectorStore(index_path, provider).build(chunks)
    return build_result.model_copy(update={"token_usage": token_usage})


def open_knowledge_retriever(
    *,
    index_path: str | Path = DEFAULT_KNOWLEDGE_INDEX,
    cache_directory: str | Path = DEFAULT_MODEL_CACHE,
    embedding_provider: EmbeddingProvider | None = None,
    retrieval_mode: RetrievalMode = DEFAULT_RETRIEVAL_MODE,
    hybrid_candidate_k: int = DEFAULT_HYBRID_CANDIDATE_K,
    rrf_k: int = DEFAULT_RRF_K,
    reranker: Reranker | None = None,
    reranker_model_name: str = DEFAULT_RERANKER_MODEL,
    reranker_cache_directory: str | Path = DEFAULT_RERANKER_CACHE,
    rerank_candidate_k: int = DEFAULT_RERANK_CANDIDATE_K,
) -> KnowledgeRetriever:
    """Open an existing index with its recorded embedding model."""
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
    selected_reranker = reranker
    if retrieval_mode is RetrievalMode.HYBRID_RERANK and selected_reranker is None:
        selected_reranker = FastEmbedReranker(
            reranker_model_name,
            cache_directory=reranker_cache_directory,
        )
    return KnowledgeRetriever(
        LocalVectorStore(selected_path, provider),
        retrieval_mode=retrieval_mode,
        hybrid_candidate_k=hybrid_candidate_k,
        rrf_k=rrf_k,
        reranker=selected_reranker,
        rerank_candidate_k=rerank_candidate_k,
    )
