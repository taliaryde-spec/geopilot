# GeoPilot Agent 组件与工程实现记录

## 文档职责与维护规则

这是第一份持续追加的 Agent 主文档，记录 GeoPilot **实际采用的方法**。每次 Agent 相关代码、参数、实验指标或架构边界发生有意义的变化，都必须在文末“迭代记录”追加日期、变更、证据、取舍和下一步，并同步更新 [Agent 面试问题与项目化回答](AGENT_INTERVIEW_QA.md)。

本文件只记录已经由源码、测试或真实运行证明的事实；规划中的功能必须明确标记为“未实现”，不能因为出现在路线图里就写成已完成。

这份文档区分“已经形成第一条可运行闭环”和“完整大模型应用的全部组件”。第一条闭环是：自然语言问题 → LLM 规划与工具调用 → 人工审批 → 确定性 GIS 执行 → 验证 → 地图数据与报告。RAG/Embedding、用户确认型长期记忆、Agent Eval V1 和脱敏 Trace 已分别接入；生成答案语义评测、token/成本监控、Web UI 和 MCP 仍是后续独立阶段。

## 当前调用链

```text
用户自然语言
    ↓
CLI
    ↓
Long-term Memory 按 Query 过滤（可关闭）
    ↓
System Prompt + Agent Loop
    ↓
LLM Adapter（DeepSeek / OpenRouter / OpenAI）
    ↕ Tool Calling
数据检查 / CRS 推荐 / 本地知识检索 / 结构化计划提交
                    ↕
        Chunking → Embedding → Dense/BM25/RRF → 可选 Cross-Encoder
    ↓
PlanStore（awaiting_approval → approved / rejected）
    ↓ execute
计划编译器 → Dispatcher → 确定性 GIS 工具
    ↓
RunStore（步骤检查点、失败信息、产物元数据）
    ↓
GeoPackage / GeoJSON / Markdown

旁路质量链路：版本化 Agent Cases → 真实 Agent Run → 结果/过程/安全规则评分
旁路观测链路：普通 Agent Run → 脱敏 Trace JSONL → trace-list
```

## 已有组件及源码位置

