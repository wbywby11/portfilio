# 后端回归基建与增强方案

> 前置背景：架构统一修复（7 批次）已完成，路由 238→220，服务边界与依赖方向已收口。
> 本方案覆盖三个后续任务，按顺序执行：**T1 回归测试基建 → T2 N+1 查询优化 → T3 双份实现收敛**。
> T2、T3 必须在 T1 就位后进行，用 T1 的回归检查作为验收门槛。

---

## T1 常驻回归测试套件（核心）

### 问题定义

两轮架构改造各自重建了一次性验证脚本（`_debt_fixture.py`、`_arch_fixture.py` + `_arch_baseline.py`），
做完即删。系统缺少**可重复的行为基线**：任何人改回测/监控/服务层代码后，无法用一条命令确认数值行为未漂移。
（注：已删脚本未提交 git，无法恢复，按本方案重写；核心设计已验证过两轮，直接复用。）

### 目录结构

```
portfilio-end/tests/regression/
├── __init__.py
├── fixture.py            # 测试数据创建/清理（幂等）
├── chains.py             # 四链路执行器（直调服务层，不起 HTTP）
├── compare.py            # walk_diff 递归对比器
├── run_regression.py     # CLI 入口：rebase / check 两模式
└── golden_baseline.json  # 黄金基线（提交 git）
```

### fixture.py 设计

- 所有测试文档统一前缀 `_regr_`（模型名、组合名、监控实例 ID），便于清理与识别。
- 创建内容（对齐上轮已验证的 fixture 结构）：
  - 4 个策略模型：`risk_parity`、四象限（quadrant）、等权（equal_weight）、动量类模板各一，
    参数取模板默认值，资产用系统内已有行情的资产（从 `model_templates` 集合取模板，勿手写参数结构）；
  - 1 个投资组合：引用其中 2 个模型，固定权重 + 月度再平衡；
  - 1 个监控实例：对 risk_parity 模型执行 `run_init`（固定 init 日期）。
- **日期区间写死**（如 `START = "2024-01-02"`, `END = "2025-06-30"`），保证后续行情追加不影响基线数值。
- `create()` 与 `cleanup()` 均幂等：create 前先 cleanup 同前缀文档；cleanup 按前缀删除
  `strategy_models` / `portfolios` / `backtest_records` / `live_publish_logs` / `monitor_states` 五个集合。
- 链路执行包在 `try/finally` 中，异常也要 cleanup。

### chains.py 四链路

全部**直调服务层/API 函数**（import FastAPI 依赖树，不起 uvicorn），输出统一为 jsonable dict：

| 链路 | 内容 | 调用入口 |
|------|------|---------|
| C1 | 组合回测 ×2（fixture 组合 + 内联组合配置） | `run-portfolio-by-id` / `run-portfolio` 对应服务调用（`app/api/backtests.py` L2010/L2206 背后的管道） |
| C2 | 模型快捷回测 | `run-by-model` 服务路径（backtests.py L927 背后） |
| C3 | 四象限链路 | 四象限权重模型回测 + `get_param_schema()` 输出 |
| C4 | 监控读端 | `MonitorService`：`get_nav_history` / `get_positions` / `get_performance` / `get_signal_status` / `get_daily_attribution` |
| C4b | 实盘互通 | `eligible-for-monitor` 端点函数 + `get_model`（含 live_effective 字段） |

### compare.py 对比器

- `walk_diff(path, before, after, diffs)`：递归对比 dict/list/标量；
- float 容差 `1e-12`（相对+绝对取宽）；
- `VOLATILE_KEYS` 剔除易变字段：`_id`, `id`, `record_id`, `model_id`, `portfolio_id`,
  `created_at`, `updated_at`, `completed_at`, `execution_time`, `timestamp`, `duration_ms`, `run_id`
  （实施时跑一次 rebase→check 自验，把仍然抖动的键补进列表——判断标准：**与业务数值无关的标识/时间戳类字段才允许剔除**）。

### run_regression.py CLI

```
py tests\regression\run_regression.py rebase   # fixture→四链路→写 golden_baseline.json→cleanup
py tests\regression\run_regression.py check    # fixture→四链路→对比 golden→cleanup→报告
```

- `check` 输出末行为明确标记：`REGRESSION IDENTICAL` 或 `REGRESSION DIFFS: <n>`（逐条打印 diff 路径），
  exit code 0/1。
- ⚠️ Windows/PowerShell 注意：loguru 输出到 stderr 会让 ExitCode 呈现假失败，**以末行标记为准**；
  运行命令统一 `py`（非 python）。
