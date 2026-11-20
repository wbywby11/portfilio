# S01 回归基线差异归因（未 rebase，待决策）

> 记录时间：2026-11-06
> 触发原因：执行《SOTA 策略库建设实施计划》批次一 S01「建立基线」时，
> `tests/regression` 的 check 模式未通过，按批次一约束「基线不干净不允许继续」中止。
> 本文只做归因与证据留存，**未执行 rebase，未改动任何业务代码**。
> 库内数据方面：本次未执行任何主动写操作；但按 S01 要求运行 `run_regression.py check` 时，
> 该测试自身的 fixture 在 `monitor_states` 留下 2 条未清理文档（详见 §5 发现 4）。

---

## 1. 现象

命令与结果：

```
py -3 tests\regression\run_regression.py check
→ 末行：REGRESSION DIFFS: 12944
→ exit code = 1
```

完整输出留存于 `logs/_regression_pre_S01.log`。

对照历史记录：`tests/regression/rebase_log/P8_bond_factor_score_index.md` 第 11-14 行记载，
P8 交付时（2026-10-30）同一命令报 **274 处 DIFF，全部落在 `C4_*`**，
而 C1a / C1b / C2 / C2b / C3a / C4b 六条链路**逐字节一致**。

即：**从 274 处增长到 12944 处，新增的 12670 处全部落在回测链路**——这是本次需要归因的主体。

---

## 2. 差异分布

### 2.1 按顶层链路

| 链路 | DIFF 数 | 占比 |
|---|---|---|
| C2b_run_by_model_trend | 3801 | 29.4% |
| C2_run_by_model | 3560 | 27.5% |
| C1a_portfolio_by_id | 1778 | 13.7% |
| C1b_portfolio_by_model | 1778 | 13.7% |
| C3a_quadrant_backtest | 1603 | 12.4% |
| C4_nav_history | 254 | 2.0% |
| C4_signal_status | 128 | 1.0% |
| C4_positions | 12 | 0.1% |
| C4b_model_live | 11 | 0.1% |
| C4_attribution | 10 | 0.1% |
| C4_performance | 9 | 0.1% |
| **合计** | **12944** | 100% |

回测五链路（C1a/C1b/C2/C2b/C3a）合计 **12520 处，占 96.7%**。

### 2.2 按差异类型

按 `compare.py:59-99` 的 5 种输出格式精确分类
（S01 中止报告中的「其他 42」实为「本次输出缺失该键」）：

| kind | 数量 | `compare.py` 行 | 含义 |
|---|---|---|---|
| `value_mismatch` | 12770 | 71 / 75 / 99 | 标量不等（bool / 数值 / 字符串） |
| `baseline_missing_key` | 125 | 85 | 基线无该键、本次输出有 |
| `current_missing_key` | 42 | 87 | 基线有该键、本次输出无 |
| `list_length` | 7 | 93 | 列表长度不同 |
| `type_mismatch` | 0 | 78 | 类型不同 |

`baseline_missing_key` 125 条中 4 条属根因 C（preset 四字段），其余 121 条属根因 A：
`equity_curve` / `weights` 数组长度变化后，`compare.py:80-90` 按 index 对齐时产生的键错位，
与 `current_missing_key` 42 条是同一错位现象的两个方向。

长度不一致的 7 处样例（本次输出比基线**少 2 笔**，各链路一致）：

```
$.C2_run_by_model.data.trades:        列表长度不同 57 != 59
$.C2b_run_by_model_trend.data.trades: 列表长度不同 129 != 131
$.C1a_portfolio_by_id.data.trades:    列表长度不同 1472 != 1490
$.C3a_quadrant_backtest.data.trades:  列表长度不同 111 != 113
```

---

## 3. 根因归因

### 根因 A（❗**已证伪，保留作取证记录，结论见 §9**）：`000300.SH` 区间行情在基线冻结后被重写

> ⚠ **本节的「传导路径」与「结论」已于 2026-11-06 经决定性实验证伪。**
> 下方的**数据观测（时间线、359/390 条数、缺失的 31 个日期全为法定休市日）经复核全部为真**，
> 但它们**不是** 12944 处差异的原因。真正的根因是 HEAD 提交 `a14fa13` 改了回测内核口径
> 但未 rebase 基线。完整证据与修正后的归因见 **§9**。
> 本节原文保留，目的是记录一次归因错误的完整形态（数据事实为真 ≠ 因果成立）。

**时间线证据**

| 对象 | 时间 | 来源 |
|---|---|---|
| `golden_baseline.json` 冻结 | 2026-10-30 09:46:22 | 文件 mtime |
| `000300.SH` 区间内行情写入 | 2026-11-02 15:11（CST） | ObjectId 时间戳，359 条集中在同一分钟 |
| `ZQGZ10`/`GLD`/`SHCU`/`SPX`/`UST10` 写入 | 2026-08-28 10:57（CST） | ObjectId 时间戳，**早于**基线冻结 |
| `HSTECH` 写入 | 2026-07-29 17:20（CST） | ObjectId 时间戳，**早于**基线冻结 |

