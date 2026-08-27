# GeoPilot Agent 面试问题与项目化回答

## 文档职责与回答原则

这是第二份持续追加的 Agent 主文档。问题按组件组织，回答必须基于 GeoPilot 的真实源码、实验和限制，不能只背通用定义。每次项目推进时，应补充新问题、更新已有答案，并在文末追加变更记录。

## 一、项目与架构

### 1. 请用一分钟介绍 GeoPilot

GeoPilot 是一个自然语言驱动的 GIS 分析 Agent。用户提出空间分析问题后，LLM 先调用数据检查和 CRS 推荐工具，再生成具有稳定产物 ID 的结构化计划；计划必须经过人工批准，之后由确定性执行器调用 GeoPandas 完成投影、缓冲、叠置、空间连接、验证、GeoJSON 导出和 Markdown 报告。项目还接入了本地引用型 RAG，让 Agent 检索 GIS 规则和字段定义。核心原则是让 LLM 负责理解和决策，让代码负责数值计算、状态与权限。

### 2. 这是 Agent 还是 Workflow？

两者结合。自然语言理解、工具选择和计划生成属于 Agent；批准后的 13 步空间分析属于确定性 Workflow。纯 Agent 灵活但容易误调用和编造，纯 Workflow 稳定但不能理解开放式需求。GeoPilot 用人工审批和编译器作为两者边界。

### 3. 为什么选择 GIS 场景？

GIS 同时具备开放式自然语言需求和高确定性计算要求，很适合展示 Agent 的合理边界。例如 LLM 可以理解“分析公共服务覆盖”，但 CRS、米制距离、几何有效性、覆盖率公式必须由 GIS 工具计算。这比只做聊天机器人更能体现工程设计。

## 二、模型调用与 Prompt

### 4. 为什么要做模型适配层？

GeoPilot 通过统一 ChatModel 接口隔离供应商，DeepSeek/OpenRouter 使用 OpenAI-compatible Chat Completions，OpenAI 使用 Responses API。Agent Loop 只依赖统一的消息、工具定义和模型响应，不依赖某个 SDK 的对象，因此可以切换模型而不修改 GIS 工具与业务流程。

### 5. API Key 怎么管理？

API Key 只从环境变量或本地 `.env` 读取，`.env` 被 Git 忽略；源码、Prompt、运行轨迹和错误输出都不包含真实密钥。配置错误与模型请求错误使用不同退出码，便于定位但不泄露敏感信息。

### 6. Prompt 怎么设计？

System Prompt 采用显式规则和版本号，规定数据事实必须来自工具、距离分析前必须调用 CRS 推荐、执行型任务必须先提交计划、RAG 引用必须原样保留。Prompt 只承担行为引导；关键约束同时在 Pydantic Schema、语义校验器、状态机和执行编译器实现，因为 Prompt 不能作为安全边界。

### 7. 如何处理模型输出被截断？

模型适配器检查结束原因；当供应商返回长度截断时，不把残缺 JSON 工具参数交给本地工具，而是返回明确协议错误。CLI 允许调整最大输出 token，复杂计划使用更大的上限。

## 三、Function Calling、Agent Loop 与工具

### 8. Function Calling 的完整流程是什么？

Tool Registry 把工具名称、描述和 Pydantic JSON Schema发给模型；模型返回工具名和 JSON 参数；Registry 校验参数、调用本地处理函数，再将结构化结果作为 tool message 加回上下文；模型继续决定调用其他工具或生成最终回答。LLM 只负责选择，真正执行发生在本地代码。

### 9. Tool Registry 解决了什么问题？

它统一工具发现、Schema、参数校验、错误边界和调用分发，避免 Agent Runner 写大量 if/else。未知工具、参数错误和业务错误都会转换为结构化 Tool Result，让模型有机会修正，而不是让进程直接崩溃。

### 10. 工具应该大还是小？

GeoPilot 的模型可见工具采用高内聚业务能力，例如数据检查、CRS 推荐、知识检索和计划提交；底层重投影、缓冲、求交等工具由批准后的执行器调度，不全部暴露给对话模型。这样减少模型选错工具和组合参数的空间，同时保留底层函数的独立测试能力。

### 11. 如何防止 Agent 死循环？

Agent Runner 设置最大模型轮数。超过上限会停止并返回有界工具轨迹，只暴露工具名、成功状态和错误代码，不输出完整 Prompt、密钥或大型结果。后续 Eval 阶段还会统计重复工具调用率和任务成功率。

