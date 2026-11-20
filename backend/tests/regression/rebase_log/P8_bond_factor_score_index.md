# P8 债券券池因子打分指数（`bond_factor_score_index`）· 落库交付与对账

验收对象：`bond_factor_score_index`（债券筛券打分 + 季度调样，打包独立形态）
数据来源：`research/凤凰指数债券` 复现原型 → **归档基线**（`tests/regression/bond_factor_score_index/`，随仓库走，不依赖原型目录）
验证口径：**官方点位 + 官方筛券名单双对账 + 库内真实读库路径复算 + 全量自动化测试**。功能与界面表现由使用者自行验证。

> 结论：三张集合首次历史灌库完成并读回校验全 PASS；库内复算净值与归档变体A 基线
> `max_rel_err=2.272e-11`，与官方点位 rebase `max_rel_err=2.633e-04`（口径差，见 §3.1）；
> 2026Q4 全池 548 → 入选 60 与官方名单**逐券一致**。四条缺口已在台账中列明（§6.2），不写「基本齐全」。
>
> ❗ **遗留项（非本次引入）**：存量黄金基线 `run_regression.py check` 报 **274 处 DIFF，全部落在
> `C4_*`（监控五读端）**；回测/组合/实盘互通六条链路（C1a、C1b、C2、C2b、C3a、C4b）**逐字节一致**。
> 根因是黄金基线早于「通用监控改 gross NAV 口径（不计交易/复制成本）」这一生产语义变更，
> 证据与归因见 §5.3；**未自行 rebase**，等基线 owner 决策。

---

## 1. 通道 → 集合 → 代码落点

| 通道 | 触发入口 | 结果集合 | 代码落点 |
|---|---|---|---|
| 回测 | 策略详情 → 回测 | `backtest_records`、`strategy_models.latest_backtest_summary` | `backtesting/engine.py`、`backtesting/runner.py` → `pipeline.set_panels` |
| 实盘发布 | 策略详情 → 实盘发布 | `strategy_models.published_snapshot`、`monitor_states` | `services/live_publish_service.py` |
| 日常监控 | 发布后启动 / 步进 | `monitor_states`、`monitor_daily_reports`、`monitor_operations` | `services/monitor_service.py`（`_load_monitor_panels` → `_inject_monitor_panels`）、`monitor/rebalance_planning.py` |
| 组合子策略 | 组合管理 → 创建组合 | `portfolios`、`rebalance_records` | `portfolio/portfolio_service.py` |

三条通道**共用同一条面板注入链路**，无策略特判：

```
BondFactorScoreIndexStrategy.get_extra_panels() → ["factor_panel"]
  → data_feed.PANEL_LOADERS._load_factor_panel → load_strategy_panels(template_code, dates)
      ├─ 回测：DataFeed.from_market_service(strategy_type=…) → engine/runner set_panels
      └─ 监控：monitor_service._load_monitor_panels(rt) → _inject_monitor_panels() → pipeline.set_panels
```

调仓日同样三通道同源：`get_data_feed_options()` 声明 `panel_event_dates=True` →
`CompositionPipeline._inject_panel_event_dates` 把 28 个面板期日写进
`get_execution_schedule()["event_dates"]` → 回测由 `ScheduleResolver` 消费，
监控由 `monitor/rebalance_planning.py::_build_event_driven_rebalance_map` 用**同一个
`ScheduleResolver`** 消费（信号日 = 期日，`execution_delay=0` → 执行日 = 信号日）。
未声明 `event_dates` 的存量策略走月末 T+2 回退路径，零影响。

---

## 2. 数据集设计

### 2.1 复用三张既有集合，未新增集合

| 集合 | 业务主键 | 本次写入 | 时效级别 | 内容 |
|---|---|---|---|---|
| `assets` | `code` | 387 | permanent | 债券主数据：`asset_class=固收` / `security_type=债券` / `instrument_type=指数型` |
| `asset_prices` | `(asset_code, date)` | 93840 | permanent | 每券「全收益价格指数」，稀疏落库（§2.2） |
| `factor_panel` | `(as_of_date, code)`（**2026-10-26 起为三元 `(dataset, as_of_date, code)`，见下方补记**） | 2084 行 / 28 期 | permanent | 券池截面：27 期成分快照 + 1 期全池因子截面 |