fixture 用到的 7 个资产中，**只有 `000300.SH` 在基线冻结之后被重写过**。

**条数证据**

`tests/regression/fixture.py` 第 33 行注释声明：

> 资产宇宙：均已核实在 2024-01-02 ~ 2025-06-30 有完整行情（390 行）

实测该区间内各资产的日期条数：

| 资产 | 条数 | 与注释声明的 390 行 |
|---|---|---|
| 000300.SH | **359** | 少 31 |
| ZQGZ10 | 390 | 一致 |
| GLD | 390 | 一致 |
| SHCU | 390 | 一致 |
| SPX | 390 | 一致 |
| UST10 | 390 | 一致 |
| HSTECH | 390 | 一致 |

**缺失的 31 个日期逐个核对，全部是 A股法定休市日，零个真实交易日、零个周末：**

| 缺失日期 | 星期 | 对应节假日 |
|---|---|---|
| 2024-02-09 ~ 02-16（6 天） | 周五~周五 | 2024 春节 |
| 2024-04-04 ~ 04-05 | 周四~周五 | 2024 清明 |
| 2024-05-01 ~ 05-03 | 周三~周五 | 2024 劳动节 |
| 2024-06-10 | 周一 | 2024 端午 |
| 2024-09-16 ~ 09-17 | 周一~周二 | 2024 中秋 |
| 2024-10-01 ~ 10-04、10-07（5 天） | 周二~周一 | 2024 国庆 |
| 2025-01-01 | 周三 | 2025 元旦 |
| 2025-01-28 ~ 01-31、02-03 ~ 02-04（6 天） | 周二~周二 | 2025 春节 |
| 2025-04-04 | 周五 | 2025 清明 |
| 2025-05-01 ~ 05-02、05-05（3 天） | 周四~周一 | 2025 劳动节 |
| 2025-06-02 | 周一 | 2025 端午 |

这些日期在 `SPX` 与 `ZQGZ10` 中**全部存在**。

**390 这个数字的来源**：2024-01-02 ~ 2025-06-30 共 545 个自然日 ≈ 78 周，
78 × 5 = 390 个工作日。即 `ZQGZ10`/`GLD`/`SHCU`/`SPX`/`UST10`/`HSTECH` 六个资产的日期集
是**「区间内全部周一至周五」，未剔除任何节假日**（实测 `ZQGZ10` 与 `SPX` 的日期集完全相同，
双向差集均为 0）。而 `000300.SH` 现在是 390 − 31 = 359，即**按真实 A股交易日历**。

**传导路径（❗已证伪，以下为当时的错误推断，保留作对照）**：`000300.SH` 同时出现在 `ASSETS_RP`、`ASSETS_EQ`、`ASSETS_TC` 与四象限信号标的
（`QUADRANT_SIGNAL_CODE = "000300.SH"`），因此 C1a / C1b / C2 / C2b / C3a 五条链路全部受影响，
与 §2.1 的分布完全吻合。~~日历少 31 个交易日使调仓点位移，产生：~~

- ~~`trades` 条数变化（各链路一致少 2 笔）~~
- ~~`equity_curve` / `weights` 数组长度变化，导致 `compare.py:80-90` 按 index 对齐时**键错位**~~
- `annual_return` 等汇总指标变化，例：
  `0.16050273735140386 != 0.15993086322808514`（此条为真，但原因不是日历）

**证伪要点（详见 §9）**：

1. `equity_curve` 长度在基线与当前输出中**都是 390**（无 `list_length` 差异），
   交易日历轴**根本没变**——「日历少 31 天」不会传导到回测序列长度。
2. 7 条 `list_length` 差异全部是**当前比基线多**（`trades` +2/+2/+18/+2、
   `weight_history` 12→14、`rebalance_history` 21→22），即**调仓变多**，
   与「日历变短→调仓变少」的方向相反。
3. `000300.SH` 权重键差异共 26 处，方向是「**基线缺失该键**」（当前多出），
   且集中在 `C2b.data.snapshots[17..42]` 一段**连续区间**；
   若真是 31 个假日无行情，应表现为**散落在 31 个假日上的「本次输出缺失该键」**。实测为零。

**结论（❗已作废）**：~~这 12520 处差异不是代码缺陷，是 `000300.SH` 行情数据的交易日历口径
在基线冻结后发生变化。~~

**修正后的结论**：`000300.SH` 确实在 2026-11-02 被重写为 359 条真实交易日历，
但因回测引擎的日期轴由其余 6 个资产（390 天）决定、缺失日按前值填充，
**该数据变化未对回归输出产生可归因的差异**。12527 处的真正根因是 `a14fa13` 的代码变更（§9）。
附带发现 1（fixture 7 个资产日历口径不一致，§5 / §7 D3）**仍为真且仍需处理**，
但它不是回归红灯的原因——两者需在文档中分开。

