# GeoPilot RAG Chunking Experiment V1

## 实验问题

GeoPilot 最初使用 `chunk_size=700`、`overlap=100`，但这只是工程 baseline，没有实验依据。本实验参考[结构感知与递归字符切片的选择框架](https://notes.kamacoder.com/llm/app/how_to_chunking.html)，在固定其他条件时比较四组字符切块参数。

## 控制变量

- 日期：2026-08-27
- 知识文档：3 份
- 黄金 Query：10 条
- Embedding：`BAAI/bge-small-zh-v1.5`，512 维
- 检索：L2 归一化后的精确余弦相似度
- Top-K：3
- 固定项：文档内容、加载器、标题结构解析、Embedding 模型、检索算法、评估标签
- 唯一变量：`chunk_size` 与 `chunk_overlap`

为使参数产生真实差异，新增 `knowledge/facility_site_selection.md`，其中“候选点生成、硬约束与排序流程”是较长但主题一致的章节。该文档明确属于演示分析口径，不冒充法定规划规范。

## 复现命令

```powershell
uv run geopilot rag-chunk-experiment knowledge --cases knowledge/retrieval_cases.json --top-k 3
```

## 实验结果

| size/overlap | chunks | 平均字符 | 最大字符 | 索引字节 | Hit@3 | Precision@3 | Recall@3 | MRR | NDCG@3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 300/50 | 26 | 209.27 | 298 | 437,897 | 0.90 | 0.30 | 0.90 | 0.75 | 0.7893 |
| 500/80 | 19 | 273.05 | 448 | 322,916 | 1.00 | 0.3333 | 1.00 | 0.90 | 0.9262 |
| 700/100 | 18 | 286.11 | 693 | 306,517 | 1.00 | 0.3333 | 1.00 | 0.90 | 0.9262 |
| 900/120 | 17 | 298.35 | 765 | 289,974 | 1.00 | 0.3333 | 1.00 | 0.90 | 0.9262 |

耗时只来自一次本机运行，受模型预热、文件缓存和系统负载影响，不作为严格性能结论。索引大小和 Chunk 数是本次语料下的确定结果。

`300/50` 没有在 Top-3 找回 `site_selection_constraints_first` 的黄金片段，说明过细切分在当前语料上破坏了该问题所需的上下文。其余三组检索指标相同。

## 参数选择

项目默认值从 `700/100` 调整为 `500/80`：

1. 它在 10 条黄金集上保持完整 Recall，与 700 和 900 的排序指标相同。
2. 比 300 少 7 个 Chunk，索引减少约 26%，同时修复漏召回。
3. 900 的索引最小，但当前 `chunk_size` 按字符而不是模型 token 计数；更长中文片段更可能接近或超过 Embedding 输入上限并被截断。
4. 500 是当前质量与输入长度风险之间的保守折中，不宣称是所有语料的全局最优值。

## 主索引复验

使用新默认值重建 `artifacts/rag/index.json` 后得到：3 份文档、19 个 Chunk；10 条黄金集的 Hit@3 1.0、Precision@3 0.3333、Recall@3 1.0、MRR 0.90、NDCG@3 0.9262，与实验对应组一致。

## 下一步

实现模型 token 感知的 Chunk 统计，记录每个 `embedding_text` 的 token 数与截断风险。完成后再进入关键词/向量混合检索，继续遵守一次只改变一个变量的原则。
