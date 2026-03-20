# BacktestExecution.vue 依赖清单

## 📋 概述

`BacktestExecution.vue` 是回测执行页面的主组件，位于 `src/views/strategy/BacktestExecution.vue`。

---

## 🔗 直接依赖的组件

### 1. **BacktestResult.vue**
- **路径**: `src/views/strategy/BacktestResult.vue`
- **用途**: 显示回测结果容器组件
- **传递的 props**:
  - `results`: 回测结果数据对象
  - `mode`: 回测模式（'single' 或 'multi'）
  - `config`: 回测配置信息

---

## 🔗 间接依赖的组件（通过 BacktestResult.vue）

### 2. **SingleStrategyResult.vue**
- **路径**: `src/views/strategy/backtest/SingleStrategyResult.vue`
- **用途**: 单策略回测结果展示组件
- **功能**:
  - 显示核心绩效指标（总收益率、年化收益率、夏普比率、最大回撤等）
  - 绘制净值曲线图表（使用 ECharts）
  - 绘制回撤曲线图表
  - 显示持仓权重变化图表
  - 显示波动率监控图表
  - 显示交易明细表格

### 3. **MultiStrategyComparison.vue**
- **路径**: `src/views/strategy/backtest/MultiStrategyComparison.vue`
- **用途**: 多策略对比结果展示组件
- **功能**:
  - 绩效指标对比表格
  - 净值曲线对比图表
  - 各策略详细结果（使用 SingleStrategyResult 组件）

---

## 📦 Vuex Store 依赖

### Store Module: `strategy`

#### State 使用:
```javascript
mapState('strategy', ['strategyModelList'])
```

#### Actions 调用:
1. **`strategy/fetchStrategyModelList`**
   - **用途**: 获取策略模型列表
   - **参数**: `{ status?: string }` (可选，不传则获取所有状态)
   - **返回**: 策略模型数组

2. **`strategy/runBacktest`**
   - **用途**: 执行回测
   - **参数**: 
     ```javascript
     {
       modelId: string,
       data: {
         start_date: string,      // 格式: 'YYYYMMDD'
         end_date: string,         // 格式: 'YYYYMMDD'
         initial_cash: number,    // 初始资金
         rebalance_freq: string,   // 调仓频率: 'daily'|'weekly'|'monthly'|'quarterly'|'yearly'
         commission_rate: number,  // 手续费率
         slippage: number,         // 滑点
         lookback_days: number     // 历史数据回看期（默认252）
       }
     }
     ```
   - **返回**: 回测结果对象

---

## 🌐 API 依赖（通过 Vuex Store）

### API 文件: `src/api/strategy.js`

#### 使用的函数:
1. **`getStrategyModelList(params)`**
   - **后端接口**: `GET /api/v1/strategy-models/`
   - **用途**: 获取策略模型列表

2. **`runBacktest(modelId, data)`**
   - **后端接口**: `POST /api/v1/backtests/run-by-model/{modelId}`
   - **用途**: 执行回测
   - **请求体**:
     ```javascript
     {
       start_date: string,      // 'YYYYMMDD'
       end_date: string,         // 'YYYYMMDD'
       initial_cash: number,
       rebalance_freq: string,
       commission_rate: number,
       slippage: number,
       lookback_days: number
     }
     ```

---

## 🛠️ 工具库依赖

### 1. **dayjs**
- **用途**: 日期处理和格式化
- **使用场景**:
  - 设置默认回测时间范围（当前日期往前推1年）
  - 日期格式化

### 2. **Element UI 组件**
- **使用的组件**:
  - `el-card`: 卡片容器
  - `el-form` / `el-form-item`: 表单
  - `el-radio-group` / `el-radio-button`: 单选按钮组
  - `el-select` / `el-option`: 下拉选择
  - `el-checkbox-group` / `el-checkbox`: 多选框组
  - `el-input-number`: 数字输入框
  - `el-date-picker`: 日期选择器
  - `el-button`: 按钮
  - `el-alert`: 提示信息
  - `el-tooltip`: 工具提示
  - `el-tag`: 标签
  - `el-divider`: 分割线

