# StrategyModelDetail 相比 portfolio-end1 原版的代码增量部分的新依赖关系

## 概述

本文档详细分析 `StrategyModelDetail.vue` 相比原版 `portfolio-end1` 的增量代码部分，特别是与动量选择器展示相关的新增依赖关系。

**文件位置**: `D:\portfilio\src\views\strategy\StrategyModelDetail.vue`

**注意**: 由于原版 `portfolio-end1` 中不存在 `StrategyModelDetail.vue` 文件，因此整个文件及其所有依赖都是新增的。

---

## 一、直接依赖（Import 语句）

### 1.1 第三方库依赖

**位置**: 行 450-451

```javascript
import dayjs from 'dayjs';
import * as echarts from 'echarts';
```

**依赖说明**:
- **`dayjs`**: 日期处理库，用于格式化日期显示
- **`echarts`**: 图表库，用于绘制权益曲线图

**是否新增**: ✅ **完全新增**（原版中不存在此文件）

---

### 1.2 组件依赖

**位置**: 行 452-453, 460-461

```javascript
// 直接导入的组件
import BacktestDialog from '@/components/BacktestDialog.vue';
import BacktestDetailDialog from '@/components/BacktestDetailDialog.vue';

// 动态导入的组件
StrategyModelForm: () => import('./StrategyModelForm.vue'),
PortfolioDetail: () => import('../portfolio/PortfolioDetail.vue')
```

**依赖说明**:
- **`BacktestDialog`**: 回测配置对话框组件
- **`BacktestDetailDialog`**: 回测详情对话框组件
- **`StrategyModelForm`**: 策略模型表单组件（用于编辑）
- **`PortfolioDetail`**: 组合详情组件

**是否新增**: ✅ **完全新增**

---

## 二、Vuex Store 依赖

### 2.1 Strategy Store Actions

**位置**: 行 566, 590, 635

```javascript
// 获取策略模型详情（包含动量选择器参数）
this.model = await this.$store.dispatch('strategy/fetchStrategyModel', this.modelId);

// 获取回测历史
const res = await this.$store.dispatch('strategy/fetchBacktestHistory', {
  modelId: this.modelId,
  skip: this.backtestPagination.skip,
  limit: this.backtestPagination.limit
});

// 发布策略模型
await this.$store.dispatch('strategy/publishModel', this.modelId);
```

**依赖的 Store Actions**:

1. **`strategy/fetchStrategyModel`**
   - **文件**: `D:\portfilio\src\store\modules\strategy.js`
   - **功能**: 获取单个策略模型详情
   - **API 调用**: `getStrategyModel(modelId)` → `GET /api/v1/strategy-models/{model_id}`
   - **返回数据**: 包含动量选择器参数（`enable_momentum_selection`, `selector_type`, `asset_selection_count`, `min_history_days`, `momentum_windows`, `tie_break_window`）
   - **是否新增**: ✅ **新增**（用于获取包含动量选择器参数的策略详情）

2. **`strategy/fetchBacktestHistory`**
   - **文件**: `D:\portfilio\src\store\modules\strategy.js`
   - **功能**: 获取策略模型的回测历史记录
   - **是否新增**: ✅ **新增**

3. **`strategy/publishModel`**
   - **文件**: `D:\portfilio\src\store\modules\strategy.js`
   - **功能**: 发布策略模型
   - **是否新增**: ✅ **新增**

### 2.2 Portfolio Store Actions

**位置**: 行 705

```javascript
// 创建模拟组合
const portfolioId = await this.$store.dispatch('portfolio/createPortfolio', portfolioData);
```

**依赖的 Store Actions**:

1. **`portfolio/createPortfolio`**
   - **文件**: `D:\portfilio\src\store\modules\portfolio.js`
   - **功能**: 创建模拟组合
   - **是否新增**: ✅ **新增**

---

## 三、API 依赖

### 3.1 策略模型 API

**文件**: `D:\portfilio\src\api\strategy.js`

