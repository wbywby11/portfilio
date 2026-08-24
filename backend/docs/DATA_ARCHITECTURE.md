# 数据架构设计

> **定位**：本文档是系统数据层的唯一设计权威。从功能需求出发定义"应该有什么"，而非记录"现在有什么"。
> 任何新增/修改集合必须先更新本文档，再写代码。

---

## 一、设计原则

### 1.1 核心原则

| 原则 | 说明 |
|------|------|
| **功能驱动** | 每个集合必须对应一个明确的业务功能，无功能引用的集合不应存在 |
| **单一职责** | 一个集合只存一类数据；禁止"万能文档" |
| **契约优先** | Schema 先定义后使用；写入方和读取方共享同一份 Pydantic Model |
| **幂等写入** | 所有导入/生成操作必须可重复执行，结果一致 |
| **可追溯** | 系统生成的数据须记录生成时间、触发来源 |

### 1.2 命名规范

| 对象 | 规范 | 示例 |
|------|------|------|
| 集合名 | 小写 snake_case，复数名词 | `assets`, `monitor_states` |
| 字段名 | 小写 snake_case | `asset_code`, `created_at` |
| 业务唯一键 | 联合唯一索引，不依赖 `_id` | `{asset_code: 1, date: 1}` |
| 时间戳 | `created_at` / `updated_at` | MongoDB ISODate |
| 布尔 | `is_` / `enable_` 前缀 | `is_active` |
| 系统内部集合 | `_` 前缀 | `_collection_registry` |

### 1.3 日期标准

| 场景 | 存储类型 | 格式 | 查询方式 |
|------|---------|------|---------|
| 业务日期（行情、汇率、调仓日等） | **string** | `"YYYY-MM-DD"` | 字符串比较 |
| 交易日历（历史原因） | datetime | ISODate | datetime 比较 |
| 时间戳（created_at 等） | datetime | ISODate | — |

**强制规则**：
- 前端/Excel 输入兼容多格式（YYYYMMDD、Excel序列日），但**入库前必须归一化为 `YYYY-MM-DD` 字符串**
- 禁止对字符串日期字段用 datetime 对象查询（类型不匹配会静默返回空）

### 1.4 集合名与字段映射集中管理

```
app/config/collections.py      ← 所有集合名常量（禁止硬编码字符串）
app/schemas/field_mappings.py  ← 所有导入列名映射（禁止各处重复定义）
```

---

## 二、功能域与集合设计

系统按功能划分为 **8 个域**，共 **44 个设计集合**（2026-07-23 全量审计后更新）。

---

### 域 1：市场行情数据（Market Data）

> 功能：为回测、监控、估值提供基础价格数据。用户通过 Excel/API 导入维护。

#### `assets` — 资产主数据

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `code` | string | ✅ | 资产代码（业务主键） |
| `name` | string | ✅ | 资产名称 |
| `instrument_type` | enum | ✅ | 工具形态，驱动 TR 计算分支（见 8.1） |
| `asset_class` | enum | ✅ | 资产大类，用于过滤/分组/风控（见 8.2） |
| `security_type` | enum | — | 证券细分标签（可选，见 8.3） |
| `exchange` | string | — | 交易所 |
| `description` | string | — | 描述 |
| `is_active` | bool | ✅ | 是否启用 |
| `rollover_days` | int | — | 期货展期天数（`instrument_type = 期货型` 专用） |
| `rollover_threshold` | float | — | 持仓量阈值（期货型专用） |
| `rollover_window_p` | int | — | 观察窗口起点（期货型专用） |
| `rollover_window_q` | int | — | 观察窗口终点（期货型专用） |
| `substitute_code` | string | — | 替代标的代码（现货型专用） |
| `switch_date` | string | — | 切换日期（现货型专用） |
| `currency` | string | — | 计价货币 |
| `trading_cost_rate` | float | — | 交易费率 |
| `replication_cost_rate` | float | — | 复制费率 |
| `created_at` | datetime | 自动 | — |
| `updated_at` | datetime | 自动 | — |

- **唯一索引**: `{code: 1}`
- **写入来源**: 前端新增/批量导入、Agent 导入
- **被消费方**: 几乎所有模块

**三维度正交分类设计**（对标 Bloomberg / Wind / FactSet）：

> 成熟金融系统（Bloomberg、FactSet、Wind）均采用**多维度正交分类**：每个维度独立字段、职责单一，绝不用单字段混存。本系统借鉴该共识，将资产分类拆分为三个正交维度：

