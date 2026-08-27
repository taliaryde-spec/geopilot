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
    EmbeddingProvider,
    FastEmbedProvider,
)
from geopilot.rag.loader import load_knowledge_documents
from geopilot.rag.models import KnowledgeBuildResult, KnowledgeSearchResult
from geopilot.rag.vector_store import LocalVectorStore

DEFAULT_KNOWLEDGE_INDEX = Path("artifacts") / "rag" / "index.json"
DEFAULT_MODEL_CACHE = Path("artifacts") / "models" / "fastembed"


class KnowledgeRetriever:
    """Small application-facing facade around the local vector store."""

    def __init__(self, store: LocalVectorStore) -> None:
        self._store = store

    def search(self, query: str, *, top_k: int = 4) -> KnowledgeSearchResult:
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
    return LocalVectorStore(index_path, provider).build(chunks)


def open_knowledge_retriever(
    *,
    index_path: str | Path = DEFAULT_KNOWLEDGE_INDEX,
    cache_directory: str | Path = DEFAULT_MODEL_CACHE,
    embedding_provider: EmbeddingProvider | None = None,
) -> KnowledgeRetriever:
    """Open an existing index with its recorded embedding model."""
    selected_path = Path(index_path)
    if embedding_provider is not None:
        return KnowledgeRetriever(LocalVectorStore(selected_path, embedding_provider))
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
    return KnowledgeRetriever(LocalVectorStore(selected_path, provider))
