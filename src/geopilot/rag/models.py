"""Validated contracts for GeoPilot retrieval-augmented generation."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class KnowledgeDocument(BaseModel):
    """One UTF-8 knowledge source before chunking."""

    document_id: str = Field(pattern=r"^doc_[a-f0-9]{16}$")
    source: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    metadata: dict[str, str] = Field(default_factory=dict)


class KnowledgeChunk(BaseModel):
    """A citation-ready, structure-aware piece of a knowledge document."""

    chunk_id: str = Field(pattern=r"^chunk_[a-f0-9]{16}$")
    document_id: str = Field(pattern=r"^doc_[a-f0-9]{16}$")
    source: str = Field(min_length=1)
    title: str = Field(min_length=1)
    section: str = Field(min_length=1)
    ordinal: int = Field(ge=1)
    text: str = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def citation(self) -> str:
        """Return the stable source anchor shown to the model and user."""
        return f"{self.source}#{self.section} [chunk:{self.ordinal}]"

    @property
    def embedding_text(self) -> str:
        """Include document structure in the semantic representation."""
        return f"{self.title}\n{self.section}\n{self.text}"


class IndexedKnowledgeChunk(KnowledgeChunk):
    """A normalized dense vector stored beside its source chunk."""

    vector: list[float] = Field(min_length=1)


class VectorIndexManifest(BaseModel):
    """Metadata needed to validate and reopen a local vector index."""

    schema_version: Literal["1.0"] = "1.0"
    model_name: str = Field(min_length=1)
    dimension: int = Field(ge=1)
    document_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    created_at: datetime


class StoredVectorIndex(BaseModel):
    """Portable JSON representation of a small local vector index."""

    manifest: VectorIndexManifest
    chunks: list[IndexedKnowledgeChunk] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_index_consistency(self) -> "StoredVectorIndex":
        """Reject dimension, count, and identifier inconsistencies."""
        if len(self.chunks) != self.manifest.chunk_count:
            raise ValueError("Index chunk_count does not match stored chunks.")
        document_ids = {chunk.document_id for chunk in self.chunks}
        if len(document_ids) != self.manifest.document_count:
            raise ValueError("Index document_count does not match stored chunks.")
        chunk_ids = [chunk.chunk_id for chunk in self.chunks]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("Index chunk identifiers must be unique.")
        if any(len(chunk.vector) != self.manifest.dimension for chunk in self.chunks):
            raise ValueError("Stored vector dimensions do not match the manifest.")
        return self


class KnowledgeBuildResult(BaseModel):
    """Summary returned after building a local knowledge index."""

    index_path: str
    model_name: str
    dimension: int = Field(ge=1)
    document_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    sources: list[str] = Field(min_length=1)


class KnowledgeSearchHit(BaseModel):
    """One semantically relevant chunk with a reproducible citation."""

    chunk_id: str
    source: str
    title: str
    section: str
    citation: str
    text: str
    score: float = Field(ge=-1.0, le=1.0)


class KnowledgeSearchResult(BaseModel):
    """Ranked retrieval evidence returned to an Agent or CLI user."""

    query: str = Field(min_length=1)
    model_name: str
    hits: list[KnowledgeSearchHit]


class RelevantKnowledgeTarget(BaseModel):
    """One manually labelled relevant chunk target for retrieval evaluation."""

    source: str = Field(min_length=1)
    section: str = Field(min_length=1)
    text_contains: str | None = Field(default=None, min_length=1)
    relevance: int = Field(default=1, ge=1, le=3)


class RetrievalEvaluationCase(BaseModel):
    """One offline query with one or more graded relevant targets."""

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    query: str = Field(min_length=1)
    relevant_targets: list[RelevantKnowledgeTarget] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_targets(self) -> "RetrievalEvaluationCase":
        """Prevent duplicated gold labels from inflating evaluation metrics."""
        identifiers = [
            (target.source, target.section, target.text_contains)
            for target in self.relevant_targets
        ]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Retrieval relevant targets must be unique.")
        return self


class RetrievalCaseResult(BaseModel):
    """Per-query ranking outcome for an offline retrieval evaluation."""

    case_id: str
    relevant_target_count: int = Field(ge=1)
    retrieved_relevant_count: int = Field(ge=0)
    first_relevant_rank: int | None = Field(default=None, ge=1)
    passed: bool
    precision_at_k: float = Field(ge=0, le=1)
    recall_at_k: float = Field(ge=0, le=1)
    reciprocal_rank: float = Field(ge=0, le=1)
    ndcg_at_k: float = Field(ge=0, le=1)


class RetrievalEvaluationResult(BaseModel):
    """Aggregate coverage and ranking metrics for a retrieval test set."""

    top_k: int = Field(ge=1)
    case_count: int = Field(ge=1)
    hit_rate_at_k: float = Field(ge=0, le=1)
    mean_precision_at_k: float = Field(ge=0, le=1)
    mean_recall_at_k: float = Field(ge=0, le=1)
    mean_reciprocal_rank: float = Field(ge=0, le=1)
    mean_ndcg_at_k: float = Field(ge=0, le=1)
    cases: list[RetrievalCaseResult] = Field(min_length=1)


class ChunkingExperimentVariant(BaseModel):
    """One character-based chunk size and overlap combination."""

    chunk_size: int = Field(ge=100)
    chunk_overlap: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_overlap(self) -> "ChunkingExperimentVariant":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be below chunk_size.")
        return self

    @property
    def label(self) -> str:
        return f"chars_{self.chunk_size}_overlap_{self.chunk_overlap}"


class ChunkingExperimentRun(BaseModel):
    """Build characteristics and retrieval metrics for one variant."""

    variant: ChunkingExperimentVariant
    index_path: str
    document_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    mean_chunk_characters: float = Field(gt=0)
    max_chunk_characters: int = Field(ge=1)
    index_size_bytes: int = Field(ge=1)
    build_duration_ms: float = Field(ge=0)
    evaluation_duration_ms: float = Field(ge=0)
    evaluation: RetrievalEvaluationResult


class ChunkingExperimentResult(BaseModel):
    """Comparable runs produced under a shared corpus and embedding model."""

    model_name: str = Field(min_length=1)
    top_k: int = Field(ge=1)
    case_count: int = Field(ge=1)
    sources: list[str] = Field(min_length=1)
    runs: list[ChunkingExperimentRun] = Field(min_length=2)
