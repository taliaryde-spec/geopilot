# GeoPilot

GeoPilot 是一个自然语言驱动的地理空间分析 Agent。用户提供空间数据和分析问题，Agent 将检查数据、规划分析步骤、调用 GIS 工具、验证结果，并生成地图与报告。

> 当前项目处于 v0.1 开发阶段。本仓库已经跑通自然语言规划、人工审批、确定性 GIS 执行、结果验证与报告，并加入了带引用的本地 RAG、中文 Embedding、长期记忆、Agent 规则评测、版本化 Prompt 对照实验、脱敏运行 Trace、workspace 隔离的本地 FastAPI 和 Web GIS。

## 演示场景

分析居民区附近的公共服务设施覆盖情况，找出服务不足的区域，并生成可复现的分析结果与选址建议。

仓库中的演示数据是为项目测试构造的虚构数据，不代表真实设施或人口分布。

## 当前已实现

- GeoJSON、Shapefile 等矢量数据读取
- 带经纬度字段的 CSV 点图层转换
- 字段、记录数、几何类型、CRS、范围和缺失值检查
- 缺失 CRS、缺失几何、空几何和无效几何验证
- 结构化 Pydantic 输出与稳定错误代码
- `geopilot inspect` 命令行接口
- Provider-neutral Agent Loop、System Prompt、Tool Registry 与工作记忆
- OpenAI Responses API、DeepSeek/OpenRouter Chat Completions 与结构化 Tool Calling
- 基于数据范围确定性推荐米制投影 CRS，并禁止 Agent 猜测 EPSG 编号
- 结构化分析计划、文件检查点与明确的批准/拒绝状态转换
- 已批准计划的依赖编译、确定性执行、失败停止与检查点恢复
- Markdown/TXT 知识加载、层级切块、本地中文 Embedding、Hybrid Search、可选 Cross-Encoder 与来源引用
- RAG 的章节级 Precision/Recall/MRR/NDCG 离线评估及 Agent `search_knowledge` 工具
- 用户确认的长期偏好/目标/项目背景，支持 namespace、revision、过期、删除和按 Query 注入
- 版本化 Agent 金标准任务、正确失败/工具/步骤/安全指标和真实 DeepSeek 回归
- 三组 System Prompt 版本、6 类任务、Token/Cache/Reasoning 用量与工具参数合法率的控制变量实验
- 默认脱敏 JSONL Trace，只保存 Prompt 哈希、工具元数据、耗时、轮数和终态
- Dataset、Agent、Plan、Run、Trace 的本地 FastAPI/OpenAPI，包含路径越界和状态冲突防护
- 数据预检、工具证据、计划审批、执行检查点和 GeoJSON 地图组成的响应式 Web GIS
- Ruff、Pyright 和 Pytest 质量检查

完整组件规划与各阶段验收标准见 [GeoPilot 项目路线图](docs/PROJECT_ROADMAP.md)。

按照卡码 Agent 专栏逐项整理的“知识原理 → GeoPilot 源码 → 当前缺口 → 优化实验 → 项目化面试回答”见 [卡码 Agent 知识与 GeoPilot 实现对照手册](docs/KAMA_AGENT_GUIDE.md)。

## 快速开始

项目使用 Python 3.13 和 uv 管理依赖与虚拟环境。

```powershell
uv sync --all-groups
```

重新生成演示数据：

```powershell
uv run python scripts/generate_sample_data.py
```

检查公共设施点数据：

```powershell
uv run geopilot inspect examples/data/facilities.geojson
```

检查同一批设施的经纬度 CSV：

```powershell
uv run geopilot inspect examples/data/facilities.csv
```

默认坐标字段为 `longitude` 和 `latitude`。其他字段名可以显式指定：

```powershell
uv run geopilot inspect data/facilities.csv --longitude-column lon --latitude-column lat
```

检查居民区面数据：

```powershell
uv run geopilot inspect examples/data/neighborhoods.geojson
```