**使用的 API 函数**:

1. **`getStrategyModel(modelId)`** (行 78-83)
   ```javascript
   export function getStrategyModel(modelId) {
     return request({
       url: `/api/v1/strategy-models/${modelId}`,
       method: 'get'
     });
   }
   ```
   - **后端端点**: `GET /api/v1/strategy-models/{model_id}`
   - **返回数据**: 包含动量选择器参数的策略模型详情
   - **是否新增**: ✅ **新增**（用于获取包含动量选择器参数的策略详情）

2. **`publishModel(modelId)`**
   - **后端端点**: `POST /api/v1/strategy-models/{model_id}/publish`
   - **是否新增**: ✅ **新增**

### 3.2 后端 API 端点依赖

**后端文件**: `D:\portfilio-end\app\api\strategy_model.py`

**关键端点**:

1. **`GET /api/v1/strategy-models/{model_id}`** (行 234-291)
   - **功能**: 获取策略模型详情
   - **增量修改**: 行 259-282 - 从 MongoDB 原始文档读取动量选择器参数
   - **返回字段**: 
     - `enable_momentum_selection`
     - `selector_type`
     - `asset_selection_count`
     - `min_history_days`
     - `momentum_windows`
     - `tie_break_window`

---

## 四、Element UI 组件依赖

### 4.1 基础组件（用于动量选择器展示）

**位置**: 行 94-117（资产选择配置卡片）

**使用的组件**:

1. **`el-card`**
   - 用于包装"资产选择配置"卡片
   - **是否新增**: ✅ **新增**（用于展示动量选择器配置）

2. **`el-descriptions`** 和 **`el-descriptions-item`**
   - 用于展示动量选择器参数的描述列表
   - **是否新增**: ✅ **新增**（用于展示动量选择器参数）

3. **`el-tag`**
   - 用于显示"已启用"状态标签
   - **是否新增**: ✅ **新增**（用于显示启用状态）

### 4.2 其他组件（非动量选择器相关）

- `el-button` - 按钮组件
- `el-dialog` - 对话框组件
- `el-form` - 表单组件
- `el-timeline` - 时间线组件
- `el-pagination` - 分页组件
- `el-date-picker` - 日期选择器
- `el-input-number` - 数字输入框
- `el-empty` - 空状态组件

---

## 五、数据模型依赖

### 5.1 策略模型数据字段

**位置**: `model` 对象（行 476-485）

**新增字段**（与动量选择器相关）:

```javascript
model: {
  // ... 原有字段
  enable_momentum_selection: undefined,  // 新增
  selector_type: undefined,              // 新增
  asset_selection_count: undefined,       // 新增
  min_history_days: undefined,           // 新增
  momentum_windows: undefined,            // 新增
  tie_break_window: undefined             // 新增
}
```

**数据来源**: 后端 API `GET /api/v1/strategy-models/{model_id}` 返回

---

## 六、方法依赖

### 6.1 新增方法（与动量选择器相关）

**位置**: 行 847-855

```javascript
// 获取选择器名称
getSelectorName(selectorType) {
  const map = {
    'momentum': 'SHARP动量选择器',
    'reversal': '反转选择器',
    'momentum_reversal': '动量-反转混合选择器'
  };
  return map[selectorType] || selectorType || '未知';
}
```

**依赖说明**:
- **无外部依赖**：纯 JavaScript 方法，不依赖其他模块
- **功能**: 将选择器类型代码转换为中文显示名称

---

## 七、后端数据依赖

### 7.1 后端 API 返回数据格式

**后端端点**: `GET /api/v1/strategy-models/{model_id}`

**返回数据格式**（包含动量选择器参数）:

```json
{
  "id": "...",
  "name": "策略名称",
  "template_code": "...",
  "parameters": {...},
  "asset_codes": [...],
  // 以下为新增的动量选择器参数字段
  "enable_momentum_selection": true,
  "selector_type": "momentum",
  "asset_selection_count": 8,
  "min_history_days": 260,
  "momentum_windows": "22,65,260",
  "tie_break_window": 22
}
```