- golden_baseline.json 用 `json.dump(..., sort_keys=True)`（不缩进，控制体积），提交 git。

### 验收标准（T1.完成定义）

1. `rebase` 后立即 `check` → `REGRESSION IDENTICAL`；
2. 手工改一个回测参数默认值再 `check` → 能报出 DIFF（验证灵敏度），改回后恢复 IDENTICAL；
3. 两次 `check` 之间 DB 无 `_regr_` 前缀残留文档；
4. golden_baseline.json 已提交。

---

## T2 `_get_asset_daily_changes` N+1 查询优化

### 问题定义

[monitor_service.py L2556-2600](../app/services/monitor_service.py)：逐资产各发一次
`find({'asset_code', 'date'}).sort('date',-1).limit(2)`，持仓页/归因页每次请求 N 次串行 Mongo 往返。

### 改法（推荐：并发化，零行为差异）

保持单资产查询函数体不变，仅将串行 for 循环改为 `asyncio.gather` 并发：

```python
async def _fetch_one(aid: str, stored: str):
    cursor = prices_collection.find(
        {'asset_code': stored, 'date': {'$lte': as_of_date}},
        {'date': 1, 'close': 1}
    ).sort('date', -1).limit(2)
    prices = await cursor.to_list(length=2)
    # ……原涨跌幅计算逻辑逐字保留……
    return aid, value

pairs = [(aid, stored_price_code(config.ASSET_NAME_TO_CODE[aid])
              if aid in config.ASSET_NAME_TO_CODE else str(aid).strip())
         for aid in names]
results = await asyncio.gather(*[_fetch_one(a, s) for a, s in pairs])
result = dict(results)
```

- 不选 `$topN` 聚合方案：依赖 Mongo ≥ 5.2，且改变查询形态需重新验证等价性；
  gather 方案结果逐字节等价，只消延迟。
- 注意 `result` 的键序：原实现按 `names` 顺序插入。`dict(results)` 配合 gather
  的返回顺序与输入顺序一致（asyncio.gather 保序），键序不变。

### 验收标准

`py tests\regression\run_regression.py check` → `REGRESSION IDENTICAL`（C4 覆盖 positions/attribution）。

---

## T3 汇率/波动率双份实现收敛（先审计后动手）

### 现状映射（已核实的函数对）

**汇率解析：**

| 回测域 | 监控域 |
|--------|--------|
| `app/backtesting/index_nav.py::get_fx_rate` | `app/monitor/portfolio_tracker.py::get_fx_rate / get_all_fx_rates / get_asset_fx_rate / get_all_asset_fx_rates` |
| `app/services/fx_service.py`（数据服务，唯一 DB 入口，保留） | `app/monitor/data_provider.py::load_fx / _normalize_fx_dataframe / _fx_from_xlsx` |
| — | `app/monitor/signal_detector.py::_get_asset_fx_today` |

**波动率触发/重置：**

| 位置 | 函数 |
|------|------|
| `app/allocation/models/base.py` | `check_volatility_trigger` / `compute_volatility_reset_weights`（疑似规范实现） |
| `app/backtesting/composition_pipeline.py` | 同名两函数 |
| `app/monitor/engine_adapter.py` | 同名两函数 |
| `app/monitor/volatility_calculator.py` | `calc_current_volatility` / `calc_asset_volatility_raw` / `calc_portfolio_volatility_raw` 等 |

（研究员策略 `researcher_strategies/*/engine.py` 内的 `_get_fx_rate` / `_calc_*_volatility`
**不在收敛范围**——该模块定位为自包含轻量通道，刻意隔离。）

### 阶段 1：审计（只读，产出映射表）

对上表每一对同名/同职能函数做逐行 diff，将结果分为三类：

- **A 逐字一致**：可直接收敛为单一实现 + 转发；
- **B 数值等价但写法不同**（如年化因子、窗口对齐方式一致，仅代码组织不同）：收敛前需构造
  同输入对拍脚本证明输出一致；
- **C 有意差异**（如监控域用 T+2 汇率、回测域用当日）：**不收敛**，改为在两处代码加交叉引用注释
  `# 与 app/xxx.py::yyy 存在口径差异（原因），修改任一侧须同步评估另一侧`。

审计结论输出为本文档附录（每对函数：A/B/C 分类 + 证据）。

### 阶段 2：收敛（仅 A/B 类）

- 收敛方向：**波动率触发/重置以 `app/allocation/models/base.py` 为 home**（策略域是规范定义方），
  `composition_pipeline` 与 `engine_adapter` 改为 import 转发；