运行真实模型 Agent 前，复制 `.env.example` 为 `.env`，填写自己的 API 密钥：

```powershell
Copy-Item .env.example .env
```

`.env` 已被 Git 忽略，不能把真实 API Key 写入源码或提交到仓库。示例默认使用 DeepSeek 直连：

```dotenv
GEOPILOT_PROVIDER=deepseek
DEEPSEEK_API_KEY=your-key
```

也可以切换到 OpenRouter，但必须填写一个支持 Tool Calling 的完整模型 ID：

```dotenv
GEOPILOT_PROVIDER=openrouter
OPENROUTER_API_KEY=your-key
OPENROUTER_MODEL=provider/model-name
```

## 本地 FastAPI 产品入口

启动本地开发服务：

```powershell
uv run fastapi dev
```

随后访问：

- Web GIS：`http://127.0.0.1:8000/`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`
- Swagger API 文档：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`

API 直接复用 Agent、计划审批和确定性执行服务，不启动子进程解析 CLI 文本。请求路径、模型在 Tool Calling 中生成的路径以及旧计划内的数据源都会被限制在配置的 workspace 中；模型 provider、endpoint 和 API Key 只从服务端环境读取，不允许浏览器传入。

Web GIS 可完成“数据预检 → Agent 规划 → 人工审批 → 确定性执行 → GeoJSON 地图/报告”的演示闭环。页面从 Tool Result 的结构化字段取得 Plan ID，并只通过受控 Run 产物路由读取 GeoJSON/Markdown，不解析模型文本猜状态，也不直接访问本地绝对路径。完整设计见 [Web GIS V1](docs/evaluations/WEB_GIS_V1.md)。

当前版本没有认证、限流、后台队列、流式输出和多 worker 一致性保证，只应监听本机回环地址，不能直接作为公网生产服务。API 接口、威胁边界和测试证据见 [FastAPI 产品入口 V1](docs/evaluations/API_V1.md)。

配置完成后运行：

```powershell
uv run geopilot agent "请检查 examples/data/facilities.csv，并说明数据是否可以继续分析"
```

Agent 会把 `inspect_dataset` 的 JSON Schema 发给模型。模型选择工具后，本地代码执行检查，再把结构化结果返回模型生成最终回答。切换供应商只改变模型适配层，不改变 Agent Loop 或 GIS 工具。SDK 重试次数、超时和最大输出 token 可在 `.env` 中配置。复杂计划默认允许 4096 个输出 token，也可以单次覆盖：

```powershell
uv run geopilot agent "你的任务" --max-output-tokens 4096
```

当供应商返回 `finish_reason=length` 时，GeoPilot 会明确报告响应可能被截断，不会把残缺的工具参数交给 GIS 工具执行。

对同一模型、工具和 6 条任务比较 `minimal`、`structured` 与 `structured_few_shot` 三组 Prompt：

```powershell
uv run geopilot prompt-experiment evals/prompt_cases_v1.json `
  --max-output-tokens 8192 `
  --output artifacts/evaluations/prompt_experiment_v1.json
```

真实 DeepSeek V1 中 Few-shot 的 Task Success 为 0.50，高于另两组的 0.3333，且禁用工具违规降为 0；但总 Token 比当前 structured 默认版高约 6.5%，样本仅 6 条且只运行一次，因此暂不切换默认 Prompt。完整结果与失败复盘见 [Prompt 对照实验 V1](docs/evaluations/PROMPT_EXPERIMENT_V1.md)。

请求距离、缓冲区或面积分析时，Agent 必须调用 `recommend_metric_crs`，不能自行猜测 UTM 分区或 EPSG 编号：

```powershell
uv run geopilot agent "请为 examples/data/facilities.csv 推荐适合距离分析的投影坐标系"
```

上海演示数据的确定性结果是 `EPSG:32651`（WGS 84 / UTM zone 51N）。工具同时返回线性单位、是否需要重投影、计算方法和范围风险警告。

