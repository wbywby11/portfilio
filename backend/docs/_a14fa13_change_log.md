# a14fa13 变更登记（回归 diff 的归因以 `_regression_drift_S01.md` 为准）

> 本文不是「回测引擎演进」批次一（S1–S5）的交付物，而是**既有债务的登记**。
> 目的：登记 a14fa13 对回测内核的改动范围，供未来 rebase 时查阅。
>
> 建立时间：2026-11-06 ｜ 建立位置：批次一 S1 收尾 ｜ **v2 同日纠正，见下方红框**
> 当前 HEAD：`a14fa13`（工作区另有 3 处未提交改动，见 §7）

---

## 0. ⛔ v2 纠正声明：本文初版的归因方向是错的

**初版（v1）主张**：12944 处 diff 主要归因于 a14fa13 的代码改动（分资产费率、
调仓日口径、engine 每日结算）。并用「`list_length` 为 0」作为证据，**排除**了
「数据区间漂移」这一类解释。

**这个主张是错的，排除推理也是错的。** 两点原因：

1. **`list_length = 0` 是我自己代码的 bug 造成的假象。**
   `snapshot_guard.py::classify()` 初版用 `diff.endswith("列表长度不同")` 判别类型，
   但 `compare.py:93` 的实际格式是 `f"{path}: 列表长度不同 {N} != {M}"`——标记**后面还跟着
   内容**，`endswith` 恒为 False。7 条 `list_length` diff 因此全部被误归为 `value`
   （`value` 从 12770 虚增到 12777）。`type_mismatch`（`compare.py:78` 同构）同理，
   只是它的真值恰好也是 0，结论碰巧没错。
   已修正为锚定完整格式的正则，修正后 `by_kind` 与 S01 逐项吻合（见 §4.2）。

2. **那 7 条 `list_length` 正是「数据被重写」的最强证据，而我用它们的缺席反证了相反结论。**
   实测 7 条全部是成交/调仓序列**少 2 笔**（如 `$.C2_run_by_model.data.trades: 列表长度不同 57 != 59`），
   与「`000300.SH` 交易日历从 390 天变为 359 天 → 调仓点位移」的因果链完全吻合。

**正确的归因**已由更早 47 分钟建立的 `docs/_regression_drift_S01.md` §3 给出，证据链远硬于本文：

| 根因 | 条数 | 占比 | 内容 | 证据强度 |
|---|---|---|---|---|
| **A** | 12527 | **96.78%** | `000300.SH` 区间行情于 **2026-11-02 15:11** 被重写，交易日历从 390 天（区间内全部周一至周五）变为 359 天（真实 A股日历） | ObjectId 时间戳 + 缺失的 31 个日期**逐个核对全部是 A股法定休市日**（零个真实交易日、零个周末）+ 其余 6 资产日期集双向差集为 0 |
| **B** | 413 | 3.19% | 监控推演的「最新数据日期」随行情推进漂移 | `chains.py:13-19` 已声明属预期行为 |
| **C** | 4 | 0.03% | `get_model` 响应新增 4 个 preset 留痕字段，基线未跟随 | 五层实现齐全，属有意引入（S01 §8.1） |

**a14fa13 不是这 12944 处 diff 的主因。** 时间线上数据重写（11-02）还早于该提交（11-05）3 天。
a14fa13 确实改动了回测内核（§3 逐项列举，这部分内容仍然有效、且在未来 rebase 时必须知道），
但它对 diff 的贡献**未做条目级分离**，不能声称是主因。

> 本文 v1 的错误已导致一次错误的外部决策依据（「git 提交时间、改动文件清单、diff 特征
> 三者吻合」中，**「diff 特征」这一环是 bug 产物**）。v2 保留 §2/§3 的改动登记价值，
> 撤回 §4 的归因主张，改为引用 S01。

---

## 1. 事实摘要

`tests/regression/golden_baseline.json` **已过期**，`run_regression.py check`
在进入批次一之前就是红灯：

