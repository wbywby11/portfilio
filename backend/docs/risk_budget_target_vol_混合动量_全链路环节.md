# risk_budget_target_vol 混合动量策略 — 全链路环节

从**资产选择** → **权重计算** → **调仓实施** → **净值计算** → **最终收益率计算** 的完整代码链路说明。

**【重要】** 本全链路**仅应用于** `risk_budget_target_vol` 的混合动量资产选择策略，**不应用于**其他任何策略。其他策略使用通用 `BacktestEngine`。

---

## 一、整体流程概览

```
prices (价格数据)
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Step1: 资产选择 (每月末)                                                     │
│  app/selection/step_files/step1_asset_selection.py                          │
│  select_assets_for_date() → 动量7 + 反转1 → 最终入选 + 入选矩阵_row            │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Step2: 权重计算 (每月末)                                                     │
│  app/selection/step_files/step2_weight_calculation.py                       │
│  calc_weights_for_date() → 风险预算 → 初始权重 → 缩放 → 截断 → 最终权重        │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Step3: 调仓实施 + 净值计算 (T+2 执行日 + 每日循环)                            │
│  app/selection/step_files/step3_backtest_fx_v1.py (源自 动量策略相关资料)     │
│  run_backtest_fx_inmem() → 汇率、波动率监控、交易/复制成本                     │
│  FX 加载：fx_rates > fx_df > data/fx.xlsx（回退，失败则禁用汇率）              │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  最终收益率计算                                                              │
│  app/backtesting/analytics.py                                               │
│  PerformanceAnalyzer.from_results() → total_return, annual_return, sharpe... │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Step3 说明**：全链路回测使用 `step3_backtest_fx_v1.py`（portfilio-end 副本，源自 `动量策略相关资料/step3_backtest_fx_v1.py`）。FX 文件置于 `data/fx.xlsx`，支持回退：若不存在或读取失败，则禁用汇率（全部 1.0）。step3 导入失败时，hybrid_momentum_engine 会回退到内置循环。

---

## 二、环节一：资产选择

**入口**：`app/backtesting/hybrid_momentum_engine.py` 第 244 行

```python
sel = select_assets_for_date(
    nav=prices.iloc[: date_idx + 1],
    date_idx=date_idx,
    calc_date=pd.Timestamp(calc_date),
    min_history=cfg.min_history_days,  # 260
    top_momentum=cfg.top_momentum,     # 7
)
```

**核心实现**：`app/selection/step_files/step1_asset_selection.py`

| 步骤 | 函数/逻辑 | 说明 |
|------|-----------|------|
| 有效资产池 | `valid_count >= min_history` | 近 260 天有效数据 |
| 动量打分 | `calc_momentum_scores()` | MOM/MACD/POSI/SMOM 多窗口，> -2% 得 1 分 |
| 动量入选 | 按平均排名取前 7 | `avg_rank <= top_momentum` 则入选 |
| 反转打分 | `calc_reversal_scores()` | 10 日、22 日偏度，负偏优先 |
| 反转入选 | 唯一最高分 | 并列则都不入选 |
| 最终入选 | `momentum_selected ∪ reversal_selected` | 7～8 个资产 |
| 入选矩阵 | `{asset: 0\|1\|2}` | 0=未入选, 1=单一入选, 2=双入选 |

**输出**：`selection_records`（含 `final_selected`, `入选矩阵_row`）

---

## 三、环节二：权重计算

**入口**：`app/backtesting/hybrid_momentum_engine.py` 第 273 行

```python
w_res = calc_weights_for_date(
    nav=nav,
    date_idx=date_idx,
    selection_row=selection_row,   # 入选矩阵_row
    all_assets=all_assets,
    target_vol=cfg.target_vol,    # 0.05
    max_leverage=cfg.max_leverage,
    weight_caps=weight_caps,
    fillna_zero=False,
)
```

**核心实现**：`app/selection/step_files/step2_weight_calculation.py` / `engine_reference.py`

| 步骤 | 公式/逻辑 | 说明 |
|------|-----------|------|
| 风险预算 | `status=2 → 2/8; status=1 → 1/8; 0 → 0` | 按入选矩阵分配 |
| 资产波动率 | `max(σ_22, σ_65, σ_130)` | 年化波动率 |
| 初始权重 | `w_init = b × (target_vol / σ)` | 风险预算 × 目标波动率 / 资产波动率 |
| 组合波动率 | `max(σ_port_22, σ_port_65, σ_port_130)` | 组合年化波动率 |
| 缩放约束 | `scale = min(target_vol/σ_port, max_leverage/Σw)` | 波动率 + 杠杆约束 |
| 单资产上限 | `capped = min(w, weight_caps[asset])` | 截断超限权重 |
| 最终权重 | `final_weights` | 供调仓使用 |

**输出**：`weight_records`，`rebalance_map[execute_date] = final_weights`

---

## 四、环节三：调仓实施

**T+2 规则**：`app/backtesting/hybrid_momentum_engine.py` 构建 `rebalance_map`，step3 执行调仓

```python
effective_calc = month_last_trade[period]   # 月末最后交易日
execute_date = future_dates[1]             # T+2
execute_date = _skip_excluded_execute_date(execute_date, ...)  # 排除日顺延
rebalance_map[execute_date] = final_weights
```

**调仓日逻辑**：由 `step3_backtest_fx_v1.run_backtest_fx_inmem()` 执行

```python
if date in rebalance_map and not is_vol_reset_day:
    new_weights = rebalance_map[date]
    # 交易成本
    if enable_costs:
        tc_cost = Σ |target_cny - curr_cny| × tc[asset]
        index_value -= tc_cost
    # 更新持仓
    current_weights = new_weights
    for a in all_assets:
        positions_cny[a] = index_value × current_weights[a]
        positions_local[a] = positions_cny[a] / fx_rates_t[a]
