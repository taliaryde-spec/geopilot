# GeoPilot Web GIS V1

完成日期：2026-09-04

## 目标

把已经验证的 Agent、Human-in-the-loop 和确定性 GIS Workflow 变成可展示的本地产品，而不是给已有 CLI 外面套一个聊天框。页面必须让用户看到任务、工具证据、结构化计划、风险、审批状态、执行检查点、GeoJSON 地图和 Markdown 报告入口。

## 实现

- 页面结构：`src/geopilot/web/index.html`
- 响应式视觉与状态样式：`src/geopilot/web/styles.css`
- API 编排、DOM 安全渲染和 Leaflet 地图：`src/geopilot/web/app.js`
- 静态页面与受控产物路由：`src/geopilot/api/app.py`
- Plan ID 和产物解析服务：`src/geopilot/api/models.py`、`src/geopilot/api/service.py`
- 集成测试：`tests/test_api.py`

启动：

```powershell
uv run fastapi dev
```

访问 `http://127.0.0.1:8000/`。页面支持：

1. 对 workspace 内的数据集做确定性预检；
2. 向 Agent 提交任务并展示回答、工具成功/失败摘要和 Trace ID；
3. 从 API 的结构化 `plan_ids` 自动加载计划，不解析模型自然语言；
4. 展示每步 operation、说明和风险等级，由用户批准或拒绝；
5. 用户再次点击后才执行确定性 Workflow，展示 Run 和逐步检查点；
6. 加载第一个成功的 GeoJSON 产物到 Leaflet，并提供 GeoJSON/Markdown 产物链接。

## Agent 与前端的边界

前端不实现 Agent 推理，也不保存 API Key。它只调用同源 `/api/v1`；provider、endpoint、Prompt 规则、Tool Registry 和 Memory/RAG 装配仍由服务端控制。Agent 回答、工具名、数据属性和错误都通过 `textContent` 或 DOM 文本节点渲染，不使用 `innerHTML`，避免把模型或数据内容当作可执行 HTML。

`AgentRunResponse.plan_ids` 来自成功的 `submit_analysis_plan` Tool Result，而不是从最终回答中用正则提取。这保证 UI 审批的是应用实际持久化的计划 ID。

## 产物安全

浏览器不接收本地绝对路径来直接访问文件。`GET /api/v1/runs/{run_id}/artifacts/{output}`：

- 先从 RunStore 加载合法 Run；
- 按稳定 `output` 查找成功步骤，而不是接收任意文件路径；
- 将登记的 artifact path 规范化，并再次要求它位于对应 Run 目录；
- 只允许 `.geojson` 和 `.md`，GeoPackage 返回 415；
- 缺失、未完成、越界和不支持格式使用稳定错误代码。

GeoJSON 在确定性导出工具中统一转换为 `EPSG:4326`，地图只负责展示，不在浏览器重新做分析投影或距离计算。

## 测试证据

API/Web 测试由 8 项增至 10 项，新增覆盖：

- `/`、`/static/app.js` 和 `/static/styles.css` 可访问；
- 脚本不包含 `innerHTML`；
- Agent 结构化返回实际提交的 Plan ID；
- 成功 GeoJSON 产物以 `application/geo+json` 返回；
- GeoPackage 不能通过 Web 产物路由读取。

本轮最终全项目回归为 186 项测试通过，Ruff、格式检查和 Pyright 均为 0 错误；前端 JavaScript 额外通过 `node --check` 语法验证。

使用隔离的项目内 uv cache 运行 `uv build`，成功生成 sdist 和 wheel；wheel 内容检查确认 `geopilot/web/index.html`、`styles.css` 与 `app.js` 被打包，不会只在源码 checkout 中可用。

## 当前限制

- Agent 和执行仍是同步 HTTP，请求期间页面等待；不能实时看到正在运行的中间步骤。
- 没有文件上传、拖拽图层、空间参数表单、地图编辑或结果对比。
- Leaflet 1.9.4 和 OpenStreetMap 底图使用外部网络；离线时仍能使用 API 和下载 GeoJSON，但地图组件/底图可能不可用。
- 当前自动化验证 API、静态资源和 JS 语法，没有 Playwright 浏览器 E2E、视觉回归或无障碍审计。
- 没有认证、RBAC、CSP、限流、CSRF 策略和公网部署加固，只建议 loopback。
- 页面只自动加载 Run 中第一个 GeoJSON；多个图层开关和大文件矢量瓦片尚未实现。

## 下一步优化与验收

以下内容保留为产品工程待办，不代表紧接着实施；2026-09-04 主线纠偏后，下一阶段先完成 Prompt 与结构化输出实验。

1. 将 Agent/执行改为后台 Job + SSE，创建任务立即返回 `job_id`；验收取消、断线重连、状态顺序和超时。
2. 增加上传白名单、大小/要素数限制、隔离目录与数据删除生命周期。
3. 增加 Playwright 核心路径：预检 → 生成计划 → 批准 → 执行 → 地图。
4. 记录前端感知延迟、任务成功率、人工拒绝/接管率和地图加载耗时。
5. 数据规模增大后评估 GeoParquet/PostGIS、简化和矢量瓦片，不能直接把大 GeoJSON 塞给浏览器。
