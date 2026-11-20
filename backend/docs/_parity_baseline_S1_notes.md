# 执行语义零漂移基线（S1）设计说明与偏差登记

> 「回测引擎演进」批次一 S1 的交付说明。S2–S5 每步的门禁都依赖本文描述的夹具。
>
> 建立时间：2026-11-06 ｜ HEAD：`a14fa13`
> 夹具 SHA256：`5c4a4054e2553153a1194c4cde95a7bdcc388de20611f6b895a6a662b945fa10`

---

## 1. 这套基线是什么

`tests/execution_parity/` 下的四路径零漂移夹具，用于在 S2–S5 纯重构期间证明
「执行语义与记账结果逐字段不变」。

与既有 `tests/regression/` 的区别：

| | `tests/regression/` | `tests/execution_parity/` |
|---|---|---|
| 容差 | `FLOAT_RTOL = FLOAT_ATOL = 1e-12` | **无容差**，要求 `a == b` 精确成立 |
| 覆盖面 | 端到端业务链路（含 Mongo 读写、API 层） | 执行语义与记账内核（全内存，不碰库） |
| 当前状态 | **红灯**（12944 处既有 diff，权威归因见 `docs/_regression_drift_S01.md`） | 绿灯（`PARITY IDENTICAL`） |
| 对本批次的针对性 | 粗粒度，且基线过期 | 直接覆盖 S2–S5 的改动面 |

**对 S2–S5 而言 parity 是更严的闸门**：`abs=0` 能抓住浮点求和顺序变化，
而 `1e-12` 容差恰恰会把这类漂移藏起来——而这正是 S2（`mark_to_market` 的求和顺序）
和 S4（`CloseFill` 逐行照搬算术）最容易引入的问题。

---

## 2. 文件清单

| 文件 | 行数 | 作用 |
|---|---|---|
| `tests/execution_parity/__init__.py` | 9 | 包说明 |
| `tests/execution_parity/builders.py` | ~700 | 四路径驱动、固定种子价格矩阵、归一化 |
| `tests/execution_parity/compare.py` | 137 | 逐字段 `abs=0` 深度比对（**不含任何 rtol/atol**） |
| `tests/execution_parity/run_parity.py` | 117 | CLI `rebase` / `check` + SHA256 |
| `tests/execution_parity/golden_baseline.json` | 1,419,045 B | 冻结夹具 |
| `tests/execution_parity/GOLDEN_SHA.txt` | 66 B | SHA256 记录（防夹具被手改） |
| `tests/test_execution_parity.py` | ~370 | pytest 门禁，20 个用例 |

`golden_baseline.json` **未被 `.gitignore` 忽略**，会随代码提交（与 `logs/` 下的回归快照不同）。

---

## 3. 冻结规模

| 路径 | 冻结叶子字段 | 内容 |
|---|---|---|
| `single`（5 config） | 15,704 | `snapshots` 全 9 字段 × 240 日 + `trades` 全 8 字段 + `metrics` 10 项 |
| `composite`（2 variant） | 6,498 | `portfolio_nav` / `portfolio_returns` / `weight_history` / `sub_contributions` / `rebalance_dates` / `portfolio_trades` / `performance` |
| `sensitivity`（5 网格点） | 16,250 | 同 `single` 结构 |
| `monitor`（探针口径） | 6,242 | 240 行 × 14 字段 + 7 个终值标量 |
| `monitor_gross`（生产口径） | 6,242 | 同上 |
| `meta` | 27 | 种子、区间、资产码、config 键等 |
| **合计** | **50,963** | |

`metrics` 10 项：`annual_return` / `annual_vol` / `sharpe` / `max_drawdown` / `calmar` /
`total_return` / `n_trades` / `total_commission` / `total_slippage` / `turnover`。

`trades` 8 字段：`time` / `thscode` / `side` / `quantity` / `price` / `commission` /
`slippage_cost` / `pnl`。

`snapshots` 9 字段：`time` / `total_value` / `cash` / `holdings_value` / `weights` /
`is_rebalance_day` / `rebalance_type` / `signal_date` / `execution_delay_days`。

---

## 4. 分支覆盖矩阵