| 事实 | 值 | 取证方式 |
|---|---|---|
| 回归基线冻结于 | `d408639`（提交 2026-10-29 14:37，文件落盘 2026-10-30 09:46） | `git log -1 -- tests/regression/golden_baseline.json` + mtime |
| 基线文件工作区状态 | 未修改、**未 rebase** | `git status --porcelain` 不含该文件 |
| 当前 HEAD | `a14fa13`（2026-11-05 16:56） | `git log -1` |
| HEAD 是否改过回测内核 | **是**，12 个文件、1120 insertions / 28 deletions | `git show --stat a14fa13 -- app/backtesting/ app/monitor/ app/allocation/` |
| 基线 SHA256 | `92280bd5a28fc3a2abfbd8227a3cdd0b80869e7fff2f06a8df6b13b731386e83` | 与 S01 §8.4 记录一致 |
| 当前 diff 数 | **12944** | `run_regression.py check` 末行 `REGRESSION DIFFS: 12944` |
| 主根因 | **数据重写（根因 A，96.78%）**，非代码改动 | `_regression_drift_S01.md` §3 |

**12944 处 diff 不是批次一引入的**——批次一 S1 阶段对 `app/` 零改动
（`git status --porcelain -- app/backtesting app/monitor app/portfolio app/standalone_strategies app/allocation/models`
输出为空）。

⚠ **易踩的坑 1**：`tests/regression/_check_log.txt` 末行写着 `REGRESSION IDENTICAL`，
但该文件时间戳是 **2026-08-11**，早于 d408639 与 a14fa13，是三个月前的旧日志。
S1 期间曾据它误判「回归基线当前是绿的」，已用 git 证据推翻。
**判断回归门禁状态必须实跑 `run_regression.py check`，不得读该日志。**

⚠ **易踩的坑 2（v2 新增）**：S01 §4 第 3 条称「项目不是 git 仓库」
（`git status` → `fatal: not a git repository`）。实测在 `portfilio-end/` 下 git 命令**正常可用**
（本文全部 git 证据均实跑取得）。S01 那次应是在错误目录下执行，其「不可回退」的顾虑
不成立于当前环境——但**「rebase 需用户显式授权」这一结论仍然正确**，不因 git 可用而改变。

---

## 2. 提交事实

```
commit a14fa13c71b9d5e31d7d7740a865b69b643563aa
Author: wbywwwwww
Date:   2026-11-05 16:56:49 +0800
Subject: feat(upgrade): 三策略与宏观估值序列增量包入库，剔除 Generative UI 实验模块

- 策略：新增 dividend_garp / erp_timing_enhance / industry_timing_target_vol 三套独立策略，
  同步 bond_factor_score_index / factor_score_index / nous_low_vol 口径修正
- 宏观：新增 macro_series 模型、服务与 /api/v1/macro 路由（序列查询、数据导入、模板下载）
- 预设：新增 builtin_presets 与 strategy_preset 服务/路由，资产 tags 多值索引支撑按标签展开资产池
- 回测：composition/engine/data_feed/runner 与组合、监控、再平衡口径对齐，补充 analysis 服务
- 剔除 GenUI 实验后端（app/genui、api/gen_ui.py、路由注册），llm_client 回退到基线
- 资产下拉 /assets/options 取数上限 500 -> 5000，避免千只资产被截断
- 补三策略对账基线 CSV、单测与数据文档；清理不在增量范围内的实验脚本
- .gitignore 收纳一次性排查目录、升级包解包产物与核对中间输出

规模：74 files changed, 16233 insertions(+), 1172 deletions(-)
```

提交信息第 4 条「**回测：composition/engine/data_feed/runner 与组合、监控、再平衡口径对齐**」
是本次漂移的自述根因——它明说了口径变了，但没有同步 rebase 回归基线，
也没有在 `tests/regression/rebase_log/` 留下记录。

---

## 3. 回测内核改动逐项（数值后果）

只列与回归 diff 有因果关系的改动，取证方式均为 `git show a14fa13 -- <file>`。

### 3.1 分资产费率链路（新增能力，改变成交计费）