| 维度 | 字段 | 职责 | 值域 |
|---|---|---|---|
| 工具形态 | `instrument_type` | **驱动计算逻辑**（TR 分支、表单字段、展期参数） | 指数型 / 现货型 / 期货型 |
| 资产大类 | `asset_class` | **业务分组**（过滤、报告、风控、Agent 查询） | 权益 / 固收 / 商品 / 货币 / 另类 |
| 证券细分 | `security_type` | **细粒度标签**（可选，用于精确筛选） | 股票 / 指数 / ETF / LOF / 债券 / 基金 / 期货 / 数字货币 |

**典型资产组合示例**：

| code | name | instrument_type | asset_class | security_type |
|---|---|---|---|---|
| 000300.SH | 沪深300 | 指数型 | 权益 | 指数 |
| 510300.SH | 华泰柏瑞300ETF | 现货型 | 权益 | ETF |
| IF.HOT | IF主力 | 期货型 | 权益 | 期货 |
| CBA00101.CS | 中债总财富指数 | 指数型 | 固收 | 指数 |
| T.HOT | 10年国债期货 | 期货型 | 固收 | 期货 |
| 518880.SH | 黄金ETF | 现货型 | 商品 | ETF |
| BTC-USD | 比特币 | 指数型 | 另类 | 数字货币 |

> **历史遗留（已废弃）**：旧设计将 7 个基础类型（股票/债券/商品/货币/基金/指数/数字货币）和 3 个业务分类（指数类/现货类/期货类）共 10 个值混存在同一个 `asset_type` 字段中，导致代码两套逻辑并存、TR 默认值与业务值不一致、Agent 查询结果不确定。本设计彻底解决该问题。

---

#### `asset_prices` — 日频行情

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `asset_code` | string | ✅ | FK → assets.code |
| `date` | string | ✅ | `YYYY-MM-DD` |
| `open` | float | — | 开盘价 |
| `high` | float | — | 最高价 |
| `low` | float | — | 最低价 |
| `close` | float | ✅ | 收盘价 |
| `volume` | float | — | 成交量 |
| `amount` | float | — | 成交额 |
| `scale` | float | — | 规模 |

- **唯一索引**: `{asset_code: 1, date: 1}`
- **写入模式**: upsert by (asset_code, date)；全覆盖模式先删后插
- **被消费方**: 回测引擎、监控系统、期权同步、Agent 查询

---

#### `fx_rates` — 汇率

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `date` | string | ✅ | `YYYY-MM-DD` |
| `EUR` | float | — | 欧元/人民币 |
| `USD` | float | — | 美元/人民币 |
| `HKD` | float | — | 港币/人民币 |
| `JPY` | float | — | 日元/人民币 |
| `CNH` | float | — | 离岸人民币（通常 1.0） |

- **唯一索引**: `{date: 1}`
- **被消费方**: 回测引擎、监控系统（夏普策略日经225等 JPY 计价资产）、期权同步、Agent 查询

**策略币种依赖**（缺失币种将导致 NAV 计算错误）：

| 策略 | 必需币种 | 关联资产 |
|------|---------|----------|
| sharpe_18 | USD, JPY, CNH | 标普500/纳指/原油/美债(USD), 日经225(JPY), 其余(CNH) |
| hybrid_12 | USD, EUR, HKD, CNH | 标普500(USD), 德国DAX(EUR), 恒生科技(HKD) |

---

#### `trade_dates` — 交易日历

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `date` | datetime | ✅ | 交易日（ISODate，历史设计） |

- **唯一索引**: `{date: 1}`
- **特殊说明**: 此集合 date 为 datetime（非字符串），查询时须用 datetime 对象
- **被消费方**: 导入跳过非交易日、监控、回测

---

#### `etf_discount_market_data` — ETF 折溢价数据

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `date` | string | ✅ | 日期 |
| `code` | string | ✅ | ETF 代码 |
| `close` | float | ✅ | 收盘价 |
| 其他折溢价指标 | float | — | 由选择器定义 |

- **被消费方**: ETFDiscountSelector、回测 DataFeed

---

### 域 2：策略配置（Strategy Configuration）

> 功能：用户创建/编辑策略模型，系统管理模板和参数版本。

