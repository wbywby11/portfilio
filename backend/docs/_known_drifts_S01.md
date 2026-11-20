# S01 已知回归差异清单

> 生成时间：2026-11-06（归因描述于同日修正，items 逐条未动）
> 清单文件：`logs/_known_drifts_S01.json`（3,000,498 字节，12944 条）
> 生成工具：`scripts/regression_drift_report.py freeze`
> 来源日志：`logs/_regression_post_D5.log`（`run_regression.py check` 输出）
>
> **这不是 rebase**：`tests/regression/golden_baseline.json` 未改动（mtime 仍为
> 2026-10-30 09:46:22，1,093,971 字节，SHA256 `92280BD5…386E83`）。本清单只登记
> 「S01 时点已归因的差异」，供后续步骤做新增差异比对。
>
> ⚠ **根因归因已修正**：原本把 12527 处归为「`000300.SH` 行情日历口径变更」，
> 经决定性实验**证伪**，真正根因是 HEAD 提交 `a14fa13` 改了回测内核口径但未 rebase 基线。
> 证据与实验过程见 `docs/_regression_drift_S01.md` **§9**（§3 根因 A 原文保留作取证记录）。
> **条数划分与门禁行为均未变**：差异身份键是 `(chain, path)`，`root_cause` 不参与判定；
> 补丁后重跑 compare 仍为 `GATE PASSED` / exit 0 / 新增 0 / 消失 0 / 类型变化 0。
>
> 三类根因的完整证据链见 `docs/_regression_drift_S01.md`，本文不重复分析。

---

## 1. 三类根因

| 根因 | 条数 | 占比 | 一句话归因（**已修正**） | 详细证据 |
|---|---|---|---|---|
| **A** | 12527 | 96.78% | HEAD 提交 `a14fa13`（2026-11-05）改了回测内核口径但未 rebase 基线：分资产费率与 `invest_value` 净额配平、`force_month_end` 修正与执行延迟解析、`_run_daily_settle` 并入 close、lookback 与最小历史天数、监控母层计成本 | `_regression_drift_S01.md` **§9**（含 git 取证与 167 处键差异形态表）、`_a14fa13_change_log.md` §3 |
| **B** | 413 | 3.19% | 监控推演的「最新数据日期」随行情推进而漂移，`chains.py:13-19` 已声明属预期行为 | `_regression_drift_S01.md` §3 根因 B |
| **C** | 4 | 0.03% | `get_model` 响应新增 4 个 preset 留痕字段；`git log -S` 证实**由 `a14fa13` 引入**，与 A 同源；字段属有意引入（model + schema + service + API + 测试五层齐全，库内 7 条实际数据） | `_regression_drift_S01.md` §3 根因 C、§8.1、§9.2 |
| 合计 | **12944** | 100% | ＝`a14fa13` 未 rebase（12531，A+C）＋监控推演日漂移（413，B） | |

> **A 的原归因已作废**：原文为「`000300.SH` 区间行情在基线冻结后被重写，交易日历从 390 天
> 变为 359 天（剔除 31 个法定休市日）」。数据观测本身为真（`000300.SH` 确实于 2026-11-02
> 被重写为 359 条），但**不是差异的原因**：回测日期轴由其余 6 个 390 天资产决定，
> 基线与当前的 `equity_curve` 长度**都是 390**。证伪的三个判据见 `_regression_drift_S01.md` §9.3。

## 2. 差异类型分布

来自 `compare.py:59-99` 的 5 种输出格式：

| kind | 条数 | 对应 `compare.py` 行 | 含义 |
|---|---|---|---|
| `value_mismatch` | 12770 | 71 / 75 / 99 | 标量不等（bool / 数值 / 字符串） |
| `baseline_missing_key` | 125 | 85 | 基线无该键、本次输出有 |
| `current_missing_key` | 42 | 87 | 基线有该键、本次输出无 |
| `list_length` | 7 | 93 | 列表长度不同 |
| `type_mismatch` | 0 | 78 | 类型不同 |

`baseline_missing_key` 125 条中，4 条属根因 C（preset 四字段），
36 条是 `n_trades` / `total_commission` / `total_slippage` / `turnover` 四个**新增成本响应字段**
（各 9 条，均由 `a14fa13` 引入），其余 85 条为权重键出现（主要是 `ZQGZ10`）。

> ❗ **原文以下表述已作废**：「其余 121 条属根因 A——`equity_curve` / `weights` 数组长度变化后，
> `compare.py:80-90` 按 index 对齐时产生的键错位，与 `current_missing_key` 42 条是同一错位现象的两个方向」。
> 实测：**`equity_curve` 无长度差异**（两边都是 390）；数组长度差异只有 7 条，
> 全在 `trades`（4 条）、`weight_history`（1 条）、`rebalance_history`（1 条）上。
> 因此「index 对齐错位」这个机制**并不存在**，167 处键差异是真实的字段增删，
> 形态分析见 `_regression_drift_S01.md` §9.3。

## 3. 链路分布

| 链路 | 条数 | 根因 |
|---|---|---|
| C2b_run_by_model_trend | 3801 | A |
| C2_run_by_model | 3560 | A |
| C1a_portfolio_by_id | 1778 | A |
| C1b_portfolio_by_model | 1778 | A |
| C3a_quadrant_backtest | 1603 | A |
| C4_nav_history | 254 | B |
| C4_signal_status | 128 | B |
| C4_positions | 12 | B |
| C4b_model_live | 11 | A×7 + C×4 |
| C4_attribution | 10 | B |
| C4_performance | 9 | B |

