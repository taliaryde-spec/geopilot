"""Atomic JSON persistence for user-confirmed long-term memory."""

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from pydantic import ValidationError

from geopilot.memory.models import (
    MemoryEntry,
    MemoryKind,
    MemoryWriteRequest,
    StoredMemory,
)

DEFAULT_MEMORY_PATH = Path("artifacts") / "memory" / "profile.json"

_SENSITIVE_KEY_PARTS = {
    "api_key",
    "credential",
    "credentials",
    "password",
    "private_key",
    "secret",
    "token",
}


class MemoryStoreErrorCode(StrEnum):
    """Stable identifiers for memory persistence and policy failures."""

    CONFIRMATION_REQUIRED = "memory_confirmation_required"
    SENSITIVE_KEY_REJECTED = "memory_sensitive_key_rejected"
    NOT_FOUND = "memory_not_found"
    INVALID_STORE = "invalid_memory_store"


class MemoryStoreError(ValueError):
    """Raised when a memory request violates storage or policy constraints."""

    def __init__(self, code: MemoryStoreErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class MemoryStore:
    """Create, update, list, and delete scoped memory entries atomically."""

    def __init__(
        self,
        path: str | Path = DEFAULT_MEMORY_PATH,
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self._id_factory = id_factory or (lambda: f"mem_{uuid4().hex[:16]}")
        self._clock = clock or (lambda: datetime.now(UTC))

    def upsert(self, request: MemoryWriteRequest) -> MemoryEntry:
        """Persist an explicitly confirmed value under one stable identity."""
        if not request.confirmed:
            raise MemoryStoreError(
                MemoryStoreErrorCode.CONFIRMATION_REQUIRED,
                "Long-term memory writes require explicit user confirmation.",
            )
        self._reject_sensitive_key(request.key)
        now = self._normalize_time(self._clock())
        expires_at = (
            now + timedelta(days=request.expires_in_days)
            if request.expires_in_days is not None
            else None
        )
        stored = self.load()
        existing = next(
            (
                entry
                for entry in stored.entries
                if entry.namespace == request.namespace
                and entry.kind is request.kind
                and entry.key == request.key
            ),
            None,
        )
        entry = MemoryEntry(
            memory_id=(existing.memory_id if existing else self._id_factory()),
            namespace=request.namespace,
            kind=request.kind,
            key=request.key,
            value=request.value.strip(),
            revision=(existing.revision + 1 if existing else 1),
            created_at=(existing.created_at if existing else now),
            updated_at=now,
            expires_at=expires_at,
        )
        remaining = [
            candidate
            for candidate in stored.entries
            if not (
                candidate.namespace == request.namespace
                and candidate.kind is request.kind
                and candidate.key == request.key
            )
        ]
        self._save(StoredMemory(entries=[*remaining, entry]))
        return entry

    def list_entries(
        self,
        namespace: str,
        *,
        kind: MemoryKind | None = None,
        include_expired: bool = False,
    ) -> list[MemoryEntry]:
        """Return one namespace without leaking entries across users/scopes."""
        now = self._normalize_time(self._clock())
        entries = [
            entry
            for entry in self.load().entries
            if entry.namespace == namespace
            and (kind is None or entry.kind is kind)
            and (include_expired or entry.expires_at is None or entry.expires_at > now)
        ]
        return sorted(entries, key=lambda entry: (entry.kind, entry.key))

    def delete(self, namespace: str, memory_id: str) -> MemoryEntry:
        """Delete exactly one entry while enforcing its namespace boundary."""
        stored = self.load()
        selected = next(
            (
                entry
                for entry in stored.entries
                if entry.namespace == namespace and entry.memory_id == memory_id
            ),
            None,
        )
        if selected is None:
            raise MemoryStoreError(
                MemoryStoreErrorCode.NOT_FOUND,
                f"Memory entry does not exist in namespace '{namespace}': {memory_id}",
            )
        self._save(
            StoredMemory(
                entries=[
                    entry for entry in stored.entries if entry.memory_id != memory_id
                ]
            )
        )
        return selected

    def load(self) -> StoredMemory:
        """Load and validate the complete storage envelope."""
        if not self.path.exists():
            return StoredMemory()
        try:
            return StoredMemory.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, json.JSONDecodeError) as error:
            raise MemoryStoreError(
                MemoryStoreErrorCode.INVALID_STORE,
                f"Memory store is invalid: {self.path.resolve()}",
            ) from error

    def _save(self, stored: StoredMemory) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(stored.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _reject_sensitive_key(key: str) -> None:
        normalized = key.lower().replace("-", "_").replace(".", "_")
        if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
            raise MemoryStoreError(
                MemoryStoreErrorCode.SENSITIVE_KEY_REJECTED,
                "Secrets, tokens, passwords, and credentials cannot be stored.",
            )

    @staticmethod
    def _normalize_time(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