#### `strategy_models` — 策略模型

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `name` | string | ✅ | 模型名称 |
| `template_code` | string | ✅ | FK → model_templates.code |
| `description` | string | — | 描述 |
| `asset_codes` | list[str] | ✅ | 关联资产列表 |
| `asset_names` | dict | — | {code: name} |
| `parameters` | dict | — | 分配器参数（schema 驱动） |
| `rebalance_frequency` | string | ✅ | 调仓频率 |
| `inception_date` | datetime | — | 建仓日 |
| `enable_momentum_selection` | bool | — | 启用选择器 |
| `selector_type` | string | — | 选择器类型 |
| `asset_selection_count` | int | — | 选择资产数量 |
| `min_history_days` | int | — | 最小历史数据要求 |
| `momentum_windows` | string | — | 动量窗口（兼容旧数据） |
| `mom_windows` / `posi_windows` / `smom_windows` | string | — | 各因子窗口 |
| `macd_windows` / `macd_long_window` | string/int | — | MACD 均线窗口 |
| `reversal_windows` / `sharp_windows` / `tie_break_window` | string/int | — | 其他选择器窗口 |
| `selector_parameters` | dict | — | 选择器参数聚合视图（与上述散列字段对称） |
| `controller_code` | string | — | 控制器代码 |
| `controller_parameters` | dict | — | 控制器参数 |
| `is_portfolio` | bool | — | 是否组合模型 |
| `sub_strategies` | list | — | 子策略（组合用） |
| `status` | string | — | 草稿/已发布/已归档 |
| `structured_params` | dict | — | 结构化参数快照（前端提交时写入） |
| `tags` | list[str] | — | 策略标签（用于检索和分类） |
| `latest_backtest_summary` | dict | — | 最近回测绩效快照 |
| `initial_nav` | float | — | 回测起始净值（默认1000） |
| `live_publish_enabled` | bool | — | 是否已实盘发布 |
| `live_published_at` | datetime | — | 实盘发布时间 |
| `live_effective_date` | datetime | — | 实盘生效日期 |
| `live_rebalance_mode` | string | — | auto / manual |
| `live_version` | int | — | 实盘发布版本号 |
| `live_snapshot` | dict | — | 实盘配置快照 |
| `live_snapshot_outdated` | bool | — | 实盘快照是否落后 |
| `created_by` | string | — | 创建人 |
| `created_at` / `updated_at` | datetime | 自动 | — |

- **被消费方**: 回测、监控、组合、参数版本

---

#### `model_templates` — 策略模板

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `code` | string | ✅ | 模板代码（唯一） |
| `name` | string | ✅ | 名称 |
| `description` | string | ✅ | 模板描述 |
| `source_code` | string | — | 策略源代码（Python 类定义） |
| `pdf_filename` | string | — | 策略 PDF 文档文件名 |
| `parameters` | list[ModelParameter] | ✅ | 参数定义列表（代码实现） |
| `param_schema` | list[dict] | — | 参数 JSON Schema（由 parameters 自动聚合，文档对齐字段） |
| `composition` | dict | — | 三层声明 |
| `category` | string | — | 分类 |
| `is_builtin` | bool | — | 内置标记（builtin_templates.py 注册） |
| `is_active` | bool | ✅ | 是否可用 |

- **写入来源**: 系统初始化 `builtin_templates.py` + 用户自定义
- **被消费方**: 前端表单渲染、回测引擎

---

#### `strategy_param_versions` — 参数版本快照

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `model_id` | string | ✅ | FK → strategy_models._id |
| `version` | int | ✅ | 自增版本号 |
| `allocator_params` | dict | — | 分配参数快照 |
| `selector_enabled` | bool | — | — |
| `selector_type` | string | — | — |
| `selector_params` | dict | — | — |
| `controller_code` | string | — | — |
| `controller_params` | dict | — | — |
| `template_code` | string | — | — |
| `asset_codes` | list[str] | — | — |
| `created_at` | datetime | 自动 | 快照时间 |

- **唯一索引**: `{model_id: 1, version: 1}`
- **写入时机**: 策略每次保存时自动生成
- **被消费方**: 前端版本对比、参数回滚

---

### 域 3：回测与监控（Execution & Monitoring）

> 功能：系统运行回测/监控后自动生成的结果数据。用户不直接写入。

#### `backtest_records` — 回测记录

- **主键**: model_id + created_at
- **写入时机**: 回测引擎完成后
- **内容**: 参数快照 + 绩效指标 + 净值序列 + 持仓记录
- **生命周期**: 永久保留