---

## 📁 文件依赖树

```
BacktestExecution.vue
├── BacktestResult.vue
│   ├── SingleStrategyResult.vue
│   │   └── echarts (图表库)
│   └── MultiStrategyComparison.vue
│       └── SingleStrategyResult.vue (复用)
├── Vuex Store (strategy module)
│   └── src/api/strategy.js
│       └── src/utils/request.js
└── dayjs (日期处理库)
```

---

## 🔧 必需文件清单

### 组件文件
- [x] `src/views/strategy/BacktestExecution.vue` (主组件)
- [x] `src/views/strategy/BacktestResult.vue` (结果容器)
- [x] `src/views/strategy/backtest/SingleStrategyResult.vue` (单策略结果)
- [x] `src/views/strategy/backtest/MultiStrategyComparison.vue` (多策略对比)

### Store 文件
- [x] `src/store/modules/strategy.js` (策略模块)

### API 文件
- [x] `src/api/strategy.js` (策略 API)
- [x] `src/utils/request.js` (HTTP 请求工具)

### 路由配置
- [x] `src/router/index.js` (需要配置路由)

### 菜单配置
- [x] `src/layout/MainLayout.vue` (需要添加菜单项)

---

## 📝 路由配置

在 `src/router/index.js` 中需要配置：

```javascript
{
  path: '/strategy/backtest',
  name: 'BacktestExecution',
  component: () => import('@/views/strategy/BacktestExecution.vue'),
  meta: { title: '回测执行' }
}
```

---

## 🎯 菜单配置

在 `src/layout/MainLayout.vue` 的菜单中需要添加：

```vue
<el-menu-item index="/strategy/backtest">回测执行</el-menu-item>
```

---

## 🔄 数据流

```
用户操作
  ↓
BacktestExecution.vue
  ↓
Vuex Action: strategy/runBacktest
  ↓
API: runBacktest(modelId, data)
  ↓
后端: POST /api/v1/backtests/run-by-model/{modelId}
  ↓
返回回测结果
  ↓
BacktestResult.vue
  ↓
SingleStrategyResult.vue 或 MultiStrategyComparison.vue
  ↓
显示图表和表格
```

---

## ⚠️ 注意事项

1. **策略列表加载**: 组件在 `created` 钩子中自动加载策略列表，不筛选状态（包括草稿和已发布）

2. **模式切换**: 单策略模式和多策略模式之间切换时，会自动重置策略选择

3. **策略选择验证**:
   - 单策略模式: 必须选择1个策略
   - 多策略模式: 必须选择2-5个策略

4. **日期格式**: 提交给后端时，日期需要转换为 `YYYYMMDD` 格式（去掉横线）

5. **调仓频率映射**: 前端显示中文（每日、每周等），提交时转换为英文（daily、weekly等）

6. **错误处理**: 
   - 对于数据不足的错误，使用 `$alert` 对话框显示完整信息
   - 对于其他错误，使用 `$message` 提示

7. **图表库**: `SingleStrategyResult.vue` 使用 ECharts 绘制图表，需要确保 ECharts 已正确引入

---

## 🚀 快速检查清单

移植或部署时，请确认以下文件存在：

- [ ] `src/views/strategy/BacktestExecution.vue`
- [ ] `src/views/strategy/BacktestResult.vue`
- [ ] `src/views/strategy/backtest/SingleStrategyResult.vue`
- [ ] `src/views/strategy/backtest/MultiStrategyComparison.vue`
- [ ] `src/store/modules/strategy.js`
- [ ] `src/api/strategy.js`
- [ ] `src/utils/request.js`
- [ ] `src/router/index.js` (包含路由配置)
- [ ] `src/layout/MainLayout.vue` (包含菜单项)
- [ ] `package.json` (包含 dayjs、echarts、element-ui 依赖)
