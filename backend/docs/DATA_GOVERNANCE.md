# 数据资产管理规范

> **已归档（2026-10-31）**：本文档已并入 `DATA_SYSTEM.md`，后续数据治理变更只更新该文档。本文保留作历史参考，不再修改。
>
> **原定位**：定义数据从"产生"到"消亡"全生命周期的治理规则。

---

## 一、管理目标

| 目标 | 衡量标准 |
|------|---------|
| **可发现** | 任何人 30 秒内能找到"某类数据存在哪、长什么样" |
| **可信赖** | 数据写入有校验、异常有告警、质量有量化指标 |
| **可追溯** | 任何一条数据能回答"从哪来、谁写的、什么时候写的" |
| **可清理** | 过期/废弃数据有明确的识别和清除机制 |
| **可变更** | Schema 变更有流程，不会"改一处崩全局" |

---

## 二、资产目录（Asset Catalog）

### 2.1 资产卡片标准

每个集合必须登记以下元信息（YAML 格式存于文档，不由代码生成）：

| 分组 | 字段 | 示例 |
|------|------|------|
| 基本信息 | collection_name / display_name / domain / status | `asset_prices` / 日频行情 / market_data / active |
| Schema | primary_key / date_field / date_type / schema_ref | `[asset_code, date]` / date / string / `AssetPrice` |
| 所有权 | producer / consumers / quality_owner | asset_service / [回测, 监控] / asset_service |
| 规模 | doc_count / daily_growth / avg_doc_size | 274K / ~500/天 / 120B |
| 生命周期 | lifecycle / retention / cleanup_trigger | permanent / null / manual |
| 质量规则 | field + rule + severity | `close > 0` (P0)、`asset_code exists in assets` (P1) |

### 2.2 全量资产目录

#### 域 1：市场行情（market_data）

| 集合 | 中文名 | 状态 | 文档量级 | 生命周期 | 质量责任方 |
|------|--------|:----:|---------|---------|-----------|
| `assets` | 资产主数据 | active | ~200 | permanent | asset_service |
| `asset_prices` | 日频行情 | active | ~270K | permanent | asset_service |
| `fx_rates` | 汇率 | active | ~5K | permanent | fx_service |
| `trade_dates` | 交易日历 | active | ~4K | permanent | trade_calendar_service |
| `factor_panel` | 因子截面面板（按 `dataset` 分区，多数据产品共用） | active | ~2K | permanent | factor_panel_service |

> `etf_discount_market_data`（ETF 折溢价）已于 2026-10-27 随 etf_discount 策略弃用下线：
> 选择器、专用 DataFeed、模型与集合常量均已从代码移除；库内该集合为 0 行，空集合保留不删。

#### 域 2：策略配置（strategy）

| 集合 | 中文名 | 状态 | 文档量级 | 生命周期 | 质量责任方 |
|------|--------|:----:|---------|---------|-----------|
| `strategy_models` | 策略模型 | active | ~30 | permanent | strategy_model_service |
| `model_templates` | 策略模板 | active | ~30 | permanent | template_init_service |
| `strategy_param_versions` | 参数版本 | active | ~50 | permanent(随模型) | strategy_model_service |

#### 域 3：回测与监控（execution）

| 集合 | 中文名 | 状态 | 文档量级 | 生命周期 | 质量责任方 |
|------|--------|:----:|---------|---------|-----------|
| `backtest_records` | 回测记录 | active | ~75 | permanent | backtest_engine |
| `monitor_states` | 监控状态 | active | ~6 | rolling(最新) | monitor_service |
| `monitor_daily_reports` | 监控日报 | active | ~3.5K | permanent | monitor_service |
| `subjective_overrides` | 主观调仓 | active | ~1 | ephemeral(消费后) | monitor_service |
| `sharpe_rebalance_weights` | 夏普权重缓存 | active | ~150 | rolling | monitor_service |
| `strategy_live_change_logs` | 变更审计 | active | ~12 | permanent | strategy_model_service |
| `strategy_live_monitoring_records` | 实盘跟踪 | active | 0 | permanent | monitor_service |