对于重投影、缓冲区、空间连接、结果导出或报告任务，Agent 必须先调用 `submit_analysis_plan`。计划会以 `awaiting_approval` 状态保存在 `artifacts/plans/`，不会立即执行：

```powershell
uv run geopilot agent "分析 examples/data/facilities.csv 的服务覆盖范围，先给出计划，不要执行"
```

使用 Agent 返回的 `plan_id` 检查完整计划：

```powershell
uv run geopilot show-plan plan_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

确认输入、步骤、参数、输出、风险和假设后，显式批准计划：

```powershell
uv run geopilot approve plan_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

计划有问题时应拒绝并说明原因：

```powershell
uv run geopilot reject plan_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx --reason "需要先确认服务半径字段的单位"
```

批准只改变计划检查点的状态，不会提前执行空间分析。当前执行器会使用 `plan_id` 检查授权状态，再运行重投影、缓冲区、空间连接等确定性工具。

计划提交前还会经过代码级语义校验，而不只依赖 Prompt：

- 社区总面积必须在叠加求交前通过 `calculate_geometry_area` 以平方米计算，并保留明确的数据血缘
- 覆盖面积必须按“米制缓冲区 → `union_all` 合并重叠 → 叠加求交 → 指标计算”的顺序规划
- 求交后必须用 `restore_uncovered_features` 恢复全部社区，并将未覆盖社区的面积、覆盖率和覆盖人口填 0
- `spatial_join` 必须分别声明 `how`、`predicate` 和字段后缀，不能用含糊的 `join_type`
- 覆盖指标与设施计数必须通过 `attribute_join` 按社区标识显式合并，验证步骤不能暗中承担数据连接
- 覆盖率、覆盖人口及结果验证必须声明具体字段、计算假设和边界检查
- 用于 Web 地图的 GeoJSON 必须输出为 `EPSG:4326`，米制 CRS 仅用于距离与面积计算

语义校验失败时，错误会作为工具结果返回模型；Agent 可以修正计划并重新提交，但错误版本不会写入计划存储。

如果 Agent 达到最大模型轮数，CLI 会返回一个有界工具轨迹：只包含工具名、成功状态和错误代码，不输出完整 Prompt、API Key 或大型工具结果。这用于定位模型是否在重复检查、反复提交错误计划或遇到工具故障。

## 确定性 GIS 执行工具

已实现的第一批执行工具位于 `src/geopilot/tools/vector_operations.py`：

- `reproject_vector_dataset`：把 CSV 点或矢量数据安全重投影到米制投影 CRS
- `calculate_polygon_area`：只在米制投影面图层上计算平方米面积
- `buffer_by_distance_field`：按正数、非空的米制字段逐要素生成缓冲区
- `dissolve_coverage_buffers`：使用 `union_all` 合并缓冲区，防止重叠覆盖面积重复计算
- `intersect_polygon_datasets`：在相同米制 CRS 下求两个面图层的交集，并保留社区属性

中间产物统一写为 GeoPackage（`.gpkg`），以保留 CRS、几何和字段类型。工具默认拒绝覆盖已有文件，并通过临时文件完成后再原子替换，降低中途失败留下残缺结果的风险。它们不会注册到普通对话 Agent，而是由后续的 `ApprovedPlanExecutor` 在确认计划状态为 `approved` 后调用。

这些工具已经覆盖当前计划的“重投影 → 求交前面积 → 字段缓冲 → 去重合并 → 社区求交”链路。求交工具允许合法的空结果，因为零覆盖社区会由 `restore_uncovered_features` 恢复并填入 0。覆盖指标计算、社区恢复和数据连接由下述业务工具完成。

覆盖业务工具位于 `src/geopilot/tools/coverage_analysis.py`：

