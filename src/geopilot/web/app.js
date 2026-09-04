"use strict";

const ui = {
  healthDot: document.querySelector("#health-dot"),
  healthText: document.querySelector("#health-text"),
  notice: document.querySelector("#notice"),
  prompt: document.querySelector("#agent-prompt"),
  runAgent: document.querySelector("#run-agent"),
  agentPanel: document.querySelector("#agent-result-panel"),
  agentAnswer: document.querySelector("#agent-answer"),
  toolTrace: document.querySelector("#tool-trace"),
  datasetSource: document.querySelector("#dataset-source"),
  inspectDataset: document.querySelector("#inspect-dataset"),
  datasetResult: document.querySelector("#dataset-result"),
  planPanel: document.querySelector("#plan-panel"),
  planId: document.querySelector("#plan-id"),
  loadPlan: document.querySelector("#load-plan"),
  planSummary: document.querySelector("#plan-summary"),
  planSteps: document.querySelector("#plan-steps"),
  planActions: document.querySelector("#plan-actions"),
  approvePlan: document.querySelector("#approve-plan"),
  rejectPlan: document.querySelector("#reject-plan"),
  executePlan: document.querySelector("#execute-plan"),
  runPanel: document.querySelector("#run-panel"),
  runSummary: document.querySelector("#run-summary"),
  runSteps: document.querySelector("#run-steps"),
  mapEmpty: document.querySelector("#map-empty"),
  artifactLinks: document.querySelector("#artifact-links"),
};

const state = {
  plan: null,
  run: null,
  map: null,
  geojsonLayer: null,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("json") ? await response.json() : null;
  if (!response.ok) {
    const detail = payload?.error;
    throw new Error(detail ? `${detail.code}: ${detail.message}` : `HTTP ${response.status}`);
  }
  return payload;
}

function setBusy(button, busy, label) {
  if (!button.dataset.originalLabel) {
    button.dataset.originalLabel = button.textContent.trim();
  }
  button.disabled = busy;
  button.textContent = busy ? label : button.dataset.originalLabel;
}

function showNotice(message, isError = false) {
  ui.notice.textContent = message;
  ui.notice.classList.toggle("error", isError);
  ui.notice.hidden = false;
}

function clearNotice() {
  ui.notice.hidden = true;
  ui.notice.textContent = "";
  ui.notice.classList.remove("error");
}

function makeMetric(label, value) {
  const node = document.createElement("div");
  node.className = "metric";
  const key = document.createElement("small");
  key.textContent = label;
  const result = document.createElement("strong");
  result.textContent = String(value ?? "—");
  node.append(key, result);
  return node;
}

function makeBadge(value, className = "status-badge") {
  const badge = document.createElement("span");
  badge.className = className;
  badge.textContent = value;
  return badge;
}

async function checkHealth() {
  try {
    const health = await api("/api/v1/health");
    ui.healthDot.className = "state-dot online";
    ui.healthText.textContent = `${health.service} · ${health.status}`;
  } catch (error) {
    ui.healthDot.className = "state-dot offline";
    ui.healthText.textContent = "本地服务不可用";
  }
}

async function inspectDataset() {
  clearNotice();
  setBusy(ui.inspectDataset, true, "检查中…");
  try {
    const result = await api("/api/v1/datasets/inspect", {
      method: "POST",
      body: JSON.stringify({ source: ui.datasetSource.value.trim() }),
    });
    const grid = document.createElement("div");
    grid.className = "metric-grid";
    grid.append(
      makeMetric("要素", result.profile.feature_count),
      makeMetric("几何", result.profile.geometry_types.join(", ")),
      makeMetric("CRS", result.profile.crs),
      makeMetric("无效几何", result.profile.invalid_geometry_count),
      makeMetric("空几何", result.profile.empty_geometry_count),
      makeMetric("可继续", result.validation.can_proceed ? "是" : "否"),
    );
    ui.datasetResult.replaceChildren(grid);
  } catch (error) {
    ui.datasetResult.textContent = error.message;
    showNotice(error.message, true);
  } finally {
    setBusy(ui.inspectDataset, false, "");
  }
}