```

**FX 加载**：`fx_rates`（传入）> `fx_df`（传入）> `data/fx.xlsx`（`load_fx_from_data_fallback()`，回退）

---

## 五、环节四：净值计算

**每日循环**：由 `step3_backtest_fx_v1.run_backtest_fx_inmem()` 执行（hybrid_momentum_engine 调用）

### 5.1 复制成本（按日计提）

```python
days_between = (date - prev_date).days
rc_cost = positions_local[a] × (rc[a] / 365) × days_between
rc_cny = rc_cost × fx_rates_t[a]
index_value -= daily_replication_cost
```

### 5.2 每日损益（价格 + 汇率）

```python
ret = (p1 - p0) / p0
pnl_local = positions_local[a] × ret
pnl_cny_val = pnl_local × fx_rates_t[a]   # 文档公式: PnL_CNY = PnL_local × FX_t
daily_pnl_cny += pnl_cny_val
positions_local[a] *= (1 + ret)
positions_cny[a] = positions_local[a] × fx_rates_t[a]
index_value += daily_pnl_cny
```

### 5.3 调仓日交易成本

```python
tc_cost = Σ |target_cny - curr_cny| × tc[asset]
index_value -= tc_cost
```

### 5.4 波动率重置（可选）

当组合波动率 > 6% 时，T+2 执行降仓：`new_weights = current_weights × (target_vol / vol_trigger)`

### 5.5 净值序列

```python
nav_series = pd.Series([s.total_value for s in snapshots], index=[s.time for s in snapshots])
```

---

## 六、环节五：最终收益率计算

**入口**：`app/backtesting/hybrid_momentum_engine.py` 第 605～621 行

```python
perf_analyzer = PerformanceAnalyzer(risk_free_rate=0.02)
summary = perf_analyzer.from_results(snapshots, trades)
performance = {
    "total_return": summary.total_return,      # (end_nav/start_nav) - 1
    "annual_return": summary.annual_return,    # (1+mean_ret)^252 - 1
    "volatility": summary.volatility,          # 日度波动率
    "max_drawdown": summary.max_drawdown,      # 最大回撤
    "sharpe_ratio": summary.sharpe_ratio,      # (年化收益-无风险)/年化波动率
    "calmar_ratio": summary.calmar_ratio,      # 年化收益/|最大回撤|
}
```

**核心实现**：`app/backtesting/analytics.py` 第 56～120 行

| 指标 | 计算方式 |
|------|----------|
| total_return | `(end_value / start_value) - 1` |
| annual_return | `(1 + mean_ret)^252 - 1` |
| volatility | `returns.std()` |
| annual_volatility | `volatility × √252` |
| max_drawdown | `calculate_drawdown_series(total_values)` |
| sharpe_ratio | `(annual_return - rf) / annual_vol` |
| calmar_ratio | `annual_return / |max_drawdown|` |

**说明**：调仓日收益率设为 0，不参与收益统计。

---

## 七、文件与调用关系

| 环节 | 主文件 | 关键函数/变量 |
|------|--------|----------------|
| 资产选择 | `app/selection/step_files/step1_asset_selection.py` | `select_assets_for_date()` |
| 权重计算 | `app/selection/step_files/step2_weight_calculation.py` | `calc_weights_for_date()` |
| 引擎调度 | `app/selection/engine_reference.py` | 封装 step1/step2 |
| 回测（step3） | `app/selection/step_files/step3_backtest_fx_v1.py` | `run_backtest_fx_inmem()`，FX 从 `data/fx.xlsx` 回退 |
| 全链路入口 | `app/backtesting/hybrid_momentum_engine.py` | `run_hybrid_momentum_backtest()`，调用 step1→step2→step3 |
| 收益率 | `app/backtesting/analytics.py` | `PerformanceAnalyzer.from_results()` |
| 导出 | `app/backtesting/hybrid_momentum_export.py` | 资产选择、权重、回测结果 Excel |

---

## 八、API 入口

`app/api/backtests.py` 第 539～573 行：**仅当** `strategy_type == "risk_budget_target_vol"` **且** 启用混合动量选择（`enable_momentum_selection` / `asset_selection_count` / `selector_type == "reference_engine"`）时，调用 `run_hybrid_momentum_backtest()`，使用 step3 全链路回测。其他策略使用通用 `BacktestEngine`。