| 组件 | 当前实现 | 主要位置 | 作用 |
|---|---|---|---|
| LLM 配置 | 已完成 | `src/geopilot/agent/config.py` | 从环境变量读取提供商、模型、API Key、Base URL 和输出 token 限制 |
| LLM 抽象接口 | 已完成 | `src/geopilot/agent/client.py` | 用统一接口隔离不同模型 API |
| DeepSeek / OpenRouter 适配 | 已完成 | `src/geopilot/agent/chat_completions.py` | 通过 OpenAI-compatible Chat Completions 调用模型与 Tool Calling |
| OpenAI 适配 | 已完成 | `src/geopilot/agent/openai_responses.py` | 对接 Responses API |
| 模型工厂 | 已完成 | `src/geopilot/agent/factory.py` | 根据配置选择实际模型适配器 |
| System Prompt | 已完成，持续迭代 | `src/geopilot/agent/prompts.py` | 定义 GIS 安全规则、规划规则、工具参数和禁止编造约束 |
| Agent Loop | 已完成 | `src/geopilot/agent/runner.py` | 维护单次任务消息、循环请求模型、执行工具调用并返回工具结果 |
| Tool Registry | 已完成 | `src/geopilot/agent/registry.py` | 注册工具定义、校验参数并根据工具名调用 |
| LLM 工具适配 | 已完成 | `src/geopilot/agent/tool_adapters.py` | 把数据检查、CRS 推荐和计划提交暴露为模型可调用工具 |
| 结构化规划 | 已完成 | `src/geopilot/planning/models.py` | 使用 Pydantic 定义计划、步骤、风险、输入、参数和稳定产物 ID |
| Guardrails | 已完成第一版 | `src/geopilot/planning/validator.py` | 拒绝错误 CRS、错误覆盖计算顺序、缺失字段、含糊空间连接等计划 |
| Human-in-the-loop | 已完成 | `src/geopilot/planning/store.py` | 计划必须经过批准后才能执行 |
| GIS 工具层 | 已完成当前矢量 MVP | `src/geopilot/tools/` | GeoPandas 负责重投影、缓冲、求交、统计、验证和报告 |
| 计划编译器 | 已完成 | `src/geopilot/execution/compiler.py` | 把已批准计划转换为具有明确依赖关系的可执行清单 |
| Dispatcher | 已完成 | `src/geopilot/execution/dispatcher.py` | 将每种计划 operation 严格绑定到一个确定性 GIS 函数 |
| 执行与恢复 | 已完成第一版 | `src/geopilot/execution/executor.py` | 顺序执行、失败停止、跳过已成功步骤并从检查点恢复 |
| 运行存储 | 已完成第一版 | `src/geopilot/execution/store.py` | 保存 manifest、run 状态、工具结果元数据和产物路径 |
| 知识加载与切块 | 已完成第一版 | `src/geopilot/rag/loader.py`、`chunker.py` | 递归加载 Markdown/TXT，按标题层级切成稳定引用片段 |
| Embedding | 已完成第一版 | `src/geopilot/rag/embeddings.py` | 使用本地 FastEmbed 区分 passage/query 角色生成中文向量 |
| Vector Store | 已完成第一版 | `src/geopilot/rag/vector_store.py` | JSON 持久化、模型/维度校验和精确余弦相似度检索 |
| RAG 服务与工具 | 已完成第一版 | `src/geopilot/rag/service.py`、`agent/tool_adapters.py` | 返回带来源引用的证据，并按索引存在性注册 Agent 工具 |
| 检索评估 | 已完成第一版 | `src/geopilot/rag/evaluation.py`、`knowledge/retrieval_cases.json` | 按来源、章节、正文标签与相关度等级计算 Precision、Recall、MRR 和 NDCG |
| Cross-Encoder Rerank | 已实现并完成首轮评估，默认关闭 | `src/geopilot/rag/reranking.py`、`rerank_experiment.py` | 对 Hybrid 候选成对打分；真实实验无收益，因此不替换默认 Hybrid |
| Long-term Memory | 已完成安全第一版 | `src/geopilot/memory/`、`agent/runner.py`、`cli.py` | 显式确认写入、namespace 隔离、版本/过期/删除、相关召回和可关闭 Prompt 注入 |
| Agent Eval | 已完成规则评测 V1 | `src/geopilot/evaluation/`、`evals/agent_cases_v1.json` | 评估任务结果、必需/禁用工具、正确失败、步骤效率、重复调用和延迟 |
| Observability | 已完成脱敏 Trace V1 | `src/geopilot/observability/` | 以 JSONL 保存提示词哈希、轮数、工具元数据、耗时和终态，不保存模型可见正文 |
| 用户入口 | CLI 已完成 | `src/geopilot/cli.py` | Agent/执行、RAG、Memory、Agent Eval 与 trace-list 命令 |

## 当前采用的方法与技术取舍

### 1. Agent 与 Workflow 的组合

GeoPilot 没有让 LLM 直接执行任意 Python 或任意 GIS 操作。LLM 负责理解自然语言、选择受限工具和生成结构化计划；计划一旦获批，就交给确定性 Workflow 顺序执行。这样保留 Agent 的灵活理解能力，同时让 CRS、缓冲、求交、统计与导出保持可测试和可复现。

### 2. 模型适配与配置隔离

`agent/client.py` 定义统一模型接口，`chat_completions.py` 适配 DeepSeek/OpenRouter，`openai_responses.py` 适配 OpenAI，`factory.py` 根据配置选择实现。API Key 只从环境变量读取，`.env` 被 Git 忽略。模型供应商变化不会改变 Agent Loop、工具契约或 GIS 业务逻辑。

### 3. 版本化 Prompt 与代码护栏