`factor_panel` 此前已有 `COL_FACTOR_PANEL` 常量、导入器、`POST /factor-panel/import`
与前端「因子截面」tab（`DATA_IMPORT_SPEC.md` §1.1 第 11 项）——**此记载有误，实测前端不存在该 tab，详见下方修正说明**，本次首次灌入数据，
并补建索引（`FactorPanelService.ensure_indexes`）：`uniq_period_code{as_of_date,code}`（唯一）、
`idx_code_period{code,as_of_date}`、`idx_period_industry{as_of_date,industry}`
——**这三个索引已于 2026-10-26 被三元索引取代并由 `_drop_legacy_indexes` 删除，见下方补记**。
同时补齐两份文档登记：`DATA_ARCHITECTURE.md` 域 1 新增 `factor_panel` 字段/索引/消费方条目，
`DATA_GOVERNANCE.md` 域 1 资产目录与「所有权速查」各新增一行。

> **初版记载纠错（缺口 E）**：初版此处称 `factor_panel` 已有「前端因子截面 tab
> （`DATA_IMPORT_SPEC.md` §1.1 第 11 项）」。实测 `portfilio/src/views/analysis/FxImport.vue`
> 只有「汇率数据」（name=fx）与「交易日历」（name=calendar）两个 tab；前端全仓 grep
> `factor_panel` / `因子截面` 为 0 匹配（命中的 18 处全是 `scale_factor` / `boost_factor` /
> `年化因子` 等无关词）。即 `DATA_IMPORT_SPEC.md:34` 的记载本身就是错的，初版未核实便沿用。
> 后果：本次 2084 行截面数据**没有前端导入入口**，只能由一次性脚本灌入（脚本已按红线删除）。
> 后端 `app/api/factor_panel.py` 的导入/总览/读期/删期/模板下载五个端点均已存在且可用，
> 缺的只是前端 tab。已记入 §7 已知边界。

> **缺口 E 销账（2026-10-26）**：前端入口已补齐 —— `views/analysis/FactorPanelImport.vue`
> （数据集选择 + 模板下载 + 导入 + 库内总览/读期/删期）、路由 `analysis/factor-panel`
> （`name: FactorPanelImport`）、`layout/MainLayout.vue` 数据分析菜单项、`api/factorPanel.js`（6 个函数）。
> 后端端点由 5 个增至 6 个（新增 `GET /factor-panel/datasets` 数据集清单）。
> `DATA_IMPORT_SPEC.md:34` 的错误记载已同步纠正。缺口 E 关闭。

> **dataset 维度改造补记（2026-10-26）**：`factor_panel` 现由多个数据产品共用
> （`bond_phoenix50` = 本策略的债券凤凰 50 券池，`equity_quality_growth` = 股票质量成长），
> 主键、索引与映射随之改口径：
>
> | 项 | 本次交付时 | 2026-10-26 起 |
> |---|---|---|
> | 业务主键 / 唯一索引 | `(as_of_date, code)` / `uniq_period_code` | `(dataset, as_of_date, code)` / `uniq_dataset_period_code` |
> | 辅助索引 | `idx_code_period`、`idx_period_industry` | 由 `ensure_indexes` 重建，旧索引经 `_drop_legacy_indexes` 删除 |
> | 因子中文名映射 | 单张扁平表 `FACTOR_NAME_MAPPING` | 按数据集分组 `FACTOR_NAME_MAPPING_BY_DATASET` |
> | 类别因子（文本）键 | 未显式登记 | `FACTOR_CATEGORICAL_KEYS_BY_DATASET` 显式登记 |
> | 存量 2084 行 | 无 `dataset` 字段 | 已一次性回填 `dataset=bond_phoenix50` |
>
> 类别因子解析口径（以当前代码为准）：`_row_to_doc` 对因子列双路处理 —— 键在
> `categorical_keys` 内走 `_to_text` 保留原文；否则走 `_to_float`，解析失败但单元格非空时
> 按**原中文列名**计入 `bad_cells` 上报（置空、不静默丢弃）。即 §4 所称「文本列保留字符串」
> 不再无条件成立，取决于该键是否已登记。
>
> 本策略的加载口径不变：`get_panel_datasets()` 声明 `{"factor_panel": "bond_phoenix50"}`，
> `data_feed._load_factor_panel` 按 dataset 过滤，回归基线无需重算。
> 跨数据集隔离由 `tests/test_factor_panel_dataset.py`（46 项，全不触库）钉住。

### 2.2 价格稀疏落库口径（关键决策）

