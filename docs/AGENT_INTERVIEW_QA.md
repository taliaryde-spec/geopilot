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

Agent Runner 设置最大模型轮数。超过上限会停止并返回有界工具轨迹，只暴露工具名、成功状态和错误代码，不输出完整 Prompt、密钥或大型结果。Agent Eval V1 进一步统计任务成功率、精确重复调用率和步骤效率；真实 4-Case 实验没有死循环，但发现 RAG Case 做了两次不同参数的检索并因超过调用预算失败。

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

在线侧：Agent 判断需要知识 → `search_knowledge` → query Embedding → 模型名和维度校验 → Dense 与 BM25 双路召回 → RRF 融合 → 可选 Cross-Encoder 精排 → Top-K 正文与引用 → Tool Result 进入上下文 → DeepSeek 基于证据回答。默认不启用 Cross-Encoder，因为真实对照没有质量收益。

### 23. 为什么选择 `BAAI/bge-small-zh-v1.5`？

项目以中文 GIS 问答为主，当前知识库很小，更看重本地 CPU 可运行、无额外 Embedding API 成本和部署简单。实际输出为 512 维，FastEmbed 分别使用 passage/query 接口处理非对称检索。选择 small 是资源与效果的 baseline 折中，未与其他模型对照前不能宣称最优。

### 24. Embedding、生成模型和 Rerank 有什么区别？

Embedding 把 Query 和文档分别编码，文档向量可离线预计算，适合粗召回；DeepSeek 是生成模型，负责工具决策和答案组织；Rerank 把 Query 与每个候选共同输入 Cross-Encoder，交互更充分但不能预计算文档分数。GeoPilot 已实现 `BAAI/bge-reranker-base` 的可选精排，真实实验质量略降且 CPU 延迟大幅增加，所以没有设为默认。

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

当前困难集包含 20 条 Query、24 个相关标签，其中 4 条为多正例。默认 Hybrid 的 Top-3 结果为 Hit Rate 1.0、Precision 0.3833、Recall 0.9750、MRR 0.9750、NDCG 0.9521。`service_radius_field` 的首个相关片段排第 2，`missing_accessibility_weight` 只召回两个正例中的一个。

### 31. 为什么 Precision@3 只有 0.3333，还能说效果好吗？

大多数问题只有一个严格黄金片段，Top-3 命中一个时 Precision 就是 1/3；4 条多正例问题最多可达到 2/3。未标注的辅助片段按评测规则仍算不相关，因此当前 0.3833 不能直接解释为用户看到的上下文有 61.67% 都“错误”。它主要用于同一标签口径下做版本对照，必须与 Recall、NDCG、逐 Query 回归和标注覆盖一起看。

### 32. 如何证明优化有效？

先固定语料、黄金集、Embedding、Chunk 参数、检索方法和 Top-K 记录 baseline。之后每次只改变一个变量，例如 chunk size，重新计算所有指标并检查单个样例是否退化。指标改善才采纳，不能用“感觉回答更好”。

### 33. 只评估检索够吗？

不够。GeoPilot 已增加完整 Agent 的任务成功率、必需/禁用工具、正确失败、步骤效率、平均轮数和延迟评估；仍需补充 Faithfulness、Answer Relevancy、Context Relevancy、引用正确率、无答案拒答，以及 token/成本。过程规则与生成语义 Judge 应分开报告，不能互相替代。

### 34. 你是怎么选择 `500/80` 的？

固定 3 份文档、10 条黄金 Query、BGE 模型、余弦检索和 Top-3，只改变 size/overlap。`300/50` 产生 26 个 Chunk，但漏掉一个选址硬约束问题，Recall@3 降到 0.90；500、700、900 三组质量相同。选择 500 是因为它恢复完整召回，同时比更长字符片段更保守地控制输入长度。实验命令和完整指标保存于 `RAG_CHUNK_EXPERIMENT_V1.md`。

### 35. 为什么不选索引最小、速度更快的 `900/120`？

900 在一次本机实验中索引最小，但耗时差异受缓存和系统负载影响，不能据此下稳定性能结论。真实 BGE tokenizer 实验进一步发现 `900/120` 最大达到 686 token，17 个 Chunk 中有 2 个超过模型 512 上限；`700/100` 也有 2 个超限。它们的检索分数虽与 500 相同，但向量实际对应的是被截断内容，因此不能据此选择长 Chunk。

### 36. 字符切块和 token 切块有什么区别？

