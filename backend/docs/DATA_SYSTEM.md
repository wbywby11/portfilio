# 数据体系总览

> **定位**：系统数据层的唯一文档。现状、架构、治理、导入通道、待落库清单均以本文为准，后续只更新本文。
> **已并入本文**：`DATA_ARCHITECTURE.md`、`DATA_GOVERNANCE.md`、`DATA_IMPORT_SPEC.md`、`DATA_INVENTORY_STRATEGY_ONBOARD.md`（四份停止更新，保留作历史）。
> **现状口径**：2026-10-31 对库 `asset_allocation` 实测，采集工具 `scripts/audit_db_inventory.py`（只读，可复跑）。数据变更后复跑并按第一节更新。
> **Schema 口径**：字段定义以 `app/models/` 的 Pydantic 模型为唯一实现；本文只记现状、约束、职责，不复制字段清单。

---

## 一、现状快照（2026-10-31 实测）

### 1.1 规模

| 项 | 实测值 |
|---|---|
| 集合数 | 33（含 GridFS 的 `template_pdfs.files` / `template_pdfs.chunks`） |
| 行情类文档 | `asset_prices` 440,995 条，覆盖 499 只资产 |
| 主数据 | `assets` 518 条 |
| 因子截面 | `factor_panel` 2,084 条，仅 1 个数据集 |
| 日历 / 汇率 | `trade_dates` 4,344 条 / `fx_rates` 4,997 条 |
| 业务数据 | 模型 24、模板 25、回测 40、监控实例 11、组合 5 |

### 1.2 集合清单

| 集合 | 条数 | 域 | 职责 | 写入方 |
|---|---:|---|---|---|
| `assets` | 518 | 市场行情 | 资产主数据 | asset_service（前端/脚本） |
| `asset_prices` | 440,995 | 市场行情 | 日频收盘价 | asset_service（前端/Agent/脚本） |
| `fx_rates` | 4,997 | 市场行情 | 汇率（USD/JPY/CNH 列） | fx_service（前端导入） |
| `trade_dates` | 4,344 | 市场行情 | 系统交易日历 | trade_calendar_service |
| `trading_calendars` | 1 | 市场行情 | GMSI2 原型日历备份（代码 0 引用） | 原型脚本 |
| `factor_panel` | 2,084 | 市场行情 | 因子截面，按 `dataset` 分区 | factor_panel_service |
| `macro_series` | 0 | 市场行情 | 宏观与估值序列（指数PE/PB/股息率、债券收益率、信用利差、ERP分量），主键 `(code, date)` | macro_series_service（前端导入） |
| `strategy_models` | 24 | 策略配置 | 策略模型与实盘快照 | strategy_model_service |
| `model_templates` | 25 | 策略配置 | 模板、参数、源码 | template_init_service |
| `strategy_param_versions` | 49 | 策略配置 | 参数版本快照 | strategy_model_service |
| `backtest_records` | 40 | 回测监控 | 回测参数与绩效 | backtest_engine |
| `monitor_states` | 29 | 回测监控 | 监控最新状态 | monitor_service |
| `monitor_daily_reports` | 6,689 | 回测监控 | 监控日报 | monitor_service |
| `monitor_operations` | 4,617 | 回测监控 | 监控操作日志 | monitor_service |
| `monitor_performance_cache` | 26 | 回测监控 | 绩效缓存 | monitor_service |
| `monitored_strategies` | 11 | 回测监控 | 监控实例配置 | 前端创建 |
| `sharpe_rebalance_weights` | 150 | 回测监控 | 夏普权重缓存 | monitor_service |
| `strategy_live_change_logs` | 46 | 回测监控 | 参数变更审计 | strategy_model_service |
| `portfolios` | 5 | 组合管理 | 投资组合 | portfolio_service |
| `rebalance_records` | 1 | 组合管理 | 调仓记录 | portfolio_service |
| `subject_risk_records` | 0 | 主体风险 | 主体风险记录 | `/subject-risk/import` |
| `subject_risk_import_batches` | 0 | 主体风险 | 导入批次 | 同上 |
| `agent_conversations` | 7 | AI 助手 | 会话 | conversation_store |
| `agent_messages` | 45 | AI 助手 | 消息 | conversation_store |
| `agent_knowledge` | 10 | AI 助手 | 知识条目 | agent |
| `agent_memories` | 3 | AI 助手 | 记忆 | memory_store |
| `agent_confirmations` | 13 | AI 助手 | 待确认操作 | agent |
| `agent_write_logs` | 26 | AI 助手 | 写操作日志 | agent |
| `agent_tool_results` | 0 | AI 助手 | 工具结果 | agent |
| `reports` | 2 | 研究 | 研究报告 | report_service |
| `template_pdfs.files` | 3 | 研究 | 模板 PDF（GridFS） | template_service |
| `template_pdfs.chunks` | 19 | 研究 | 同上分片 | template_service |
| `scheduler_state` | 1 | 基础设施 | 调度器状态 | scheduler_service |
| `_import_audit_log` | 7 | 基础设施 | 导入审计 | ImportAuditService |