**后端实现位置**: 
- **`D:\portfilio-end\app\api\strategy_model.py`** (行 259-282)
- 从 MongoDB 原始文档读取动量选择器参数

---

## 八、依赖关系图

### 8.1 完整依赖关系

```
StrategyModelDetail.vue
│
├── 第三方库
│   ├── dayjs (日期处理)
│   └── echarts (图表绘制)
│
├── Vue 组件
│   ├── BacktestDialog (回测配置对话框)
│   ├── BacktestDetailDialog (回测详情对话框)
│   ├── StrategyModelForm (策略表单，用于编辑)
│   └── PortfolioDetail (组合详情)
│
├── Vuex Store
│   ├── strategy/fetchStrategyModel (获取策略详情，包含动量选择器参数)
│   ├── strategy/fetchBacktestHistory (获取回测历史)
│   ├── strategy/publishModel (发布策略)
│   └── portfolio/createPortfolio (创建组合)
│
├── API 调用
│   ├── getStrategyModel() → GET /api/v1/strategy-models/{model_id}
│   └── publishModel() → POST /api/v1/strategy-models/{model_id}/publish
│
└── Element UI 组件
    ├── el-card (资产选择配置卡片)
    ├── el-descriptions (参数展示)
    ├── el-tag (状态标签)
    └── 其他组件...
```

### 8.2 动量选择器相关的依赖（增量部分）

```
StrategyModelDetail.vue (动量选择器展示部分)
│
├── 数据来源
│   └── model 对象中的动量选择器字段
│       ├── enable_momentum_selection
│       ├── selector_type
│       ├── asset_selection_count
│       ├── min_history_days
│       ├── momentum_windows
│       └── tie_break_window
│
├── Vuex Store Action
│   └── strategy/fetchStrategyModel
│       └── 调用 API: getStrategyModel()
│           └── 后端: GET /api/v1/strategy-models/{model_id}
│               └── 返回包含动量选择器参数的数据
│
├── 方法依赖
│   └── getSelectorName() (选择器类型映射)
│
└── Element UI 组件
    ├── el-card (包装配置卡片)
    ├── el-descriptions (展示参数)
    └── el-tag (显示状态)
```

---

## 九、新增依赖详细说明

### 9.1 与动量选择器直接相关的依赖

#### 9.1.1 后端 API 数据字段

**依赖**: 后端返回的动量选择器参数字段

**字段列表**:
- `enable_momentum_selection` (boolean)
- `selector_type` (string)
- `asset_selection_count` (number)
- `min_history_days` (number)
- `momentum_windows` (string)
- `tie_break_window` (number)

**后端实现**:
- **文件**: `D:\portfilio-end\app\api\strategy_model.py`
- **位置**: 行 259-282
- **关键代码**: 从 MongoDB 原始文档读取这些字段

#### 9.1.2 Vuex Store Action

**依赖**: `strategy/fetchStrategyModel`

**文件**: `D:\portfilio\src\store\modules\strategy.js`

**功能**: 
- 调用 `getStrategyModel(modelId)` API
- 返回包含动量选择器参数的策略模型数据

**是否新增**: ✅ **新增**（用于获取包含动量选择器参数的策略详情）

#### 9.1.3 前端 API 函数

**依赖**: `getStrategyModel(modelId)`

**文件**: `D:\portfilio\src\api\strategy.js`

**位置**: 行 78-83

**功能**: 调用后端 API 获取策略模型详情

**是否新增**: ✅ **新增**

#### 9.1.4 方法依赖

**依赖**: `getSelectorName(selectorType)`

**位置**: `StrategyModelDetail.vue` 行 847-855

**功能**: 将选择器类型代码转换为中文名称

**是否新增**: ✅ **新增**

#### 9.1.5 Element UI 组件