归档基线的价格矩阵是**密集矩阵**：1643 交易日 × 387 券 = 635841 格，其中入池前被
`fillna(100.0)` 填成恒定值 —— 那是复现原型的计算便利，不是可成交行情。落库改为**稀疏**：

| 落库行 | 规则 | 行数 |
|---|---|---|
| 成分日 | 券在该交易日属于指数成分 → 写当日全收益价格指数 | 93506 |
| 基期日 | 首次入池的**前一交易日**，值恒为 100 | 334（= 387 − 首期已在成分内的 53 只） |
| 非成分日 | **不写行**，由 `data_feed.sanitize_prices` 前向平延 | 少写 542001 条虚构行 |

两条依据：

1. `sanitize_prices` 显式保留各列首个有效观测点之前的 NaN（注释：「否则上市/首个数据日
   之前的区间会被未来价格回填成『恒定价格』」）→ 系统天然支持资产历史长度不齐，无需补虚构行。
2. 引擎在**决策日收盘**建仓（决策日 = 生效日前一交易日），新入池券当日必须有可成交价格
   → 基期行不可省。灌库脚本对此断言 `|close − 100| ≤ 1e-9`，不满足即中止。

自校验：稀疏行 pivot + `ffill` 与归档密集矩阵**在基期日起逐点一致**（`atol=1e-9`）PASS；
读回后 `基期前保持 NaN 单元 292133`（未发生后向回填）。

`asset_prices.close` 语义已写进 `assets.description`：**该券全收益价格指数，非真实成交价，
不可用于成交撮合口径**；`open/high/low/volume/amount/scale` 一律 `null`，`price_basis` 不使用。

### 2.3 `factor_panel` 双模式截面

| 期数 | `as_of_date` | `industry` | `factors` | 策略选样模式 |
|---|---|---|---|---|
| 27 | 2019-12-31 ~ 2026-06-30 | 金融债/地方债/二永债、其它信用债、历史成分 | `{}`（空） | `constituent_snapshot`：全截面等权 |
| 1 | 2026-09-30 | 同上（548 行全池） | `{issuer, issue_size, issuer_size, modified_duration}` | `factor_score`：打分 → 限额 → 前 K → 等权 |

模式判定在策略内（`_is_constituent_snapshot`）：截面缺任一拍分因子列即走快照模式，
审计字段 `selection_source` 区分二者，**不做静默兜底等权**。历史 27 期只有官方成分名单、
无逐券因子值，故按成分快照复现；当期（2026Q4）有完整因子截面，走打分复现。

`factors` 为开放 dict，**不写死因子列名**：换一套因子只改导入文件与策略参数
（`score_factors` / `score_weights` / `rank_factors`），不改表结构、不改模型。
本次为支持 `issuer`（发行人，类别因子）已把类型从 `Dict[str, float]` 放宽为
`Dict[str, Union[float, str]]`（§4）。

---

## 3. 对账闭环

### 3.1 对账表

| # | 对账层级 | 天数 / 样本 | 收益相关 | 端点误差 | 最大偏差 | 判定 |
|---|---|---|---|---|---|:--:|
| 1 | 因子打分 vs 官方得分列（发行规模分 / 主体规模分 / 久期分 / 综合分） | 548 券 × 4 列 | — | — | `max_abs_err = 2.842e-14`（容差 1e-6） | **PASS** |
| 2 | 筛券名单 vs 官方入选名单 | 548 → 60（其它信用债 10 + 金融债/地方债/二永债 50） | — | — | 对称差 **0**；发行人限额淘汰 413 | **PASS** |
| 3 | 库内行情 vs 归档基线（P0 记录数/主数据 + P1 正值/覆盖） | 93840 行；抽样 **24 日 × 全部 387 券** | — | — | 值不一致 0、库内多余 0、库内缺失 0（`atol=1e-9`） | **PASS** |
| 4 | 稀疏存储 + 前向平延 vs 密集矩阵 | 1643 日 × 387 券 | — | — | 逐点不一致券 **0**；基期前保持 NaN 292133 单元 | **PASS** |
| 5 | 库内复算净值 vs 归档变体A 基线 | 1643 日 | —（同源自算基线） | 末点 125.363241 vs 125.363241 | `max_rel_err = 2.272e-11`（容差 1e-6） | **PASS** |
| 6 | 库内复算净值 vs **官方点位**（rebase 100） | 1643 日（2020-01-02 ~ 2026-10-16） | 水平 `0.99999997`；日收益 `0.99999801` | 末点 125.363241 vs 125.330289（**+0.0263%**，累计 +25.363% vs +25.330%） | `max_rel_err = 2.633e-04`（容差 5e-4） | **PASS** |
| 7 | 调仓事件 vs 面板期日 | 28 次 vs 28 期 | — | 期初建仓 2020-01-02；末期 as_of 2026-09-30（生效 2026-10-08） | 期日集合对称差 **0** | **PASS** |
| 8 | 调样日阶跃（变体A vs 变体B 反向验证） | 27 个调样日 | — | — | 变体A `<1e-5`；变体B `3.958e-4`（超阈 1e-4，被测试锁为错误口径） | **PASS** |