模型覆盖：`app/models/` 下 18 个模型文件覆盖 23 个集合。无 Pydantic 模型、直接以 dict 读写的 10 个：`strategy_live_change_logs`、`monitor_performance_cache`、`_import_audit_log`、`agent_knowledge`、`agent_confirmations`、`agent_write_logs`、`agent_tool_results`、`scheduler_state`、`trading_calendars`、`template_pdfs.*`（GridFS 元数据）。

### 1.3 `assets` 构成

| 维度 | 分布 |
|---|---|
| `asset_class` | 固收 408 / 商品 67 / 权益 42 / 货币 1 |
| `instrument_type` | 指数型 459 / 期货型 56 / 现货型 3 |
| `security_type` | 债券 394 / 期货 51 / 指数 35 / ETF 29 / 未填 7 / 股票 1 / 基金 1 |
| `is_active` | 全部 true |

权益 42 只中，境内宽基与 ETF 占多数（000300.SH、510300.SH、510500.SH、512100.SH、159915.SZ 等），另含 SPX、NDX、N225、GDAXI、HSTECH 等海外指数。**无个股**。

### 1.4 `asset_prices` 覆盖

| 项 | 实测 |
|---|---|
| 总条数 | 440,995 |
| 有行情资产 | 499 / 518 |
| 日期范围 | 2005-01-03 ~ 2026-10-16 |
| 非空字段 | `close` 440,995 条；`open`/`high`/`low`/`volume`/`amount`/`scale` 均为 0 条 |
| 价格基准 | 模型另有 `price_basis`（close=收盘价 / settle=结算价），实际 0 条非空，缺省按 close 处理 |
| 权益 | 42 只中 32 只有行情，平均 3,209 条，最多 5,647 |
| 固收 | 408 只中 403 只有行情，平均 388 条，最少 8 条 |
| 商品 | 67 只中 63 只有行情，平均 2,855 条 |
| 货币 | 1 只，2,095 条 |

按最后交易日分布（日期降序前 8 档，合计 213 只；其余 286 只最后日期早于 2026-03-31）：

| 最后日期 | 资产 | 条数 |
|---|---:|---:|
| 2026-10-16 | 60 | 10,147 |
| 2026-09-30 | 19 | 6,228 |
| 2026-08-25 | 18 | 95,306 |
| 2026-07-31 | 21 | 42,402 |
| 2026-07-27 | 22 | 80,524 |
| 2026-06-30 | 17 | 4,589 |
| 2026-06-10 | 51 | 128,923 |
| 2026-03-31 | 5 | 1,143 |

有主数据但无行情的 19 只：

```
000015.SH  000510.SH  000688.SH  000852.SH  000905.SH  399006.SZ  600905.SH
930839.CSI 932315.CSI 980081.CNI 980092.CNI Au9999.SGE CBC00702.CS DZ
H00101.SH  H01077.SH  H01098.SH  H11014.CSI  h30198.CSI
```

其中 000852.SH、000905.SH、Au9999.SGE 已在库内有主数据但无行情，补齐前无法参与回测。孤儿行情（有行情无主数据）为 0 只。

