# P0 日历锚定 —— rebase 归因报表

- **日期**：2026-08-11
- **阶段**：P0（5.1 信号日全历史分组 + 窗口不变式守卫）
- **变更**：`app/backtesting/schedule.py` `ScheduleResolver.resolve_signal_dates`
  由「先按 [start,end] 切片再分组」改为「全历史日历分组得到全量信号日（缓存）→ 按 [start,end] 过滤」；
  新增 `tests/test_schedule_invariant.py`（66 项断言，含行情日历与命名日历两套路径 × 6 种频率）。

## rebase 前 diff（共 5 处，全部归因于切片 artifact 消除）

| # | 路径 | golden（旧行为） | 现值（新行为） |
|---|---|---|---|
| 1 | `C2_run_by_model.data.snapshots[0].rebalance_reason` | `周期性调仓` | `期初建仓` |
| 2 | `C2_run_by_model.data.snapshots[0].rebalance_type` | `regular` | `期初建仓` |
| 3 | `C2_run_by_model.data.trades[0].rebalance_label` | `周期性调仓` | `初始化仓位` |
| 4 | `C2_run_by_model.data.trades[1].rebalance_label` | `周期性调仓` | `初始化仓位` |
| 5 | `C2_run_by_model.data.trades[2].rebalance_label` | `周期性调仓` | `初始化仓位` |

## 归因

- **根因**：旧实现先切片后分组，回测窗口首日必被判为月度信号日（幽灵调仓）。
  C2（risk_parity，monthly）窗口首日同时命中 `first_bar_in_range` 与幽灵信号日，
  引擎按"常规调仓"分支标记 `rebalance_type=regular`。
- **新行为**：窗口首日不再是信号日，引擎走量化策略期初建仓分支
  （`engine.py` L522-530），归因标签变为 `期初建仓 / 初始化仓位`。
- **数值影响**：零。期初建仓权重与常规调仓同样由 `generate_target_weights` 产出，
  全部净值、权重、绩效指标逐项一致（compare 容差 1e-12 下除上述 5 处标签外无任何 diff）。
- **结论**：预期内的语义修正，已 rebase 黄金基线；rebase 后 `REGRESSION IDENTICAL`。

## 验证清单

- [x] `tests/test_schedule_invariant.py` 66 项通过（G8/W1 窗口不变式）
- [x] `tests/test_backtesting_boundary.py` + `tests/test_schema_consistency.py` 13 项通过
- [x] 回归 check：rebase 前 5 处 diff 全部归因；rebase 后 REGRESSION IDENTICAL
