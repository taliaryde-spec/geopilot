"""Deterministic Markdown-aware chunking for Chinese and English knowledge."""

import re
from dataclasses import dataclass
from hashlib import sha256

from geopilot.rag.models import KnowledgeChunk, KnowledgeDocument

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 80


@dataclass(frozen=True, slots=True)
class _Section:
    name: str
    text: str


def _markdown_sections(document: KnowledgeDocument) -> list[_Section]:
    if document.metadata.get("format") != "md":
        return [_Section(name=document.title, text=document.content)]

    sections: list[_Section] = []
    heading_stack: list[tuple[int, str]] = []
    current_name = document.title
    current_lines: list[str] = []

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(_Section(name=current_name, text=text))

    for line in document.content.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match is None:
            current_lines.append(line)
            continue
        flush()
        current_lines = []
        level = len(match.group(1))
        heading = match.group(2).strip()
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, heading))
        current_name = " > ".join(item[1] for item in heading_stack)
    flush()
    return sections or [_Section(name=document.title, text=document.content)]


def _choose_boundary(text: str, start: int, maximum_end: int) -> int:
    if maximum_end >= len(text):
        return len(text)
    minimum_end = start + int((maximum_end - start) * 0.6)
    for separator in ("\n\n", "\n", "。", "！", "？", ". ", "; ", "；"):
        position = text.rfind(separator, minimum_end, maximum_end)
        if position >= minimum_end:
            return position + len(separator)
    return maximum_end


def _split_section(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    normalized = re.sub(r"[ \t]+", " ", text).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        maximum_end = min(start + chunk_size, len(normalized))
        end = _choose_boundary(normalized, start, maximum_end)
        piece = normalized[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
        while start < len(normalized) and normalized[start].isspace():
            start += 1
    return chunks


def chunk_knowledge_documents(
    documents: list[KnowledgeDocument],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[KnowledgeChunk]:
    """Split documents by headings and bounded character windows."""
    if not documents:
        raise ValueError("At least one knowledge document is required.")
    if chunk_size < 100:
        raise ValueError("chunk_size must be at least 100 characters.")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and below chunk_size.")

    chunks: list[KnowledgeChunk] = []
    for document in documents:
        ordinal = 0
        for section in _markdown_sections(document):
            for text in _split_section(
                section.text,
                chunk_size=chunk_size,
                overlap=chunk_overlap,
            ):
                ordinal += 1
                digest = sha256(
                    f"{document.document_id}\0{section.name}\0{ordinal}\0{text}".encode()
                ).hexdigest()[:16]
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=f"chunk_{digest}",
                        document_id=document.document_id,
                        source=document.source,
                        title=document.title,
                        section=section.name,
                        ordinal=ordinal,
                        text=text,
                        metadata=document.metadata,
                    )
                )
    if not chunks:
        raise ValueError("Knowledge documents produced no non-empty chunks.")
    return chunks
