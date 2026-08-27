"""Local retrieval-augmented generation components for GeoPilot."""

from geopilot.rag.chunker import chunk_knowledge_documents
from geopilot.rag.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingError,
    EmbeddingErrorCode,
    EmbeddingProvider,
    FastEmbedProvider,
)
from geopilot.rag.evaluation import evaluate_retrieval, load_evaluation_cases
from geopilot.rag.loader import (
    KnowledgeLoadError,
    KnowledgeLoadErrorCode,
    load_knowledge_document,
    load_knowledge_documents,
)
from geopilot.rag.models import (
    IndexedKnowledgeChunk,
    KnowledgeBuildResult,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    RetrievalCaseResult,
    RetrievalEvaluationCase,
    RetrievalEvaluationResult,
    StoredVectorIndex,
    VectorIndexManifest,
)
from geopilot.rag.service import (
    DEFAULT_KNOWLEDGE_INDEX,
    DEFAULT_MODEL_CACHE,
    KnowledgeRetriever,
    build_knowledge_index,
    open_knowledge_retriever,
)
from geopilot.rag.vector_store import (
    LocalVectorStore,
    VectorStoreError,
    VectorStoreErrorCode,
)

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_KNOWLEDGE_INDEX",
    "DEFAULT_MODEL_CACHE",
    "EmbeddingError",
    "EmbeddingErrorCode",
    "EmbeddingProvider",
    "FastEmbedProvider",
    "IndexedKnowledgeChunk",
    "KnowledgeBuildResult",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeLoadError",
    "KnowledgeLoadErrorCode",
    "KnowledgeRetriever",
    "KnowledgeSearchHit",
    "KnowledgeSearchResult",
    "LocalVectorStore",
    "RetrievalCaseResult",
    "RetrievalEvaluationCase",
    "RetrievalEvaluationResult",
    "StoredVectorIndex",
    "VectorIndexManifest",
    "VectorStoreError",
    "VectorStoreErrorCode",
    "build_knowledge_index",
    "chunk_knowledge_documents",
    "evaluate_retrieval",
    "load_evaluation_cases",
    "load_knowledge_document",
    "load_knowledge_documents",
    "open_knowledge_retriever",
]
