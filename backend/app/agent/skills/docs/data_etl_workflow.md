---
name: data_etl_workflow
display_name: 数据加工工作流
description: 对原始数据进行关联、并集、维度映射、清洗、转换、透视等加工操作，支持将加工流程保存为可复用模板
version: "2.0"
tags:
  - 加工
  - 清洗
  - ETL
  - 转换
  - 合并
  - 连接
  - 并集
  - 维度映射
  - 多表关联
trigger_keywords:
  - 合并
  - 关联
  - 清洗
  - 加工
  - 整合
  - 拼接
  - 转换
  - 标准化
  - 透视
  - 宽表
  - 长表
  - 连接
  - 多表
  - 并集
  - 堆叠
  - 维度
  - 映射
  - 机构名
  - 编码替换
  - 左连接
  - 全连接
exclude_keywords:
  - 评级
  - 回测
  - 策略
  - 报告
toolset:
  - data_analysis
show_plan: true
steps:
  - name: 识别数据源
    description: 探索可用数据集合，确认需要加工的原始数据
    tools:
      - data_query
  - name: 获取原始数据
    description: 查询需要加工的数据（多表关联时分别查询左表和右表）
    tools:
      - data_query
  - name: 执行加工
    description: 按用户要求进行表连接、并集堆叠、维度映射、清洗或转换
    tools:
      - data_transform
  - name: 质量验证
    description: 对加工后的数据进行异常检测，确认数据质量
    tools:
      - data_analyze
    condition: 数据加工后需要验证质量时
  - name: 结果可视化
    description: 将加工结果生成图表展示
    tools:
      - data_visualize
    condition: 用户需要可视化展示时
  - name: 保存为模板
    description: 将此加工流程保存为可复用模板
    tools:
      - data_template
    condition: 用户希望以后复用此加工流程时
---

## 数据加工工作流指导

### 核心流程

数据加工遵循“发现数据 → 获取原始数据 → 执行加工 → 质量验证 → 可选保存模板”的工作流。
每个加工操作对应 `data_transform` 工具的一种 action 类型。

### 数据获取

加工前必须先确认数据源：
1. 使用 `data_query(action="discover")` 探索系统中可用的数据集合
2. 使用 `data_query(action="schema", collection="目标集合")` 了解字段结构
3. 使用 `data_query(action="query", collection="目标集合")` 获取原始数据

多数据源场景下，需分别获取各数据集，确认关联字段名称和类型一致。

---

### 八种加工类型

#### 1. join — 专业多表连接（金融核心能力）

> 适用：客户信息左连贷款合同、产品持仓关联、任何需要多关联键或唯一性校验的场景

```
data_transform(
  action="join",
  left_ref="customer_data",       # 左表：客户基本信息
  right_ref="loan_data",          # 右表：贷款合同
  config={
    "join_keys": "客户号",          # 关联键（字符串或数组）
    "join_type": "left",           # left/right/inner/outer
    "validate": "one_to_many",    # 唯一性校验：客户号在左表唯一
    "suffixes": ["_客户", "_合同"]  # 重名列后缀
  }
)
```

支持的 join_type：`left`（默认）、`right`、`inner`、`outer`

支持的 validate：`many_to_many`（默认，不校验）、`one_to_one`、`one_to_many`、`many_to_one`

复合关联键示例：
```
config={"join_keys": ["客户号", "产品类型"], "join_type": "inner"}
```

#### 2. union — 纵向并集运算

> 适用：将不同时间切片的数据纵向并入整年表，合并多渠道数据

```
data_transform(
  action="union",
  sources=["jan_txn", "feb_txn", "mar_txn", ..., "dec_txn"],  # 各月流水引用
  config={"mode": "all"}   # all=UNION ALL(>保留重复), distinct=自动去重
)
```

支持的 mode：`all`（UNION ALL，默认）、`distinct`（去重）

`fill_missing: true`（默认）自动将缺失列填 null；`false` 则仅保留公共列。

#### 3. map_dimension — 维度映射

> 适用：将交易流水中的内部机构号映射为分行中文名称，须风险等级编码映射为中文描述

```
data_transform(
  action="map_dimension",
  source_ref="txn_data",           # 主表：交易流水
  config={
    "key_field": "branch_code",    # 主表编码字段
    "map_source_ref": "branch_dim", # 映射表：机构维表
    "map_key_field": "code",        # 映射表键
    "map_value_field": "branch_name", # 映射表值
    "output_field": "branch_name",  # 新列名（不填则覆盖 key_field）
    "keep_unmapped": true           # 未命中时保留原编码
  }
)
```

命中率低于 100% 时返回结果中会附加未命中条数提示，方便模型判断映射完整性。

#### 4. merge — 简单单键关联（向后兼容）

```
data_transform(action="merge", source_data={...}, config={right_data: {...}, join_key: "asset_code", join_type: "left"})
```

> 注：建议新场景使用 `join`，`merge` 为已有接口保留。

#### 5. filter — 条件过滤

```
data_transform(action="filter", source_ref="目标集合", config={conditions: [{field: "status", op: "eq", value: "active"}]})
```

#### 6. resample — 时间序列重采样

```
data_transform(action="resample", source_ref="daily_nav", config={freq: "M", method: "last"})
```

freq 可选值：`W`（周）、`M`（月）、`Q`（季）。method 可选：`last`、`mean`、`sum`

#### 7. pivot — 透视聚合

```
data_transform(action="pivot", source_ref="目标集合", config={index: "date", columns: "asset_code", values: "nav", aggfunc: "last"})
```

#### 8. normalize — 列名映射/格式转换

```
data_transform(action="normalize", source_ref="目标集合", config={mappings: {"R1": "低风险", "R2": "中低风险"}, fill_na: {method: "ffill"}})
```

> 注：`normalize` 做的是列名重命名，如需字段值级的编码映射请使用 `map_dimension`。

---

### 质量验证

加工完成后，建议使用异常检测验证数据质量：
```
data_analyze(action="anomaly", data_ref="加工结果引用")
```
检查项包括：缺失值比例、重复行、数值范围异常、时间序列断点等。

### 模板保存与复用

当用户希望将当前加工流程保存为模板以便后续复用：
```
data_template(action="save", name="模板名称", description="模板描述")
```
保存后可通过 `data_template(action="list")` 查看已有模板，`data_template(action="execute", template_id="xxx")` 直接执行。

---

### 金融场景典型示例

| 用户说法 | 执行路径 |
|---------|--------|
| "客户信息左连贷款合同" | query(客户表) + query(合同表) → transform(join, left, join_keys=客户号, validate=one_to_many) |
| "将全年月度流水并成一张年度明细" | query(1月12个月分) → transform(union, sources=[jan..dec], mode=all) |
| "机构号映射为分行名称" | query(流水表) + query(机构维表) → transform(map_dimension, key_field=branch_code) |
| "风险等级中文化" | query(产品表) → transform(map_dimension, map_source=[{R1:低}, {R2:中低}...]) |
| "把产品净值表按代码合并成宽表" | query(daily_nav) → transform(pivot, index=date, columns=asset_code, values=nav) |
| "日度数据转月度" | query(daily_data) → transform(resample, freq=M, method=last) |
| "清掉测试数据" | query(目标集合) → transform(filter, conditions=[{is_test: ne: true}]) |