基线的价值不在字段多，而在**是否真的走到了要重构的那几段代码**。以下是实测确认的覆盖：

| 目标代码 | 由哪个 config 覆盖 | 实测证据 |
|---|---|---|
| `execution.py:58-61` `_commission_rate(code)` 分资产费率 | `single/by_code` | `total_commission = 29,096.442272` ≠ `flat_rate` 的 `26,406.587315` |
| `execution.py:75-84` `invest_value` **净额配平** | `single/by_code` | 期末总值 `12,201,003.769303` ≠ `flat_rate` 的 `12,195,342.290047`，成交明细亦不同 |
| `execution.py:74` 毛额分配（`invest_value = total_value`） | `zero_cost` / `flat_rate` / `initial_weights` / `empty_target` | 四者 `commission_by_code` 均为空 |
| `execution.py:98` 只遍历 `target_weights` → **遗留资产不清仓** | `single/initial_weights` | `ASSET4.TEST` 只 buy 1 次，期末权重 `0.08094623339116187 > 0` |
| `execution.py:103-104` `abs(delta) < 1e-6` 跳过 | `single/empty_target` | 只在首日 `2022-03-28` 成交 2 笔，此后 239 日零成交 |
| `execution.py:116-126` 买入分支 + `_avg_cost` 更新 | 全部 5 config | 46/46/46/49/2 笔成交 |
| `execution.py:127-134` 卖出分支 + `_avg_cost.pop` | `zero_cost` / `flat_rate` / `by_code` / `initial_weights` | 轮动权重含 `{T0:0.00, T1:0.50, T2:0.00, T3:0.50}`，触发清仓卖出 |
| `engine.py:146-157` `_compute_total_value` | 全部 | 240 个快照 × `total_value` |
| `risk.py` `max_total_leverage` 缩放 | `sensitivity/grid_1`、`grid_2` | `no_constraint` 最小现金 `-2,186,579.88`（杠杆期负现金）；两档均改变结果 |
| `risk.py` `max_weight_dict` 截断（默认上限 0.10） | `sensitivity/grid_3` | `cap_A_0.35` 期末总值 `10,753,412.158153` ≠ `no_constraint` 的 `12,195,342.290047` |
| `risk.py` 约束不咬合时应无影响 | `sensitivity/grid_4` | `loose_both`（杠杆 1.5 / 上限 0.60）与 `no_constraint` **逐字段完全相同** |
| `portfolio_tracker.py:391-400` **扣费算术** | `monitor`（费率 0.0003） | `final_total_trading_cost = 2.378862036828674 > 0` |
| `portfolio_tracker.py:403-418` 目标态赋值 | `monitor` + `monitor_gross` | 240 行 × `nav`/`nav_base`/`cash`/`quantities`/`positions_cny` |
| `portfolio_tracker.py:413-415` **遗留资产强制清零** | `monitor` + `monitor_gross` | `final_quantities['ASSET4.TEST'] = 0.0` |
| `composite_runner.py:276-278` / `:316` 原样透传 | `TestCrossPathIdentity` | 见 §5 |

---

## 5. 计划前提检验：跨路径同一性

用户指定的中止条件是「如果当前 `run_unified` 的两条路径（单策略 vs 组合）本身就结果不同，
立即中止并报告」。

**检验结论：前提成立。** 复刻 `run_composite_unified` 步骤 1–8 直驱 `run_unified`，
与 `run_composite_unified` 的输出做 float 精确比对：

| variant | `portfolio_nav` | `portfolio_trades` |
|---|---|---|
| `with_cost` | 300 点逐字段 `==` | 28 笔 × 8 字段逐字段 `==` |
| `zero_cost` | 300 点逐字段 `==` | 28 笔 × 8 字段逐字段 `==` |

依据：`composite_runner.py:276-278` 的 `portfolio_nav` 是
`[float(s.total_value) for s in result.snapshots]` 的原样透传，`:316` 的
`portfolio_trades = list(result.trades or [])` 同样是原样透传——组合路径不重新记账。

---

## 6. C1-3 差异已被如实冻结

回测与监控对「遗留资产」（在持仓中但不在目标权重里的资产）的处理相反：