### 12. 当前短期记忆是什么？

一次运行中的 system、user、assistant 和 tool messages 构成 Working Memory，让模型能看到前几轮工具结果。进程结束后消息不自动跨会话保存。PlanStore/RunStore 是可靠工作流状态，不等同于语义长期记忆。

## 四、规划、Guardrails 与 Human-in-the-loop

### 13. 为什么不让模型直接执行 GIS 工具？

空间分析存在 CRS、单位、字段、几何、覆盖口径和文件写入风险。GeoPilot 要求模型先提交完整计划，用户检查步骤、参数、风险和假设后再批准；这样把不可逆或高风险动作放在人类决策之后。

### 14. 如何保证计划可执行，而不只是看起来合理？

每一步必须包含受限 operation、完整参数、输入引用和唯一 output 标识。语义校验器检查覆盖计算顺序、面积数据血缘、空间连接参数、未覆盖社区恢复、验证字段和导出 CRS；编译器再检查依赖、未来引用、重复产物和审批状态。

### 15. Prompt Guardrail 和代码 Guardrail 有什么区别？

Prompt Guardrail 是软约束，降低模型产生错误计划的概率；代码 Guardrail 是硬约束，错误计划即使由模型生成也不能写入或执行。GeoPilot 两层都使用：Prompt 解释正确方法，Pydantic/Validator/Compiler/状态机负责最终拦截。

### 16. 人工审批状态怎么设计？

计划初始为 `awaiting_approval`，只能显式变为 `approved` 或 `rejected`。提交不等于批准，拒绝需要理由，执行器只接受 approved。状态持久化到文件检查点，重启程序后仍然有效。

## 五、确定性执行与可靠性

### 17. LLM 在执行阶段还参与数值计算吗？

不参与。批准后的 Plan 由 Compiler、Dispatcher 和 GeoPandas 工具执行。LLM 可以解释已验证结果，但覆盖面积、覆盖率、人口估算和设施数都直接来自工具产物。

### 18. 为什么需要 Compiler 和 Dispatcher？

Compiler 把开放的计划对象转换为严格的可执行清单并验证数据依赖；Dispatcher 将有限 operation 映射到唯一函数。它们阻止模型用自然语言描述偷偷替代真实参数，也避免运行时动态执行任意代码。

### 19. 失败后怎么恢复？

RunStore 为每一步保存 pending/running/succeeded/failed 状态、错误和产物元数据。恢复时从第一个未完成步骤继续，并且只有成功步骤的产物仍存在时才跳过。写文件使用临时文件后原子替换，减少半成品。

### 20. GIS 场景最重要的安全规则是什么？

不能在 EPSG:4326 等地理坐标系中直接进行米制距离、缓冲或面积计算；必须先根据数据范围确定适合的米制投影。多个设施缓冲区应先融合避免重复计算覆盖面积，求交丢失的零覆盖社区必须恢复，最终指标必须做范围与空值验证。

## 六、RAG、Embedding 与向量检索

### 21. 为什么需要 RAG，直接问 DeepSeek 不行吗？

DeepSeek 的参数知识不知道 GeoPilot 示例字段的业务含义，也不能保证遵循项目规定的覆盖计算口径。RAG 提供可更新、可引用的项目知识并降低无依据回答；真实字段值、CRS 和空间指标仍由确定性 GIS 工具计算。

### 22. GeoPilot 的完整 RAG 链路是什么？

离线侧：Markdown/TXT 加载 → UTF-8 与空文档校验 → 标题结构解析 → 超长章节递归字符切分 → passage Embedding → 向量归一化 → 保存向量、正文、章节、来源和模型 manifest。

在线侧：Agent 判断需要知识 → `search_knowledge` → query Embedding → 模型名和维度校验 → 精确余弦检索 → Top-K 正文与引用 → Tool Result 进入上下文 → DeepSeek 基于证据回答。

### 23. 为什么选择 `BAAI/bge-small-zh-v1.5`？

项目以中文 GIS 问答为主，当前知识库很小，更看重本地 CPU 可运行、无额外 Embedding API 成本和部署简单。实际输出为 512 维，FastEmbed 分别使用 passage/query 接口处理非对称检索。选择 small 是资源与效果的 baseline 折中，未与其他模型对照前不能宣称最优。