### 1.5 `factor_panel`

| dataset | 条数 | 期数 | code 数 | 期日范围 |
|---|---:|---:|---:|---|
| `bond_phoenix50` | 2,084 | 28 | 830 | 2019-12-31 ~ 2026-09-30 |

代码侧已登记但库内尚无一行的数据集：`equity_quality_growth`（A 股质量成长季度截面）。业务主键 `(dataset, as_of_date, code)`，必填 `as_of_date` / `code` / `industry`。

### 1.6 日历与汇率

| 项 | 实测 |
|---|---|
| `trade_dates` | 4,344 条，2006-11-01 ~ **2026-08-26**，`date` 为 datetime（与行情 string 不同型） |
| 行情最新日 | 2026-10-16 |
| 落后 | **51 个自然日**，2026-08-26 之后的行情无日历可对齐 |
| `trading_calendars` | 1 条（`gmsi2_proto`，4,290 个日期，2006-11-01 ~ 2026-06-05），`app/` 下 0 引用 |
| `fx_rates` | 4,997 条，最新 2026-08-25，`date` 为 string，仅 USD / JPY / CNH 三列 |
| 汇率落后 | **52 个自然日**，8/26 之后外币资产无折算报价 |

### 1.7 索引

实测 16 个集合有业务索引，17 个仅 `_id_`。

**唯一索引齐全（4 个）**：`assets`(code)、`asset_prices`(asset_code, date)、`factor_panel`(dataset, as_of_date, code)、`trade_dates`(date)。

**有非唯一业务索引**：`model_templates`、`monitor_operations`、`agent_confirmations`、`agent_conversations`、`agent_knowledge`、`agent_memories`、`agent_messages`、`agent_tool_results`、`subject_risk_records`、`subject_risk_import_batches`、`template_pdfs.*`。

**仅 `_id_`（17 个）**：

```
_import_audit_log  agent_write_logs  backtest_records  fx_rates
monitor_daily_reports  monitor_performance_cache  monitor_states
monitored_strategies  portfolios  rebalance_records  reports
scheduler_state  sharpe_rebalance_weights  strategy_live_change_logs
strategy_models  strategy_param_versions  trading_calendars
```

**与设计不符**：`monitor_states` 缺 `monitor_id` 唯一索引，`strategy_param_versions` 缺 `(model_id, version)` 唯一索引——旧文档声明已建，实测未建。`_import_audit_log` 未建文档要求的 `(target_collection, created_at)` / `(operator, created_at)`。

### 1.8 审计与注册表

`_import_audit_log` 实有 7 条，全部来自两类操作：

| 时间 | 目标集合 | 方式 | 来源 | 行数 |
|---|---|---|---|---:|
| 2026-07-28 | `assets` | upsert | script:seed_assets | 47 |
| 2026-07-28 | `asset_prices` | upsert | script:seed_prices | 87,026 |
| 2026-07-28 | `trade_dates` | upsert | script:seed_trade_dates | 2,312 |
| 2026-08-28 | `trade_dates` | replace | excel | 5,648 / 4,344（两轮） |

资产主数据、行情、汇率、因子截面的**前端导入未产生审计记录**，与 `DATA_IMPORT_SPEC` 声明的"审计层覆盖全部导入"不一致；代码侧现状是仅 `trade_calendar_service` 写入审计，因子截面已接入。

`_collection_registry` **集合在库中不存在**（`list_collection_names()` 未返回，不是空集合）。代码中只有常量 `COL_COLLECTION_REGISTRY` 与模型 `app/models/collection_registry.py`，无写库服务、无初始化脚本，字段清单与业务主键只存在于文档。

### 1.9 文档与库的差异（合并时必须记录的偏差）

**文档登记但库内不存在（18 个；另有 `_collection_registry` 见 1.8，合计 19 个）**：

```
option_products  option_market_data  option_vol_surfaces  option_valuations
option_valuation_history  option_lifecycle_events  option_risk_reports
option_accounting_entries  option_accounting_config
subjective_overrides  strategy_live_monitoring_records
research_knowledge  analysis_templates  financial_products
agent_plans  sim_trades  sim_daily_snapshots  etf_discount_market_data
```