#### `monitor_states` — 监控状态（最新一份）

- **唯一索引**: `{monitor_id: 1}`（replace_one upsert）
- **写入时机**: 监控引擎每日运行
- **内容**: 当前净值、持仓、权重、日期
- **生命周期**: 只保留最新状态

#### `monitor_daily_reports` — 监控日报

- **写入时机**: 监控运行后自动生成
- **生命周期**: 按日累积，永久保留

#### `subjective_overrides` — 主观调仓指令

- **写入来源**: 前端手动下达
- **消费方**: 监控引擎下次运行时读取并执行

#### `sharpe_rebalance_weights` — 夏普策略权重缓存

- **写入时机**: 夏普策略监控计算后缓存
- **用途**: 避免重复计算

#### `strategy_live_change_logs` — 参数变更审计

- **写入时机**: 策略参数被修改时自动记录
- **用途**: 审计追踪

#### `strategy_live_monitoring_records` — 实盘跟踪记录

- **写入时机**: 实盘跟踪运行后
- **用途**: 实盘 vs 回测对比

#### `monitored_strategies` — 监控实例配置

- **写入来源**: 前端创建监控实例
- **用途**: 关联策略模型与监控参数

---

### 域 4：组合管理（Portfolio Management）

> 功能：组合创建、调仓执行、模拟交易。

#### `portfolios` — 投资组合

- **写入来源**: 前端创建组合 → 系统回测 → 写入
- **关键字段**: source_type (MANUAL/SINGLE_STRATEGY/PORTFOLIO_MODEL)、performance、sub_strategies

#### `rebalance_records` — 调仓记录

- **关联**: portfolio_id
- **写入时机**: 调仓执行后

#### `sim_trades` — 模拟交易

- **关联**: portfolio_id
- **写入时机**: 模拟交易引擎执行

#### `sim_daily_snapshots` — 模拟日快照

- **关联**: portfolio_id
- **写入时机**: 每日收盘后

---

### 域 5：期权估值（Derivatives）

> 功能：结构化产品定价、估值、风险管理。

#### `option_products` — 产品定义

- **业务主键**: product_id
- **内容**: 产品类型、标的、条款参数、状态

#### `option_market_data` — 市场数据

- **唯一索引**: `{date: 1, underlying: 1}`
- **写入来源**: 手动导入 / 从 asset_prices 同步
- **内容**: spot、各期限 vol、各期限 rate

#### `option_vol_surfaces` — 波动率曲面

#### `option_valuations` — 估值快照（最新）

#### `option_valuation_history` — 估值历史（累积）

#### `option_lifecycle_events` — 生命周期事件

- **内容**: 敲入/敲出/到期/赎回等事件记录

#### `option_risk_reports` — 风险报告（Greeks）

#### `option_accounting_entries` — 会计分录

#### `option_accounting_config` — 会计配置

---

### 域 6：AI 助手（AI Assistant）

> 功能：AI Agent 的运行时数据存储。

#### `agent_conversations` — 会话

- **内容**: 会话元数据（标题、创建时间、状态）

#### `agent_messages` — 消息

- **关联**: conversation_id
- **内容**: 角色、内容、工具调用记录

#### `agent_plans` — 计划

- **内容**: Agent 生成的执行计划及状态

#### `agent_memories` — 记忆

- **内容**: Agent 长期记忆（用户偏好、项目知识）

#### `agent_tool_results` — 工具结果存储

- **写入时机**: 工具返回结果超过 4000 字符时独立存储
- **生命周期**: 30 天 TTL 自动过期
- **内容**: 完整工具结果（消息中保留压缩摘要，完整结果按需获取）

#### `subject_risk_records` — 主体风险记录

- **写入来源**: Agent `subject_risk_search` 工具（上游同步 + 本地缓存）
- **被消费方**: Agent 风险分析、报告生成
- **内容**: 主体名称、风险类型、信号内容、来源、时间

#### `subject_risk_import_batches` — 风险导入批次

- **写入来源**: Agent 批量同步上游数据时记录
- **内容**: 批次号、同步时间、条数、状态

---

### 域 7：研究与报告（Research & Reporting）

> 功能：AI 辅助研究知识管理和报告生成。

#### `research_knowledge` — 研究知识库

- **写入来源**: Agent 研究产出、手动录入
- **被消费方**: 报告生成时检索

#### `reports` — 研究报告

- **写入来源**: Agent/用户生成
- **内容**: 标题、内容、关联数据

