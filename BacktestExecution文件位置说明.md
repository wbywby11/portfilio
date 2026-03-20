# BacktestExecution.vue 文件位置说明

## 📁 问题描述

如果 `BacktestExecution.vue` 被移到了 `src/views/research/` 目录下，需要调整依赖文件的位置或导入路径。

---

## 🔧 方案一：移动所有依赖文件到 research 目录（推荐）

### 目录结构

```
src/views/research/
├── BacktestExecution.vue          ✅ 主组件
├── BacktestResult.vue             ✅ 结果容器组件
└── backtest/                      ✅ 回测结果子组件目录
    ├── SingleStrategyResult.vue   ✅ 单策略结果组件
    └── MultiStrategyComparison.vue ✅ 多策略对比组件
```

### 文件位置对应关系

| 原位置 | 新位置 |
|--------|--------|
| `src/views/strategy/BacktestExecution.vue` | `src/views/research/BacktestExecution.vue` |
| `src/views/strategy/BacktestResult.vue` | `src/views/research/BacktestResult.vue` |
| `src/views/strategy/backtest/SingleStrategyResult.vue` | `src/views/research/backtest/SingleStrategyResult.vue` |
| `src/views/strategy/backtest/MultiStrategyComparison.vue` | `src/views/research/backtest/MultiStrategyComparison.vue` |

### 需要修改的导入路径

#### 1. BacktestExecution.vue（无需修改）
```javascript
// 第269行，相对路径导入，如果 BacktestResult.vue 在同一目录下，无需修改
import BacktestResult from './BacktestResult.vue';
```

#### 2. BacktestResult.vue（需要修改）
```javascript
// 原代码（第30-31行）
import SingleStrategyResult from './backtest/SingleStrategyResult.vue';
import MultiStrategyComparison from './backtest/MultiStrategyComparison.vue';

// 如果文件在同一目录结构下，无需修改
// 如果文件在不同位置，需要修改为：
// import SingleStrategyResult from './backtest/SingleStrategyResult.vue';
// import MultiStrategyComparison from './backtest/MultiStrategyComparison.vue';
```

---

## 🔧 方案二：保持原文件位置，修改导入路径

### 目录结构（保持原样）

```
src/views/
├── research/
│   └── BacktestExecution.vue      ✅ 主组件（已移动）
└── strategy/
    ├── BacktestResult.vue         ✅ 保持原位置
    └── backtest/
        ├── SingleStrategyResult.vue   ✅ 保持原位置
        └── MultiStrategyComparison.vue ✅ 保持原位置
```

### 需要修改的导入路径

#### 1. BacktestExecution.vue（需要修改）
```javascript
// 原代码（第269行）
import BacktestResult from './BacktestResult.vue';

// 修改为（从 research 目录导入 strategy 目录的文件）
import BacktestResult from '../strategy/BacktestResult.vue';
```

#### 2. BacktestResult.vue（无需修改）
```javascript
// 保持原样，因为 backtest 目录在 strategy 目录下
import SingleStrategyResult from './backtest/SingleStrategyResult.vue';
import MultiStrategyComparison from './backtest/MultiStrategyComparison.vue';
```

---

## 📋 完整文件清单

### 必需文件（方案一：全部移到 research）

```
src/views/research/
├── BacktestExecution.vue
├── BacktestResult.vue
└── backtest/
    ├── SingleStrategyResult.vue
    └── MultiStrategyComparison.vue
```

### 必需文件（方案二：保持原位置）

```
src/views/
├── research/
│   └── BacktestExecution.vue
└── strategy/
    ├── BacktestResult.vue
    └── backtest/
        ├── SingleStrategyResult.vue
        └── MultiStrategyComparison.vue
```

---

## 🚀 快速操作步骤

### 方案一：移动文件（推荐，更独立）

```bash
# 1. 创建目录
mkdir -p src/views/research/backtest

# 2. 移动文件
# Windows PowerShell
Move-Item src/views/strategy/BacktestResult.vue src/views/research/
Move-Item src/views/strategy/backtest/SingleStrategyResult.vue src/views/research/backtest/
Move-Item src/views/strategy/backtest/MultiStrategyComparison.vue src/views/research/backtest/

# 3. 检查 BacktestResult.vue 的导入路径（应该无需修改）
```

