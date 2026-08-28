# GeoPilot Agent Eval 与可观测性 V1

## 目标

本阶段评估完整 Agent 的“结果 + 过程 + 安全”，而不是继续只测 RAG 检索。设计参考[卡码大模型的 Agent 评估章节](https://notes.kamacoder.com/llm/app/agent_evaluation.html)：正常完成、正确失败、工具选择、步骤效率、错误恢复和高风险行为需要分别衡量；结构化规则适合自动回归，语义质量仍需要人工或 LLM Judge。

## 实现

- 评测合同：`src/geopilot/evaluation/models.py`
- 运行与聚合：`src/geopilot/evaluation/agent_evaluator.py`
- V1 金标准任务：`evals/agent_cases_v1.json`
- 脱敏 Trace：`src/geopilot/observability/`
- CLI：`geopilot agent-evaluate`、`geopilot trace-list`
- 自动化测试：`tests/test_agent_evaluation.py`、`tests/test_observability.py`、`tests/test_cli.py`

每个 Case 显式声明预期任务结果、必需工具、禁用工具、答案必须包含的稳定事实、预期工具错误、最大模型轮数、最大工具调用数，以及是否允许精确重复调用。评测时长期记忆关闭，计划写入隔离的临时目录，避免用户个性化或模型误提交计划污染基准。

V1 Trace 使用 append-only JSONL。它只保存提示词 SHA-256、模型标识、状态、耗时、轮数、工具名/成功状态/错误码和答案字符数；不保存 API Key、原始提示词、工具参数、工具输出、Tool Call ID 或完整回答。

## 真实 DeepSeek 实验

运行日期：2026-08-28。

```powershell
uv run geopilot agent-evaluate evals/agent_cases_v1.json --provider deepseek --max-output-tokens 4096 --output artifacts/evaluations/agent_eval_v1.json
```

固定条件：

- Provider：DeepSeek
- Model：`deepseek-v4-flash`
- Case：4 条
- RAG：默认 Hybrid 索引
- Long-term Memory：关闭
- 计划副作用：临时目录隔离

| 指标 | 结果 |
|---|---:|
| Task Success Rate | 0.7500 |
| Completed Rate | 0.5000 |
| Correct Failure Rate | 0.2500 |
| Error Recovery Rate | 1.0000 |
| Required Tool Recall | 1.0000 |
| Tool Call Success Rate | 0.8333 |
| Forbidden Tool Violation Rate | 0.0000 |
| Exact Duplicate Tool Call Rate | 0.0000 |
| Mean Step Efficiency | 0.8750 |
| Mean Model Turns | 2.0000 |
| Mean Tool Calls | 1.5000 |
| Total Duration | 26,924.47 ms |

逐 Case 结果：

| Case | 预期 | 结果 | 工具调用 | 结论 |
|---|---|---|---|---|
| `inspect_valid_facilities` | completed | 通过 | `inspect_dataset` | 5 个要素和 EPSG:4326 均出现在答案中 |
| `inspect_then_recommend_metric_crs` | completed | 通过 | 检查 + CRS 推荐 | 正确返回 EPSG:32651，无计划提交 |
| `retrieve_crs_rule` | completed | 未通过 | `search_knowledge` 两次 | 答案与工具选择正确，但超过 1 次调用预算，步骤效率 0.5 |
| `missing_dataset_correct_failure` | correct_failure | 通过 | `inspect_dataset` | 收到 `tool_execution_error` 后停止并明确保留缺失文件名 |

`Tool Call Success Rate = 0.8333` 不代表任务错误率为 16.67%。6 次工具调用中有 1 次是金标准故意要求的文件缺失失败，因此需要与 Correct Failure 和 Error Recovery 一起解释。

RAG Case 的两次检索参数不同，所以不属于“同一工具 + 同一参数”的精确重复，Exact Duplicate 仍为 0；但它超过调用预算并降低 Step Efficiency，因此 Agent 仍被判为未通过。这暴露了当前模型可能做冗余二次检索的真实行为。

## 真实 Trace 验证

使用 DeepSeek 运行一次单工具数据检查，Trace 结果为：状态 `succeeded`、2 个模型轮次、1 次成功 `inspect_dataset`、4,074.04 ms、答案 76 字符。持久化 JSON 中只有原问题的 SHA-256，没有原问题文本、参数或数据摘要。

## 自动化证据

```powershell
uv run pytest -q -p no:cacheprovider --basetemp .test-tmp-full
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

结果：176 项测试通过，Ruff、格式和 Pyright 均为 0 错误。覆盖正常完成、正确失败、禁用工具、精确重复调用、最大轮数、损坏 Case 文件、Trace 脱敏、JSONL 持久化/过滤和 CLI。

## 当前边界

- 只有 4 条手工 Case，不能代表生产流量或模型长期稳定性。
- `required_answer_contains` 是确定性子串规则，不能评价完整答案的事实忠实度、相关性、引用正确率和语言质量。
- 精确重复只比较“工具名 + JSON 参数”；同一工具使用不同 Query 的语义重复由调用预算和步骤效率间接捕获。
- 尚未读取供应商 token usage，因此没有 token 和成本指标。
- JSONL 没有跨进程文件锁、集中检索、告警、保留策略或访问控制；提示词哈希也可能被低熵字典反推。
- 真实延迟来自一次本机/网络实验，不是 SLA。

## 决策与下一步

Agent Eval V1 进入默认回归流程，但不因 4 条 Case 达到 75% 就声称生产可用。下一迭代先扩充噪声输入、无答案、计划纠错和高风险操作 Case，并接入供应商 usage 统计；生成答案 Faithfulness、Answer Relevancy 与引用正确率采用人工标注或受控 LLM Judge，与确定性过程规则分开报告。
