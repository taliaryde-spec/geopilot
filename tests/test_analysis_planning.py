"""Tests for structured analysis plans and human approval checkpoints."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from geopilot.planning.models import (
    AnalysisOperation,
    AnalysisPlanProposal,
    AnalysisPlanStep,
    PlanRiskLevel,
    PlanStatus,
)
from geopilot.planning.store import (
    PlanStore,
    PlanStoreError,
    PlanStoreErrorCode,
)

FIXED_TIME = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def build_proposal() -> AnalysisPlanProposal:
    """Return a minimal but complete spatial-analysis plan proposal."""
    return AnalysisPlanProposal(
        user_goal="分析公共服务设施覆盖范围",
        datasets=["facilities.csv", "neighborhoods.geojson"],
        steps=[
            AnalysisPlanStep(
                step_id=1,
                operation=AnalysisOperation.REPROJECT,
                description="将设施点转换到推荐的米制 CRS。",
                inputs=["facilities.csv"],
                parameters={"target_crs": "EPSG:32651"},
                expected_output="米制设施点图层",
                risk_level=PlanRiskLevel.MEDIUM,
            ),
            AnalysisPlanStep(
                step_id=2,
                operation=AnalysisOperation.BUFFER,
                description="按服务半径生成设施缓冲区。",
                inputs=["米制设施点图层"],
                parameters={"distance_field": "service_radius_m"},
                expected_output="设施服务范围图层",
                risk_level=PlanRiskLevel.HIGH,
            ),
        ],
        expected_outputs=["设施服务范围 GeoJSON", "Markdown 分析报告"],
        risks=["缓冲距离依赖 service_radius_m 字段的单位正确性。"],
        assumptions=["service_radius_m 的单位为米。"],
    )


def build_store(root: Path) -> PlanStore:
    """Return a deterministic plan store for tests."""
    return PlanStore(
        root,
        clock=lambda: FIXED_TIME,
        id_factory=lambda: "plan_test123",
    )


def test_plan_proposal_requires_sequential_step_ids() -> None:
    proposal = build_proposal().model_dump()
    proposal["steps"][1]["step_id"] = 3

    with pytest.raises(ValidationError, match="sequential"):
        AnalysisPlanProposal.model_validate(proposal)


def test_plan_store_creates_awaiting_checkpoint(tmp_path: Path) -> None:
    store = build_store(tmp_path)

    plan = store.create(build_proposal())

    assert plan.plan_id == "plan_test123"
    assert plan.status is PlanStatus.AWAITING_APPROVAL
    assert plan.decided_at is None
    assert (tmp_path / "plan_test123.json").is_file()
    assert store.load(plan.plan_id) == plan


def test_plan_store_approves_and_authorizes_plan(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    plan = store.create(build_proposal())

    with pytest.raises(PlanStoreError) as pending_error:
        store.require_approved(plan.plan_id)
    assert pending_error.value.code is PlanStoreErrorCode.PLAN_NOT_APPROVED

    approved = store.approve(plan.plan_id)

    assert approved.status is PlanStatus.APPROVED
    assert approved.decided_at == FIXED_TIME
    assert store.require_approved(plan.plan_id) == approved


def test_plan_store_rejects_with_reason_and_blocks_later_approval(
    tmp_path: Path,
) -> None:
    store = build_store(tmp_path)
    plan = store.create(build_proposal())

    rejected = store.reject(plan.plan_id, "缓冲距离字段需要先核实。")

    assert rejected.status is PlanStatus.REJECTED
    assert rejected.rejection_reason == "缓冲距离字段需要先核实。"
    with pytest.raises(PlanStoreError) as transition_error:
        store.approve(plan.plan_id)
    assert transition_error.value.code is PlanStoreErrorCode.INVALID_PLAN_TRANSITION


def test_plan_store_rejects_path_traversal_identifier(tmp_path: Path) -> None:
    store = build_store(tmp_path)

    with pytest.raises(PlanStoreError) as error_info:
        store.load("../secret")

    assert error_info.value.code is PlanStoreErrorCode.INVALID_PLAN_ID