第 5 行走**真实读库路径**，不复用内存对象：
`AssetService.get_price_dataframe` → `sanitize_prices` → `load_strategy_panels` →
`allocate` 选样 → 按引擎日循环约定复算净值（**持仓量记账**，权重在两次调仓间自然漂移；
持仓券当日无价格即报错，不静默跳过）。

### 3.2 第 6 行残差归因（口径差，非复现误差）

| 来源 | 说明 | 处置 |
|---|---|---|
| **现金桶** | 官方点位把未投出的剩余资金按现金收益计入；系统按红线**不模拟现金账户**，全部资金严格 1/N 投在入选券上 | 不改系统口径迁就指数；差异量级 2.633e-4 已锁定为验收容差 |
| **权重十进位舍入** | 官方按 `round(1/N, 8)` 落权重，系统严格 1/N（仅浮点残差超 `_WEIGHT_TOL=1e-8` 才归代码最小券） | 归档基线以 `round` 口径生成，故第 5 行残差 2.272e-11 即由此项贡献 |
| **调样日对齐** | 变体A：面板 `as_of` = 生效日**前一交易日**（决策日），当日收盘成交、新权重次日起息 = 指数「生效日收益用新权重」 | 已定案；变体B（`as_of` = 生效日）产生 3.958e-4 阶跃，写成反向验证用例（第 8 行） |

---

## 4. 本轮通用能力增强（`factor_panel` 支持类别因子，3 处）

三处都是**通用路径增强**（所有截面因子类策略可用），没有为 `bond_factor_score_index` 增加任何专用分支。

| 文件 | 改动 |
|---|---|
| `app/models/factor_panel.py` | `factors` 类型 `Dict[str, float]` → `Dict[str, Union[float, str]]`；字段说明区分「数值因子供打分/加权、类别因子（如发行人）供分组/限额」 |
| `app/services/factor_panel_importer.py` | 数值列走 float 归一，文本列保留字符串（不再把非数值单元格判为脏数据丢弃）——**2026-10-26 起细化为「显式登记的双路解析」，口径见 §2.1 补记** |
| `app/schemas/field_mappings.py` | `FACTOR_NAME_MAPPING` 补中文列名 → 英文键：发行人 → `issuer`、债券发行规模 → `issue_size`、主体发行规模 → `issuer_size`、修正久期 → `modified_duration`（**该常量 2026-10-26 起按 dataset 分组为 `FACTOR_NAME_MAPPING_BY_DATASET`，见 §2.1 补记**） |

`docs/DATA_ARCHITECTURE.md` / `docs/DATA_GOVERNANCE.md` 的 `factor_panel` 登记见 §2.1。

---

## 5. 测试覆盖

### 5.1 新增 `tests/regression/test_bond_factor_score_index.py`（55 项，758 行）

全部不触库、不启引擎；价格与截面直接读归档基线 parquet/CSV。

| 分组 | 项数 | 代表断言 |
|---|---|---|
| 打分公式（纯函数） | 9 | 名次分 `100*(rank_max−1)/(N−1)`，**分母锁死 N−1 而非 rank 极差**；并列取 max 名次；`N<2` 报错不产 inf；距目标分命中得 100、偏离全距归零、超全距不为负；等权严格 1/N（N=548 仍合计为 1） |
| 打分复现 vs 官方 | 2 | 548 行 × 4 列 `max_err < 1e-6`（实测 2.842e-14）；改权重为均等后与官方**不再一致**（防口径漂移） |
| 选样复现 vs 官方名单 | 6 | 548 → 60 逐券一致；两个分组各自 10 / 50 一致；等权 1/60、权重轴覆盖整池；发行人限额逐组生效；同发行人超限保留综合分更高者 |
| 净值复现 vs 归档基线 | 多项 | 变体A `max_rel_err < 1e-6`；vs 官方 `< 5e-4`；**调样日无阶跃**（变体B 有 → 反向用例） |
| 面板解析与滞后门禁 | 多项 | `panel_max_lag_days=5` 内可用、超期报错；跨期状态按实例隔离（不共享模块级变量） |
| 快照模式 / 参数门禁 | 多项 | 截面缺因子列 → `constituent_snapshot` 全截面等权；`pool_caps`/`pool_topk` 未声明分组即报错；入选券不在资产池即报错 |
| 契约与调度声明 | 多项 | `get_execution_schedule()` 不含任何日期常量；`get_data_contract()` 不声明 `min_assets`/`min_history_days`/`require_continuous`；`internal_leverage=True` |