### 根因 B：监控推演最新日随行情推进（413 处，3.19%）

`tests/regression/chains.py` 第 13-19 行已声明该行为：

> C4 中 get_performance / get_signal_status / get_positions 基于监控推演的
> 「最新数据日期」状态——导入新行情后这三项会真实变化，属预期行为，
> 需重新 rebase（不做切片伪装稳定）；

实测漂移值：

```
$.C4_positions.date:                    '2026-08-25' != '2026-10-13'
$.C4_signal_status.last_rebalance_date: '2026-08-04' != '2026-10-09'
```

全库 `asset_prices` 最新一条为 `000300.SHA` / `date=2026-10-13`，写入时间 2026-11-06 10:59（CST），
与 `C4_positions.date` 的新值 `2026-10-13` 一致。

涉及链路：C4_nav_history 254 + C4_signal_status 128 + C4_positions 12 + C4_attribution 10 +
C4_performance 9 = **413 处**。

`C4_nav_history` / `C4_attribution` 虽然用固定切片日期（`NAV_END_DATE` / `ATTRIBUTION_DATE` = 2025-06-30），
但其上游净值序列由 `run_init` 推演产生，推演终点是行情最新日，因此仍会漂移。

### 根因 C：`get_model` 响应新增字段，基线未跟随（4 处，0.03%）

C4b 链路共 11 处差异，其中 **4 处属本根因**（「基线缺失该键」），字段为：

```
asset_selection_snapshot
preset_applied_at
preset_code
preset_version
```

其余 7 处为 `latest_backtest_summary.*`（`total_return` / `win_rate` 等），
该字段是 `StrategyModel` 上存的最近回测摘要（`app/models/strategy_model.py:344-348`），
其值随 fixture 回测结果变动，与五条回测链路同源，**归入根因 A**。
因此根因 A 为 12520（五链路）+ 7 = 12527 处。

这四个字段定义在 `app/schemas/strategy_model.py:127-134`（原型预设留痕），
以及 `app/services/strategy_preset_service.py:170-172`、`app/allocation/builtin_presets.py:569-571`。

对 `tests/regression/rebase_log/` 下全部 7 份文档（P0/P1/P3/P5/P6/P7/P8）检索
`preset` 与 `asset_selection_snapshot`，**匹配 0 处**——该批字段进入 `get_model` 响应
这件事在 rebase_log 中无任何登记。

旁证：`tests/_routes_baseline.txt` 与 `docs/DATA_ARCHITECTURE.md`、`docs/DATA_GOVERNANCE.md`、
`docs/DATA_IMPORT_SPEC.md`、`docs/DATA_INVENTORY_STRATEGY_ONBOARD.md`、`docs/DATA_SYSTEM.md`
六个文件的 mtime **同为 2026-11-06 08:30:11**（同一秒批量写入），
而 `golden_baseline.json` 仍是 2026-10-30 09:46:22。
即代码与文档在 10-30 之后有演进，黄金基线未跟随 rebase。

`tests/test_architecture_guard.py` 当前 **5 passed**（167s），说明路由面与 `_routes_baseline.txt` 是一致的，
差异仅在黄金回归基线一侧。

---

## 4. 为什么没有执行 rebase

四条理由：

1. 批次一约束明确「如果 `tests/regression` 当前有失败用例，立即中止并报告」，
   且禁止「为通过测试而修改断言或放宽基线」。rebase 即重写基线，属需单独授权的动作。
2. 项目既有惯例：`rebase_log/P8_bond_factor_score_index.md` 第 14 行写明
   「**未自行 rebase**，等基线 owner 决策」。
3. 项目**不是 git 仓库**（`git status` → `fatal: not a git repository`），
   `golden_baseline.json` 1,093,971 字节一旦被 rebase 覆盖即不可回退。
4. 根因 C 是未登记的代码语义变更。若现在 rebase，这四个新增字段会被写入基线，
   该变更从此不再有对照物。

---

## 5. 附带发现（仅记录，未修复）

按批次一约束「发现计划外的 bug 只记录不修复」，以下三项列入待用户决策清单：

**发现 1：fixture 7 个资产的交易日历口径不一致**

`000300.SH` 为真实 A股交易日历（359 天），其余 6 个资产为「区间内全部周一至周五」（390 天）。
`ZQGZ10` 是中国国债指数，2024-10-01 ~ 10-07 国庆休市期间在库内有行情记录，
`SPX` 是美股指数，同期为正常交易日，两者日期集却完全相同（双向差集为 0）。
组合回测中各资产按自身日期序列推进，日历不一致会造成资产间对齐错位。

**发现 2：`asset_prices` 写入未全量进审计**

