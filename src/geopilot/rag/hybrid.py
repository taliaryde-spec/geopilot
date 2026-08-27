"""Dense and BM25 retrieval fused with Reciprocal Rank Fusion."""

from geopilot.rag.lexical import BM25Index
from geopilot.rag.models import (
    IndexedKnowledgeChunk,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    RetrievalMode,
)
from geopilot.rag.vector_store import LocalVectorStore

DEFAULT_HYBRID_CANDIDATE_K = 12
DEFAULT_RRF_K = 60


class HybridSearcher:
    """Fuse dense and lexical candidate ranks without comparing raw scores."""

    def __init__(
        self,
        store: LocalVectorStore,
        *,
        candidate_k: int = DEFAULT_HYBRID_CANDIDATE_K,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        if candidate_k < 1 or candidate_k > 20:
            raise ValueError("Hybrid candidate_k must be between 1 and 20.")
        if rrf_k < 1:
            raise ValueError("RRF k must be positive.")
        self._store = store
        self._candidate_k = candidate_k
        self._rrf_k = rrf_k
        self._lexical_index: BM25Index | None = None
        self._chunks_by_id: dict[str, IndexedKnowledgeChunk] = {}

    def search(self, query: str, *, top_k: int) -> KnowledgeSearchResult:
        """Retrieve two candidate lists and return normalized RRF ranking."""
        if top_k < 1 or top_k > 20:
            raise ValueError("Hybrid top_k must be between 1 and 20.")
        candidate_k = min(20, max(top_k, self._candidate_k))
        dense_result = self._store.search(query, top_k=candidate_k)
        lexical_hits = self._get_lexical_index().search(query, top_k=candidate_k)

        dense_by_id = {hit.chunk_id: hit for hit in dense_result.hits}
        lexical_by_id = {hit.chunk_id: hit for hit in lexical_hits}
        candidate_ids = set(dense_by_id) | set(lexical_by_id)
        maximum_rrf_score = 2 / (self._rrf_k + 1)
        ranked: list[tuple[float, str]] = []
        for chunk_id in candidate_ids:
            dense_hit = dense_by_id.get(chunk_id)
            lexical_hit = lexical_by_id.get(chunk_id)
            raw_score = 0.0
            if dense_hit is not None and dense_hit.dense_rank is not None:
                raw_score += 1 / (self._rrf_k + dense_hit.dense_rank)
            if lexical_hit is not None:
                raw_score += 1 / (self._rrf_k + lexical_hit.rank)
            ranked.append((raw_score / maximum_rrf_score, chunk_id))
        ranked.sort(key=lambda item: (-item[0], item[1]))

        hits: list[KnowledgeSearchHit] = []
        for fused_score, chunk_id in ranked[:top_k]:
            chunk = self._chunks_by_id[chunk_id]
            dense_hit = dense_by_id.get(chunk_id)
            lexical_hit = lexical_by_id.get(chunk_id)
            hits.append(
                KnowledgeSearchHit(
                    chunk_id=chunk.chunk_id,
                    source=chunk.source,
                    title=chunk.title,
                    section=chunk.section,
                    citation=chunk.citation,
                    text=chunk.text,
                    score=min(1.0, fused_score),
                    dense_score=(
                        dense_hit.dense_score if dense_hit is not None else None
                    ),
                    bm25_score=(lexical_hit.score if lexical_hit is not None else None),
                    dense_rank=(
                        dense_hit.dense_rank if dense_hit is not None else None
                    ),
                    bm25_rank=(lexical_hit.rank if lexical_hit is not None else None),
                )
            )
        return KnowledgeSearchResult(
            query=dense_result.query,
            model_name=dense_result.model_name,
            retrieval_mode=RetrievalMode.HYBRID,
            hits=hits,
        )

    def _get_lexical_index(self) -> BM25Index:
        if self._lexical_index is None:
            stored_index = self._store.load()
            self._chunks_by_id = {
                chunk.chunk_id: chunk for chunk in stored_index.chunks
            }
            self._lexical_index = BM25Index(stored_index.chunks)
        return self._lexical_index
