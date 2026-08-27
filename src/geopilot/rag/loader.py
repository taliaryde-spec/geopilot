"""Load local UTF-8 Markdown and text files into knowledge documents."""

import re
from collections.abc import Sequence
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from geopilot.rag.models import KnowledgeDocument

SUPPORTED_KNOWLEDGE_SUFFIXES = {".md", ".txt"}


class KnowledgeLoadErrorCode(StrEnum):
    """Stable identifiers for local knowledge ingestion failures."""

    SOURCE_NOT_FOUND = "knowledge_source_not_found"
    UNSUPPORTED_FORMAT = "unsupported_knowledge_format"
    EMPTY_DOCUMENT = "empty_knowledge_document"
    NO_SUPPORTED_DOCUMENTS = "no_supported_knowledge_documents"
    READ_ERROR = "knowledge_read_error"


class KnowledgeLoadError(ValueError):
    """Raised when a knowledge source cannot be loaded safely."""

    def __init__(self, code: KnowledgeLoadErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _source_label(path: Path, *, working_directory: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(working_directory.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _document_title(path: Path, content: str) -> str:
    if path.suffix.lower() == ".md":
        for line in content.splitlines():
            match = re.match(r"^#\s+(.+?)\s*$", line)
            if match:
                return match.group(1).strip()
    return path.stem.replace("_", " ").strip()


def load_knowledge_document(
    source: str | Path,
    *,
    working_directory: str | Path | None = None,
) -> KnowledgeDocument:
    """Load one supported file with a stable content-derived identifier."""
    path = Path(source).resolve()
    if not path.is_file():
        raise KnowledgeLoadError(
            KnowledgeLoadErrorCode.SOURCE_NOT_FOUND,
            f"Knowledge document does not exist: {path}",
        )
    if path.suffix.lower() not in SUPPORTED_KNOWLEDGE_SUFFIXES:
        raise KnowledgeLoadError(
            KnowledgeLoadErrorCode.UNSUPPORTED_FORMAT,
            f"Unsupported knowledge document format: {path.suffix or '<none>'}",
        )
    try:
        content = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise KnowledgeLoadError(
            KnowledgeLoadErrorCode.READ_ERROR,
            f"Knowledge document is not readable UTF-8 text: {path}",
        ) from error
    if not content:
        raise KnowledgeLoadError(
            KnowledgeLoadErrorCode.EMPTY_DOCUMENT,
            f"Knowledge document is empty: {path}",
        )
    base = Path(working_directory or Path.cwd())
    source_name = _source_label(path, working_directory=base)
    checksum = sha256(content.encode("utf-8")).hexdigest()
    document_key = sha256(f"{source_name}\0{checksum}".encode()).hexdigest()[:16]
    return KnowledgeDocument(
        document_id=f"doc_{document_key}",
        source=source_name,
        title=_document_title(path, content),
        content=content,
        checksum=checksum,
        metadata={"format": path.suffix.lower().lstrip(".")},
    )


def load_knowledge_documents(
    sources: Sequence[str | Path],
    *,
    working_directory: str | Path | None = None,
) -> list[KnowledgeDocument]:
    """Recursively load files from deterministic, de-duplicated sources."""
    if not sources:
        raise ValueError("At least one knowledge source is required.")
    selected_files: dict[Path, Path] = {}
    for source in sources:
        path = Path(source).resolve()
        if not path.exists():
            raise KnowledgeLoadError(
                KnowledgeLoadErrorCode.SOURCE_NOT_FOUND,
                f"Knowledge source does not exist: {path}",
            )
        if path.is_file():
            if path.suffix.lower() not in SUPPORTED_KNOWLEDGE_SUFFIXES:
                raise KnowledgeLoadError(
                    KnowledgeLoadErrorCode.UNSUPPORTED_FORMAT,
                    f"Unsupported knowledge document format: {path.suffix or '<none>'}",
                )
            selected_files[path] = path
            continue
        for candidate in path.rglob("*"):
            if (
                candidate.is_file()
                and candidate.suffix.lower() in SUPPORTED_KNOWLEDGE_SUFFIXES
            ):
                selected_files[candidate.resolve()] = candidate.resolve()
    if not selected_files:
        raise KnowledgeLoadError(
            KnowledgeLoadErrorCode.NO_SUPPORTED_DOCUMENTS,
            "Knowledge sources contain no supported Markdown or text files.",
        )
    return [
        load_knowledge_document(path, working_directory=working_directory)
        for path in sorted(selected_files, key=lambda item: item.as_posix())
    ]