### 5.2 全量结果

```
python -m pytest tests -q
278 passed, 1 skipped, 75 warnings in 249.50s     # 删除全部一次性脚本后重跑，无残留依赖
```

§4 三处通用增强**未造成任何退化**：既有守卫全绿且断言未修改
（`test_backtesting_boundary.py`、`test_architecture_guard.py`、`test_schema_consistency.py`、
`test_standalone_pipeline.py`、`test_data_contract.py`、`test_standalone_delivery.py`）。
模板注册已生效：启动日志 `策略服务初始化完成: 24/24 模板加载成功`，含
`✓ 更新内置模板 [bond_factor_score_index] 参数定义`。

### 5.3 存量黄金基线核对：274 处 DIFF 的归因（非本次引入，待 owner 决策）

```
python tests/regression/run_regression.py check
REGRESSION DIFFS: 274        # 两次独立运行均为 274，可复现
```

**按链路分布（差异 100% 限于 C4）**：

| 链路 | 差异数 | 说明 |
|---|---|---|
| C1a_portfolio_by_id / C1b_portfolio_by_model | **0** | 组合回测（文档/模型）逐字节一致 |
| C2_run_by_model / C2b_run_by_model_trend | **0** | 模型快捷回测逐字节一致 |
| C3a_quadrant_backtest | **0** | 四象限组合回测 + `get_param_schema` 逐字节一致 |
| C4b_model_live | **0** | 实盘互通（eligible-for-monitor + live 字段）逐字节一致 |
| **C4_nav_history** | 254 | 127 个固定切片（`end_date=2025-06-30`）× nav/daily_return |
| **C4_performance** | 8 | 含 `total_trading_cost`、`total_replication_cost` 本体 |
| **C4_positions** | 7 | nav / total_leverage / 5 个持仓 value_cnh·weight |
| **C4_attribution** | 3 | prev_nav / current_nav / total_pnl |
| **C4_signal_status** | 2 | `rebalance_history` 21→20、`monthly_rebalance.next_date` `'2026-08-26'`→`'无'` |

**成因 1（272 处）—— 通用监控改 gross NAV 口径，基线写在变更之前：**

| 证据 | 内容 |
|---|---|
| 代码 | `app/monitor/portfolio_tracker.py` 构造函数注释：「通用监控净值口径：gross NAV（不计交易成本与复制成本）……`config.TRADING_COST` / `REPLICATION_COST` 不再参与通用监控计算」，并显式置空 `self.trading_cost = {}`、`self.replication_cost = {}` |
| 代码 | `app/monitor/monitor_runtime.py::resolve_replication_cost_for_asset` 注释：「历史费率解析：通用监控已改为 gross NAV 口径（portfolio_tracker 不再调用）」 |
| 输出 | `total_trading_cost: 1.0073973807622807 → 0.0`、`total_replication_cost: 10.217978036697845 → 0.0`；成本归零后全量净值上移（`C4_positions.nav: 1436.083 → 1444.238`），`nav_history` / `performance` / `attribution` / `positions` 均为其下游 |
| **时间戳** | `golden_baseline.json` **2026-10-22 10:22** → `portfolio_tracker.py` **2026-10-22 20:04**（晚 9.7 小时）→ `monitor_runtime.py` **2026-10-23 16:44** → 本次改动 5 个文件 **2026-10-26 11:04** |

时间戳证明：基线写入时还是含费口径，成本口径切换发生在**基线之后、本次落库之前 3~4 天**。

**成因 2（2 处）—— 监控三读端数据敏感（`chains.py` 已声明为预期行为）：**
`chains.py` docstring：「C4 中 `get_performance` / `get_signal_status` / `get_positions` 基于监控推演的
『最新数据日期』状态——导入新行情后这三项会真实变化，属预期行为，需重新 rebase」。
当前库内 fixture 四资产（`000300.SH` / `ZQGZ10` / `GLD` / `SHCU`）行情止于 **2026-08-25**
（`run_init` 日志：「处理日期范围: 2025-01-02 ~ 2026-08-25, 共 429 个交易日」），
而基线生成时含 2026-08-26 → 调仓映射 21→20、`next_date` 变 `'无'`。