#### 域 4：组合管理（portfolio）

| 集合 | 中文名 | 状态 | 文档量级 | 生命周期 | 质量责任方 |
|------|--------|:----:|---------|---------|-----------|
| `portfolios` | 投资组合 | active | ~3 | permanent | portfolio_service |
| `rebalance_records` | 调仓记录 | active | 0 | permanent(随组合) | portfolio_service |
| `sim_trades` | 模拟交易 | active | 0 | permanent(随组合) | sim_trade_engine |
| `sim_daily_snapshots` | 模拟日快照 | active | 0 | permanent(随组合) | sim_trade_engine |

#### 域 5：期权估值（derivatives）

| 集合 | 中文名 | 状态 | 文档量级 | 生命周期 | 质量责任方 |
|------|--------|:----:|---------|---------|-----------|
| `option_products` | 产品定义 | active | ~12 | permanent | option_pricing_service |
| `option_market_data` | 市场数据 | active | ~280 | permanent | option_pricing_service |
| `option_vol_surfaces` | 波动率曲面 | active | ~20 | permanent | option_pricing_service |
| `option_valuations` | 估值快照 | active | ~2 | rolling(最新) | option_pricing_service |
| `option_valuation_history` | 估值历史 | active | ~24 | permanent | option_pricing_service |
| `option_lifecycle_events` | 生命周期事件 | active | 0 | permanent | option_pricing_service |
| `option_risk_reports` | 风险报告 | active | ~1 | permanent | option_pricing_service |
| `option_accounting_entries` | 会计分录 | active | ~12 | permanent | option_accounting_service |
| `option_accounting_config` | 会计配置 | active | ~1 | permanent | option_accounting_service |

#### 域 6：AI 助手（assistant）

| 集合 | 中文名 | 状态 | 文档量级 | 生命周期 | 质量责任方 |
|------|--------|:----:|---------|---------|-----------|
| `agent_conversations` | 会话 | active | ~215 | rolling(90天) | conversation_store |
| `agent_messages` | 消息 | active | ~624 | rolling(90天) | conversation_store |
| `agent_plans` | 计划 | active | ~49 | rolling(30天) | plan_manager |
| `agent_memories` | 记忆 | active | ~9 | permanent | memory_store |

#### 域 7：研究与报告（research）

| 集合 | 中文名 | 状态 | 文档量级 | 生命周期 | 质量责任方 |
|------|--------|:----:|---------|---------|-----------|
| `research_knowledge` | 研究知识库 | active | ~15 | permanent | report_service |
| `reports` | 研究报告 | active | ~1 | permanent | report_service |
| `analysis_templates` | 分析模板 | active | ~4 | permanent | template_service |

#### 域 8：系统基础（infrastructure）

| 集合 | 中文名 | 状态 | 文档量级 | 生命周期 | 质量责任方 |
|------|--------|:----:|---------|---------|-----------|
| `_collection_registry` | 集合元数据 | active | ~22 | auto-refresh | collection_registry |
| `_query_audit_log` | 查询审计 | active | ~428 | rolling(30天) | generic_query_engine |
| `scheduler_state` | 调度器状态 | active | ~2 | rolling(最新) | scheduler_service |
| `financial_products` | 理财产品 | active | ~25 | permanent | financial_product_service |

---

## 三、所有权矩阵（Ownership）

### 3.1 角色定义

| 角色 | 职责 |
|------|------|
| **Producer** | 创建/写入数据的模块。负责写入校验和格式正确性 |
| **Consumer** | 读取/使用数据的模块。有权提出数据质量需求 |
| **Quality Owner** | 数据质量第一责任人。负责巡检规则定义和异常处理 |
| **Schema Owner** | Schema 变更审批人。通常是 Producer 的负责人 |

### 3.2 变更规则

```
Schema 变更流程：
1. Schema Owner 提出变更（新增字段 / 修改类型 / 删除字段）
2. 通知所有 Consumer 评估影响
3. 新增字段：可直接加（向后兼容）
4. 修改/删除字段：必须所有 Consumer 确认兼容后执行
5. 更新 DATA_ARCHITECTURE.md + 本文档资产卡片
6. 执行变更 + 必要时数据迁移
```

