# GeoPilot 完整 Agent 项目路线图

本文档用于保证 GeoPilot 最终覆盖大模型应用开发的完整组件，而不是只完成一个 GIS 脚本或聊天机器人。

## 总体架构

```text
CLI / Web UI / API
        ↓
Agent Runtime
├── LLM Adapter
├── System Prompt
├── Planner + Human Approval
├── Working / Long-term Memory
├── Tool Registry
└── Guardrails
        ↓
GIS Tools             RAG Pipeline
├── Intake            ├── Documents
├── Projection        ├── Chunking
├── Buffer            ├── Embedding
├── Spatial Join      ├── Vector Store
└── Reporting         └── Retrieval
        ↓
Evaluation / Tracing / Storage / Deployment / MCP
```

## 分阶段交付

| 阶段 | 组件 | 状态 | 完成标准 |
|---|---|---|---|
| 1 | 工程基础 | 已完成 | uv、src 布局、Git、Ruff、Pyright、Pytest |
| 2 | 数据接入 | 已完成 | GeoJSON、Shapefile、CSV、CRS 与几何验证 |
| 3 | Agent 核心 | 已完成 | Prompt、模型接口、Tool Registry、Agent Loop、工作记忆 |
| 4 | 真实 LLM | 已完成 | OpenAI Responses、DeepSeek/OpenRouter Chat Completions、配置、错误边界与 DeepSeek Tool Calling 实测 |
| 5 | 规划与审批 | 已完成 | 结构化计划、语义护栏、文件检查点、批准/拒绝状态机及 DeepSeek 多轮纠错实测 |
| 6 | GIS 执行工具 | 进行中 | 已完成确定性米制 CRS 推荐；待实现重投影、缓冲区、空间连接、结果验证与报告 |
| 7 | RAG 与 Embedding | 待开始 | 文档加载、切块、向量化、检索、引用与离线评测 |
| 8 | Memory | 待开始 | 会话状态、任务检查点、用户偏好、长期记忆边界 |
| 9 | Eval 与可观测性 | 待开始 | 测试集、工具成功率、幻觉率、Tracing、日志、成本 |
| 10 | 产品与部署 | 待开始 | FastAPI、Web UI、数据库、Docker、CI/CD、安全 |
| 11 | MCP | 待开始 | 将稳定 GIS 工具发布为可复用 MCP Server |

## 开发原则

- LLM 负责理解、规划和选择工具；GeoPandas 负责确定性计算。
- Prompt、工具输入、工具输出和 Agent 状态都使用版本化结构。
- 高风险分析必须先展示计划并等待用户确认。
- 工具失败、缺少 CRS 或无效几何时禁止编造结果。
- RAG 用于检索知识与规范，不代替空间数据计算。
- Memory 必须区分当前任务状态与跨会话长期信息。
- 每个阶段都必须包含测试、文档、可观测性和明确验收标准。