- `calculate_coverage_metrics`：按社区合并交集片段，计算覆盖面积、覆盖率和基于均匀人口密度假设的覆盖人口
- `restore_uncovered_features`：将指标左连接回完整社区图层，仅为被求交遗漏的社区补 0
- `count_spatial_relationships`：通过左空间连接统计社区内设施数量，同时保留 0 设施社区
- `join_coverage_attributes`：只把右侧新增字段合并到覆盖结果，保留左侧标准人口和社区字段名

上述工具覆盖批准计划的第 1～10 步。结果验证、EPSG:4326 GeoJSON 导出和 Markdown 报告由下述输出工具完成；所有写文件工具仍只能由后续审批执行器调用。

结果输出工具位于 `src/geopilot/tools/result_outputs.py`：

- `validate_coverage_result`：执行几何、空值、覆盖率边界和覆盖人口边界四项规范检查，失败时不写“已验证”产物
- `export_web_geojson`：将验证结果重投影为 EPSG:4326，并原子写出 Web GeoJSON
- `generate_coverage_report`：直接从验证结果汇总社区、人口、覆盖和设施计数，生成可复现 Markdown 报告

确定性 GIS 工具层现已覆盖批准计划的全部 13 个步骤。`ApprovedPlanExecutor` 读取 `approved` 计划、为步骤建立产物依赖、调度工具、保存执行检查点，并在失败时停止而不是让 LLM 编造结果。

## 可执行计划编译

新提交的每个计划步骤除了面向用户的 `expected_output` 描述，还必须包含唯一的机器产物标识 `output`：

```json
{
  "operation": "reproject",
  "inputs": ["examples/data/neighborhoods.geojson"],
  "output": "neighborhoods_projected",
  "expected_output": "投影后的完整社区面图层"
}
```

`src/geopilot/execution/compiler.py` 只编译 `approved` 计划，并拒绝缺少产物 ID、重复输出、覆盖原始数据集名称、引用未来步骤或使用规划期工具的计划。旧计划仍能查看和保留审批记录，但缺少 `output` 时不会被猜测执行，需要用 Prompt 0.6.0 或更高版本重新生成。

`src/geopilot/execution/models.py` 定义了 GeoPackage、GeoJSON、Markdown 三类产物，以及 `pending → running → succeeded/failed` 的运行和步骤检查点状态。

`src/geopilot/execution/dispatcher.py` 将每个 operation 严格绑定到一个确定性 GIS 工具；`executor.py` 顺序执行计划、失败即停止，并在恢复时跳过产物仍然存在的成功步骤；`store.py` 原子保存 manifest、run checkpoint 和工具结果元数据。Prompt 0.6.0 与计划语义校验器要求提供真实工具所需的完整字段和 CRS 参数，避免“计划看起来合理但函数无法调用”。

```powershell
# 只执行已经人工批准的计划
uv run geopilot execute <plan_id>

# 查看每一步状态、错误和产物路径
uv run geopilot show-run <run_id>

# 修复临时文件、环境或依赖问题后，从第一个未完成步骤恢复
uv run geopilot resume <run_id>
```

完整 Agent 组件、实际方法和迭代证据见 [Agent 组件与工程实现记录](docs/AGENT_COMPONENTS.md)，对应的面试追问与项目化回答见 [Agent 面试问题与项目化回答](docs/AGENT_INTERVIEW_QA.md)。逐组件的优化方向、验收指标与求职证据见 [Agent 组件优化与求职证据矩阵](docs/AGENT_OPTIMIZATION_AND_CAREER.md)。以后每次 Agent 相关推进都会同步追加两份主文档。第一条“问题 → 规划 → 审批 → 执行 → 报告”闭环、本地 RAG、长期记忆、Agent Eval V1、脱敏 Trace、本地 FastAPI 与 Web GIS 已经具备；生成语义评测、异步 Job、安全部署和 MCP 仍按路线图分阶段实现。

## 长期记忆

GeoPilot 将单次对话消息、Plan/Run 任务状态、长期用户信息和 RAG 外部知识分开管理。长期记忆不会自动保存聊天；V1 只允许用户明确确认的回答偏好、长期目标和项目背景。

