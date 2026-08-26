# GeoPilot

GeoPilot 是一个自然语言驱动的地理空间分析 Agent。用户提供空间数据和分析问题，Agent 将检查数据、规划分析步骤、调用 GIS 工具、验证结果，并生成地图与报告。

> 当前项目处于 v0.1 开发阶段。本仓库已经完成数据检查、真实 LLM Tool Calling 和确定性 CRS 推荐；自然语言规划与空间分析执行工具仍在持续实现。

## 演示场景

分析居民区附近的公共服务设施覆盖情况，找出服务不足的区域，并生成可复现的分析结果与选址建议。

仓库中的演示数据是为项目测试构造的虚构数据，不代表真实设施或人口分布。

## 当前已实现

- GeoJSON、Shapefile 等矢量数据读取
- 带经纬度字段的 CSV 点图层转换
- 字段、记录数、几何类型、CRS、范围和缺失值检查
- 缺失 CRS、缺失几何、空几何和无效几何验证
- 结构化 Pydantic 输出与稳定错误代码
- `geopilot inspect` 命令行接口
- Provider-neutral Agent Loop、System Prompt、Tool Registry 与工作记忆
- OpenAI Responses API、DeepSeek/OpenRouter Chat Completions 与结构化 Tool Calling
- 基于数据范围确定性推荐米制投影 CRS，并禁止 Agent 猜测 EPSG 编号
- Ruff、Pyright 和 Pytest 质量检查

完整组件规划与各阶段验收标准见 [GeoPilot 项目路线图](docs/PROJECT_ROADMAP.md)。

## 快速开始

项目使用 Python 3.13 和 uv 管理依赖与虚拟环境。

```powershell
uv sync --all-groups
```

重新生成演示数据：

```powershell
uv run python scripts/generate_sample_data.py
```

检查公共设施点数据：

```powershell
uv run geopilot inspect examples/data/facilities.geojson
```

检查同一批设施的经纬度 CSV：

```powershell
uv run geopilot inspect examples/data/facilities.csv
```

默认坐标字段为 `longitude` 和 `latitude`。其他字段名可以显式指定：

```powershell
uv run geopilot inspect data/facilities.csv --longitude-column lon --latitude-column lat
```

检查居民区面数据：

```powershell
uv run geopilot inspect examples/data/neighborhoods.geojson
```

运行真实模型 Agent 前，复制 `.env.example` 为 `.env`，填写自己的 API 密钥：

```powershell
Copy-Item .env.example .env
```

`.env` 已被 Git 忽略，不能把真实 API Key 写入源码或提交到仓库。示例默认使用 DeepSeek 直连：

```dotenv
GEOPILOT_PROVIDER=deepseek
DEEPSEEK_API_KEY=your-key
```

也可以切换到 OpenRouter，但必须填写一个支持 Tool Calling 的完整模型 ID：

```dotenv
GEOPILOT_PROVIDER=openrouter
OPENROUTER_API_KEY=your-key
OPENROUTER_MODEL=provider/model-name
```

配置完成后运行：

```powershell
uv run geopilot agent "请检查 examples/data/facilities.csv，并说明数据是否可以继续分析"
```

Agent 会把 `inspect_dataset` 的 JSON Schema 发给模型。模型选择工具后，本地代码执行检查，再把结构化结果返回模型生成最终回答。切换供应商只改变模型适配层，不改变 Agent Loop 或 GIS 工具。SDK 重试次数、超时和最大输出 token 可在 `.env` 中配置。

请求距离、缓冲区或面积分析时，Agent 必须调用 `recommend_metric_crs`，不能自行猜测 UTM 分区或 EPSG 编号：

```powershell
uv run geopilot agent "请为 examples/data/facilities.csv 推荐适合距离分析的投影坐标系"
```

上海演示数据的确定性结果是 `EPSG:32651`（WGS 84 / UTM zone 51N）。工具同时返回线性单位、是否需要重投影、计算方法和范围风险警告。

命令会向标准输出写入 JSON，其中包含：

- `profile`：数据事实，例如字段、CRS、范围和几何统计
- `validation.issues`：结构化错误或警告
- `validation.can_proceed`：是否允许进入后续空间分析

## CLI 退出码

- `0`：数据可以继续分析，只有 warning 时也返回 `0`
- `2`：命令参数使用错误
- `3`：输入文件不存在
- `4`：数据验证发现阻断性错误
- `5`：CSV 字段、坐标值或坐标范围无效
- `6`：模型密钥、模型名或其他配置无效
- `7`：模型鉴权、限流、超时、连接或 API 请求失败
- `8`：模型返回格式或 Agent 循环异常

PowerShell 可以通过 `$LASTEXITCODE` 查看退出码；Windows CMD 可以运行 `echo %ERRORLEVEL%`。

## CSV 输入约定

- 经度作为 X，范围必须为 `[-180, 180]`
- 纬度作为 Y，范围必须为 `[-90, 90]`
- 坐标不能为空、不能是非数值或无穷值
- 转换后的点图层明确使用 `EPSG:4326`
- 当前 MVP 不自动识别分隔符、文件编码、度分秒坐标或压缩 CSV
- CSV 已有名为 `geometry` 的字段时会拒绝转换，避免覆盖原始信息

## 项目结构

```text
src/geopilot/
├── agent/                 # Prompt、模型接口、工具注册表与 Agent Loop
├── cli.py                 # 命令行适配层
├── models.py              # Pydantic 数据契约
├── tools/                 # 可独立测试的确定性 GIS 工具
└── workflows/             # 组合多个工具的业务流水线
scripts/
└── generate_sample_data.py
examples/data/             # 可复现的虚构演示数据
tests/                     # 单元测试与集成测试
```

## 开发质量检查

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q
```

## MVP 路线图

- [x] 检查矢量数据并生成结构化摘要
- [x] 在分析前验证 CRS、缺失值和几何质量
- [x] 读取带经纬度字段的 CSV 并转换为点图层
- [x] 根据数据范围推荐米制投影 CRS，禁止 Agent 编造 EPSG
- [ ] 将自然语言问题转换为空间分析计划
- [ ] 在执行前让用户确认分析计划
- [ ] 执行米制投影、缓冲区和空间连接
- [ ] 验证分析结果并输出 GeoJSON 与 Markdown 报告
- [ ] 提供可交互的 Web 界面

## v0.1 验收标准

- 系统能够读取一个 GeoJSON 面图层和一个带经纬度字段的 CSV 点图层
- 系统能够输出字段、记录数量、几何类型、CRS 和缺失值统计
- 进行距离分析前，系统必须转换到使用米作为单位的投影坐标系
- Agent 必须先生成包含输入、步骤、输出和风险的计划，获得用户确认后才能执行
- 系统能够完成缓冲区和空间连接，并输出 GeoJSON 结果与 Markdown 报告
- 报告必须包含 CRS、距离单位、匹配数量、未匹配数量和空值比例
- 输入缺少 CRS、经纬度字段或包含无效几何时，系统必须明确报错，不能编造结果

## v0.1 暂不实现

- 栅格和遥感影像分析
- QGIS 插件
- PostGIS
- 多 Agent 并行工作流
- 云端部署