| 文件 | 改动 | 数值后果 |
|---|---|---|
| `app/backtesting/config.py` | 新增 `commission_by_code: Optional[Dict[str, float]] = None` | 缺省 `None`，未声明费率的策略行为不变 |
| `app/backtesting/execution.py` | 新增 `_commission_rate(code) = float(_by_code.get(code, self._config.commission_rate))`；`commission = gross * _commission_rate(code)`（原为 `gross * self._config.commission_rate`） | 自带费率表的策略，逐笔手续费改变 |
| `app/backtesting/execution.py` | **新增 `invest_value` 净额配平分支**：`_by_code` 非空且 `total_value > 0` 时，按 `Σ(|目标权重 − 当前权重| × (费率 + 滑点))` 估算 `cost_rate`，`invest_value = total_value * (1 − min(max(cost_rate,0),1))`；`target_value` 由 `total_value * w` 改为 `invest_value * w` | 目标数量改变 → 成交量、现金、净值全链路改变 |
| `app/backtesting/runner.py` (+38) | 新增 `_resolve_cost_owner()` + `_apply_trading_costs()`：把策略 `get_trading_costs(params)` 自述的费率表回填到 config | 声明了费率的独立策略，此前费率被静默跳过（净值偏高），现在真的扣 |

> 这三处正是批次一 S1 基线 `by_code` config 所覆盖的分支。S1 已实测该分支生效：
> `by_code` 期末总值 `12,201,003.769303` vs `flat_rate` `12,195,342.290047`，成交明细亦不同。

### 3.2 调仓日口径（改变调仓时点）

| 文件 | 改动 | 数值后果 |
|---|---|---|
| `app/backtesting/composition_builder.py` (+11) | `force_month_end = strategy_type in _MONTH_END_ALLOCATORS` 提到分支外，**「不启用选择器」的返回分支也必须带回该标记**（原 `return CompositionSpec(composition=dict(base_composition))` 漏传） | 纯 tag_based 预算类模型此前退回普通 `monthly`，调仓日在月初/月末之间错位；修正后**调仓日改变** |
| `app/monitor/rebalance_planning.py` (+130) | 新增 `_resolve_declared_execution_delay()` | 执行延迟解析口径变化 → 执行日改变 |
| `app/backtesting/composition_pipeline.py` (+7) | 保留 `natural_frequency`（原「模型一填 execution_delay 就丢失该声明」） | daily/weekly 自然频率语义恢复，回测与监控频率同源 |

### 3.3 每日结算与数据链路

| 文件 | 改动 | 数值后果 |
|---|---|---|
| `app/backtesting/engine.py` (+8) | `_run_daily_settle` 的 extra 并入 close：`_settle_extra.setdefault("close", bar.close)` | 实现了每日结算钩子的策略（闲置资金利息、GC001 回购利息、成本/年费拖累）现在能按当日收盘价折算持仓市值 → 逐日 `total_value` 改变 |
| `app/backtesting/data_feed.py` (+261) | 新增 `_load_macro_series` / `_load_asset_metrics` / `_schema_min_history_days` / `resolve_lookback_days` / `with_scenario_shocks` / `_resolve_shock_date` / `_shock_prices` | lookback 解析与最小历史天数口径变化会影响信号起算日；情景冲击是新增能力（默认不启用） |
| `app/monitor/portfolio_backtest_monitor.py` (+3) | 母层传入 `commission_rate` / `slippage`（注释「母层成本与子策略同一组参数，保证监控与回测的成本口径一致」） | 组合监控母层由 gross 变为计成本 |
| `app/allocation/builtin_presets.py` (+589) | 新增预设 | 走预设的链路参数来源改变 |

---

## 4. 12944 处 diff 的归因（v2：改为引用 S01）

> v1 在此处自行做了一套归因，方向错误（见 §0）。v2 不再重复分析，
> 只转引 `docs/_regression_drift_S01.md` 与 `docs/_known_drifts_S01.md` 的结论，
> 并保留两份工具对同一批 diff 的**交叉校验**结果。

### 4.1 按链路（根因标注取自 S01 §3）

