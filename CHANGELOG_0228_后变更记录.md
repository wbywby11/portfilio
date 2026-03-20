# Portfilio 0228 版本后变更记录

> **版本基准**：0228（2025-02-28）
> **用途**：记录 0228 之后的所有代码变动，便于合并代码时参考

## 版本信息

- **当前版本**：0.2.28（0228）
- **基准日期**：2025-02-28
- **项目**：portfilio（前端 Vue 项目）
- **前后端联动变更**：参见 `portfilio-end/合并代码变更记录_0228后.md`
- **回退措施**：参见 `portfilio-end/0228版本回退措施.md`，执行 `portfilio-end/rollback_0228.ps1` 可快速回退

---

## 变更记录模板

每次更新请按以下格式追加记录：

```markdown
### YYYY-MM-DD 更新

#### 新增文件
- `路径/文件名` - 说明

#### 修改文件
- `路径/文件名` - 修改说明（可注明行号或功能点）

#### 删除文件
- `路径/文件名` - 说明

#### 功能说明
- 简要描述本次变更的功能或修复
```

---

## 0228 之后变更汇总

### 2025-02-28 更新（权重上限按策略类型区分）

#### 修改文件
- `src/views/strategy/BacktestExecution.vue` - `selectedStrategyInfo` watcher、`onStrategySelect` 仅对非主观策略拉取 `max_weight_dict`；`initMultiStrategyManualAdjustments` 不再拉取（主观策略不限制）

#### 功能说明
- 指数编制规则权重上限仅对动量/量化策略生效，主观策略（manual_allocation）不再受特定资产上限约束

### 2025-02-28 更新（主观策略调仓日优化）

#### 修改文件
- `src/views/strategy/BacktestExecution.vue` - `rebalanceDatePickerOptions` 增加回测时间区间限制，调仓日不可超出 `form.date_range` 的 [开始日期, 终止日期]

#### 功能说明
- 调仓日选择器限制在回测时间区间内，超出开始/终止日期的日期将被禁用

### 2025-02-28 更新（回测结果图表布局与对齐优化）

#### 修改文件
- `src/views/strategy/backtest/SingleStrategyResult.vue` - 持仓权重变化：grid.left=80、grid.top=40；调仓类型文字改用 graphic 在上方横向展示，使用 convertToPixel 与竖线对齐；波动率图 grid.right=14%、markLine label position:'end'
- `src/components/BacktestDetailDialog.vue` - 权重图 grid.left=80；波动率图 grid.right=14%、markLine label position:'end'
- `src/views/strategy/backtest/MultiStrategyComparison.vue` - 净值/波动率对比图 grid.left=80

#### 功能说明
- 解决持仓权重变化文字与纵坐标重叠；组合波动率监控目标波动率值显示不全；调仓类型文字与竖线精确对齐

