# P6 独立策略统一接入管道：回归基线重建记录

日期：2026-10-22
阶段：P6（独立策略统一接入管道 + 首个实例 nous_low_vol）

## 1. 为什么必须 rebase

进入本阶段前执行 `run_regression.py check`，harness **直接跑不完**（在
`fixture.create()` 阶段抛 `ValueError: 仅已发布模型可以实盘发布，请先发布`）。
排查确认基线 `golden_baseline.json`（2026-08-11 写入）相对当前生产语义与当前
库内数据已全面过期，共 11973 处差异，三个**互相独立**的成因：

| # | 成因 | 证据 | 与本次改动的关系 |
| --- | --- | --- | --- |
| 1 | 生产代码收紧：`live_publish_service.live_publish_model` 要求 `status == PUBLISHED` 且 `published_snapshot` 非空；组合回测据此走「发布快照」分支 | 旧基线 `C4b_model_live.status = '草稿'`、`published_version = None`、`published_snapshot = {}`，而 `live_publish_enabled = True`、`live_version = 1` —— 该组合只可能在两道校验存在之前生成 | 无关（校验早于本阶段落地） |
| 2 | 库内行情推进：基线之后又导入了新行情，监控推演多出一个月的调仓 | `C4_signal_status.last_rebalance_date` `2026-07-02 → 2026-08-04`、`rebalance_history` 长度 `20 → 21`、`C4_nav_history[1..127].nav/daily_return` 全量漂移、`latest_backtest_summary` 八项全变 | 无关（`chains.py` 模块 docstring 已声明此为「预期行为，需重新 rebase」） |
| 3 | 生产模型新增字段 | `C4b_model_live.config_fingerprint`、`live_published_version`、`live_snapshot.{asset_names, asset_selection_count, controller_code, controller_parameters, enable_momentum_selection, ...}` 均报「基线缺失该键」 | 无关 |

按链路分布（旧基线 vs 修复后当前输出）：

| 链路 | 差异数 |
| --- | --- |
| C1a_portfolio_by_id | 1272 |
| C1b_portfolio_by_model | 1272 |
| C2_run_by_model | 3539 |
| C2b_run_by_model_trend | 3801 |
| C3a_quadrant_backtest | 1638 |
| C4_nav_history（127 个切片 × 2） | 254 |
| C4_performance / C4_positions / C4_signal_status / C4_attribution | 9 / 14 / 129 / 12 |
| C4b_model_live | 33 |
| **合计** | **11973** |

## 2. 本次改动对存量策略逐字节惰性（A/B 对照）

计划要求「回归基线四链路（C1-C4b）必须逐字节不变；F 层改动
`composition_pipeline` 短路条件后重点核对，任何偏差都说明
`has_native_vol_control()` 默认值被破坏」。由于旧基线本身不可复现，改用
**同库同刻 A/B 对照**给出更强的证据：

- **A**：本次改动全部生效（四处运行前门禁 + F 层自带风控放行 + E 层日历口径
  可声明 + allocator 自声明键放行规则）
- **B**：用 monkeypatch 把上述四项能力逐一退回改动前行为
  - `DataContract.is_empty → True`（四处门禁全部走「空契约快速返回」分支，
    等价于门禁不存在，见计划 D 层「空契约时四处门禁全部快速返回」）
  - `CompositionPipeline._allocator_has_native_vol_control → False`
    + `BaseStrategyModel.has_native_vol_control → False`（F 层短路条件退回）
  - `composition_pipeline._filtered_param_keys → _SELECTION_PARAM_KEYS`
    （参数放行规则退回）
  - `coerce_trade_dates` 忽略第三参 `source`，恒用 `trade_dates`（E 层退回）；
    同时替换 `app.monitor.monitor_query` / `app.services.monitor_service`
    两处 `from ... import` 绑定

两次独立进程各自 `boot → fixture.create → chains.run_all → fixture.cleanup →
_normalize`，输出 JSON 用 `compare.walk_diff` 对比：

```
AB_IDENTICAL
```

**0 处差异**（含 `frozen_at` 纳入易变字段后）。即本次新增能力对存量
risk_parity / mean_variance / manual_allocation / trend_cross_sectional /
四象限组合 / 监控五读端 / 实盘互通字段的全部输出逐字节不变。

补充：`_filtered_param_keys` 的放行范围经逐策略核对（13 个 manifest 条目），
仅 `nous_low_vol` 放行 `sharp_windows` / `tie_break_window` 两键，其余 12 个
存量 allocator 的过滤集合与 `_SELECTION_PARAM_KEYS` **完全相等**；
`calendar_source` / `preserve_price_gaps` / `inception_weights` 等 Pipeline
控制键即使被 `model_level_param_group()` 声明也仍恒过滤。

## 3. harness 修复

`tests/regression/fixture.py` 新增 `_publish_all()`，在 `create_portfolio` 与
`live_publish_model` 之前发布 6 个 fixture 模型（risk_parity / mean_variance /
manual_equal / trend_cs / portfolio_fixed / portfolio_quadrant）。fixture 走
同一套生产服务层代码，因此必须复现前端「建模 → 发布 → 实盘发布 → 监控」的
真实链路；发布失败直接 `RuntimeError`，不静默跳过。

## 4. 比对器修订

`tests/regression/compare.py` `VOLATILE_KEYS` 增 `frozen_at`。理由：
`live_snapshot.frozen_at` / `published_snapshot.frozen_at` 是快照冻结的墙钟
时间，每次运行必变，属文件头 docstring 已声明的准入标准「落库时间戳」；
不纳入则 rebase 后的基线永不可复现。净值、权重、绩效指标字段一律未动。

## 5. 双闸门

| 闸门 | 结果 |
| --- | --- |
| `python -m pytest tests/ -q` | **205 passed, 1 skipped** |
| `python -m tests.regression.run_regression rebase` | REGRESSION REBASED |
| `python -m tests.regression.run_regression check` | **REGRESSION IDENTICAL** |

守卫断言均未修改：`test_backtesting_boundary.py`（`data_contract.py` 在
`app/backtesting/` 内且不 import 上层模块）、`test_architecture_guard.py`
（含 `test_route_surface_matches_baseline`）、`test_schema_consistency.py`
（含 `test_selection_param_keys_complete`、`test_allocator_no_selector_params`）
全部通过。

> 环境注意：PowerShell 下必须设 `$env:PYTHONIOENCODING='utf-8'` 与
> `$env:PYTHONUTF8='1'`，否则 `template_init_service` 输出的 `✓` 触发
> `UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'`；
> loguru 写 stderr 会让 `$LASTEXITCODE` 呈现假失败，以末行标记为准。