字符数实现简单、与中英文标点边界容易组合，但字符数和模型 tokenizer 产生的 token 数不是固定比例，尤其中文、英文、数字和专业符号混合时差异明显。GeoPilot 仍使用字符和自然边界生成 Chunk，但在 Embedding 前对最终 `title + section + text` 使用同一 BGE tokenizer 做未截断计数；正式建库会拒绝超限片段。

## 八、Memory 与尚未实现组件的边界题

### 37. Memory 和 RAG 有什么区别？

RAG 检索 GIS 规范、字段定义等外部知识；Memory 保存用户偏好、长期目标和项目背景；PlanStore/RunStore 保存当前任务的可靠 Session State；Agent messages 是单次 Working Memory。GeoPilot 已实现结构化长期记忆 V1，但没有把聊天历史向量化：用户通过 CLI 明确确认写入，读取时按 namespace、过期和当前 Query 过滤，再以受限上下文注入。

### 38. MCP 和 Function Calling 有什么区别？

Function Calling 是模型输出结构化工具请求的机制；MCP 是客户端与外部工具/资源服务之间的标准协议。GeoPilot 当前工具只在进程内 Registry 注册，尚未发布 MCP Server。后续会把稳定的 GIS 工具通过 MCP 暴露给其他客户端，但 MCP 不替代 Agent Loop、RAG 或模型。

### 39. 当前系统最大的不足是什么？

RAG 语料和黄金集仍小，只支持 Markdown/TXT；虽然已有 Hybrid 和可选 Rerank，但没有相似度拒答、Query 改写和生成侧 Judge。Memory V1 是本地 JSON + 词法过滤，没有自动摘要、语义召回、加密、认证和并发控制。Agent Eval 只有 4 条 Case，Trace 只是本地脱敏 JSONL，还没有 token/成本、集中监控、Web UI、权限系统与部署。当前定位是可运行、可解释、可评估的工程学习项目，不是生产平台。

### 40. 如何证明 RAG 不是孤立的演示脚本，而是真正接入了 Agent？

我做了三层验证。第一层是检索器单元测试，验证切块、Embedding、Dense/BM25/RRF 排序和引用；第二层是黄金集评估，记录 Recall、MRR 和 NDCG；第三层是使用真实 DeepSeek 模型运行 `geopilot agent`，让模型自主调用 `search_knowledge`。Dense 阶段验证过公共设施候选选址，切换默认 Hybrid 后又验证了 EPSG:4326 距离问题；实际响应返回稳定章节引用，同时没有误调用空间分析工具。这证明了真实链路是“LLM 决策 → Function Calling → Hybrid RAG → 引用回答”，而不是在测试代码中直接调用检索函数。

### 41. 你如何发现 Embedding 输入被静默截断？

我没有只看字符长度，而是用生成向量的同一 FastEmbed tokenizer 统计完整 `embedding_text`。FastEmbed 默认 tokenizer 会先截断再返回 token 数，因此直接调用 `token_count` 无法知道原文超了多少；GeoPilot 克隆 tokenizer、关闭克隆体 truncation，再做逐 Chunk 计数。实验发现 700/100 和 900/120 都各有 2 个片段超过 BGE 的 512-token 上限。

### 42. 为什么告警阈值是 80%，它与 512 上限有什么区别？

512 是模型的硬上限，超过后输入会被截断；80% 是 GeoPilot 可配置的工程预警线，默认对应 410 token，用于提前暴露余量不足。`500/80` 的最大输入是 443 token，因而有 3 个告警但没有超限，可以建库；任何大于 512 的输入则会在 Embedding 和写索引前直接失败。告警阈值不是模型能力声明，也不能消除后续语料增长带来的风险。

### 43. 为什么 GeoPilot 要做 Hybrid Search？

Dense Embedding 擅长语义近似，但字段名、EPSG 编号和专业术语需要精确匹配；BM25 正好补足这类词法信号。GeoPilot 同时召回 Dense 与 BM25 候选后用 RRF 融合。历史固定 10 条 Query 上 Hybrid 把 MRR 从 0.90 提升到 0.95、NDCG 从 0.9262 提升到 0.9631且 Recall 不降，因此有量化依据切换默认；这个历史集合已单独快照，避免后续扩充黄金集导致数字无法复现。

### 44. 为什么不能直接把余弦分数和 BM25 分数加权相加？