#### `analysis_templates` — 分析模板

- **内容**: 预定义的分析框架模板

---

### 域 8：系统基础设施（Infrastructure）

> 功能：系统运行支撑，非业务数据。

#### `_collection_registry` — 集合元数据

- **用途**: AI Agent 语义查询的元数据支撑
- **前缀 `_`**: 标识为系统内部集合

#### `_query_audit_log` — 查询审计

- **用途**: 记录 Agent 数据查询操作，用于安全审计

#### `_import_audit_log` — 导入审计

- **用途**: 记录每次导入操作（操作人、时间、目标集合、统计、错误），详见 `DATA_IMPORT_SPEC.md` Layer 4
- **生命周期**: rolling，保留 180 天
- **索引**: `{target_collection: 1, created_at: -1}`

#### `scheduler_state` — 调度器状态

- **用途**: 定时任务执行状态持久化

#### `financial_products` — 理财产品

- **用途**: 产品管理（独立于期权产品）
- **唯一索引**: `{product_code: 1}`

#### `investment_managers` — 投资经理

- **写入来源**: 前端创建/管理
- **用途**: 投资经理信息维护
- **唯一索引**: `{manager_code: 1}`

#### `_data_asset_registry` — 数据资产注册

> 实际集合名: `_data_asset_registry`（非 `api_data_assets`，以代码为准）

- **用途**: 登记系统对外暴露的数据资产（API 可查询的数据源）
- **写入来源**: `ApiDataAssetService`（手动注册/自动发现）
- **内容**: 数据源名称、集合名、描述、状态、访问统计

#### `lineage_nodes` — 血缘节点

- **写入来源**: `LineageService`（被 quality_engine 调用）
- **用途**: 数据血缘图谱的节点（集合、API、工具等实体）

#### `lineage_edges` — 血缘边

- **写入来源**: `LineageService`
- **用途**: 数据血缘图谱的边（DATA_FLOW / TRANSFORM / REFERENCE / DERIVE）

---

## 三、导入链路标准

> 完整的导入子系统规范见 `DATA_IMPORT_SPEC.md`（五层架构：映射层、协议层、流程层、审计层、前端层）。
> 本节仅定义核心链路原则。

### 3.1 标准流程（任何导入功能必须遵循）

```
Excel/CSV 文件
    │
    ▼
① 解析文件（pandas.read_excel）
    │
    ▼
② 引用 field_mappings.py 映射列名 → 标准字段名
    │
    ▼
③ Pydantic Schema 校验（类型、必填、值域）
    │
    ▼
④ 日期归一化 → "YYYY-MM-DD" 字符串
    │
    ▼
⑤ 业务校验（资产代码是否存在、数据合理性）
    │
    ▼
⑥ 写入 MongoDB（upsert by 业务主键）
    │
    ▼
⑦ 写入审计日志（import_audit_log）
    │
    ▼
⑧ 返回 ImportResponse（统一格式）
```

### 3.2 幂等性设计

| 集合 | 幂等键 | 写入方式 |
|------|--------|---------|
| `assets` | `code` | updateOne upsert |
| `asset_prices` | `asset_code + date` | 按日 upsert 或全覆盖 |
| `fx_rates` | `date` | replace / incremental |
| `trade_dates` | `date` | 存在则跳过 |
| `option_market_data` | `date + underlying` | upsert |

### 3.3 字段映射（唯一来源）

所有导入路径（前端 API、Agent Tool、脚本）必须引用同一份映射（详见 `DATA_IMPORT_SPEC.md` Layer 1）。

**映射文件位置**：`app/schemas/field_mappings.py`

**核心映射表**：
- `PRICE_COLUMN_MAPPING` — 行情字段（日期、开盘价、收盘价等）
- `ASSET_COLUMN_MAPPING` — 资产主数据（资产代码、资产名称、资产类型等）
- `TRADE_DATES_COLUMN_MAPPING` — 交易日历（交易日、日期等）

**资产代码映射**（研究员数据列名 → 库内 asset_code）：
- `app/monitor/config.py` 中 `SHARPE_NAME_TO_CODE`（18 类资产）
- `app/monitor/config.py` 中 `ASSET_NAME_TO_CODE`（12 类资产）

> **强制规则**：导入脚本禁止自行定义资产代码映射，必须引用 config 中的标准常量。
> 完整映射表见 `DATA_IMPORT_SPEC.md` §5.2。