System Prompt 位于 `agent/prompts.py` 并有显式版本。Prompt 0.8.0 负责告诉模型何时检查数据、何时推荐 CRS、何时检索知识、何时提交计划，以及长期记忆只能用于个性化、不能覆盖系统规则和工具事实；关键安全规则还会在 Pydantic Schema、计划语义校验器和执行编译器中再次验证。原因是 Prompt 属于软约束，不能替代代码级权限与数据校验。

### 4. Function Calling 与 Tool Registry

工具通过 `AgentTool` 注册名称、说明、输入 Pydantic 模型、处理函数和可恢复错误。Agent Loop 把 JSON Schema 发给模型；模型返回 Tool Call 后，Registry 再校验参数并调用本地函数。工具结果以结构化消息返回模型，模型不能绕过 Registry 直接访问 GIS 函数。

### 5. 结构化规划与人工审批

空间分析计划包含原始数据集、顺序步骤、操作、参数、风险、假设和稳定 output 标识。`PlanStore` 使用 `awaiting_approval → approved/rejected` 状态机保存人工决策。提交计划不等于批准，批准也不自动篡改步骤；执行器只接受已批准且能通过编译的计划。

### 6. 确定性 GIS 执行与恢复

Compiler 验证产物依赖、输出唯一性和操作参数，Dispatcher 将每个 operation 映射到明确的 GeoPandas 工具，Executor 顺序执行并失败即停。RunStore 保存步骤状态和产物元数据；恢复时只跳过产物仍存在的成功步骤。文件工具采用临时文件后原子替换，降低中断留下残缺产物的风险。

### 7. Agentic RAG

知识库存在时才注册 `search_knowledge`。离线侧加载 Markdown/TXT，采用 Markdown 标题结构感知切分，超长章节再按自然分隔符递归字符切分；默认最大 500 字符、重叠 80 字符，该参数来自四组控制变量实验。`BAAI/bge-small-zh-v1.5` 分别通过 passage/query 接口生成 512 维向量，向量 L2 归一化后写入 JSON 索引。在线侧使用同一模型生成 Query 向量，精确计算余弦相似度并返回正文、分数和稳定引用。

Token 护栏位于 `rag/embeddings.py`、`rag/tokenization.py` 和 `rag/service.py`。`FastEmbedProvider` 克隆当前模型 tokenizer 并关闭克隆体的 truncation，以便测量完整 `title + section + text` 的原始 token 数，同时保留模型真实的 512-token 配置。正式 `rag-build` 在生成向量和写索引前统计平均、P95、最大值、80% 告警数与超限数；发现超限时返回 `embedding_input_token_limit_exceeded`。自定义 Embedding Provider 只有实现 `TokenCounter` 契约时才获得该护栏。

在线默认检索由 `rag/lexical.py`、`rag/hybrid.py` 和 `rag/service.py` 组成。Dense 路径继续使用精确余弦相似度；BM25 对英文/数字/字段标识符做完整 token，对连续中文生成双字片段；两路默认各取最多 12 个候选，使用 RRF `k=60` 融合名次。归一化 RRF 分数仅用于排序，不是概率。结果同时暴露 Dense/BM25 原始分数和名次。`rag-retrieval-experiment` 固定索引、模型、Query 与 Top-K，并在预热同一 Embedding Provider 后比较两种策略。

可选精排位于 `rag/reranking.py`：`HybridSearcher` 先召回最多 12 个候选，`BAAI/bge-reranker-base` 再将 Query 与每个候选的 `title + section + text` 成对编码并排序。`Reranker` Protocol 使真实模型与测试替身解耦；适配器拒绝空输入、数量不匹配和 NaN/Infinity 分数。只有显式选择 `hybrid_rerank` 才延迟加载约 1.052 GiB 的本地模型缓存。`rag-rerank-experiment` 在同一候选池和黄金集上对比 Hybrid 与 Rerank。真实结果没有改善，所以默认仍是 Hybrid。

