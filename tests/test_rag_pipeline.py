"""Tests for GeoPilot's citation-aware local RAG pipeline."""

import json
from math import log2
from pathlib import Path

import pytest

from geopilot.rag.chunker import chunk_knowledge_documents
from geopilot.rag.evaluation import evaluate_retrieval, load_evaluation_cases
from geopilot.rag.experiment import run_chunking_experiment
from geopilot.rag.loader import load_knowledge_document, load_knowledge_documents
from geopilot.rag.models import (
    ChunkingExperimentVariant,
    RelevantKnowledgeTarget,
    RetrievalEvaluationCase,
)
from geopilot.rag.service import (
    KnowledgeRetriever,
    build_knowledge_index,
    open_knowledge_retriever,
)
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

    @staticmethod
    def _embed(text: str) -> list[float]:
        if any(token in text for token in ("CRS", "投影", "EPSG:4326", "缓冲")):
            return [1.0, 0.0, 0.0]
        if any(token in text for token in ("capacity", "字段", "人口")):
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


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
    retriever = KnowledgeRetriever(LocalVectorStore(index_path, provider))
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
    retriever = KnowledgeRetriever(LocalVectorStore(index_path, provider))
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
    retriever = KnowledgeRetriever(LocalVectorStore(index_path, provider))
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