期权域 9 个集合整域未落库，`sim_*`、`agent_plans`、`research_knowledge`、`analysis_templates`、`financial_products` 亦无。文档标注的"44 个设计集合"是设计目标，不是现状。

**库内有但四份文档未登记（12 个）**：

```
_import_audit_log  agent_confirmations  agent_knowledge  agent_tool_results
agent_write_logs  monitor_operations  monitor_performance_cache
subject_risk_records  subject_risk_import_batches
template_pdfs.files  template_pdfs.chunks  trading_calendars
```

**条数与文档量级不符**：

| 集合 | 文档量级 | 实测 |
|---|---|---|
| `asset_prices` | ~270K | 440,995 |
| `assets` | ~200 | 518 |
| `monitor_daily_reports` | ~3.5K | 6,689 |
| `backtest_records` | ~75 | 40 |
| `agent_conversations` | ~215 | 7 |
| `agent_messages` | ~624 | 45 |

结论：原文档的"文档量级"是维护者手填估算，不可作为容量依据。本文第一节为实测值，以后以此为准。

---

## 二、架构

### 2.1 五项原则

| 原则 | 说明 |
|---|---|
| 功能驱动 | 每个集合对应明确业务功能，无功能引用的集合不应存在 |
| 单一职责 | 一个集合只存一类数据，禁止万能文档 |
| 契约优先 | Schema 先定义后使用，写入方与读取方共享同一 Pydantic 模型 |
| 幂等写入 | 导入/生成可重复执行，结果一致 |
| 可追溯 | 系统生成的数据记录生成时间与触发来源 |

### 2.2 命名与日期

| 对象 | 规范 |
|---|---|
| 集合名 | 小写 snake_case 复数名词（`assets`、`monitor_states`） |
| 字段名 | 小写 snake_case |
| 业务唯一键 | 联合唯一索引，不依赖 `_id`；`asset_prices` 为 `(asset_code, date)`，`factor_panel` 为 `(dataset, as_of_date, code)` |
| 时间戳 | `created_at` / `updated_at`，ISODate |
| 内部集合 | `_` 前缀（`_collection_registry`、`_import_audit_log`） |

日期存储：

| 场景 | 类型 | 说明 |
|---|---|---|
| 业务日期（行情、汇率、期日） | string `"YYYY-MM-DD"` | 字符串比较；入库前归一化，兼容 YYYYMMDD / Excel 序列日 |
| `trade_dates.date` | datetime | 历史遗留，写入时转换；**与行情 string 查询不可混用** |
| `trading_calendars.dates` | list[string] | 原型遗留，单文档存全量日期 |

### 2.3 三维资产分类

| 维度 | 字段 | 职责 | 值域 |
|---|---|---|---|
| 工具形态 | `instrument_type` | 驱动计算分支（TR、展期参数） | 指数型 / 现货型 / 期货型 |
| 资产大类 | `asset_class` | 业务分组、过滤、风控 | 权益 / 固收 / 商品 / 货币 / 另类 |
| 证券细分 | `security_type` | 细粒度标签（可选） | 股票 / 指数 / ETF / LOF / 债券 / 基金 / 期货 / 数字货币 |

典型组合：`000300.SH`（指数型/权益/指数）、`510300.SH`（现货型/权益/ETF）、`IF.HOT`（期货型/权益/期货）、`CBA00101.CS`（指数型/固收/指数）、`518880.SH`（现货型/商品/ETF）。

旧字段 `asset_type`（10 个值混存）在 `app/schemas/asset.py` 标为已废弃，但仍是导入目标字段（`ASSET_COLUMN_MAPPING` 把“资产类型*”映射到 `asset_type`），`asset_service._infer_asset_type` 在导入时按名称/代码兜底推断并写入；库内 518 条均带该字段值。

### 2.4 集合选型决策

