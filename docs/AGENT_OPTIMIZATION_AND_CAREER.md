# GeoPilot Agent 组件优化与求职证据矩阵

## 文档目的

这份文档回答三个求职问题：GeoPilot 到底包含哪些 Agent 组件、每个组件下一步怎么优化、面试或简历凭什么证明做过。状态以仓库代码和实验为准；“计划优化”不能写成已实现。

卡码专栏逐项知识解释、GeoPilot 实现和项目化面试回答见 [卡码 Agent 知识与 GeoPilot 实现对照手册](KAMA_AGENT_GUIDE.md)；本文件继续作为精简的优化与证据矩阵。

学习主线参考[卡码大模型学习路线](https://notes.kamacoder.com/llm/)，工程补充参考卡码的 [Agent vs Workflow](https://notes.kamacoder.com/llm/app/agent_vs_workflow.html)、[工具设计](https://notes.kamacoder.com/llm/app/agent_tool_design.html)、[Memory](https://notes.kamacoder.com/llm/app/agent_memory.html)、[Agent Evaluation](https://notes.kamacoder.com/llm/app/agent_evaluation.html) 与 [MCP](https://notes.kamacoder.com/llm/app/mcp_protocol.html)。近期一手资料采用 Anthropic 的 [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)、[Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) 和 MCP 官方 [Architecture](https://modelcontextprotocol.io/docs/learn/architecture)。

## 总体设计判断

GeoPilot 采用 Agent + Workflow，而不是纯 Agent：LLM 处理自然语言理解、知识检索、工具选择和计划生成；代码状态机与 GeoPandas Workflow 处理审批、依赖、数值计算、写文件、验证和恢复。原因是公共服务覆盖问题的表达开放，但 CRS、距离单位、覆盖公式和文件副作用必须确定、可审计、可回放。

近期 Agent 工程更强调 Context Engineering：Prompt 只是上下文的一部分，工具定义、检索证据、消息历史、Memory、计划状态和权限信息都会占用有限 attention budget。GeoPilot 后续优化不以“把所有规则塞进 System Prompt”为目标，而以“在每一步提供最少但足够的高信号上下文”为目标。

## 组件优化矩阵

| 组件 | 当前真实实现与证据 | 下一步优化 | 验收指标 | 面试/简历可讲点 |
|---|---|---|---|---|
| 模型适配 | Provider-neutral `ChatModel`；两类 API；V1 已归一化 input/output/total/cache/reasoning usage | 按错误类型重试；将 usage 写入脱敏 Trace；可选模型路由与熔断 | Prompt 实验 usage 覆盖率 100%；429/timeout/5xx 分类测试 | 为什么业务层不绑定 SDK；缓存 token 与费用如何核算 |
| System Prompt | minimal/structured/few-shot catalog；6-Case DeepSeek V1；Few-shot 成功率 0.50、违规 0、效率 0.7944，但未升级默认 | 扩展 Case、多次重复/方差；Prompt 版本进 Trace；从重复检索失败驱动修改 | 相同 Case 回归；置信区间；token/质量 Pareto；Prompt 版本可追溯 | Few-shot 为什么有候选收益却不立即上线；Prompt 软约束与硬校验 |
| Context Engineering | RAG 按需、Memory Top-6/2000 字符、工具结果回到 Working Memory | 工具结果摘要/清理；按任务动态选择工具；长任务 compaction + 结构化 task note；为上下文各来源做 token budget | 平均上下文 token、冗余工具调用和任务成功率对照 | Prompt Engineering 与 Context Engineering 的区别；为什么长上下文不等于高质量 |
| Agent Loop | `plan/act/observe` 多轮循环；最大 6 轮；结构化 Tool Result | 增加 wall-clock/tool/token 总预算、取消信号、每类错误重试策略、重复/语义重复检测 | 超预算 100% 可终止；取消延迟；循环 Case 通过率 | 如何避免死循环和错误复合；为什么预算应是多维的 |
| Tool Registry | Pydantic JSON Schema、稳定名称/描述、可恢复错误；API 可注入路径 resolver | 工具能力标签（read/write/high-risk）；动态最小工具集；版本号与 deprecation；输出做 token-efficient 摘要 | 工具选择准确率、参数有效率、平均工具 Schema token | 工具不是 API 列表，而是模型的行动与权限边界 |
| GIS 工具 | 数据检查、CRS、缓冲、融合、求交、连接、验证、导出和报告均为确定性函数 | 增加栅格/网络可达性前先扩充领域测试；大数据改 PostGIS/GeoParquet；基准内存和耗时 | 几何/CRS/空结果属性测试；大数据基准 | 为什么不让 LLM 计算距离；GIS 的单位和投影风险 |
| Structured Planning | Pydantic 计划、稳定 output ID、语义校验、Compiler | 显式 DAG、计划 schema_version、计划迁移；把风险/权限要求编译进执行清单 | 非法依赖/旧版本/权限 Case；编译确定性 | “能生成 JSON”不等于“可执行计划” |
| Human-in-the-loop | `awaiting_approval → approved/rejected`；审批后才执行 | 审批凭证绑定 plan hash/version/用户/有效期；按风险分级；执行前检测数据或计划变更 | 篡改/过期/重复审批测试；高风险确认率 | 批准的是精确计划，不是给 Agent 永久权限 |
| Durable Execution | RunStore 步骤检查点、失败停止、产物存在性检查、恢复 | SQLite/Postgres 事务；幂等键；lease/锁；队列 Worker；取消与重试状态 | crash/restart/并发/重复请求测试；恢复成功率 | Session State 与聊天 Memory 的区别 |
| RAG/Embedding | 3 文档、19 Chunk；BGE-small-zh；token 护栏；Dense+BM25+RRF；20 Query 评测 | 增量索引、metadata filter、Query rewrite/HyDE 对照、相似度拒答、引用真实性检查 | Retrieval + Faithfulness + Citation Precision；无答案拒答率 | 为什么 Rerank 实现了却默认关闭；用指标否决复杂度 |
| Long-term Memory | 用户确认写入；三种类型；namespace/revision/过期/删除；词法召回 | `proposed → approved` 记忆写入；语义+新鲜度+类型混排；冲突合并；加密与租户授权 | 错召回/过期泄漏/跨租户率；用户删除可验证 | Memory、Session State、RAG 四层边界 |
| Agent Eval | 4 条结果/过程/安全 Case；Task Success 0.75；Correct Failure/工具/效率指标 | 扩展 normal/noisy/missing/high-risk/tool-failure/plan-correction；增加 partial outcome；人工集 + 独立 LLM Judge | 版本对照、置信区间、重复运行方差；回归门禁 | 为什么答案正确但冗余二次检索仍失败 |
| Observability | 脱敏 JSONL：Prompt hash、模型、耗时、轮数、工具状态；不存正文 | trace/span correlation、Prompt/工具版本、token/cost、线上聚合告警、采样与保留策略 | Trace 覆盖率；工具失败/超时/接管率；敏感信息扫描 | 可观测性与日志堆积的区别；隐私和可调试性的权衡 |
| FastAPI | health、Dataset、Agent、Plan、Run、Trace；workspace 路径限制；稳定错误 | 后台 Job + SSE；上传白名单/限额；认证/RBAC/限流；幂等键；CORS/TLS | API 契约、路径穿越、重复提交、并发和负载测试 | 为什么 HTTP 入口需要比本机 CLI 更严格的能力边界 |
| Web GIS | 同源响应式 UI；预检、Agent 工具摘要、结构化 Plan ID、审批、Run 检查点、受控 GeoJSON/Markdown 产物、Leaflet 地图 | Job + SSE；上传安全；多图层；Playwright E2E；大数据简化/瓦片 | 核心流程 E2E；首状态/地图加载延迟；人工接管率；地图 CRS/空结果/大 GeoJSON | 为什么不是聊天框；如何把 Agent 的证据和权限交还给用户 |
| MCP | 未实现 | 先发布只读 `inspect_dataset`/`recommend_metric_crs`；复用 Schema 和 workspace policy；再评估远程 Streamable HTTP | Inspector 契约、协议版本、权限/路径、外部客户端调用 | MCP Host/Client/Server、tools/resources/prompts；MCP 不替代 Function Calling |
| Multi-Agent | 未实现且不是当前优先级 | 只有子任务不可预知且可并行、单 Agent 成为瓶颈时做 orchestrator-workers 对照 | 相对单 Agent 的质量、延迟、成本和冲突率 | 不为热点堆架构；先证明并行收益再增加协调复杂度 |
| 部署与安全 | `.env`、ignored artifacts、本地 API、测试门禁 | Docker 非 root、CI、SBOM/依赖扫描、Secret scan、数据库备份、认证和审计 | 镜像复现、CI 全绿、漏洞门禁、恢复演练 | “本地可运行”与“生产可用”的具体差距 |

## 当前组件调用图

```text
CLI / Local FastAPI
        ↓
Context Assembly
├── System Prompt 0.8.0
├── Working Memory
├── user-confirmed Long-term Memory
├── Agentic RAG evidence
└── task-scoped Tool Schemas
        ↓
Provider-neutral Agent Loop
        ↕
read-only inspection / knowledge / CRS tools
        ↓
structured plan → semantic validation → human approval
        ↓
compiler → deterministic GIS workflow → checkpoints → validated artifacts
        ↓
Agent Eval + redacted Trace
```

## 推荐的后续开发顺序

这里的顺序按“Agent 学习和求职证据”排列，不按产品功能数量排列：

1. 已完成 Prompt 与结构化输出实验 V1；证据见 `docs/evaluations/PROMPT_EXPERIMENT_V1.md`。
2. **当前下一阶段**：Function Calling 与工具设计实验，审计工具粒度、Schema、返回值和动态最小工具集。
3. Agent 模式实验：同题比较直接 Tool Calling、ReAct、Plan-and-Execute 和一次 Reflection 验证的收益与成本。
4. RAG 生成侧与 Context Engineering：Query 改写、拒答、上下文预算/压缩、Faithfulness 和引用评估。
5. MCP：先发布两个只读 GIS 工具，用独立 Client 验证互操作与 workspace 权限。
6. 扩展 Guardrail、Memory 和 Agent Eval，增加故障、污染、高风险与生成质量 Case。
7. 核心 Agent 组件形成完整证据后，再回到 Job/SSE、数据库、认证、Docker 和 CI/CD。
8. 只有评测证明单 Agent 无法有效处理可并行复杂 GIS 调研时，才试验 Multi-Agent。

## 简历证据包

面试前应准备并能现场指出：

- 架构：`docs/AGENT_COMPONENTS.md` 的真实调用链和 Agent/Workflow 边界。
- 代码：`agent/runner.py`、`agent/registry.py`、`planning/`、`execution/`、`rag/`、`memory/`、`evaluation/`、`observability/`、`api/`。
- 测试：正常、错误、路径越界、审批冲突、恢复、RAG 排名、Memory 隔离和 Trace 脱敏。
- 指标：Hybrid Recall/MRR/NDCG、Rerank 退化与 CPU 延迟、Agent Task Success/工具召回/正确失败。
- 失败复盘：Rerank 不值得默认启用；Agent RAG Case 因二次检索超过预算；API 独立 workspace 首次解析错误。
- 安全边界：API Key 服务端管理、Path resolver、审批状态机、确定性 GIS 计算、Trace 不保存正文。
- 未实现：认证、队列、多 worker、浏览器 E2E、MCP、生产部署和生成侧 Judge；回答时主动说明，而不是等面试官拆穿。

## 当前可用简历描述

> 设计并实现自然语言驱动的 GeoPilot GIS Agent：基于 Provider-neutral LLM Adapter 与 Pydantic Function Calling 完成数据检查、RAG 检索、结构化规划和人工审批，并由可恢复的确定性 GeoPandas Workflow 执行 13 步空间覆盖分析；构建 BGE 中文 Embedding + BM25/Dense/RRF 混合检索，在 20 条困难 Query 上取得 Recall@3/MRR/NDCG@3 0.975/0.975/0.952，并通过对照实验否决高延迟 Rerank 默认上线；实现用户确认型长期记忆、结果/过程/安全 Agent Eval、脱敏 Trace、workspace 隔离的 FastAPI 和展示审批/检查点/GeoJSON 的 Web GIS。

FastAPI + Web GIS 阶段已经通过 186 项全量测试；提交后可使用这段描述。仍不能写“生产级”“高并发”“多 Agent”“MCP 已接入”或虚构用户量。

## 面试准备顺序

1. 60 秒说明业务问题、Agent/Workflow 边界和完整链路。
2. 解释一次 Function Calling 的消息循环与 Pydantic 校验。
3. 画出规划、审批、Compiler、Dispatcher、RunStore 的状态流。
4. 解释 GIS 的 CRS/单位风险及为什么数值计算必须确定性。
5. 解释 Chunk、Embedding、BM25、RRF、Rerank 和五个检索指标。
6. 解释 Working Memory、Session State、Long-term Memory、RAG。
7. 用两个负结果证明评测意识：Rerank 退化、Agent 二次检索超预算。
8. 解释 API 路径越界、审批权限、Trace 脱敏和生产差距。
9. 解释 MCP 与 Function Calling 的区别，以及为什么现在还没接。
