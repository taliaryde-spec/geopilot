"""Tests for GeoPilot's citation-aware local RAG pipeline."""

import json
from math import log2
from pathlib import Path

import pytest

from geopilot.rag.chunker import chunk_knowledge_documents
from geopilot.rag.embeddings import EmbeddingError, EmbeddingErrorCode
from geopilot.rag.evaluation import evaluate_retrieval, load_evaluation_cases
from geopilot.rag.experiment import run_chunking_experiment
from geopilot.rag.lexical import BM25Index, tokenize_for_bm25
from geopilot.rag.loader import load_knowledge_document, load_knowledge_documents
from geopilot.rag.models import (
    ChunkingExperimentVariant,
    RelevantKnowledgeTarget,
    RetrievalEvaluationCase,
    RetrievalMode,
)
from geopilot.rag.rerank_experiment import run_rerank_experiment
from geopilot.rag.reranking import (
    FastEmbedReranker,
    RerankerError,
    RerankerErrorCode,
)
from geopilot.rag.retrieval_experiment import run_retrieval_experiment
from geopilot.rag.service import (
    KnowledgeRetriever,
    build_knowledge_index,
    open_knowledge_retriever,
)
from geopilot.rag.tokenization import summarize_token_usage
from geopilot.rag.vector_store import (
    LocalVectorStore,
    VectorStoreError,
    VectorStoreErrorCode,
)


class KeywordEmbeddingProvider:
    """Small deterministic embedding provider used instead of a model download."""

    def __init__(self, model_name: str = "test-keywords-v1") -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._embed(query)

    @property
    def max_input_tokens(self) -> int:
        return 512

    def count_tokens(self, texts: list[str]) -> list[int]:
        return [len(text) for text in texts]

    @staticmethod
    def _embed(text: str) -> list[float]:
        if any(token in text for token in ("CRS", "投影", "EPSG:4326", "缓冲")):
            return [1.0, 0.0, 0.0]
        if any(token in text for token in ("capacity", "字段", "人口")):
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