**与本次改动的关系：无关。** 三条独立证据：

1. 本次只改 `factor_panel` 模型/导入器/映射 + `STRATEGY_MANIFEST` 新增一行 + 新策略包 + 文档，
   **未触碰任何监控成本/推演代码**；
2. 回测与组合六条链路（C1a/C1b/C2/C2b/C3a/C4b）**零差异**；
3. 灌库写入报告 `asset_prices … 覆盖前清除旧行 0` —— 对 fixture 四资产的行情**未删未改**；
   新增的 387 只债券也不在 fixture 宇宙内。

**处置：未自行 `rebase`。** 黄金基线是仓库级回归门牌，且本次已向库内写入 387 只资产 /
93840 行行情，rebase 会同时把当前库内数据状态固化进基线；该决策归基线 owner。
建议：确认 gross NAV 口径为预期生产语义后执行 `py tests\regression\run_regression.py rebase`，
并把本节归因追写到新的 P9（或直接并入本文件）。

### 5.4 一次性灌库脚本的读回校验（已随脚本删除，结果留档于此）

```
── 写库 ──
assets        写入 387：新增 387、更新 0（库内已存在 0）、校验失败 0
asset_prices  写入 93840：新增 93840、覆盖前清除旧行 0
factor_panel  写入 2084 行 / 28 期：新增 2084、更新 0、校验失败 0

── 读回校验 ──
[P0] assets 主数据：387/387 命中，缺失 0；大类/细分/形态不符 0/0/0；未启用 0
     交易所分布 {银行间: 364, SSE: 21, SZSE: 2}
[P0] 简称缺失（以代码占位）282 只；代码含空格 0 只；名称为空 0 只
[P0] asset_prices 记录数 93840（期望 93840），有行情券 387/387，逐券条数不符 0
[P1] 非正收盘价券 0；抽样 24 个日期 × 全部资产：值不一致 0、库内多余 0、库内缺失 0
[日历] trade_dates 4344 条 (2006-11-01 ~ 2026-08-26)；行情轴 1643 日；行情轴上未入日历 189 日
[链路] 读回价格矩阵 (1643, 387)，日历与归档一致=True；基期日起逐点不一致券 0
[链路] 面板期数 28（2019-12-31 ~ 2026-09-30）；调仓事件 28 次；期日对照表 28 期
[选样] 2026-09-30 全池 548 行 → 入选 60 只，与官方名单一致=True，来源=factor_score，
       限额淘汰 413，赋权=equal
[净值] 复算 1643 日；vs 归档变体A max_rel_err=2.272e-11；vs 官方点位 rebase max_rel_err=2.633e-04
灌库校验 PASS
```

脚本按技能红线**跑完即删**（校验通过后不再保留旁路脚本），逻辑要点已固化在 §2.2、§3.1 第 5 行
与 `tests/regression/test_bond_factor_score_index.py`；台账 CSV 作为交付物保留。

---

## 6. 交付资产台账

台账文件（随仓库走）：

- `tests/regression/bond_factor_score_index/asset_ledger.csv` — 387 行逐券台账
- `tests/regression/bond_factor_score_index/asset_codes.txt` — 前端 `asset_codes` 直接粘贴用

### 6.1 台账汇总

| 分组（`industry`） | 券数 | 主数据 | 行情条数 | 首日 | 末日 | 缺口交易日 |
|---|---|---|---|---|---|---|
| 金融债/地方债/二永债 | 72 | 387/387 有（固收/债券/指数型） | — | — | — | — |
| 其它信用债 | 33 | 同上 | — | — | — | — |
| 历史成分（已退出，不在当期券池） | 282 | 同上 | — | — | — | — |
| **合计** | **387** | **387/387 有** | **93840**（单券 8 ~ 970） | **2020-01-02** | **2026-10-16** | `inner_flat_days > 0` 仅 **1** 只（最多 66 日） |

台账逐券列：`group / code / name / name_source / master_data / issuer / price_rows / member_days /
base_day / first_row / first_member_day / last_member_day / inner_flat_days / tail_flat_days`。

两个「平延日」列是**设计口径而非数据缺陷**，须在解读时区分：