当前仅有 19 个 Chunk，选择 JSON + NumPy 是为了透明和便于测试；它不是面向百万向量、并发与增量索引的生产向量数据库。RAG 用于项目规则和字段知识，不代替数据检查或 GIS 数值计算。

### 8. 检索评估

黄金样例为每个 Query 标注一个或多个相关目标：来源、章节、正文子串和 1～3 级相关度。当前困难集包含 20 条 Query、24 个标签，其中 4 条为多正例。评估器计算 Hit Rate@K、Precision@K、Recall@K、MRR 和 NDCG@K。Baseline 固定知识库、Embedding、Chunk 参数和 Top-K，为后续控制变量实验提供比较基准。Hybrid Top-12 Recall 为 1.0，而 Rerank 后 Top-3 Recall 降低，说明问题发生在精排而不是候选召回。

## Memory 现在有什么

GeoPilot 明确区分四类状态：

- Working Memory：`runner.py` 中的 `messages` 保存单次运行的 system/user/assistant/tool 消息；进程结束后不跨会话保留。
- Session State：`artifacts/plans` 与 `artifacts/runs` 保存审批、步骤状态、失败和产物依赖；它是可靠工作流状态，不是聊天记录。
- Long-term Memory：`memory/models.py`、`store.py`、`context.py` 保存用户确认的回答偏好、长期目标和项目背景。
- External Knowledge：`rag/` 保存 GIS 规范、字段定义和项目文档，不与用户记忆混存。

长期记忆 V1 使用版本化 JSON 和 `namespace + kind + key` 唯一身份。CLI `memory-set` 必须带 `--confirmed`，模型没有写入工具；同一身份更新时保留 ID 和创建时间并增加 revision。条目可设过期时间，可按 namespace/kind 列出，也可用 namespace + memory ID 精确删除。存储使用同目录临时文件、`fsync` 和 `os.replace` 原子替换。

读取时，`MemoryContextBuilder` 默认返回最多 6 条、2000 字符：回答偏好视为全局，用户目标和项目背景按当前 Query 与 `key + value` 的词法重叠筛选，过期和其他 namespace 条目不进入上下文。渲染后的 `<user_memory>` 转义块被追加到 system message；Prompt 0.8.0 要求将它视为不可信的个性化数据，当前用户输入冲突时以当前输入为准。`agent --no-memory` 可以完全跳过读取。

当前不是生产级记忆平台：没有语义同义词召回、自动会话摘要、模型写入提案、人审冲突合并、并发锁、加密、身份认证或租户授权；敏感 key 拦截也不能替代 DLP。

## Agent Eval 与可观测性现在有什么

`evaluation/models.py` 把每道 Agent 题定义为版本化契约：预期 `completed` 或 `correct_failure`、必需工具、禁用工具、答案稳定子串、预期错误码、最大模型轮数/工具调用数和精确重复调用策略。`evaluation/agent_evaluator.py` 运行完整 `AgentRunner`，从最终答案与消息/工具轨迹计算任务成功率、正确失败恢复率、必需工具召回率、工具成功率、禁用工具违规率、精确重复率、步骤效率、轮数、调用数和耗时。

V1 金标准位于 `evals/agent_cases_v1.json`，包含有效数据检查、检查后 CRS 推荐、RAG 规则问答和缺失文件正确失败 4 类任务。评测关闭 Long-term Memory，并把可能误提交的计划写入临时目录，避免用户状态和副作用污染回归。`agent-evaluate` 可打印并可选保存 JSON 结果。

2026-08-28 的真实 `deepseek-v4-flash` 结果为：4 题通过 3 题，Task Success 0.75、Required Tool Recall 1.0、Error Recovery 1.0、Forbidden Violation 0、Mean Step Efficiency 0.875、总耗时 26.92 秒。唯一失败是 RAG Case 进行了两次参数不同的 `search_knowledge`，答案正确但超过一步预算；项目保留此失败，不调整 Case 制造满分。

