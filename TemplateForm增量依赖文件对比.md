# TemplateForm 增量依赖文件对比

## 对比说明
本文档对比 `portfilio` 和 `portfilio1` 两个项目中 `TemplateForm` 的依赖文件，找出增量（新增）的依赖文件。

---

## TemplateForm 组件基本信息

### 文件路径
- **portfilio1**: `src/views/strategy/TemplateForm.vue`
- **portfilio**: `src/views/strategy/TemplateForm.vue`

### 组件用途
- 模板表单组件，用于创建和编辑策略模型模板
- 支持对话框模式和独立页面模式
- 包含模板基本信息、算法源代码编辑、参数配置等功能

---

## TemplateForm 的直接依赖

### 1. API 依赖
两个项目中的 API 依赖完全相同：

**文件**: `src/api/strategy.js`
- `createTemplate` - 创建模板
- `updateTemplate` - 更新模板
- `validateTemplate` - 验证模板有效性

### 2. 第三方库依赖
两个项目中的第三方库依赖完全相同：

- `codemirror` - 代码编辑器
- `codemirror/lib/codemirror.css` - 编辑器样式
- `codemirror/theme/monokai.css` - 编辑器主题
- `codemirror/mode/python/python` - Python 语法高亮

---

## 使用 TemplateForm 的文件

### portfilio1 中的使用
1. **TemplateList.vue**
   - 路径: `src/views/strategy/TemplateList.vue`
   - 使用方式: 作为对话框组件使用
   - 代码位置: 第187行 `<template-form>`，第225行 `import('./TemplateForm.vue')`

2. **router/index.js**
   - 路径: `src/router/index.js`
   - 使用方式: 路由配置
   - 代码位置: 
     - 第75行: `template/add` 路由
     - 第81行: `template/edit/:id` 路由

### portfilio 中的使用
1. **TemplateList.vue**
   - 路径: `src/views/strategy/TemplateList.vue`
   - 使用方式: 作为对话框组件使用
   - 代码位置: 第187行 `<template-form>`，第225行 `import('./TemplateForm.vue')`

2. **router/index.js**
   - 路径: `src/router/index.js`
   - 使用方式: 路由配置
   - 代码位置: 
     - 第75行: `template/add` 路由
     - 第81行: `template/edit/:id` 路由

---

## 增量依赖文件分析

### 对比结果
✅ **无增量依赖文件**

两个项目中 `TemplateForm` 的依赖关系完全相同：
- 相同的 API 依赖
- 相同的第三方库依赖
- 相同的使用位置（TemplateList.vue 和 router/index.js）

### 详细对比

| 依赖类型 | portfilio1 | portfilio | 是否相同 |
|---------|-----------|----------|---------|
| API 文件 | `src/api/strategy.js` | `src/api/strategy.js` | ✅ 相同 |
| 使用组件 | `TemplateList.vue` | `TemplateList.vue` | ✅ 相同 |
| 路由配置 | `router/index.js` | `router/index.js` | ✅ 相同 |
| 第三方库 | codemirror 相关 | codemirror 相关 | ✅ 相同 |

---

## 相关文件对比

### TemplateList.vue 对比
两个项目中的 `TemplateList.vue` 使用 `TemplateForm` 的方式完全相同：
```vue
<!-- 两个项目都使用相同的代码 -->
<template-form
  v-if="formDialogVisible"
  is-dialog
  :code="currentTemplateCode"
  @success="handleFormSuccess"
  @close="formDialogVisible = false"
/>
```

### router/index.js 对比
两个项目中的路由配置完全相同：
```javascript
// 两个项目都使用相同的路由配置
{
  path: 'template/add',
  name: 'TemplateAdd',
  component: () => import('@/views/strategy/TemplateForm.vue'),
  meta: { title: '新增模板', hidden: true }
},
{
  path: 'template/edit/:id',
  name: 'TemplateEdit',
  component: () => import('@/views/strategy/TemplateForm.vue'),
  meta: { title: '编辑模板', hidden: true }
}
```

---

## 结论

### 增量文件数量
**0 个增量依赖文件**

`TemplateForm` 在两个项目中的依赖关系完全相同，没有新增的依赖文件。

### 说明
虽然 `portfilio` 项目中有新增的文件（如 `BacktestExecution.vue`、`backtest/` 目录下的文件等），但这些文件与 `TemplateForm` 没有依赖关系，因此不属于 `TemplateForm` 的增量依赖。

---

## 依赖关系图

### portfilio1 和 portfilio（相同）
```
TemplateForm.vue
  ├── API 依赖
  │   └── @/api/strategy.js
  │       ├── createTemplate
  │       ├── updateTemplate
  │       └── validateTemplate
  │
  ├── 第三方库依赖
  │   ├── codemirror
  │   ├── codemirror/lib/codemirror.css
  │   ├── codemirror/theme/monokai.css
  │   └── codemirror/mode/python/python
  │
  └── 被使用
      ├── TemplateList.vue (对话框模式)
      └── router/index.js (路由配置)
```

---

## 文件清单

### portfilio1 中的相关文件
```
src/views/strategy/TemplateForm.vue
src/views/strategy/TemplateList.vue
src/router/index.js
src/api/strategy.js
```

### portfilio 中的相关文件
```
src/views/strategy/TemplateForm.vue
src/views/strategy/TemplateList.vue
src/router/index.js
src/api/strategy.js
```

### 增量文件
**无增量文件**

---

## 迁移注意事项

如果从 `portfilio1` 迁移到 `portfilio`，关于 `TemplateForm`：

1. **无需额外操作**: `TemplateForm` 的依赖关系在两个项目中完全相同
2. **文件可直接复用**: `TemplateForm.vue` 文件可以直接复制使用
3. **依赖已存在**: 所有依赖的 API 和第三方库在两个项目中都已存在

---

## 快速参考

### TemplateForm 依赖文件路径
```
src/api/strategy.js (API 依赖)
src/views/strategy/TemplateList.vue (使用组件)
src/router/index.js (路由配置)
```

### 第三方依赖
```
codemirror (npm 包)
codemirror/lib/codemirror.css
codemirror/theme/monokai.css
codemirror/mode/python/python
```