余弦分数通常在 -1 到 1，BM25 分数非负且上界随语料、词频变化，两者量纲和分布不同，直接相加需要额外归一化且对语料变化敏感。RRF 只使用每路排名，公式为各路 `1 / (k + rank)` 之和，对原始分数尺度不敏感。GeoPilot 使用 `k=60`，再除以理论最大值把展示分数归一化到 0～1；这个分数不是概率。

### 45. 中文 BM25 怎么分词？为什么没直接用 Jieba？

当前知识库只有 19 个 Chunk，为保持依赖少、算法透明，GeoPilot 使用 Unicode NFKC 和小写归一化：英文、数字、`service_radius_m`、`EPSG:4326` 等标识符整体保留，连续中文生成双字片段。它不需要领域词典且能覆盖精确短语，但索引更大、语义边界不如专业分词。语料扩大后应对比 Jieba、IK 或搜索引擎 analyzer，而不是把当前方案称为生产级中文检索。

### 46. Hybrid 是否每条 Query 都更好？

不是。历史 10 条对照中 2 条改善、7 条不变，但 `service_radius_field` 从第 1 降到第 2。扩充到 20 条困难集后，Hybrid Top-3 的 Recall 为 0.975、NDCG 为 0.9521，仍保留字段问题和一个多正例漏召回。默认采用 Hybrid 是基于聚合收益、时延和逐 Query 回归共同决定，不代表每条查询都优于 Dense。

### 47. 当前 BM25 为什么没有单独持久化索引？

当前只有 19 个 Chunk，`KnowledgeRetriever` 首次 Hybrid 查询时从已有 JSON 向量索引构建内存 BM25，工程上更透明且足够快。复杂度仍是小语料可接受的扫描/内存统计，不支持并发、多副本、增量更新和百万文档。规模扩大时会把词法索引迁移到 Elasticsearch/OpenSearch 或支持稀疏检索的向量数据库。

### 48. GeoPilot 的 Rerank 是怎么实现的？

`HybridSearcher` 先用 Dense + BM25 + RRF 召回 12 个候选；`RerankSearcher` 将 Query 与每个候选的 `title + section + text` 交给 `BAAI/bge-reranker-base` 成对打分，再返回 Top-3。`Reranker` Protocol 隔离模型，真实实现延迟加载 FastEmbed Cross-Encoder，测试使用确定性替身。结果保留 Dense、BM25、Rerank 的原始分数和排名，错误边界覆盖空输入、结果数量不匹配与非有限分数。

### 49. 为什么 Rerank 没有提升，是否说明实现失败？

不说明实现失败。Hybrid Top-12 的 Recall 是 1.0，证明 24 个黄金标签已全部进入候选池；Cross-Encoder 重排后 Top-3 Recall 从 0.975 降到 0.925、NDCG 从 0.9521 降到 0.9496，其中两个多正例问题各掉出一个证据。这说明当前模型与项目标签/语料的排序偏好不完全一致。组件契约、真实推理和对照实验都工作正常，只是实验结论是不采用它作为默认策略。

### 50. 如何判断问题出在召回还是 Rerank？

先测候选池 Recall，再测最终 Top-K。GeoPilot 的 Hybrid Top-12 Recall 为 1.0，而 Rerank Top-3 Recall 为 0.925，所以不是候选缺失，而是相关候选被 Cross-Encoder 排到 Top-3 之外。如果候选池 Recall 已经低，应该先优化 Query、Embedding、BM25 或候选数；只有候选已经召回，优化精排才有意义。

### 51. 为什么已经写了 Rerank 却不默认上线？

工程能力与产品决策要分开。真实预热实验中 Hybrid 约 230.68ms，Rerank 约 67.69s，同时质量没有提升；模型缓存约 1.052GiB。GeoPilot 因此保留 `hybrid_rerank` 模式供后续模型、硬件和批处理实验，但默认继续使用 Hybrid，并通过延迟加载避免普通 Agent 启动承担大模型成本。

### 52. GeoPilot 的 Memory 为什么不直接保存全部聊天记录？

全部保存会带来上下文膨胀、噪音、过期事实和指令污染。GeoPilot 把原始对话限制在单次 Working Memory，任务状态放入 Plan/Run 检查点，只有稳定且以后有用的信息才能进入长期记忆。V1 只允许 `response_preference`、`user_goal` 和 `project_context`，并要求用户显式 `--confirmed`。

### 53. 为什么不让 LLM 自动调用工具写长期记忆？