五条**回测类**链路全部命中，两条非数值链路（`C3b_quadrant_schema` 只校 schema、
`C4b_eligible` 只校布尔）零差异——该形态与「`a14fa13` 改了回测内核口径」一致：
内核变更会影响所有跑数值的回测链路，与具体资产宇宙无关。

> ❗ 原文此处为「`000300.SH` 同时出现在 `ASSETS_RP`/`ASSETS_EQ`/`ASSETS_TC` 与
> `QUADRANT_SIGNAL_CODE`，故五条链路全部命中根因 A」。该推论已作废：
> 资产共享不能解释为何 `equity_curve` 长度未变、也不能解释 `000300.SH` 自身零键丢失。

## 4. 分类口径修正说明

本清单的 `by_root_cause` 为 **A 12527 / B 413 / C 4**，与 S01 中止报告中给出的
**A 12520 / B 413 / C 11** 不同。原因是中止报告按**链路**粗分（把 `C4b_model_live`
的 11 条全部归入 C），本清单按**字段**精确分：

`C4b_model_live` 的 11 条实际由两部分构成：

| 字段 | 条数 | 根因 |
|---|---|---|
| `preset_code` / `preset_version` / `preset_applied_at` / `asset_selection_snapshot` | 4 | C（基线缺失该键） |
| `latest_backtest_summary.*`（`total_return` / `win_rate` 等） | 7 | A（随 fixture 回测结果变化） |

`latest_backtest_summary` 是 `StrategyModel` 上存的最近回测摘要
（`app/models/strategy_model.py:344-348`），其值随 fixture 回测结果变动，
根因与五条回测链路同源，故归 A。

同时修正差异类型口径：中止报告中的「其他 42」实为 `current_missing_key`
（`compare.py:87`「本次输出缺失该键」），本清单已按 `compare.py` 的 5 种格式精确命名。

## 5. 门禁用法

批次一 S02 及后续步骤的回归门禁：

```powershell
# 1. 跑回归 check（输出重定向到日志）
py -3 tests\regression\run_regression.py check *> logs\_regression_stepXX.log

# 2. 与已知差异清单比对
py -3 scripts\regression_drift_report.py compare logs\_regression_stepXX.log
```

判定标准：

| 输出项 | 要求 |
|---|---|
| `新增差异（门禁要求 = 0）` | **必须为 0**，否则 GATE FAILED，返回码 1 |
| `消失差异` | 允许变化，但必须能解释，并记录到该步输出 |
| `差异类型变化` | 允许变化，但必须能解释，并记录到该步输出 |

差异身份键为 `(chain, path)`，不含 `old` / `new` 的具体值——
已知差异的数值可随行情微变而变动，只要 path 集合不新增即视为通过。

工具已完成双向验证：

| 测试 | 输入 | 结果 |
|---|---|---|
| 正向 | `logs/_regression_post_D5.log`（清单来源日志） | 新增 0 / 消失 0 / 类型变化 0，GATE PASSED，返回码 0 |
| 交叉 | `logs/_regression_pre_S01.log`（D5 修改前的 UTF-8 日志） | 新增 0 / 消失 0 / 类型变化 0，GATE PASSED，返回码 0 |
| 负向 | 3 条已知 + 1 条伪造 path `__NEGATIVE_TEST__` | 新增 1，GATE FAILED，返回码 1 |

交叉测试同时证明两件事：`compare` 兼容 UTF-8 与 UTF-16 LE 两种日志编码
（PowerShell `Out-File -Encoding utf8` 与 `*>` 重定向）；
D5 修改前后的 12944 条差异**逐条完全相同**，不只是数量相同。

## 6. 清单 JSON 结构

```json
{
  "generated_at": "2026-11-06T15:25:22",
  "source_log": "logs/_regression_post_D5.log",
  "baseline_file": "tests/regression/golden_baseline.json",
  "note": "S01 时点的已知回归差异清单。golden_baseline.json 未 rebase。...",
  "total_diffs": 12944,
  "by_root_cause": {"A": 12527, "B": 413, "C": 4},
  "by_chain": {"C2b_run_by_model_trend": 3801, "...": "..."},
  "by_kind": {"value_mismatch": 12770, "...": "..."},
  "root_cause_desc": {"A": "...", "B": "...", "C": "..."},
  "items": [
    {
      "chain": "C1a_portfolio_by_id",
      "path": "$.C1a_portfolio_by_id.data.calmar_ratio",
      "kind": "value_mismatch",
      "old": "1.234",
      "new": "1.235",
      "root_cause": "A"
    }
  ]
}
```

`items` 共 12944 条，每条含 6 个字段。

## 7. 清单失效条件

以下任一情况发生时，本清单需重新 freeze：

1. 执行了 `run_regression.py rebase`（`golden_baseline.json` 变更）
2. **HEAD 变更且新提交改了回测/监控内核**（当前根因 A 的来源就是 `a14fa13`）
3. D3 单独立项完成（fixture 7 个资产的交易日历口径统一，见 `_regression_drift_S01.md` §7）
4. 行情数据再次发生区间内重写（S01 已证实 2026-11-02 那次重写**未**产生可归因差异，
   但它改变了基线输入，下次重写不保证同样无害）
5. `fixture.py` 的 `START` / `END` / 资产宇宙发生变更

重新 freeze 的命令：

```powershell
py -3 scripts\regression_drift_report.py freeze logs\_regression_<新日志>.log
```