### 3.3 所有权速查

| 集合 | Producer | 主要 Consumer | Quality Owner |
|------|----------|--------------|---------------|
| `assets` | asset_service (前端导入) | 回测、监控、策略、期权 | asset_service |
| `asset_prices` | asset_service (前端/Agent/脚本) | 回测、监控、期权 | asset_service |
| `fx_rates` | fx_service (前端导入) | 监控 data_provider | fx_service |
| `trade_dates` | trade_calendar_service | 导入校验、监控、回测 | trade_calendar_service |
| `factor_panel` | factor_panel_service (前端「因子截面数据」页) | 回测 DataFeed 面板注入、监控面板注入 | factor_panel_service |
| `strategy_models` | strategy_model_service (前端) | 回测、监控、组合 | strategy_model_service |
| `model_templates` | template_init_service (系统) | 前端表单、回测 | template_init_service |
| `backtest_records` | backtest_engine (系统) | 前端展示 | backtest_engine |
| `monitor_states` | monitor_service (系统) | 前端面板 | monitor_service |
| `portfolios` | portfolio_service (前端触发) | 前端、模拟交易 | portfolio_service |
| `option_products` | option_pricing_service (前端) | 估值、风控 | option_pricing_service |

---

## 四、数据血缘（Lineage）

### 4.1 数据生产 → 消费链路

```
用户 Excel 导入 / 前端操作 / 系统引擎 / 外部 API
          │
          ▼
  ┌─ 生产层（基础数据）─┐
  │ assets              │← 用户导入
  │ asset_prices        │← 用户/Agent/脚本
  │ fx_rates            │← 用户导入
  │ trade_dates         │← 用户导入
  │ strategy_models     │← 前端操作
  │ model_templates     │← 系统初始化
  │ option_products     │← 前端操作
  │ option_market_data  │← 导入/同步
  └──────────┬──────────┘
             │ 读取
             ▼
  ┌─ 消费/生产层（衍生数据）─────────────────────────────┐
  │ 回测引擎 → backtest_records                          │
  │ 监控引擎 → monitor_states / daily_reports / weights  │
  │ 组合引擎 → portfolios / rebalance_records / sim_*    │
  │ 期权引擎 → valuations / lifecycle / risk_reports     │
  │ 参数版本 → strategy_param_versions                   │
  └──────────────────────────────────────────────────────┘
```

### 4.2 影响分析表

> 当某份数据出问题时，快速判断影响范围：

| 如果这份数据缺失/错误 | 影响范围 |
|---------------------|--------|
| `assets` 某资产被删 | 该资产行情无法导入、相关策略无法回测 |
| `asset_prices` 某日缺失 | 回测结果偏差、监控净值计算错误 |
| `asset_prices` 数值与源文件不一致 | 监控 NAV 与研究员结果不对齐（静默错误） |
| `fx_rates` 某日缺失 | 监控中外币资产折算为 1.0（静默错误） |
| `fx_rates` 某币种整体缺失 | 该币种所有资产 NAV 计算错误（如缺 JPY 影响日经225） |
| `trade_dates` 不全 | 导入时非交易日未跳过、监控日期对齐错误 |
| `strategy_models` 参数错误 | 回测结果无意义、监控调仓权重异常 |
| `model_templates` 被禁用 | 前端策略类型下拉缺失 |
| `option_market_data` 缺失 | 估值失败、Greeks 无法计算 |

---

## 五、质量保障体系（Quality）

### 5.1 三道质量关

| 关卡 | 时机 | 手段 | 责任方 |
|------|------|------|--------|
| **Gate 1：写入前校验** | 数据进入 MongoDB 前 | Pydantic Schema + 业务规则 | Producer |
| **Gate 2：读取时防御** | Consumer 从 DB 读取后 | 空值防御、类型兼容、异常跳过+日志 | Consumer |
| **Gate 3：定期巡检** | 定时任务（每日/每周） | 自动化巡检脚本 | Quality Owner |

