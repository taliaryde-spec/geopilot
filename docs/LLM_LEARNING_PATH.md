# GeoPilot 大模型学习与面试主线

GeoPilot 后续大模型部分以[卡码大模型学习路线](https://notes.kamacoder.com/llm/)作为知识框架参考，并用 GIS Agent 的实际代码完成每个知识点。外部教程用于组织学习和准备面试，GeoPilot 的功能边界、技术选型和指标仍必须由本仓库的代码、测试与实验结果证明。

所有组件的实现与迭代统一追加到 [Agent 组件与工程实现记录](AGENT_COMPONENTS.md)，所有项目化面试回答统一追加到 [Agent 面试问题与项目化回答](AGENT_INTERVIEW_QA.md)。

## 主线纠偏：学习 Agent 组件，而不是继续堆产品功能

2026-09-04 起，GeoPilot 的优先级从“继续扩展页面和部署能力”调整为“系统掌握 Agent 组件”。FastAPI 与 Web GIS 保留为可演示入口，但后台 Job、SSE、认证和部署暂时降为支线。原因是本项目首先服务于学习、简历和面试：必须能解释 Prompt、Function Calling、Agent 模式、RAG、Context、Memory、Guardrail、Eval 与 MCP 如何实现和优化，而不只是展示一个能运行的页面。

主线参考卡码的 Agent 六步路线，并根据 GeoPilot 已有代码采用“已有能力补实验、缺失能力再实现”的方式：

| 顺序 | 学习组件 | GeoPilot 当前基础 | 下一次实践与实验 | 必须形成的面试证据 |
|---|---|---|---|---|
| 1 | Prompt、模型调用、结构化输出 | **V1 已完成**：Prompt catalog、6 条 Case、三组 DeepSeek 对照、usage 归一化 | 扩展 Case 并每组重复多次；将 Prompt/tool 版本和 Token 写入 Trace | Few-shot 提升但未盲目上线；Prompt 软约束与 Schema/语义校验硬约束；Token/延迟/成本取舍 |
| 2 | Function Calling 与工具设计 | Agent Loop、Tool Registry、GIS/RAG/Plan 工具已存在 | 审计工具粒度、名称、描述、参数和返回值；比较全量工具与按任务最小工具集 | 一次 Function Calling 完整消息流；参数 Schema；工具错误；为什么工具也是权限边界 |
| 3 | Agent 模式 | 当前 Loop 属于工具调用型 ReAct，另有 Plan-and-Execute Workflow | 用同一 GIS 任务比较直接工具调用、Plan-and-Execute、带一次验证的 Reflection；不要求模型输出隐藏思维链 | 三种模式的适用场景、成本、延迟、失败模式；为什么 GeoPilot 采用 Agent + Workflow |
| 4 | RAG 与 Agentic RAG | Chunking、BGE Embedding、Dense/BM25/RRF、可选 Rerank 和检索评测已存在 | 补 Query 改写/拒答/Context 压缩对照；增加答案 Faithfulness、Citation Precision 与无答案集 | Chunk/Embedding/向量库/Hybrid/Rerank；召回问题与生成问题如何定位 |
| 5 | Context Engineering | Prompt、RAG、Memory、工具结果已分层，但没有统一 token budget | 实现上下文清单、token 估算、动态工具集、工具结果摘要/清理；比较质量、步骤与成本 | Prompt Engineering 与 Context Engineering；检索、筛选、排序、压缩、组装 |
| 6 | 工具协议 MCP | 尚未实现，已有稳定 Pydantic 工具和 workspace policy | 发布只读 `inspect_dataset`、`recommend_metric_crs` MCP Server；用独立 Client 做契约、权限和互操作测试 | Host/Client/Server；tools/resources/prompts；MCP 与 Function Calling 的区别 |
| 7 | Guardrails 与故障兜底 | 最大轮数、路径隔离、计划校验、人工审批、正确失败已有 | 增加死循环、误调用、Prompt Injection、工具超时、计划篡改和高风险 Case | 防御分层；可恢复/不可恢复错误；Human-in-the-loop 不是万能安全措施 |
| 8 | Memory 与 Eval | 四层状态边界、确认型长期记忆、规则 Eval 和脱敏 Trace 已存在 | 扩大黄金集；增加记忆冲突/污染评测、独立生成 Judge、token/成本和版本对照 | Memory/RAG/Session 区别；结果/过程/安全评测；LLM Judge 的偏差 |
| 9 | 产品部署支线 | FastAPI + Web GIS V1 已完成 | 等核心组件补齐后再做 Job/SSE、数据库、认证、Docker 和 CI/CD | 能说明同步/异步、TTFT/TPOT/吞吐，但不抢占 Agent 学习主线 |

Prompt 与结构化输出实验 V1 已完成；当前下一阶段固定为“Function Calling 与工具设计实验”，优先比较全量工具和按任务动态最小工具集，同时回应本次 Token 与冗余调用问题。每个阶段都按“先讲原理 → 指出源码 → 修改代码 → 跑实验 → 分析失败 → 更新双文档 → 形成简历/面试表述”推进。

## 每一步的完成标准

从本阶段开始，一个大模型组件只有同时具备以下内容，才算完成一次可用于简历的迭代：

1. 原理：能解释它在完整链路中的位置，以及解决什么问题。
2. 实现：仓库中存在可运行代码，并能指出核心文件。
3. 测试：正常路径、失败路径和关键数学逻辑有自动化测试。
4. 实验：使用真实模型或真实 Agent 运行，记录参数和量化结果。
5. 取舍：说明为什么选择当前方案、什么时候应替换，以及未实现的边界。
6. 面试：形成项目化回答，不只背通用定义。
7. 简历：指标稳定后再写简历描述，不把小样本结果包装成生产结论。

## 教程章节与项目映射

| 教程主题 | GeoPilot 对应实现 | 当前状态 | 后续证据 |
|---|---|---|---|
| Prompt 与模型调用 | `agent/prompting/`、模型适配器、`evaluation/prompt_experiment.py` | V1 已完成 | 6 条 Case、3 组 Prompt、Task Success/Schema/工具/步骤/Token/延迟指标；Few-shot 暂不升级默认 |
| Function Calling | Tool Registry、数据检查、CRS、计划提交、知识检索 | 已实测 | DeepSeek 多轮工具调用、错误纠正轨迹 |
| RAG 离线链路 | 文档加载、结构感知切块、同模型 tokenizer 检查、Embedding、索引 | 第一版完成 | 3 文档、19 chunks、512 维索引；超限构建前失败 |
| RAG 在线链路 | Query Embedding、Dense + BM25、RRF、可选 Cross-Encoder、引用、Agent 工具 | 检索侧完成 | Dense/Hybrid/Rerank 对照与章节级黄金集 |
| RAG 优化 | 混合检索与 Rerank 已评估；Rerank 无收益故默认关闭 | 当前阶段完成 | 20 Query、24 标签的控制变量实验 |
| RAG 评估 | Precision、Recall、MRR、NDCG | 检索侧完成 | `docs/evaluations/RAG_RERANK_V1.md` |
| Agent 设计 | LLM 决策 + 确定性 Workflow + 人工审批 | 核心闭环完成 | 结构化计划、执行恢复与真实 Tool Calling |
| Agent Eval 与 Trace | 结果/过程/安全规则评测、正确失败、脱敏 JSONL | V1 完成 | 4-Case DeepSeek Task Success 0.75；当前全项目 186 项自动化测试 |
| Memory | 工作记忆、任务状态、长期偏好/目标/背景 | 安全第一版完成 | 用户确认、namespace、revision、过期、删除、词法召回和 Prompt 边界 |
| Context Engineering | Prompt、工具 Schema、RAG、Memory、工具结果的高信号上下文组织 | 基础分层完成 | 下一步加入 token budget、压缩、拒答阈值和上下文版本 Trace |
| MCP | 对外发布稳定 GIS 工具 | 待开始 | MCP Server、外部客户端调用测试 |
| 部署与工程化 | API、Web GIS、容器、CI/CD、监控 | FastAPI + Web GIS V1 完成 | 10 项 API/Web 测试覆盖契约、路径、Plan ID 与受控产物；Job、E2E、认证和负载指标待补 |
| Transformer 与微调 | 应用开发所需原理和选型边界 | 学习阶段待开展 | 原理笔记、选型题，不为了简历盲目训练模型 |

## 当前 RAG 学习顺序

教程将 RAG 拆为离线与在线两段，并强调先建立评估 baseline，再一次只调整一个变量。GeoPilot 采用以下顺序：

1. 已完成：受控 GIS 文档、结构感知 + 递归字符切块、本地中文 Embedding、精确余弦检索和引用。
2. 已完成：章节与正文片段级黄金标签，Precision@K、Recall@K、MRR、NDCG@K。
3. 已完成：固定 Embedding 和知识库，对比四组 chunk size/overlap，选择 `500/80`。
4. 已完成：用 BGE 的真实 tokenizer 统计完整 Embedding 输入，并在正式建库前拒绝超限 Chunk。
5. 已完成：加入透明 BM25 关键词检索，用 RRF 与 Dense 融合；默认 Hybrid 在当前小样本上改善 MRR/NDCG。
6. 已完成：扩充为 20 条困难 Query、24 个标签，以 12 个 Hybrid 候选对照 `BAAI/bge-reranker-base`；Rerank 的 Recall/NDCG 下降且 CPU 延迟显著增加，因此默认关闭。
7. 后续生成评测：增加回答忠实度、答案相关性、引用正确率和拒答评估；完整 Agent 的过程规则评测已在 V1 实现。

Memory V1 已完成：区分 Working Memory、Plan/Run Session State、Long-term Memory 与 RAG；只允许用户确认的三类稳定信息，并实现作用域、更新、过期、删除、相关召回和 `--no-memory`。

Agent Eval 与可观测性 V1 也已完成：4 条通用 Agent Case 的真实 DeepSeek Task Success/Required Tool Recall/Error Recovery 为 0.75/1.0/1.0。Prompt V1 又用 6 条任务比较三组系统提示，Few-shot 的 Task Success/Forbidden Violation/Step Efficiency 为 0.50/0/0.7944，但只跑一次且 Token 增长，暂不替换默认。普通 Agent 默认写入不含 Prompt/参数/输出正文的脱敏 JSONL Trace。

本地 FastAPI 与 Web GIS V1 已完成：`src/geopilot/api/` 将 Dataset、Agent、Plan、Run 和 Trace 暴露为版本化 JSON API，并把请求路径、模型生成的工具路径、旧计划审批和执行目录统一限制在 workspace；`src/geopilot/web/` 展示工具证据、结构化计划、人工审批、Run 检查点和受控 GeoJSON。10 项 API/Web 集成测试通过。它仍是同步、无认证的 loopback 产品入口，下一步是后台 Job/SSE、浏览器 E2E 与安全部署能力。

近期 Agent 工程学习从“只写更长 Prompt”升级为 Context Engineering：控制模型每一步能看到的 Prompt、工具说明、RAG、Memory 和工具结果，优先保留高信号、按需加载的上下文。GeoPilot 当前已完成来源分层，后续用 token/成本、步骤效率和任务成功率验证压缩或检索策略，不能只凭主观观感优化。

## 主要参考

- [RAG 完整链路：离线阶段与在线阶段](https://notes.kamacoder.com/llm/app/chain_of_rag.html)
- [Embedding、模型选型与 Rerank 区别](https://notes.kamacoder.com/llm/app/embedding.html)
- [四种 Chunking 策略对比](https://notes.kamacoder.com/llm/app/how_to_chunking.html)
- [RAG 检索与生成评估体系](https://notes.kamacoder.com/llm/app/rag_evaluation.html)
- [Agent 的短期记忆、Session State、长期记忆与 RAG](https://notes.kamacoder.com/llm/app/agent_memory.html)
- [Agent 任务完成率、步骤效率与错误恢复评估](https://notes.kamacoder.com/llm/app/agent_evaluation.html)
- [Agent 与 Workflow 的工程边界](https://notes.kamacoder.com/llm/app/agent_vs_workflow.html)
- [Agent 工具设计](https://notes.kamacoder.com/llm/app/agent_tool_design.html)
- [Anthropic：Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic：Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [MCP 官方架构](https://modelcontextprotocol.io/docs/learn/architecture)