`observability/` 默认把普通 `agent` 运行追加到 `artifacts/traces/agent_runs.jsonl`。Trace 只含提示词 SHA-256、provider/model、状态、耗时、模型轮数、工具名/成功状态/错误码、答案字符数和顶层错误码；不保存 API Key、原始 Prompt、工具参数/输出、Tool Call ID 或完整回答。`--no-trace` 可关闭，`trace-list` 可按状态和数量读取。Trace 写入失败只输出 warning，不改变原 Agent 成败。

当前规则评测不能判断答案整体忠实度、相关性和引用正确率；JSONL 也没有并发锁、集中日志、告警、保留策略或访问控制，低熵 Prompt 哈希存在字典反推风险。供应商 token usage 尚未接入，因此 V1 没有成本指标。完整证据见 `docs/evaluations/AGENT_EVAL_V1.md`。

## RAG、Embedding 在哪里

第 8 阶段已经实现以下链路：

```text
GIS 规范 / 项目文档 / 数据字典
    ↓ 文档加载
Chunking
    ↓
Embedding
    ↓
Vector Store
    ↓ Dense + BM25 + RRF 候选召回
可选 Cross-Encoder Rerank
    ↓
带来源与章节引用的上下文
    ↓
Planner / Agent
```

GeoPilot 的 RAG 用于检索 CRS 说明、空间分析规范、字段定义和项目知识，不用于替代 GeoPandas 的数值计算。当前使用 20 条人工黄金 Query、24 个相关标签衡量 Precision@K、Recall@K、MRR 与 NDCG；Agent Eval V1 已覆盖是否调用检索工具和步骤预算，回答忠实度和引用正确率的 LLM-as-judge/人工评测仍未实现。

## MCP 在哪里

当前尚未实现。MCP 阶段会把已经稳定、具有 Pydantic 输入输出契约的 GIS 工具发布为 MCP Server，使其他 Agent 或桌面客户端也能发现和调用它们。MCP 是工具互操作协议，不是模型、RAG 或记忆本身。

## 后续完整组件顺序

1. 扩充 Agent 回归集，增加生成答案 Judge、供应商 token/成本统计和 Trace 聚合告警。
2. FastAPI、Web GIS 图形界面、数据库和权限边界。
3. Docker、CI/CD、安全检查和部署。
4. MCP Server，将稳定 GIS 能力提供给外部 Agent。

这套顺序先保证 Agent 会正确计算和失败，再增加知识、记忆与产品界面，便于定位每个阶段的问题并形成可展示的工程提交历史。

## 迭代记录

### 2026-08-27：RAG 检索评估 Baseline V1

- 变更：黄金标签从单一“来源 + 章节”升级为可包含多个目标、正文子串和 1～3 级相关度。
- 指标：新增 Precision@K、Recall@K 与 NDCG@K，保留 Hit Rate@K 和 MRR。
- 测试：新增排名第 2 的位置折扣测试和多等级相关度 NDCG 测试；全项目 135 项测试通过。
- 真实结果：Top-3 下 Hit Rate 1.0、Precision 0.3333、Recall 1.0、MRR 0.9167、NDCG 0.9385。
- 取舍：每个当前问题只标注一个严格黄金片段，因此 Precision@3 理论值为 1/3；不通过放宽标签制造更高分数。
- 局限：只有 2 份文档和 6 条人工 Query，尚未评估生成答案忠实度与引用正确率。
- 下一步：固定其他变量，对比多组 chunk size/overlap，验证 700/100 的参数依据。

### 2026-08-27：建立双文档持续维护机制

- 方法记录：本文件统一维护所有 Agent 组件的实际实现、证据、取舍和变更历史。
- 面试记录：`docs/AGENT_INTERVIEW_QA.md` 统一维护项目化问题与回答。
- 仓库规则：根目录 `AGENTS.md` 要求未来 Agent 相关修改必须同时更新两份文档。

