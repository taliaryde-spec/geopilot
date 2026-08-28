"""Validated contracts for GeoPilot's explicit long-term memory."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MemoryKind(StrEnum):
    """Whitelisted categories suitable for cross-session persistence."""

    RESPONSE_PREFERENCE = "response_preference"
    USER_GOAL = "user_goal"
    PROJECT_CONTEXT = "project_context"


class MemorySource(StrEnum):
    """Auditable origins accepted by the first memory version."""

    USER_CONFIRMED = "user_confirmed"


class MemoryEntry(BaseModel):
    """One versioned, scoped, and optionally expiring memory fact."""

    memory_id: str = Field(pattern=r"^mem_[a-f0-9]{16}$")
    namespace: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: MemoryKind
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    value: str = Field(min_length=1, max_length=500)
    source: MemorySource = MemorySource.USER_CONFIRMED
    revision: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> "MemoryEntry":
        if self.updated_at < self.created_at:
            raise ValueError("Memory updated_at cannot precede created_at.")
        if self.expires_at is not None and self.expires_at <= self.updated_at:
            raise ValueError("Memory expires_at must be after updated_at.")
        return self


class MemoryWriteRequest(BaseModel):
    """User-authorized request to create or update one stable memory."""

    namespace: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: MemoryKind
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    value: str = Field(min_length=1, max_length=500)
    confirmed: bool
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class StoredMemory(BaseModel):
    """Portable JSON envelope with an explicit storage schema version."""

    schema_version: Literal["1.0"] = "1.0"
    entries: list[MemoryEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_entries(self) -> "StoredMemory":
        ids = [entry.memory_id for entry in self.entries]
        identities = [
            (entry.namespace, entry.kind, entry.key) for entry in self.entries
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("Memory identifiers must be unique.")
        if len(identities) != len(set(identities)):
            raise ValueError("Memory namespace/kind/key identities must be unique.")
        return self


class MemoryRecallResult(BaseModel):
    """Relevant active memories and the bounded prompt context they produce."""

    namespace: str
    query: str
    entries: list[MemoryEntry]
    context: str
