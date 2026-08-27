# RAG Token-aware Chunking V1

## 目标

验证字符分块产生的完整 Embedding 输入是否超过 `BAAI/bge-small-zh-v1.5` 的 512-token 上限，并检查上一轮选择 `500/80` 的依据。理论参考来自卡码教程的 [Embedding 输入上限](https://notes.kamacoder.com/llm/app/embedding.html)与 [Chunking 大小取舍](https://notes.kamacoder.com/llm/app/how_to_chunking.html)。

## 计数口径

- 语料：`knowledge/` 下 3 份 Markdown 文档。
- 黄金集：`knowledge/retrieval_cases.json`，10 条 Query。
- Embedding/tokenizer：`BAAI/bge-small-zh-v1.5`。
- 检索：精确余弦 Top-3。
- 输入文本：`title + section + text`，不是只统计正文。
- Token 数：克隆 FastEmbed 当前 tokenizer 并关闭克隆体 truncation，统计截断前 `attention_mask`。
- 硬上限：512 token。
- 工程告警线：80%，向上取整为 410 token。

复现命令：

```powershell
uv run geopilot rag-chunk-experiment knowledge --cases knowledge/retrieval_cases.json --top-k 3 --output-directory artifacts/rag/token_chunk_experiments_v1 --token-warning-ratio 0.8
```

## 真实结果

| size/overlap | chunks | 平均 token | P95 token | 最大 token | 最大利用率 | 告警数 | 超限数 | Recall@3 | MRR | NDCG@3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 300/50 | 26 | 202.42 | 298 | 302 | 58.98% | 0 | 0 | 0.90 | 0.75 | 0.7893 |
| 500/80 | 19 | 252.58 | 443 | 443 | 86.52% | 3 | 0 | 1.00 | 0.90 | 0.9262 |
| 700/100 | 18 | 262.94 | 655 | 655 | 127.93% | 3 | 2 | 1.00 | 0.90 | 0.9262 |
| 900/120 | 17 | 272.18 | 686 | 686 | 133.98% | 3 | 2 | 1.00 | 0.90 | 0.9262 |

## 结论

保留 `500/80`。它在当前 10 条小样本上保持完整召回，且所有 19 个 Embedding 输入均未超过 512 token。`700/100` 与 `900/120` 虽然检索指标相同，但各有 2 个 Chunk 在建向量时会被模型截断，因此这些分数不能证明长 Chunk 更合适。

正式 `rag-build` 已增加前置护栏：发现任何超限输入时返回 `embedding_input_token_limit_exceeded`，并且不创建索引文件。80% 告警只用于观察安全余量，不会阻止构建。

真实失败路径使用 `900/120` 返回 CLI 退出码 11，报告 2 个超限输入，探针文件 `token_guard_probe_v1.json` 未创建。随后使用默认 `500/80` 成功重建主索引，输出 19 个 Chunk、平均 252.58 token、P95/最大 443 token、3 个告警和 0 个超限。

## 局限与下一步

- 语料只有 3 份文档，黄金集只有 10 条，不能推广为其他中文知识库的通用最优参数。
- Chunk 仍按字符和结构边界生成；tokenizer 负责测量与阻断，不会自动把超限 Chunk 再切开。
- 自定义 Embedding Provider 需要实现 `TokenCounter` 才能获得同等护栏。
- 下一步固定 `500/80` 与同一黄金集，对比 Dense-only 和 BM25 + Dense Hybrid Search。
