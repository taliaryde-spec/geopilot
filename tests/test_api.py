"""Integration tests for the local-first FastAPI product boundary."""

import json
from collections.abc import Sequence
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point

import geopilot.api.service as service_module
from geopilot.agent.models import AgentMessage, ModelResponse, ToolCall, ToolDefinition
from geopilot.api import ApiSettings, GeoPilotApiService, create_app
from geopilot.planning.models import (
    AnalysisOperation,
    AnalysisPlanProposal,
    AnalysisPlanStep,
)
from geopilot.planning.store import PlanStore


class ScriptedApiModel:
    """Return fixed Tool Calling responses without accessing a model API."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses.copy()

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        del messages, tools
        if not self._responses:
            raise AssertionError("Scripted API model has no response left")
        return self._responses.pop(0)


def _settings(workspace: Path) -> ApiSettings:
    return ApiSettings(workspace_root=workspace)


def _write_facilities_csv(workspace: Path) -> Path:
    data_directory = workspace / "data"
    data_directory.mkdir(parents=True, exist_ok=True)
    path = data_directory / "facilities.csv"
    pd.DataFrame(
        {
            "name": ["Clinic A", "Clinic B"],
            "longitude": [121.47, 121.48],
            "latitude": [31.23, 31.24],
        }
    ).to_csv(path, index=False)
    return path


def test_health_and_openapi_do_not_require_model_credentials(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    health = client.get("/api/v1/health")
    schema = client.get("/openapi.json")

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "geopilot-api",
        "version": "0.1.0",
    }
    assert schema.status_code == 200
    assert "/api/v1/agent/runs" in schema.json()["paths"]
    assert "/api/v1/plans/{plan_id}/approve" in schema.json()["paths"]


def test_dataset_inspection_accepts_workspace_path_and_blocks_traversal(
    tmp_path: Path,
) -> None:
    _write_facilities_csv(tmp_path)
    client = TestClient(create_app(_settings(tmp_path)))

    accepted = client.post(
        "/api/v1/datasets/inspect",
        json={"source": "data/facilities.csv"},
    )
    blocked = client.post(
        "/api/v1/datasets/inspect",
        json={"source": "../outside.csv"},
    )

    assert accepted.status_code == 200
    assert accepted.json()["profile"]["feature_count"] == 2
    assert accepted.json()["profile"]["crs"] == "EPSG:4326"
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "invalid_dataset_input"
    assert "inside the API workspace" in blocked.json()["error"]["message"]


def test_request_validation_uses_stable_error_envelope(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.post("/api/v1/agent/runs", json={"max_turns": 100})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"
    assert response.json()["error"]["context"]["issues"]


def test_agent_api_runs_tool_call_and_writes_redacted_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_facilities_csv(tmp_path)
    model = ScriptedApiModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-api-inspect",
                        name="inspect_dataset",
                        arguments={"source": "data/facilities.csv"},
                    )
                ]
            ),
            ModelResponse(content="API 检查完成：2 个点，CRS 为 EPSG:4326。"),
        ]
    )
    monkeypatch.setenv("GEOPILOT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEOPILOT_MODEL", "test-model")
    monkeypatch.setattr(service_module, "build_model", lambda settings: model)
    settings = _settings(tmp_path)
    client = TestClient(create_app(settings))
    prompt = "请检查 data/facilities.csv，不要调用其他工具。"

    response = client.post(
        "/api/v1/agent/runs",
        json={"prompt": prompt, "memory_enabled": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_turns"] == 2
    assert payload["tools"] == [
        {"name": "inspect_dataset", "success": True, "error_code": None}
    ]
    assert payload["trace_id"].startswith("trace_")
    serialized_trace = settings.trace_path.read_text(encoding="utf-8")
    assert prompt not in serialized_trace
    assert "call-api-inspect" not in serialized_trace
    assert "feature_count" not in serialized_trace


def test_agent_api_tool_policy_blocks_model_path_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = ScriptedApiModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-outside",
                        name="inspect_dataset",
                        arguments={"source": "../private.csv"},
                    )
                ]
            ),
            ModelResponse(content="路径超出工作区，未读取文件。"),
        ]
    )
    monkeypatch.setenv("GEOPILOT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEOPILOT_MODEL", "test-model")
    monkeypatch.setattr(service_module, "build_model", lambda settings: model)
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.post(
        "/api/v1/agent/runs",
        json={"prompt": "读取 ../private.csv", "memory_enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["tools"] == [
        {
            "name": "inspect_dataset",
            "success": False,
            "error_code": "tool_execution_error",
        }
    ]
    assert response.json()["answer"] == "路径超出工作区，未读取文件。"


def test_plan_api_approves_executes_and_shows_run(tmp_path: Path) -> None:
    source = tmp_path / "data" / "facilities.geojson"
    source.parent.mkdir(parents=True)
    gpd.GeoDataFrame(
        {"facility_id": [1]},
        geometry=[Point(121.47, 31.23)],
        crs="EPSG:4326",
    ).to_file(source, driver="GeoJSON")
    service = GeoPilotApiService(_settings(tmp_path))
    plan = service.plan_store.create(
        AnalysisPlanProposal(
            user_goal="重投影设施数据",
            datasets=["data/facilities.geojson"],
            steps=[
                AnalysisPlanStep(
                    step_id=1,
                    operation=AnalysisOperation.REPROJECT,
                    description="转换到米制坐标系。",
                    inputs=["data/facilities.geojson"],
                    parameters={"target_crs": "EPSG:32651"},
                    output="facilities_projected",
                    expected_output="米制设施图层",
                )
            ],
            expected_outputs=["米制设施图层"],
        )
    )
    client = TestClient(create_app(service=service))

    shown = client.get(f"/api/v1/plans/{plan.plan_id}")
    approved = client.post(f"/api/v1/plans/{plan.plan_id}/approve")
    conflict = client.post(f"/api/v1/plans/{plan.plan_id}/approve")
    executed = client.post(f"/api/v1/plans/{plan.plan_id}/execute")
    run_id = executed.json()["run_id"]
    shown_run = client.get(f"/api/v1/runs/{run_id}")

    assert shown.status_code == 200
    assert shown.json()["status"] == "awaiting_approval"
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "invalid_plan_transition"
    assert executed.status_code == 200
    assert executed.json()["status"] == "succeeded"
    assert shown_run.status_code == 200
    assert shown_run.json()["steps"][0]["status"] == "succeeded"


def test_api_refuses_to_approve_legacy_plan_outside_workspace(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    unrestricted_store = PlanStore(
        settings.plans_directory,
        id_factory=lambda: "plan_unsafe_api",
    )
    plan = unrestricted_store.create(
        AnalysisPlanProposal(
            user_goal="读取工作区外数据",
            datasets=["../outside.geojson"],
            steps=[
                AnalysisPlanStep(
                    step_id=1,
                    operation=AnalysisOperation.REPROJECT,
                    description="尝试重投影。",
                    inputs=["../outside.geojson"],
                    parameters={"target_crs": "EPSG:32651"},
                    output="outside_projected",
                    expected_output="不安全结果",
                )
            ],
            expected_outputs=["不安全结果"],
        )
    )
    client = TestClient(create_app(settings))

    response = client.post(f"/api/v1/plans/{plan.plan_id}/approve")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsafe_plan_dataset"


def test_trace_api_filters_status(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.trace_path.parent.mkdir(parents=True)
    settings.trace_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "trace_id": f"trace_{'a' * 32}",
                "started_at": "2026-08-28T00:00:00Z",
                "provider": "test",
                "model_name": "test-model",
                "prompt_sha256": "b" * 64,
                "status": "failed",
                "duration_ms": 10,
                "model_turns": 1,
                "tool_calls": [],
                "final_answer_characters": 0,
                "error_code": "agent_runtime_error",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(settings))

    response = client.get("/api/v1/traces?status=failed&limit=1")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "failed"