模型可能把临时猜测、未确认意向或敏感信息误写成长期事实。V1 因此没有模型可见的 Memory 写工具，只提供用户操作的 CLI；写入记录来源为 `user_confirmed`。后续如果增加模型提议，也应该采用 `proposed → approved/rejected` 状态机，不能让模型直接提交最终记忆。

### 54. 长期记忆如何更新、过期和删除？

`namespace + kind + key` 是唯一身份。相同身份再次确认会保留 memory ID 和 created_at、更新 value/updated_at 并增加 revision；`expires_in_days` 支持 1～3650 天，到期后默认不召回但仍可审计；删除同时校验 namespace 与 memory ID，防止跨作用域误删。

### 55. Memory 如何避免把所有条目塞进 Prompt？

`MemoryContextBuilder` 默认最多选择 6 条、2000 字符。回答偏好天然适用于所有请求；用户目标和项目背景必须与当前 Query 的 `key + value` 有 BM25 同款 token 重叠。过期和其他 namespace 条目先被排除。当前方法透明、可测试，但不能理解没有共同 token 的跨语言同义表达。

### 56. Memory 内容会不会形成 Prompt Injection？

记忆仍是不可信用户数据。GeoPilot 将其放在独立 `<user_memory>` 块中，转义尖括号防止伪造结束标签，并在 Prompt 0.8.0 声明它不能覆盖系统规则、工具证据、人工审批和当前输入；当前输入冲突时以当前输入为准。这个设计降低风险但不是完整安全证明，生产环境还需要输入分类、审计和权限控制。

### 57. 如何证明长期记忆真正接入了 Agent？

首先用自动化测试覆盖 Store、相关召回、Prompt 注入和 CLI 生命周期；然后在临时 namespace 写入“专业方向是 GIS”和“回答时说明关键步骤目的”，禁用 RAG 索引并要求不调用工具。真实 DeepSeek 正确复述两项内容，证明链路是 `Memory Store → Query 过滤 → Prompt 0.8.0 → LLM`，不是从知识库或 GIS 工具得到。

## 九、Agent Eval 与可观测性

### 58. GeoPilot 如何评估完整 Agent？

每条 `AgentEvaluationCase` 同时声明结果、过程和安全期望：任务应正常完成还是正确失败，必须/禁止调用哪些工具，答案必须包含哪些稳定事实，预期哪些工具错误，以及轮数和调用数预算。评测器运行真实 `AgentRunner` 后计算 Task Success、Required Tool Recall、Tool Success、Error Recovery、Forbidden Violation、Exact Duplicate、Step Efficiency、平均轮数/调用数和延迟。它不是只匹配最终一句回答，也不是只检查工具是否曾出现。

### 59. 什么是 Correct Failure，为什么它很重要？

Agent 遇到缺失文件、权限不足或不合法输入时，正确行为不是“想办法给出结果”，而是调用合适工具、识别明确错误并停止，不编造或换用其他数据。GeoPilot 的缺失文件 Case 预期 `inspect_dataset` 返回 `tool_execution_error`，最终回答保留缺失文件名且不调用 CRS/计划工具；真实 DeepSeek 通过，Error Recovery 为 1.0。

### 60. 为什么真实 Task Success 只有 75%，是否项目失败？

不是。4 个 V1 Case 中三个通过；失败的 RAG Case 使用了正确工具、答案也包含 EPSG:4326，但调用两次 `search_knowledge`，超过金标准的一次调用预算，所以步骤效率 0.5 并判失败。这正说明评测能发现“答案对但过程冗余”的问题。项目保留该结果，后续应优化 Prompt 或检索决策，再用相同 Case 回归，不能事后放宽标准制造满分。

### 61. Tool Call Success 0.8333 是否代表 16.67% 的任务失败？

不能这样解释。真实 4-Case 一共有 6 次工具调用，其中 1 次失败是缺失文件 Case 故意要求的正确工具失败。工具调用成功率衡量函数执行，不直接等于任务成功率；它必须和 Expected Outcome、Correct Failure、Error Recovery 一起看。这也是为什么聚合指标不能脱离 Case 语义单独汇报。

### 62. 如何定义重复工具调用？

V1 的 Exact Duplicate 只比较“工具名 + JSON 排序后的完整参数”，因此同工具同参数重复才计数。RAG Case 的两次 Query 不同，所以 Exact Duplicate 为 0，但总调用数超过预算，Step Efficiency 降到 0.5。这个设计区分机械循环和可能有意的重试；语义上是否必要仍需 Case 预算或 Trace 人审，未来可增加 Query 相似度判定。