- 汇率解析优先收敛 `portfolio_tracker` 内四个函数与 `index_nav.get_fx_rate` 的重复逻辑，
  数据加载（`FxService` / `data_provider.load_fx`）各域保留（属数据编排，非公式）；
- 每收敛**一对**函数 → 跑一次 `check` → IDENTICAL 才做下一对；任何 DIFF 立即回退该对，归入 C 类。

### 验收标准

1. 全部 A/B 类函数对收敛后 `check` → `REGRESSION IDENTICAL`；
2. C 类函数对两侧均已加交叉引用注释；
3. 附录审计表完整（无"未分类"项）。

---

## 执行顺序与整体验收

```
T1 fixture/chains/compare/run_regression 实现
  → rebase 生成 golden → check 自验 IDENTICAL → 灵敏度验证 → 提交
T2 gather 并发化
  → check IDENTICAL → 提交
T3 阶段1 审计表
  → 阶段2 逐对收敛（每对一次 check）→ 提交
```

| 任务 | 预估工作量 | 风险 |
|------|-----------|------|
| T1 | 1~1.5 天 | 低（设计已验证过两轮，纯固化） |
| T2 | 0.5 小时 | 极低（保序并发，行为等价） |
| T3 | 审计 0.5 天 + 收敛视 A/B 数量 | 中（严格按"每对一 check"节奏可控） |

---

## 附录：T3 审计结果

审计日期：2026-07-30。分类依据逐行 diff + 临时对拍脚本（`_tmp_t3_audit_check.py`，已删除）。
B 类结论均以同输入对拍 IDENTICAL（atol=1e-12）为前提；不确定项一律保守归 C。

### 汇率解析

| # | 函数对 | 分类 | 证据/差异说明 |
|---|--------|------|---------------|
| FX-1 | `app/backtesting/index_nav.py::IndexNavConfig.get_fx_rate` (L56) ↔ `app/monitor/portfolio_tracker.py::PortfolioTracker.get_fx_rate` (L447) | **C** | 数据模型不同（按资产键的 Series/常数 dict vs 按货币列的 DataFrame）；NaN 行为不同（对拍取证：当日值为 NaN 时 index_nav 直接返回 NaN，tracker 跳过 NaN 向前回退取到 7.10）；index_nav 支持常数汇率、无时间戳规范化（tracker 走 `normalize_calendar_timestamp` + 索引 coerce）。不收敛，双侧加交叉引用注释。 |
| FX-2 | `portfolio_tracker.py::get_all_fx_rates` (L498) / `get_asset_fx_rate` (L515) / `get_all_asset_fx_rates` (L520) ↔ 同文件 `get_fx_rate` | **A**（内部薄封装） | 三函数均为对 `get_fx_rate` 的字典推导/货币映射薄封装，无独立公式逻辑；与回测域无对应重复实现，收敛动作仅限跟随 FX-1 结论（即无动作）。 |
| FX-3 | `app/monitor/signal_detector.py::_get_asset_fx_today` (L295，闭包) ↔ `portfolio_tracker.py::get_fx_rate` (L447) | **B**（仅查找内核） | 汇率查找内核（当日命中→NaN 跳过→向前回退→1.0 兜底）对拍 11 用例（当日有值/当日 NaN/末日 NaN/越界/CNH/缺列/空表/重复日期/乱序索引/非交易日）全部 IDENTICAL。注意两点须在收敛时保留在调用侧：① 货币解析链不同（detector 为 rt.asset_currency→config→resolve_asset_currency_for_monitor 三级回退，tracker 为 asset_currency.get(asset,'CNH')）；② detector 有整体 try/except 吞错返回 1.0。收敛范围限查找内核本身。 |
| FX-4 | `app/monitor/data_provider.py::load_fx` (async L245 / sync L511) / `_normalize_fx_dataframe` (L119) / `_fx_from_xlsx` (L136) ↔ `app/services/fx_service.py` | **保留，不在收敛范围** | 逐行核查：仅含查询构建、pivot、索引规范化、去重、排序及缺列填 1.0/CNH=1.0 的数据整形约定，无汇率解析"公式"逻辑混入；xlsx 回退直接复用 `FxService._load_from_xlsx`。属数据编排，按方案声明各域保留。 |
| FX-5 | `app/services/fx_service.py`（`get_rate`/`get_rates_dataframe`/`get_fx_series_for_assets` 等） | **保留（对照项）** | 唯一 DB 入口，方案已声明保留不动，仅作对照，不参与收敛。 |

### 波动率触发/重置