function renderAgentResult(result) {
  ui.agentPanel.hidden = false;
  ui.agentAnswer.textContent = result.answer;
  ui.toolTrace.replaceChildren();
  for (const tool of result.tools) {
    const pill = document.createElement("span");
    pill.className = `pill${tool.success ? "" : " failed"}`;
    pill.textContent = `${tool.success ? "✓" : "!"} ${tool.name}${tool.error_code ? ` · ${tool.error_code}` : ""}`;
    ui.toolTrace.append(pill);
  }
  if (result.trace_id) {
    const trace = document.createElement("span");
    trace.className = "pill";
    trace.textContent = `Trace · ${result.trace_id.slice(0, 14)}…`;
    ui.toolTrace.append(trace);
  }
}

async function runAgent() {
  clearNotice();
  const prompt = ui.prompt.value.trim();
  if (!prompt) {
    showNotice("请先输入任务。", true);
    return;
  }
  setBusy(ui.runAgent, true, "Agent 正在检查与规划…");
  try {
    const result = await api("/api/v1/agent/runs", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    });
    renderAgentResult(result);
    if (result.plan_ids.length > 0) {
      ui.planId.value = result.plan_ids.at(-1);
      await loadPlan();
      ui.planPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      ui.planPanel.hidden = false;
      showNotice("Agent 已完成回答；本次没有提交结构化计划。", false);
    }
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setBusy(ui.runAgent, false, "");
  }
}

function renderPlan(plan) {
  state.plan = plan;
  ui.planPanel.hidden = false;
  ui.planId.value = plan.plan_id;
  ui.planSummary.replaceChildren();
  const summary = document.createElement("div");
  summary.className = "summary-line";
  summary.append(makeBadge(plan.status));
  const id = document.createElement("span");
  id.textContent = plan.plan_id;
  summary.append(id);
  const count = document.createElement("span");
  count.textContent = `${plan.steps.length} 个步骤 · ${plan.datasets.length} 个数据源`;
  summary.append(count);
  ui.planSummary.append(summary);

  ui.planSteps.replaceChildren();
  for (const step of plan.steps) {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `${String(step.step_id).padStart(2, "0")} · ${step.operation}`;
    const description = document.createElement("p");
    description.textContent = step.description;
    item.append(title, description, makeBadge(step.risk_level, "risk-badge"));
    ui.planSteps.append(item);
  }

  ui.planActions.hidden = false;
  const awaiting = plan.status === "awaiting_approval";
  ui.approvePlan.hidden = !awaiting;
  ui.rejectPlan.hidden = !awaiting;
  ui.executePlan.hidden = plan.status !== "approved";
}

async function loadPlan() {
  clearNotice();
  const planId = ui.planId.value.trim();
  if (!planId) {
    showNotice("请输入 Plan ID。", true);
    return;
  }
  setBusy(ui.loadPlan, true, "加载中…");
  try {
    renderPlan(await api(`/api/v1/plans/${encodeURIComponent(planId)}`));
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setBusy(ui.loadPlan, false, "");
  }
}

async function approvePlan() {
  clearNotice();
  setBusy(ui.approvePlan, true, "批准中…");
  try {
    const plan = await api(`/api/v1/plans/${encodeURIComponent(state.plan.plan_id)}/approve`, {
      method: "POST",
    });
    renderPlan(plan);
    showNotice("计划已批准。此时仍未执行；请点击“执行确定性工作流”。");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setBusy(ui.approvePlan, false, "");
  }
}