### 5.2 写入前校验标准（Gate 1）

所有导入/写入操作必须通过以下校验：

| 校验项 | 规则 | 失败处理 |
|--------|------|--------|
| 必填字段 | 按 Schema 定义 | 拒绝写入，返回错误 |
| 类型正确 | 数值字段不接受非数值字符串 | 拒绝或转换 |
| 值域合理 | close > 0, 权重 ∈ [0,1] | 拒绝，标记异常 |
| 唯一性 | 业务主键不冲突（或 upsert） | upsert 覆盖 |
| 引用完整性 | asset_code 存在于 assets | 警告（P1）或拒绝（P0） |
| 日期合法性 | 日期在合理范围内（1990~今天+1） | 拒绝 |
| **目标库正确** | 连接配置从 settings 读取，禁止硬编码 | 拒绝执行 |
| **资产代码唯一性** | `assets.code` 为业务主键，自由命名（无白名单校验，见 DATA_IMPORT_SPEC.md §5.2）；`asset_prices` 以 (asset_code, date) 唯一 | 重名资产 upsert 覆盖；同一 code 混存不同日历口径视为脏数据 |
| **策略数据契约** | 运行前由 `app/backtesting/data_contract.py` 校验（回测构造 / 实盘发布 / 监控启动三处门禁） | 拒绝运行，列出缺口与修复建议 |

### 5.3 导入后校验标准（Gate 1.5）

> **历史教训**：曾因导入后未校验，导致 JPY 汇率缺失、价格数据版本不同步、资产代码错误等问题
> 直到监控 NAV 偏差才被发现。导入后校验是强制步骤，不可省略。

每次基础数据导入（asset_prices / fx_rates / trade_dates）完成后，必须执行：

| # | 校验项 | 工具 | 判定标准 |
|---|--------|------|----------|
| 1 | 数据源对齐 | `scripts/_compare_excel_vs_db.py` | Excel 与 DB 数值完全一致（容差 ≤ 1e-6） |
| 2 | 币种完整性 | 查询 fx_rates 各币种非空计数 | 策略涉及币种均有数据 |
| 3 | 资产覆盖率 | 按 asset_code 统计条数 | 与源文件有效行数一致 |
| 4 | 前端可见性 | 前端查看导入结果 | 用户能正常看到新导入的数据 |

### 5.4 定期巡检规则（Gate 3）

#### 每日巡检

| 检查项 | 规则 | 严重级别 | 告警方式 |
|--------|------|:--------:|---------|
| 行情连续性 | 最近交易日所有活跃资产有行情 | P0 | 日志 + 前端提示 |
| 汇率完整性 | 最近交易日 fx_rates 有记录 | P1 | 日志 |
| 监控运行 | monitor_states.updated_at 在最近 2 天内 | P1 | 日志 |
| 数据量异常 | 单日新增文档数偏离 7 日均值 >3σ | P2 | 日志 |

#### 每周巡检

| 检查项 | 规则 | 严重级别 |
|--------|------|:--------:|
| 孤儿行情 | asset_prices.asset_code 不在 assets 中 | P1 |
| 孤儿策略 | strategy_models.template_code 不在 model_templates 中 | P1 |
| 重复文档 | asset_prices 中 (asset_code, date) 有重复 | P0 |
| 废弃集合 | DB 中存在但代码无引用的集合 | P2 |
| 索引健康 | 唯一索引是否缺失 | P1 |

#### 每月巡检

| 检查项 | 规则 | 严重级别 |
|--------|------|:--------:|
| 存储增长 | 各集合大小月增长率是否异常 | P3 |
| 过期数据 | rolling 类集合是否按策略清理 | P2 |
| Schema 漂移 | 实际文档字段是否与 Model 定义一致 | P1 |

### 5.5 质量度量指标