| 链路 | diff 数 | 根因 |
|---|---|---|
| `C2b_run_by_model_trend` | 3801 | **A**（数据重写） |
| `C2_run_by_model` | 3560 | **A** |
| `C1a_portfolio_by_id` | 1778 | **A** |
| `C1b_portfolio_by_model` | 1778 | **A** |
| `C3a_quadrant_backtest` | 1603 | **A** |
| `C4_nav_history` | 254 | **B**（监控最新日漂移） |
| `C4_signal_status` | 128 | **B** |
| `C4_positions` | 12 | **B** |
| `C4b_model_live` | 11 | **A×7 + C×4** |
| `C4_attribution` | 10 | **B** |
| `C4_performance` | 9 | **B** |
| **合计** | **12944** | A 12527 / B 413 / C 4 |

回测五链路（C1a/C1b/C2/C2b/C3a）合计 **12520 处，占 96.7%**，全部命中根因 A。
传导路径：`000300.SH` 同时出现在 `ASSETS_RP`、`ASSETS_EQ`、`ASSETS_TC` 与
`QUADRANT_SIGNAL_CODE`，故五条链路无一幸免。

**两份工具对 `by_chain` 的统计逐链路完全一致**（我的 `snapshot_guard.summarize` vs
S01 的 `regression_drift_report`），这是两套独立实现互为校验的结果。

### 4.2 按 diff 类型（v2 已修正）

| 类型 | v1 误报 | **v2 实测** | S01 记录 | `compare.py` 行 |
|---|---|---|---|---|
| `value` | 12777 | **12770** | 12770 ✓ | 71 / 75 / 99 |
| `key_missing_in_baseline` | 125 | **125** | 125 ✓ | 85 |
| `key_missing_in_current` | 42 | **42** | 42 ✓ | 87 |
| `list_length` | ~~0~~ | **7** | 7 ✓ | 93 |
| `type_mismatch` | 0 | **0** | 0 ✓ | 78 |

`12770 + 7 = 12777` —— v1 的 `value` 恰好比真值多 7，即被吞掉的那 7 条 `list_length`。
这个数字对得上，是 bug 定位的决定性证据。

**那 7 条的完整原文**（实测从快照中提取，各链路一致地「少 2 笔」）：

```
$.C1a_portfolio_by_id.data.trades:        列表长度不同 129 != 131
$.C1b_portfolio_by_model.data.trades:     列表长度不同 129 != 131
$.C2_run_by_model.data.trades:            列表长度不同 57 != 59
$.C2b_run_by_model_trend.data.trades:     列表长度不同 1472 != 1490
$.C3a_quadrant_backtest.data.trades:      列表长度不同 111 != 113
$.C3a_quadrant_backtest.data.weight_history: 列表长度不同 12 != 14
$.C4_signal_status.rebalance_history:     列表长度不同 21 != 22
```

> 小勘误：S01 §2.2 的样例把 `C1a` 与 `C2b` 的数值标串了（写作 `C2b: 129 != 131`、
> `C1a: 1472 != 1490`）。实测应为 `C1a: 129 != 131`、`C2b: 1472 != 1490`。
> 不影响 S01 的条数统计与「各链路一致少 2 笔」的结论，仅此处路径↔数值对应关系需修正。

键存在性差异共 167 处（125 + 42），主要集中在 `equity_curve[i].weights.<code>`
（`ZQGZ10` 87 处），另有 `is_rebalance_day` 14 处、`date` 61 处、`SH` 26 处、
`n_trades` / `turnover` / `total_commission` / `total_slippage` 各 9 处。

**S01 的解释（正确）**：`equity_curve` / `weights` 数组长度变化后，`compare.py:80-90`
按 index 对齐时产生**键错位**——同一资产在某些 index「基线缺失该键」、在另一些 index 数值不等，
125 与 42 正是同一错位现象的两个方向。

~~**v1 的解释（已撤回）**：「这组特征与 §3.2 调仓日改变高度吻合」；
「`list_length` 为 0 说明回测区间与序列长度没变，**排除**数据区间漂移」。~~
真相是序列长度**变了**（7 处），而它变的根源正是数据区间被重写。

### 4.3 本文还剩多少归因价值

- **有效**：§2 提交事实、§3 回测内核改动逐项（逐文件读 diff 取得）。a14fa13 确实改了
  `execution.py` / `engine.py` / `runner.py` / `composition_builder.py` / `data_feed.py` /
  `rebalance_planning.py`，这些改动在未来 rebase 时**必须知道**，否则会把它们的后果
  误算到别的变更头上。