**强制规则**：禁止在各导入文件中硬编码列名映射，必须引用上述常量。

---

## 四、跨集合引用关系

```
assets.code ─────────────┐
                         ├──→ asset_prices.asset_code
                         ├──→ strategy_models.asset_codes[]
                         ├──→ portfolios（间接）
                         └──→ option_market_data.underlying（语义）

strategy_models._id ─────┐
                         ├──→ strategy_param_versions.model_id
                         ├──→ backtest_records.model_id
                         ├──→ monitor_states（通过 tracker）
                         ├──→ portfolios.model_id
                         └──→ strategy_live_change_logs.model_id

model_templates.code ────→ strategy_models.template_code

portfolios._id ──────────┐
                         ├──→ rebalance_records.portfolio_id
                         ├──→ sim_trades.portfolio_id
                         └──→ sim_daily_snapshots.portfolio_id

option_products.product_id ──→ option_valuations / lifecycle_events / risk_reports

agent_conversations._id ────→ agent_messages.conversation_id / agent_tool_results.message_id

lineage_nodes.node_id ────→ lineage_edges.{source_id, target_id}
```

---

## 五、现状审计（Current State Audit）

> 最后审计时间：2026-07-23。全量代码→数据库→文档→Models 四方对齐完成。
> DB 实际集合: **42 个**；文档设计集合: **44 个**（含 2 个懒创建尚未触发）。

### 5.1 废弃集合清理记录（已完成 ✅）

2026-07-21 已清理 13 个无代码引用的废弃集合（约 8,545 条孤儿文档）：

| 集合 | 原文档数 | 处置 |
|------|--------|------|
| `option_contracts` | 1,266 | 已删除（备份于 exports/） |
| `option_iv_data` | 1,210 | 已删除 |
| `option_pricings` | 1 | 已删除 |
| `options` | 1 | 已删除 |
| `credit_history` | 23 | 已删除 |
| `credit_models` | 2 | 已删除 |
| `credit_subjects` | 12 | 已删除 |
| `research_insights` | 0 | 已删除 |
| `structured_products` | 0 | 已删除 |
| `data_asset_catalog` | 25 | 已删除 |
| `report_templates` | 5 | 已删除 |
| `etf_discount_gc001` | 800 | 已删除 |
| `etf_discount_tech` | 4,000 | 已删除 |

### 5.2 设计存在但 DB 中尚未创建的（2 个）

| 集合 | 原因 |
|------|------|
| `sim_trades` | 模拟交易未执行 |
| `sim_daily_snapshots` | 同上 |
| `option_lifecycle_events` | 无产品触发事件 |
| `_import_audit_log` | 导入审计日志（DATA_IMPORT_SPEC.md 新增） |

这些集合代码已就绪，首次使用时 MongoDB 会自动创建，无需干预。

### 5.3 对齐状态（2026-07-23 审计后）

```
设计集合:   44 个（代码审计全量对齐后）
DB 实际:    42 个（含 2 个懒创建尚未触发）
废弃集合:   0 个（已全部清理）
差距:       2 个懒创建集合（sim_trades、sim_daily_snapshots）

本次新增模型定义:
- trade_calendar.py (TradeDate)
- etf_discount.py (EtfDiscountMarketData)
- agent_conversation.py (AgentConversation, AgentMessage, AgentToolResult)
- agent_memory.py (AgentMemory)
- monitor.py + SharpeRebalanceWeight
- strategy_model.py + StrategyLiveChangeLog + StrategyLiveMonitoringRecord
- option_product.py + OptionValuationHistory
- report_model.py + AnalysisTemplate
- collection_registry.py (CollectionRegistryEntry)
- scheduler.py (SchedulerState)
```

---

## 六、技术债务与修复优先级