```
数据是「某资产/某主体 + 某日期 + 若干数值」吗？
├─ 是 → 复用现有集合
│   ├─ 价格类 → asset_prices
│   ├─ 汇率 → fx_rates
│   ├─ 日历 → trade_dates
│   └─ 截面因子 → factor_panel（新增 dataset，不新建集合）
└─ 否（多维/异构/带元数据/独立生命周期）→ 新集合，走 5 步登记
```

新集合 5 步（缺一即未完成）：

1. `app/config/collections.py` 加 `COL_XXX` 常量，禁止 Service 硬编码集合名
2. `_collection_registry` 登记字段清单、业务主键、索引、时效级别（当前集合不存在，先补服务实现与初始化）
3. `app/schemas/field_mappings.py` 加中文列名映射
4. 本文第四节入口清单加一行（API + 前端入口 + 目标集合）
5. 索引按访问模式建：等值在前、范围在后

### 2.5 域职责

| 域 | 集合 | 性质 |
|---|---|---|
| 市场行情 | `assets` / `asset_prices` / `fx_rates` / `trade_dates` / `trading_calendars` / `factor_panel` | 用户导入维护，只增不改语义 |
| 策略配置 | `strategy_models` / `model_templates` / `strategy_param_versions` | 前端写入，系统同步 |
| 回测监控 | `backtest_records` / `monitor_states` / `monitor_daily_reports` / `monitor_operations` / `monitor_performance_cache` / `monitored_strategies` / `sharpe_rebalance_weights` / `strategy_live_change_logs` | 引擎生成，用户不直接写 |
| 组合管理 | `portfolios` / `rebalance_records` | 前端触发，引擎生成 |
| 主体风险 | `subject_risk_records` / `subject_risk_import_batches` | 上游 API 导入 |
| AI 助手 | `agent_conversations` / `agent_messages` / `agent_knowledge` / `agent_memories` / `agent_confirmations` / `agent_write_logs` / `agent_tool_results` | Agent 自动写 |
| 研究 | `reports` / `template_pdfs.*` | 报告与 PDF |
| 基础设施 | `scheduler_state` / `_import_audit_log` / `_collection_registry` | 系统内部 |

---

## 三、治理

### 3.1 所有权

| 集合 | Producer | 主要 Consumer | Quality Owner |
|---|---|---|---|
| `assets` | asset_service | 回测、监控、策略、组合 | asset_service |
| `asset_prices` | asset_service | 回测、监控 | asset_service |
| `fx_rates` | fx_service | 监控 data_provider | fx_service |
| `trade_dates` | trade_calendar_service | 导入校验、回测、监控 | trade_calendar_service |
| `factor_panel` | factor_panel_service | 回测/监控面板注入 | factor_panel_service |
| `strategy_models` | strategy_model_service | 回测、监控、组合 | strategy_model_service |
| `model_templates` | template_init_service | 前端表单、回测 | template_init_service |
| `backtest_records` | backtest_engine | 前端展示 | backtest_engine |
| `monitor_states` | monitor_service | 前端面板 | monitor_service |
| `portfolios` | portfolio_service | 前端、模拟交易 | portfolio_service |

### 3.2 变更规则

```
1. Schema Owner 提出变更（增字段 / 改类型 / 删字段）
2. 通知所有 Consumer 评估影响
3. 新增字段：可直接加（向后兼容）
4. 修改/删除字段：所有 Consumer 确认兼容后执行
5. 更新本文第一节现状与集合职责
6. 执行变更 + 必要时数据迁移
```

### 3.3 血缘与影响

```
导入（Excel / Agent / 脚本 / 上游 API）
   │
   ├─ assets ──┐
   ├─ asset_prices ──┤
   ├─ fx_rates ──┼──→ 回测引擎 → backtest_records
   ├─ trade_dates ──┤        └→ strategy_models.latest_backtest_summary
   ├─ factor_panel ──┤
   └─ model_templates ──→ 监控引擎 → monitor_states / daily_reports / performance_cache
                              └→ portfolios → rebalance_records
```

