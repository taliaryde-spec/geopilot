# RAG Cross-Encoder Rerank V1

## 目标

在固定知识库、Chunk、Embedding、Hybrid 召回、黄金集和 Top-K 的前提下，只增加 Cross-Encoder Rerank，验证它是否能改善精排。实验方法参考卡码教程的 [RAG 优化顺序](https://notes.kamacoder.com/llm/app/rag_optimization.html)：Rerank 只处理已经召回的小候选池，并用对照实验决定是否采用。

## 困难评测集

- `knowledge/retrieval_cases.json`：20 条 GIS Query、24 个黄金相关标签。
- 4 条 Query 包含两个相关目标，用于测试同一问题需要多段证据时的 Recall 与 NDCG。
- 新增语义/词法冲突、派生字段、分析 CRS 与展示 CRS、设施数量与覆盖面积、均匀人口假设及缺失可达性权重等问题。
- 历史 10 条 Hybrid V1 集合保存在 `knowledge/retrieval_cases_hybrid_v1.json`，旧报告不受后续黄金集扩充影响。

## 实现与参数

- 知识库：3 份文档、19 个 Chunk。
- Embedding：`BAAI/bge-small-zh-v1.5`，512 维。
- 第一阶段：Dense + BM25 + RRF，`hybrid_candidate_k=12`、`rrf_k=60`。
- 第二阶段：`BAAI/bge-reranker-base`，对 12 个候选的 `title + section + text` 与 Query 成对打分。
- 最终返回：Top-3。
- 运行环境：Windows，本地 CPU，模型经 FastEmbed/ONNX Runtime 运行；缓存实占约 1.052 GiB。
- 计时：Embedding 与 Reranker 均先预热；单次本机结果只用于量级判断，不作为 SLA。

复现命令：

```powershell
uv run geopilot rag-rerank-experiment knowledge/retrieval_cases.json --top-k 3 --hybrid-candidate-k 12 --rerank-candidate-k 12 --rrf-k 60
```

## 候选池诊断

Hybrid Top-12 的 Hit Rate 为 1.0、Recall 为 1.0，说明 24 个黄金标签全部进入 Rerank 候选池。后续 Top-3 的变化主要反映 Cross-Encoder 排序，而不是第一阶段漏召回。

## 聚合结果

| 模式 | Hit@3 | Precision@3 | Recall@3 | MRR | NDCG@3 | 单次总时长 |
|---|---:|---:|---:|---:|---:|---:|
| Hybrid | 1.0000 | 0.3833 | 0.9750 | 0.9750 | 0.9521 | 230.68 ms |
| Hybrid + Rerank | 1.0000 | 0.3500 | 0.9250 | 0.9750 | 0.9496 | 67,688.53 ms |

Rerank 相对 Hybrid：Precision `-0.0333`、Recall `-0.0500`、MRR `0`、NDCG `-0.0025`。按逐 Query NDCG 比较，1 条改善、2 条退化、17 条不变。

## 逐 Query 变化

- `facility_count_vs_coverage_area`：NDCG 从 0.8340 升至 1.0000，两个证据的顺序更理想。
- `analysis_crs_vs_web_crs`：Recall 从 1.0 降至 0.5，NDCG 从 0.9558 降至 0.7872，一个正例被排出 Top-3。
- `capacity_not_coverage_formula`：Recall 从 1.0 降至 0.5，NDCG 从 0.8340 降至 0.7872，一个正例被排出 Top-3。
- `service_radius_field`：相关片段仍排第 2，Rerank 没有修复原 Hybrid 回归。
- 其余 16 条的 NDCG 不变。

## 决策

保留 `hybrid_rerank` 模式、Reranker 抽象、真实模型适配和实验命令，但默认在线检索继续使用 `hybrid`。原因不是 Rerank 原理无效，而是当前 19-Chunk 语料、20-Query 黄金集和本机 CPU 条件下没有质量收益，同时单次实验耗时约增加两个数量级。

`BAAI/bge-reranker-base` 的输出是相关性排序分数，不是校准概率。GeoPilot 在命中结果中保留 `dense_score`、`bm25_score`、两路排名以及 `rerank_score`、`rerank_rank`，便于定位排序变化。模型只有在显式选择 `hybrid_rerank` 或运行 Rerank 实验时才延迟加载，不影响默认 Agent 启动。

## 局限与下一步

- 20 条 Query 和 3 份项目文档仍是小型人工评测集，不能代表生产效果。
- 当前只测一个 Cross-Encoder、一个候选池大小和一次本机 CPU 运行，未比较模型、批大小、P50/P95 或 GPU。
- 多正例标签揭示了“首个答案正确但证据不完整”的问题；只看 Hit Rate 或 MRR 会遗漏这种退化。
- 下一阶段进入 Memory；RAG 后续再补生成侧 Faithfulness、Answer Relevancy、引用正确率和拒答评估。