| 列 | 含义 | 实测 |
|---|---|---|
| `inner_flat_days` | 首个成分日与末个成分日之间**未落库**的交易日（退出后重入之间的空档），由系统 `ffill` 平延 | 387 只中仅 1 只 > 0，最大 66 日 |
| `tail_flat_days` | 末个成分日到行情轴末日（2026-10-16）的交易日数 —— 退出指数后不再被持有，价格平延但不进权重 | 0 ~ 1585 日 |

发行人 24 家（`issuer` 去重）；简称来源：券池文件 105 只、缺失以代码占位 282 只。

### 6.2 缺口清单（4 项，均需业务方决策，不静默补齐）

| # | 缺口 | 影响 | 处置 |
|---|---|---|---|
| 1 | **282/387 券简称缺失**（原型源文件不含这 282 只历史成分的简称） | `assets.name` 以代码占位；前端资产列表显示代码，不影响任何计算 | 台账 `name_source=缺失（以代码占位）` 可筛出全部 282 只，业务方补简称后走「数据导入 → 资产主数据」覆盖 upsert |
| 2 | **2026Q4 全池 548 只中 443 只无行情**（附件 2 只覆盖 387 只历史成分） | 这 443 只在 `factor_panel` 有截面行（**参与打分**），但不在 `assets`/`asset_prices`（**不参与落地**）。官方入选 60 只全在 387 只内，故当前参数下无影响 | 若把 `pool_topk` 调大导致选中无行情券，策略 `_assert_in_pool` **明确报错**（设计如此，不静默剔除）；要支持更大 K 须先补这 443 只的行情 |
| 3 | **`trade_dates` 4344 条止于 2026-08-26**，行情轴 1643 日中 **189 日未入日历**（含 2020-01-02/01-03/01-13/01-20 与 2026-08-27 ~ 10-16 尾段） | 本策略日历口径为 `prices`（引擎 `trade_dates = list(data_feed.prices.index)`，监控 `calendar_source` 默认 `prices`）→ **不阻塞回测与监控** | 影响面是其它按 Mongo 日历对齐的策略与导入校验。补数走前端「数据导入 → 交易日历」（`POST /trade-dates/import`） |
| 4 | **首期面板 `as_of = 2019-12-31`（指数基日）不在价格轴上，也不在 `trade_dates` 内** | 仅供期初建仓定位截面：引擎在首个交易日 2020-01-02 建仓，`_resolve_panel` 命中该期（滞后 1 个交易日，在 `panel_max_lag_days=5` 容差内） | 无需补数据；把 `panel_max_lag_days` 调到 0 会导致首日建仓报错 |

---

## 7. 已知边界

1. **不模拟现金桶**：系统口径把全部资金严格 1/N 投在入选券上，官方点位含现金收益 →
   累计差 2.633e-4（§3.2）。若业务要求逐点贴合官方点位，应作为**通用能力**（可配置现金账户）
   另行设计，不在本策略内特判。
2. **`close` 是全收益价格指数，不是成交价**：不含费用、不含买卖价差，不可用于成交撮合或
   个券估值核对；`description` 已写明。默认不计费（技能红线），如需成本口径走模型级
   通用执行参数（`model_level_param_group()`）。
3. **历史 27 期只有成分名单、无逐券因子值** → 只能按成分快照复现（全截面等权），
   无法在历史期上验证打分链路。打分链路的官方对账证据来自当期 2026Q4 全池截面（§3.1 第 1、2 行）。
4. **调仓频率由面板期日决定**：`get_execution_schedule()` 只声明 `rebalance_freq="daily"` +
   `execution_delay=0` 作兜底，**不含任何日期常量**。面板没导入新区间，就不会产生新调仓日
   （区间末尾沿用最后一期成分，权重自然漂移）。
5. **`assets` 三维度枚举取 `.value` 落库**（`固收` / `债券` / `指数型`），不写废弃的
   `asset_type` 字段；`exchange` 按代码后缀映射 `IB→银行间 / SH→SSE / SZ→SZSE`。
6. **缺口 E：因子截面无前端导入入口**（**2026-10-26 已闭环，原影响已消除，见 §2.1「缺口 E 销账」**；下文为原记载）。初版误记为已有，见 §2.1 纠错块。实测
   `FxImport.vue` 只有「汇率数据」「交易日历」两个 tab，前端全仓无 `factor_panel` 引用；
   `DATA_IMPORT_SPEC.md:34` 的记载有误，已改正为「后端五个端点已就绪，前端 tab 待建」。
   影响：本策略的券池截面**只能靠脚本灌入**，无法自助更新；每接入一个同类策略都要开发
   介入写一次性脚本。后端 `app/api/factor_panel.py` 的 import / overview / period GET /
   period DELETE / 模板下载五个端点均可用，补前端 tab 即可闭环。

