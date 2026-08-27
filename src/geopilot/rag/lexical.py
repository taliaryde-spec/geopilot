"""Transparent BM25 keyword retrieval for small Chinese GIS knowledge bases."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from math import isfinite, log

from geopilot.rag.models import IndexedKnowledgeChunk

DEFAULT_BM25_K1 = 1.5
DEFAULT_BM25_B = 0.75

_TOKEN_PATTERN = re.compile(
    r"[a-z0-9_]+(?:[:./+-][a-z0-9_]+)*|[\u3400-\u4dbf\u4e00-\u9fff]+",
    re.IGNORECASE,
)
_CHINESE_PATTERN = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")


def tokenize_for_bm25(text: str) -> list[str]:
    """Tokenize identifiers and Chinese bigrams without external dictionaries."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        value = match.group(0)
        if _CHINESE_PATTERN.fullmatch(value) is None:
            tokens.append(value)
            continue
        if len(value) == 1:
            tokens.append(value)
            continue
        tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
    return tokens


@dataclass(frozen=True, slots=True)
class BM25SearchHit:
    """One lexical candidate before result fusion."""

    chunk_id: str
    score: float
    rank: int


class BM25Index:
    """In-memory BM25 index suitable for GeoPilot's small local corpus."""

    def __init__(
        self,
        chunks: list[IndexedKnowledgeChunk],
        *,
        k1: float = DEFAULT_BM25_K1,
        b: float = DEFAULT_BM25_B,
    ) -> None:
        if not chunks:
            raise ValueError("BM25 index requires at least one knowledge chunk.")
        if not isfinite(k1) or k1 <= 0:
            raise ValueError("BM25 k1 must be a positive finite number.")
        if not isfinite(b) or not 0 <= b <= 1:
            raise ValueError("BM25 b must be between 0 and 1.")

        self._chunks = chunks
        self._k1 = k1
        self._b = b
        self._term_frequencies = [
            Counter(tokenize_for_bm25(chunk.embedding_text)) for chunk in chunks
        ]
        self._document_lengths = [
            sum(frequencies.values()) for frequencies in self._term_frequencies
        ]
        self._average_document_length = sum(self._document_lengths) / len(chunks)
        self._document_frequencies: Counter[str] = Counter()
        for frequencies in self._term_frequencies:
            self._document_frequencies.update(frequencies.keys())

    def search(self, query: str, *, top_k: int) -> list[BM25SearchHit]:
        """Return positive-score BM25 candidates in deterministic rank order."""
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("BM25 query must not be empty.")
        if top_k < 1:
            raise ValueError("BM25 top_k must be positive.")
        query_terms = set(tokenize_for_bm25(cleaned_query))
        if not query_terms:
            return []

        scores: list[tuple[float, str]] = []
        document_count = len(self._chunks)
        for chunk, frequencies, document_length in zip(
            self._chunks,
            self._term_frequencies,
            self._document_lengths,
            strict=True,
        ):
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if frequency == 0:
                    continue
                document_frequency = self._document_frequencies[term]
                inverse_document_frequency = log(
                    1
                    + (document_count - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                length_normalization = (
                    1
                    - self._b
                    + self._b
                    * (
                        document_length / self._average_document_length
                        if self._average_document_length > 0
                        else 0.0
                    )
                )
                score += (
                    inverse_document_frequency
                    * (frequency * (self._k1 + 1))
                    / (frequency + self._k1 * length_normalization)
                )
            if score > 0:
                scores.append((score, chunk.chunk_id))

        scores.sort(key=lambda item: (-item[0], item[1]))
        return [
            BM25SearchHit(chunk_id=chunk_id, score=score, rank=rank)
            for rank, (score, chunk_id) in enumerate(scores[:top_k], start=1)
        ]