写入一条确认过的偏好：

```powershell
uv run geopilot memory-set response_preference learning_style "回答时说明每一步操作的目的" --confirmed --namespace default
```

写入可过期的项目背景：

```powershell
uv run geopilot memory-set project_context academic_major "我的专业方向是地理信息系统（GIS）" --confirmed --expires-in-days 365 --namespace default
```

列出、预览当前任务会召回的条目，以及删除：

```powershell
uv run geopilot memory-list --namespace default
uv run geopilot memory-recall "继续完善 GIS Agent 项目" --namespace default
uv run geopilot memory-delete <memory_id> --namespace default
```

普通 `agent` 命令默认从 `artifacts/memory/profile.json` 读取 namespace `default`。可用 `--memory-namespace` 切换隔离范围，或用 `--no-memory` 完全关闭读取。Memory 值只用于个性化，不能覆盖工具事实、人工审批、System Prompt 或当前用户输入。完整设计与真实 DeepSeek 验证见 [Long-term Memory V1](docs/evaluations/MEMORY_V1.md)。

## Agent 评测与脱敏 Trace

运行版本化的完整 Agent 基准：

```powershell
uv run geopilot agent-evaluate evals/agent_cases_v1.json --provider deepseek --output artifacts/evaluations/agent_eval_v1.json
```

V1 的 4 条 Case 覆盖数据检查、检查后 CRS 推荐、RAG 问答和文件缺失的正确失败。每条题同时检查最终稳定事实、必需/禁用工具、预期错误、轮数、调用预算和精确重复。真实 `deepseek-v4-flash` 的 Task Success、Required Tool Recall、Error Recovery 为 `0.75 / 1.0 / 1.0`；唯一失败是 RAG 问题进行了两次不同参数的检索，超过一步预算。

普通 `agent` 默认把脱敏元数据追加到 `artifacts/traces/agent_runs.jsonl`，查看最近记录：

```powershell
uv run geopilot trace-list --limit 20
uv run geopilot trace-list --status failed
```

Trace 不保存 API Key、原始 Prompt、工具参数/输出或完整回答。可用 `agent --no-trace` 完全关闭。设计、指标和限制见 [Agent Eval 与可观测性 V1](docs/evaluations/AGENT_EVAL_V1.md)。

## 本地 RAG 与 Embedding

GeoPilot 使用 RAG 检索 GIS 分析规则、项目数据字典和字段定义。RAG 只向模型提供有来源的知识证据，不代替数据检查、CRS 推荐或 GeoPandas 计算。

首次构建本地知识索引：

```powershell
uv run geopilot rag-build knowledge
```

默认 Embedding 模型是 `BAAI/bge-small-zh-v1.5`。首次执行会下载模型到被 Git 忽略的 `artifacts/models/fastembed/`，并把可移植 JSON 向量索引写入 `artifacts/rag/index.json`。当前知识库包含 3 份文档、19 个标题感知片段和 512 维向量。默认 Chunk 参数为实验选出的 `500/80`，分别表示最大字符数与重叠字符数。索引构建会使用同一模型 tokenizer 对完整的 `title + section + text` 做未截断计数；超过 512 token 时会在写索引前报错，避免静默截断。

直接检查检索结果和引用：

```powershell
uv run geopilot rag-search "为什么不能在 EPSG:4326 中直接做米制缓冲？" --top-k 3
```

运行章节级离线评估：

```powershell
uv run geopilot rag-evaluate knowledge/retrieval_cases.json --top-k 3
```

默认检索现为 Dense + BM25 + RRF 的 Hybrid Search。当前困难集包含 20 条 GIS Query、24 个黄金标签，其中 4 条为多正例；Hybrid 的真实 Top-3 结果为：`Hit Rate = 1.00`、`Precision = 0.3833`、`Recall = 0.9750`、`MRR = 0.9750`、`NDCG = 0.9521`。标签同时指定来源、章节、正文子串和相关度等级，不只检查是否命中了同一份文档。历史 10 条 Dense/Hybrid 对照见 [Hybrid Search V1](docs/evaluations/RAG_HYBRID_SEARCH_V1.md)，并由独立快照保证可复现。