---

## 8. 前端步骤（用户执行）

1. **重启后端**（本次改了后端代码：策略包、manifest、模型/导入器/映射、两份文档）：
   `python main.py`（8000）；前端 `npm run dev`（8080）。模板注册在启动时刷新，
   未重启则「新建模型」看不到 `债券券池因子打分指数`。
2. **建模型**：策略库 → 新建模型 → 选 `债券券池因子打分指数`（`bond_factor_score_index`）。
3. **配底层资产**：把 `tests/regression/bond_factor_score_index/asset_codes.txt` 内容整体粘贴到
   `asset_codes`（387 只）。**必须全选 387 只**：季度调样会在其间轮换，池子给窄了会在
   某个期日触发「入选券不在资产池」报错。
4. **配参数**（默认值即官方口径，可直接用）：

   | 参数 | 默认值 | 含义 |
   |---|---|---|
   | `score_factors` | `issue_size,issuer_size,modified_duration` | 打分因子键（顺序与权重一一对应） |
   | `score_weights` | `0.2,0.2,0.6` | 综合分权重 |
   | `rank_factors` | `issue_size,issuer_size` | 名次打分因子；其余按距目标线性扣分 |
   | `duration_target` / `duration_span` | `2.5` / `7.5` | 修正久期目标值与扣分全距 |
   | `pool_caps` | `其它信用债:2,金融债/地方债/二永债:10` | 分组单发行人入选限额 |
   | `pool_topk` | `其它信用债:10,金融债/地方债/二永债:50` | 分组入选数量上限（合计 60） |
   | `panel_max_lag_days` | `5` | 截面相对执行日的最大滞后交易日数（advanced） |

5. **跑回测**：区间 `2020-01-02 ~ 2026-10-16`，初始资金任意（等权策略，净值形状不变）。
   验收对照：累计约 **+25.36%**、末点净值约 **125.36**（初始 100 口径）、调仓 **28** 次；
   与官方点位比 `max_rel_err` 应在 **2.633e-4** 量级（§3.1 第 6 行）。
6. **发布监控**：策略详情 → 实盘发布。发布后监控按 28 个面板期日驱动调仓（与回测同源），
   `monitor_states.custom_metrics` 会带上审计字段（`panel_as_of` / `selection_source` /
   `candidate_count` / `issuer_cap_dropped` / `selected_count` / `weight_method`）。
   **注意**：面板最后一期 `as_of = 2026-09-30`，此后无新调仓日；要继续日常监控须先导入
   新一期券池截面（前端「数据导入 → 因子截面」）。
7. **组合引用**：组合管理 → 创建组合 → 选该已发布策略作为子策略。

---

## 9. 复跑方式

```
python -m pytest tests/regression/test_bond_factor_score_index.py -q   # 55 passed
python -m pytest tests -q                                              # 278 passed, 1 skipped
python tests/regression/run_regression.py check                        # REGRESSION DIFFS: 274（全在 C4，归因见 §5.3）
```

本策略自身的对账不依赖黄金基线（基线四链路不含 `bond_factor_score_index`），
而是直接对归档基线与官方数据对账：`pytest tests/regression/test_bond_factor_score_index.py -q`。

环境：Windows PowerShell 需先设 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`；
MongoDB 27018（`start-mongodb.bat`，启动后等 6~7 秒）；后端 `python main.py`（8000），
前端 `npm run dev`（8080）。

归档基线（对账唯一数据源，不依赖 `research/`）：

```
tests/regression/bond_factor_score_index/
  prices.parquet                1643 × 387 密集价格矩阵（原型口径，含入池前 fillna(100)）
  panel_periods.csv             28 期 as_of / effective / constituents / panel_kind 对照表
  factor_panel_snapshots.csv    27 期历史成分快照（1536 行）
  factor_panel_2026Q4.csv       当期全池因子截面（548 行，含官方得分列与入选标记）
  baseline_nav.csv              official_rebased / variant_a_sim / rebalance_effective（1643 行）
  asset_ledger.csv              387 行逐券交付台账
  asset_codes.txt               前端 asset_codes 粘贴用
```
