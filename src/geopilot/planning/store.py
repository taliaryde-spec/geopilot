"""Persist analysis plans and enforce human-approval state transitions."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from geopilot.planning.models import (
    AnalysisPlan,
    AnalysisPlanProposal,
    PlanStatus,
)
from geopilot.planning.validator import validate_analysis_plan


class PlanStoreErrorCode(StrEnum):
    """Stable identifiers for plan persistence and transition failures."""

    INVALID_PLAN_ID = "invalid_plan_id"
    PLAN_NOT_FOUND = "plan_not_found"
    CORRUPT_PLAN = "corrupt_plan"
    INVALID_PLAN_TRANSITION = "invalid_plan_transition"
    PLAN_NOT_APPROVED = "plan_not_approved"


class PlanStoreError(ValueError):
    """Raised when a plan cannot be persisted, loaded, or transitioned."""

    def __init__(self, code: PlanStoreErrorCode, message: str) -> None:
        """Store a stable code alongside the human-readable message."""
        self.code = code
        super().__init__(message)


class PlanStore:
    """File-backed plan checkpoint store for CLI and future Web sessions."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._root = Path(root).resolve()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: f"plan_{uuid4().hex}")

    @property
    def root(self) -> Path:
        """Return the resolved storage directory."""
        return self._root

    def create(self, proposal: AnalysisPlanProposal) -> AnalysisPlan:
        """Create and persist a plan that must wait for human approval."""
        validate_analysis_plan(proposal)
        plan = AnalysisPlan(
            **proposal.model_dump(),
            plan_id=self._id_factory(),
            status=PlanStatus.AWAITING_APPROVAL,
            created_at=self._clock(),
        )
        self._write(plan)
        return plan

    def load(self, plan_id: str) -> AnalysisPlan:
        """Load and validate one persisted plan."""
        plan_path = self._plan_path(plan_id)
        if not plan_path.is_file():
            raise PlanStoreError(
                PlanStoreErrorCode.PLAN_NOT_FOUND,
                f"Analysis plan does not exist: {plan_id}",
            )
        try:
            return AnalysisPlan.model_validate_json(
                plan_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as error:
            raise PlanStoreError(
                PlanStoreErrorCode.CORRUPT_PLAN,
                f"Analysis plan could not be read or validated: {plan_id}",
            ) from error

    def approve(self, plan_id: str) -> AnalysisPlan:
        """Approve a pending plan without executing it."""
        plan = self.load(plan_id)
        self._require_pending(plan)
        approved = plan.model_copy(
            update={
                "status": PlanStatus.APPROVED,
                "decided_at": self._clock(),
            }
        )
        self._write(approved)
        return approved

    def reject(self, plan_id: str, reason: str) -> AnalysisPlan:
        """Reject a pending plan and persist the human-provided reason."""
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ValueError("Rejection reason must not be empty.")

        plan = self.load(plan_id)
        self._require_pending(plan)
        rejected = plan.model_copy(
            update={
                "status": PlanStatus.REJECTED,
                "decided_at": self._clock(),
                "rejection_reason": cleaned_reason,
            }
        )
        self._write(rejected)
        return rejected

    def require_approved(self, plan_id: str) -> AnalysisPlan:
        """Return a plan only when a human has explicitly approved it."""
        plan = self.load(plan_id)
        if plan.status is not PlanStatus.APPROVED:
            raise PlanStoreError(
                PlanStoreErrorCode.PLAN_NOT_APPROVED,
                f"Analysis plan is not approved: {plan_id}",
            )
        return plan

    def _plan_path(self, plan_id: str) -> Path:
        """Resolve a validated identifier without allowing path traversal."""
        if re.fullmatch(r"plan_[A-Za-z0-9_-]+", plan_id) is None:
            raise PlanStoreError(
                PlanStoreErrorCode.INVALID_PLAN_ID,
                f"Invalid analysis plan identifier: {plan_id!r}",
            )
        return self._root / f"{plan_id}.json"

    def _write(self, plan: AnalysisPlan) -> None:
        """Atomically replace one plan checkpoint."""
        plan_path = self._plan_path(plan.plan_id)
        self._root.mkdir(parents=True, exist_ok=True)
        temporary_path = plan_path.with_suffix(".tmp")
        temporary_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        temporary_path.replace(plan_path)

    @staticmethod
    def _require_pending(plan: AnalysisPlan) -> None:
        """Reject repeated or conflicting approval decisions."""
        if plan.status is not PlanStatus.AWAITING_APPROVAL:
            raise PlanStoreError(
                PlanStoreErrorCode.INVALID_PLAN_TRANSITION,
                f"Plan {plan.plan_id} is already {plan.status.value}.",
            )
