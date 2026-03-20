# 动量选择器权重参数传递与「权重之和不为 1」问题说明

## 一、后端 (portfolio-end) 接收参数

### 1. 接口与请求体

- **接口**: `POST /api/v1/backtests/run-by-model/{model_id}`
- **请求体模型**: `BacktestByModelRequest`（`app/api/backtests.py`）

### 2. 用于计算权重的接收参数

| 参数 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `start_date` | str | 回测开始日期 (YYYYMMDD) | 必填，前端 |
| `end_date` | str | 回测结束日期 (YYYYMMDD) | 必填，前端 |
| `initial_cash` | float | 初始资金 | 前端，默认 1000万 |
| `rebalance_freq` | str | 调仓频率 (daily/weekly/monthly/quarterly/yearly) | 前端，可覆盖模型 |
| `commission_rate` | float | 手续费率 | 前端，可覆盖 |
| `slippage` | float | 滑点率 | 前端，可覆盖 |
| `lookback_days` | int | 历史数据预加载天数 | 前端，默认 500 |
| **动量选择器** | | | |
| `enable_momentum_selection` | bool? | 是否启用动量资产选择 | 前端，覆盖模型 |
| `selector_type` | str? | 选择器类型 (momentum / momentum_reversal) | 前端，覆盖模型 |
| `asset_selection_count` | int? | **选择资产数量**（如 2） | 前端，覆盖模型 |
| `min_history_days` | int? | 最小历史数据要求 | 前端，覆盖模型 |
| `momentum_windows` | str? | 动量窗口，如 "22,65,260" | 前端，覆盖模型 |
| `tie_break_window` | int? | 并列决胜窗口 | 前端，覆盖模型 |

**资产列表 (thscodes)**：前端 **不传**。由后端根据 `model_id` 从策略模型读取 `model.asset_codes`（如 3 个资产），即 **始终用模型配置的完整资产池** 作为候选池。

### 3. 后端权重计算实际用到的数据

- **资产池**: `request_data["thscodes"]` ← `to_backtest_request()` 中的 `model.asset_codes`（**不改动**，与前端无关）。
- **是否启用选择**: `enable_selection` = 前端 `enable_momentum_selection` ?? 模型 `enable_momentum_selection`；若前端传了 `asset_selection_count` / `selector_type` / `min_history_days` / `momentum_windows` / `tie_break_window` 任一，也会强制 `enable_selection = True`。
- **选择资产数量**: `n_assets` = 前端 `asset_selection_count` ?? 模型 `asset_selection_count` ?? `len(model.asset_codes)`。
- **策略参数**: `strategy_params` 来自模型 `parameters`，并叠加上面前端传来的动量选择器参数。

**权重计算流程**（`run_backtest` → 策略层）:

1. 若 **未启用** 资产选择：  
   - 用 **全部** `thscodes`（即 `model.asset_codes`，如 3 个）跑策略 `allocate`，权重在 3 个资产上求和为 1。
2. 若 **启用** 资产选择：  
   - 用 `StrategyAdapterWithSelection`：先从 `thscodes` 里动量选 `n_assets` 个（如 2 个），再用 **仅这 2 个资产** 的历史数据调 `allocate`，权重在 2 个资产上求和为 1，未选中的资产权重为 0。

因此，**真正参与权重计算的资产数量** 由 `enable_selection` + `asset_selection_count`（或模型默认）决定；`thscodes` 只定义候选池，不因前端改动。

---

## 二、前端 (portfolio) 发送参数

### 1. 调用链

1. `BacktestExecution.vue` 中构建 `backtestData`
2. `this.$store.dispatch('strategy/runBacktest', { modelId, data: backtestData })`
3. `src/api/strategy.js` → `runBacktest(modelId, data)` → `POST /api/v1/backtests/run-by-model/{modelId}`，body = `data`

### 2. 始终发送的字段

```javascript
{
  start_date: 'YYYYMMDD',      // form.date_range[0]
  end_date: 'YYYYMMDD',        // form.date_range[1]
  initial_cash: number,
  rebalance_freq: 'daily'|'weekly'|'monthly'|'quarterly'|'yearly',
  commission_rate: number,
  slippage: number,
  lookback_days: 252
}
```

### 3. 动量选择器相关（条件发送）

当 **单策略 + 有动量选择配置** 或 **当前策略启用选择器** 时，会追加：

```javascript
{
  enable_momentum_selection: true,
  selector_type: 'momentum' | ...,
  asset_selection_count: number,   // 如 2
  min_history_days: number,
  momentum_windows: '22,65,260',
  tie_break_window: number
}
```

- **单策略**: 使用 `form.selector_type`、`form.asset_selection_count`、`form.min_history_days`、`form.momentum_windows`、`form.tie_break_window`。
- **多策略**: 使用 `form.multiStrategySelectionParams[strategyId]` 里对应策略的配置。

**是否展示「动量资产选择器配置」**：单策略且 `hasMomentumSelection` 为 true 时展示。  
`hasMomentumSelection` 来源于 `selectedStrategyInfo.enable_momentum_selection === true`。

