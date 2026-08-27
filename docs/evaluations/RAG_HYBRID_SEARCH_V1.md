# RAG Hybrid Search V1

## 目标

在固定知识库、Chunk、Embedding、黄金集和 Top-K 的前提下，对比 Dense-only 与 Dense + BM25 + RRF，判断是否有证据切换默认检索策略。方法参考卡码教程的 [RAG 优化顺序与混合检索](https://notes.kamacoder.com/llm/app/rag_optimization.html)。

## 实现与参数

- 知识库：3 份文档、19 个 Chunk。
- Embedding：`BAAI/bge-small-zh-v1.5`。
- 黄金集：10 条 GIS Query。
- 最终返回：Top-3。
- Hybrid 候选：Dense 与 BM25 各最多 12 条。
- RRF：`k=60`，两路等权。
- BM25：`k1=1.5`、`b=0.75`。
- 中文处理：连续中文双字片段；英文、数字、字段名和 EPSG 标识符整体保留。
- 计时：同一 Provider 先预热；结果仍只来自一次本机运行。

复现命令：

```powershell
uv run geopilot rag-retrieval-experiment knowledge/retrieval_cases.json --top-k 3 --hybrid-candidate-k 12 --rrf-k 60
```

## 聚合结果

| 模式 | Hit@3 | Precision@3 | Recall@3 | MRR | NDCG@3 | 单次总时长 |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 1.00 | 0.3333 | 1.00 | 0.90 | 0.9262 | 85.72 ms |
| Hybrid | 1.00 | 0.3333 | 1.00 | 0.95 | 0.9631 | 88.96 ms |

差值：Hit、Precision、Recall 均为 0；MRR `+0.05`；NDCG `+0.0369`。逐 Query 为 2 个改善、1 个退化、7 个不变。

## 排名变化

| Query | Dense 首个相关排名 | Hybrid 首个相关排名 | 变化 |
|---|---:|---:|---|
| `metric_crs` | 2 | 1 | 改善 |
| `missing_feasibility_layers` | 2 | 1 | 改善 |
| `service_radius_field` | 1 | 2 | 退化 |
| 其余 7 条 | 1 | 1 | 不变 |

## 决策

默认在线检索切换为 Hybrid，因为当前聚合排序质量改善且 Recall 没有下降。Dense 模式继续保留，用于 baseline、回归定位和控制变量实验。`score` 是归一化 RRF 排序分数，不是相关概率；原始 Dense/BM25 分数与名次均保留在命中结果中。

## 局限与下一步

- 只有 10 条 Query，且每条目前只有一个严格正例，结果不能推广到生产语料。
- 单次耗时差异不能作为稳定性能结论，需要重复运行并记录 P50/P95。
- BM25 在首次 Hybrid 查询时从 JSON Chunk 构建内存统计，没有持久化倒排索引或增量更新。
- 中文双字切分透明但粗糙；需要用更大的 GIS 术语集评估专业分词。
- 下一步扩充困难负例、多正例和语义/词法冲突 Query，再判断 Cross-Encoder Rerank 是否改善精排并修复 `service_radius_field` 回归。

本阶段完成后，全项目 Ruff、格式、Pyright 和 146 项 pytest 均通过；真实 DeepSeek Agent 默认 Hybrid 调用也验证成功。
