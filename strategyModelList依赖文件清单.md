# strategyModelList 依赖文件清单

## 概述
`strategyModelList` 是 Vuex store 中 `strategy` 模块的状态，存储策略模型列表数据。本文档列出所有依赖它的 Vue 文件及其相对路径。

## Store 定义位置
- **文件路径**: `src/store/modules/strategy.js`
- **状态定义**: `state.strategyModelList = []`
- **别名**: `strategyList` (通过 getter 提供，用于向后兼容)

---

## 直接使用 strategyModelList 的文件

### 1. BacktestExecution.vue
- **相对路径**: `src/views/strategy/BacktestExecution.vue`
- **使用方式**: 
  ```javascript
  ...mapState('strategy', ['strategyModelList'])
  computed: {
    strategyList() {
      return this.strategyModelList || [];
    }
  }
  ```
- **用途**: 
  - 回测执行页面，显示策略列表供选择
  - 通过 `fetchStrategyModelList` action 加载策略列表
  - 用于单策略和多策略回测模式

---

## 使用 strategyList 别名（间接依赖）的文件

### 2. PortfolioCreate.vue
- **相对路径**: `src/views/portfolio/PortfolioCreate.vue`
- **使用方式**: 
  ```javascript
  ...mapState('strategy', ['strategyList'])
  ```
- **用途**: 
  - 创建组合页面，显示策略列表供选择
  - 用于关联策略到组合

### 3. Rebalance.vue
- **相对路径**: `src/views/portfolio/Rebalance.vue`
- **使用方式**: 
  ```javascript
  ...mapState('strategy', ['strategyList'])
  ```
- **用途**: 
  - 组合调仓页面，根据策略ID查找策略信息
  - 用于显示和配置调仓策略

### 4. Dashboard.vue
- **相对路径**: `src/views/Dashboard.vue`
- **使用方式**: 
  ```javascript
  ...mapState('strategy', ['strategyList'])
  computed: {
    strategyCount() {
      return this.strategyList.length;
    }
  }
  ```
- **用途**: 
  - 仪表板页面，显示策略数量统计
  - **问题**: 使用了不存在的 `fetchStrategyList` action（第216行），应改为 `fetchStrategyModelList`

### 5. StrategyList.vue
- **相对路径**: `src/views/strategy/StrategyList.vue`
- **使用方式**: 
  ```javascript
  ...mapState('strategy', ['strategyList', 'templateList'])
  ```
- **用途**: 
  - 策略列表页面，显示所有策略
  - **问题**: 使用了不存在的 `fetchStrategyList` action（第94行），应改为 `fetchStrategyModelList`

---

## 调用 fetchStrategyModelList Action 的文件

### 6. StrategyModelList.vue
- **相对路径**: `src/views/strategy/StrategyModelList.vue`
- **使用方式**: 
  ```javascript
  await this.$store.dispatch('strategy/fetchStrategyModelList', { ... })
  ```
- **用途**: 
  - 策略模型列表页面，加载并显示策略模型列表
  - 管理策略模型的增删改查

---

## 依赖关系图

```
strategy.js (store)
  └── state.strategyModelList
      ├── getter: strategyList (别名)
      │   ├── PortfolioCreate.vue
      │   ├── Rebalance.vue
      │   ├── Dashboard.vue
      │   └── StrategyList.vue
      │
      └── 直接使用
          └── BacktestExecution.vue
              └── computed: strategyList (本地别名)

actions.fetchStrategyModelList
  ├── BacktestExecution.vue
  └── StrategyModelList.vue
```

---

## 文件相对路径汇总

### 从项目根目录 (portfilio/)
1. `src/views/strategy/BacktestExecution.vue`
2. `src/views/strategy/StrategyModelList.vue`
3. `src/views/portfolio/PortfolioCreate.vue`
4. `src/views/portfolio/Rebalance.vue`
5. `src/views/Dashboard.vue`
6. `src/views/strategy/StrategyList.vue`

### Store 模块
- `src/store/modules/strategy.js`

---

## 注意事项

1. **别名使用**: 部分文件使用 `strategyList` 别名，这是通过 getter 提供的向后兼容别名，实际指向 `strategyModelList`。

2. **Action 调用问题**: 
   - 正确的 action 名称是 `fetchStrategyModelList`
   - ❌ **需要修复**: `Dashboard.vue` (第216行) 和 `StrategyList.vue` (第94行) 中使用了不存在的 `fetchStrategyList` action
   - 修复方法：将 `fetchStrategyList` 改为 `fetchStrategyModelList`

3. **数据流**: 
   - 数据通过 `fetchStrategyModelList` action 从后端加载
   - 加载后通过 `SET_STRATEGY_MODEL_LIST` mutation 更新 state
   - 各组件通过 `mapState` 或 getter 访问数据

4. **依赖关系**: 
   - 所有使用 `strategyModelList` 或 `strategyList` 的组件都依赖于 `src/store/modules/strategy.js`
   - 如果 store 模块路径改变，需要更新所有引用

---

## 检查清单

在迁移或重构时，需要检查以下文件：

- [ ] `src/store/modules/strategy.js` - Store 定义
- [ ] `src/views/strategy/BacktestExecution.vue` - 直接使用
- [ ] `src/views/strategy/StrategyModelList.vue` - 调用 action
- [ ] `src/views/portfolio/PortfolioCreate.vue` - 使用别名
- [ ] `src/views/portfolio/Rebalance.vue` - 使用别名
- [ ] `src/views/Dashboard.vue` - 使用别名（⚠️ 需要修复：第216行 `fetchStrategyList` → `fetchStrategyModelList`）
- [ ] `src/views/strategy/StrategyList.vue` - 使用别名（⚠️ 需要修复：第94行 `fetchStrategyList` → `fetchStrategyModelList`）

---

## 需要修复的问题

### 问题1: Dashboard.vue
**文件**: `src/views/Dashboard.vue`  
**行号**: 216  
**问题**: 使用了不存在的 action `fetchStrategyList`  
**修复**:
```javascript
// 修改前
await this.$store.dispatch('strategy/fetchStrategyList');

// 修改后
await this.$store.dispatch('strategy/fetchStrategyModelList');
```

### 问题2: StrategyList.vue
**文件**: `src/views/strategy/StrategyList.vue`  
**行号**: 94  
**问题**: 使用了不存在的 action `fetchStrategyList`  
**修复**:
```javascript
// 修改前
this.$store.dispatch('strategy/fetchStrategyList');

// 修改后
this.$store.dispatch('strategy/fetchStrategyModelList');
```
