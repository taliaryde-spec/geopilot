"""Integration tests for the GeoPilot command-line interface."""

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

import geopilot.cli as cli_module
from geopilot.agent.config import ModelSettings
from geopilot.agent.models import ModelResponse, ToolCall
from geopilot.cli import (
    EXIT_AGENT_ERROR,
    EXIT_CONFIGURATION_ERROR,
    EXIT_EVALUATION_ERROR,
    EXIT_EXECUTION_ERROR,
    EXIT_FILE_NOT_FOUND,
    EXIT_INPUT_ERROR,
    EXIT_MEMORY_ERROR,
    EXIT_PLAN_ERROR,
    EXIT_RAG_ERROR,
    EXIT_SUCCESS,
    EXIT_TRACE_ERROR,
    EXIT_VALIDATION_ERROR,
    build_parser,
    main,
)
from geopilot.planning.models import (
    AnalysisOperation,
    AnalysisPlanProposal,
    AnalysisPlanStep,
)
from geopilot.planning.store import PlanStore


def build_cli_plan(store: PlanStore) -> str:
    """Persist a small pending plan and return its identifier."""
    proposal = AnalysisPlanProposal(
        user_goal="分析设施服务范围",
        datasets=["facilities.csv"],
        steps=[
            AnalysisPlanStep(
                step_id=1,
                operation=AnalysisOperation.REPROJECT,
                description="转换到米制坐标系。",
                inputs=["facilities.csv"],
                parameters={"target_crs": "EPSG:32651"},
                expected_output="米制设施点图层",
            )
        ],
        expected_outputs=["米制设施点图层"],
    )
    return store.create(proposal).plan_id


def test_main_without_command_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == EXIT_SUCCESS
    assert "inspect" in captured.out
    assert "agent" in captured.out
    assert "agent-evaluate" in captured.out
    assert "show-plan" in captured.out
    assert "approve" in captured.out
    assert "reject" in captured.out
    assert "execute" in captured.out
    assert "show-run" in captured.out
    assert "resume" in captured.out
    assert "rag-build" in captured.out
    assert "rag-search" in captured.out
    assert "rag-evaluate" in captured.out
    assert "rag-chunk-experiment" in captured.out
    assert "rag-retrieval-experiment" in captured.out
    assert "rag-rerank-experiment" in captured.out
    assert "memory-set" in captured.out
    assert "memory-list" in captured.out
    assert "memory-recall" in captured.out
    assert "memory-delete" in captured.out
    assert "trace-list" in captured.out


def test_memory_cli_requires_confirmation_and_supports_full_lifecycle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memory_path = tmp_path / "memory.json"
    base = ["--memory-path", str(memory_path), "--namespace", "student"]

    rejected = main(
        [
            "memory-set",
            "project_context",
            "major",
            "地理信息系统",
            *base,
        ]
    )
    rejected_payload = json.loads(capsys.readouterr().err)

    assert rejected == EXIT_MEMORY_ERROR
    assert rejected_payload["error"]["code"] == "memory_confirmation_required"
    assert not memory_path.exists()

    created = main(
        [
            "memory-set",
            "project_context",
            "major",
            "地理信息系统",
            "--confirmed",
            *base,
        ]
    )
    created_payload = json.loads(capsys.readouterr().out)
    memory_id = created_payload["memory_id"]

    assert created == EXIT_SUCCESS
    assert created_payload["source"] == "user_confirmed"

    listed = main(["memory-list", *base])
    listed_payload = json.loads(capsys.readouterr().out)

    assert listed == EXIT_SUCCESS
    assert [entry["memory_id"] for entry in listed_payload] == [memory_id]

    recalled = main(["memory-recall", "我的地理信息系统专业", *base])
    recalled_payload = json.loads(capsys.readouterr().out)

    assert recalled == EXIT_SUCCESS
    assert recalled_payload["entries"][0]["memory_id"] == memory_id
    assert "地理信息系统" in recalled_payload["context"]

    deleted = main(["memory-delete", memory_id, *base])
    deleted_payload = json.loads(capsys.readouterr().out)

    assert deleted == EXIT_SUCCESS
    assert deleted_payload["memory_id"] == memory_id

    main(["memory-list", *base])
    assert json.loads(capsys.readouterr().out) == []


def test_chunk_experiment_parser_validates_repeatable_variants() -> None:
    arguments = build_parser().parse_args(
        [
            "rag-chunk-experiment",
            "knowledge",
            "--variant",
            "300:50",
            "--variant",
            "700:100",
            "--token-warning-ratio",
            "0.75",
        ]
    )

    assert arguments.command == "rag-chunk-experiment"
    assert [variant.model_dump() for variant in arguments.variants] == [
        {"chunk_size": 300, "chunk_overlap": 50},
        {"chunk_size": 700, "chunk_overlap": 100},
    ]
    assert arguments.token_warning_ratio == 0.75


