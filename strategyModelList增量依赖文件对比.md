# strategyModelList 增量依赖文件对比

## 对比说明
本文档对比 `portfilio` 和 `portfilio1` 两个项目中 `strategyModelList` 的依赖文件，找出增量（新增）的依赖文件。

---

## portfilio1 中的依赖文件

### 使用 strategyList 别名
1. `src/views/Dashboard.vue`
2. `src/views/portfolio/Rebalance.vue`
3. `src/views/portfolio/PortfolioCreate.vue`
4. `src/views/strategy/StrategyList.vue`

### 调用 fetchStrategyModelList action
5. `src/views/strategy/StrategyModelList.vue`

### 其他相关文件（使用 templateList，不直接依赖 strategyModelList）
6. `src/views/strategy/StrategyModelForm.vue`
7. `src/views/strategy/StrategyDetail.vue`
8. `src/views/strategy/StrategyDevelop.vue`

---

## portfilio 中的依赖文件

### 直接使用 strategyModelList
1. **`src/views/strategy/BacktestExecution.vue`** ⭐ **新增文件**

### 使用 strategyList 别名
2. `src/views/Dashboard.vue`
3. `src/views/portfolio/Rebalance.vue`
4. `src/views/portfolio/PortfolioCreate.vue`
5. `src/views/strategy/StrategyList.vue`

### 调用 fetchStrategyModelList action
6. `src/views/strategy/StrategyModelList.vue`
7. **`src/views/strategy/BacktestExecution.vue`** ⭐ **新增调用**

### 其他相关文件（使用 templateList，不直接依赖 strategyModelList）
8. `src/views/strategy/StrategyModelForm.vue`
9. `src/views/strategy/StrategyDetail.vue`
10. `src/views/strategy/StrategyDevelop.vue`

---

## 增量文件清单（portfilio 相比 portfilio1 新增）

### 1. BacktestExecution.vue ⭐
- **文件路径**: `src/views/strategy/BacktestExecution.vue`
- **依赖方式**: 
  - 直接使用 `strategyModelList` (通过 `mapState`)
  - 调用 `fetchStrategyModelList` action
  - 提供本地 computed 别名 `strategyList`
- **用途**: 
  - 回测执行页面
  - 显示策略列表供选择（单策略和多策略模式）
  - 支持策略回测功能
- **代码位置**:
  ```javascript
  // 第528行：mapState
  ...mapState('strategy', ['strategyModelList']),
  
  // 第530-532行：computed 别名
  strategyList() {
    return this.strategyModelList || [];
  }
  
  // 第601行：调用 action
  await this.$store.dispatch('strategy/fetchStrategyModelList', { ... })
  
  // 多处使用：strategyList.find(), strategyList.length 等
  ```

---

## 对比总结

| 项目 | 依赖文件数量 | 新增文件 |
|------|------------|---------|
| portfilio1 | 8个文件 | - |
| portfilio | 10个文件 | 1个文件 |

### 增量统计
- **新增文件**: 1个
  - `src/views/strategy/BacktestExecution.vue`

- **新增功能**: 
  - 回测执行功能（单策略和多策略对比）
  - 策略选择器（支持单选和多选）
  - 回测参数配置
  - 回测结果展示

---

## 文件路径对比

### portfilio1 中的文件（8个）
```
src/views/Dashboard.vue
src/views/portfolio/Rebalance.vue
src/views/portfolio/PortfolioCreate.vue
src/views/strategy/StrategyList.vue
src/views/strategy/StrategyModelList.vue
src/views/strategy/StrategyModelForm.vue
src/views/strategy/StrategyDetail.vue
src/views/strategy/StrategyDevelop.vue
```

### portfilio 中的文件（10个）
```
src/views/strategy/BacktestExecution.vue          ⭐ 新增
src/views/Dashboard.vue
src/views/portfolio/Rebalance.vue
src/views/portfolio/PortfolioCreate.vue
src/views/strategy/StrategyList.vue
src/views/strategy/StrategyModelList.vue
src/views/strategy/StrategyModelForm.vue
src/views/strategy/StrategyDetail.vue
src/views/strategy/StrategyDevelop.vue
```

---

## 迁移注意事项

如果从 `portfilio1` 迁移到 `portfilio`，需要：

1. **新增文件**:
   - 复制 `src/views/strategy/BacktestExecution.vue` 及其依赖组件
   - 复制 `src/views/strategy/backtest/` 目录下的组件
     - `SingleStrategyResult.vue`
     - `MultiStrategyComparison.vue`
   - 复制 `src/views/strategy/BacktestResult.vue`

2. **路由配置**:
   - 在 `src/router/index.js` 中添加回测执行路由

3. **菜单配置**:
   - 在 `src/layout/MainLayout.vue` 中添加回测执行菜单项

4. **API 依赖**:
   - 确保后端支持回测相关 API
   - 检查 `src/api/strategy.js` 中的 `runBacktest` 函数

---

## 依赖关系图

### portfilio1
```
strategy.js (store)
  └── strategyModelList
      └── getter: strategyList
          ├── Dashboard.vue
          ├── Rebalance.vue
          ├── PortfolioCreate.vue
          └── StrategyList.vue
      
      └── action: fetchStrategyModelList
          └── StrategyModelList.vue
```

### portfilio (增量)
```
strategy.js (store)
  └── strategyModelList
      ├── 直接使用
      │   └── BacktestExecution.vue ⭐ 新增
      │
      └── getter: strategyList
          ├── Dashboard.vue
          ├── Rebalance.vue
          ├── PortfolioCreate.vue
          ├── StrategyList.vue
          └── BacktestExecution.vue ⭐ (也使用别名)
      
      └── action: fetchStrategyModelList
          ├── StrategyModelList.vue
          └── BacktestExecution.vue ⭐ 新增
```

---

## 快速参考

### 增量文件路径
```
src/views/strategy/BacktestExecution.vue
```

### 相对路径（从项目根目录）
```
portfilio/src/views/strategy/BacktestExecution.vue
```

### 绝对路径（Windows）
```
D:\portfilio\src\views\strategy\BacktestExecution.vue
```
