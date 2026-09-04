# Prompt 与结构化输出对照实验 V1

实验日期：2026-09-04

## 目标

这次实验不比较回答文风，而是检查 System Prompt 如何影响完整 Agent 轨迹：工具选择、参数 Schema、错误恢复、步骤效率、越权调用、Token 与延迟。主要实现位于：

- `src/geopilot/agent/prompting/`：版本化 Prompt catalog；
- `src/geopilot/agent/models.py`：Provider-neutral `ModelUsage`；
- `src/geopilot/agent/runner.py`：多轮 usage 累加；
- `src/geopilot/evaluation/prompt_experiment.py`：控制变量实验器；
- `evals/prompt_cases_v1.json`：6 条版本化任务；
- `src/geopilot/cli.py`：`geopilot prompt-experiment` 入口。

## 对照设计

固定以下变量：

- 模型：`deepseek-v4-flash`；
- 提供商：DeepSeek 直连；
- 工具定义：`inspect_dataset`、`search_knowledge`、`recommend_metric_crs`、`submit_analysis_plan`；
- 知识索引、示例数据、Case 和最大模型轮数；
- 最大输出：8192 tokens；
- 长期 Memory：实验不注入；
- 计划写入：每个 variant 使用独立临时目录，实验后删除。

唯一主动变量是 System Prompt：

| Variant | 版本 | 字符数 | 说明 |
|---|---:|---:|---|
| `minimal` | 1.0.0 | 473 | 只保留角色、不编造、米制 CRS、先计划后审批等最小规则 |
| `structured` | 0.8.0 | 5,557 | GeoPilot 当前详细 GIS 工具与审批规则 |
| `structured_few_shot` | 0.8.0-fs1 | 6,195 | 在详细版上增加 4 个简短决策示例 |

6 类 Case 分别是：数据检查、米制 CRS 推荐、基于 RAG 的 CRS 规范回答、缺失数据的正确失败、缓冲区计划提交、无需工具的直接回答。

## 真实结果

| 指标 | minimal | structured | structured_few_shot |
|---|---:|---:|---:|
| Task Success | 0.3333 | 0.3333 | **0.5000** |
| Required Tool Recall | 1.0000 | 1.0000 | 1.0000 |
| Tool Execution Success | 0.5000 | **0.8462** | 0.8333 |
| Tool Argument Schema Valid | 1.0000 | 1.0000 | 1.0000 |
| Forbidden Tool Violation | 0.1667 | 0.1667 | **0.0000** |
| Exact Duplicate Tool Call | 0.0000 | 0.0000 | 0.0000 |
| Mean Step Efficiency | 0.5278 | 0.6278 | **0.7944** |
| Mean Model Turns | 2.5000 | **2.3333** | **2.3333** |
| Mean Tool Calls | 2.3333 | 2.1667 | **2.0000** |
| Total Duration | 91.23s | **65.76s** | 66.36s |
| Input Tokens | **52,789** | 63,645 | 67,730 |
| Output Tokens | 13,009 | **9,167** | 9,826 |
| Total Tokens | **65,798** | 72,812 | 77,556 |
| Cached Input Tokens | 42,624 | 52,096 | 57,088 |
| Reasoning Tokens | 5,237 | **3,937** | 4,461 |

usage 覆盖率为 100%，三组都由提供商返回 Token 统计。

按实验时间对应的 DeepSeek 官方高峰时段单价估算，将 input 拆分为 cache hit 与 cache miss，并单独计算 output：`minimal` 约 0.02224 美元，`structured` 约 0.01791 美元，`structured_few_shot` 约 0.01845 美元，总计约 0.05860 美元。这是根据 Token 与[DeepSeek 官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)计算的实验估算，不是账单，价格变化后应重新计算。

## 逐案例发现

- 三组都通过基础数据检查和缺失数据的 Correct Failure。
- 三组都在 CRS 推荐 Case 多做了一次 `search_knowledge`，在规范问答 Case 调用了两次 `search_knowledge`，因而超过严格工具预算。
- `minimal` 在计划 Case 中 5 轮内连续提交失败，最终触发 Max Turns；详细规则显著提高了该类工具执行成功率。
- 两个详细 Prompt 的计划 Case 都先出现一次工具拒绝，然后自我修正并提交成功；但由于工具总数为 5，超过 Case 预算 4，仍被严格评为失败。这同时暴露了 Case 需区分“有效自我修正”和“无效冗余”。
- 直接回答 Case 中，`minimal` 和 `structured` 都误用 RAG；Few-shot 唯一做到零工具直接回答，使违规率降为 0。
- 三组 Tool Argument Schema Valid 都为 1.0，但计划工具仍可被领域语义校验拒绝：这是“JSON/Schema 合法不等于 GIS 计划正确”的直接证据。

## 决策

**保持 `structured` 0.8.0 为默认，不立即切换 Few-shot。**

Few-shot 在这一次运行中成功率、禁用工具违规和步骤效率更好，总 Token 比 `structured` 高约 6.5%，缓存后估算费用只略高。但样本只有 6 条、每个 variant 只运行一次，不能排除随机性；而且三组仍有共同的重复检索和计划修正成本。下一轮应先扩充 Case，每组重复多次，报告均值/方差，再决定是否升级默认 Prompt。

## 可复现命令

```powershell
uv run geopilot prompt-experiment evals/prompt_cases_v1.json `
  --max-output-tokens 8192 `
  --output artifacts/evaluations/prompt_experiment_v1.json
```

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

本轮代码验证结果：194 项 Pytest 通过，Ruff 与格式检查通过，Pyright 0 错误。

## 局限与下一步

- V1 只有 6 条任务和一次真实运行，不是生产可靠性证明。
- 实验仍受模型随机性、网络和提供商缓存影响；延迟不是稳定 SLA。
- 当前只评分可确定判定的文本片段和工具轨迹，未做 LLM-as-a-Judge 或 GIS 专家盲评。
- 当前 CLI 只在全部 variant 结束后写结果；长实验应增加按 variant 检查点和重试。
- 详细 Prompt 和完整工具 Schema 在每轮重复输入，Token 数据已经指向下一个 Context Engineering 优化：按任务类型动态缩小工具集，并对工具结果做结构化压缩。