def test_retrieval_strategy_parser_accepts_hybrid_parameters() -> None:
    arguments = build_parser().parse_args(
        [
            "rag-search",
            "service_radius_m 是什么？",
            "--retrieval-mode",
            "hybrid",
            "--hybrid-candidate-k",
            "8",
            "--rrf-k",
            "30",
        ]
    )

    assert arguments.retrieval_mode.value == "hybrid"
    assert arguments.hybrid_candidate_k == 8
    assert arguments.rrf_k == 30


def test_retrieval_strategy_parser_accepts_reranker_parameters() -> None:
    arguments = build_parser().parse_args(
        [
            "rag-search",
            "距离分析为什么不能直接使用 EPSG:4326？",
            "--retrieval-mode",
            "hybrid_rerank",
            "--reranker-model",
            "BAAI/bge-reranker-base",
            "--reranker-cache",
            "artifacts/test-reranker-cache",
            "--rerank-candidate-k",
            "10",
        ]
    )

    assert arguments.retrieval_mode is cli_module.RetrievalMode.HYBRID_RERANK
    assert arguments.reranker_model == "BAAI/bge-reranker-base"
    assert arguments.reranker_cache == Path("artifacts/test-reranker-cache")
    assert arguments.rerank_candidate_k == 10


def test_rag_search_reports_missing_index(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "rag-search",
            "为什么需要米制 CRS？",
            "--index-path",
            str(tmp_path / "missing-index.json"),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_RAG_ERROR
    assert captured.out == ""
    assert payload["error"]["code"] == "vector_index_not_found"


def test_main_reports_missing_model_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEOPILOT_PROVIDER", raising=False)
    monkeypatch.delenv("GEOPILOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEOPILOT_MODEL", raising=False)

    exit_code = main(["agent", "检查示例数据"])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_CONFIGURATION_ERROR
    assert captured.out == ""
    assert payload["error"]["code"] == "model_configuration_error"


def test_main_runs_agent_without_network(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeModel:
        def complete(self, messages: object, tools: object) -> ModelResponse:
            return ModelResponse(content="Agent 已返回测试答案。")

    monkeypatch.setenv("GEOPILOT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEOPILOT_MODEL", "test-model")
    captured_max_tokens: list[int] = []

    def build_fake_model(settings: ModelSettings) -> FakeModel:
        captured_max_tokens.append(settings.max_output_tokens)
        return FakeModel()

    monkeypatch.setattr(cli_module, "build_model", build_fake_model)

    exit_code = main(
        [
            "agent",
            "检查示例数据",
            "--max-output-tokens",
            "5000",
            "--no-trace",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == EXIT_SUCCESS
    assert captured_max_tokens == [5000]
    assert captured.out == "Agent 已返回测试答案。\n"
    assert captured.err == ""


def test_main_evaluates_agent_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeModel:
        def complete(self, messages: object, tools: object) -> ModelResponse:
            return ModelResponse(content="评测任务完成。")

    cases_path = tmp_path / "agent-cases.json"
    cases_path.write_text(
        json.dumps(
            [
                {
                    "case_id": "answer_only",
                    "prompt": "直接回答",
                    "required_answer_contains": ["完成"],
                    "max_model_turns": 1,
                    "max_tool_calls": 0,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "result.json"
    monkeypatch.setenv("GEOPILOT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEOPILOT_MODEL", "test-model")
    monkeypatch.setattr(cli_module, "build_model", lambda settings: FakeModel())

    exit_code = main(
        [
            "agent-evaluate",
            str(cases_path),
            "--knowledge-index",
            str(tmp_path / "missing-index.json"),
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert captured.err == ""
    assert payload["task_success_rate"] == 1.0
    assert payload["case_count"] == 1
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_agent_evaluation_reports_invalid_empty_case_set(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "empty-cases.json"
    cases_path.write_text("[]", encoding="utf-8")

    exit_code = main(["agent-evaluate", str(cases_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_EVALUATION_ERROR
    assert captured.out == ""
    assert payload["error"]["code"] == "invalid_agent_evaluation"


def test_agent_no_memory_bypasses_an_invalid_memory_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeModel:
        def complete(self, messages: object, tools: object) -> ModelResponse:
            return ModelResponse(content="Memory 已关闭，Agent 正常运行。")

    memory_path = tmp_path / "invalid-memory.json"
    memory_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setenv("GEOPILOT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEOPILOT_MODEL", "test-model")
    monkeypatch.setattr(cli_module, "build_model", lambda settings: FakeModel())

    exit_code = main(
        [
            "agent",
            "继续任务",
            "--memory-path",
            str(memory_path),
            "--no-memory",
            "--no-trace",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == EXIT_SUCCESS
    assert captured.out == "Memory 已关闭，Agent 正常运行。\n"
    assert captured.err == ""


def test_main_reports_bounded_trace_after_agent_max_turns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class LoopingModel:
        def complete(self, messages: object, tools: object) -> ModelResponse:
            return ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="call-loop",
                        name="missing_tool",
                        arguments={},
                    )
                ]
            )

    monkeypatch.setenv("GEOPILOT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEOPILOT_MODEL", "test-model")
    monkeypatch.setattr(
        cli_module,
        "build_model",
        lambda settings: LoopingModel(),
    )

    trace_path = tmp_path / "agent-runs.jsonl"
    exit_code = main(
        [
            "agent",
            "持续调用工具",
            "--max-turns",
            "2",
            "--trace-path",
            str(trace_path),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_AGENT_ERROR
    assert captured.out == ""
    assert payload["error"]["code"] == "agent_max_turns"
    assert payload["trace"]["model_turns"] == 2
    assert payload["trace"]["tool_results"] == [
        {
            "name": "missing_tool",
            "success": False,
            "error_code": "unknown_tool",
            "error": "Tool is not registered: missing_tool",
        },
        {
            "name": "missing_tool",
            "success": False,
            "error_code": "unknown_tool",
            "error": "Tool is not registered: missing_tool",
        },
    ]

    list_exit_code = main(
        ["trace-list", "--trace-path", str(trace_path), "--status", "failed"]
    )
    listed = json.loads(capsys.readouterr().out)

    assert list_exit_code == EXIT_SUCCESS
    assert listed[0]["status"] == "failed"
    assert listed[0]["error_code"] == "agent_max_turns"
    assert listed[0]["tool_calls"][0] == {
        "sequence": 1,
        "name": "missing_tool",
        "success": False,
        "error_code": "unknown_tool",
    }
    serialized = json.dumps(listed, ensure_ascii=False)
    assert "持续调用工具" not in serialized
    assert "call-loop" not in serialized


def test_trace_list_reports_invalid_query(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "trace-list",
            "--trace-path",
            str(tmp_path / "missing.jsonl"),
            "--limit",
            "0",
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == EXIT_TRACE_ERROR
    assert payload["error"]["code"] == "invalid_trace_query"


def test_main_inspects_valid_dataset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "facilities.geojson"
    frame = gpd.GeoDataFrame(
        {"name": ["Clinic A"]},
        geometry=[Point(121.47, 31.23)],
        crs="EPSG:4326",
    )
    frame.to_file(dataset_path, driver="GeoJSON")

    exit_code = main(["inspect", str(dataset_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert captured.err == ""
    assert payload["profile"]["feature_count"] == 1
    assert payload["profile"]["crs"] == "EPSG:4326"
    assert payload["validation"]["can_proceed"] is True


def test_main_allows_dataset_with_validation_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "facilities_with_missing_name.geojson"
    frame = gpd.GeoDataFrame(
        {"name": ["Clinic A", None]},
        geometry=[Point(121.47, 31.23), Point(121.48, 31.24)],
        crs="EPSG:4326",
    )
    frame.to_file(dataset_path, driver="GeoJSON")

    exit_code = main(["inspect", str(dataset_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert payload["validation"]["can_proceed"] is True
    assert payload["validation"]["issues"][0]["severity"] == "warning"


def test_main_inspects_csv_with_custom_coordinate_columns(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "facilities.csv"
    pd.DataFrame(
        {
            "name": ["Clinic A"],
            "lon": [121.47],
            "lat": [31.23],
        }
    ).to_csv(dataset_path, index=False)

    exit_code = main(
        [
            "inspect",
            str(dataset_path),
            "--longitude-column",
            "lon",
            "--latitude-column",
            "lat",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert payload["profile"]["geometry_types"] == {"Point": 1}
    assert payload["profile"]["crs"] == "EPSG:4326"
    assert payload["validation"]["can_proceed"] is True


def test_main_reports_csv_coordinate_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "invalid_coordinates.csv"
    pd.DataFrame(
        {
            "longitude": [181.0],
            "latitude": [31.23],
        }
    ).to_csv(dataset_path, index=False)

    exit_code = main(["inspect", str(dataset_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_INPUT_ERROR
    assert captured.out == ""
    assert payload["error"]["code"] == "longitude_out_of_range"


def test_main_reports_missing_dataset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "missing.geojson"

    exit_code = main(["inspect", str(dataset_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_FILE_NOT_FOUND
    assert captured.out == ""
    assert payload["error"]["code"] == "dataset_not_found"


def test_main_returns_validation_error_for_invalid_geometry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "invalid.geojson"
    invalid_polygon = Polygon(
        [
            (0, 0),
            (1, 1),
            (1, 0),
            (0, 1),
            (0, 0),
        ]
    )
    frame = gpd.GeoDataFrame(
        {"name": ["Invalid area"]},
        geometry=[invalid_polygon],
        crs="EPSG:4326",
    )
    frame.to_file(dataset_path, driver="GeoJSON")

    exit_code = main(["inspect", str(dataset_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_VALIDATION_ERROR
    assert payload["validation"]["can_proceed"] is False
    assert payload["validation"]["issues"][0]["code"] == "invalid_geometry"


def test_main_shows_pending_analysis_plan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = PlanStore(tmp_path, id_factory=lambda: "plan_cli_show")
    plan_id = build_cli_plan(store)

    exit_code = main(["show-plan", plan_id, "--plans-dir", str(tmp_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert captured.err == ""
    assert payload["plan_id"] == plan_id
    assert payload["status"] == "awaiting_approval"


def test_main_approves_pending_analysis_plan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = PlanStore(tmp_path, id_factory=lambda: "plan_cli_approve")
    plan_id = build_cli_plan(store)

    exit_code = main(["approve", plan_id, "--plans-dir", str(tmp_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert captured.err == ""
    assert payload["status"] == "approved"
    assert store.load(plan_id).status == "approved"


def test_main_rejects_pending_analysis_plan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = PlanStore(tmp_path, id_factory=lambda: "plan_cli_reject")
    plan_id = build_cli_plan(store)

    exit_code = main(
        [
            "reject",
            plan_id,
            "--reason",
            "需要先确认服务半径字段。",
            "--plans-dir",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert captured.err == ""
    assert payload["status"] == "rejected"
    assert payload["rejection_reason"] == "需要先确认服务半径字段。"


def test_main_reports_missing_analysis_plan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["approve", "plan_missing", "--plans-dir", str(tmp_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_PLAN_ERROR
    assert captured.out == ""
    assert payload["error"]["code"] == "plan_not_found"


def test_main_executes_approved_plan_and_shows_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "facilities.geojson"
    gpd.GeoDataFrame(
        {"facility_id": [1]},
        geometry=[Point(121.47, 31.23)],
        crs="EPSG:4326",
    ).to_file(source, driver="GeoJSON")
    plans_dir = tmp_path / "plans"
    runs_dir = tmp_path / "runs"
    store = PlanStore(plans_dir, id_factory=lambda: "plan_cli_execute")
    proposal = AnalysisPlanProposal(
        user_goal="重投影设施数据",
        datasets=[str(source)],
        steps=[
            AnalysisPlanStep(
                step_id=1,
                operation=AnalysisOperation.REPROJECT,
                description="转换到米制坐标系。",
                inputs=[str(source)],
                parameters={"target_crs": "EPSG:32651"},
                output="facilities_projected",
                expected_output="米制设施图层",
            )
        ],
        expected_outputs=["米制设施图层"],
    )
    plan = store.create(proposal)
    store.approve(plan.plan_id)

    exit_code = main(
        [
            "execute",
            plan.plan_id,
            "--plans-dir",
            str(plans_dir),
            "--runs-dir",
            str(runs_dir),
        ]
    )
    captured = capsys.readouterr()
    run_payload = json.loads(captured.out)

    assert exit_code == EXIT_SUCCESS
    assert captured.err == ""
    assert run_payload["status"] == "succeeded"
    run_id = run_payload["run_id"]

    show_exit_code = main(["show-run", run_id, "--runs-dir", str(runs_dir)])
    show_capture = capsys.readouterr()
    shown_payload = json.loads(show_capture.out)

    assert show_exit_code == EXIT_SUCCESS
    assert shown_payload["run_id"] == run_id
    assert shown_payload["steps"][0]["status"] == "succeeded"


def test_main_rejects_execution_of_legacy_plan_without_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plans_dir = tmp_path / "plans"
    runs_dir = tmp_path / "runs"
    store = PlanStore(plans_dir, id_factory=lambda: "plan_cli_legacy")
    plan_id = build_cli_plan(store)
    store.approve(plan_id)

    exit_code = main(
        [
            "execute",
            plan_id,
            "--plans-dir",
            str(plans_dir),
            "--runs-dir",
            str(runs_dir),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert exit_code == EXIT_EXECUTION_ERROR
    assert captured.out == ""
    assert payload["error"]["code"] == "legacy_plan_missing_output"
