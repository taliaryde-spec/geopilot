"""Validated contracts for end-to-end GeoPilot Agent evaluation."""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class ExpectedTaskOutcome(StrEnum):
    """Outcomes that an evaluation case can intentionally require."""

    COMPLETED = "completed"
    CORRECT_FAILURE = "correct_failure"


class ObservedTaskOutcome(StrEnum):
    """Rule-derived outcome observed after one Agent run."""

    COMPLETED = "completed"
    CORRECT_FAILURE = "correct_failure"
    FAILED = "failed"


class AgentEvaluationCase(BaseModel):
    """One task with explicit process, result, and safety expectations."""

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    prompt: str = Field(min_length=1)
    expected_outcome: ExpectedTaskOutcome = ExpectedTaskOutcome.COMPLETED
    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_answer_contains: list[str] = Field(default_factory=list)
    expected_tool_error_codes: list[str] = Field(default_factory=list)
    max_model_turns: int = Field(default=4, ge=1, le=12)
    max_tool_calls: int = Field(default=4, ge=0, le=30)
    allow_duplicate_tool_calls: bool = False

    @model_validator(mode="after")
    def validate_expectations(self) -> "AgentEvaluationCase":
        if len(self.required_tools) != len(set(self.required_tools)):
            raise ValueError("Agent evaluation required_tools must be unique.")
        if len(self.forbidden_tools) != len(set(self.forbidden_tools)):
            raise ValueError("Agent evaluation forbidden_tools must be unique.")
        overlap = set(self.required_tools) & set(self.forbidden_tools)
        if overlap:
            raise ValueError("A tool cannot be both required and forbidden.")
        if (
            self.expected_outcome is ExpectedTaskOutcome.CORRECT_FAILURE
            and not self.expected_tool_error_codes
        ):
            raise ValueError("Correct-failure cases require expected error codes.")
        return self


class AgentCaseEvaluation(BaseModel):
    """Deterministic process and result score for one Agent case."""

    case_id: str
    passed: bool
    expected_outcome: ExpectedTaskOutcome
    observed_outcome: ObservedTaskOutcome
    duration_ms: float = Field(ge=0)
    model_turns: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    tool_names: list[str]
    required_tool_recall: float = Field(ge=0, le=1)
    tool_call_success_rate: float = Field(ge=0, le=1)
    step_efficiency: float = Field(ge=0, le=1)
    forbidden_tool_call_count: int = Field(ge=0)
    duplicate_tool_call_count: int = Field(ge=0)
    missing_answer_requirements: list[str]
    missing_expected_error_codes: list[str]
    runtime_error: str | None = None


class AgentEvaluationResult(BaseModel):
    """Aggregate reliability metrics for a fixed Agent task set."""

    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    case_count: int = Field(ge=1)
    task_success_rate: float = Field(ge=0, le=1)
    completed_rate: float = Field(ge=0, le=1)
    correct_failure_rate: float = Field(ge=0, le=1)
    error_recovery_rate: float = Field(ge=0, le=1)
    mean_required_tool_recall: float = Field(ge=0, le=1)
    tool_call_success_rate: float = Field(ge=0, le=1)
    forbidden_tool_violation_rate: float = Field(ge=0, le=1)
    duplicate_tool_call_rate: float = Field(ge=0, le=1)
    mean_step_efficiency: float = Field(ge=0, le=1)
    mean_model_turns: float = Field(ge=0)
    mean_tool_calls: float = Field(ge=0)
    total_duration_ms: float = Field(ge=0)
    cases: list[AgentCaseEvaluation] = Field(min_length=1)