### 2026-08-27：Chunking 控制变量实验 V1

- 变更：新增 `rag-chunk-experiment`，复用同一 Embedding Provider，对多组 size/overlap 分别建索引并运行同一黄金集。
- 语料：新增公共设施候选选址知识，知识库扩展为 3 份文档；黄金集从 6 条扩展到 10 条。
- 实验：比较 `300/50`、`500/80`、`700/100`、`900/120`。
- 结果：`300/50` Recall@3 为 0.90；其余三组 Recall@3 为 1.0、MRR 为 0.90、NDCG@3 为 0.9262。
- 决策：默认值由 `700/100` 改为 `500/80`。它保持完整召回，并比更长片段降低字符切块接近模型 token 上限的风险。
- 证据：`docs/evaluations/RAG_CHUNK_EXPERIMENT_V1.md`；主索引重建为 3 文档、19 chunks。
- 局限：字符数不等于 tokenizer token 数，耗时来自单次本机运行，不能作为严格性能基准。
- 下一步：增加 token 感知统计，再进行 Hybrid Search 对照。

### 2026-08-27：真实 DeepSeek Agent 检索验证

- 验证方式：通过 `geopilot agent` 提问“公共设施候选点能否直接作为最终建设位置，还缺少哪些数据”，并明确要求先调用 `search_knowledge`、保留引用且不执行空间分析。
- 实际行为：Agent 检索了新增的 `knowledge/facility_site_selection.md`，引用对应章节，说明候选点不等于最终建设位置，并列出道路与可达性、土地利用与规划、权属、地形水文、生态灾害和建筑等缺失数据。
- 安全边界：本次请求只需要知识回答，Agent 没有调用 GIS 分析工具，也没有生成或执行分析计划。
- 结论：验证链路覆盖了“真实模型判断是否检索 → 工具调用 → 本地向量检索 → 带来源回答”，不仅是单元测试中的直接函数调用。

### 2026-08-27：Token-aware Chunking 与建库护栏 V1

- 实现：新增 `TokenCounter`、`TokenUsageStatistics` 和 `summarize_token_usage`；`rag-chunk-experiment` 输出模型上限、平均/P95/最大 token、利用率、告警数和超限数。
- 计数口径：使用生成向量的同一 FastEmbed tokenizer，统计完整 `KnowledgeChunk.embedding_text`，并通过克隆 tokenizer 后关闭 truncation 获得截断前长度。
- 正式护栏：`build_knowledge_index` 在 Embedding 和写索引前拒绝任何超过模型上限的输入；错误码为 `embedding_input_token_limit_exceeded`。
- CLI 实测：`rag-build --chunk-size 900 --chunk-overlap 120` 返回退出码 11，报告 2 个超限输入且探针索引不存在；默认 `500/80` 成功重建 3 文档、19 Chunk 的主索引。
- 真实结果：BGE 上限 512 token。`300/50` 最大 302、无告警；`500/80` 最大 443、3 个达到 80% 告警线、无超限；`700/100` 最大 655、2 个超限；`900/120` 最大 686、2 个超限。
- 决策：保留默认 `500/80`。它保持 Recall@3 1.0 且没有截断；700 与 900 的检索指标虽然相同，但部分文档向量建立在被截断的输入上，不能作为更优方案。
- 测试：覆盖预截断计数、P95/阈值计算、tokenizer 模型一致性和“超限时不创建索引”；全项目 141 项测试通过。
- 证据：`docs/evaluations/RAG_TOKEN_AWARE_CHUNKING_V1.md`。
- 局限：80% 是工程告警阈值而非模型规则；当前分块边界仍按字符生成，只是在 Embedding 前用 token 做测量和阻断。
- 下一步：固定默认 Chunk 与黄金集，实现稠密向量 + BM25 的 Hybrid Search 对照实验。

### 2026-08-27：BM25 + Dense Hybrid Search V1