### 24. Embedding、生成模型和 Rerank 有什么区别？

Embedding 使用可离线预计算的独立向量做粗召回；DeepSeek 是生成模型，负责工具决策和答案组织；Rerank 通常把 Query 与少量候选成对输入交叉编码器做精排，可能提高准确性，但增加逐对推理延迟。当前只有 19 个 Chunk，先通过评估决定是否添加 Rerank。

### 25. Chunk 怎么切，为什么？

当前采用结构感知 + 递归字符：Markdown 保留完整标题层级；章节超过 500 字符时，优先在空行、换行、中文句号、问号和分号等自然边界切分，重叠 80 字符。GIS 规范与数据字典有清晰章节，适合结构切分；递归字符是超长章节兜底。500/80 来自四组控制变量实验，不是凭经验写死。

### 26. Chunk 太大、太小分别有什么问题？为什么需要 overlap？

太小会导致语义不完整并扩大索引；太大会混合话题、稀释向量语义、增加上下文噪声。Overlap 让边界附近的信息同时保留在相邻 Chunk，但过大会产生重复召回和额外存储。

### 27. 为什么没有直接用向量数据库？

当前只有 19 个 Chunk，JSON + NumPy 精确遍历更透明、易测试，能展示归一化和余弦相似度底层过程。向量数据库主要解决大规模 ANN、并发、过滤、增量索引与分布式问题；规模和延迟出现瓶颈后再迁移更合理。

### 28. 为什么建库和查询必须使用同一 Embedding 模型？

不同模型的向量不在同一语义空间，余弦相似度没有意义。GeoPilot 把模型名与维度写入 manifest，查询不一致时返回 `embedding_model_mismatch` 或维度错误。

### 29. 这是传统 RAG 还是 Agentic RAG？

属于基础 Agentic RAG：不是每个请求都固定检索，而是索引存在时注册 `search_knowledge`，由 Agent 根据问题决定是否调用。当前还没有 Query 规划、多路检索、自我纠错和动态重试，因此只是 Agentic RAG 第一版。

## 七、RAG 与 Agent 评估

### 30. 如何评估检索？

黄金样例可标注多个相关目标，包括来源、章节、正文子串和 1～3 级相关度。Precision@K 衡量纯度，Recall@K 衡量覆盖，MRR 关注第一个正确结果的位置，NDCG 同时考虑相关度等级和排序位置。

当前 10 条 Top-3 结果：Hit Rate 1.0、Precision 0.3333、Recall 1.0、MRR 0.90、NDCG 0.9262。CRS 和缺失可行性图层问题的黄金片段排第 2。

### 31. 为什么 Precision@3 只有 0.3333，还能说效果好吗？

当前每个问题只人工标注了一个严格黄金片段，Top-3 分母固定为 3，因此一个黄金命中对应 1/3。另两个片段可能有辅助价值，但未标为黄金就不算相关。这个结果说明召回完整，但上下文纯度和标注覆盖仍需改进；不能只展示 Recall 和 MRR 隐藏 Precision。

### 32. 如何证明优化有效？

先固定语料、黄金集、Embedding、Chunk 参数、检索方法和 Top-K 记录 baseline。之后每次只改变一个变量，例如 chunk size，重新计算所有指标并检查单个样例是否退化。指标改善才采纳，不能用“感觉回答更好”。

### 33. 只评估检索够吗？

不够。后续还需评估 Faithfulness、Answer Relevancy、Context Relevancy、Context Recall、引用正确率、无答案拒答，以及完整 Agent 的任务成功率、工具选择准确率、平均轮数、延迟和成本。

### 34. 你是怎么选择 `500/80` 的？

固定 3 份文档、10 条黄金 Query、BGE 模型、余弦检索和 Top-3，只改变 size/overlap。`300/50` 产生 26 个 Chunk，但漏掉一个选址硬约束问题，Recall@3 降到 0.90；500、700、900 三组质量相同。选择 500 是因为它恢复完整召回，同时比更长字符片段更保守地控制输入长度。实验命令和完整指标保存于 `RAG_CHUNK_EXPERIMENT_V1.md`。

### 35. 为什么不选索引最小、速度更快的 `900/120`？

