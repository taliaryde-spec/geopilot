"""Token-aware measurements for RAG embedding inputs."""

from math import ceil
from statistics import fmean

from geopilot.rag.embeddings import TokenCounter
from geopilot.rag.models import TokenUsageStatistics

DEFAULT_TOKEN_WARNING_RATIO = 0.8


def summarize_token_usage(
    texts: list[str],
    token_counter: TokenCounter,
    *,
    warning_threshold_ratio: float = DEFAULT_TOKEN_WARNING_RATIO,
) -> TokenUsageStatistics:
    """Measure untruncated token usage with the embedding model tokenizer."""
    if not texts:
        raise ValueError(
            "At least one embedding input is required for token statistics."
        )
    if not 0 < warning_threshold_ratio <= 1:
        raise ValueError("warning_threshold_ratio must be above 0 and at most 1.")

    counts = token_counter.count_tokens(texts)
    if len(counts) != len(texts):
        raise ValueError("Token count does not match embedding input count.")
    if any(count < 1 for count in counts):
        raise ValueError("Embedding token counts must be positive.")

    maximum = token_counter.max_input_tokens
    if maximum < 1:
        raise ValueError("Embedding model max_input_tokens must be positive.")
    warning_threshold = ceil(maximum * warning_threshold_ratio)
    ordered_counts = sorted(counts)
    p95_rank = max(1, ceil(len(ordered_counts) * 0.95))
    maximum_count = ordered_counts[-1]

    return TokenUsageStatistics(
        model_max_input_tokens=maximum,
        warning_threshold_ratio=warning_threshold_ratio,
        warning_threshold_tokens=warning_threshold,
        mean_embedding_tokens=fmean(counts),
        p95_embedding_tokens=ordered_counts[p95_rank - 1],
        max_embedding_tokens=maximum_count,
        max_input_utilization=maximum_count / maximum,
        warning_chunk_count=sum(count >= warning_threshold for count in counts),
        over_limit_chunk_count=sum(count > maximum for count in counts),
    )
