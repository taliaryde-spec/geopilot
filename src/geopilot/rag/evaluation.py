"""Offline retrieval evaluation with hit rate and reciprocal rank."""

from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from geopilot.rag.models import (
    RetrievalCaseResult,
    RetrievalEvaluationCase,
    RetrievalEvaluationResult,
)
from geopilot.rag.service import KnowledgeRetriever


def load_evaluation_cases(source: str | Path) -> list[RetrievalEvaluationCase]:
    """Load a JSON array of retrieval queries and expected sources."""
    path = Path(source).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Retrieval evaluation file does not exist: {path}")
    try:
        return TypeAdapter(list[RetrievalEvaluationCase]).validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise ValueError(f"Retrieval evaluation file is invalid: {path}") from error


def evaluate_retrieval(
    retriever: KnowledgeRetriever,
    cases: list[RetrievalEvaluationCase],
    *,
    top_k: int = 4,
) -> RetrievalEvaluationResult:
    """Measure whether expected sources occur and how highly they rank."""
    if not cases:
        raise ValueError("At least one retrieval evaluation case is required.")
    case_results: list[RetrievalCaseResult] = []
    reciprocal_rank_total = 0.0
    hit_count = 0
    for case in cases:
        result = retriever.search(case.query, top_k=top_k)
        first_rank = next(
            (
                rank
                for rank, hit in enumerate(result.hits, start=1)
                if case.expected_source in hit.source
                and case.expected_section in hit.section
            ),
            None,
        )
        passed = first_rank is not None
        if first_rank is not None:
            hit_count += 1
            reciprocal_rank_total += 1 / first_rank
        case_results.append(
            RetrievalCaseResult(
                case_id=case.case_id,
                expected_source=case.expected_source,
                expected_section=case.expected_section,
                first_relevant_rank=first_rank,
                passed=passed,
            )
        )
    case_count = len(cases)
    return RetrievalEvaluationResult(
        top_k=top_k,
        case_count=case_count,
        hit_rate_at_k=hit_count / case_count,
        mean_reciprocal_rank=reciprocal_rank_total / case_count,
        cases=case_results,
    )