| 数据缺失/错误 | 影响 |
|---|---|
| `assets` 缺某资产 | 该资产行情无法导入、相关策略无法回测 |
| `asset_prices` 某日缺失 | 回测偏差、监控 NAV 错误 |
| `asset_prices` 与源文件不一致 | 监控 NAV 与研究员结果静默不对齐 |
| `asset_prices` 尾部停更 | 缺口区间日收益为 0、波动率低估，逆波动率类权重虚高 |
| `fx_rates` 某日缺失 | 外币资产折算为 1.0（静默） |
| `trade_dates` 不全 | 导入不跳非交易日、监控日期对齐错误 |
| `factor_panel` dataset 选错 | 数据写入另一截面、因子键与参数对不上（静默） |
| `strategy_models` 参数错误 | 回测无意义、监控权重异常 |

### 3.4 三道质量关

| 关卡 | 时机 | 手段 | 责任方 |
|---|---|---|---|
| Gate 1 写入前 | 入库前 | Pydantic + 业务规则 + 数据契约 | Producer |
| Gate 1.5 导入后 | 落库后 | 源文件逐值比对（容差 1e-6）、币种完整性、覆盖率、前端可见性 | Producer |
| Gate 2 读取时 | 消费前 | 空值防御、类型兼容、异常跳过+日志 | Consumer |
| Gate 3 定期巡检 | 每日/每周 | 巡检脚本 | Quality Owner |

Gate 1 必过项：必填字段、类型正确、`close > 0`、业务主键唯一（或 upsert）、`asset_code` 存在于 `assets`、日期在 1990~今日+30 天、目标库从 settings 读取、运行前数据契约校验（`app/backtesting/data_contract.py`，回测构造 / 实盘发布 / 监控启动三处门禁）。

### 3.5 数据时效分级

| 级别 | 含义 | 数据 | 更新方式 | 超期判定 |
|---|---|---|---|---|
| S 静态 | 编制规则、主数据 | `assets`、分组定义 | 变更时导入一次 | 不判定 |
| L 低频 | 月/季更新 | 成分权重、费率、风险预算 | 前端 Excel | `stale_days > 45` 告警 |
| D 日频 | 每交易日更新 | `asset_prices`、`fx_rates`、`trade_dates` | 导入或 API 同步 | 落后 > 2 交易日告警 |
| E 事件 | 不定期 | 分红除权、停牌 | 事件导入 | 不判定 |

时间差以 `trade_dates` 计数，不用自然日估算。**当前 `trade_dates` 自身落后 51 个自然日**，D 级数据的超期判定暂时无法执行，先补日历。

---

## 四、导入通道

### 4.1 入口清单

| # | 数据 | API | 输入 | 前端入口 | 目标集合 | 审计 |
|---|---|---|---|---|:---:|
| 1 | 资产主数据 | `POST /assets/import/excel` | Excel | AssetList.vue | `assets` | 未接 |
| 2 | 单资产行情 JSON | `POST /assets/prices/import` | JSON | Agent/内部 | `asset_prices` | 未接 |
| 3 | 单资产行情 Excel | `POST /assets/prices/import/excel` | Excel | AssetQuote.vue | `asset_prices` | 未接 |
| 4 | 多资产宽表解析 | `POST /assets/prices/import/multi-asset/parse` | Excel | AssetQuote.vue | — | — |
| 5 | 多资产宽表导入 | `POST /assets/prices/import/multi-asset` | JSON | AssetQuote.vue | `assets` + `asset_prices` | 未接 |
| 6 | 汇率 | `POST /fx/import` | Excel | FxImport.vue | `fx_rates` | 未接 |
| 7 | 交易日历 | `POST /trade-dates/import` | Excel | TradeCalendarPanel.vue | `trade_dates` | 已接 |
| 8 | 波动率曲面 | `POST /options/vol-surface/import/excel` | Excel | optionPricing.js | `option_vol_surfaces`（集合不存在） | 未接 |
| 9 | 主体风险 | `POST /subject-risk/import` | JSON | Agent | `subject_risk_records` | 未接 |
| 10 | 因子截面 | `POST /factor-panel/import` | Excel | FactorPanelImport.vue | `factor_panel` | 已接 |

### 4.2 `factor_panel` 规则（唯一多产品共用集合）