复现 Chunking 控制变量实验：

```powershell
uv run geopilot rag-chunk-experiment knowledge --cases knowledge/retrieval_cases_hybrid_v1.json --top-k 3
```

实验输出同时包含模型 token 上限、平均/P95/最大 token、最大利用率、80% 告警 Chunk 数和超限 Chunk 数。可用 `--token-warning-ratio 0.75` 调整告警线；该参数只影响风险标记，不改变模型真实的 512-token 上限。

复现 Dense-only 与 Hybrid Search 对照：

```powershell
uv run geopilot rag-retrieval-experiment knowledge/retrieval_cases_hybrid_v1.json --top-k 3 --hybrid-candidate-k 12 --rrf-k 60
```

普通 `rag-search` 和 Agent 默认使用 Hybrid；可传入 `--retrieval-mode dense` 复现纯向量结果。Hybrid 输出中的 `score` 是归一化 RRF 分数，不是概率；`dense_score`、`bm25_score`、`dense_rank` 和 `bm25_rank` 用于解释两路召回。

显式测试 Hybrid + Cross-Encoder 精排：

```powershell
uv run geopilot rag-search "为什么分析 CRS 与 Web 地图 CRS 不一样？" --top-k 3 --retrieval-mode hybrid_rerank
```

首次使用会把 `BAAI/bge-reranker-base` 下载到被 Git 忽略的 `artifacts/models/fastembed-rerank/`。真实 20-Query 对照中，Rerank 的 Recall@3/NDCG@3 为 0.9250/0.9496，低于 Hybrid 的 0.9750/0.9521；同一预热 CPU 实验总时长约从 230.68ms 增至 67.69s。因此项目保留可选能力，但默认不启用。完整参数、候选池诊断和逐 Query 变化见 [Cross-Encoder Rerank V1](docs/evaluations/RAG_RERANK_V1.md)。

复现 Hybrid 与 Rerank 对照：

```powershell
uv run geopilot rag-rerank-experiment knowledge/retrieval_cases.json --top-k 3 --hybrid-candidate-k 12 --rerank-candidate-k 12 --rrf-k 60
```

后续大模型学习和面试准备以 [GeoPilot 大模型学习与面试主线](docs/LLM_LEARNING_PATH.md) 为统一入口；每个阶段必须同时交付原理、代码、测试、真实实验、技术取舍、面试回答和诚实的简历描述。

索引存在时，普通 `agent` 命令会自动注册 `search_knowledge` 工具。模型可在解释 GIS 方法或项目字段前检索知识库，并收到 `source#标题层级 [chunk:n]` 形式的稳定引用；索引不存在时，Agent 仍可使用原有数据检查、CRS 推荐和计划工具。

命令会向标准输出写入 JSON，其中包含：

- `profile`：数据事实，例如字段、CRS、范围和几何统计
- `validation.issues`：结构化错误或警告
- `validation.can_proceed`：是否允许进入后续空间分析

## CLI 退出码

- `0`：数据可以继续分析，只有 warning 时也返回 `0`
- `2`：命令参数使用错误
- `3`：输入文件不存在
- `4`：数据验证发现阻断性错误
- `5`：CSV 字段、坐标值或坐标范围无效
- `6`：模型密钥、模型名或其他配置无效
- `7`：模型鉴权、限流、超时、连接或 API 请求失败
- `8`：模型返回格式或 Agent 循环异常
- `9`：计划不存在、状态转换冲突或计划文件无效
- `10`：计划编译、执行检查点或 GIS 工具执行失败
- `11`：知识加载、Embedding、向量索引、检索或 RAG 评估失败
- `12`：长期记忆确认、策略、存储、召回或删除失败
- `13`：Agent 评测 Case、运行或结果保存失败
- `14`：Trace 文件损坏或查询参数无效

