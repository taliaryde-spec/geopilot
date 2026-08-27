# GeoPilot Agent 组件与工程实现记录

## 文档职责与维护规则

这是第一份持续追加的 Agent 主文档，记录 GeoPilot **实际采用的方法**。每次 Agent 相关代码、参数、实验指标或架构边界发生有意义的变化，都必须在文末“迭代记录”追加日期、变更、证据、取舍和下一步，并同步更新 [Agent 面试问题与项目化回答](AGENT_INTERVIEW_QA.md)。

本文件只记录已经由源码、测试或真实运行证明的事实；规划中的功能必须明确标记为“未实现”，不能因为出现在路线图里就写成已完成。

这份文档区分“已经形成第一条可运行闭环”和“完整大模型应用的全部组件”。第一条闭环是：自然语言问题 → LLM 规划与工具调用 → 人工审批 → 确定性 GIS 执行 → 验证 → 地图数据与报告。RAG 与 Embedding 已作为第二条知识链路接入；跨会话长期记忆、系统化 Agent 评测、Web UI 和 MCP 仍是后续独立阶段。

## 当前调用链

```text
用户自然语言
    ↓
CLI
    ↓
System Prompt + Agent Loop
    ↓
LLM Adapter（DeepSeek / OpenRouter / OpenAI）
    ↕ Tool Calling
数据检查 / CRS 推荐 / 本地知识检索 / 结构化计划提交
                    ↕
        Chunking → Embedding → Vector Store
    ↓
PlanStore（awaiting_approval → approved / rejected）
    ↓ execute
计划编译器 → Dispatcher → 确定性 GIS 工具
    ↓
RunStore（步骤检查点、失败信息、产物元数据）
    ↓
GeoPackage / GeoJSON / Markdown
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
| 用户入口 | CLI 已完成 | `src/geopilot/cli.py` | 原有 Agent/执行命令及 rag-build、rag-search、rag-evaluate |

## 当前采用的方法与技术取舍

### 1. Agent 与 Workflow 的组合

GeoPilot 没有让 LLM 直接执行任意 Python 或任意 GIS 操作。LLM 负责理解自然语言、选择受限工具和生成结构化计划；计划一旦获批，就交给确定性 Workflow 顺序执行。这样保留 Agent 的灵活理解能力，同时让 CRS、缓冲、求交、统计与导出保持可测试和可复现。

### 2. 模型适配与配置隔离

`agent/client.py` 定义统一模型接口，`chat_completions.py` 适配 DeepSeek/OpenRouter，`openai_responses.py` 适配 OpenAI，`factory.py` 根据配置选择实现。API Key 只从环境变量读取，`.env` 被 Git 忽略。模型供应商变化不会改变 Agent Loop、工具契约或 GIS 业务逻辑。

### 3. 版本化 Prompt 与代码护栏

System Prompt 位于 `agent/prompts.py` 并有显式版本。Prompt 负责告诉模型何时检查数据、何时推荐 CRS、何时检索知识和何时提交计划；关键安全规则还会在 Pydantic Schema、计划语义校验器和执行编译器中再次验证。原因是 Prompt 属于软约束，不能替代代码级权限与数据校验。

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

当前仅有 19 个 Chunk，选择 JSON + NumPy 是为了透明和便于测试；它不是面向百万向量、并发与增量索引的生产向量数据库。RAG 用于项目规则和字段知识，不代替数据检查或 GIS 数值计算。

### 8. 检索评估

黄金样例为每个 Query 标注一个或多个相关目标：来源、章节、正文子串和 1～3 级相关度。评估器计算 Hit Rate@K、Precision@K、Recall@K、MRR 和 NDCG@K。Baseline 固定知识库、Embedding、Chunk 参数和 Top-K，为后续控制变量实验提供比较基准。

## Memory 现在有什么

当前有两种“任务内状态”，但还没有完整长期记忆：

- 单次 Agent Working Memory：`runner.py` 中的 `messages` 保存本轮用户、模型和工具消息；进程结束后不跨会话保留。
- 任务检查点：`artifacts/plans` 与 `artifacts/runs` 保存审批状态、执行状态和产物依赖；这是可靠的工作流状态，不是语义记忆。

后续 Memory 阶段会增加会话摘要、用户偏好、历史任务检索、写入边界、遗忘和隐私策略。不会把所有对话无选择地写入向量库。

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
    ↓ 相似度排序
带来源与章节引用的上下文
    ↓
Planner / Agent
```

GeoPilot 的 RAG 用于检索 CRS 说明、空间分析规范、字段定义和项目知识，不用于替代 GeoPandas 的数值计算。当前使用 10 条人工黄金样例衡量 Precision@K、Recall@K、MRR 与 NDCG；回答忠实度和引用正确率的 LLM-as-judge/人工评测将在完整 Eval 阶段加入。

## MCP 在哪里

当前尚未实现。MCP 阶段会把已经稳定、具有 Pydantic 输入输出契约的 GIS 工具发布为 MCP Server，使其他 Agent 或桌面客户端也能发现和调用它们。MCP 是工具互操作协议，不是模型、RAG 或记忆本身。

## 后续完整组件顺序

1. 会话记忆、任务记忆、用户偏好与长期记忆边界。
2. Eval、Tracing、日志、token/成本统计与回归数据集。
3. FastAPI、Web GIS 图形界面、数据库和权限边界。
4. Docker、CI/CD、安全检查和部署。
5. MCP Server，将稳定 GIS 能力提供给外部 Agent。

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