- 实现：新增纯 Python `BM25Index`、中文双字/字段标识符 tokenizer、`HybridSearcher` 和 RRF 融合；不增加第三方检索依赖。
- 调用链：`search_knowledge` → `KnowledgeRetriever` → Dense 与 BM25 双路候选 → RRF → 带引用和两路排名的 Top-K。
- 参数：默认在线模式 `hybrid`，`hybrid_candidate_k=12`、`rrf_k=60`；CLI 可切回 `dense`。
- 真实对照：10 条 Query、Top-3 下 Recall 均为 1.0；MRR 从 0.90 升至 0.95，NDCG 从 0.9262 升至 0.9631。
- Query 变化：`metric_crs`、`missing_feasibility_layers` 从第 2 升至第 1；`service_radius_field` 从第 1 降至第 2；其余 7 条不变。
- 单次耗时：预热后 Dense 85.72ms、Hybrid 88.96ms；单次本机结果受负载影响，不作为稳定 SLA。
- 取舍：采用 RRF 是因为余弦与 BM25 分数不可直接相加；当前聚合排序指标改善且无召回退化，因此切换默认，但明确保留单 Query 退化证据。
- 测试：覆盖中文/标识符分词、BM25 排序、Dense 错排时 Hybrid 恢复、RRF 可解释字段、对照指标和 Agent 工具兼容；全项目 146 项测试通过。
- 真实 Agent：DeepSeek 通过默认 `search_knowledge` 回答 EPSG:4326 距离问题，返回 CRS、缓冲与输出章节引用，且未误调用数据检查或空间分析工具。
- 证据：`docs/evaluations/RAG_HYBRID_SEARCH_V1.md`。
- 局限：当前 BM25 在查询时扫描 19 个 Chunk，没有持久化倒排索引；中文双字切分不等于专业分词；黄金集过小且大多只有一个正例。
- 下一步：先扩充困难负例、多正例和词汇错配 Query，再以候选池 + Cross-Encoder 方式评估 Rerank。

### 2026-08-27：困难集与 Cross-Encoder Rerank V1

- 评测集：从 10 条扩充为 20 条 Query、24 个黄金标签；4 条问题包含两个正例，覆盖分析/展示 CRS、覆盖面积/设施计数、可达性权重和容量字段等易混淆边界。原 10 条集合固定为 `knowledge/retrieval_cases_hybrid_v1.json`。
- 实现：新增 `Reranker` Protocol、延迟加载的 `FastEmbedReranker`、`RerankSearcher`、稳定错误代码、`hybrid_rerank` 模式及 `rag-rerank-experiment` CLI。
- 模型：真实使用 `BAAI/bge-reranker-base`；缓存实占约 1.052 GiB。Rerank 输入为 Query 与候选的 `title + section + text`，第一阶段候选数 12。
- 候选诊断：Hybrid Top-12 Hit Rate 和 Recall 都是 1.0，24 个标签全部已被召回。
- 真实 Top-3：Hybrid 的 Precision/Recall/MRR/NDCG 为 0.3833/0.9750/0.9750/0.9521；Rerank 为 0.3500/0.9250/0.9750/0.9496。
- 逐 Query：按 NDCG 比较为 1 条改善、2 条退化、17 条不变；`service_radius_field` 仍排第 2。
- 时延：同一预热实验中 Hybrid 230.68ms，Rerank 67,688.53ms；单次本机 CPU 数据不作为 SLA，但足以说明当前量级差异。
- 决策：保留可选 Rerank 能力用于后续模型/硬件实验，默认继续使用 Hybrid。组件实现完成不等于必须上线。
- 测试：覆盖候选池边界、排序、模型按需加载、空输入、数量不匹配、非有限分数、CLI 和受控实验；全项目 152 项测试、Ruff、格式和 Pyright 均通过；证据见 `docs/evaluations/RAG_RERANK_V1.md`。
- 局限：小语料、小黄金集、单模型、单次 CPU 测量；尚未评估生成侧忠实度、引用正确率和拒答。
- 下一步：进入 Memory，先实现可审计的用户偏好写入边界，并映射 Working Memory、Session State 与 RAG 的职责。

