"""FastAPI application factory for GeoPilot's local product interface."""

from typing import Annotated

from fastapi import FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from geopilot.api.models import (
    AgentRunRequest,
    AgentRunResponse,
    ApiErrorDetail,
    ApiErrorResponse,
    ApiSettings,
    DatasetInspectRequest,
    HealthResponse,
    RejectPlanRequest,
)
from geopilot.api.service import ApiServiceError, GeoPilotApiService
from geopilot.execution.models import ExecutionRun
from geopilot.models import DatasetIntakeResult
from geopilot.observability import AgentTrace, AgentTraceStatus
from geopilot.planning.models import AnalysisPlan

PlanId = Annotated[str, Path(pattern=r"^plan_[A-Za-z0-9_-]+$")]
RunId = Annotated[str, Path(pattern=r"^run_[A-Za-z0-9_-]+$")]


def create_app(
    settings: ApiSettings | None = None,
    *,
    service: GeoPilotApiService | None = None,
) -> FastAPI:
    """Create an app with injectable local paths for integration testing."""
    selected_service = service or GeoPilotApiService(settings)
    application = FastAPI(
        title="GeoPilot API",
        version="0.1.0",
        description=(
            "Local-first GIS Agent API. Bind to loopback unless authentication "
            "and deployment hardening have been added."
        ),
    )

    @application.exception_handler(ApiServiceError)
    async def handle_service_error(
        request: Request,
        error: ApiServiceError,
    ) -> JSONResponse:
        del request
        payload = ApiErrorResponse(
            error=ApiErrorDetail(
                code=error.code,
                message=str(error),
                context=error.context,
            )
        )
        return JSONResponse(
            status_code=error.status_code,
            content=payload.model_dump(mode="json", exclude_none=True),
        )

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        del request
        payload = ApiErrorResponse(
            error=ApiErrorDetail(
                code="request_validation_error",
                message="The HTTP request does not match the API contract.",
                context={
                    "issues": [
                        {
                            "type": issue["type"],
                            "location": list(issue["loc"]),
                            "message": issue["msg"],
                        }
                        for issue in error.errors()
                    ]
                },
            )
        )
        return JSONResponse(
            status_code=422,
            content=payload.model_dump(mode="json", exclude_none=True),
        )

    @application.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @application.post(
        "/api/v1/datasets/inspect",
        response_model=DatasetIntakeResult,
    )
    def inspect_dataset(request: DatasetInspectRequest) -> DatasetIntakeResult:
        return selected_service.inspect_dataset(request)

    @application.post("/api/v1/agent/runs", response_model=AgentRunResponse)
    def run_agent(request: AgentRunRequest) -> AgentRunResponse:
        return selected_service.run_agent(request)

    @application.get("/api/v1/plans/{plan_id}", response_model=AnalysisPlan)
    def show_plan(plan_id: PlanId) -> AnalysisPlan:
        return selected_service.show_plan(plan_id)

    @application.post(
        "/api/v1/plans/{plan_id}/approve",
        response_model=AnalysisPlan,
    )
    def approve_plan(plan_id: PlanId) -> AnalysisPlan:
        return selected_service.approve_plan(plan_id)

    @application.post(
        "/api/v1/plans/{plan_id}/reject",
        response_model=AnalysisPlan,
    )
    def reject_plan(plan_id: PlanId, request: RejectPlanRequest) -> AnalysisPlan:
        return selected_service.reject_plan(plan_id, request.reason)

    @application.post(
        "/api/v1/plans/{plan_id}/execute",
        response_model=ExecutionRun,
    )
    def execute_plan(plan_id: PlanId) -> ExecutionRun:
        return selected_service.execute_plan(plan_id)

    @application.get("/api/v1/runs/{run_id}", response_model=ExecutionRun)
    def show_run(run_id: RunId) -> ExecutionRun:
        return selected_service.show_run(run_id)

    @application.post("/api/v1/runs/{run_id}/resume", response_model=ExecutionRun)
    def resume_run(run_id: RunId) -> ExecutionRun:
        return selected_service.resume_run(run_id)

    @application.get("/api/v1/traces", response_model=list[AgentTrace])
    def list_traces(
        limit: Annotated[int, Query(ge=1, le=500)] = 20,
        status: AgentTraceStatus | None = None,
    ) -> list[AgentTrace]:
        return selected_service.list_traces(limit=limit, status=status)

    return application


app = create_app()