PowerShell 可以通过 `$LASTEXITCODE` 查看退出码；Windows CMD 可以运行 `echo %ERRORLEVEL%`。

## CSV 输入约定

- 经度作为 X，范围必须为 `[-180, 180]`
- 纬度作为 Y，范围必须为 `[-90, 90]`
- 坐标不能为空、不能是非数值或无穷值
- 转换后的点图层明确使用 `EPSG:4326`
- 当前 MVP 不自动识别分隔符、文件编码、度分秒坐标或压缩 CSV
- CSV 已有名为 `geometry` 的字段时会拒绝转换，避免覆盖原始信息

## 项目结构

```text
src/geopilot/
├── api/                   # workspace 隔离的 FastAPI、请求契约与领域服务适配
├── agent/                 # Prompt、模型接口、工具注册表与 Agent Loop
├── cli.py                 # 命令行适配层
├── execution/             # 已批准计划编译、工具调度、运行检查点与恢复
├── evaluation/            # 完整 Agent 结果、过程、效率与安全评测
├── memory/                # 用户确认型长期记忆、原子存储与相关上下文筛选
├── models.py              # Pydantic 数据契约
├── observability/         # 不保存模型正文的本地脱敏运行 Trace
├── rag/                   # 文档加载、切块、Embedding、向量索引、检索与评估
├── tools/                 # 可独立测试的确定性 GIS 工具
├── web/                   # 人工审批、执行检查点与 GeoJSON 地图界面
└── workflows/             # 组合多个工具的业务流水线
knowledge/                 # GIS 知识文档与章节级检索评估集
evals/                     # 版本化完整 Agent 金标准任务集
scripts/
└── generate_sample_data.py
examples/data/             # 可复现的虚构演示数据
tests/                     # 单元测试与集成测试
```

## 开发质量检查

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q
```

## MVP 路线图

- [x] 检查矢量数据并生成结构化摘要
- [x] 在分析前验证 CRS、缺失值和几何质量
- [x] 读取带经纬度字段的 CSV 并转换为点图层
- [x] 根据数据范围推荐米制投影 CRS，禁止 Agent 编造 EPSG
- [x] 将自然语言问题转换为可校验的结构化分析计划
- [x] 持久化计划检查点，并在执行前要求用户批准或拒绝
- [x] 执行米制投影、缓冲区和空间连接
- [x] 验证分析结果并输出 GeoJSON 与 Markdown 报告
- [x] 本地 RAG、中文 Embedding、引用和章节级检索评估
- [x] 用户确认型长期记忆、作用域、过期、删除和 Agent 注入
- [x] 完整 Agent 规则评测、真实 DeepSeek 回归和脱敏 Trace
- [x] workspace 隔离的本地 FastAPI 与 OpenAPI
- [x] 提供计划审批、运行检查点和 GeoJSON 地图的 Web GIS V1
- [ ] 后台 Job、流式进度、安全上传、认证与部署

## v0.1 验收标准

- 系统能够读取一个 GeoJSON 面图层和一个带经纬度字段的 CSV 点图层
- 系统能够输出字段、记录数量、几何类型、CRS 和缺失值统计
- 进行距离分析前，系统必须转换到使用米作为单位的投影坐标系
- Agent 必须先生成包含输入、步骤、输出和风险的计划，获得用户确认后才能执行
- 系统能够完成缓冲区和空间连接，并输出 GeoJSON 结果与 Markdown 报告
- 报告必须包含 CRS、距离单位、匹配数量、未匹配数量和空值比例
- 输入缺少 CRS、经纬度字段或包含无效几何时，系统必须明确报错，不能编造结果

## v0.1 暂不实现

- 栅格和遥感影像分析
- QGIS 插件
- PostGIS
- 多 Agent 并行工作流
- 云端部署