- **撤回**：「a14fa13 是 12944 处 diff 的主因」这一主张，以及支撑它的 `list_length = 0` 排除推理。
- **未做**：a14fa13 对 diff 的**条目级贡献分离**。若要做，需在 `d408639` 与 `a14fa13`
  两个 checkout 上各跑一次 `run_regression.py check`，比对差集——这是 S5 后 rebase 的前置动作（§6）。
- **风险提示**：根因 A 是「历史行情被一次性重写」。若 S2–S5 期间 `asset_prices` 再次被写入，
  回归 diff 集合会整体变动，届时快照守卫会报大量 NEW，**那不是 S2–S5 引入的回归**，
  而须按 S01 §7 的失效条件重新 freeze。

---

## 5. 快照资产（S2–S5 期间的对照基线）

### 5.0 ⚠ 重复建设：S01 已有一套同类且更强的基础设施

本次 S1 收尾建快照时，**未发现工作区已存在 S01 建立的同类资产**（建立时间早 47 分钟）：

| | S01（15:25） | S1 收尾（16:11） |
|---|---|---|
| 工具 | `scripts/regression_drift_report.py`（freeze / compare） | `tests/regression/snapshot_guard.py`（build / check） |
| 快照 | `logs/_known_drifts_S01.json`（2,998,907 B） | `logs/_regression_snapshot_S1.json`（2,160,016 B） |
| 文档 | `_regression_drift_S01.md`（478 行）+ `_known_drifts_S01.md`（159 行） | 本文 + `_parity_baseline_S1_notes.md` |
| **逐条根因标注** | **有**（每条带 `root_cause: A/B/C`） | 无 |
| 差异身份键 | `(chain, path)`，**不含值** | diff 字符串**全文**（含值） |
| 允许已知差异的值微变 | 是 | **否**（值变即报 NEW） |
| 自检 | 正向 / 交叉 / 负向 三项 | 正向 / 反向 A–D 五项 |

**两套的实质差异在于宽严**：S01 故意放宽值层（理由：根因 A/B 源于行情数据，
已知差异的值会随行情微变）；本快照对值层也严格比对（理由：S2–S5 是**纯重构**，
任何值变就是漂移）。

**处理决定**：两套共存，分工如下，不删除 S01 资产（它带根因标注，归因能力更强）：

- **归因用 S01**：`logs/_known_drifts_S01.json`（每条带 A/B/C）+ 两份 S01 文档。
- **S2–S5 门禁用本快照**：`snapshot_guard.py check`，因为它对纯重构更严（值层也卡）。
  若它报 NEW 而 S01 工具报 PASSED，说明差异只在**值**上、path 集合未变——
  对 S2–S5 而言这仍是**必须解释的漂移**，不得当作通过。
- 若 S2–S5 期间行情数据再次被写入（S01 §7 失效条件），**两套都需重建**。

### 5.1 本快照的字段

| 项 | 值 |
|---|---|
| 快照文件 | `logs/_regression_snapshot_S1.json` |
| 快照 SHA256 | `9b511a37c24ba7f3b490dffa0c63d5d206ab26d4605098b3a1475452b6d25ebc` |
| 快照大小 | 2,160,016 字节 |
| 内容 | 12944 条 diff 全文（值层）+ 12944 个唯一路径（路径层）+ 计数/链路/类型摘要 |
| `by_kind` | value 12770 / key_missing_in_baseline 125 / key_missing_in_current 42 / **list_length 7** |
| 建立时 HEAD | `a14fa13` |
| 记录的 parity 基线 SHA256 | `5c4a4054e2553153a1194c4cde95a7bdcc388de20611f6b895a6a662b945fa10` |
| 守卫脚本 | `tests/regression/snapshot_guard.py`（不改动 `run_regression.py` / `compare.py`） |

> **v1 → v2 的快照变更**：SHA 从 `f87a1790…` 变为 `9b511a37…`，但**值层与路径层逐条未变**
> （仍是同一批 12944 条 diff 全文 + 12944 个路径）。变的只有 `summary.by_kind`
> 的分类修正与 `meta.note`。因此守卫的**判据不变**，四项反向测试重跑结果与 v1 一致（见 §5.2）。