900 在一次本机实验中索引最小，但耗时差异受缓存和系统负载影响，不能据此下稳定性能结论。真实 BGE tokenizer 实验进一步发现 `900/120` 最大达到 686 token，17 个 Chunk 中有 2 个超过模型 512 上限；`700/100` 也有 2 个超限。它们的检索分数虽与 500 相同，但向量实际对应的是被截断内容，因此不能据此选择长 Chunk。

### 36. 字符切块和 token 切块有什么区别？

字符数实现简单、与中英文标点边界容易组合，但字符数和模型 tokenizer 产生的 token 数不是固定比例，尤其中文、英文、数字和专业符号混合时差异明显。GeoPilot 仍使用字符和自然边界生成 Chunk，但在 Embedding 前对最终 `title + section + text` 使用同一 BGE tokenizer 做未截断计数；正式建库会拒绝超限片段。

## 八、尚未实现组件的边界题

### 37. Memory 和 RAG 有什么区别？

RAG 检索外部或项目知识；Memory 保存 Agent 与用户、历史任务相关的状态。GeoPilot 当前有单次 Working Memory 和计划/运行检查点，但没有跨会话语义记忆。长期记忆必须设计写入白名单、用户隔离、过期、删除和隐私规则，不能把全部对话直接向量化。

### 38. MCP 和 Function Calling 有什么区别？

Function Calling 是模型输出结构化工具请求的机制；MCP 是客户端与外部工具/资源服务之间的标准协议。GeoPilot 当前工具只在进程内 Registry 注册，尚未发布 MCP Server。后续会把稳定的 GIS 工具通过 MCP 暴露给其他客户端，但 MCP 不替代 Agent Loop、RAG 或模型。

### 39. 当前系统最大的不足是什么？

RAG 语料和黄金集小，只支持 Markdown/TXT，Chunk 按字符而不是 token，仅稠密检索，没有混合检索、Rerank、相似度拒答和生成侧评估；Agent 没有长期记忆、完整 tracing、成本监控、Web UI、权限系统与部署。当前定位是可运行、可解释、可评估的工程学习项目，不是生产平台。

### 40. 如何证明 RAG 不是孤立的演示脚本，而是真正接入了 Agent？

我做了三层验证。第一层是检索器单元测试，验证切块、Embedding、Dense/BM25/RRF 排序和引用；第二层是黄金集评估，记录 Recall、MRR 和 NDCG；第三层是使用真实 DeepSeek 模型运行 `geopilot agent`，让模型自主调用 `search_knowledge`。Dense 阶段验证过公共设施候选选址，切换默认 Hybrid 后又验证了 EPSG:4326 距离问题；实际响应返回稳定章节引用，同时没有误调用空间分析工具。这证明了真实链路是“LLM 决策 → Function Calling → Hybrid RAG → 引用回答”，而不是在测试代码中直接调用检索函数。

### 41. 你如何发现 Embedding 输入被静默截断？

我没有只看字符长度，而是用生成向量的同一 FastEmbed tokenizer 统计完整 `embedding_text`。FastEmbed 默认 tokenizer 会先截断再返回 token 数，因此直接调用 `token_count` 无法知道原文超了多少；GeoPilot 克隆 tokenizer、关闭克隆体 truncation，再做逐 Chunk 计数。实验发现 700/100 和 900/120 都各有 2 个片段超过 BGE 的 512-token 上限。

### 42. 为什么告警阈值是 80%，它与 512 上限有什么区别？

512 是模型的硬上限，超过后输入会被截断；80% 是 GeoPilot 可配置的工程预警线，默认对应 410 token，用于提前暴露余量不足。`500/80` 的最大输入是 443 token，因而有 3 个告警但没有超限，可以建库；任何大于 512 的输入则会在 Embedding 和写索引前直接失败。告警阈值不是模型能力声明，也不能消除后续语料增长带来的风险。

### 43. 为什么 GeoPilot 要做 Hybrid Search？

Dense Embedding 擅长语义近似，但字段名、EPSG 编号和专业术语需要精确匹配；BM25 正好补足这类词法信号。GeoPilot 同时召回 Dense 与 BM25 候选后用 RRF 融合。在固定 10 条 Query 上 Recall 都是 1.0，但 Hybrid 把 MRR 从 0.90 提升到 0.95、NDCG 从 0.9262 提升到 0.9631，所以有量化依据切换默认。

### 44. 为什么不能直接把余弦分数和 BM25 分数加权相加？