- `dataset` 为 **Form 必填参数**，受 `field_mappings.FACTOR_DATASETS` 控制，清单外直接报错
- 业务主键 `(dataset, as_of_date, code)`；必填 `as_of_date` / `code` / `industry`
- **选错 dataset 不报错**，数据静默写入另一截面，因子键与策略参数对不上
- 配套端点 6 个：`POST /import`、`GET /datasets`、`GET /overview`、`GET /period/{dataset}/{as_of_date}`、`DELETE /period/{dataset}/{as_of_date}`（只删本数据集整期）、`GET /template/download?dataset=`
- 新增数据集只改 `field_mappings.py` 三处：`FACTOR_DATASETS`、`FACTOR_NAME_MAPPING_BY_DATASET`、`FACTOR_CATEGORICAL_KEYS_BY_DATASET`，不动 `collections.py`

### 4.3 八步链路

```
① 接收（≤50MB，.xlsx/.xls/.csv） → ② 解析 → ③ 列名映射（引用 field_mappings）
→ ④ 逐行类型校验（不因一行中止） → ⑤ 值域归一化（日期→YYYY-MM-DD）
→ ⑥ 业务校验（外键、日期范围） → ⑦ 幂等写入（BulkWrite ≤1000/批）
→ ⑧ 写审计 + 返回 ImportResponse
```

映射层唯一来源 `app/schemas/field_mappings.py`：`PRICE_COLUMN_MAPPING`（含"成交额→amount""成交量→volume""规模→scale"）、`ASSET_COLUMN_MAPPING`、`TRADE_DATES_COLUMN_MAPPING`。所有导入路径禁止硬编码列名。

### 4.4 前端交互

```
选文件 + 选模式（upsert 默认 / replace / incremental）→ 预览 dry-run → 执行 → 结果
```

数据集选择器仅当一个集合被多产品共用时出现（当前只有因子截面）。

### 4.5 一次性脚本边界

脚本只用于首次历史灌库：跑完出导入报告（新增/更新/跳过/失败+原因）→ 校验通过 → 删除。长期更新必须能在前端完成。已存在的历史脚本（`scripts/` 下 117 个文件）不属于日常通道。

---

## 五、待落库：三个原型

### 5.1 结论

| 原型 | 形态 | 落点 | 新集合 |
|---|---|---|---|
| 红利 GARP 专户 | standalone 一体化 | `app/standalone_strategies/` | 0 |
| FOF 目标波动 | standalone 一体化 | 同上 | 0 |
| 指数增强（实为固收+） | standalone 一体化，类内三段（ERP 分位→仓位、三信号→战术、8 因子→选基） | 同上 | 0 |

新增 `factor_panel` dataset 2 个：`index_valuation`（指数日频 PE/PB）、`index_enhance_stock`（成分股月末 PB + 高低分组收益差）。其余数据全部复用 `assets` / `asset_prices` / `trade_dates`。

### 5.2 共用资产池（按资产建一次，多策略引用）

**宽基、风格、红利（10 条）**

| 代码 | 名称 | 用途 |
|---|---|---|
| 000985.CSI | 中证全指 | sig1 成交额、sig3 成分域、GARP BM |
| H00852.SH | 中证 1000 全收益 | FOF 小盘 |
| H00918.CSI | 沪深 300 成长全收益 | FOF 成长、DAR |
| H00922.CSI | 中证红利全收益 | GARP BM、FOF 红利 |
| H00919.CSI | 沪深 300 价值全收益 | FOF 价值 |
| Au9999.SGE | 黄金现货 | FOF 黄金 |
| 885009.WI | 现金代理 | FOF 现金 |
| 512890.SH | 红利低波 ETF | GARP DLV |
| 931231CNY01 | 红利质量 | GARP YQ50 |
| 931579CNY01 | GARP 指数 | GARP 基准 |

**债券（6 条）**：CBA00621.CS（国债 1-3 年）、CBA00651.CS（国债 7-10 年）、CBA01921.CS（高等级信用 1-3 年）、CBA01931.CS（信用 3-5 年）、CBA00121.CS（中债总财富，指增基准）、992618（GARP 债券，后缀待确认）。

