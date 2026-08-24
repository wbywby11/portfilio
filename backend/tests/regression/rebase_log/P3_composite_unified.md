# P3 组合路径切换统一引擎 · 退役 composite_engine

日期：2026-08-11
阶段：策略体系边界与引擎收束 P3

## 1. 变更内容

| 项 | 变更 |
| --- | --- |
| 删除 | `app/backtesting/composite_engine.py`（NAV 级复合第二套计算路径） |
| 搬迁 | `PortfolioBacktestResult` / `_performance_from_nav` → `app/portfolio/composite_runner.py` |
| 切换 | 组合回测 API（`backtests.py` run-portfolio / run-portfolio-by-id）、组合监控（`portfolio_backtest_monitor.py`）、`portfolio_service.py`（create_from_portfolio_model / `_run_composite`）、`sim_trade_engine.py`（PORTFOLIO_MODEL 推进）全部改经 `run_composite_unified` |
| 归因 | `portfolio_analytics` 输入改为新引擎的 `sub_contributions` 序列（T-1 收盘权重 × 子资产收益，可加性闭合） |
| 边界 | `test_backtesting_boundary.py` 移除 `composite_engine→weight_models` 白名单，新增 `test_composite_engine_retired`（文件不得复活 / 全仓无导入残留 / 组合编排必须经 run_unified + 合成资产价格构建） |
| facade | `app/backtesting/__init__.py` 移除 `run_portfolio_backtest`，新增 `build_synthetic_prices` |

## 2. 数值归因（rebase 前 check 共 2180 处差异）

| 链路 | 差异数 | 归因 |
| --- | --- | --- |
| C2（risk_parity 单策略） | 0 | 单策略路径零变化 |
| C2b（trend_cs 单策略） | 6 | 仅标签：首日快照 `rebalance_type` 由 `regular` 恢复为 `期初建仓`（P2 引擎优先级契约修复的直接结果，数值逐位不变） |
| C1a / C1b（固定权重组合） | 各 712 | 漂移口径：旧路径 `w_series.shift(delay)` 叠加逐日漂移后 t 日实际用 t-2 收盘市值权重，比严格市值漂移滞后一天；新路径为引擎内真实市值漂移（详见 `docs/组合适配统一引擎双跑比对报告.md`） |
| C3a（四象限组合） | 750 | 同上漂移口径；另 `weight_history` 11≠12 与 `win_rate` 0.8→0.727：旧路径 rebalance_dates 记**信号日**（含区间尾部落空未执行的信号），新路径只标记**实际执行**的调仓日 |

双跑量化（P2 真实数据 GMSI2 母组合 2614 天）：锚点归一后最大逐日相对差
2.8e-3、均值 1.6e-3、收益相关 0.999963、调仓日 130/130。

## 3. 闸门结果

| 闸门 | 结果 |
| --- | --- |
| `py tests\regression\run_regression.py rebase` | `REGRESSION REBASED` |
| `py tests\regression\run_regression.py check` | `REGRESSION IDENTICAL` |
| `py -m pytest tests --ignore=tests/regression -q` | 88 passed（含边界守卫 + 组合语义守卫 5 用例） |

## 4. 遗留

- `tests/regression/test_prototype_alignment.py` 的清单解析已迁至测试侧
  `tests/regression/prototype_manifest.py`（原 `app/allocation/onboarding`
  已按用户反馈删除，见 P1 勘误）；原型对账链路在 P5 端到端验证阶段跑通。
- GMSI2 原型基线（`gmsi2_replication/gmsi2_baseline_nav.csv`）按旧漂移口径
  生成；新路径为严格市值漂移，P5 核对时以双跑报告的容差口径为准。