`_import_audit_log` 共 15 条，其中 `target_collection = asset_prices` 仅 **1 条**
（2026-07-28 09:31:34，`quadrant_prices.xlsx`，87026 行）。
但实测 `000300.SH`（2026-11-02）、`ZQGZ10` 等 5 个资产（2026-08-28）、`HSTECH`（2026-07-29）
的写入时间在审计日志中**均无对应记录**。
审计日志的 `target_collection` 分布为：`trade_dates` 7 条、`factor_panel` 6 条、
`assets` 1 条、`asset_prices` 1 条。

**发现 3：`fixture.py:33` 的注释已与库内实际不符**

注释声明 7 个资产「均有完整行情（390 行）」，实测 `000300.SH` 为 359 行。
该注释是回归基线的口径说明，与实际不符会误导后续 rebase 判断。

**发现 4：`monitor_states` 有 17 条孤儿文档，且每运行一次回归 check 增加 2 条**

实测 `monitor_states` 共 49 条，由两类文档构成：

| 类别 | `monitor_id` 形态 | 条数 |
|---|---|---|
| 主状态 | 无后缀 | 20 |
| 模型口径状态 | `{monitor_id}::model` | 29 |

29 个模型口径状态的 base id 中，**17 个没有对应的主状态文档**。
20 个主状态 id 中 17 个存在于 `monitored_strategies`；29 个 base id 中仅 12 个存在于 `monitored_strategies`。

`::model` 后缀是生产语义，见 `app/services/monitor_service.py:881-884`：

```python
@staticmethod
def _model_track_state_id(monitor_id: str) -> str:
    """模型口径状态文档 ID（与主状态同集合，以 ::model 后缀隔离）"""
    return f"{monitor_id}::model"
```

漏删根因在 `tests/regression/fixture.py:97`：

```python
await db.monitor_states.delete_many({"monitor_id": {"$in": model_ids}})
```

按 `monitor_id` 精确等于 `model_ids` 匹配，能删掉主状态，删不掉带 `::model` 后缀的那条。

且该残留**不可自愈**：`fixture.py:100` 先按 `_regr_` 前缀删掉 `strategy_models`，
之后 `_regr_model_ids()` 再也查不到这些 id；孤儿文档的 `strategy_model_id` 字段又是 `None`，
因此后续任何一次 cleanup 都无法定位到它们，只会单调增长。

本次运行新增的 2 条（前序记录 `monitor_states` 为 47 条，运行 check 后为 49 条）：

| monitor_id | created_at | strategy_model_id | nav | day_count |
|---|---|---|---|---|
| `6aed636d600d3cb4ad3ebfe9::model` | 2026-11-06 13:21:53 | None | 1361.9760942312842 | 458 |
| `6aed64822064590f973f8f99::model` | 2026-11-06 13:27:14 | None | 1361.9760942312842 | 458 |

判定依据：两个 base id 在 `strategy_models` 中均已不存在（`count_documents` = 0）；
`created_at` 与本次 check 运行时刻吻合；两条 `nav` 与 `day_count` 完全相同，
对应同一个 fixture 监控实例（risk_parity 模型 live_publish 后 run_init）。

其余 15 条孤儿 `created_at` 早于今日，形态与上述漏删完全一致，
但来源需进一步确认（可能是历次回归运行，也可能是生产删除监控实例路径的同类漏删）。

影响：批次一后续 12 个步骤每步都要求跑回归验证，该缺陷不修则 `monitor_states`
将再累积约 24 条孤儿文档。本次未删除任何文档（批次一约束 #5 禁止删数据）。

---

## 6. 待用户决策

| # | 决策项 | 选项 |
|---|---|---|
| D1 | 是否 rebase 黄金基线 | (a) 立即 rebase，接受根因 A/B/C 三类差异一并写入新基线；(b) 先统一 fixture 7 个资产的日历口径（需写 `asset_prices`，批次一约束 #5 禁止），再 rebase；(c) 先确认根因 C 的 4 个 preset 字段是否为有意引入，再 rebase |
| D2 | 根因 C 的 4 个字段 | 确认 `preset_code` / `preset_version` / `preset_applied_at` / `asset_selection_snapshot` 进入 `get_model` 响应是否为预期，并补一份 rebase_log 登记 |
| D3 | 附带发现 1（日历口径不一致） | 是否需要在批次一之外单独立项处理 |
| D4 | 附带发现 2（审计缺口） | 是否需要排查绕过 `_import_audit_log` 的 `asset_prices` 写入通道 |
| D5 | 附带发现 4（`fixture.cleanup()` 漏删 `::model`） | (a) 授权修 `fixture.py:97` 的删除条件（属改回归测试代码，不在批次一 13 个步骤范围内）；(b) 授权清理库内 17 条孤儿文档（属删数据，批次一约束 #5 禁止）；(c) 暂不处理，接受批次一后续每步 +2 条 |

2026-11-06 决策结果：