**申万一级行业（30 条，剔除 801230 综合）**：`asset_class=权益`，`asset_prices.close` 存行业指数。用于 FOF 时点行业、指增 sig2 集中度；DAR 控仓另需 801230 综合，合计 31 条。

### 5.3 现有数据缺口

| 策略 | 缺什么 | 落点 |
|---|---|---|
| GARP | 中证红利 PE-TTM 日频序列（`index_valuation`） | 新增 dataset |
| FOF | 30 个申万行业收盘、H00852/H00918/H00919/Au9999/885009 行情、high/low/volume/amount | `assets` + `asset_prices` |
| 指增 | sig1 需 000985 成交额、sig2 需 30 行业成交额、sig3 需月末全市场 PB（约 83 万行） | `asset_prices.amount` + `index_enhance_stock` |

当前 `amount` 全库 0 条非空，`high`/`low` 全空，30 个申万行业资产 0 条，上述三策略在补齐前无法运行。

---

## 六、缺口与待办

### P0（阻断运行）

1. **`trade_dates` 与 `fx_rates` 同步落后**：日历止于 2026-08-26（落后 51 天），汇率止于 2026-08-25（落后 52 天），行情已到 2026-10-16。两者补齐前，8/26 之后的回测与监控无排期轴、外币资产无折算汇率。
2. **19 只资产无行情**：含 000852.SH、000905.SH、Au9999.SGE。走 `POST /assets/prices/import/excel` 补。
3. **`asset_prices` 六字段全空**：`open`/`high`/`low`/`volume`/`amount`/`scale` 均为 0 条非空。FOF 时点行业、指增 sig1/sig2/sig3 全部依赖成交额，不补齐则三个原型中两个无法落地。
4. **`_collection_registry` 集合不存在**：治理注册表无实现、无初始化，新集合的字段/主键/索引无落库记录。

### P1（影响可用性）

5. **固收历史过短**：403 只有行情，平均 388 条，最少 8 条（2026-09-30~2026-10-16 的 8 个交易日），低于 `min_history_days=260` 门槛。
6. **权益池仅 42 只**（32 只有行情）：缺 FOF 的风格指数、指增的场内/场外基金池（名单在 `research/指数增强/数据映射表.xlsx`，未入库）。
7. **文档与库不一致**：18 个集合仅存在于设计文档（期权域 9 个、`sim_*`、`agent_plans` 等），12 个库内集合未登记。本文第一节已按实况修正，代码侧无需改动。
8. **索引缺失**：`fx_rates`、`backtest_records`、`monitor_states` 仅 `_id`；`_import_audit_log` 未建文档要求的两个索引。

### P2（数据卫生）

9. `assets` 中 7 条 `security_type` 未填，`DZ` 无交易所后缀，`992618` 后缀未确认。
10. `trading_calendars` 1 条原型日历（代码 0 引用，止于 2026-06-05），与 `trade_dates` 并存，待确认后清除或标注 deprecated。
11. 导入审计未覆盖资产、行情、汇率、因子截面四类通道；`_import_audit_log` 现有 7 条全部来自 seed 脚本与日历导入。

---

## 七、维护规则

1. **唯一文档**：数据层任何变更只更新本文件，不再更新已归档的四份。
2. **现状必须实测**：第一节的条数、覆盖、索引、日期类结论，须来自 `py -3 scripts/audit_db_inventory.py` 的输出，不填估算值。
3. **变更记录**：每次数据变更在下方登记，格式为「日期 / 变更内容 / 影响集合 / 复核人」。

| 日期 | 变更 | 影响集合 | 复核 |
|---|---|---|---|
| 2026-10-31 | 四份文档合并为本文；实测建库现状 | 全部 | — |

4. **新增数据三问**：能否复用现有集合？能否作为 `factor_panel` 新 dataset？若都要新建，是否完成 2.4 的 5 步？
5. **策略接入前**：先按第五节核对资产与字段是否齐备，缺项列入第六节待办，不带缺口进入编码。