class MisleadingEmbeddingProvider(KeywordEmbeddingProvider):
    """Ranks generic text above an exact identifier to test lexical recovery."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            [0.0, 1.0] if "service_radius_m" in text else [1.0, 0.0] for text in texts
        ]

    def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0]


class KeywordReranker:
    """Deterministic Cross-Encoder substitute used without a model download."""

    def __init__(self, preferred_text: str) -> None:
        self.preferred_text = preferred_text
        self.scored_document_counts: list[int] = []

    @property
    def model_name(self) -> str:
        return "test-reranker-v1"

    def score(self, query: str, documents: list[str]) -> list[float]:
        self.scored_document_counts.append(len(documents))
        return [
            2.0 if self.preferred_text in document else -1.0 for document in documents
        ]


def _write_knowledge_files(directory: Path) -> tuple[Path, Path]:
    crs_path = directory / "crs.md"
    crs_path.write_text(
        "# 坐标参考系\n\n## 距离分析\n\n"
        "EPSG:4326 使用角度，米制缓冲前必须转换到合适的投影 CRS。\n",
        encoding="utf-8",
    )
    dictionary_path = directory / "dictionary.md"
    dictionary_path.write_text(
        "# 数据字典\n\n## capacity 字段\n\n"
        "capacity 表示设施容量，population 表示社区人口。\n",
        encoding="utf-8",
    )
    return crs_path, dictionary_path


def test_loader_and_chunker_preserve_structure_and_stable_citations(
    tmp_path: Path,
) -> None:
    crs_path, _ = _write_knowledge_files(tmp_path)

    document = load_knowledge_document(crs_path, working_directory=tmp_path)
    repeated = load_knowledge_document(crs_path, working_directory=tmp_path)
    chunks = chunk_knowledge_documents([document])

    assert document.title == "坐标参考系"
    assert document.source == "crs.md"
    assert document.document_id == repeated.document_id
    assert len(document.checksum) == 64
    assert [chunk.section for chunk in chunks] == ["坐标参考系 > 距离分析"]
    assert chunks[0].citation == "crs.md#坐标参考系 > 距离分析 [chunk:1]"
    assert chunks[0].chunk_id.startswith("chunk_")
    assert "坐标参考系\n坐标参考系 > 距离分析" in chunks[0].embedding_text


def test_directory_loader_is_recursive_sorted_and_ignores_json(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "z.md").write_text("# Z\n\n内容", encoding="utf-8")
    (nested / "a.txt").write_text("A 文本", encoding="utf-8")
    (tmp_path / "ignored.json").write_text("{}", encoding="utf-8")

    documents = load_knowledge_documents([tmp_path], working_directory=tmp_path)

    assert [document.source for document in documents] == ["nested/a.txt", "z.md"]


def test_build_search_persist_and_reopen_local_vector_index(tmp_path: Path) -> None:
    _write_knowledge_files(tmp_path)
    index_path = tmp_path / "index.json"
    provider = KeywordEmbeddingProvider()

    build_result = build_knowledge_index(
        [tmp_path],
        index_path=index_path,
        embedding_provider=provider,
        working_directory=tmp_path,
    )
    retriever = open_knowledge_retriever(
        index_path=index_path,
        embedding_provider=provider,
    )
    result = retriever.search("为何缓冲前需要投影 CRS？", top_k=1)
    stored_payload = json.loads(index_path.read_text(encoding="utf-8"))

    assert build_result.document_count == 2
    assert build_result.chunk_count == 2
    assert build_result.dimension == 3
    assert build_result.sources == ["crs.md", "dictionary.md"]
    assert build_result.token_usage is not None
    assert build_result.token_usage.over_limit_chunk_count == 0
    assert stored_payload["manifest"]["model_name"] == provider.model_name
    assert result.hits[0].source == "crs.md"
    assert result.hits[0].score == pytest.approx(1.0)
    assert result.hits[0].citation == "crs.md#坐标参考系 > 距离分析 [chunk:1]"


def test_search_rejects_embedding_model_mismatch(tmp_path: Path) -> None:
    crs_path, _ = _write_knowledge_files(tmp_path)
    document = load_knowledge_document(crs_path, working_directory=tmp_path)
    chunks = chunk_knowledge_documents([document])
    index_path = tmp_path / "index.json"
    LocalVectorStore(index_path, KeywordEmbeddingProvider()).build(chunks)
    mismatched_store = LocalVectorStore(
        index_path,
        KeywordEmbeddingProvider("other-model"),
    )

    with pytest.raises(VectorStoreError) as captured:
        mismatched_store.search("投影 CRS")

    assert captured.value.code is VectorStoreErrorCode.MODEL_MISMATCH


def test_bm25_tokenizer_preserves_identifiers_and_chinese_bigrams() -> None:
    tokens = tokenize_for_bm25("EPSG:4326 与 service_radius_m 服务半径")

    assert "epsg:4326" in tokens
    assert "service_radius_m" in tokens
    assert "服务" in tokens
    assert "务半" in tokens
    assert "半径" in tokens


def test_hybrid_search_recovers_exact_identifier_missed_by_dense(
    tmp_path: Path,
) -> None:
    (tmp_path / "generic.md").write_text(
        "# 通用说明\n\n## 设施分析\n\n设施分析的一般背景信息。",
        encoding="utf-8",
    )
    (tmp_path / "fields.md").write_text(
        "# 数据字典\n\n## 服务半径\n\nservice_radius_m 表示设施服务半径。",
        encoding="utf-8",
    )
    index_path = tmp_path / "index.json"
    provider = MisleadingEmbeddingProvider()
    build_knowledge_index(
        [tmp_path],
        index_path=index_path,
        embedding_provider=provider,
        working_directory=tmp_path,
    )

    dense = open_knowledge_retriever(
        index_path=index_path,
        embedding_provider=provider,
        retrieval_mode=RetrievalMode.DENSE,
    ).search("service_radius_m 字段是什么？", top_k=1)
    hybrid = open_knowledge_retriever(
        index_path=index_path,
        embedding_provider=provider,
        retrieval_mode=RetrievalMode.HYBRID,
        hybrid_candidate_k=2,
    ).search("service_radius_m 字段是什么？", top_k=1)

    assert dense.hits[0].source == "generic.md"
    assert hybrid.retrieval_mode is RetrievalMode.HYBRID
    assert hybrid.hits[0].source == "fields.md"
    assert hybrid.hits[0].dense_rank == 2
    assert hybrid.hits[0].bm25_rank == 1
    assert hybrid.hits[0].bm25_score is not None


def test_rerank_search_reorders_bounded_hybrid_candidates(tmp_path: Path) -> None:
    (tmp_path / "generic.md").write_text(
        "# 通用说明\n\n## 设施分析\n\n设施分析的一般背景信息。",
        encoding="utf-8",
    )
    (tmp_path / "fields.md").write_text(
        "# 数据字典\n\n## 服务半径\n\nservice_radius_m 表示设施服务半径。",
        encoding="utf-8",
    )
    index_path = tmp_path / "index.json"
    provider = MisleadingEmbeddingProvider()
    build_knowledge_index(
        [tmp_path],
        index_path=index_path,
        embedding_provider=provider,
        working_directory=tmp_path,
    )
    reranker = KeywordReranker("一般背景信息")

    result = open_knowledge_retriever(
        index_path=index_path,
        embedding_provider=provider,
        retrieval_mode=RetrievalMode.HYBRID_RERANK,
        hybrid_candidate_k=2,
        reranker=reranker,
        rerank_candidate_k=2,
    ).search("service_radius_m 字段是什么？", top_k=1)

    assert result.retrieval_mode is RetrievalMode.HYBRID_RERANK
    assert result.reranker_model_name == "test-reranker-v1"
    assert result.hits[0].source == "generic.md"
    assert result.hits[0].score == 2.0
    assert result.hits[0].rerank_score == 2.0
    assert result.hits[0].rerank_rank == 1
    assert result.hits[0].dense_rank is not None
    assert reranker.scored_document_counts == [2]


def test_hybrid_rerank_mode_requires_a_reranker(tmp_path: Path) -> None:
    _write_knowledge_files(tmp_path)
    index_path = tmp_path / "index.json"
    provider = KeywordEmbeddingProvider()
    build_knowledge_index(
        [tmp_path],
        index_path=index_path,
        embedding_provider=provider,
        working_directory=tmp_path,
    )

    with pytest.raises(ValueError, match="requires a reranker"):
        KnowledgeRetriever(
            LocalVectorStore(index_path, provider),
            retrieval_mode=RetrievalMode.HYBRID_RERANK,
        )


def test_fastembed_reranker_validates_input_and_output_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WrongCountModel:
        def rerank(self, query: str, documents: list[str]) -> list[float]:
            return [1.0]

    reranker = FastEmbedReranker("test-reranker")

    with pytest.raises(RerankerError) as empty_input:
        reranker.score("", ["candidate"])
    assert empty_input.value.code is RerankerErrorCode.EMPTY_INPUT

    monkeypatch.setattr(reranker, "_get_model", lambda: WrongCountModel())
    with pytest.raises(RerankerError) as wrong_count:
        reranker.score("query", ["first", "second"])
    assert wrong_count.value.code is RerankerErrorCode.RESULT_COUNT_MISMATCH


def test_fastembed_reranker_rejects_non_finite_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidScoreModel:
        def rerank(self, query: str, documents: list[str]) -> list[float]:
            return [float("nan")]

    reranker = FastEmbedReranker("test-reranker")
    monkeypatch.setattr(reranker, "_get_model", lambda: InvalidScoreModel())

    with pytest.raises(RerankerError) as captured:
        reranker.score("query", ["candidate"])

    assert captured.value.code is RerankerErrorCode.INVALID_SCORE


def test_bm25_scores_exact_identifier_above_unmatched_chunk(tmp_path: Path) -> None:
    (tmp_path / "generic.md").write_text("# 通用\n\n普通信息", encoding="utf-8")
    (tmp_path / "fields.md").write_text(
        "# 字段\n\nservice_radius_m 表示服务半径。",
        encoding="utf-8",
    )
    index_path = tmp_path / "index.json"
    provider = KeywordEmbeddingProvider()
    build_knowledge_index(
        [tmp_path],
        index_path=index_path,
        embedding_provider=provider,
        working_directory=tmp_path,
    )
    stored = LocalVectorStore(index_path, provider).load()

    hits = BM25Index(stored.chunks).search("service_radius_m", top_k=2)

    assert len(hits) == 1
    assert (
        next(
            chunk.source
            for chunk in stored.chunks
            if chunk.chunk_id == hits[0].chunk_id
        )
        == "fields.md"
    )


def test_index_build_rejects_embedding_inputs_above_token_limit(
    tmp_path: Path,
) -> None:
    knowledge_path = tmp_path / "long.md"
    knowledge_path.write_text(
        "# 长文档\n\n## 超长章节\n\n" + ("投影坐标系。" * 120),
        encoding="utf-8",
    )

    with pytest.raises(EmbeddingError) as captured:
        build_knowledge_index(
            [knowledge_path],
            index_path=tmp_path / "index.json",
            chunk_size=900,
            chunk_overlap=120,
            embedding_provider=KeywordEmbeddingProvider(),
            working_directory=tmp_path,
        )

    assert captured.value.code is EmbeddingErrorCode.INPUT_TOKEN_LIMIT_EXCEEDED
    assert not (tmp_path / "index.json").exists()


def test_retrieval_evaluation_calculates_ranking_metrics(tmp_path: Path) -> None:
    _write_knowledge_files(tmp_path)
    index_path = tmp_path / "index.json"
    provider = KeywordEmbeddingProvider()
    build_knowledge_index(
        [tmp_path],
        index_path=index_path,
        embedding_provider=provider,
        working_directory=tmp_path,
    )
    retriever = KnowledgeRetriever(
        LocalVectorStore(index_path, provider),
        retrieval_mode=RetrievalMode.DENSE,
    )
    cases = [
        RetrievalEvaluationCase(
            case_id="metric_crs",
            query="米制缓冲为什么需要投影？",
            relevant_targets=[
                RelevantKnowledgeTarget(
                    source="crs.md",
                    section="距离分析",
                    text_contains="EPSG:4326",
                    relevance=3,
                )
            ],
        ),
        RetrievalEvaluationCase(
            case_id="capacity_field",
            query="capacity 字段是什么？",
            relevant_targets=[
                RelevantKnowledgeTarget(
                    source="dictionary.md",
                    section="capacity 字段",
                    text_contains="capacity",
                    relevance=3,
                )
            ],
        ),
    ]

    result = evaluate_retrieval(retriever, cases, top_k=1)

    assert result.case_count == 2
    assert result.hit_rate_at_k == 1.0
    assert result.mean_precision_at_k == 1.0
    assert result.mean_recall_at_k == 1.0
    assert result.mean_reciprocal_rank == 1.0
    assert result.mean_ndcg_at_k == 1.0
    assert all(case.first_relevant_rank == 1 for case in result.cases)


def test_retrieval_evaluation_discounts_a_rank_two_result(tmp_path: Path) -> None:
    _write_knowledge_files(tmp_path)
    index_path = tmp_path / "index.json"
    provider = KeywordEmbeddingProvider()
    build_knowledge_index(
        [tmp_path],
        index_path=index_path,
        embedding_provider=provider,
        working_directory=tmp_path,
    )
    retriever = KnowledgeRetriever(
        LocalVectorStore(index_path, provider),
        retrieval_mode=RetrievalMode.DENSE,
    )
    query = "没有关键词的查询"
    expected_hit = retriever.search(query, top_k=2).hits[1]
    cases = [
        RetrievalEvaluationCase(
            case_id="rank_two",
            query=query,
            relevant_targets=[
                RelevantKnowledgeTarget(
                    source=expected_hit.source,
                    section=expected_hit.section,
                    text_contains=expected_hit.text,
                    relevance=3,
                )
            ],
        )
    ]

    result = evaluate_retrieval(retriever, cases, top_k=2)
    case = result.cases[0]

    assert case.first_relevant_rank == 2
    assert case.precision_at_k == 0.5
    assert case.recall_at_k == 1.0
    assert case.reciprocal_rank == 0.5
    assert case.ndcg_at_k == pytest.approx(1 / log2(3))


def test_retrieval_evaluation_uses_graded_relevance_for_ndcg(tmp_path: Path) -> None:
    _write_knowledge_files(tmp_path)
    index_path = tmp_path / "index.json"
    provider = KeywordEmbeddingProvider()
    build_knowledge_index(
        [tmp_path],
        index_path=index_path,
        embedding_provider=provider,
        working_directory=tmp_path,
    )
    retriever = KnowledgeRetriever(
        LocalVectorStore(index_path, provider),
        retrieval_mode=RetrievalMode.DENSE,
    )
    query = "没有关键词的查询"
    ranked_hits = retriever.search(query, top_k=2).hits
    cases = [
        RetrievalEvaluationCase(
            case_id="graded_relevance",
            query=query,
            relevant_targets=[
                RelevantKnowledgeTarget(
                    source=ranked_hits[0].source,
                    section=ranked_hits[0].section,
                    text_contains=ranked_hits[0].text,
                    relevance=1,
                ),
                RelevantKnowledgeTarget(
                    source=ranked_hits[1].source,
                    section=ranked_hits[1].section,
                    text_contains=ranked_hits[1].text,
                    relevance=3,
                ),
            ],
        )
    ]

    result = evaluate_retrieval(retriever, cases, top_k=2)

    actual_dcg = 1 + (7 / log2(3))
    ideal_dcg = 7 + (1 / log2(3))
    assert result.cases[0].ndcg_at_k == pytest.approx(actual_dcg / ideal_dcg)
    assert result.cases[0].precision_at_k == 1.0
    assert result.cases[0].recall_at_k == 1.0


def test_load_evaluation_cases_validates_json(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            [
                {
                    "case_id": "crs",
                    "query": "如何投影？",
                    "relevant_targets": [
                        {
                            "source": "crs.md",
                            "section": "距离分析",
                            "text_contains": "EPSG:4326",
                            "relevance": 3,
                        }
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cases = load_evaluation_cases(cases_path)

    assert cases[0].case_id == "crs"
    assert cases[0].relevant_targets[0].source == "crs.md"
    assert cases[0].relevant_targets[0].section == "距离分析"


def test_chunking_experiment_compares_variants_under_shared_settings(
    tmp_path: Path,
) -> None:
    knowledge_path = tmp_path / "long_guideline.md"
    knowledge_path.write_text(
        "# 长文档\n\n## 投影规则\n\n" + ("距离分析必须使用米制 CRS。" * 60),
        encoding="utf-8",
    )
    cases = [
        RetrievalEvaluationCase(
            case_id="metric_crs",
            query="距离分析使用什么坐标系？",
            relevant_targets=[
                RelevantKnowledgeTarget(
                    source="long_guideline.md",
                    section="投影规则",
                    relevance=3,
                )
            ],
        )
    ]
    variants = [
        ChunkingExperimentVariant(chunk_size=120, chunk_overlap=20),
        ChunkingExperimentVariant(chunk_size=300, chunk_overlap=50),
    ]

    result = run_chunking_experiment(
        [knowledge_path],
        cases,
        variants=variants,
        output_directory=tmp_path / "experiment",
        embedding_provider=KeywordEmbeddingProvider(),
        working_directory=tmp_path,
        top_k=1,
    )

    assert result.model_name == "test-keywords-v1"
    assert result.case_count == 1
    assert len(result.runs) == 2
    assert result.runs[0].chunk_count > result.runs[1].chunk_count
    assert result.runs[0].max_chunk_characters <= 120
    assert result.runs[1].max_chunk_characters <= 300
    assert result.runs[0].token_usage.model_max_input_tokens == 512
    assert result.runs[0].token_usage.max_embedding_tokens > 0
    assert result.runs[0].token_usage.over_limit_chunk_count == 0
    assert all(run.evaluation.mean_recall_at_k == 1.0 for run in result.runs)
    assert all(Path(run.index_path).is_file() for run in result.runs)


def test_chunking_experiment_rejects_duplicate_variants(tmp_path: Path) -> None:
    knowledge_path = tmp_path / "knowledge.md"
    knowledge_path.write_text("# 知识\n\n有效正文", encoding="utf-8")
    variant = ChunkingExperimentVariant(chunk_size=300, chunk_overlap=50)

    with pytest.raises(ValueError, match="must be unique"):
        run_chunking_experiment(
            [knowledge_path],
            [
                RetrievalEvaluationCase(
                    case_id="knowledge",
                    query="正文是什么？",
                    relevant_targets=[
                        RelevantKnowledgeTarget(
                            source="knowledge.md",
                            section="知识",
                        )
                    ],
                )
            ],
            variants=[variant, variant],
            output_directory=tmp_path / "experiment",
            embedding_provider=KeywordEmbeddingProvider(),
            working_directory=tmp_path,
        )


def test_token_usage_statistics_count_pre_truncation_risk() -> None:
    provider = KeywordEmbeddingProvider()

    statistics = summarize_token_usage(
        ["a" * 100, "b" * 410, "c" * 513],
        provider,
    )

    assert statistics.model_max_input_tokens == 512
    assert statistics.warning_threshold_tokens == 410
    assert statistics.mean_embedding_tokens == pytest.approx(341.0)
    assert statistics.p95_embedding_tokens == 513
    assert statistics.max_embedding_tokens == 513
    assert statistics.max_input_utilization == pytest.approx(513 / 512)
    assert statistics.warning_chunk_count == 2
    assert statistics.over_limit_chunk_count == 1


def test_chunking_experiment_rejects_mismatched_tokenizer_model(
    tmp_path: Path,
) -> None:
    knowledge_path = tmp_path / "knowledge.md"
    knowledge_path.write_text("# 知识\n\n有效正文", encoding="utf-8")

    with pytest.raises(ValueError, match="must match"):
        run_chunking_experiment(
            [knowledge_path],
            [
                RetrievalEvaluationCase(
                    case_id="knowledge",
                    query="正文是什么？",
                    relevant_targets=[
                        RelevantKnowledgeTarget(source="knowledge.md", section="知识")
                    ],
                )
            ],
            variants=[
                ChunkingExperimentVariant(chunk_size=300, chunk_overlap=50),
                ChunkingExperimentVariant(chunk_size=500, chunk_overlap=80),
            ],
            output_directory=tmp_path / "experiment",
            embedding_provider=KeywordEmbeddingProvider(),
            token_counter=KeywordEmbeddingProvider("other-model"),
            working_directory=tmp_path,
        )


def test_retrieval_experiment_compares_dense_and_hybrid(tmp_path: Path) -> None:
    (tmp_path / "generic.md").write_text(
        "# 通用\n\n普通设施说明。",
        encoding="utf-8",
    )
    (tmp_path / "fields.md").write_text(
        "# 字段\n\nservice_radius_m 表示设施服务半径。",
        encoding="utf-8",
    )
    index_path = tmp_path / "index.json"
    provider = MisleadingEmbeddingProvider()
    build_knowledge_index(
        [tmp_path],
        index_path=index_path,
        embedding_provider=provider,
        working_directory=tmp_path,
    )
    cases = [
        RetrievalEvaluationCase(
            case_id="service_radius",
            query="service_radius_m 字段是什么？",
            relevant_targets=[
                RelevantKnowledgeTarget(source="fields.md", section="字段")
            ],
        )
    ]

    result = run_retrieval_experiment(
        index_path,
        cases,
        embedding_provider=provider,
        top_k=1,
        hybrid_candidate_k=2,
    )

    assert [run.retrieval_mode for run in result.runs] == [
        RetrievalMode.DENSE,
        RetrievalMode.HYBRID,
    ]
    assert result.runs[0].evaluation.mean_recall_at_k == 0.0
    assert result.runs[1].evaluation.mean_recall_at_k == 1.0
    assert result.recall_delta == 1.0
    assert result.improved_case_count == 1
    assert result.regressed_case_count == 0
    assert result.unchanged_case_count == 0


def test_rerank_experiment_compares_shared_hybrid_candidates(tmp_path: Path) -> None:
    _write_knowledge_files(tmp_path)
    index_path = tmp_path / "index.json"
    provider = KeywordEmbeddingProvider()
    build_knowledge_index(
        [tmp_path],
        index_path=index_path,
        embedding_provider=provider,
        working_directory=tmp_path,
    )
    store = LocalVectorStore(index_path, provider)
    hybrid = KnowledgeRetriever(
        store,
        retrieval_mode=RetrievalMode.HYBRID,
        hybrid_candidate_k=2,
    ).search("无关键词查询", top_k=2)
    target = hybrid.hits[1]
    cases = [
        RetrievalEvaluationCase(
            case_id="rerank_second_candidate",
            query="无关键词查询",
            relevant_targets=[
                RelevantKnowledgeTarget(
                    source=target.source,
                    section=target.section,
                )
            ],
        )
    ]

    result = run_rerank_experiment(
        index_path,
        cases,
        embedding_provider=provider,
        reranker=KeywordReranker(target.title),
        top_k=1,
        hybrid_candidate_k=2,
        rerank_candidate_k=2,
    )

    assert [run.retrieval_mode for run in result.runs] == [
        RetrievalMode.HYBRID,
        RetrievalMode.HYBRID_RERANK,
    ]
    assert result.runs[0].evaluation.mean_recall_at_k == 0.0
    assert result.runs[1].evaluation.mean_recall_at_k == 1.0
    assert result.recall_delta == 1.0
    assert result.ndcg_delta == 1.0
    assert result.improved_case_count == 1