| # | 问题 | 影响 | 修复方案 | 优先级 |
|---|------|------|---------|:------:|
| 1 | ~~`data_provider.py` 用 datetime 查询 `asset_prices.date`（字符串字段）~~ | ~~监控可能查不到数据~~ | ✅ 已改为字符串比较（2026-07-24） | ~~P0~~ |
| 2 | ~~字段映射在 api/asset.py、schemas/asset.py、data_import_tool.py 三处重复~~ | ~~改一漏一~~ | ✅ 已抽取到 `field_mappings.py` 统一引用（2026-07-24） | ~~P1~~ |
| 3 | ~~集合名硬编码在各 Service（`self.db['xxx']`）~~ | ~~重命名时全局搜索~~ | ✅ 已抽取到 `collections.py` 常量（2026-07-24） | ~~P1~~ |
| 4 | ~~AssetType 枚举混用基础类型和前端分类~~ | ~~筛选逻辑混乱~~ | ✅ 已分离为 InstrumentType/AssetClass/SecurityType 三维度正交设计（2026-07） | ~~P2~~ |
| 5 | `trade_dates.date` 是 datetime 非字符串 | 与其他集合不一致 | 保持现状，查询层统一兼容 | P2 |
| 6 | ~~13 个废弃集合占用空间~~ | ~~混淆、备份膨胀~~ | ✅ 已于 2026-07-21 清理 | ~~P2~~ |
| 7 | ~~`fx_rates` 模型无 JPY 但 data_provider 运行时补~~ | ~~模型与实际不一致~~ | ✅ 已补全 JPY（Model/API/前端/文档全链路） | ~~P3~~ |
| 8 | ~~`app/models/` 与文档未对齐~~ | ~~13 个集合无模型定义~~ | ✅ 2026-07-23 全量对齐：补充 10 个缺失模型、修复字段不一致、文档更新 | ~~P0~~ |
| 9 | ~~ImportResponse 响应格式不统一（共4种）~~ | ~~前端解析困难~~ | ✅ 已创建统一 `import_protocol.py`（2026-07-24） | ~~P1~~ |
| 10 | ~~缺失 `_import_audit_log` 审计日志~~ | ~~导入操作不可追溯~~ | ✅ 已实现 `import_audit_service.py`（2026-07-24） | ~~P1~~ |

---

## 七、DataHub 模块边界

以下属于 DataHub 数据中台（试验性），**不在本架构管辖范围**：

- `dwd_*` 系列（82+ 张表，9 域，大写 SNAKE_CASE 命名）
- `_collection_registry` 中注册的 DataHub 域元数据

> 注：`subject_risk_*` 和 `_data_asset_registry` 虽最初由 DataHub 引入，但已被主业务 Agent 系统深度使用，
> 现归入主业务设计（域 6 AI 助手 / 域 8 基础设施）。

**与主业务的唯一接口**: `dwd_ast_info.AST_CD` 语义等价于 `assets.code`。
如需打通须通过显式映射服务，禁止直接跨域查询。

---

## 八、枚举值定义（Enum Reference）

> 所有枚举字段的权威定义。Schema 表中 `enum` 类型的字段，其合法值必须从此表查找。

### 8.1 InstrumentType（工具形态）

**集合**: `assets` | **字段**: `instrument_type` | **模型**: `app.models.asset.InstrumentType`

> 对标 Bloomberg Instrument / FpML productType。本维度**驱动 TR 计算分支**，是资产的核心业务属性。

| 值 | 含义 | TR 公式 | 条件参数 |
|---|---|---|---|
| `指数型` | 指数/无特殊处理标的 | 收盘价累积（`tr.py` §2.1） | — |
| `现货型` | 有上市切换的标的（ETF/LOF等） | 上市前替代、上市后切换（`tr.py` §2.4） | `substitute_code` + `switch_date` |
| `期货型` | 需主力合约展期 | 加权展期收益率（`tr.py` §3.2） | `rollover_days/threshold/window_p/window_q` |

> **命名规范**：值统一使用 `XX型`（形态表达），不是 `XX类`（类别表达）。形态决定行为，类别属于 `asset_class` 维度。

### 8.2 AssetClass（资产大类）

**集合**: `assets` | **字段**: `asset_class` | **模型**: `app.models.asset.AssetClass`

> 对标 Wind 资产大类 / Bloomberg Asset Class。用于过滤/分组/风控/Agent 查询。

| 值 | 含义 | 涵盖资产举例 |
|---|---|---|
| `权益` | 权益类资产 | 股票、ETF、股票指数、股指期货 |
| `固收` | 固定收益类 | 债券、债券基金、债券指数、国债期货 |
| `商品` | 大宗商品 | 商品期货、商品 ETF、商品指数 |
| `货币` | 现金及等价物 | 货币基金、存款、回购 |
| `另类` | 另类投资 | 数字货币、REITs、私募 |

### 8.3 SecurityType（证券细分，可选）

**集合**: `assets` | **字段**: `security_type` | **模型**: `app.models.asset.SecurityType`

> 对标 Bloomberg Security Type / FactSet Sec Type。可选的细粒度标签，用于精确筛选。

