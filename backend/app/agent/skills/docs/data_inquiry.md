---
name: data_inquiry
display_name: 数据查询问数
description: 通过自然语言查询系统中的各类业务数据，支持动态发现数据集合和结构化查询
version: "1.0"
tags:
  - 查询
  - 数据
  - 产品
  - 资产
  - 净值
trigger_keywords:
  - 查询
  - 查一下
  - 有哪些
  - 看看
  - 列出
  - 多少
  - 什么数据
  - 查看
  - 帮我查
  - 找一下
exclude_keywords:
  - 深度分析
  - 归因
  - 回测
  - 创建策略
  - 评级
  - 评分
toolset:
  - data_analysis
show_plan: false
steps:
  - name: 探索可用数据
    description: 查看系统中有哪些数据集合可供查询
    tools:
      - data_query
    condition: 用户未明确指定数据类型或首次查询时
  - name: 了解数据结构
    description: 查看目标集合的字段结构和示例值
    tools:
      - data_query
    condition: 首次查询某个集合时，需要了解字段含义
  - name: 执行查询
    description: 根据用户条件查询数据
    tools:
      - data_query
---

## 数据查询工作流指导

### 核心三阶段流程：discover → schema → query/aggregate

数据查询遵循"先探索、再理解、后查询"的渐进式工作流，确保在构造查询前充分理解数据结构。

### 第一步：discover 先行

当用户提出的查询未明确指定数据集合名称时，**必须先执行数据发现**：

```
data_query(action="discover")
```

该操作返回系统中所有可用集合的名称和简要描述，帮助判断用户需求应映射到哪个集合。例如用户说"查一下R3产品"，需先发现 `products` 集合存在后再进行下一步。

### 第二步：schema 辅助

首次查询某个集合时，**必须先了解其字段结构**：

```
data_query(action="schema", collection="目标集合名")
```

返回字段名、字段类型和示例值。确认字段名的准确拼写和数据类型后，才能正确构造筛选条件，避免字段名猜测导致查询失败。

### 第三步：构造查询

根据用户需求选择 `query` 或 `aggregate`：

- **结构化查询**：筛选条件使用 `filters` 数组，每项包含 `{field, op, value}`；排序使用 `sort` 数组，每项包含 `{field, direction}`；通过 `limit` 控制返回数量。
- **统计汇总**：当用户需要计数、求和、均值等统计时，使用 `action="aggregate"` 并指定 `metrics` 数组，每项包含 `{field, agg, alias}`。

### 回复规范

1. **表格呈现**：查询结果统一以 Markdown 表格形式展示，字段名使用中文标注。
2. **摘要统计**：超过 20 条记录时，先给出摘要统计（总数、关键字段分布），再展示前 10 条代表性记录。
3. **主动引导**：查询完成后主动引导用户进一步分析，如"是否需要对这些数据做统计分析？"或"需要按某个维度进行汇总吗？"。
4. **来源注明**：回复中注明数据来源集合名称和实际使用的查询条件，方便用户验证和复现。

### 常见场景示例

| 用户说法 | 执行路径 |
|---------|---------|
| "查一下R3产品" | discover → schema(products) → query(products, filters=[{field:"risk_level", op:"eq", value:"R3"}]) |
| "有多少只基金" | discover → aggregate(funds, metrics=[{field:"_id", agg:"count", alias:"total"}]) |
| "最近净值数据" | discover → schema(daily_nav) → query(daily_nav, sort=[{field:"date", direction:"desc"}], limit=20) |
| "列出所有资产" | discover → schema(assets) → query(assets, limit=50) |
| "R2以上的产品有多少" | discover → aggregate(products, filters=[{field:"risk_level", op:"gte", value:"R2"}], metrics=[{field:"_id", agg:"count", alias:"total"}]) |
