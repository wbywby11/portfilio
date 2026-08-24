# P5 端到端验证记录（四象限 + GMSI2）

日期：2026-08-12
阶段：P5（四象限与 GMSI2 端到端验证）

## 1. 四象限组合：监控 == 回测

验证脚本：`scripts/verify_quadrant_monitor_e2e.py`（回归 fixture 的
`_regr_portfolio_quadrant` 模型：signal_driven + T+2 + quadrant_strategy_map，
区间 20240102 ~ 20250630，commission=0.00015）。

两条路径：

1. 组合监控管线 `app.monitor.portfolio_backtest_monitor.run_portfolio_monitor_pipeline`
2. 组合回测路径（run-portfolio 端点同一套构建块：子策略回测 +
   `build_quadrant_weight_components` + `run_composite_unified` + 产品层）

| 项 | 结果 |
| --- | --- |
| 日历一致性 | 390 个交易日完全一致 |
| 逐日 NAV 最大偏差 | **0.000e+00（相对 0.000e+00）** |
| 调仓次数 | 12（事件驱动 T+2） |
| 绩效 | ann_ret=16.0413%，ann_vol=8.1630%，sharpe=1.720，mdd=-4.5154% |
| 期末 NAV | 1249.3106（基准 1000.0） |

结论：**[PASS] 四象限组合监控 == 回测（同区间逐日完全一致）**。
fixture 验证后已幂等清理。

## 2. GMSI2 原型数值验收

验证入口：`tests/regression/test_prototype_alignment.py`（清单
`tests/regression/manifests/gmsi2.yaml`：corr_min=0.94，end_err_max=5%；
窗口 20140103 ~ 20260610，固定终点可复现）。

- 子策略层：`PortfolioService._run_sub_strategy_backtest` 逐层跑库内
  GMAP（vol_scaled_budget）/ GCMI（trend_cross_sectional）模型；
- 母组合层：`run_composite_unified`（60/40 monthly + 母层 vol 控制
  target=3%、ewma、short=20/long=60，对齐原型 use_mother_vol_control 口径）。

对账表（系统 NAV 与原型基线各自归一到公共区间首日=1）：

| 层级 | 天数 | 收益相关 | 端点误差 | 最大偏差 | 系统端点 | 原型端点 | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GMAP | 3020 | 0.9501 | 3.20% | 0.0501 | 1.4714 | 1.5200 | PASS |
| GCMI | 3021 | 0.9976 | 1.21% | 0.0262 | 2.1009 | 2.0757 | PASS |
| PORTFOLIO | 2614 | 0.9676 | 1.78% | 0.0473 | 2.0895 | 2.1274 | PASS |

结果：`1 passed`（pytest，2026-08-12，迁移到测试侧清单解析后复验通过）。

## 3. 架构调整（用户反馈驱动）

onboarding 只是临时脚本，不作为系统架构组件；GMSI2 模型是前端策略建模
产出的配置实例（后续经前端操作配置）：

- 删除 `app/allocation/onboarding/` 与项目根 `manifests/`；
- 清单解析迁至 `tests/regression/prototype_manifest.py`，清单文件迁至
  `tests/regression/manifests/gmsi2.yaml`（均为回归测试侧资产）；
- 验收测试改从 `regression.prototype_manifest` 导入；模型缺失时报错指引
  经前端创建同名模型；
- 详见 `docs/backtesting计算引擎架构.md` 第 7 节与 `P1_onboarding.md` 勘误。

## 4. 双闸门

| 闸门 | 结果 |
| --- | --- |
| `python -m pytest tests --ignore=tests/regression -q` | 92 passed |
| `python tests\regression\run_regression.py check` | REGRESSION IDENTICAL |
| `python -m pytest tests\regression\test_prototype_alignment.py -q` | 1 passed |
| `python scripts\verify_quadrant_monitor_e2e.py` | [PASS] 监控 == 回测 |