| 值 | 含义 | 典型搭配（asset_class + instrument_type） |
|---|---|---|
| `股票` | 个股 | 权益 + 现货型 |
| `指数` | 价格指数/全收益指数 | 权益/固收/商品 + 指数型 |
| `ETF` | 场内 ETF | 权益/固收/商品 + 现货型 |
| `LOF` | LOF 基金 | 权益 + 现货型 |
| `基金` | 场外基金 | 权益/固收 + 现货型 |
| `债券` | 债券 | 固收 + 现货型 |
| `期货` | 期货合约 | 权益/固收/商品 + 期货型 |
| `数字货币` | 加密货币 | 另类 + 指数型 |
| `存款` | 存款/回购 | 货币 + 指数型 |

### 8.4 RebalanceFrequency（调仓频率）

**集合**: `strategy_models` | **字段**: `rebalance_frequency` | **模型**: `app.models.strategy_model.RebalanceFrequency`

| 值 | 含义 |
|---|---|
| `日` | 每日调仓 |
| `周` | 每周调仓 |
| `月` | 每月调仓 |
| `季` | 每季调仓 |
| `年` | 每年调仓 |
| `自定义` | 自定义频率 |

### 8.5 ModelStatus（策略模型状态）

**集合**: `strategy_models` | **字段**: `status` | **模型**: `app.models.strategy_model.ModelStatus`

| 值 | 含义 |
|---|---|
| `草稿` | 未发布，可编辑 |
| `已发布` | 已发布，可用于回测/监控 |
| `已归档` | 已归档，只读 |

### 8.6 OptionProductType（期权产品类型）

**集合**: `option_products` | **字段**: `type` | **模型**: `app.models.option_product.OptionProductType`

| 值 | 含义 |
|---|---|
| `fixed` | 固定收益 |
| `binary` | 二元结构 |
| `spread` | 价差结构 |
| `sharkfin` | 鲨鱼鳍 |
| `snowball` | 雪球 |
| `phoenix` | 凤凰 |
| `double_barrier` | 双鲨 |
| `asian` | 亚式期权 |
| `rainbow` | 彩虹期权 |
| `range_accrual` | 区间累积 |
| `callable_fixed` | 可赎回固收 |
| `digital_range` | 数字区间 |
| `american_option` | 美式期权（二叉树） |
| `fd_option` | 有限差分期权（PDE） |
| `local_vol_option` | 局部波动率期权（Dupire） |

### 8.7 OptionProductStatus（期权产品状态）

**集合**: `option_products` | **字段**: `status` | **模型**: `app.models.option_product.OptionProductStatus`

| 值 | 含义 |
|---|---|
| `active` | 存续中 |
| `pending` | 待生效 |
| `knocked_out` | 已敲出 |
| `knocked_in` | 已敲入 |
| `matured` | 已到期 |

### 8.8 ProductType（理财产品类型）

**集合**: `financial_products` | **字段**: `product_type` | **模型**: `app.models.financial_product.ProductType`

| 值 | 含义 |
|---|---|
| `固收类` | 固定收益类 |
| `固收+` | 固收增强 |
| `混合类` | 混合型 |
| `权益类` | 权益类 |
| `商品类` | 商品类 |
| `现金管理类` | 现金管理类 |

### 8.9 RiskLevel（风险等级）

**集合**: `financial_products` | **字段**: `risk_level` | **模型**: `app.models.financial_product.RiskLevel`

| 值 | 含义 |
|---|---|
| `R1` | 低风险 |
| `R2` | 中低风险 |
| `R3` | 中风险 |
| `R4` | 中高风险 |
| `R5` | 高风险 |

### 8.10 ProductStatus（理财产品状态）

**集合**: `financial_products` | **字段**: `status` | **模型**: `app.models.financial_product.ProductStatus`

| 值 | 含义 |
|---|---|
| `草稿` | 草稿状态 |
| `已验证` | 已验证 |
| `已审批` | 已审批 |
| `已发行` | 已发行 |
| `已到期` | 已到期 |
| `已归档` | 已归档 |

### 8.11 OverrideStatus（主观调仓状态）

**集合**: `subjective_overrides` | **字段**: `status` | **模型**: `app.models.monitor.OverrideStatus`

| 值 | 含义 |
|---|---|
| `pending` | 待执行 |
| `executed` | 已执行 |
| `cancelled` | 已取消 |
