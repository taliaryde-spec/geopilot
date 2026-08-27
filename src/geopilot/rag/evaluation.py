"""Offline retrieval evaluation with coverage and ranking metrics."""

from math import log2
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from geopilot.rag.models import (
    KnowledgeSearchHit,
    RelevantKnowledgeTarget,
    RetrievalCaseResult,
    RetrievalEvaluationCase,
    RetrievalEvaluationResult,
)
from geopilot.rag.service import KnowledgeRetriever


def _target_matches_hit(
    target: RelevantKnowledgeTarget,
    hit: KnowledgeSearchHit,
) -> bool:
    return (
        target.source in hit.source
        and target.section in hit.section
        and (target.text_contains is None or target.text_contains in hit.text)
    )


def _ranked_relevances(
    hits: list[KnowledgeSearchHit],
    targets: list[RelevantKnowledgeTarget],
) -> list[int]:
    """Assign each gold target to at most one ranked hit."""
    unmatched = set(range(len(targets)))
    relevances: list[int] = []
    for hit in hits:
        matches = [
            index for index in unmatched if _target_matches_hit(targets[index], hit)
        ]
        if not matches:
            relevances.append(0)
            continue
        selected = max(matches, key=lambda index: targets[index].relevance)
        unmatched.remove(selected)
        relevances.append(targets[selected].relevance)
    return relevances


def _discounted_cumulative_gain(relevances: list[int]) -> float:
    return sum(
        ((2**relevance) - 1) / log2(rank + 1)
        for rank, relevance in enumerate(relevances, start=1)
    )


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
    precision_total = 0.0
    recall_total = 0.0
    ndcg_total = 0.0
    hit_count = 0
    for case in cases:
        result = retriever.search(case.query, top_k=top_k)
        relevances = _ranked_relevances(result.hits, case.relevant_targets)
        first_rank = next(
            (
                rank
                for rank, relevance in enumerate(relevances, start=1)
                if relevance > 0
            ),
            None,
        )
        passed = first_rank is not None
        retrieved_relevant_count = sum(relevance > 0 for relevance in relevances)
        precision_at_k = retrieved_relevant_count / top_k
        recall_at_k = retrieved_relevant_count / len(case.relevant_targets)
        reciprocal_rank = 1 / first_rank if first_rank is not None else 0.0
        ideal_relevances = sorted(
            (target.relevance for target in case.relevant_targets),
            reverse=True,
        )[:top_k]
        ideal_dcg = _discounted_cumulative_gain(ideal_relevances)
        ndcg_at_k = min(
            1.0,
            _discounted_cumulative_gain(relevances) / ideal_dcg
            if ideal_dcg > 0
            else 0.0,
        )
        if passed:
            hit_count += 1
        reciprocal_rank_total += reciprocal_rank
        precision_total += precision_at_k
        recall_total += recall_at_k
        ndcg_total += ndcg_at_k
        case_results.append(
            RetrievalCaseResult(
                case_id=case.case_id,
                relevant_target_count=len(case.relevant_targets),
                retrieved_relevant_count=retrieved_relevant_count,
                first_relevant_rank=first_rank,
                passed=passed,
                precision_at_k=precision_at_k,
                recall_at_k=recall_at_k,
                reciprocal_rank=reciprocal_rank,
                ndcg_at_k=ndcg_at_k,
            )
        )
    case_count = len(cases)
    return RetrievalEvaluationResult(
        top_k=top_k,
        case_count=case_count,
        hit_rate_at_k=hit_count / case_count,
        mean_precision_at_k=precision_total / case_count,
        mean_recall_at_k=recall_total / case_count,
        mean_reciprocal_rank=reciprocal_rank_total / case_count,
        mean_ndcg_at_k=ndcg_total / case_count,
        cases=case_results,
    )