余弦分数通常在 -1 到 1，BM25 分数非负且上界随语料、词频变化，两者量纲和分布不同，直接相加需要额外归一化且对语料变化敏感。RRF 只使用每路排名，公式为各路 `1 / (k + rank)` 之和，对原始分数尺度不敏感。GeoPilot 使用 `k=60`，再除以理论最大值把展示分数归一化到 0～1；这个分数不是概率。

### 45. 中文 BM25 怎么分词？为什么没直接用 Jieba？

当前知识库只有 19 个 Chunk，为保持依赖少、算法透明，GeoPilot 使用 Unicode NFKC 和小写归一化：英文、数字、`service_radius_m`、`EPSG:4326` 等标识符整体保留，连续中文生成双字片段。它不需要领域词典且能覆盖精确短语，但索引更大、语义边界不如专业分词。语料扩大后应对比 Jieba、IK 或搜索引擎 analyzer，而不是把当前方案称为生产级中文检索。

### 46. Hybrid 是否每条 Query 都更好？

不是。真实对照中 2 条排名改善、7 条不变，但 `service_radius_field` 从第 1 降到第 2。聚合 MRR/NDCG 改善且 Recall 没下降，所以当前默认采用 Hybrid；报告仍保留单条退化，后续困难集和 Rerank 需要重点检查这类精确字段问题。不能只汇报平均数隐藏回归。

### 47. 当前 BM25 为什么没有单独持久化索引？

当前只有 19 个 Chunk，`KnowledgeRetriever` 首次 Hybrid 查询时从已有 JSON 向量索引构建内存 BM25，工程上更透明且足够快。复杂度仍是小语料可接受的扫描/内存统计，不支持并发、多副本、增量更新和百万文档。规模扩大时会把词法索引迁移到 Elasticsearch/OpenSearch 或支持稀疏检索的向量数据库。

## 九、简历描述草案

实现自然语言驱动的 GeoPilot GIS Agent：设计 Provider-neutral LLM 适配、Pydantic Function Calling、结构化规划与人工审批，使用确定性 GeoPandas Workflow 完成 13 步覆盖分析并支持失败检查点恢复；构建本地引用型 RAG，采用结构感知切块、BGE 中文 Embedding、同 tokenizer 截断护栏及 BM25 + Dense + RRF 混合检索，在 10 条演示样例上取得 Recall@3 1.0、MRR 0.95、NDCG@3 0.9631，并保留小样本与单 Query 退化边界。

## 迭代记录

### 2026-08-27

- 建立覆盖全部 Agent 组件的统一面试问答文档。
- 合并原 RAG 专项问答，新增架构、模型调用、Prompt、工具、规划审批、执行恢复、评估、Memory 与 MCP 问题。
- 后续每次 Agent 组件变化必须同步追加本文件和 `AGENT_COMPONENTS.md`。

### 2026-08-27：Chunking Experiment V1

- 新增 Chunk 参数实验、字符与 token 区别、参数选择和未选择 900/120 的项目化问答。
- 当前问答更新为 3 文档、19 chunks、10 条黄金集和最新指标。
- 下一轮需要补充 token 感知实现及其面试追问。

### 2026-08-27：真实 Agent 集成验证

- 新增“如何证明 RAG 真正接入 Agent”的项目化回答。
- 证据来自真实 DeepSeek Function Calling，而不是仅依赖 mock 或直接函数测试。

### 2026-08-27：Token-aware Chunking V1

- 新增“如何识别静默截断”和“80% 告警线与 512 硬上限的区别”两道项目化追问。
- 用真实 BGE tokenizer 证明 `500/80` 无超限，而 700/900 各有 2 个超限 Chunk。
- 真实 CLI 失败路径返回退出码 11 且不创建索引；安全默认值成功重建主索引。
- 面试回答明确区分字符分块、token 测量、工程告警和模型硬限制。

### 2026-08-27：Hybrid Search V1

- 新增 Dense/BM25 互补、RRF 原理、中文分词、单 Query 退化和索引规模边界相关问答。
- 简历草案更新为真实 Hybrid 指标，不使用教程示例或虚构提升数据。
- 真实 DeepSeek Agent 已通过默认 Hybrid 路径回答 CRS 问题并保持工具边界。
- 全项目 146 项自动化测试通过。
- 下一轮面试准备聚焦困难负例设计、候选池大小和是否需要 Cross-Encoder Rerank。