**依赖的组件**:
- `el-card` - 用于包装资产选择配置卡片
- `el-descriptions` - 用于展示参数列表
- `el-tag` - 用于显示启用状态

**是否新增**: ✅ **新增**（用于展示动量选择器配置）

---

## 十、依赖关系对比

### 10.1 原版状态（portfolio-end1）

根据搜索结果，原版 `portfolio-end1` 中：
- **不存在** `StrategyModelDetail.vue` 文件
- **不存在** 策略模型详情页面功能
- **不存在** 动量选择器相关的前端展示代码

### 10.2 当前版本新增依赖

当前版本 `portfilio` 中，`StrategyModelDetail.vue` 的所有依赖都是新增的：

#### 10.2.1 第三方库（2个）
- ✅ `dayjs` - 日期处理
- ✅ `echarts` - 图表绘制

#### 10.2.2 Vue 组件（4个）
- ✅ `BacktestDialog` - 回测配置对话框
- ✅ `BacktestDetailDialog` - 回测详情对话框
- ✅ `StrategyModelForm` - 策略表单
- ✅ `PortfolioDetail` - 组合详情

#### 10.2.3 Vuex Store Actions（4个）
- ✅ `strategy/fetchStrategyModel` - 获取策略详情（**关键**：返回动量选择器参数）
- ✅ `strategy/fetchBacktestHistory` - 获取回测历史
- ✅ `strategy/publishModel` - 发布策略
- ✅ `portfolio/createPortfolio` - 创建组合

#### 10.2.4 API 函数（2个）
- ✅ `getStrategyModel()` - 获取策略详情 API（**关键**：返回动量选择器参数）
- ✅ `publishModel()` - 发布策略 API

#### 10.2.5 Element UI 组件（多个）
- ✅ `el-card` - 卡片组件（用于资产选择配置）
- ✅ `el-descriptions` - 描述列表（用于展示参数）
- ✅ `el-tag` - 标签组件（用于显示状态）
- ✅ 其他组件（按钮、对话框、表单等）

#### 10.2.6 方法（1个）
- ✅ `getSelectorName()` - 选择器名称映射方法

---

## 十一、关键依赖路径（动量选择器相关）

### 11.1 数据获取路径

```
StrategyModelDetail.vue
  ↓
this.$store.dispatch('strategy/fetchStrategyModel', modelId)
  ↓
src/store/modules/strategy.js → fetchStrategyModel action
  ↓
getStrategyModel(modelId) (src/api/strategy.js)
  ↓
GET /api/v1/strategy-models/{model_id} (后端 API)
  ↓
app/api/strategy_model.py → get_model endpoint
  ↓
从 MongoDB 读取策略模型数据（包含动量选择器参数）
  ↓
返回给前端
  ↓
渲染到页面（如果 enable_momentum_selection 为 true）
```

### 11.2 显示逻辑路径

```
后端返回 model 对象
  ↓
包含 enable_momentum_selection 字段
  ↓
v-if="model.enable_momentum_selection" 条件判断
  ↓
如果为 true，显示资产选择配置卡片
  ↓
使用 getSelectorName() 转换选择器类型
  ↓
显示所有动量选择器参数
```

---

## 十二、依赖文件清单

### 12.1 前端文件依赖

1. **`D:\portfilio\src\views\strategy\StrategyModelDetail.vue`** (主文件)
2. **`D:\portfilio\src\components\BacktestDialog.vue`** (回测配置对话框)
3. **`D:\portfilio\src\components\BacktestDetailDialog.vue`** (回测详情对话框)
4. **`D:\portfilio\src\views\strategy\StrategyModelForm.vue`** (策略表单)
5. **`D:\portfilio\src\views\portfolio\PortfolioDetail.vue`** (组合详情)
6. **`D:\portfilio\src\store\modules\strategy.js`** (Vuex store)
7. **`D:\portfilio\src\store\modules\portfolio.js`** (Vuex store)
8. **`D:\portfilio\src\api\strategy.js`** (API 函数)

