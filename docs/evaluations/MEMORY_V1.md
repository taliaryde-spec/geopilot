# Agent Long-term Memory V1

## 目标与边界

为 GeoPilot 增加跨进程、跨 CLI 调用的结构化长期记忆，同时避免把全部聊天原文自动写入。设计参考卡码教程的 [Agent 短期记忆、Session State、长期记忆与 RAG](https://notes.kamacoder.com/llm/app/agent_memory.html)：四类状态用途不同，长期记忆必须筛选、按需读取、更新、过期和删除。

GeoPilot 当前分层：

| 类型 | 当前实现 | 生命周期/用途 |
|---|---|---|
| Working Memory | `AgentRunner.messages` | 单次 Agent 运行中的用户、模型和工具消息 |
| Session State | `PlanStore`、`RunStore` | 计划审批、步骤状态、失败和产物依赖 |
| Long-term Memory | `src/geopilot/memory/` | 用户确认的回答偏好、长期目标和项目背景 |
| External Knowledge | `src/geopilot/rag/` | GIS 规范、字段定义和项目知识 |

## 数据与策略

- 允许类型：`response_preference`、`user_goal`、`project_context`。
- 身份：`namespace + kind + key` 唯一；重复写入保留 `memory_id/created_at` 并增加 `revision`。
- 来源：V1 只接受 `user_confirmed`。
- 写入：CLI 必须带 `--confirmed`；没有模型可调用的 Memory 写工具。
- 生命周期：支持 `expires_in_days`、默认过滤过期条目、审计时可显式包含过期条目。
- 删除：必须同时匹配 namespace 和 memory ID。
- 敏感信息：拒绝 secret/token/password/credential 等敏感 key；CLI 明确提示不存密钥。
- 存储：版本化 JSON，临时文件写完并 `fsync` 后通过 `os.replace` 原子替换。
- 召回：回答偏好视为全局；其他类型使用当前 Query 与 `key + value` 的 BM25 同款 token 词法重叠；默认 Top-6、最多 2000 字符。
- Prompt：动态记忆以 `<user_memory>` 块加入 system message，`<`/`>` 会转义；Prompt 0.8.0 明确记忆不能覆盖系统规则、工具事实、审批或当前输入。
- 熔断：`agent --no-memory` 可完全跳过读取，即使存储损坏也不阻塞 Agent。

## CLI 验证

```powershell
uv run geopilot memory-set response_preference learning_style "回答时说明关键步骤的目的" --confirmed --namespace demo
uv run geopilot memory-set project_context academic_major "我的专业方向是地理信息系统（GIS）" --confirmed --namespace demo
uv run geopilot memory-list --namespace demo
uv run geopilot memory-recall "请说明我的专业方向和回答偏好" --namespace demo
uv run geopilot memory-delete <memory_id> --namespace demo
```

本次使用被 Git 忽略的临时 `artifacts/memory-smoke/profile.json` 验证写入与召回，随后让真实 DeepSeek 在禁用 RAG 索引、禁止工具调用的情况下回答。模型正确说明用户专业方向为 GIS，并复述“说明关键步骤目的”的回答偏好，证明链路不是从 RAG 或 GIS 工具获得信息。

## 自动化证据

覆盖以下路径：

- 未确认写入失败且不创建文件。
- 同身份 upsert 保持 ID、revision 增加。
- 过期默认过滤但可审计。
- namespace 隔离和精确删除。
- 敏感 key 与损坏 JSON 拒绝。
- 相关召回、全局回答偏好、无关长期目标过滤。
- 记忆块分隔符转义与字符上限。
- Agent system context 注入。
- CLI 写入、列出、召回、删除完整生命周期。
- `--no-memory` 绕过损坏存储。

本阶段完成后，全项目 162 项 Pytest、Ruff、格式检查与 Pyright 均通过。

## 取舍与限制

- V1 使用透明词法匹配，不支持“GIS”与“地理信息系统”等无共同 token 的同义词召回；后续需在更大记忆集上对比 Embedding/BM25，而不是直接复用知识库索引。
- 回答偏好会在每个启用 Memory 的请求中加入，但其他类型必须与 Query 有词法重叠，避免全量塞入上下文。
- 敏感 key 拦截是基础护栏，不是 DLP；用户仍不应把密钥放在普通 value 中。
- 本地 JSON 没有并发锁、加密、身份认证或租户授权，不能宣称生产级多用户隔离。
- 当前没有自动摘要、重要性模型、冲突审批或模型提出记忆后的人审工作流；V1 有意只允许用户显式 CLI 写入。
