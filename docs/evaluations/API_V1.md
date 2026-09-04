# GeoPilot FastAPI 产品入口 V1

完成日期：2026-09-04

## 目标

把已有 CLI、Agent 和确定性 GIS Workflow 提供为可被 Web UI 调用的本地 HTTP API，同时保持路径隔离、人工审批、结构化错误和脱敏 Trace。FastAPI 的安装、OpenAPI 与 TestClient 方式参考[官方教程](https://fastapi.tiangolo.com/tutorial/)和[官方 First Steps](https://fastapi.tiangolo.com/tutorial/first-steps/)。

## 实现

- 应用工厂与路由：`src/geopilot/api/app.py`
- 服务编排与错误映射：`src/geopilot/api/service.py`
- HTTP 请求/响应契约：`src/geopilot/api/models.py`
- 工具路径策略注入：`src/geopilot/agent/tool_adapters.py`
- 集成测试：`tests/test_api.py`
- FastAPI 入口：`pyproject.toml` 中 `geopilot.api.app:app`

V1 路由：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/v1/health` | 不依赖模型密钥的进程健康检查 |
| POST | `/api/v1/datasets/inspect` | 检查 workspace 内的数据集 |
| POST | `/api/v1/agent/runs` | 使用服务端模型配置运行 Agent |
| GET | `/api/v1/plans/{plan_id}` | 查看完整计划 |
| POST | `/api/v1/plans/{plan_id}/approve` | 显式批准 |
| POST | `/api/v1/plans/{plan_id}/reject` | 带理由拒绝 |
| POST | `/api/v1/plans/{plan_id}/execute` | 执行已批准计划 |
| GET | `/api/v1/runs/{run_id}` | 查看执行检查点 |
| POST | `/api/v1/runs/{run_id}/resume` | 恢复失败/中断运行 |
| GET | `/api/v1/traces` | 查询脱敏 Trace |

## 安全边界

- HTTP 请求不能传 API Key、Base URL 或任意 provider 凭据；模型配置只来自服务端 `.env`/环境变量。
- Dataset API 对相对/绝对路径做 `resolve`，结果必须位于配置的 workspace 内；`..` 和指向外部的符号链接不能越界。
- API 使用的 Agent Tool Registry 注入同一 `source_resolver`，因此限制不仅在直接 Dataset 路由，也覆盖 LLM 发起的 `inspect_dataset` 与 `recommend_metric_crs`。
- `WorkspacePlanStore` 在计划创建时校验全部原始数据集；API 在批准、执行和恢复前再次校验，可拦截旧 CLI 计划或手工文件中的外部路径。
- 执行器显式使用 API workspace 解析相对输入，不继承未知进程目录。
- Plan ID、Run ID、Prompt 长度、最大轮数、输出 token、namespace 和请求字段由 Pydantic/FastAPI 校验；错误使用稳定 JSON envelope。
- API 不配置 CORS，V1 仅建议绑定 `127.0.0.1`。尚无认证和授权，不能暴露到公网或不可信局域网。

## 测试证据

8 个 API 集成测试覆盖：

- health 与自动 OpenAPI；
- workspace 内 CSV 检查；
- `../` 路径穿越拦截；
- 请求校验错误 envelope 且不回显完整输入；
- mock 模型执行真实 Agent Loop + Tool Registry + Trace；
- 模型主动请求外部路径时工具返回安全失败；
- HTTP 查看、批准、重复批准冲突、执行和查询 Run；
- 拒绝批准工作区外的旧计划；
- Trace 状态过滤。

初次测试暴露 API 执行器仍以 `Path.cwd()` 解析相对数据路径，导致独立 workspace 计划失败。修复后 `execute(..., working_directory=workspace_root)`，8/8 通过。该问题没有通过修改断言规避。

最终全项目回归为 184 项测试通过，Ruff、格式检查和 Pyright 均为 0 错误；另以真实 Uvicorn 进程验证 health 和 OpenAPI 返回 HTTP 200。

## 当前边界

- API 请求是同步等待模型和 GIS 任务；没有队列、后台任务、取消、SSE/WebSocket 流式输出或幂等键。
- 文件仍由路径引用，没有浏览器上传、文件大小限制、病毒扫描和对象存储。
- 本地 JSON/JSONL Store 没有并发锁和事务数据库，不能安全承载多 worker 写入。
- 没有用户认证、RBAC、租户隔离、限流、CSRF/CORS 策略、TLS 或反向代理配置。
- Health 只证明进程可响应，不检查模型、索引和磁盘等依赖 readiness。
- 还没有 Web GIS 页面；Swagger `/docs` 只是开发期 API 调试界面。

## 下一步

在保持同源和 loopback 默认的前提下实现 Web GIS V1：任务输入、Agent 回答、计划审批卡片、运行步骤状态和 GeoJSON 地图预览。之后再引入后台 Job、数据库、认证和部署配置，不能把本地同步 API 描述成生产服务。