### 12.2 后端文件依赖

1. **`D:\portfilio-end\app\api\strategy_model.py`** (API 端点)
   - `GET /api/v1/strategy-models/{model_id}` (行 234-291)
   - 从 MongoDB 读取动量选择器参数（行 259-282）

2. **`D:\portfilio-end\app\models\strategy_model.py`** (数据模型)
   - 定义动量选择器参数字段（行 224-230）

3. **`D:\portfilio-end\app\schemas\strategy_model.py`** (API Schema)
   - `StrategyModelOut` 包含动量选择器字段（行 207-212）

---

## 十三、新增依赖总结

### 13.1 与动量选择器展示直接相关的新增依赖

1. **后端数据字段** (6个)
   - `enable_momentum_selection`
   - `selector_type`
   - `asset_selection_count`
   - `min_history_days`
   - `momentum_windows`
   - `tie_break_window`

2. **Vuex Store Action** (1个)
   - `strategy/fetchStrategyModel` - 获取包含动量选择器参数的策略详情

3. **API 函数** (1个)
   - `getStrategyModel()` - 调用后端 API

4. **后端 API 端点修改** (1处)
   - `GET /api/v1/strategy-models/{model_id}` - 从 MongoDB 读取动量选择器参数

5. **前端方法** (1个)
   - `getSelectorName()` - 选择器类型映射

6. **Element UI 组件** (3个)
   - `el-card` - 配置卡片
   - `el-descriptions` - 参数列表
   - `el-tag` - 状态标签

### 13.2 文件级新增依赖

**完全新增的文件**:
- ✅ `StrategyModelDetail.vue` (整个文件)

**修改的文件**:
- ✅ `src/store/modules/strategy.js` - 添加 `fetchStrategyModel` action
- ✅ `src/api/strategy.js` - 添加 `getStrategyModel` 函数
- ✅ `app/api/strategy_model.py` - 修改 GET 端点，读取动量选择器参数

---

## 十四、依赖关系检查清单

### 14.1 前端依赖检查

- [ ] `dayjs` 是否已安装？ (`package.json`)
- [ ] `echarts` 是否已安装？ (`package.json`)
- [ ] `BacktestDialog.vue` 组件是否存在？
- [ ] `BacktestDetailDialog.vue` 组件是否存在？
- [ ] `StrategyModelForm.vue` 组件是否存在？
- [ ] `PortfolioDetail.vue` 组件是否存在？
- [ ] Vuex store `strategy` 模块是否存在？
- [ ] Vuex store `portfolio` 模块是否存在？
- [ ] API 函数 `getStrategyModel()` 是否已定义？

### 14.2 后端依赖检查

- [ ] API 端点 `GET /api/v1/strategy-models/{model_id}` 是否存在？
- [ ] 端点是否从 MongoDB 读取动量选择器参数？
- [ ] 数据模型 `StrategyModel` 是否包含动量选择器字段？
- [ ] Schema `StrategyModelOut` 是否包含动量选择器字段？

---

## 十五、注意事项

1. **数据依赖**
   - 确保后端 API 返回完整的动量选择器参数
   - 后端需要从 MongoDB 原始文档读取这些字段（因为 Pydantic 模型可能将可选字段设为 None）

2. **组件依赖**
   - 确保所有引用的组件文件都存在
   - 动态导入的组件需要确保路径正确

3. **Store 依赖**
   - 确保 Vuex store 中定义了 `fetchStrategyModel` action
   - 确保 action 正确调用 API 并返回数据

4. **向后兼容**
   - 如果后端未返回动量选择器参数，页面不会报错
   - 只有当 `enable_momentum_selection` 为 `true` 时才显示配置卡片

---

**文档生成时间**: 2026-01-26  
**参照版本**: portfolio-end1 (原版)  
**当前版本**: portfilio (增量版本)  
**主文件**: `D:\portfilio\src\views\strategy\StrategyModelDetail.vue`