| # | 函数对 | 分类 | 证据/差异说明 |
|---|--------|------|---------------|
| VOL-1 | `app/backtesting/composition_pipeline.py::check_volatility_trigger` (L200) / `compute_volatility_reset_weights` (L222) / `compute_monitoring_metrics` (L180) ↔ `app/allocation/models/base.py` 同名 (L99/L122/L80) | **C**（已是代理，守卫为有意差异） | 无重复公式——三函数均转发至 allocator（合并 `_strategy_params`）。但存在有意旁路：composition 未配置 `controller` 时短路返回 `(False,None)`/`None`/`{}`，而直调 base.py 在 `enable_vol_reset=True` 时会走 `_default_portfolio_vol` 内置兜底——即"无 controller + enable_vol_reset=True"场景两者行为不同，docstring 明示该守卫是为"避免 allocator 内置兜底逻辑被误触发"的设计。另 reset 返回契约不同（base 未启用时返回原 `current_weights`，pipeline 返回 `None`）。不收敛，加交叉引用注释。 |
| VOL-2 | `app/monitor/engine_adapter.py::check_volatility_trigger` (L160) / `compute_volatility_reset_weights` (L169) / `compute_monitoring_metrics` (L152) ↔ `composition_pipeline.py` 同名 | **A**（纯转发，已收敛形态） | 逐行核查为无条件直通 `self._pipeline.*(...)`，无参数改写、无旁路、无兜底分支；对 base.py 的差异完全继承自 VOL-1 的守卫。阶段 2 无收敛动作需要，保持现状即可。 |
| VOL-3 | `app/monitor/volatility_calculator.py::calc_portfolio_volatility_raw` (L344) ↔ `base.py::_default_portfolio_vol` (L14，经 `formula.compute_portfolio_volatility`) | **B**（附前提） | 对拍 4 用例（干净数据末日/中段截断/前段 NaN/零权重）全部 IDENTICAL（atol=1e-12；窗口 [22,65,130]、年化 260、ddof=1 均一致；NaN 上 `fillna(0)` 与 `sum(skipna=True)` 数值等价）。已知边界：负权重时 DIFF（raw 过滤 `w>0`＝0.1497，base 保留负权重＝0.1553）——唯一生产调用方 `monitor_service.py` L1765 已先行过滤 `v>0`，前提成立。收敛须保留 calc_date 锚定语义（base 侧由调用方截断 `prices.loc[:calc_date]`）。 |
| VOL-4 | `volatility_calculator.py::calc_asset_volatility_raw` (L321) ↔ `app/formula/rolling_volatility.py::compute_asset_rolling_volatility` (L55) | **C** | 干净数据下对拍 IDENTICAL（末日/中段截断），但缺失值口径不同：formula 侧对单资产收益 `dropna()` 压缩序列后取 `tail(window)`（窗口跨越缺口拉长日历跨度），raw 侧按 `date_idx` 定位切片保留 NaN。对拍取证：中段插入 10 日 NaN 后 raw_A=0.15850 vs formula_A=0.16519，DIFF。多资产历史长短不齐是常态，保守归 C。 |
| VOL-5 | `volatility_calculator.py::calc_current_volatility` (L26) / `calc_volatility_history` (L105) / `calc_status` (L292) ↔ `base.py::_default_portfolio_vol` | **C** | 口径明确不同：百分比形式（×100）+ `round(2)`、全列 `pct_change().fillna(0)`（含首行 0 而非丢弃）、权重来源为持仓重建（w_cny=持仓市值/nav 或 event_log 权重时间线）、`loc[:current_date]` 截断、最小窗口守卫+异常吞错返回 None。属监控展示口径而非策略触发口径，不收敛。 |
| VOL-6 | `app/monitor/researcher_strategies/`（hybrid_12 与 sharpe_18 的 `_get_fx_rate` / `_calc_*_volatility`） | **排除** | 按方案 L144-145 声明为自包含轻量通道、刻意隔离，不在收敛范围，本次未审计。 |

### 阶段 2 输入摘要

- 可收敛对：FX-3（仅查找内核，货币解析链留在调用侧）、VOL-3（保留 calc_date 锚定 + 调用侧 `w>0` 前提）。
- 需加交叉引用注释的 C 类对：FX-1（index_nav ↔ portfolio_tracker 双侧）、VOL-1（pipeline 守卫 ↔ base 兜底双侧）、VOL-4（raw ↔ formula 双侧）、VOL-5（monitor 展示口径侧）。
- 无动作项：FX-2、FX-4、FX-5、VOL-2、VOL-6。