| | 代码位置 | 行为 | 基线实测值 |
|---|---|---|---|
| 回测 | `execution.py:98` 只遍历 `target_weights.keys()` | **继续持有** | `ASSET4.TEST` 期末权重 `0.08094623339116187` |
| 监控 | `portfolio_tracker.py:413-415` | **强制清零** | `ASSET4.TEST` 期末数量 `0.0` |

这两侧相反的行为都进了夹具，由
`TestBaselineNonTrivial::test_backtest_monitor_legacy_asset_divergence_is_frozen` 守卫。
**S2–S5 若把这个差异悄悄抹平，会立刻报 diff。** 收敛该差异属 P5（可选），不在批次一范围。

---

## 7. 监控路径为什么要两个费率口径

已核实**生产上 `PortfolioTracker.trading_cost` 恒为空字典**：

| 位置 | 代码 | 注释原文 |
|---|---|---|
| `portfolio_tracker.py:43` | `self.trading_cost: Dict[str, float] = {}` | 「两个字典留作将来按资产配置费率的入口」 |
| `:59` | `self.trading_cost = {}`（`rt is None` 分支） | — |
| `:69` | `self.trading_cost = {}`（有 runtime 配置分支） | 「**费率留空：通用监控按 gross NAV 计算，不再回退到 config 兜底表**」 |
| `:92-94` | `_resolve_trading_cost` 未配置返回 `0.0` | 「通用监控交易费率：**未配置时恒为 0（gross NAV 口径）**」 |

因此单一口径无法同时满足两个要求，改为两组都冻结：

| 子树 | `trading_cost` | 性质 | 承担什么 |
|---|---|---|---|
| `monitor` | `{c: 0.0003}` | **分支覆盖探针**，不代表生产 | 让 `:391-400` 的扣费算术真的执行。S4 的 `RebalanceFill` 要逐行照搬这段；若基线是零成本，这段就是死代码，重构改错也不会被任何断言发现 |
| `monitor_gross` | `{}` | **生产口径**（gross NAV） | 代表性。累计成本必须精确为 0 |

守卫：`test_monitor_gross_variant_is_production_zero_cost_and_differs_from_probe` 断言
gross 口径逐日累计成本恒为 0、探针口径成本 > 0、**两者期末 NAV 必须不同**
（相同则说明其中一组没真跑到对应分支），且两组的天数/调仓次数/遗留资产清零行为一致。

---

## 8. 偏差登记

| # | 偏差 | 理由与证据 | 性质 |
|---|---|---|---|
| D1 | 敏感性路径**不导入 `app.services`**，改用 `app.backtesting.analytics.PerformanceAnalyzer(risk_free_rate=0.02)` 直算指标 + 直接构造 `RiskConfig` | 实测 `import app.services.backtest_analysis_service` = **93.89s**、`from app.services.backtest_execution import _build_risk_config` = **36.46s**。`PerformanceAnalyzer` 正是 `compute_metrics_from_result:99-105` 内部委托的同一内核，指标口径不变 | 实现路径偏差，口径不变 |
| D2 | 回归门禁的调用形式是 `py tests\regression\run_regression.py check`，不是 `pytest tests/regression/run_regression.py` | 该文件无 test 函数，pytest 收集为 0；`REGRESSION IDENTICAL` 只在脚本 `check` 模式输出 | 调用形式，未放宽断言 |
| D3 | 修正了一条 S1 内自己写的非平凡性守卫：`nav_history_len == n_days` → `== n_days - 1` | 见 §8.1 | **修正测试代码的错误预期，不是基线漂移，不是放宽断言** |
| D4 | 监控路径显式配置费率，并拆成 `monitor` / `monitor_gross` 两个口径 | 见 §7 | 让基线覆盖到该覆盖的分支 + 补回生产代表性 |
| D5 | 回归门禁每次运行都向 Mongo 写 `_regr_` 前缀临时文档并自清理 | 用户禁止数据库写操作，但同时把该脚本列为强制门禁，两者冲突。fixture 在六个集合内按 `_regr_` 前缀 create/cleanup（`finally` 保证异常也清理），不做数据迁移、不改非 `_regr_` 文档 | **约束冲突，需用户裁决**，已登记为债务 D-3 |