### 方案二：修改导入路径

```javascript
// 在 BacktestExecution.vue 中修改第269行
// 从：
import BacktestResult from './BacktestResult.vue';
// 改为：
import BacktestResult from '../strategy/BacktestResult.vue';
```

---

## ⚠️ 注意事项

### 1. 相对路径说明

- `./` 表示当前目录
- `../` 表示上一级目录
- `./backtest/` 表示当前目录下的 backtest 子目录

### 2. 路径示例

假设 `BacktestExecution.vue` 在 `src/views/research/` 下：

```
src/views/research/BacktestExecution.vue
  ↓ 导入 ./BacktestResult.vue
src/views/research/BacktestResult.vue  ✅ 同一目录

src/views/research/BacktestExecution.vue
  ↓ 导入 ../strategy/BacktestResult.vue
src/views/strategy/BacktestResult.vue  ✅ 上一级目录的 strategy 子目录
```

### 3. 其他依赖（无需修改）

以下依赖使用绝对路径或从 node_modules 导入，无需修改：

```javascript
// Vuex Store（使用绝对路径别名 @）
import { mapState } from 'vuex';
...mapState('strategy', ['strategyModelList'])

// 第三方库（从 node_modules）
import dayjs from 'dayjs';
```

### 4. Store 和 API 依赖（无需移动）

这些文件位置不变，使用绝对路径别名 `@`：

- `src/store/modules/strategy.js` - Vuex Store
- `src/api/strategy.js` - API 文件
- `src/utils/request.js` - 请求工具

---

## 🔍 检查清单

### 方案一检查清单

- [ ] `src/views/research/BacktestExecution.vue` 存在
- [ ] `src/views/research/BacktestResult.vue` 存在
- [ ] `src/views/research/backtest/SingleStrategyResult.vue` 存在
- [ ] `src/views/research/backtest/MultiStrategyComparison.vue` 存在
- [ ] `BacktestExecution.vue` 中导入路径为 `'./BacktestResult.vue'`
- [ ] `BacktestResult.vue` 中导入路径为 `'./backtest/SingleStrategyResult.vue'` 和 `'./backtest/MultiStrategyComparison.vue'`

### 方案二检查清单

- [ ] `src/views/research/BacktestExecution.vue` 存在
- [ ] `src/views/strategy/BacktestResult.vue` 存在
- [ ] `src/views/strategy/backtest/SingleStrategyResult.vue` 存在
- [ ] `src/views/strategy/backtest/MultiStrategyComparison.vue` 存在
- [ ] `BacktestExecution.vue` 中导入路径为 `'../strategy/BacktestResult.vue'`
- [ ] `BacktestResult.vue` 中导入路径为 `'./backtest/SingleStrategyResult.vue'` 和 `'./backtest/MultiStrategyComparison.vue'`

---

## 🐛 常见错误

### 错误 1: `Cannot find module './BacktestResult.vue'`

**原因**: `BacktestResult.vue` 不在 `BacktestExecution.vue` 同一目录下

**解决**:
- 方案一：将 `BacktestResult.vue` 移到同一目录
- 方案二：修改导入路径为 `'../strategy/BacktestResult.vue'`

### 错误 2: `Cannot find module './backtest/SingleStrategyResult.vue'`

**原因**: `backtest` 目录不在 `BacktestResult.vue` 同一目录下

**解决**:
- 方案一：将 `backtest` 目录移到 `BacktestResult.vue` 同一目录
- 方案二：修改导入路径为 `'../strategy/backtest/SingleStrategyResult.vue'`

---

## 📝 总结

**推荐使用方案一**（移动所有文件到 research 目录），因为：
1. 所有相关文件集中在一个目录，便于管理
2. 相对路径更简单，不易出错
3. 如果将来需要移动整个 research 模块，只需移动一个目录

**如果选择方案二**（保持原位置），需要：
1. 修改 `BacktestExecution.vue` 中的导入路径
2. 确保路径正确（`../strategy/BacktestResult.vue`）