### 63. Trace 保存什么，如何避免泄露？

默认 JSONL Trace 只保存 Prompt SHA-256、provider/model、终态、耗时、轮数、工具名/成功状态/错误码、答案字符数和顶层错误码。它不保存 API Key、原 Prompt、工具参数、工具输出、Tool Call ID 和完整回答；自动化测试会在序列化字符串中检查敏感样例不存在。`--no-trace` 可以熔断，Trace 写失败只警告，不改变用户任务结果。

### 64. 为什么规则评测不能替代 LLM-as-Judge 或人工评测？

规则适合稳定检查工具、错误码、预算、必需事实和禁用行为，成本低且可重复；但 `required_answer_contains` 无法判断完整答案是否忠实、相关、引用正确或表达清楚。LLM Judge 能覆盖语义但可能受模型偏差、Prompt 和自评泄漏影响；人工评测更可信但昂贵。GeoPilot 当前只完成规则 Eval V1，下一步会为生成质量建立独立标注和 Judge，不把 75% 过程分数包装成答案质量分数。

## 十、FastAPI、Context Engineering 与扩展边界

### 65. 为什么已经有 CLI，还要做 FastAPI？

CLI 证明的是开发者可以在本机完成闭环，FastAPI 提供的是稳定的产品调用边界：前端不需要解析终端文本，而是通过版本化 JSON 契约调用 Dataset、Agent、Plan、Run 和 Trace。`src/geopilot/api/` 直接复用领域服务，不通过子进程调用 CLI；OpenAPI 还能成为后续 Web GIS 和外部集成的接口合同。HTTP 会扩大攻击面，所以 API 比 CLI 增加了 workspace 路径隔离、请求长度限制、稳定错误 envelope 和服务端模型配置。

### 66. GeoPilot 如何防止路径穿越和 Agent 借工具访问工作区外文件？

只校验用户的第一层 HTTP 参数不够，因为模型也可能在后续 Tool Calling 中生成 `../secret` 或工作区外的绝对路径。`GeoPilotApiService` 将每个来源路径解析为规范绝对路径，并检查它仍位于 `workspace_root`；同一个 resolver 被注入 `build_default_tool_registry`，因此模型生成的工具参数也经过相同策略。计划在创建、批准、执行和恢复前会再次校验数据源，避免旧计划或磁盘篡改绕过入口检查。自动化测试同时覆盖直接请求越界、模型工具越界和旧计划越界。

### 67. 为什么 API 不允许客户端传 provider、base URL 和 API Key？

这些字段会把服务端变成可被客户端操纵的任意模型代理，并增加密钥进入访问日志、Trace 或浏览器存储的风险。GeoPilot 的 HTTP 请求只包含任务参数，模型 provider、endpoint 和密钥由服务端环境变量加载；返回值也只包含安全摘要，不返回配置和原始工具参数。V1 仍只建议监听 loopback，因为尚未实现认证、RBAC、限流和 TLS。

### 68. 当前 FastAPI 能否直接部署为生产服务？

不能。当前是本地产品入口 V1，8 项集成测试证明 API 契约、工作区隔离、真实 Agent Loop 的 mock 路径、审批冲突、执行恢复入口和 Trace 查询可用；但 Agent 与 GIS 分析仍在同步请求中运行，没有后台队列、SSE/WebSocket、幂等键、数据库锁、多 worker 一致性、上传限额、认证和负载测试。正确演进顺序是先做本地 Web GIS 演示，再把耗时任务改为 Job，补齐身份和权限后才评估公网部署。

### 69. Context Engineering 和 Prompt Engineering 有什么区别？GeoPilot 怎么做？

Prompt Engineering 主要优化单次指令的措辞和结构；Context Engineering 关注模型在每一步实际看到的全部高信号信息，包括 System Prompt、工具定义、当前消息、RAG 片段、长期记忆和工具结果。GeoPilot 已经把这些来源分层：版本化 Prompt 定义规则，Tool Registry 只暴露必要 Schema，RAG 按 Query 即时检索，Memory 先做 namespace 和相关性过滤，工具结果使用结构化摘要。下一步会加入 token budget、旧工具结果压缩、检索拒答阈值和 Prompt/工具版本 Trace，以量化上下文质量，而不是无限增大 Prompt。

### 70. 为什么现在没有做多 Agent？什么时候值得做？

