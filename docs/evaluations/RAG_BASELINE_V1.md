# GeoPilot RAG 检索 Baseline V1

## 实验目的

在任何 Chunking、Embedding、混合检索或 Rerank 优化前，记录可复现的检索基线。后续实验每次只修改一个变量，并与本报告比较。

## 固定条件

- 日期：2026-08-27
- 知识来源：`knowledge/gis_analysis_guidelines.md`、`knowledge/data_dictionary.md`
- 文档数：2
- Chunk 数：12
- Chunking：Markdown 结构感知；超长章节最大 700 字符、重叠 100 字符
- Embedding：`BAAI/bge-small-zh-v1.5`
- 维度：512
- 检索：L2 归一化后的精确余弦相似度
- Top-K：3
- 黄金集：6 条人工标注 Query；目标包含来源、章节、正文子串和相关度等级

## 复现命令

```powershell
uv run geopilot rag-build knowledge/gis_analysis_guidelines.md knowledge/data_dictionary.md
uv run geopilot rag-evaluate knowledge/retrieval_cases_v1.json --top-k 3
```

## 结果

| 指标 | 结果 |
|---|---:|
| Hit Rate@3 | 1.0000 |
| Mean Precision@3 | 0.3333 |
| Mean Recall@3 | 1.0000 |
| MRR | 0.9167 |
| Mean NDCG@3 | 0.9385 |

6 条查询都在前三名找回唯一黄金片段。5 条查询的黄金片段排名第 1；`metric_crs` 排名第 2，因此该样例的 reciprocal rank 为 0.5、NDCG@3 为 0.6309。

Precision@3 为 0.3333 不代表另外两个结果必然完全无用，而是当前黄金集每个问题只标注一个精确答案片段；按严格标签计算，Top-3 中只有一个被认定为黄金结果。后续应扩充人工标注，而不是通过放宽匹配规则制造更高指标。

## 当前结论与下一实验

Baseline 的召回已经覆盖全部黄金片段，主要改进空间在首位排序与上下文纯度。下一实验固定知识库、Embedding、检索算法和 Top-K，只比较多组 chunk size/overlap；目标是验证参数依据，并观察 `metric_crs` 是否提升到第 1，同时确保其他样例不退化。