| 指标 | 定义 | 目标值 |
|------|------|--------|
| **完整性** | 最近 N 交易日有行情的资产占比 | ≥ 99% |
| **准确性** | 导入时无校验错误的记录占比 | ≥ 99.5% |
| **一致性** | 跨集合引用完整的记录占比 | ≥ 99% |
| **时效性** | 数据从产生到可查询的延迟 | ≤ 1 分钟（导入）/ ≤ 1 天（监控） |
| **唯一性** | 无重复文档的集合占比 | 100% |

---

## 六、生命周期管理（Lifecycle）

### 6.1 生命周期分类

| 类型 | 含义 | 适用集合 | 清理策略 |
|------|------|---------|---------|
| **permanent** | 永久保留 | assets, asset_prices, strategy_models, backtest_records | 用户手动删除 |
| **rolling** | 只保留最新 N 条/天 | monitor_states(1), _query_audit_log(30天), agent_messages(90天) | 自动定期清理 |
| **ephemeral** | 消费后即失效 | subjective_overrides(执行后) | 消费方标记/删除 |
| **cascading** | 跟随父实体 | param_versions(随模型), sim_trades(随组合) | 删除父实体时级联 |

### 6.2 清理规则

```python
# 定期清理任务（由 scheduler_service 调度）

CLEANUP_RULES = {
    # rolling 类：按时间窗口
    "_query_audit_log": {"retain_days": 30, "delete_field": "timestamp"},
    "agent_conversations": {"retain_days": 90, "delete_field": "created_at"},
    "agent_messages": {"retain_days": 90, "delete_field": "created_at"},
    "agent_plans": {"retain_days": 30, "delete_field": "created_at"},

    # rolling 类：只保留最新 N 条
    "monitor_states": {"keep_latest": 1, "group_by": "monitor_id"},
    "option_valuations": {"keep_latest": 1, "group_by": "product_id"},
    "scheduler_state": {"keep_latest": 1, "group_by": "job_id"},

    # cascading 类：父删子删（由 service 层 delete 方法保证）
    # strategy_param_versions → 删除 strategy_models 时级联
    # rebalance_records / sim_trades / sim_daily_snapshots → 删除 portfolios 时级联
}
```

### 6.3 归档策略

对于量大但访问频率低的数据，可考虑归档：

| 集合 | 归档条件 | 归档方式 |
|------|---------|---------|
| `monitor_daily_reports` | 超过 1 年 | 按月聚合摘要后删除明细 |
| `backtest_records` | 同一模型超过 50 条 | 保留最近 50 条 + 最优 5 条 |
| `agent_messages` | 超过 90 天 | 直接删除 |

---

## 七、变更管控（Change Control）

### 7.1 新增集合

```
1. 在 DATA_ARCHITECTURE.md 中定义 Schema
2. 在本文档中登记资产卡片（域、所有权、生命周期、质量规则）
3. 在 collections.py 中注册集合名常量
4. 创建 Pydantic Model（app/models/ 或 app/schemas/）
5. 编写 Service 层（含写入校验）
6. 如需导入：在 field_mappings.py 中添加列名映射
7. 配置巡检规则（如需要）
```

### 7.2 修改 Schema

```
1. 评估影响：列出所有 Consumer
2. 向后兼容变更（新增可选字段）：直接执行
3. 破坏性变更（改类型/删字段）：
   a. 通知所有 Consumer
   b. 编写数据迁移脚本
   c. 更新 Model + 文档
   d. 执行迁移
   e. 验证所有 Consumer 正常
```

### 7.3 废弃集合

```
1. 确认代码中无任何引用（grep 全项目）
2. 在本文档中标记 status: deprecated
3. 导出备份（mongodump 或 JSON 导出）
4. 从 DB 中删除
5. 更新本文档（移除或标记已删除）
```

---

## 八、治理工具

| 工具 | 位置 | 功能 |
|------|------|------|
| `collection_registry` | app/services/collection_registry.py | 启动时扫描集合、推断 Schema |
| `scheduler_service` | app/services/scheduler_service.py | 定时任务调度（巡检、清理） |
| 导入审计日志 | `_import_audit_log` 集合 | 记录每次导入操作（详见 DATA_IMPORT_SPEC.md） |