### 8.1 D3 的完整说明（避免未来重复归因）

**这是修正测试代码里的错误预期，不是基线漂移，也不是放宽断言。**

根因（代码级）：

- `nav_history.append` 只发生在 `process_day` 的步骤 E（`portfolio_tracker.py:923`）；
- 期初建仓走 `_initialize_positions_traditional`（`:188-196`），该函数只把
  `positions_cny` / `positions_local` / `apl_local` 置零，**不追加 `nav_history`**；
- 基线 `rows` = 1 个 `init` 行 + 239 次 `process_day` = 240 行；
- 故 `nav_history_len` 恒等于 `n_days - 1` = 239。

实测值：`n_days = 240`、`nav_history_len = 239`。原断言 `== n_days` 必然失败，
是我在 S1 内写守卫时算错了 init 行，与 `app/` 代码无关。

修正后的断言带完整注释，说明为什么是 `n_days - 1`，防止后来者再算错一次。
**未触碰 `golden_baseline.json`，未引入任何容差。**

---

## 9. S2–S5 每步怎么用

```powershell
# 门禁 1：零漂移（必须 PARITY IDENTICAL）
py tests\execution_parity\run_parity.py check
py -m pytest tests/test_execution_parity.py -q

# 门禁 2 + 4：等价性与架构守卫（必须全绿）
py -m pytest tests/test_runner_equivalence.py tests/test_backtesting_boundary.py -q

# 门禁 3：回归快照对照（不允许新增红灯，三层均无新增才算过）
py tests\regression\run_regression.py check > logs\_gate3_SX.txt 2>&1
py tests\regression\snapshot_guard.py check logs\_gate3_SX.txt logs\_regression_snapshot_S1.json
# 若上一步报 NEW，再跑 S01 工具拿逐条根因标注（A/B/C）辅助归因
py -3 scripts\regression_drift_report.py compare logs\_gate3_SX.txt
```

门禁 3 的完整语义、快照 SHA、五项自检、与 S01 工具的分工，见
`docs/_a14fa13_change_log.md` §5。12944 处 diff 的根因归因（数据重写 96.78%）见
`docs/_regression_drift_S01.md` §3。

环境：`D:\project\python3.13\python.exe`（pandas 2.2.3 / numpy 2.4.2 / pytest 9.0.3）。
仓库自带的 `venv` 已损坏——`venv\Scripts\python.exe` 指向不存在的
`C:\Users\wangb\AppData\Local\Programs\Python\Python312\python.exe`。

### 禁止事项

1. **S2–S5 禁止 `run_parity.py rebase`**。夹具是闸门不是可调参数；这两步是纯重构，
   任何数值变化都是 bug。rebase 只在「用户显式授权有意改变数值」时才允许（如 P5）。
2. **禁止在 `compare.py` 里引入 rtol/atol**。它的价值就在于不容差。
3. **禁止 rebase `tests/regression/golden_baseline.json`**，除非满足
   `docs/_a14fa13_change_log.md` §6 的**五个**前置条件且经用户授权。
4. **禁止为了让门禁变绿而删减 `TestBaselineNonTrivial` 的断言**。这组断言的作用是
   防止「两边都是空」的假绿——零漂移在空集上恒成立。

---

## 10. 相关文档

**回归 diff 的归因（S01 建立，权威来源）**

- `docs/_regression_drift_S01.md` — 12944 处 diff 的三类根因与完整证据链（**归因以本文为准**）
- `docs/_known_drifts_S01.md` — 已知差异清单说明与 S01 门禁用法
- `logs/_known_drifts_S01.json` — 12944 条差异，每条带 `root_cause: A/B/C`

**S1 收尾建立**

- `docs/_a14fa13_change_log.md` — a14fa13 变更登记、快照资产、债务 D-1~D-7。
  ⚠ 其 v1 版的归因方向错误（把数据根因归给了代码提交），v2 已置顶纠正，阅读时以 §0 为准
- `tests/regression/snapshot_guard.py` — 回归 diff 快照守卫（三层比对，值层严格）
- `tests/regression/rebase_log/` — 历史 rebase 记录（a14fa13 缺此记录，即债务 D-1）
