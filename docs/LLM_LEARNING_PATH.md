# GeoPilot 大模型学习与面试主线

GeoPilot 后续大模型部分以[卡码大模型学习路线](https://notes.kamacoder.com/llm/)作为知识框架参考，并用 GIS Agent 的实际代码完成每个知识点。外部教程用于组织学习和准备面试，GeoPilot 的功能边界、技术选型和指标仍必须由本仓库的代码、测试与实验结果证明。

所有组件的实现与迭代统一追加到 [Agent 组件与工程实现记录](AGENT_COMPONENTS.md)，所有项目化面试回答统一追加到 [Agent 面试问题与项目化回答](AGENT_INTERVIEW_QA.md)。

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
| Prompt 与模型调用 | `agent/prompts.py`、模型适配器、Pydantic Tool Schema | 基础闭环完成 | Prompt 版本、结构化输出失败率、token/延迟统计 |
| Function Calling | Tool Registry、数据检查、CRS、计划提交、知识检索 | 已实测 | DeepSeek 多轮工具调用、错误纠正轨迹 |
| RAG 离线链路 | 文档加载、结构感知切块、同模型 tokenizer 检查、Embedding、索引 | 第一版完成 | 3 文档、19 chunks、512 维索引；超限构建前失败 |
| RAG 在线链路 | Query Embedding、Dense + BM25、RRF、可选 Cross-Encoder、引用、Agent 工具 | 检索侧完成 | Dense/Hybrid/Rerank 对照与章节级黄金集 |
| RAG 优化 | 混合检索与 Rerank 已评估；Rerank 无收益故默认关闭 | 当前阶段完成 | 20 Query、24 标签的控制变量实验 |
| RAG 评估 | Precision、Recall、MRR、NDCG | 检索侧完成 | `docs/evaluations/RAG_RERANK_V1.md` |
| Agent 设计 | LLM 决策 + 确定性 Workflow + 人工审批 | 核心闭环完成 | 任务成功率、死循环与权限边界评估 |
| Memory | 工作记忆、任务记忆、长期偏好 | 待开始 | 写入策略、遗忘、隐私和检索评估 |
| MCP | 对外发布稳定 GIS 工具 | 待开始 | MCP Server、外部客户端调用测试 |
| 部署与工程化 | API、Web GIS、容器、CI/CD、监控 | 待开始 | 延迟、吞吐、成本、可用性和安全指标 |
| Transformer 与微调 | 应用开发所需原理和选型边界 | 学习阶段待开展 | 原理笔记、选型题，不为了简历盲目训练模型 |

## 当前 RAG 学习顺序

教程将 RAG 拆为离线与在线两段，并强调先建立评估 baseline，再一次只调整一个变量。GeoPilot 采用以下顺序：

1. 已完成：受控 GIS 文档、结构感知 + 递归字符切块、本地中文 Embedding、精确余弦检索和引用。
2. 已完成：章节与正文片段级黄金标签，Precision@K、Recall@K、MRR、NDCG@K。
3. 已完成：固定 Embedding 和知识库，对比四组 chunk size/overlap，选择 `500/80`。
4. 已完成：用 BGE 的真实 tokenizer 统计完整 Embedding 输入，并在正式建库前拒绝超限 Chunk。
5. 已完成：加入透明 BM25 关键词检索，用 RRF 与 Dense 融合；默认 Hybrid 在当前小样本上改善 MRR/NDCG。
6. 已完成：扩充为 20 条困难 Query、24 个标签，以 12 个 Hybrid 候选对照 `BAAI/bge-reranker-base`；Rerank 的 Recall/NDCG 下降且 CPU 延迟显著增加，因此默认关闭。
7. 后续 Eval 阶段：增加回答忠实度、答案相关性、引用正确率和拒答评估。

下一阶段按完整 Agent 路线进入 Memory：先区分 Working Memory、可靠任务状态和长期用户偏好，再实现白名单写入、作用域、过期与删除，而不是把所有聊天内容直接向量化。

## 主要参考

- [RAG 完整链路：离线阶段与在线阶段](https://notes.kamacoder.com/llm/app/chain_of_rag.html)
- [Embedding、模型选型与 Rerank 区别](https://notes.kamacoder.com/llm/app/embedding.html)
- [四种 Chunking 策略对比](https://notes.kamacoder.com/llm/app/how_to_chunking.html)
- [RAG 检索与生成评估体系](https://notes.kamacoder.com/llm/app/rag_evaluation.html)
