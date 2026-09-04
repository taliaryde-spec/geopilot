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
| 6 | GIS 执行工具 | 已完成 | CRS、重投影、面积、缓冲、合并、求交、覆盖指标、恢复、连接、验证、导出与报告 |
| 7 | Approved Plan Executor | 已完成 | 稳定产物 ID、严格参数契约、依赖编译、运行存储、工具调度、失败停止、检查点恢复与 CLI |
| 8 | RAG 与 Embedding | 检索侧阶段完成 | 已完成结构感知切块、token 超限护栏、FastEmbed、BM25、RRF、20 条困难集、可选 Cross-Encoder 与控制变量实验；Rerank 实测无收益故默认关闭，生成侧评估并入阶段 10 |
| 9 | Memory | 安全第一版完成 | 已区分 Working Memory、Session State、Long-term Memory 与 RAG；实现用户确认写入、namespace、revision、过期、删除、相关召回、Prompt 边界与关闭开关 |
| 10 | Eval 与可观测性 | 规则评测与脱敏 Trace V1 完成 | 已有 4 条版本化 Agent Case、任务/工具/正确失败/步骤/安全指标和 JSONL Trace；生成忠实度 Judge、token/成本、集中监控待补 |
| 11 | 产品与部署 | FastAPI + Web GIS V1 完成 | 已实现 workspace 隔离 API、结构化 Plan ID、审批/检查点/受控产物地图和 10 项 API/Web 测试；后台 Job、上传、数据库、认证、Docker、CI/CD 待补 |
| 12 | MCP | 待开始 | 将稳定 GIS 工具发布为可复用 MCP Server |

## 开发原则

- LLM 负责理解、规划和选择工具；GeoPandas 负责确定性计算。
- Prompt、工具输入、工具输出和 Agent 状态都使用版本化结构。
- 高风险分析必须先展示计划并等待用户确认。
- 工具失败、缺少 CRS 或无效几何时禁止编造结果。
- RAG 用于检索知识与规范，不代替空间数据计算。
- Memory 必须区分当前任务状态与跨会话长期信息。
- 每个阶段都必须包含测试、文档、可观测性和明确验收标准。

## 2026-09-04 后续优先级纠偏

项目的首要目标是让开发者完整掌握大模型应用与 Agent 组件，并形成能用于简历和面试的代码、实验和回答；Web 页面只是展示入口。因此后续不以 Job/SSE、页面功能或部署数量作为主线。

新的核心顺序是：

1. Prompt、模型调用与结构化输出控制变量实验；
2. Function Calling 与工具设计优化；
3. ReAct、Plan-and-Execute、Reflection 的同题对比；
4. RAG 生成质量与 Context Engineering；
5. 只读 GIS MCP Server 与独立 Client 验证；
6. Guardrails、Memory 与 Agent Eval 扩展；
7. 最后再恢复 Job/SSE、认证、数据库、容器和部署支线。

每个组件必须完成：原理讲解、源码定位、亲手实践点、正常/失败测试、真实模型或可复现实验、指标与取舍、双文档更新、面试问答和诚实简历表述。已有组件不能因为“代码已经写过”就跳过这套学习闭环。