### 2026-08-28：Long-term Memory V1

- 分层：明确 Working Memory、Plan/Run Session State、Long-term Memory 与 RAG 外部知识四类对象，避免用一个 `memory` 表混存。
- 契约：新增 `MemoryKind`、`MemoryEntry`、`MemoryWriteRequest`、版本化存储 envelope 和稳定错误代码；V1 只允许回答偏好、用户目标、项目背景三类用户确认信息。
- 写入策略：`memory-set` 必须显式 `--confirmed`；模型没有 Memory 写工具；同身份 upsert 增加 revision，并支持 1～3650 天过期。
- 存储与隔离：JSON 原子替换；按 namespace 读取和删除，跨 namespace ID 不可删除；敏感 key 被拒绝。
- 召回：回答偏好全局加入，其他类型按 BM25 同款 token 词法重叠筛选；默认 Top-6、最多 2000 字符、过期过滤。
- Prompt 安全：升级到 0.8.0；记忆值进行标签字符转义，并声明不能覆盖系统规则、工具证据、审批或当前输入；支持 `--no-memory` 熔断。
- 真实验证：临时写入 GIS 专业背景和“说明关键步骤目的”的偏好；禁用 RAG 与工具后，DeepSeek 正确复述两项内容。
- 自动化：覆盖确认、revision、过期、namespace、删除、损坏文件、敏感 key、相关召回、字符上限、Agent 注入、CLI 生命周期和关闭开关；全项目 162 项测试、Ruff、格式和 Pyright 均通过；证据见 `docs/evaluations/MEMORY_V1.md`。
- 局限：词法召回不理解无共同 token 的同义表达；本地 JSON 无并发、加密与认证；没有自动摘要或模型写入审批流，不能描述为生产级多用户记忆。
- 下一步：进入 Agent Eval 与可观测性，量化任务完成率、工具选择、步骤效率、错误恢复、延迟和 token 成本。

### 2026-08-28：Agent Eval 与脱敏 Trace V1

- 评测合同：新增 `AgentEvaluationCase`、Case/聚合结果模型和 JSON 加载校验；同时评价最终稳定事实、必需/禁用工具、预期错误、轮数、调用预算和精确重复。
- 运行隔离：`agent-evaluate` 禁用长期记忆，误提交计划只进入临时目录；V1 固定 4 条正常、RAG、组合工具与正确失败任务。
- 真实结果：`deepseek-v4-flash` Task Success 0.75、Required Tool Recall 1.0、Error Recovery 1.0、Forbidden Violation 0、Exact Duplicate 0、Mean Step Efficiency 0.875，总耗时 26,924.47ms。
- 回归证据：RAG Case 答案与工具选择正确，但使用两次参数不同的 `search_knowledge`，超过一次调用预算而失败；没有事后放宽 Case。
- 可观测性：新增 append-only JSONL Trace、`--no-trace` 和 `trace-list`；默认只存 Prompt 哈希、模型、状态、耗时、轮数、工具元数据、答案长度和错误码。
- 真实 Trace：DeepSeek 单工具数据检查记录 2 轮、1 次成功工具调用和 4,074.04ms，序列化内容不含原 Prompt、参数、结果正文或 Tool Call ID。
- 自动化：全项目 176 项测试通过，Ruff、格式和 Pyright 均为 0 错误；证据见 `docs/evaluations/AGENT_EVAL_V1.md`。
- 局限：4 条 Case 不代表生产可靠性；规则评测不等于生成忠实度 Judge；尚无 token/成本、并发日志锁、集中告警和访问控制。
- 下一步：扩充噪声/高风险/计划纠错 Case 并接入 usage；然后进入 FastAPI 与 Web GIS 产品层。