当前 GIS 任务有清晰的共享状态、严格审批和确定性执行链，多 Agent 会引入状态同步、重复工具调用、额外 token、冲突写入和更难的 Trace，而尚无评测证明它能提高成功率或延迟。因此当前采用一个决策 Agent 加确定性 Workflow。只有当任务出现可独立并行的子问题，例如法规检索、候选区空间计算和报告审查，并且单 Agent 在版本化 Eval 上形成稳定瓶颈时，才会用 Supervisor/Worker 试验；上线条件是质量或总耗时的收益大于成本与复杂度增长。

### 71. MCP 会放在系统哪一层，为什么不是越早接越好？

MCP 位于外部客户端与 GeoPilot 能力之间，提供 tools、resources 和 prompts 的标准发现/调用协议；它不替代模型的 Function Calling、Agent Loop、RAG 或 Memory。GeoPilot 计划先将只读、契约稳定的 `inspect_dataset` 和 `recommend_metric_crs` 发布为本地 MCP Server，并复用现有 Pydantic Schema 与 workspace policy。先完成内部工具、API 和评测，是因为过早发布不稳定工具会把命名、参数和权限问题扩散给外部客户端；写操作要等认证、审计和幂等机制成熟后再开放。

## 十一、简历描述草案

实现自然语言驱动的 GeoPilot GIS Agent：设计 Provider-neutral LLM 适配、Pydantic Function Calling、结构化规划与人工审批，使用确定性 GeoPandas Workflow 完成 13 步覆盖分析并支持失败检查点恢复；构建本地引用型 RAG，采用 BGE 中文 Embedding、token 截断护栏及 BM25 + Dense + RRF，在 20 条困难 Query 上取得 Recall@3/MRR/NDCG@3 0.975/0.975/0.9521，并通过实验否决默认启用高延迟 Rerank；实现用户确认型长期记忆、脱敏 Trace 与 workspace 隔离的 FastAPI 接口；建立结果/过程/安全三维 Agent 回归集，真实 DeepSeek V1 的 Task Success/Required Tool Recall/Error Recovery 为 0.75/1.0/1.0，并保留冗余检索失败案例。

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

### 2026-08-27：困难集与 Cross-Encoder Rerank V1

- 更新为 20 条 Query、24 个标签、4 条多正例的真实评测口径。
- 新增 Cross-Encoder 实现、候选召回/最终排序诊断、Rerank 退化原因和默认上线决策问答。
- 简历草案保留真实 Hybrid 指标，并把“实验否决昂贵组件”作为评测驱动工程证据，不包装成 Rerank 提升。

### 2026-08-28：Long-term Memory V1

- 新增短期消息、Session State、长期记忆和 RAG 四层边界，以及写入/更新/遗忘/Prompt 安全面试题。
- 回答基于 `src/geopilot/memory/`、Prompt 0.8.0、CLI 生命周期测试和真实 DeepSeek 读取验证。
- 全项目 162 项测试、Ruff、格式和 Pyright 均通过。
- 简历草案只描述用户确认型结构化记忆，不声称已有自动摘要、向量记忆或生产多租户安全。

### 2026-08-28：Agent Eval 与脱敏 Trace V1

- 新增完整 Agent 结果/过程/安全评测、Correct Failure、聚合指标解释、重复调用定义、Trace 脱敏和规则/Judge 边界共 7 道项目化面试题。
- 回答基于 `src/geopilot/evaluation/`、`src/geopilot/observability/`、4 条版本化 Case、176 项自动化测试和真实 DeepSeek 实验。
- 如实记录 0.75 Task Success：RAG Case 因二次检索超过预算失败；不把 Required Tool Recall 1.0 或正确答案单独包装成全通过。
- 简历草案加入 Eval 与 Trace 的实际指标，同时明确 4 条 Case 只是 V1，不声称生产可靠性或完整生成质量评测。

### 2026-09-04：Local FastAPI 与 Agent 优化矩阵

- 新增 API/CLI 边界、两层路径穿越防护、服务端模型配置、生产化缺口、Context Engineering、多 Agent 决策和 MCP 发布顺序共 7 道项目化问题。
- 回答基于 `src/geopilot/api/`、`tests/test_api.py` 的 8 项集成测试、全项目 184 项测试和 `docs/evaluations/API_V1.md`，不把本地同步 API 描述为生产服务。
- 新增 `AGENT_OPTIMIZATION_AND_CAREER.md`，逐组件记录当前证据、下一步优化、验收指标和面试表达；简历草案只加入已实现的 workspace 隔离 FastAPI。