- **D1** 采用「落盘已知差异清单 + 调整后续门禁」方案，**不 rebase**，`golden_baseline.json` 不动（见 §8）
- **D2** 结论：4 个 preset 字段属有意引入（见 §8.1）
- **D5** 已授权修复 `fixture.py:97`（见 §8.2）
- **D3 / D4** 登记为单独立项，本批次不处理（见 §7）

---

## 7. 单独立项清单（批次一结束后单独立项，不在本批次处理）

### D3｜fixture 7 个资产的交易日历口径不一致

区间为 `fixture.py:22-23` 的 2024-01-02 ~ 2025-06-30。实测各资产区间内条数：

| 资产 | 条数 | 日历口径 |
|---|---|---|
| 000300.SH | 359 | 真实 A股交易日历（已剔除 31 个法定休市日） |
| ZQGZ10 | 390 | 区间内全部周一至周五，未剔除节假日 |
| GLD | 390 | 同上 |
| SHCU | 390 | 同上 |
| SPX | 390 | 同上 |
| UST10 | 390 | 同上 |
| HSTECH | 390 | 同上 |

390 = 545 个自然日 ≈ 78 周 × 5 个工作日。`ZQGZ10` 与 `SPX` 的日期集完全相同
（双向差集为 0），但 `ZQGZ10` 是中国国债指数，2024-10-01 ~ 10-07 国庆休市期间不应有行情。

待处理内容：

1. 确认其余 6 个资产是否也需按各自市场的真实交易日历重建
2. 确认组合回测在资产间日历不一致时的对齐行为是否符合预期
3. 重建后需同步修正 `fixture.py:33` 的「390 行」注释，并重新 rebase 黄金基线

### D4｜`asset_prices` 写入未全量进 `_import_audit_log`

`_import_audit_log` 共 15 条，`target_collection` 分布：

| target_collection | 条数 |
|---|---|
| trade_dates | 7 |
| factor_panel | 6 |
| assets | 1 |
| asset_prices | **1** |

唯一一条 `asset_prices` 记录为 2026-07-28 09:31:34（`quadrant_prices.xlsx`，87026 行，
`import_mode=upsert`，`operator=script:seed_prices`）。

但以下写入时间在审计日志中**均无对应记录**：

| 对象 | ObjectId 写入时间（CST） |
|---|---|
| 000300.SH（区间内 359 条） | 2026-11-02 15:11 |
| ZQGZ10 / GLD / SHCU / SPX / UST10 | 2026-08-28 10:57 |
| HSTECH | 2026-07-29 17:20 |
| 全库最新一条（`000300.SHA`，date=2026-10-13） | 2026-11-06 10:59 |

待处理内容：排查绕过 `_import_audit_log` 的 `asset_prices` 写入通道，
确认是导入脚本未接审计，还是存在其他写入路径。本次差异归因受此影响：
无法从审计日志直接确认 2026-11-02 对 `000300.SH` 的写入是谁、通过什么通道做的，
只能依靠 ObjectId 时间戳与日期集反推。

---

## 8. 决策执行结果（2026-11-06）

### 8.1 D2｜preset 四字段属有意引入

读 `app/models/strategy_model.py` 全文（410 行）确认：4 个字段在 `StrategyModel`
类中**全部有持久化定义**，位于 271-283 行，带独立分组注释（第 270 行：
「原型预设来源（只记录应用痕迹，不存预设定义）」）：

| 字段 | 行号 | 类型 | 默认值 |
|---|---|---|---|
| `preset_code` | 271 | `Optional[str]` | `None` |
| `preset_version` | 272-274 | `Optional[str]` | `None` |
| `preset_applied_at` | 275 | `Optional[datetime]` | `None` |
| `asset_selection_snapshot` | 276-283 | `Optional[Dict[str, Any]]` | `None` |

**判定：有意引入**，五层实现齐全：

| 层 | 位置 | 内容 |
|---|---|---|
| model | `app/models/strategy_model.py:270-283` | 4 字段持久化定义；`asset_selection_snapshot` 的 description 写明七个子键 `{mode, tags, group_rules, groups, expanded_at, expanded_codes, applied_hash}` 与「标签模式的池子在应用时展开为快照，后续标签变更不自动同步」 |
| schema | `app/schemas/strategy_model.py:127-134`（Create）、`185-191`（Update） | 对应字段，注释「前端只需传 preset_code，其余三项由服务层写入」 |
| service | `app/services/strategy_preset_service.py:802-838` | `stamp_preset_trace()`，含四条业务规则：`preset_version` 一律按当前预设定义重算、不采信前端传值（理由：否则改过预设后旧模型会被伪造的版本号掩盖，`preset_outdated` 永不触发）；`preset_applied_at` 只在预设变更时刷新；`applied_hash` 保留前端应用那一刻的指纹作为「应用后是否被手动调整」的基准；显式清除预设时同步清空留痕 |
| API | `app/api/strategy_model.py:135-139`（create）、`390-400`（update） | 两条路径均调用 `stamp_preset_trace()`；update 带 `previous_preset_code` 参数做变更判断 |
| 测试 | `tests/test_strategy_preset_service.py:330-386` | 5 个用例：重算 version、忽略前端传值、变更时刷新 applied_at、清除时清空留痕、未知 preset 报错 |