⚠ **`logs/` 被 `.gitignore:50` 忽略**，快照不受版本控制，清理工作区即丢失。
本文记录了 SHA256 与重建方法，因此可复现，不必提交 2MB JSON：

```powershell
# 前提：HEAD = a14fa13、golden_baseline.json 未 rebase、000300.SH 行情未再被重写
py tests\regression\run_regression.py check > logs\_gate3_regression.txt 2>&1
py tests\regression\snapshot_guard.py build logs\_gate3_regression.txt `
    logs\_regression_snapshot_S1.json "<note>"
```

重建前提中「行情未再被重写」是 S01 揭示的关键变量：根因 A 源于 2026-11-02 的一次行情写入，
若再发生同类写入，重建出的快照将与本文 SHA 不同且 diff 集合整体变动。

### 5.2 三层比对与五项自检

`snapshot_guard.py check <本次日志> <快照.json>` 做三层比对，末行输出
`SNAPSHOT GUARD OK` / `SNAPSHOT GUARD NEW: <n>` / `SNAPSHOT GUARD RESOLVED: <n>`（exit 0/1）：

| 层 | 比对对象 | 用途 |
|---|---|---|
| 计数层 | diff 总数 | 粗信号 |
| 路径层 | diff 路径集合的新增/消失 | **新增路径 = 新增红灯**，最关键 |
| 值层 | diff 字符串全文集合 | 同一路径 golden/actual 值变化 |

五项自检（v2 修正 `classify()` 后**全部重跑**，验证修正未削弱检出能力）：

| 测试 | 构造 | 期望 | 实测 |
|---|---|---|---|
| 正向 | 同一份日志自比 | `OK` | `SNAPSHOT GUARD OK`（12944 条逐条一致），exit 0 |
| 反向 A | 注入 1 条伪造 diff | `NEW: 1` | `SNAPSHOT GUARD NEW: 1`，exit 1 |
| 反向 B | 删除 1 条真实 diff | `RESOLVED: 1` | `SNAPSHOT GUARD RESOLVED: 1`，exit 1 |
| 反向 C | 同路径改值（**总数不变**） | `NEW: 1` | `SNAPSHOT GUARD NEW: 1`，exit 1 |
| 反向 D | 注入 1 条伪造的 `list_length` 型 diff | `NEW: 1` | `SNAPSHOT GUARD NEW: 1`，exit 1 |

**反向 C 是关键**：它证明「diff 数不变（12944 → 12944）」不足以保证没有新引入的差异，
值层比对是必要的。S2–S5 每步的门禁判据因此是**三层均无新增**，不是只看计数。

**反向 D 是 v2 新增**：专门验证 `list_length` 类型的 diff 也能被检出——因为 v1 的 bug
正是在这个类型上。它证明 `classify()` 的修正只影响**摘要展示**，不影响 `new_diffs` /
`gone_diffs` 判据（那两个走 diff 字符串全文与 path 集合，不经 `classify`）。

### 5.3 S2–S5 每步的调用方式

```powershell
py tests\regression\run_regression.py check > logs\_gate3_S2.txt 2>&1
py tests\regression\snapshot_guard.py check logs\_gate3_S2.txt logs\_regression_snapshot_S1.json
# 归因时另跑 S01 工具（带 A/B/C 根因标注）
py -3 scripts\regression_drift_report.py compare logs\_gate3_S2.txt
```

⚠ **PowerShell `>` 重定向默认写 UTF-16LE（BOM `FF FE`），不是 UTF-8**。
`snapshot_guard.read_text_any()` 已按 BOM 自动识别（UTF-16LE/BE、UTF-8-BOM、纯 UTF-8 均可）。
S1 期间曾因按 UTF-8 硬读而一条 diff 也解析不到，已修。S01 工具也已验证兼容两种编码。

⚠ 该门禁每次运行都会通过 `tests/regression/fixture.py` 向 Mongo 写入 `_regr_` 前缀临时文档
并在 `finally` 中清理（涉及 `backtest_records` / `strategy_live_change_logs` / `monitor_states` /
`strategy_param_versions` / `portfolios` / `strategy_models` 六个集合）。见 §7 债务 D-3。

---

## 6. S5 完成后必须 rebase 回归基线（不是可选）

批次一 S2–S5 重写的正是 a14fa13 改过的部分（`execution.py` 记账算术、`engine.py` 估值委托）。
叠加根因 A（`000300.SH` 行情重写，96.78%）与根因 C（preset 四字段），
回归基线**不可能**通过「恢复 d408639 的旧值」变绿，必须在新代码 + 新数据上重建。

rebase 的前置条件（**五条**全满足才可执行，且需用户显式授权）：

1. `tests/execution_parity` 门禁为 `PARITY IDENTICAL`（S2–S5 是纯重构，parity 基线 SHA256
   必须仍是 `5c4a4054e2553153a1194c4cde95a7bdcc388de20611f6b895a6a662b945fa10`）；
2. `snapshot_guard.py check` 的三层比对相对本快照**无新增**，或每一处新增都能归因到
   S2–S5 的某个具体步骤；
3. 完成 §4.3 所述的条目级归因：在 `d408639` 与 rebase 时的 HEAD 两个 checkout 上各跑一次
   `run_regression.py check`，确认差集里没有未归因差异；
4. **（v2 新增）先处理 S01 单独立项 D3**：fixture 7 个资产的交易日历口径不一致
   （`000300.SH` 359 天真实 A股日历 vs 其余 6 个 390 天全工作日日历）。
   若不先统一就 rebase，会把一个**已知错误的 fixture 口径**写进新基线，
   下次发现时又得重新 rebase。该项需写 `asset_prices`，**必须单独授权**；
5. **（v2 新增）确认根因 B 的处理口径**：C4 链路的 413 处差异源于「监控推演最新日随行情推进」，
   `chains.py:13-19` 已声明这是预期行为、需重新 rebase。但它意味着**这部分差异会持续再生**：
   rebase 后只要再导入新行情，C4 链路又会红。rebase 时必须同时决定是否把 C4 的
   时间敏感字段列入切片或 `VOLATILE_KEYS`，否则基线建完即过期。

rebase 后必须在 `tests/regression/rebase_log/` 留一份记录，写明：rebase 时的 HEAD、
新旧基线 SHA256、diff 归因结论（引用 S01 三类根因 + 本文 §3 代码改动）、授权人。
**a14fa13 缺的正是这份记录；根因 C 的 preset 四字段也缺（S01 §8.1 待补）。**

---

## 7. 登记的债务

| # | 债务 | 影响 | 建议处理时点 |
|---|---|---|---|
| D-1 | a14fa13 改了回测内核口径但未 rebase 回归基线、未在 `rebase_log/` 留记录 | 回归门禁失去意义；后来者需重新归因 | 本文即登记。S5 后按 §6 一次性处理 |
| D-2 | `tests/regression/_check_log.txt`（2026-08-11）末行的 `REGRESSION IDENTICAL` 会被误读为当前状态 | 误判门禁为绿（S1 期间已实际踩到一次） | 建议该文件改名或加显式时间戳头部；或从判断流程中移除，只认实跑结果 |
| D-3 | `tests/regression/fixture.py` 每次跑都向 Mongo 六个集合写 `_regr_` 临时文档（自清理） | 与「禁止数据库写操作」约束冲突；无法在只读环境跑该门禁。**S2–S5 每步都跑 regression 就意味着每步都写库** | 批次一结束后评估改为内存态或独立临时库 |
| D-4 | 回归快照落在 `logs/`（被 `.gitignore:50` 忽略），不受版本控制 | 清理工作区即丢失，需按 §5.1 重建（重建依赖行情未再变） | 可接受（重建方法已记录）；若需长期留存，另选受控路径 |
| D-5 | 工作区有 3 处未提交改动：`app/allocation/builtin_presets.py`、`app/services/factor_panel_importer.py`、`tests/regression/fixture.py` | `builtin_presets.py` 可能影响走预设的链路，使 diff 归因多一个变量 | 见 §7.1：三处不能一刷子 stash |
| **D-6** | **重复建设**：`snapshot_guard.py` + `_regression_snapshot_S1.json` 与 S01 的 `regression_drift_report.py` + `_known_drifts_S01.json` 功能重叠 | 两套工具、两份 2–3MB 快照、四份文档描述同一批 12944 处 diff；后来者会困惑该信哪份 | 已按 §5.0 定下分工（归因用 S01、门禁用本快照）。若用户认为冗余，可弃用本快照改跑 S01 工具，但会失去值层严格比对 |
| **D-7** | **S1 期间我写了一份归因方向错误的文档**（v1 把 96.78% 的数据根因归给了代码提交），根因是自己的 `classify()` bug | 已对外产生一次错误决策依据（用户据 v1 认定「diff 特征与 a14fa13 吻合」） | 已按 §0 置顶纠正。教训记入 §7.2 |

### 7.1 D-5 的补充：三处未提交改动不能一刷子 stash

v1 曾建议「批次一开始前由用户决定是否提交或 stash」。这个建议对其中一处是**错的**：

| 文件 | 改动内容 | stash 掉的后果 |
|---|---|---|
| `tests/regression/fixture.py` | `cleanup()` 补删 `::model` 后缀文档（S01 §8.2 已授权修复） | ⛔ **不能 stash**。stash 后每跑一次 regression 就在 `monitor_states` 永久残留 2 条孤儿文档（S01 §5 发现 4：不可自愈） |
| `app/allocation/builtin_presets.py` | 未核实 | 可能影响走预设的链路，是归因的一个额外变量 |
| `app/services/factor_panel_importer.py` | 未核实 | 与回归链路无直接关系（待确认） |

S01 §8.2 已实测证明：`fixture.py` 修复前后的 **12944 条差异逐条完全相同**
（新增 0 / 消失 0 / 类型变化 0），因此该修复**不影响快照可复现性**，
v1 对这一点的隐含担忧是多余的。

**建议**：`fixture.py` 尽快提交（它是 bug 修复，不属批次一范围但已被授权）；
另两处由用户核实后决定。**S1 未触碰这三处。**

### 7.2 D-7 的教训（写给未来的自己）

错误链是：**一个字符串匹配 bug → 一个假的统计量（`list_length = 0`）→ 一次错误的排除推理
（「排除数据区间漂移」）→ 一个方向相反的归因结论**。四步里每一步看起来都合理。

三个可操作的防御：

1. **分类/统计代码必须对拍已有实现或原始格式**。本例中只要把 `classify()` 的输出与
   `compare.py` 的 5 个 `diffs.append` 格式逐条对拍，bug 立即可见。
2. **用「排除法」下结论前，先证明那个「0」是真的**。0 是最危险的统计量——
   它既可能是「真的没有」，也可能是「没检测到」。
3. **归因前先搜工作区是否已有同类结论**。`docs/_regression_drift_S01.md` 就在那里，
   478 行，证据链比我的硬。如果先读了它，就不会有 v1。

---

## 8. 相关文件

**归因与已知差异（S01 建立，本文不重复）**

- `docs/_regression_drift_S01.md` — **12944 处 diff 的权威归因**（三类根因 + 完整证据链，478 行）
- `docs/_known_drifts_S01.md` — 已知差异清单说明与门禁用法（159 行）
- `logs/_known_drifts_S01.json` — 12944 条差异，**每条带 `root_cause: A/B/C`**
- `scripts/regression_drift_report.py` — freeze / compare 两模式，身份键 `(chain, path)`
- `docs/_baseline_fields.md` — 基线字段清单

**本文相关**

- `tests/regression/snapshot_guard.py` — 快照守卫（build / check，值层严格比对）
- `logs/_regression_snapshot_S1.json` — S2–S5 对照快照（SHA `9b511a37…`）
- `tests/regression/run_regression.py` — 既有回归 CLI（**未修改**）
- `tests/regression/compare.py` — 既有比对器，容差 `FLOAT_RTOL = FLOAT_ATOL = 1e-12`（**未修改**）
- `tests/regression/golden_baseline.json` — 过期的回归基线（**未修改、未 rebase**）
- `tests/execution_parity/` — 批次一 S1 建立的零漂移基线（`abs=0`，无容差）
- `docs/_parity_baseline_S1_notes.md` — S1 基线设计说明与偏差登记（D1–D5）
