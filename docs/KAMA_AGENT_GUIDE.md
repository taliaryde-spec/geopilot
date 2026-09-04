# 卡码 Agent 知识与 GeoPilot 实现对照手册

更新日期：2026-09-04

## 这份手册怎么用

这不是卡码文章的复制，也不是 Agent 名词表。它把[卡码大模型完整路线](https://notes.kamacoder.com/llm/)与[卡码 Agent 专项路线](https://notes.kamacoder.com/llm/app/agent_learning_roadmap.html)中的核心知识逐项映射到 GeoPilot：

1. 这个组件解决什么问题；
2. GeoPilot 在哪里、用什么方式实现；
3. 当前实现到什么程度，哪些还没实现；
4. 下一步如何通过控制变量实验优化；
5. 面试官可能怎样追问，如何用本项目回答；
6. 学习者需要亲手完成什么，才能真正掌握。

项目主线不再按页面或接口数量推进，而按“原理 → 代码 → 测试 → 实验 → 失败分析 → 文档 → 面试 → 简历”推进。

## 一、先建立完整 Agent 系统认知

### 卡码知识

[Agent 到底是什么](https://notes.kamacoder.com/llm/app/agent_intro.html)强调 Agent 不是更强的聊天模型，而是围绕目标持续行动的系统。判断关键是它能否规划、调用工具、执行，并根据 Observation 决定下一步。模型只是系统的一部分，外围还要有 Prompt、工具、执行器、状态、记忆、评估、权限和恢复。

### GeoPilot 怎么实现

```text
用户 GIS 目标
  → System Prompt + 当前消息 + 相关 Memory
  → AgentRunner 调用 LLM
  → 模型动态选择 inspect / CRS / RAG / submit plan
  → Tool Result 回到消息上下文
  → 模型根据 Observation 继续调用或结束
  → 结构化 Plan 等待人工批准
  → Compiler + Dispatcher + GeoPandas 确定性执行
  → Run checkpoint + GeoJSON + Markdown
```

- 模型：`src/geopilot/agent/client.py`、`factory.py`、`chat_completions.py`、`openai_responses.py`
- Prompt：`src/geopilot/agent/prompts.py`
- 动态循环：`src/geopilot/agent/runner.py`
- 工具与执行：`src/geopilot/agent/registry.py`、`tool_adapters.py`
- 状态：`src/geopilot/planning/`、`src/geopilot/execution/`
- RAG：`src/geopilot/rag/`
- Memory：`src/geopilot/memory/`
- Eval/Trace：`src/geopilot/evaluation/`、`src/geopilot/observability/`

GeoPilot 是 Agent + Workflow：检查什么、是否检索知识、何时推荐 CRS、是否继续规划由模型根据任务和工具结果决定；批准后的空间数值计算走固定 Workflow。

### 怎么优化

- 不用“工具数量”证明 Agent，而用动态决策 Case 证明同一 Prompt 下模型会因 Observation 选择不同下一步。
- 增加工具不可用、数据异常和知识不足任务，观察 Agent 能否换路径或正确停止。
- Trace 中记录 Prompt/工具版本、token、延迟和决策结果，但不记录隐藏思维链。

### 面试问答

**问：你的项目为什么是 Agent，不是带大模型的普通 GIS 程序？**

答：普通程序的调用路径由代码提前写死；GeoPilot 的 `AgentRunner` 在每轮把目标、工具 Schema 和上轮 Tool Result交给模型，模型动态决定调用数据检查、CRS、RAG、计划工具或结束。它具备目标驱动、外部行动和 Observation 反馈。但涉及 CRS、面积和文件写入时，我把自由度收回到经过审批的确定性 Workflow，避免为了 Agent 化牺牲可复现性。

**你需要亲手做：**画出上面的调用链，并从 `runner.py` 逐行说明一次两轮 Function Calling 如何结束。

## 二、Prompt、模型调用与结构化输出

### 卡码知识

Agent 专项路线把 Prompt、稳定模型调用、JSON Schema 和 Function Calling 视为地基。Prompt 不只是角色描述，应明确任务、上下文、边界和输出要求；但 Prompt 是概率性的软约束，关键业务规则仍需代码验证。结构化输出的价值是让模型结果可以被程序消费，而不是“看起来像 JSON”。

### GeoPilot 怎么实现

- `prompts.py` 保存显式版本 `0.8.0`，规定先检查证据、距离分析先调用 CRS 工具、写操作先提交计划、Memory 不得覆盖系统规则等。
- `ModelSettings.from_environment` 将 provider、模型、密钥、超时与最大输出 token 从业务逻辑中隔离。
- DeepSeek/OpenRouter 使用 OpenAI-compatible Chat Completions；OpenAI 使用 Responses API；统一转换成 `ModelResponse`。
- Tool 参数和 Plan 使用 Pydantic；模型只要参数不能通过 Schema，Registry 就不会执行工具。
- 模型响应因 `finish_reason=length` 截断时明确失败，不执行残缺 JSON。

### 当前不足

- Prompt 虽经过多次功能迭代，但没有独立、版本化的 Prompt 控制变量实验。
- 没有量化基础 Prompt、结构化分节和 Few-shot 对 Schema 成功率、工具选择、token 与延迟的影响。
- 供应商 usage 还未进入 Trace；不能回答每种 Prompt 的真实成本。
- 目前没有刻意要求输出隐藏 CoT；这符合应用系统不依赖暴露思维链的安全取向，但要补“可观察决策摘要”的设计。

### 下一步实验：Prompt Evaluation V1

固定模型、温度、工具、数据和任务集，仅改变 Prompt：

1. `minimal`：只给角色和目标；
2. `structured`：背景、任务、规则、工具策略、输出格式分节；
3. `structured_few_shot`：在结构化版上加入 1～2 个边界示例。

至少覆盖数据检查、CRS、RAG、计划、缺失文件、无关任务六类 Case，记录：

- Tool Selection Accuracy；
- Tool Argument Schema Valid Rate；
- Task Success / Correct Failure；
- 平均模型轮数与工具次数；
- input/output token、延迟与估算成本；
- Prompt Injection 或越权违规数。

只有指标提升超过 token/延迟成本，才升级默认 Prompt。不要因为 Few-shot 看起来更专业就默认加入。

### 面试问答

**问：Prompt 怎么设计和优化？**

答：GeoPilot 将 Prompt 版本化，按角色、GIS 安全边界、工具策略、计划审批和 Memory 信任边界组织。关键规则同时在 Pydantic、计划语义校验器和执行器中实现，因为 Prompt 只能降低概率，不能提供权限保证。优化时固定模型和任务集，对比 Prompt 版本的 Schema 有效率、工具选择率、任务成功率、token 和延迟，而不是凭回答观感修改。

**问：为什么不用模型直接输出一大段 JSON？**

答：JSON 文本不等于可靠契约。GeoPilot 让模型通过 Function Calling 提交参数，再由 Pydantic 做类型、必填项和模式校验，计划还经过领域语义校验。格式正确但 CRS 顺序错误的计划一样会被拒绝。

**你需要亲手做：**下一阶段和我一起阅读 Prompt 0.8.0、编写六类 Case、运行三组 Prompt 对照，并解释一次失败 Trace。

## 三、Context Engineering

### 卡码知识

[Context Engineering](https://notes.kamacoder.com/llm/app/context_engineering.html)关心的不是一句指令怎么写，而是模型当前能看到什么。System Prompt、工具 Schema、Few-shot、消息历史、RAG、Memory、工具结果和输出预算共同占用上下文。基本过程是检索、筛选、排序、压缩和组装；长窗口不代表可以无差别塞入全部内容。

### GeoPilot 怎么实现

当前已经完成“来源分层”，尚未完成统一预算：

- System Prompt：始终进入首条 system message；
- 工具：默认注册数据检查、CRS 与计划工具，RAG 索引存在时才增加检索工具；
- Working Memory：当前 `AgentRunner` 的消息和 Tool Result；
- Long-term Memory：按 namespace 和 Query 筛选，最多 6 条、2000 字符；
- RAG：由模型按需调用，不在每个问题前固定检索；
- Session State：Plan/Run 放在外部 Store，不把全部状态持续塞入 Prompt。

### 当前不足与优化

- 没有按模型 tokenizer 计算完整 Agent 请求 token。
- 除“RAG 存在才注册”外，没有按任务动态选择最小工具集。
- 工具结果会持续保留在 messages，没有统一摘要、分页、引用替换和旧结果清理。
- 没有长任务 compaction，也没有验证压缩是否丢失目标、决策和失败原因。

Context V1 应先做可观测性，再做压缩：计算 System/Tools/History/RAG/Memory/Tool Results 各自 token；记录每轮增长；随后对比全工具与最小工具集、完整 Tool Result 与安全摘要。验收要同时看任务成功率、步骤效率、上下文 token 和错误恢复，不能只追求 token 变少。

### 面试问答

**问：Prompt Engineering 和 Context Engineering 有什么区别？**

答：Prompt Engineering 主要关注指令如何表达；Context Engineering 管理一次推理看到的所有信息。GeoPilot 已把 Prompt、工具、RAG、Memory、Session State 分层，但还没有统一 token budget。下一步先测每类上下文占用，再通过动态工具集和工具结果摘要减少噪声，并用相同 Agent Eval 确认没有损失成功率。

**你需要亲手做：**读取一次真实 Agent 请求的消息结构，手工标注每段属于哪类上下文，并预测哪一部分最容易随轮数膨胀。

## 四、Function Calling 与工具设计

### 卡码知识

[Function Calling](https://notes.kamacoder.com/llm/app/function_calling.html)是模型表达“要调用哪个函数和哪些参数”的结构化机制，实际函数仍由应用执行。[工具设计](https://notes.kamacoder.com/llm/app/agent_tool_design.html)强调名称、描述、Schema、粒度和返回值会直接影响工具选择。工具也是能力和权限边界，不应给模型任意 shell 或万能函数。

### GeoPilot 怎么实现

1. `AgentTool` 注册名称、描述、Pydantic 输入模型、handler 和可恢复异常；
2. Registry 将 Pydantic 转为 JSON Schema 发给模型；
3. 模型返回 `ToolCall(id, name, arguments)`；
4. Registry 检查工具是否存在、校验参数、执行 handler；
5. 成功或稳定错误写成 `ToolResult`，以 tool message 返回；
6. 模型读取 Observation 后决定下一步。

当前 Agent 工具是 `inspect_dataset`、`recommend_metric_crs`、条件注册的 `search_knowledge` 和 `submit_analysis_plan`。它们职责相对单一；真正的写文件 GIS 工具不直接暴露给模型，而由批准后的 Dispatcher 调用。

FastAPI 还给工具注入 workspace resolver，所以即使 Prompt 诱导模型生成 `../private.csv`，检查工具也不能越界。

### 当前不足与优化

- 需要统计每个工具的选择准确率、参数校验失败率和返回 token。
- 可以给工具增加 read/write/high-risk 能力标签，按任务暴露最小集合。
- 返回值应区分供模型决策的摘要与供审计的完整外部产物引用。
- 工具变更需要 schema version 和兼容策略。
- 避免同时提供功能高度重叠、名字相似的工具；若拆分或合并，必须跑同一 Eval。

### 面试问答

**问：Function Calling 是否意味着模型真的执行了函数？**

答：不是。模型只生成结构化调用意图，GeoPilot 的 Registry 才验证工具名和 Pydantic 参数并执行本地 handler。工具结果再回到模型。因此密钥、路径策略、审批和异常处理都由应用控制，不交给模型。

**问：为什么不做一个 `run_gis_analysis` 万能工具？**

答：万能工具 Schema 大、语义含糊、权限过宽，也难定位失败。GeoPilot 把检查、CRS、知识检索和计划提交分开；高风险写操作甚至不直接暴露给 Agent，而在批准后由 Compiler/Dispatcher 执行。后续会通过工具选择率与 Schema token 实验判断是否需要调整粒度。

**你需要亲手做：**选一个工具，解释其名称、描述、每个参数、返回字段和可恢复错误为什么这样设计。

## 五、ReAct、Reflection 与 Plan-and-Execute

### 卡码知识

[三种 Agent 思路](https://notes.kamacoder.com/llm/app/react_reflection_planning.html)分别解决不同推进方式：ReAct 根据 Observation 边做边决定；Reflection 在初次结果后用证据和标准检查、再修正；Plan-and-Execute 先拆解复杂任务再执行。它们不是越多越好，增加一次模型检查也会增加延迟和错误机会。

### GeoPilot 怎么实现

- ReAct-like：`AgentRunner` 循环“LLM → Tool Call → Tool Result → LLM”，下一工具由上轮结果决定。项目不要求或保存模型隐藏 Thought，只保留可审计的 Action/Observation。
- Plan-and-Execute：模型用 `submit_analysis_plan` 提交 Pydantic Plan；人工批准后 Compiler 和 Dispatcher 执行。
- Reflection：尚未实现通用的模型自我反思循环。当前的“检查”主要由确定性代码完成，例如计划语义验证、结果验证和 Agent Eval；这不能冒充 LLM Reflection。

### 怎么优化与实验

选同一组 GIS 任务比较：

- 直接一次回答；
- ReAct 工具调用；
- Plan-and-Execute；
- 生成后增加一次基于明确 rubric 和工具证据的 Reflection。

记录 Task Success、Correct Failure、工具次数、模型轮数、token、延迟和错误放大率。简单数据检查可能不需要 Plan；复杂覆盖分析需要 Plan；Reflection 只有在修正率明显高于额外成本时才启用，而且应限制最多一次。

### 面试问答

**问：你的 Agent 是 ReAct 还是 Plan-and-Execute？**

答：两者组合。探索和工具选择阶段是 ReAct-like：模型观察检查、CRS 或检索结果后决定下一步；高风险空间分析使用 Plan-and-Execute，模型先提交结构化计划，人工批准后确定性执行。Reflection 目前没有作为模型循环上线，结果检查由代码完成；我会先做同题对照，证明它能修正错误再引入。

**你需要亲手做：**拿“检查 CSV”和“完成公共服务覆盖分析”两个任务，分别说明为什么前者不应强制计划、后者为什么需要 Plan。

## 六、Agent vs Workflow

### 卡码知识

[Agent vs Workflow](https://notes.kamacoder.com/llm/app/agent_vs_workflow.html)的判断标准不是有没有分支，而是路径能否提前定义。规则明确的流程优先 Workflow；目标明确但路径不确定、需要多工具探索和中途判断时才使用 Agent。过度 Agent 化会增加成本、延迟、不稳定性和调试难度。

### GeoPilot 怎么实现

- Agent：理解自然语言、选择检查/RAG/CRS 工具、基于 Observation 调整、生成计划。
- Workflow：审批状态、计划编译、投影、面积、缓冲、融合、求交、连接、验证、导出、报告。

CRS 分区和空间公式有明确算法，就用确定性函数；“用户到底想分析什么、现有证据够不够、先查数据还是知识”无法完全写死，才交给 Agent。

### 面试问答

**问：为什么不用纯 Agent 自动完成全部 GIS 分析？**

答：米制距离、覆盖面积和文件副作用要求稳定、可审计、可复现。纯 Agent 会把本来明确的算法变成概率决策。GeoPilot 只在路径不确定处使用 LLM，一旦计划获批就交给 Workflow。这个选择不是 Agent 不够高级，而是把自由度放在确实需要的地方。

**你需要亲手做：**把现有 13 步覆盖流程分成“必须确定”和“允许模型决定”两列，并说明错误后果。

## 七、故障模式、Guardrails 与 Human-in-the-loop

### 卡码知识

[Agent 故障模式](https://notes.kamacoder.com/llm/app/agent_failure_modes.html)包括死循环、重复/错误工具、上下文污染、权限越界、错误结果继续传播和不可控副作用。工程兜底不能只写在 Prompt，要结合预算、Schema、权限、状态机、隔离、审批、Trace 和评测。

### GeoPilot 怎么实现

- 死循环：默认最大模型轮数，超限返回 `agent_max_turns` 和有界工具摘要；
- 参数错误：Pydantic Schema 拒绝；模型可读取错误后纠正；
- GIS 语义错误：`planning/validator.py` 拒绝不合法步骤和参数；
- 权限越界：API workspace resolver 同时覆盖直接请求和模型工具路径；
- 高风险副作用：计划必须 `awaiting_approval → approved`，批准不等于执行；
- 执行失败：失败即停，RunStore 保存检查点，恢复时验证成功产物仍存在；
- 幻觉结果：缺失 CRS、文件或无效几何时工具返回稳定错误，Prompt 禁止编造；
- 隐私：Trace 不保存原 Prompt、参数、工具输出和回答正文。

### 当前不足与优化

- 增加 wall-clock、tool-call 和 token 多维预算，不只限制轮数；
- 为工具添加风险标签和审批策略；
- 增加 Prompt Injection、间接注入、工具超时、输出过大、计划篡改、重复请求 Case；
- 审批绑定 plan hash、版本、用户和有效期；
- Memory/RAG 内容需要来源信任等级与冲突规则。

### 面试问答

**问：System Prompt 已经说不能越权，为什么还要代码校验？**

答：Prompt 是模型可见的行为建议，不能成为安全边界。GeoPilot 在 Registry 校验参数，在 workspace resolver 限制路径，在 Plan validator 校验 GIS 语义，在状态机阻止未批准执行。即使模型忽略 Prompt，这些代码仍会拒绝危险动作。

**你需要亲手做：**运行缺失文件或 `../outside.csv` Case，观察 Tool Result、Agent 最终回答和 Trace 各保存了什么。

## 八、RAG、Embedding 与 Agentic RAG

### 卡码知识

RAG 包含离线文档加载、Chunking、Embedding、索引和在线 Query、检索、上下文生成。[Agentic RAG](https://notes.kamacoder.com/llm/intro/agentic_rag.html)让 Agent 决定是否检索、如何继续检索或结合其他工具，而不是每个问题固定检索一次。优化必须区分召回阶段与生成阶段。

### GeoPilot 怎么实现

- 文档：`knowledge/` 下 3 份 Markdown；
- Chunk：标题结构感知 + 递归字符切分，默认 `500/80`，当前 19 chunks；
- Embedding：`BAAI/bge-small-zh-v1.5`，passage/query 分角色，512 维；
- Token 护栏：用同模型 tokenizer 测完整输入，超过 512 token 时建库前失败；
- 索引：透明 JSON + NumPy 精确余弦，适合当前小规模；
- Hybrid：Dense + 中文/标识符 BM25 + RRF，默认候选 12、`rrf_k=60`；
- Rerank：可选 `BAAI/bge-reranker-base`，实测质量未提升且 CPU 延迟大幅增加，默认关闭；
- Agentic：只有索引存在才注册 `search_knowledge`，是否调用由模型决定；
- 评测：20 Query、24 标签，Hybrid Recall@3/MRR/NDCG@3 为 0.975/0.975/0.9521。

### 当前不足与优化

- 检索指标较完整，但缺回答 Faithfulness、Citation Precision、Answer Relevance 和无答案拒答；
- 没有 Query rewrite/分解、metadata filter、相似度拒答和 Context 压缩对照；
- JSON 精确检索不适用于百万向量、增量和并发；达到规模阈值后再评估 Qdrant/pgvector 等；
- 应建立 noisy、ambiguous、multi-hop、no-answer Query，不只增加容易问题。

### 面试问答

**问：为什么有大模型还需要 RAG？**

答：模型参数不能保证包含项目字段、最新规则和可追溯来源。GeoPilot 用 RAG 提供 GIS 规范和数据字典证据，但数值结果仍来自工具。RAG 的价值是外部知识、更新和引用，不是替代计算。

**问：为什么实现了 Rerank 却默认关闭？**

答：我固定 Hybrid 候选和 20 条黄金 Query，用真实 Cross-Encoder 对照。Rerank 的 Recall@3/NDCG@3 反而从 0.9750/0.9521 变为 0.9250/0.9496，CPU 总耗时约从 230.68ms 增至 67.69s，所以保留可选能力但不默认上线。这体现的是评测驱动，而不是组件越多越好。

**你需要亲手做：**解释一个 Chunk 如何从文档变成向量、一个 Query 如何经过 Dense/BM25/RRF 返回引用，并手工计算一个简单 RRF 排名。

## 九、Memory、Working State 与 RAG

### 卡码知识

[Agent Memory](https://notes.kamacoder.com/llm/app/agent_memory.html)需要区分当前对话短期信息、任务状态、跨会话长期记忆和外部知识。把全部聊天永久保存并塞回 Prompt 会产生隐私、污染、冲突和 token 问题。长期记忆通常需要写入策略、作用域、召回、更新、过期和删除。

### GeoPilot 怎么实现

- Working Memory：单次 `AgentRunner.messages`；
- Session State：PlanStore/RunStore 的审批、步骤和产物状态；
- Long-term Memory：`src/geopilot/memory/` 中用户明确确认的偏好、目标和项目背景；
- RAG：项目文档与 GIS 规范，不与个人记忆混存。

Long-term Memory 使用 namespace、kind、key、revision、过期时间和原子 JSON 写入；默认最多召回 6 条、2000 字符。模型没有自动写记忆工具，CLI 写入必须 `--confirmed`。Prompt 将 Memory 标为不可信个性化数据，不能覆盖当前输入、工具事实和审批规则。

### 当前不足与优化

- 词法召回不理解同义表达；可比较词法、Embedding 和混合召回；
- 缺 `proposed → approved` 的模型记忆提案流程；
- 缺冲突合并、新鲜度衰减、敏感数据分类、加密与多租户授权；
- 需要记忆误召回、跨 namespace、过期泄漏、Prompt Injection 和删除验证 Case。

### 面试问答

**问：Memory 和 RAG 有什么区别？**

答：GeoPilot 的 RAG 保存 GIS 规范和数据字典等外部知识；Memory 保存某个 namespace 用户确认的稳定偏好、目标和背景；Plan/Run 是任务状态；messages 是单次工作上下文。四类信息生命周期、可信度和召回方式不同，不能都叫“向量库记忆”。

**你需要亲手做：**写入一条确认偏好，用两个相关/无关 Query 检查召回，再删除并验证它不再进入 Prompt。

## 十、Agent Evaluation 与可观测性

### 卡码知识

[Agent Evaluation](https://notes.kamacoder.com/llm/app/agent_evaluation.html)不能只判断最终答案。还要评估任务完成、工具选择、步骤效率、错误恢复、可靠性和安全。正确失败也是成功：输入不足或权限不允许时，Agent 应停止而不是编造。

### GeoPilot 怎么实现

`AgentEvaluationCase` 声明：

- 预期完成或正确失败；
- 必需/禁用工具；
- 答案稳定事实；
- 预期工具错误；
- 最大轮数和工具调用数；
- 是否禁止精确重复。

评测器计算 Task Success、Required Tool Recall、Tool Success、Error Recovery、Forbidden Violation、Exact Duplicate、Step Efficiency、轮数、调用数和延迟。真实 4-Case DeepSeek V1 为 0.75 Task Success；失败 Case 答案正确但重复进行不同参数的 RAG 检索，超过调用预算。项目保留失败，没有放宽标准制造满分。

Trace 只保存 Prompt hash、模型、状态、耗时、轮数、工具名/成功/错误码和回答字符数，不保存原文与参数。

### 当前不足与优化

- 4 条 Case 太少；扩充 normal/noisy/missing/high-risk/tool-failure/plan-correction/memory-pollution；
- 规则只能检查稳定事实，需增加人工集和独立 LLM Judge 评估忠实度、相关性、引用；
- Judge 需版本化 rubric、与人工一致性样本，避免用被评模型自评；
- 接入 usage，比较质量、token、成本和延迟；多次运行报告方差和置信区间；
- 离线回归之外，未来线上还应关注接管率、拒绝率、工具失败和用户反馈。

### 面试问答

**问：Task Success 75% 是否说明项目失败？**

答：它说明当前 4 条 V1 中 3 条满足结果、过程和安全联合标准，样本太小不能代表生产可靠性。失败恰好发现答案虽然正确但进行了冗余二次检索。这是有价值的回归基线；下一步修改 Prompt/检索决策后用原 Case 重跑，而不是调整指标。

**你需要亲手做：**打开 `evals/agent_cases_v1.json`，为每条 Case 解释为什么要求或禁止某个工具，并设计一条高风险正确失败 Case。

## 十一、Plan-and-Execute、DAG、Checkpoint 与 Replan

### 卡码知识

[Plan-and-Execute DAG](https://notes.kamacoder.com/llm/app/plan_execute_dag.html)把复杂任务表示成依赖图：节点声明输入输出，调度器按依赖执行；Checkpoint 支持中断恢复；环境变化或局部失败时可进行受约束的局部 Replan。真正的可执行计划需要机器契约，不能只是一段自然语言步骤。

### GeoPilot 怎么实现

- Plan Step 有顺序 ID、operation、inputs、parameters、稳定 output、风险和预期结果；
- Validator 做 GIS 语义检查；
- Compiler 检查输入是否来自原始数据或先前 output、输出唯一性和可执行 operation；
- Dispatcher 将 operation 严格映射到一个确定性函数；
- RunStore 保存 immutable manifest、步骤状态、错误和产物；
- Executor 失败即停，resume 只跳过产物仍存在的成功步骤。

### 必须诚实说明的边界

当前编译器验证的是顺序计划中的依赖关系，可以视为受限 DAG 数据依赖，但没有通用拓扑排序和并行调度；没有模型局部 Replan；恢复只重试未完成步骤，不自动改计划。因此简历可写“依赖编译与检查点恢复”，不能写“完整并行 DAG 调度与自动局部重规划”。

### 优化方向

- 增加显式 `depends_on` 和拓扑排序、环检测；
- 先保持串行，只有独立 GIS 节点存在明显收益再并行；
- Replan 只能生成补丁，限制可修改节点，并再次经过语义校验和人工批准；
- 审批绑定 plan hash；输入数据变化后使旧批准失效；
- 用 crash、产物缺失、幂等、局部失败和非法补丁 Case 验证。

### 面试问答

**问：你实现的是 DAG 吗？**

答：当前是顺序执行、带显式 inputs/output 的依赖编译器，它能验证上游产物并形成受限依赖图，但没有通用拓扑并行调度。我不会把它包装成完整 DAG 引擎。下一步会先加 `depends_on`、环检测和拓扑排序，再用独立节点的耗时实验决定是否并行。

**你需要亲手做：**从一次 13 步 Plan 画出产物依赖图，找出理论上可并行的节点，并说明并行写 GeoPackage 可能出现什么问题。

## 十二、MCP 与 Function Calling

### 卡码知识

[MCP](https://notes.kamacoder.com/llm/app/mcp_protocol.html)解决外部能力以标准方式被发现和调用的问题；Function Calling 解决模型如何输出一次结构化调用意图。MCP 通常包含 Host、Client、Server，并提供 tools、resources、prompts；它不是模型、Agent Loop、RAG 或 Memory。协议与当前架构应同时参考 [MCP 官方文档](https://modelcontextprotocol.io/docs/learn/architecture)。

### GeoPilot 当前状态

尚未实现 MCP。现有 Tool Registry 是进程内工具系统，FastAPI 是 GeoPilot 自己的 HTTP 产品协议，都不能声称是 MCP。好消息是确定性工具已有 Pydantic Schema、稳定错误和 workspace policy，具备发布基础。

### 计划实现

MCP V1 只发布两个只读工具：

- `inspect_dataset`：工作区内数据结构和质量检查；
- `recommend_metric_crs`：基于数据范围确定性推荐米制 CRS。

实现要求：

1. MCP Server 复用现有领域函数和 Pydantic 契约，不复制 GIS 逻辑；
2. 所有 source 继续走 workspace resolver；
3. 用独立 MCP Client 做 `list_tools`、合法调用、参数错误、路径越界和稳定返回测试；
4. Server 不接收模型 API Key，也不直接运行 Agent；
5. V1 使用本地传输，确认互操作后再讨论远程 Streamable HTTP；
6. 写操作、计划批准和执行暂不发布，直到身份、审计、幂等和授权成熟。

### 怎么评估

- Tool discovery 是否给出正确名称、描述和 Schema；
- 与进程内工具是否产生等价结果和错误码；
- 外部 Client 是否可以在不了解 GeoPilot 内部代码时调用；
- 路径越界和不合法参数是否 100% 被拒绝；
- 引入 MCP 后的序列化开销和延迟；
- Schema 版本升级是否兼容。

### 面试问答

**问：MCP 和 Function Calling 有什么区别？**

答：Function Calling 是模型输出工具名和参数的结构化机制；MCP 是 Host/Client 与外部 Server 之间发现和调用 tools/resources/prompts 的协议。模型可以通过 Function Calling 请求一个由 MCP Client 转发的工具，但两者处于不同层。GeoPilot 当前只有进程内 Function Calling，MCP 尚未实现；完成 Prompt、工具与模式实验后，会把两个只读 GIS 工具发布并用独立 Client 验证。

**问：为什么不直接把执行分析和删除文件都暴露为 MCP 工具？**

答：协议标准化不等于自动安全。写操作需要身份、授权、审计、幂等和明确审批语义。GeoPilot 先发布只读、确定性、契约稳定的检查工具，用真实互操作和权限测试证明边界后再扩展。

**你需要亲手做：**MCP 阶段运行 Server 与独立 Client，查看 `list_tools` 返回的 JSON Schema，然后亲自尝试一次合法路径和一次 `../` 越界路径。

## 十三、多 Agent 为什么不在当前主线前面

多 Agent 适合动态拆分且可以并行的独立子任务，但会增加通信、上下文、成本、冲突写入和调试复杂度。GeoPilot 当前的 GIS 主任务共享同一 Plan/Run 和空间产物，单 Agent + Workflow 还没有被评测证明是瓶颈。因此 Multi-Agent 仅保留实验候选：只有单 Agent 在扩展 Eval 上稳定失败，且子任务可隔离时，才比较 Supervisor/Worker 与单 Agent 的质量、延迟、成本和冲突率。

**面试回答重点：**不是没听过 Multi-Agent，而是没有数据就不为热点增加架构。

## 十四、后续执行顺序与每阶段交付物

### 阶段 A：Prompt 与结构化输出实验 V1（下一步）

- 讲解 Prompt 0.8.0 每个区块；
- 建立三组 Prompt variant 和六类 Case；
- 接入 usage/token 统计；
- 运行 mock 回归与小规模真实 DeepSeek 对照；
- 输出实验报告，更新双文档和面试回答。

### 阶段 B：Function Calling 与 Tool Design V1

- 逐工具审计名称、描述、Schema、错误和返回 token；
- 加动态最小工具集；
- 评估工具选择、参数有效率和上下文开销。

### 阶段 C：Agent Pattern Comparison V1

- 同题比较直接调用、ReAct、Plan-and-Execute 和一次 Reflection；
- 用任务成功、步骤、token、延迟决定默认策略。

### 阶段 D：RAG Generation + Context Engineering V1

- no-answer、Query rewrite、Context 压缩；
- Faithfulness、Citation Precision、Answer Relevance；
- 统一上下文 token budget 和工具结果清理。

### 阶段 E：MCP V1

- 发布两个只读 GIS 工具；
- 独立 Client 做发现、调用、错误和越界测试；
- 形成 MCP 与 Function Calling 的实际对照。

### 阶段 F：可靠性扩展

- Guardrail/Memory 污染与冲突；
- Agent Eval 扩集、生成 Judge、token/成本；
- 完成后才恢复 Job/SSE、认证和部署支线。

## 十五、简历与面试使用原则

- 只写已经有代码、测试和实验的组件；MCP 当前必须写“计划实现”，不能写“已接入”。
- 指标必须附数据规模，例如“20 条 Query 的 Recall@3 0.975”，不能写成生产总体效果。
- 主动讲负结果：Rerank 未提升、Agent 二次检索超预算、API 工作目录缺陷；它们证明评测和复盘能力。
- 面试先讲业务风险和 Agent/Workflow 边界，再讲技术名词。
- 对尚未实现的 Reflection、生成 Judge、通用 DAG、Multi-Agent、认证部署明确说边界和验证计划。