库内实证：`strategy_models` 38 条中 **7 条同时含这 4 个字段且全部非 null**
（7/38 = 18.4%，与 `docs/_baseline_fields.md` 中 `asset_selection_snapshot` 的出现率吻合），
证明字段有真实写入路径且成组写入，非死字段。

补充：`app/services/strategy_model_service.py` 中**零处**引用这 4 个字段。
写入点在 API 层调用 `stamp_preset_trace()` 后随 `model_data` 落库，不经 `strategy_model_service`。

**结论**：根因 C 的 4 处差异属「功能上线后未 rebase 黄金基线」，
且 `rebase_log/` 全 7 份文档零处登记，属**登记缺口**而非代码问题。
待补：一份记录该批字段引入的 rebase_log。

### 8.2 D5｜`fixture.py:97` 漏删修复

改动前后对照（`tests/regression/fixture.py` 的 `cleanup()`）：

```python
# 改动前（单行）
await db.monitor_states.delete_many({"monitor_id": {"$in": model_ids}})

# 改动后（两行代码 + 四行说明注释）
# monitor_states 中同一监控实例有两条文档：主状态（monitor_id）与模型口径状态
# （monitor_id + "::model"，见 app/services/monitor_service.py:881-884）。
# 只按裸 monitor_id 删会漏掉 ::model 那条，而下面删完 strategy_models 后
# _regr_model_ids() 再也查不到这些 id，漏删的文档将永久残留。
monitor_ids_to_delete = list(model_ids) + [f"{m}::model" for m in model_ids]
await db.monitor_states.delete_many({"monitor_id": {"$in": monitor_ids_to_delete}})
```

`cleanup()` 其余六行删除语句（`backtest_records` / `strategy_live_change_logs` /
`strategy_param_versions` / `portfolios` / `strategy_models`）未动。

复跑验证结果：

| 项 | 修改前 | 修改后 | 判定 |
|---|---|---|---|
| DIFF 总数 | 12944 | 12944 | 变化 0，在 ±5 内 |
| 差异集合逐条比对 | — | 新增 0 / 消失 0 / 类型变化 0 | 逐条完全相同 |
| `by_chain` 分布 | 见 §2.1 | 与 §2.1 逐链路一致 | 无变化 |
| `strategy_models` | 38 | 38 | 无残留 |
| `backtest_records` | 62 | 62 | 无残留 |
| `monitor_states` | 49 → 51（每次 check +2） | 49 → 49（+0） | **修复生效** |
| `_regr_` 模型残留 | 0 | 0 | — |
| `orphan_model_only` | 17 | 17 | 既有孤儿按决策保留 |

### 8.3 门禁调整

S02 及后续步骤的回归门禁改为：

1. 跑 `py -3 tests\regression\run_regression.py check *> logs\_regression_stepXX.log`
2. 跑 `py -3 scripts\regression_drift_report.py compare logs\_regression_stepXX.log`
3. 判定：**新增差异数必须为 0**（GATE PASSED，返回码 0）；
   消失差异与差异类型变化允许存在，但必须能解释并记录到该步输出

差异身份键为 `(chain, path)`，不含 `old` / `new` 具体值。
已知差异清单：`logs/_known_drifts_S01.json`，说明文档：`docs/_known_drifts_S01.md`。

工具已完成双向验证：正向（清单来源日志）GATE PASSED / 返回码 0；
交叉（D5 修改前的 UTF-8 日志）GATE PASSED / 返回码 0；
负向（3 条已知 + 1 条伪造 path）新增 1 / GATE FAILED / 返回码 1。

### 8.4 本次执行对库内的影响

| 集合 | S01 中止报告时 | 本次执行后 | 说明 |
|---|---|---|---|
| `strategy_models` | 38 | 38 | 无变化 |
| `backtest_records` | 62 | 62 | 无变化 |
| `monitor_states` | 49 | 49 | 中途因上次 check 被中断一度为 51（`_regr_` 脏数据 6 个模型未清），本次 `create()` 内置的 `cleanup()`（`fixture.py:192`）配合 D5 修复已恢复至 49 |

`golden_baseline.json` 未动（mtime 2026-10-30 09:46:22，1,093,971 字节，
SHA256 `92280BD5A28FC3A2ABFBD8227A3CDD0B80869E7FFF2F06A8DF6B13B731386E83`，
与 `_baseline_fields.md` 记录的冻结时哈希一致）。
既有 17 条孤儿文档按决策保留，批次一结束后一次性清理。
孤儿判定口径已复核：`monitor_id` 是监控实例 id（生产数据中 0 条等于 `strategy_models._id`），
故孤儿的判据是「`::model` 的 base id 在 20 条主状态中无对应文档」，
29 条模型口径状态 = 12 条有主状态 + 17 条孤儿。
业务代码（`app/` 下）本次**零改动**，唯一代码修改为 `tests/regression/fixture.py` 的 `cleanup()`。