**前端不发送** `thscodes`，资产池完全由后端模型决定。

---

## 三、「选择资产数量为 2，但两种资产权重之和不为 1」的原因

### 1. 现象

- 动量选择器配置里「选择资产数量」设为 2。
- 前端只展示 2 个资产的权重，但两者之和 ≠ 1。

### 2. 直接原因

1. **后端** 实际 **未启用资产选择**（`enable_selection = False`），或用错了 `asset_selection_count`：  
   - 权重按 **全部** `model.asset_codes`（如 3 个）计算，输出 3 个资产，且已归一化，和为 1。
2. **前端** 展示权重时做了 **「最多只显示 `selected_asset_count` 个资产」** 的截断：  
   - `SingleStrategyResult.vue`、`BacktestDetailDialog.vue` 中：先收集非零权重资产，若 `selected_asset_count` 存在且大于 0，且资产数超过该值，则 `assets = assets.slice(0, cap)`，只画前 `cap` 个。
3. 因此：**接口返回的是 3 个资产、和为 1 的权重**；**前端只展示前 2 个**，这 2 个之和必然 < 1，缺了第 3 个资产的那一部分。

### 3. 为何后端可能未启用选择？

- 前端未传 `enable_momentum_selection`，且模型里 `enable_momentum_selection` 为 false，且 **也没有传** `asset_selection_count` 等任一选择器参数，则 `enable_selection` 仍为 False。
- 前端只在「有动量选择配置」或「策略启用选择器」时才带 `asset_selection_count` 等；若 `selectedStrategyInfo.enable_momentum_selection` 不准确或策略未勾选启用，则不会带这些参数，后端就不会启用选择。

---

## 四、已实施的优化（手动选择资产 + 以前端传参为准）

### 1. 后端 (portfolio-end)

- **新增 `selected_asset_codes` 参数**：前端可传手动选择的资产代码列表，后端优先使用该列表（跳过动量选择器），仅对这些资产计算权重，权重和为 1。
- **校验**：
  - `selected_asset_codes` 中的所有资产必须在模型资产池中，否则 400。
  - 若同时传了 `asset_selection_count`，则勾选数量必须与之一致，否则 400。
- **逻辑分支**：
  - 若传 `selected_asset_codes`（非空）：用指定资产替换 `thscodes`，不启用动量选择器。
  - 若未传：走原有动量选择器逻辑（以 `asset_selection_count` 等为准）。
- **权重输出**：仅返回所选资产，权重归一化和为 1。

### 2. 前端 (portfolio)

- **资产标签点选**：在「选择资产数量」下方展示资产池标签，用户点选对应数量的资产，点选后标签变色高亮。
- **校验**：勾选的资产数量必须等于「选择资产数量」，否则阻止提交。
- **发送参数**：
  - `asset_selection_count`：选择资产数量。
  - `selected_asset_codes`：手动选择的资产代码数组。
- **逻辑**：若手动选择了资产，`enable_momentum_selection = false`，跳过动量选择器；否则走动量选择器。

### 3. 建议验证步骤

1. 回测请求体里确认包含 `enable_momentum_selection: true`、`asset_selection_count: 2`。
2. 后端日志确认 `enable_selection === True`、`n_assets === 2`，且使用 `StrategyAdapterWithSelection`。
3. 接口返回的 `snapshots[].weights` 仅有 2 个资产，且二者之和为 1。
4. 前端展示的权重与接口一致，且不做导致「只展示部分资产」的截断，或对截断做明确说明。

---

## 五、相关代码位置

| 项目 | 文件 | 说明 |
|------|------|------|
| 后端 | `app/api/backtests.py` | `BacktestByModelRequest`、`run_backtest_by_model`、`run_backtest`、`_weights_for_response` |
| 后端 | `app/services/strategy_model_service.py` | `to_backtest_request`（`thscodes` = `model.asset_codes`） |
| 后端 | `app/backtesting/strategy_api.py` | `StrategyAdapterWithSelection`、动量选择 + 仅选中资产 `allocate` |
| 前端 | `src/views/strategy/BacktestExecution.vue` | 构建 `backtestData`、动量选择器参数、`hasMomentumSelection` |
| 前端 | `src/api/strategy.js` | `runBacktest(modelId, data)` |
| 前端 | `src/views/strategy/backtest/SingleStrategyResult.vue` | `positionData`、`selected_asset_count` 截断展示 |
| 前端 | `src/components/BacktestDetailDialog.vue` | `weight_changes`、`selected_asset_count` 截断展示 |

---

**结论**：  
- 后端用于权重计算的关键参数是 **`thscodes`（来自模型）**、**`enable_momentum_selection`**、**`asset_selection_count`** 等；前端不传 `thscodes`。  
- 「两种资产权重之和不为 1」是因为：**权重实际按 3 个资产算、和为 1**，**前端只展示其中 2 个**。  
- 修复方向：**后端在传了 `asset_selection_count` 时强制启用选择、仅对选中资产算权重并只返回这些**；**前端保证传齐动量参数**，且 **不轻易截断展示导致「部分权重」**。