async function rejectPlan() {
  const reason = window.prompt("请输入拒绝原因（会记录到计划中）：");
  if (!reason?.trim()) return;
  clearNotice();
  setBusy(ui.rejectPlan, true, "拒绝中…");
  try {
    const plan = await api(`/api/v1/plans/${encodeURIComponent(state.plan.plan_id)}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason: reason.trim() }),
    });
    renderPlan(plan);
    showNotice("计划已拒绝，不会执行任何分析步骤。", false);
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setBusy(ui.rejectPlan, false, "");
  }
}

function renderRun(run) {
  state.run = run;
  ui.runPanel.hidden = false;
  ui.runSummary.replaceChildren();
  const summary = document.createElement("div");
  summary.className = "summary-line";
  summary.append(makeBadge(run.status));
  const id = document.createElement("span");
  id.textContent = run.run_id;
  summary.append(id);
  ui.runSummary.append(summary);

  ui.runSteps.replaceChildren();
  ui.artifactLinks.replaceChildren();
  let firstGeoJson = null;
  for (const step of run.steps) {
    const item = document.createElement("li");
    item.className = step.status;
    const title = document.createElement("strong");
    title.textContent = `${String(step.step_id).padStart(2, "0")} · ${step.operation}`;
    const detail = document.createElement("p");
    detail.textContent = step.error_message || `${step.output} · ${step.status}`;
    item.append(title, detail);
    ui.runSteps.append(item);

    const suffix = (step.artifact_path || "").toLowerCase();
    if (step.status === "succeeded" && (suffix.endsWith(".geojson") || suffix.endsWith(".md"))) {
      const url = `/api/v1/runs/${encodeURIComponent(run.run_id)}/artifacts/${encodeURIComponent(step.output)}`;
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = `${suffix.endsWith(".geojson") ? "地图" : "报告"} · ${step.output} ↗`;
      ui.artifactLinks.append(link);
      if (!firstGeoJson && suffix.endsWith(".geojson")) firstGeoJson = url;
    }
  }
  if (firstGeoJson) loadGeoJson(firstGeoJson);
}

async function executePlan() {
  clearNotice();
  setBusy(ui.executePlan, true, "正在执行与验证…");
  try {
    const run = await api(`/api/v1/plans/${encodeURIComponent(state.plan.plan_id)}/execute`, {
      method: "POST",
    });
    renderRun(run);
    showNotice(`执行完成：${run.run_id} · ${run.status}`);
    ui.runPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setBusy(ui.executePlan, false, "");
  }
}

function ensureMap() {
  if (state.map || typeof window.L === "undefined") return state.map;
  state.map = window.L.map("map", { zoomControl: true }).setView([31.23, 121.47], 12);
  window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(state.map);
  return state.map;
}

async function loadGeoJson(url) {
  try {
    const map = ensureMap();
    if (!map) {
      showNotice("地图组件未加载；仍可通过产物链接查看 GeoJSON。", true);
      return;
    }
    const geojson = await api(url, { headers: { Accept: "application/geo+json" } });
    if (state.geojsonLayer) state.geojsonLayer.remove();
    state.geojsonLayer = window.L.geoJSON(geojson, {
      style: {
        color: "#174f3b",
        weight: 2,
        fillColor: "#c9f36a",
        fillOpacity: 0.42,
      },
      pointToLayer: (_, latlng) =>
        window.L.circleMarker(latlng, {
          radius: 7,
          color: "#0d382a",
          fillColor: "#c9f36a",
          fillOpacity: 0.9,
        }),
      onEachFeature: (feature, layer) => {
        const properties = feature.properties || {};
        const rows = Object.entries(properties)
          .slice(0, 8)
          .map(([key, value]) => `${key}: ${String(value)}`)
          .join("\n");
        if (rows) {
          const tooltip = document.createElement("pre");
          tooltip.textContent = rows;
          layer.bindTooltip(tooltip, { sticky: true });
        }
      },
    }).addTo(map);
    const bounds = state.geojsonLayer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [24, 24] });
    ui.mapEmpty.classList.add("hidden");
    window.setTimeout(() => map.invalidateSize(), 100);
  } catch (error) {
    showNotice(`地图加载失败：${error.message}`, true);
  }
}

ui.inspectDataset.addEventListener("click", inspectDataset);
ui.runAgent.addEventListener("click", runAgent);
ui.loadPlan.addEventListener("click", loadPlan);
ui.approvePlan.addEventListener("click", approvePlan);
ui.rejectPlan.addEventListener("click", rejectPlan);
ui.executePlan.addEventListener("click", executePlan);

checkHealth();
ensureMap();