---

## 9. 归因修正（2026-11-06，经决定性实验）

### 9.1 修正的触发

并行推进的另一条工作线「回测引擎演进 批次一 S1–S5」对**同一批 12944 处 diff** 独立做了归因，
产出 `docs/_a14fa13_change_log.md`，结论是 HEAD 提交 `a14fa13` 改了回测内核口径但未 rebase 基线，
并在其 §4.3 明确「排除『数据区间漂移』这一类解释」。

两条线结论互斥（本文原 §3 根因 A 主张数据漂移），因此做了一次决定性实验。

### 9.2 git 事实（本文原 §3 完全缺失的证据链）

⚠ **踩坑记录（归因出错的直接原因之一）**：git 仓库位于 `portfilio-end/` 子目录，
不在 `d:\project\portfilio\` 根目录。从根目录跑 git 得到 `fatal: not a git repository`，
本文原 §3 因此只靠文件 mtime + ObjectId 时间戳做时间线，**没有提交级证据**。

| 事实 | 值 | 取证命令 |
|---|---|---|
| 回归基线最后一次改动 | `d408639`（2026-10-29 14:37） | `git log -1 -- tests/regression/golden_baseline.json` |
| 当前 HEAD | `a14fa13`（2026-11-05 16:56） | `git rev-parse --short HEAD` |
| `a14fa13` 是否 rebase 过基线 | **否**，只往 `tests/regression/` 加了 `dividend_garp_recon_equity.csv`（1390 行） | `git show --stat a14fa13 -- tests/regression/` |
| preset 四字段由哪个提交引入 | **`a14fa13`**（`git log -S` 唯一命中） | `git log --oneline -S "preset_applied_at" -- app/models/strategy_model.py` |

基线冻结于 `d408639`、HEAD 是 `a14fa13`、`a14fa13` 未 rebase——**基线已过期一个提交**，
这与本文原 §3「基线冻结后数据被改」是两个独立的变量，原 §3 只查了后者。

### 9.3 决定性实验：167 处键存在性差异的形态

把 167 处键差异按叶子字段归类（数据源：`logs/_known_drifts_S01.json`）：

| 叶子字段 | 处数 | 方向 | 形态 |
|---|---|---|---|
| `ZQGZ10` | 87 | baseline_missing 51 / current_missing 36 | C1a/C1b 的 `current_missing` 落在 index 195/218/239/261/284/304/325/347/369，**间隔 20–23 天＝月度调仓点**；C2 的 `baseline_missing` 是 `snapshots[109..151]` **连续 43 处** |
| `SH`（即 `000300.SH`，路径含点被叶子切分截断） | 26 | 全部 baseline_missing | C2b `snapshots[17..42]` **连续 26 处** |
| `weights`（整键） | 14 | baseline_missing 8 / current_missing 6 | C3a 散点 |
| `n_trades` / `total_commission` / `total_slippage` / `turnover` | 36（4×9） | 全部 baseline_missing | 成本与换手类**新增响应字段** |
| preset 四字段 | 4 | 全部 baseline_missing | C4b |
| 合计 | **167** | | |

**三个判据全部指向代码变更，全部否证数据漂移：**

1. **日历轴未变**：`golden_baseline.json` 中 C1a/C1b/C3a 的 `equity_curve` 长度均为 **390**
   （首末 `2024-01-02 .. 2025-06-30`），而当前输出**无 `equity_curve` 的 `list_length` 差异**
   → 当前也是 390。`000300.SH` 少 31 天并未缩短回测序列（日期轴由其余 6 个 390 天资产决定）。
2. **调仓变多而非变少**：7 条 `list_length` 差异全部是当前**多于**基线——
   `trades` 129→131、57→59、1472→1490、111→113，`weight_history` 12→14，`rebalance_history` 21→22。
   「日历变短」的预期后果是调仓变少，方向相反。
3. **`000300.SH` 键差异的方向与分布都不对**：26 处全是「基线缺失该键」（当前**多出**该键），
   且是 `snapshots[17..42]` 一段**连续区间**（≈ 2024-01 下旬至 2024-03 上旬）。
   若真是 31 个假日无行情，应表现为**散落在 31 个假日日期上的「本次输出缺失该键」**，实测**为零**。
   连续区间 + 起算日位移，是 `data_feed` 的 lookback／最小历史天数口径变化的特征。

补充：ZQGZ10 的 9 个 `current_missing` index 换算成日期后全为**月初首个交易日**
（2024-10-01、11-01、12-02、2025-01-01、02-03、03-03 等），
对应 `composition_builder.py` 的 `force_month_end` 修正（月初/月末错位）。

### 9.4 修正后的根因

| 根因 | 条数 | 修正后归因 | 与原文的关系 |
|---|---|---|---|
| A | 12527 | **`a14fa13` 改了回测内核口径但未 rebase 基线**：分资产费率与 `invest_value` 净额配平（`execution.py`）、`force_month_end` 修正与 `_resolve_declared_execution_delay`（`composition_builder.py` / `rebalance_planning.py`）、`_run_daily_settle` 并入 close（`engine.py`）、lookback 与最小历史天数（`data_feed.py`）、母层计成本（`portfolio_backtest_monitor.py`） | **原归因（数据漂移）已证伪** |
| B | 413 | 监控推演最新日随行情推进（`chains.py:13-19` 声明属预期） | **不变，仍为真** |
| C | 4 | `get_model` 响应新增 4 个 preset 留痕字段——**git 已证实由 `a14fa13` 引入** | 结论不变，**定性精确到提交**（与 A 同源） |

即：12944 = **`a14fa13` 未 rebase（12531 处，A+C）** + **监控推演日漂移（413 处，B）**。

### 9.5 尚未做到的部分（诚实声明）

- 上述为**机制级 + 形态级**归因：已用 git 证实改动内容与提交时点，已用 167 处键差异的
  方向/连续性/日期分布排除数据漂移，但**未把 12770 处 `value_mismatch` 逐条回溯到具体代码行**。
- `000300.SH` 在 2026-11-02 被重写为 359 条是**真实发生的数据变更**，只是未对回归输出产生
  可归因差异。它与 `a14fa13` 是两个独立变量，**尚未做变量分离**。
- 分离方法（`_a14fa13_change_log.md` §4.3 已提出，本文认可）：在 `d408639` 与当前 HEAD
  两个 checkout 上各跑一次 `run_regression.py check`，比对两份 diff 集合的差集。
  **代价**：需 stash 工作区 3 处未提交改动、需切 checkout、每跑一次写库，
  属需单独授权的动作，S01 未执行。

### 9.6 对 `_known_drifts_S01.json` 的影响

清单中 12527 条 item 的 `root_cause` 字段值为 `"A"`，其**文字描述**
（`root_cause_desc.A`＝「000300.SH 区间行情日历口径变更」）现已作废。

**但不影响门禁可用性**：`regression_drift_report.py` 的差异身份键是 `(chain, path)`，
`root_cause` 仅作展示与分组，不参与新增/消失判定。`by_root_cause` 的**条数划分仍然正确**
（A/B/C 的条数边界没变，变的只是 A 与 C 的解释）。
重新 freeze 会改变 `generated_at` 并使 `docs/_known_drifts_S01.md` 记录的交叉验证失效，
收益低于代价，故**不重新 freeze**，以本节为准。

### 9.7 同时发现的另一条线文档缺陷

核对 `_a14fa13_change_log.md` 时发现两处需修正（该文不属本工作线交付物，**未代改**）：

1. **§4.2 的类型分布写错**：文中 `value` = 12777、`list_length` = **0**，
   并以「`list_length` 为 0 说明回测区间与序列长度没变」作为排除数据漂移的依据。
   实测两份日志（本文的 `_regression_post_D5.log` 与该文用的 `_gate3_regression.txt`）
   类型分布**完全一致**：`value_mismatch` 12770 / `baseline_missing_key` 125 /
   `current_missing_key` 42 / **`list_length` 7**，合计 12944。
   即 7 条 `list_length` 被误归入 `value`（12770 + 7 = 12777）。
   **该文的排除结论因此不成立**（虽然结论方向恰好正确——真正排除数据漂移的是 §9.3 的三个判据，
   不是 `list_length`）。另 §4.2 称键差异「主要是 ZQGZ10，87 处…`SH` 26 处」，
   其中 `SH` 是路径按 `.` 切分把 `000300.SH` 截断的产物，应标注为 `000300.SH`。
2. **§5 的快照 SHA256 与大小已过期**：文中记 `f87a1790…` / 2,159,848 字节，
   实测 `logs/_regression_snapshot_S1.json` 为 `9b511a37c24ba7f3b490dffa0c63d5d206ab26d4605098b3a1475452b6d25ebc` /
   2,160,016 字节（mtime 16:30:53，晚于文档）。快照在文档写完后被重建过。

**快照守卫本身已验证可用**：`snapshot_guard.py check` 对 `_gate3_regression.txt` 自比对
输出 `SNAPSHOT GUARD OK`、exit 0，三层（计数/路径/值）全零，
且逐链路分布与本文 `_known_drifts_S01.json` **完全一致**
（3801/3560/1778/1778/1603/254/128/12/11/10/9）。
说明两条线冻结的是**同一批 12944 处 diff**，两套门禁工具可互为交叉验证。


---
