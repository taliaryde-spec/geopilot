# GeoPilot Agent 组件地图

这份文档区分“已经形成第一条可运行闭环”和“完整大模型应用的全部组件”。第一条闭环是：自然语言问题 → LLM 规划与工具调用 → 人工审批 → 确定性 GIS 执行 → 验证 → 地图数据与报告。RAG、Embedding、跨会话长期记忆、系统化评测、Web UI 和 MCP 是后续独立阶段，不因第一条闭环跑通而自动视为完成。

## 当前调用链

```text
用户自然语言
    ↓
CLI
    ↓
System Prompt + Agent Loop
    ↓
LLM Adapter（DeepSeek / OpenRouter / OpenAI）
    ↕ Tool Calling
数据检查 / CRS 推荐 / 结构化计划提交
    ↓
PlanStore（awaiting_approval → approved / rejected）
    ↓ execute
计划编译器 → Dispatcher → 确定性 GIS 工具
    ↓
RunStore（步骤检查点、失败信息、产物元数据）
    ↓
GeoPackage / GeoJSON / Markdown
```

## 已有组件及源码位置

| 组件 | 当前实现 | 主要位置 | 作用 |
|---|---|---|---|
| LLM 配置 | 已完成 | `src/geopilot/agent/config.py` | 从环境变量读取提供商、模型、API Key、Base URL 和输出 token 限制 |
| LLM 抽象接口 | 已完成 | `src/geopilot/agent/client.py` | 用统一接口隔离不同模型 API |
| DeepSeek / OpenRouter 适配 | 已完成 | `src/geopilot/agent/chat_completions.py` | 通过 OpenAI-compatible Chat Completions 调用模型与 Tool Calling |
| OpenAI 适配 | 已完成 | `src/geopilot/agent/openai_responses.py` | 对接 Responses API |
| 模型工厂 | 已完成 | `src/geopilot/agent/factory.py` | 根据配置选择实际模型适配器 |
| System Prompt | 已完成，持续迭代 | `src/geopilot/agent/prompts.py` | 定义 GIS 安全规则、规划规则、工具参数和禁止编造约束 |
| Agent Loop | 已完成 | `src/geopilot/agent/runner.py` | 维护单次任务消息、循环请求模型、执行工具调用并返回工具结果 |
| Tool Registry | 已完成 | `src/geopilot/agent/registry.py` | 注册工具定义、校验参数并根据工具名调用 |
| LLM 工具适配 | 已完成 | `src/geopilot/agent/tool_adapters.py` | 把数据检查、CRS 推荐和计划提交暴露为模型可调用工具 |
| 结构化规划 | 已完成 | `src/geopilot/planning/models.py` | 使用 Pydantic 定义计划、步骤、风险、输入、参数和稳定产物 ID |
| Guardrails | 已完成第一版 | `src/geopilot/planning/validator.py` | 拒绝错误 CRS、错误覆盖计算顺序、缺失字段、含糊空间连接等计划 |
| Human-in-the-loop | 已完成 | `src/geopilot/planning/store.py` | 计划必须经过批准后才能执行 |
| GIS 工具层 | 已完成当前矢量 MVP | `src/geopilot/tools/` | GeoPandas 负责重投影、缓冲、求交、统计、验证和报告 |
| 计划编译器 | 已完成 | `src/geopilot/execution/compiler.py` | 把已批准计划转换为具有明确依赖关系的可执行清单 |
| Dispatcher | 已完成 | `src/geopilot/execution/dispatcher.py` | 将每种计划 operation 严格绑定到一个确定性 GIS 函数 |
| 执行与恢复 | 已完成第一版 | `src/geopilot/execution/executor.py` | 顺序执行、失败停止、跳过已成功步骤并从检查点恢复 |
| 运行存储 | 已完成第一版 | `src/geopilot/execution/store.py` | 保存 manifest、run 状态、工具结果元数据和产物路径 |
| 用户入口 | CLI 已完成 | `src/geopilot/cli.py` | inspect、agent、show-plan、approve、reject、execute、show-run、resume |

## Memory 现在有什么

当前有两种“任务内状态”，但还没有完整长期记忆：

- 单次 Agent Working Memory：`runner.py` 中的 `messages` 保存本轮用户、模型和工具消息；进程结束后不跨会话保留。
- 任务检查点：`artifacts/plans` 与 `artifacts/runs` 保存审批状态、执行状态和产物依赖；这是可靠的工作流状态，不是语义记忆。

后续 Memory 阶段会增加会话摘要、用户偏好、历史任务检索、写入边界、遗忘和隐私策略。不会把所有对话无选择地写入向量库。

## RAG、Embedding 在哪里

当前尚未实现，路线图第 8 阶段会加入：

```text
GIS 规范 / 项目文档 / 数据字典
    ↓ 文档加载
Chunking
    ↓
Embedding
    ↓
Vector Store
    ↓ 相似度检索 + 元数据过滤
带来源引用的上下文
    ↓
Planner / Agent
```

GeoPilot 的 RAG 用于检索 CRS 说明、空间分析规范、字段定义和项目知识，不用于替代 GeoPandas 的数值计算。该阶段还会建立检索测试集，衡量 Recall@K、引用正确率和回答忠实度。

## MCP 在哪里

当前尚未实现。MCP 阶段会把已经稳定、具有 Pydantic 输入输出契约的 GIS 工具发布为 MCP Server，使其他 Agent 或桌面客户端也能发现和调用它们。MCP 是工具互操作协议，不是模型、RAG 或记忆本身。

## 后续完整组件顺序

1. RAG、Embedding、向量存储、引用和检索评测。
2. 会话记忆、任务记忆、用户偏好与长期记忆边界。
3. Eval、Tracing、日志、token/成本统计与回归数据集。
4. FastAPI、Web GIS 图形界面、数据库和权限边界。
5. Docker、CI/CD、安全检查和部署。
6. MCP Server，将稳定 GIS 能力提供给外部 Agent。

这套顺序先保证 Agent 会正确计算和失败，再增加知识、记忆与产品界面，便于定位每个阶段的问题并形成可展示的工程提交历史。
