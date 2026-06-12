# 数据血缘 × 数据语义层 — 前后端全链路嵌入需求设计书 V2

**版本**: v2.0  
**设计日期**: 2026-06-03  
**目标项目**: `portfilio-end` (金融资管数据平台)  
**关联项目**: `stock-research-end` (投研智能体平台)  

---

## 目录

1. [战略愿景与目标](#一战略愿景与目标)
2. [现状基线分析](#二现状基线分析)
3. [差距分析矩阵](#三差距分析矩阵)
4. [四层数据语义画像体系](#四五层数据语义画像体系)
5. [总体架构设计](#五总体架构设计)
6. [六大模块详细设计与意义解读](#六六大模块详细设计与意义解读)
7. [数据模型设计](#七数据模型设计)
8. [接口契约设计](#八接口契约设计)
9. [前后端链路改造](#九前后端链路改造)
10. [Agent链路改造](#十agent链路改造)
11. [改造范围清单](#十一改造范围清单)
12. [实施路线图](#十二实施路线图)
13. [风险与对策](#十三风险与对策)

---

## 一、战略愿景与目标

### 1.1 愿景

构建**全链路语义感知、端到端血缘可追溯**的金融资管数据平台，实现：

- **数据可信**: 任何数据点均可追溯至原始来源，知晓"这个数据从哪来、怎么算的、什么时候更新的"
- **语义统一**: 前后端、人机交互使用同一套业务语义，消除"字段名与业务含义脱节"的鸿沟
- **智能增强**: Agent具备数据语义感知能力，能解释字段含义、推荐查询路径、评估数据质量
- **影响可控**: 上游数据变更时，能精准评估下游影响范围，降低"改了A导致B出错"的风险

### 1.2 目标能力矩阵

| 能力维度 | 现状 | 目标 | 度量指标 |
|---------|------|------|----------|
| 语义层覆盖 | 概念层(9域82表) | 概念层+逻辑层+物理层+质量层 | 字段级语义覆盖率100% |
| 血缘追踪 | 无 | 端到端(上游API→存储→查询→消费) | 链路完整率>95% |
| 血缘粒度 | 无 | 字段级 | 字段级血缘占比>80% |
| 前端语义 | 无 | Schema语义标注+字段Tooltip | 关键字段覆盖率100% |
| Agent语义 | 离散式(schema+示例查询) | 统一语义服务层 | 查询意图理解准确率>90% |
| 数据质量 | 无 | 质量徽章+评分 | 质量评分覆盖率100% |

---

## 二、现状基线分析

### 2.1 项目结构

```
portfilio-end/
├── app/
│   ├── agent/
│   │   ├── services/
│   │   │   └── data_context.py          # 会话级数据上下文 (已有)
│   │   └── tools/
│   │       ├── data_query_tool.py       # 数据查询工具 (已有)
│   │       ├── data_analyze_tool.py     # 数据分析工具 (已有)
│   │       └── data_visualize_tool.py   # 数据可视化工具 (已有)
│   ├── api/
│   │   ├── zy_data.py                   # 前端数据探索API (已有)
│   │   └── data_hub.py                  # 数据接入API (已有)
│   ├── models/
│   │   └── data_connector.py            # 连接器定义 (已有)
│   ├── services/
│   │   ├── collection_registry.py       # 集合注册中心 (已有)
│   │   ├── generic_query_engine.py      # 通用查询引擎 (已有)
│   │   ├── data_hub_service.py          # 数据接入服务 (已有)
│   │   └── template_service.py          # 模板服务 (已有)
│   └── config/
│       └── settings.py                  # 配置 (已有)
├── scripts/
│   └── refresh_registry.py              # 注册表刷新脚本 (已有)
└── docs/
    └── data_lineage_architecture_design.md  # 血缘架构设计V1 (已有)
```

### 2.2 现有语义/血缘基础设施

| 组件 | 位置 | 现状 | 可利用度 |
|------|------|------|----------|
| `DOMAIN_METADATA` | `collection_registry.py` | 9域82表概念层元数据 | ⭐⭐⭐⭐⭐ 核心基础 |
| `ConnectorDefinition` | `data_connector.py` | 3个连接器定义，含UI字段/图表配方 | ⭐⭐⭐⭐ 血缘锚点 |
| `_collection_registry` | MongoDB | 动态推断的集合schema | ⭐⭐⭐⭐ 物理层基础 |
| `_query_audit_log` | MongoDB | 查询审计日志 | ⭐⭐⭐ 事后回溯源 |
| `DataContext._tool_history` | `data_context.py` | 工具调用历史 | ⭐⭐⭐ 运行时追踪 |
| `chart_recipes` | `ConnectorDefinition` | 前端图表配方 | ⭐⭐ 消费端锚点 |
| `foreign_keys` | `DOMAIN_METADATA` | 文本声明的外键 | ⭐⭐ 跨域关联基础 |

### 2.3 现有链路分析

**前端链路**: `zyDataDomain.js` → `zy_data.py` API → `GenericQueryEngine` → MongoDB
- 问题: API返回纯数据，无任何语义元数据
- 问题: 前端不知道字段的业务含义

**Agent链路**: `data_query_tool.py` → `DataContext` → schema/示例查询
- 问题: 语义感知离散（schema和示例查询分离）
- 问题: 无统一语义服务层
- 问题: Agent无法解释字段含义

**数据接入链路**: `DataHubService.import_from_upstream()` → 上游API → MongoDB
- 问题: 无血缘记录，不知道数据从哪来
- 问题: 无质量评估

---

## 三、差距分析矩阵

### 3.1 语义层差距

| 层级 | 现状 | 目标 | 差距描述 |
|------|------|------|----------|
| **概念层** | ✅ `DOMAIN_METADATA`(9域82表) | 扩展为语义实体定义 | 缺语义实体、跨域关联链、术语表 |
| **逻辑层** | ❌ 无 | 逻辑表/字段定义 | 缺逻辑模型、字段级语义画像 |
| **物理层** | ⚠️ 动态推断schema | 物理映射+质量画像 | 缺静态物理映射、缺质量评分 |
| **质量层** | ❌ 无 | 质量画像+评分 | 完全缺失 |

### 3.2 血缘追踪差距

| 追踪维度 | 现状 | 目标 | 差距描述 |
|---------|------|------|----------|
| **数据源血缘** | ❌ 无 | 上游API→存储 | `DataHubService`无血缘记录 |
| **工具调用血缘** | ⚠️ `_tool_history` | 完整工具链追踪 | 缺节点/边模型、缺转换逻辑 |
| **查询血缘** | ⚠️ `_query_audit_log` | 查询→结果血缘 | 缺查询结果与数据源的关联 |
| **消费端血缘** | ❌ 无 | 存储→前端/Agent | 缺前端页面级、Agent对话级锚点 |
| **字段级血缘** | ❌ 无 | 字段级影响分析 | 完全缺失 |

### 3.3 前后端链路差距

| 链路环节 | 现状 | 目标 | 差距描述 |
|---------|------|------|----------|
| **Schema返回** | 字段名+类型 | 字段名+类型+语义 | 缺display_name、description、单位、枚举值 |
| **查询结果** | 纯数据数组 | 数据+语义元数据 | 缺`_semantic_meta`包裹 |
| **字段Tooltip** | 无 | 业务语义提示 | 前端无语义展示组件 |
| **DeepLink** | ❌ 无 | 对话成果物→前端跳转 | 完全缺失 |

### 3.4 Agent链路差距

| 能力 | 现状 | 目标 | 差距描述 |
|------|------|------|----------|
| **Schema获取** | 动态推断 | 语义增强Schema | 缺字段语义描述 |
| **查询推荐** | 固定示例查询 | 智能查询推荐 | 缺基于语义的推荐引擎 |
| **字段解释** | 无 | 解释字段含义 | 缺术语表和字段画像 |
| **质量感知** | 无 | 告知数据质量 | 缺质量评分机制 |
| **血缘解释** | 无 | 解释数据来源 | 缺血缘查询能力 |

---

## 四、四层数据语义画像体系

### 4.1 体系总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        四层数据语义画像体系                                   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  L1: 基础语义画像层 (Foundation Semantic Profile)                    │    │
│  │  ─────────────────────────────────────────────────────────────────  │    │
│  │  定位: 字段级最小语义单元，回答"这个字段是什么"                        │    │
│  │  内容: 中文名、数据类型、业务定义、示例值、枚举值、单位               │    │
│  │  应用: 前端Tooltip、表头渲染、Agent字段解释                           │    │
│  │  示例: AST_CD → "证券代码" / "唯一标识一只可交易证券的代码"            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              ↓                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  L2: 关联语义画像层 (Relational Semantic Profile)                    │    │
│  │  ─────────────────────────────────────────────────────────────────  │    │
│  │  定位: 字段在关系网络中的位置，回答"这个字段跟谁有关"                  │    │
│  │  内容: 主键/外键关系、关联表、Cardinality、跨域映射、关联链           │    │
│  │  应用: 血缘图谱、跨域查询推荐、JOIN条件生成                           │    │
│  │  示例: ISR_ID → 外键引用dwd_isr_institution.ISR_ID / 1:N            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              ↓                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  L3: 特征语义画像层 (Characteristic Semantic Profile)                │    │
│  │  ─────────────────────────────────────────────────────────────────  │    │
│  │  定位: 字段的业务特征标签，回答"这个字段有什么特性"                    │    │
│  │  内容: 特征标签、敏感等级、时序属性、计算属性、检索属性               │    │
│  │  应用: 权限控制、查询优化、数据分类、合规检查                         │    │
│  │  示例: CUSTOMER_ID → ["敏感字段", "检索键", "不可聚合"]               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              ↓                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  L4: 质量语义画像层 (Quality Semantic Profile)                       │    │
│  │  ─────────────────────────────────────────────────────────────────  │    │
│  │  定位: 字段的数据质量评估，回答"这个字段的数据靠谱吗"                  │    │
│  │  内容: 唯一性、完整性、一致性、时效性、准确性评分                     │    │
│  │  应用: 质量徽章、数据可信度提示、低质量告警、清洗优先级               │    │
│  │  示例: COUPON_RATE → 完整性98% / 一致性95% / 时效性100%              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 L1: 基础语义画像层

#### 4.2.1 设计目标

**回答核心问题**: "这个字段是什么？"

基础语义画像层是语义体系的最小单元，为每个字段建立"身份证"——让机器和人都能一眼看懂字段的业务含义。

#### 4.2.2 画像内容

| 维度 | 字段 | 说明 | 示例 |
|------|------|------|------|
| **标识信息** | `field_name` | 物理字段名 | `AST_CD` |
| | `display_name` | 中文显示名 | `证券代码` |
| | `collection_name` | 所属集合 | `dwd_ast_info` |
| **类型信息** | `data_type` | 数据类型 | `string` / `decimal` / `datetime` |
| | `length` | 长度限制 | `32` |
| | `precision` | 精度 | `decimal(18,4)` |
| **业务语义** | `business_definition` | 业务定义 | `唯一标识一只可交易证券的代码` |
| | `business_category` | 业务分类 | `标识类` / `金额类` / `日期类` / `枚举类` |
| | `example_values` | 示例值 | `["BOND_2024_001", "STK_688521_SH"]` |
| **枚举信息** | `enum_values` | 枚举值及含义 | `[{"value": "1", "label": "债券"}, {"value": "2", "label": "股票"}]` |
| | `enum_source` | 枚举值来源 | `ZY系统码表` / `自定义` |
| **计量信息** | `unit` | 计量单位 | `%` / `万元` / `BP` / `元` |
| | `unit_conversion` | 单位换算 | `{"display_unit": "万元", "storage_unit": "元", "factor": 10000}` |
| **版本信息** | `version` | 画像版本 | `1.0` |
| | `effective_date` | 生效日期 | `2024-01-01` |
| | `owner` | 维护责任人 | `数据架构组` |

#### 4.2.3 数据模型

```python
class L1_FoundationSemanticProfile(BaseModel):
    """L1: 基础语义画像层 — 字段级最小语义单元"""
    
    # 标识信息
    field_name: str
    display_name: str
    collection_name: str
    domain: str  # "asset" | "trading" | "valuation" | ...
    
    # 类型信息
    data_type: str  # "string" | "int" | "decimal" | "datetime" | "bool"
    length: Optional[int] = None
    precision: Optional[str] = None  # "decimal(18,4)"
    nullable: bool = True
    default_value: Optional[str] = None
    
    # 业务语义
    business_definition: str  # 业务定义
    business_category: str  # "标识类" | "金额类" | "日期类" | "枚举类" | "计算类" | "描述类"
    example_values: list[str] = []  # 示例值
    
    # 枚举信息
    enum_values: Optional[list[dict]] = None  # [{"value": "1", "label": "债券", "description": ""}]
    enum_source: Optional[str] = None  # "ZY系统码表" | "自定义"
    
    # 计量信息
    unit: Optional[str] = None  # "%" | "万元" | "BP" | "元"
    unit_conversion: Optional[dict] = None  # {"display_unit": "万元", "storage_unit": "元", "factor": 10000}
    
    # 版本信息
    version: str = "1.0"
    effective_date: datetime
    owner: str = "system"
    status: str = "active"  # "active" | "deprecated" | "draft"
    
    created_at: datetime
    updated_at: datetime
```

#### 4.2.4 应用场景

| 场景 | 应用方式 | 效果 |
|------|----------|------|
| **前端表头渲染** | `display_name`替代`field_name` | 用户看到"证券代码"而非"AST_CD" |
| **字段Tooltip** | `business_definition` + `example_values` | 鼠标悬停显示业务含义和示例 |
| **Agent字段解释** | 注入Prompt: "{field}是{display_name}，{business_definition}" | Agent能准确解释字段含义 |
| **枚举值提示** | `enum_values`渲染下拉选项 | 用户知道"1=债券, 2=股票" |
| **单位显示** | `unit`附加在数值后 | 显示"3.5%"而非"0.035" |

#### 4.2.5 意义解读

> **为什么需要L1？**
> 
> 金融数据系统的字段命名通常采用缩写+下划线形式（如`AST_CD`、`VAL_NET_PRC`），这对业务人员极不友好。L1基础语义画像层建立了"物理字段名→业务语义"的映射，是消除"技术-业务"鸿沟的第一道桥梁。
> 
> **核心价值**:
> - **降低认知成本**: 业务人员无需记忆字段缩写含义
> - **减少沟通歧义**: "证券代码"比"AST_CD"更不容易被误解
> - **赋能AI理解**: Agent通过L1理解字段含义，生成更准确的查询和分析

---

### 4.3 L2: 关联语义画像层

#### 4.3.1 设计目标

**回答核心问题**: "这个字段跟谁有关？"

关联语义画像层描述字段在数据关系网络中的位置——它是主键还是外键？它引用了哪个表？跨系统时它叫什么名字？

#### 4.3.2 画像内容

| 维度 | 字段 | 说明 | 示例 |
|------|------|------|------|
| **键关系** | `is_primary_key` | 是否主键 | `true` |
| | `is_foreign_key` | 是否外键 | `true` |
| | `foreign_key_ref` | 外键引用 | `dwd_isr_institution.ISR_ID` |
| | `is_unique` | 是否唯一 | `true` |
| | `is_indexed` | 是否索引 | `true` |
| **关联表** | `related_tables` | 关联表列表 | `["dwd_ast_info_ch", "dwd_trd_trade"]` |
| | `related_fields` | 关联字段列表 | `[{"collection": "dwd_ast_info_ch", "field": "AST_CD"}]` |
| **Cardinality** | `cardinality` | 关联基数 | `1:1` / `1:N` / `N:M` |
| **跨域映射** | `cross_domain_mapping` | 跨系统名称映射 | `{"zy_system": "AST_CD", "jy_system": "SEC_ID", "ta_system": "FUND_CODE"}` |
| | `mapping_type` | 映射类型 | `direct` / `derived` / `lookup` |
| **关联链** | `association_chains` | 所属关联链 | `["asset_to_issuer", "asset_to_valuation"]` |
| | `join_conditions` | JOIN条件模板 | `"{table1}.AST_CD = {table2}.AST_CD"` |

#### 4.3.3 数据模型

```python
class L2_RelationalSemanticProfile(BaseModel):
    """L2: 关联语义画像层 — 字段在关系网络中的位置"""
    
    # 键关系
    is_primary_key: bool = False
    is_foreign_key: bool = False
    foreign_key_ref: Optional[str] = None  # "dwd_isr_institution.ISR_ID"
    is_unique: bool = False
    is_indexed: bool = False
    index_type: Optional[str] = None  # "btree" | "hash" | "compound"
    
    # 关联表
    related_tables: list[str] = []  # 关联的表名列表
    related_fields: list[dict] = []  # [{"collection": "xxx", "field": "xxx", "relation": "1:N"}]
    
    # Cardinality
    cardinality: Optional[str] = None  # "1:1" | "1:N" | "N:M" | "N:1"
    
    # 跨域映射
    cross_domain_mapping: dict = {}  # {"zy_system": "AST_CD", "jy_system": "SEC_ID"}
    mapping_type: str = "direct"  # "direct" | "derived" | "lookup" | "transform"
    mapping_logic: Optional[str] = None  # 转换逻辑，如"substring(SEC_ID, 1, 6)"
    
    # 关联链
    association_chains: list[str] = []  # ["asset_to_issuer", "asset_to_valuation"]
    join_conditions: list[str] = []  # JOIN条件模板
    
    # 跨域关联键标记
    is_cross_domain_key: bool = False  # 是否为跨域关联键
    cross_domain_key_type: Optional[str] = None  # "primary" | "secondary" | "alternate"
    
    created_at: datetime
    updated_at: datetime
```

#### 4.3.4 应用场景

| 场景 | 应用方式 | 效果 |
|------|----------|------|
| **血缘图谱构建** | `foreign_key_ref` + `related_tables` | 自动生成表间关联边 |
| **跨域查询推荐** | `cross_domain_mapping` + `association_chains` | Agent推荐"查茅台的发行人"→自动JOIN dwd_isr_institution |
| **数据一致性检查** | `cross_domain_mapping` | 对比ZY系统的AST_CD和JY系统的SEC_ID是否一致 |
| **JION条件生成** | `join_conditions` | 自动生成SQL/MongoDB聚合的$lookup条件 |
| **影响分析** | `related_tables` + `cardinality` | 评估字段变更对下游表的影响范围 |

#### 4.3.5 意义解读

> **为什么需要L2？**
> 
> 金融数据的核心价值在于关联分析——"某只债券的发行人财务状况如何？""某个客户的所有持仓风险暴露是多少？"这些问题的回答依赖于跨表、跨域的关联能力。L2关联语义画像层将隐式的关联关系显性化，使机器能够自动理解和利用这些关系。
> 
> **核心价值**:
> - **自动化关联**: Agent无需人工告知，自动知道"AST_CD可以关联到dwd_isr_institution.ISR_ID"
> - **跨域整合**: 识别不同系统中同一业务概念的不同字段名（ZY的AST_CD = JY的SEC_ID）
> - **影响可控**: 修改字段时，精准评估下游影响范围

---

### 4.4 L3: 特征语义画像层

#### 4.4.1 设计目标

**回答核心问题**: "这个字段有什么特性？"

特征语义画像层为字段打上业务特征标签，描述字段在数据处理、权限控制、查询优化等方面的特性。

#### 4.4.2 画像内容

| 维度 | 字段 | 说明 | 示例 |
|------|------|------|------|
| **特征标签** | `tags` | 特征标签列表 | `["主键", "跨域关联键", "检索键"]` |
| **敏感属性** | `sensitivity_level` | 敏感等级 | `P1`(公开) / `P2`(内部) / `P3`(机密) / `P4`(绝密) |
| | `is_pii` | 是否个人身份信息 | `true` |
| | `masking_rule` | 脱敏规则 | `phone: 138****1234` / `idcard: 前3后4` / `full: ***` |
| **时序属性** | `is_temporal` | 是否时序字段 | `true` |
| | `temporal_type` | 时序类型 | `biz_date` / `create_time` / `update_time` / `valid_from` |
| | `temporal_granularity` | 时序粒度 | `day` / `month` / `quarter` / `year` |
| **计算属性** | `is_computed` | 是否计算字段 | `true` |
| | `computation_formula` | 计算公式 | `VAL_NET_PRC = VAL_FULL_PRC - ACCRUED_INTEREST` |
| | `computation_dependencies` | 计算依赖字段 | `["VAL_FULL_PRC", "ACCRUED_INTEREST"]` |
| **检索属性** | `is_searchable` | 是否可检索 | `true` |
| | `search_weight` | 检索权重 | `10` (高权重) |
| | `full_text_index` | 是否全文索引 | `true` |
| **聚合属性** | `is_aggregatable` | 是否可聚合 | `true` |
| | `default_aggregation` | 默认聚合方式 | `sum` / `avg` / `count` / `min` / `max` |
| | `aggregation_restrictions` | 聚合限制 | `["不可跨产品聚合"]` |

#### 4.4.3 特征标签体系

```python
# 预定义特征标签体系
FEATURE_TAGS = {
    # 键类型标签
    "primary_key": "主键 — 唯一标识一条记录",
    "foreign_key": "外键 — 引用其他表的主键",
    "cross_domain_key": "跨域关联键 — 跨系统/域关联的关键字段",
    "business_key": "业务主键 — 业务层面唯一标识",
    "surrogate_key": "代理键 — 系统生成的唯一标识",
    
    # 数据类型标签
    "temporal_field": "时序字段 — 包含时间信息",
    "amount_field": "金额字段 — 表示货币金额",
    "rate_field": "利率/比率字段 — 表示百分比或比率",
    "enum_field": "枚举字段 — 取值范围有限",
    "text_field": "文本字段 — 自由文本",
    
    # 业务特征标签
    "sensitive_field": "敏感字段 — 需要脱敏处理",
    "pii_field": "PII字段 — 个人身份信息",
    "computed_field": "计算字段 — 由其他字段计算得出",
    "derived_field": "派生字段 — 从其他数据源派生",
    "static_field": "静态字段 — 极少变更",
    "volatile_field": "易变字段 — 频繁变更",
    
    # 查询特征标签
    "search_key": "检索键 — 常用于查询条件",
    "sort_key": "排序键 — 常用于排序",
    "group_key": "分组键 — 常用于GROUP BY",
    "filter_key": "过滤键 — 常用于WHERE条件",
    "high_cardinality": "高基数 — 唯一值数量多",
    "low_cardinality": "低基数 — 唯一值数量少",
    
    # 质量特征标签
    "mandatory_field": "必填字段 — 不可为空",
    "nullable_field": "可空字段 — 允许为空",
    "default_field": "有默认值 — 空值时有默认填充",
}
```

#### 4.4.4 数据模型

```python
class L3_CharacteristicSemanticProfile(BaseModel):
    """L3: 特征语义画像层 — 字段的业务特征标签"""
    
    # 特征标签
    tags: list[str] = []  # 从FEATURE_TAGS中选取
    custom_tags: list[str] = []  # 自定义标签
    
    # 敏感属性
    sensitivity_level: str = "P1"  # "P1" | "P2" | "P3" | "P4"
    is_pii: bool = False
    masking_rule: Optional[str] = None  # 脱敏规则名称
    masking_config: Optional[dict] = None  # {"type": "phone", "pattern": "{prefix}****{suffix}"}
    
    # 时序属性
    is_temporal: bool = False
    temporal_type: Optional[str] = None  # "biz_date" | "create_time" | "update_time" | "valid_from" | "valid_to"
    temporal_granularity: Optional[str] = None  # "day" | "month" | "quarter" | "year"
    temporal_format: Optional[str] = None  # "%Y-%m-%d" | "%Y%m%d"
    
    # 计算属性
    is_computed: bool = False
    computation_formula: Optional[str] = None
    computation_dependencies: list[str] = []
    computation_trigger: Optional[str] = None  # "on_insert" | "on_update" | "scheduled"
    
    # 检索属性
    is_searchable: bool = True
    search_weight: int = 1  # 1-100
    full_text_index: bool = False
    search_analyzer: Optional[str] = None  # "standard" | "ik_max_word"
    
    # 聚合属性
    is_aggregatable: bool = True
    default_aggregation: Optional[str] = None  # "sum" | "avg" | "count" | "min" | "max"
    aggregation_restrictions: list[str] = []
    
    # 生命周期属性
    is_active: bool = True
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    
    created_at: datetime
    updated_at: datetime
```

#### 4.4.5 应用场景

| 场景 | 应用方式 | 效果 |
|------|----------|------|
| **权限控制** | `sensitivity_level` + `is_pii` | P3/P4字段自动脱敏，PII字段限制访问 |
| **查询优化** | `is_indexed` + `search_weight` | 优先使用索引字段，高权重字段优先匹配 |
| **数据分类** | `tags` | 自动识别金额字段、时序字段、敏感字段 |
| **合规检查** | `is_pii` + `masking_rule` | 自动检测PII字段是否脱敏 |
| **计算溯源** | `computation_formula` + `computation_dependencies` | 知道VAL_NET_PRC由哪些字段计算得出 |
| **聚合推荐** | `default_aggregation` | Agent知道"收益率"用avg，"持仓金额"用sum |

#### 4.4.6 意义解读

> **为什么需要L3？**
> 
> 不同字段有不同的"性格"——有些敏感需要脱敏，有些是计算得出不能修改，有些适合聚合有些不适合。L3特征语义画像层为字段打上"性格标签"，使系统能够根据字段特性自动做出正确的处理决策。
> 
> **核心价值**:
> - **自动化权限**: 系统自动识别敏感字段并脱敏，无需人工配置
> - **智能查询**: Agent知道哪些字段适合过滤、哪些适合聚合、哪些适合排序
> - **合规保障**: 自动识别PII字段，确保数据使用符合监管要求
> - **计算透明**: 知道计算字段的公式和依赖，便于调试和审计

---

### 4.5 L4: 质量语义画像层

#### 4.5.1 设计目标

**回答核心问题**: "这个字段的数据靠谱吗？"

质量语义画像层为字段建立数据质量评分卡，从多个维度评估字段的数据质量，让用户和Agent知道"这个数据可信度如何"。

#### 4.5.2 画像内容

| 维度 | 指标 | 说明 | 计算方式 | 权重 |
|------|------|------|----------|------|
| **唯一性** | `uniqueness_score` | 主键字段的唯一性 | 唯一值数/总记录数 | 20% |
| **完整性** | `completeness_score` | 非空值占比 | 非空记录数/总记录数 | 25% |
| **一致性** | `consistency_score` | 跨系统一致性 | 一致记录数/总记录数 | 20% |
| **时效性** | `timeliness_score` | 数据新鲜度 | 1 - (当前日期-最新数据日期)/容忍天数 | 15% |
| **准确性** | `accuracy_score` | 数值合理性 | 合规记录数/总记录数 | 15% |
| **稳定性** | `stability_score` | 数据波动合理性 | 1 - 异常波动次数/总检查次数 | 5% |

**综合质量评分**: `overall_score = Σ(维度得分 × 权重)`

**质量等级**:
| 分数 | 等级 | 徽章 | 说明 |
|------|------|------|------|
| 90-100 | 优秀 | 🟢 Green | 数据质量高，可放心使用 |
| 70-89 | 良好 | 🟡 Yellow | 数据质量较好，注意个别问题 |
| 50-69 | 一般 | 🟠 Orange | 数据质量一般，使用前需确认 |
| 0-49 | 差 | 🔴 Red | 数据质量差，不建议使用 |

#### 4.5.3 数据模型

```python
class L4_QualitySemanticProfile(BaseModel):
    """L4: 质量语义画像层 — 字段的数据质量评估"""
    
    # 评估日期
    assessment_date: datetime
    assessment_period: str  # "daily" | "weekly" | "monthly"
    
    # 样本信息
    total_records: int
    sample_size: int
    
    # 维度评分 (0-100)
    uniqueness_score: float = 100.0
    completeness_score: float = 100.0
    consistency_score: float = 100.0
    timeliness_score: float = 100.0
    accuracy_score: float = 100.0
    stability_score: float = 100.0
    
    # 综合评分
    overall_score: float = 100.0
    quality_level: str = "green"  # "green" | "yellow" | "orange" | "red"
    
    # 维度详情
    uniqueness_details: dict = {}
    completeness_details: dict = {}
    consistency_details: dict = {}
    timeliness_details: dict = {}
    accuracy_details: dict = {}
    stability_details: dict = {}
    
    # 问题列表
    issues: list[dict] = []  # [{"type": "completeness", "severity": "warning", "description": "", "affected_count": 0}]
    
    # 历史趋势
    score_history: list[dict] = []  # [{"date": "", "overall_score": 0}]
    
    # 评估配置
    assessment_config: dict = {}  # 评估规则配置
    
    created_at: datetime
    updated_at: datetime


class QualityAssessmentConfig(BaseModel):
    """质量评估配置"""
    
    # 唯一性规则
    uniqueness_rules: list[dict] = []  # [{"type": "primary_key", "fields": ["AST_CD"]}]
    
    # 完整性规则
    completeness_rules: list[dict] = []  # [{"field": "AST_CD", "required": true}]
    
    # 一致性规则
    consistency_rules: list[dict] = []  # [{"source": "ZY", "target": "JY", "mapping": {"AST_CD": "SEC_ID"}}]
    
    # 时效性规则
    timeliness_rules: list[dict] = []  # [{"field": "BIZ_DT", "max_delay_days": 1}]
    
    # 准确性规则
    accuracy_rules: list[dict] = []  # [{"field": "COUPON_RATE", "min": 0, "max": 50, "unit": "%"}]
    
    # 稳定性规则
    stability_rules: list[dict] = []  # [{"field": "NET_ASSET", "max_daily_change_pct": 10}]
```

#### 4.5.4 质量评估规则示例

```python
# 证券代码(AST_CD)质量评估配置
AST_CD_QUALITY_CONFIG = {
    "uniqueness_rules": [
        {"type": "primary_key", "fields": ["AST_CD"], "expected_unique": true}
    ],
    "completeness_rules": [
        {"field": "AST_CD", "required": true, "min_length": 1}
    ],
    "consistency_rules": [
        {
            "source": "ZY",
            "target": "JY",
            "mapping": {"AST_CD": "SEC_ID"},
            "check_type": "existence"  # 检查ZY中的AST_CD是否在JY中存在对应
        }
    ],
    "timeliness_rules": [],  # AST_CD是静态字段，无时序要求
    "accuracy_rules": [
        {"field": "AST_CD", "pattern": "^[A-Z0-9_]+$", "description": "证券代码只能包含大写字母、数字和下划线"}
    ],
    "stability_rules": []  # AST_CD是静态字段
}

# 票面利率(COUPON_RATE)质量评估配置
COUPON_RATE_QUALITY_CONFIG = {
    "uniqueness_rules": [],  # 非主键，不要求唯一
    "completeness_rules": [
        {"field": "COUPON_RATE", "required": false}  # 股票无票面利率，可为空
    ],
    "consistency_rules": [],
    "timeliness_rules": [],
    "accuracy_rules": [
        {"field": "COUPON_RATE", "min": 0, "max": 50, "unit": "%", "description": "票面利率应在0%-50%之间"},
        {"field": "COUPON_RATE", "precision": 4, "description": "票面利率保留4位小数"}
    ],
    "stability_rules": [
        {"field": "COUPON_RATE", "max_change_per_update": 0, "description": "票面利率一旦确定不应变更"}
    ]
}
```

#### 4.5.5 应用场景

| 场景 | 应用方式 | 效果 |
|------|----------|------|
| **质量徽章** | `quality_level`渲染颜色徽章 | 用户一眼知道数据质量等级 |
| **低质量告警** | `overall_score < 70`触发告警 | 及时发现问题数据 |
| **Agent质量提示** | 注入Prompt: "该字段质量评分{score}，{issues}" | Agent告知用户数据可信度 |
| **数据清洗优先级** | `issues`按severity排序 | 优先处理高severity问题 |
| **质量趋势监控** | `score_history`绘制趋势图 | 发现数据质量恶化趋势 |
| **影响评估** | 低质量字段在血缘图谱中标记 | 评估低质量数据对下游的影响 |

#### 4.5.6 意义解读

> **为什么需要L4？**
> 
> 金融决策对数据质量极度敏感——一个错误的收益率数据可能导致错误的投资决策。L4质量语义画像层建立了"数据可信度"的量化评估体系，让用户和Agent在使用数据前就知道"这个数据靠谱吗"。
> 
> **核心价值**:
> - **数据可信**: 量化评估数据质量，避免"用错数据做决策"
> - **问题发现**: 自动检测数据异常（如票面利率>100%）
> - **趋势监控**: 发现数据质量恶化趋势，及时介入
> - **责任追溯**: 质量问题可追溯到具体字段和上游来源

---

### 4.6 四层画像整合模型

#### 4.6.1 统一字段语义画像

```python
class UnifiedFieldSemanticProfile(BaseModel):
    """
    统一字段语义画像 — 整合L1-L4四层画像
    
    这是语义层的核心数据模型，为每个字段提供完整的语义描述。
    """
    
    # 基础信息
    field_name: str
    collection_name: str
    domain: str
    
    # L1: 基础语义画像
    l1_foundation: L1_FoundationSemanticProfile
    
    # L2: 关联语义画像
    l2_relational: L2_RelationalSemanticProfile
    
    # L3: 特征语义画像
    l3_characteristic: L3_CharacteristicSemanticProfile
    
    # L4: 质量语义画像 (最新评估)
    l4_quality: Optional[L4_QualitySemanticProfile] = None
    
    # 血缘信息
    lineage_info: Optional[dict] = None  # 字段级血缘摘要
    
    # 元数据
    version: str = "1.0"
    status: str = "active"
    created_at: datetime
    updated_at: datetime
    
    def get_display_info(self) -> dict:
        """获取前端展示信息"""
        return {
            "field_name": self.field_name,
            "display_name": self.l1_foundation.display_name,
            "description": self.l1_foundation.business_definition,
            "data_type": self.l1_foundation.data_type,
            "unit": self.l1_foundation.unit,
            "tags": self.l3_characteristic.tags,
            "quality_score": self.l4_quality.overall_score if self.l4_quality else None,
            "quality_level": self.l4_quality.quality_level if self.l4_quality else None,
        }
    
    def get_lineage_summary(self) -> dict:
        """获取血缘摘要"""
        return {
            "is_primary_key": self.l2_relational.is_primary_key,
            "is_foreign_key": self.l2_relational.is_foreign_key,
            "foreign_key_ref": self.l2_relational.foreign_key_ref,
            "related_tables": self.l2_relational.related_tables,
            "cross_domain_mapping": self.l2_relational.cross_domain_mapping,
        }
    
    def get_prompt_context(self) -> str:
        """生成Agent Prompt上下文"""
        lines = [
            f"字段: {self.field_name} ({self.l1_foundation.display_name})",
            f"定义: {self.l1_foundation.business_definition}",
            f"类型: {self.l1_foundation.data_type}",
        ]
        if self.l1_foundation.unit:
            lines.append(f"单位: {self.l1_foundation.unit}")
        if self.l3_characteristic.tags:
            lines.append(f"标签: {', '.join(self.l3_characteristic.tags)}")
        if self.l4_quality:
            lines.append(f"质量评分: {self.l4_quality.overall_score}/100 ({self.l4_quality.quality_level})")
        return "\n".join(lines)
```

#### 4.6.2 四层画像应用矩阵

| 应用场景 | L1基础语义 | L2关联语义 | L3特征语义 | L4质量语义 |
|---------|-----------|-----------|-----------|-----------|
| **前端表头渲染** | ✅ display_name | ❌ | ❌ | ❌ |
| **字段Tooltip** | ✅ description + example | ✅ related_tables | ✅ tags | ✅ quality_score |
| **Agent字段解释** | ✅ definition | ✅ cross_domain_mapping | ✅ tags | ✅ quality_level |
| **血缘图谱** | ❌ | ✅ foreign_key_ref | ❌ | ✅ quality_level(节点颜色) |
| **跨域查询推荐** | ❌ | ✅ association_chains | ❌ | ❌ |
| **权限控制** | ❌ | ❌ | ✅ sensitivity_level | ❌ |
| **数据脱敏** | ❌ | ❌ | ✅ masking_rule | ❌ |
| **查询优化** | ❌ | ✅ is_indexed | ✅ search_weight | ❌ |
| **质量告警** | ❌ | ❌ | ❌ | ✅ overall_score |
| **计算溯源** | ❌ | ❌ | ✅ computation_formula | ❌ |
| **聚合推荐** | ❌ | ❌ | ✅ default_aggregation | ❌ |
| **合规检查** | ❌ | ❌ | ✅ is_pii | ❌ |

---

## 五、总体架构设计

### 5.1 四层架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           前端应用层 (Frontend)                               │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐  │
│  │ 数据探索页    │ │ 血缘图谱页    │ │ 数据质量页    │ │ Agent对话界面       │  │
│  │zyDataDomain  │ │LineageGraph  │ │QualityBoard  │ │ Chat UI            │  │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └─────────┬──────────┘  │
│         │                │                │                   │             │
│         └────────────────┴────────────────┴───────────────────┘             │
│                                    │                                        │
│                         ┌──────────┴──────────┐                             │
│                         │   DeepLink路由协议   │                             │
│                         │  /lineage?dl={...}  │                             │
│                         └──────────┬──────────┘                             │
└────────────────────────────────────┼────────────────────────────────────────┘
                                     │
┌────────────────────────────────────┼────────────────────────────────────────┐
│                        API网关层 (Semantic Gateway)                          │
│  ┌─────────────────────────────────┴─────────────────────────────────────┐   │
│  │  /api/v1/semantic/schema      /api/v1/semantic/search               │   │
│  │  /api/v1/semantic/field/{id}  /api/v1/semantic/entity/{name}        │   │
│  │  /api/v1/lineage/query        /api/v1/lineage/graph                 │   │
│  │  /api/v1/lineage/impact       /api/v1/lineage/deeplink              │   │
│  │  /api/v1/quality/score        /api/v1/quality/badge                 │   │
│  └─────────────────────────────────┬─────────────────────────────────────┘   │
└────────────────────────────────────┼────────────────────────────────────────┘
                                     │
┌────────────────────────────────────┼────────────────────────────────────────┐
│                      后端服务层 (Service Layer)                              │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌──────────┐  │
│  │ 语义层服务       │ │ 血缘追踪服务     │ │ 数据接入服务     │ │ 监控治理  │  │
│  │SemanticLayer    │ │LineageTracker   │ │DataHubService   │ │Monitor   │  │
│  │  - L1-L4画像管理 │ │  - 静态注册      │ │  - 导入血缘      │ │  - 告警  │  │
│  │  - 概念层管理    │ │  - 动态观测      │ │  - 质量评估      │ │  - 报表  │  │
│  │  - 逻辑层管理    │ │  - 事后回溯      │ │  - 变更检测      │ │  - 审计  │  │
│  │  - 物理层映射    │ │  - 影响分析      │ │                 │ │          │  │
│  │  - 术语表        │ │  - 图谱查询      │ │                 │ │          │  │
│  │  - 语义搜索      │ │                 │ │                 │ │          │  │
│  └────────┬────────┘ └────────┬────────┘ └────────┬────────┘ └──────────┘  │
│           │                   │                   │                         │
│           └───────────────────┴───────────────────┘                         │
│                               │                                             │
│                    ┌──────────┴──────────┐                                  │
│                    │   Agent语义增强层    │                                  │
│                    │ SemanticLayerClient │                                  │
│                    │  (注入DataContext)   │                                  │
│                    └─────────────────────┘                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
┌────────────────────────────────────┼────────────────────────────────────────┐
│                    元数据存储层 (Metadata Storage)                            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐  │
│  │_semantic_    │ │_lineage_     │ │_lineage_     │ │_data_quality_      │  │
│  │definitions   │ │nodes         │ │edges         │ │scores              │  │
│  │(语义定义)     │ │(血缘节点)     │ │(血缘边)       │ │(质量评分)           │  │
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────────────────┘  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐  │
│  │_physical_    │ │_query_audit_ │ │_collection_  │ │DOMAIN_METADATA     │  │
│  │mappings      │ │log           │ │registry      │ │(内存+MongoDB)       │  │
│  │(物理映射)     │ │(审计日志)     │ │(集合注册)     │ │                    │  │
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 核心设计原则

| 原则 | 说明 | 具体措施 |
|------|------|----------|
| **保护现有投资** | 不替换`DOMAIN_METADATA`，而是扩展 | 语义层作为独立集合，通过`collection_name`关联 |
| **技术栈一致** | 继续使用MongoDB | 图模型用节点+边集合存储，不引入Neo4j |
| **增量增强** | Agent架构不变 | `SemanticLayerClient`作为`DataContext`的依赖注入 |
| **零侵入采集** | 血缘采集不阻塞主流程 | 异步内存队列+批量写入，目标<5ms/调用 |
| **结构化节点ID** | 自描述、可前缀查询 | 格式: `{type}:{namespace}:{name}:{version}` |

---

## 六、六大模块详细设计与意义解读

### 模块1: 语义层服务 (Semantic Layer Service)

#### 6.1.1 模块定位

**语义层服务是整个系统的"大脑"**，负责管理数据的语义知识——让机器理解"这个字段是什么意思"。

#### 6.1.2 核心功能

```
┌─────────────────────────────────────────────────────────────┐
│                    语义层服务 (SemanticLayer)                 │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  L1基础语义  │  │  L2关联语义  │  │  L3特征语义  │         │
│  │  管理       │  │  管理       │  │  管理       │         │
│  │             │  │             │  │             │         │
│  │ • 字段画像CRUD│  │ • 外键关系管理│  │ • 特征标签管理│         │
│  │ • 中文名维护 │  │ • 跨域映射维护│  │ • 敏感等级配置│         │
│  │ • 枚举值管理 │  │ • 关联链定义 │  │ • 计算公式维护│         │
│  │ • 单位换算   │  │ • JOIN条件模板│  │ • 检索权重配置│         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          │                                  │
│                   ┌──────┴──────┐                           │
│                   │  L4质量语义  │                           │
│                   │  管理       │                           │
│                   │             │                           │
│                   │ • 质量评估触发│                           │
│                   │ • 评分历史管理│                           │
│                   │ • 问题追踪   │                           │
│                   └──────┬──────┘                           │
│                          │                                  │
│  ┌───────────────────────┼───────────────────────┐          │
│  │                       │                       │          │
│  │  ┌─────────────┐     │     ┌─────────────┐  │          │
│  │  │ 语义实体管理 │◄────┴────►│ 术语表管理   │  │          │
│  │  │             │           │             │  │          │
│  │  │ • 实体定义   │           │ • 术语CRUD   │  │          │
│  │  │ • 实体-表映射│           │ • 同义词管理 │  │          │
│  │  │ • 实体关系   │           │ • 定义维护   │  │          │
│  │  └─────────────┘           └─────────────┘  │          │
│  │                                             │          │
│  │  ┌─────────────────────────────────────┐    │          │
│  │  │         语义搜索服务                  │    │          │
│  │  │  • 关键词搜索                        │    │          │
│  │  │  • 语义相似度匹配                     │    │          │
│  │  │  • 智能推荐                          │    │          │
│  │  └─────────────────────────────────────┘    │          │
│  └─────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

#### 6.1.3 关键API

| API | 功能 | 应用场景 |
|-----|------|----------|
| `GET /api/v1/semantic/field/{collection}/{field}` | 获取字段完整画像(L1-L4) | Agent解释字段、前端Tooltip |
| `GET /api/v1/semantic/schema/{collection}` | 获取集合语义增强Schema | 前端表头渲染、Agent查询 |
| `GET /api/v1/semantic/search?q={keyword}` | 语义搜索 | 用户搜索"收益率"找到所有相关字段 |
| `GET /api/v1/semantic/entity/{name}` | 获取语义实体 | 跨域查询推荐 |
| `POST /api/v1/semantic/profile/batch` | 批量创建字段画像 | 初始化导入 |

#### 6.1.4 意义解读

> **为什么语义层是"大脑"？**
> 
> 没有语义层，系统只是"存储和搬运数据"——知道AST_CD存在，但不知道它是"证券代码"。语义层赋予数据"业务含义"，使系统从"数据搬运工"升级为"数据理解者"。
> 
> **核心价值**:
> - **人机理解统一**: 业务人员说"证券代码"，系统知道是AST_CD
> - **AI赋能基础**: Agent通过语义层理解数据，才能生成准确的查询和分析
> - **知识沉淀**: 将分散在文档、头脑中的业务知识结构化、可查询
> - **跨域整合**: 识别不同系统中同一概念的不同名称（ZY的AST_CD = JY的SEC_ID）

---

### 模块2: 血缘追踪服务 (Lineage Tracking Service)

#### 6.2.1 模块定位

**血缘追踪服务是整个系统的"神经系统"**，负责追踪数据的来龙去脉——让系统知道"这个数据从哪来、到哪去"。

#### 6.2.2 核心功能

```
┌─────────────────────────────────────────────────────────────┐
│                  血缘追踪服务 (LineageTracker)                │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 三层采集模型                         │   │
│  │                                                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │ 静态注册层   │  │ 动态观测层   │  │ 事后回溯层   │ │   │
│  │  │             │  │             │  │             │ │   │
│  │  │ 系统启动时   │  │ 运行时零侵入 │  │ 每日凌晨执行 │ │   │
│  │  │ 从元数据生成 │  │ 装饰器采集   │  │ 从日志反推   │ │   │
│  │  │ 基础血缘骨架 │  │ 运行时血缘   │  │ 补录缺失血缘 │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 血缘查询服务                         │   │
│  │                                                     │   │
│  │  • 正向追溯: 数据源 → 所有下游依赖                   │   │
│  │  • 反向溯源: 消费端 → 所有上游来源                   │   │
│  │  • 字段级影响分析: 字段变更 → 影响范围评估            │   │
│  │  • 深度控制: 支持指定遍历深度(默认3层, 最大10层)      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 血缘图谱服务                         │   │
│  │                                                     │   │
│  │  • 节点/边CRUD                                      │   │
│  │  • 图谱遍历算法(BFS/DFS)                             │   │
│  │  • 最短路径查询                                      │   │
│  │  • 环检测                                           │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 DeepLink服务                         │   │
│  │                                                     │   │
│  │  • URL生成: /lineage?dl={payload}&view={view}       │   │
│  │  • 锚点解析: SYMBOL/DATE/FIELD/CHART_POINT/...      │   │
│  │  • 意图路由: VIEW_LINEAGE/VIEW_SOURCE/VIEW_IMPACT   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

#### 6.2.3 关键API

| API | 功能 | 应用场景 |
|-----|------|----------|
| `GET /api/v1/lineage/graph?root_id={id}&direction=downstream&depth=3` | 血缘图谱查询 | 前端血缘图谱可视化 |
| `GET /api/v1/lineage/impact?node_id={id}&field={field}` | 影响分析 | 评估字段变更影响 |
| `GET /api/v1/lineage/source?node_id={id}` | 溯源查询 | 追溯数据来源 |
| `POST /api/v1/lineage/deeplink` | 生成DeepLink | 对话成果物→前端跳转 |
| `POST /api/v1/lineage/register` | 注册血缘 | 数据接入时记录血缘 |

#### 6.2.4 意义解读

> **为什么血缘追踪是"神经系统"？**
> 
> 没有血缘追踪，数据就像"黑箱"——你知道结果，但不知道它从哪来、怎么算的。血缘追踪让数据的流转路径透明化，使系统具备"感知"数据流动的能力。
> 
> **核心价值**:
> - **数据可信**: 任何数据点都可追溯至原始来源
> - **影响可控**: 上游变更时，精准评估下游影响范围
> - **问题定位**: 数据异常时，快速定位问题源头
> - **合规审计**: 满足金融监管对数据溯源的要求
> - **知识传承**: 新成员通过血缘图谱快速理解数据架构

---

### 模块3: 前后端链路语义增强

#### 6.3.1 模块定位

**前后端链路语义增强是系统的"感官系统"**，负责将语义层和血缘层的知识传递到用户界面——让用户"看得见、摸得着"数据的语义和血缘。

#### 6.3.2 核心功能

```
┌─────────────────────────────────────────────────────────────┐
│              前后端链路语义增强 (Frontend-Backend)            │
│                                                             │
│  后端链路:                                                   │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ GenericQuery │───►│ 语义层查询   │───►│ _semantic_  │     │
│  │ Engine.find()│    │ (获取L1-L4)  │    │ _meta 注入   │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│         │                                              │    │
│         │ 返回: {data, total, page_info, _semantic_meta} │    │
│         ▼                                              ▼    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    API响应                            │   │
│  │  {                                                  │   │
│  │    "data": [...],                                   │   │
│  │    "_semantic_meta": {                              │   │
│  │      "collection": {display_name, description},     │   │
│  │      "fields": {AST_CD: {display_name, tags, quality_score}}│
│  │    }                                                │   │
│  │  }                                                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  前端链路:                                                   │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ zyDataDomain │───►│ 解析_semantic│───►│ SemanticTable│    │
│  │ 接收响应     │    │ _meta       │    │ 渲染         │    │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                                              │              │
│                              ┌───────────────┼───────────┐  │
│                              ▼               ▼           ▼  │
│                         ┌────────┐    ┌────────┐   ┌────────┐│
│                         │表头中文名│    │字段Tooltip│   │质量徽章││
│                         │渲染    │    │渲染      │   │渲染  ││
│                         └────────┘    └────────┘   └────────┘│
│                                                             │
│  血缘可视化:                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ MiniLineage │    │ LineageGraph │    │ DeepLink    │     │
│  │ Tree(对话内) │    │ Page(全屏)   │    │ Button      │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

#### 6.3.3 关键组件

| 组件 | 功能 | 应用场景 |
|-----|------|----------|
| `SemanticTable` | 语义增强表格 | 数据探索页，显示中文表头、质量徽章 |
| `FieldTooltip` | 字段语义Tooltip | 鼠标悬停显示字段定义、示例、质量评分 |
| `MiniLineageTree` | Mini血缘树 | 对话界面紧凑展示工具调用链 |
| `LineageGraph` | 全屏血缘图谱 | 独立页面展示完整血缘关系 |
| `DeepLinkButton` | DeepLink跳转按钮 | 从对话跳转到前端血缘图谱 |

#### 6.3.4 意义解读

> **为什么前后端链路语义增强是"感官系统"？**
> 
> 语义层和血缘层再强大，如果用户"看不见"，就只是后台的黑科技。前后端链路语义增强将抽象的语义和血缘知识转化为直观的界面元素——中文表头、Tooltip提示、质量徽章、血缘图谱——让用户真正"感知"到数据的可信度和来龙去脉。
> 
> **核心价值**:
> - **降低认知门槛**: 业务人员无需理解AST_CD，看到"证券代码"就懂
> - **提升数据信任**: 质量徽章让用户知道"这个数据靠谱吗"
> - **增强探索能力**: Tooltip和血缘图谱帮助用户深入理解数据
> - **对话成果可视化**: Agent的分析结果可以通过DeepLink跳转到前端深入查看

---

### 模块4: Agent语义增强

#### 6.4.1 模块定位

**Agent语义增强是系统的"智能中枢"**，负责让AI Agent具备数据语义感知能力——让Agent"理解"数据，而不仅仅是"搬运"数据。

#### 6.4.2 核心功能

```
┌─────────────────────────────────────────────────────────────┐
│                  Agent语义增强 (Semantic Agent)               │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              DataContext增强                         │   │
│  │                                                     │   │
│  │  class DataContext:                                 │   │
│  │    def __init__(self, semantic_client:              │   │
│  │                 SemanticLayerClient):               │   │
│  │      self._semantic_client = semantic_client        │   │
│  │                                                     │   │
│  │    async def get_semantic_schema(self, collection): │   │
│  │      return await self._semantic_client.get_schema()│   │
│  │                                                     │   │
│  │    async def explain_field(self, collection, field):│   │
│  │      profile = await self._semantic_client.get_field()│  │
│  │      return f"{profile.display_name}: {profile.definition}"│
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              DataQueryTool增强                       │   │
│  │                                                     │   │
│  │  1. 获取语义增强Schema                               │   │
│  │  2. 将Schema语义注入Prompt                           │   │
│  │  3. LLM生成查询 → 执行查询                           │   │
│  │  4. 存储结果(自动记录血缘)                            │   │
│  │  5. 返回带语义元数据的结果                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              智能查询推荐                            │   │
│  │                                                     │   │
│  │  用户: "查茅台的估值"                                 │   │
│  │  Agent:                                              │   │
│  │    1. 识别语义实体: SecurityAsset(茅台) + Valuation  │   │
│  │    2. 推荐关联链: asset → valuation (AST_CD关联)     │   │
│  │    3. 推荐字段: VAL_NET_PRC, VAL_FULL_PRC, BIZ_DT    │   │
│  │    4. 推荐过滤: BIZ_DT >= 最近一周                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              血缘解释能力                            │   │
│  │                                                     │   │
│  │  用户: "这个数据从哪来?"                              │   │
│  │  Agent: "该数据来自ZY系统的get_py_result接口，        │   │
│  │         于2024-06-01导入，共10000条记录。            │   │
│  │         [Mini血缘树展示来源链路]"                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

#### 6.4.3 关键能力

| 能力 | 功能 | 应用场景 |
|-----|------|----------|
| **语义感知Schema** | 获取字段中文名、定义、标签 | Agent理解查询目标 |
| **智能查询推荐** | 基于语义实体推荐查询路径 | 用户说"查估值"→自动推荐字段和条件 |
| **字段解释** | 解释字段业务含义 | 用户问"这个字段什么意思" |
| **血缘解释** | 解释数据来源和流转 | 用户问"这个数据从哪来" |
| **质量感知** | 告知数据质量评分 | Agent提示"该字段质量评分85分，注意完整性问题" |

#### 6.4.4 意义解读

> **为什么Agent语义增强是"智能中枢"？**
> 
> 没有语义增强，Agent只是"执行查询的工具"——用户说"查AST_CD"，Agent就查AST_CD，但不知道它是"证券代码"。语义增强让Agent成为"理解业务的智能助手"——用户说"查茅台的估值"，Agent知道茅台是SecurityAsset，估值是Valuation，自动找到关联路径和关键字段。
> 
> **核心价值**:
> - **自然语言理解**: 用户用业务语言提问，Agent自动翻译为技术查询
> - **查询准确性**: Agent知道字段含义，不会把"票面利率"当成"收益率"查询
> - **跨域整合**: Agent自动识别跨域关联，推荐最优查询路径
> - **结果可信度**: Agent告知数据质量，帮助用户判断结果可信度
> - **知识传承**: Agent成为业务知识的载体，新成员通过对话学习业务

---

### 模块5: 数据接入层血缘嵌入

#### 6.5.1 模块定位

**数据接入层血缘嵌入是系统的"记忆系统"**，负责在数据导入时记录"这个数据从哪来"——建立数据从源头到存储的第一道血缘。

#### 6.5.2 核心功能

```
┌─────────────────────────────────────────────────────────────┐
│              数据接入层血缘嵌入 (DataHub Lineage)             │
│                                                             │
│  导入流程:                                                   │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐    │
│  │ 上游API  │──►│ 数据转换 │──►│ MongoDB  │──►│ 血缘记录 │    │
│  │ 调用     │   │ 清洗     │   │ 写入     │   │ 创建     │    │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘    │
│       │                                          │          │
│       │                                          │          │
│       ▼                                          ▼          │
│  ┌─────────────┐                        ┌─────────────┐    │
│  │ SOURCE_API  │───────────────────────►│ _lineage_   │    │
│  │ 节点        │   DATA_FLOW边          │ nodes       │    │
│  │             │                        │ _lineage_   │    │
│  └─────────────┘                        │ edges       │    │
│                                         └─────────────┘    │
│  ┌─────────────┐                        ┌─────────────┐    │
│  │ STORAGE_    │───────────────────────►│ _lineage_   │    │
│  │ MONGO节点   │   TRIGGER边            │ nodes       │    │
│  └─────────────┘                        │ _lineage_   │    │
│                                         │ edges       │    │
│  ┌─────────────┐                        └─────────────┘    │
│  │ BATCH节点   │                                            │
│  │ (批次信息)  │                                            │
│  └─────────────┘                                            │
│                                                             │
│  质量评估:                                                   │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐    │
│  │ 完整性   │   │ 一致性   │   │ 时效性   │   │ 准确性   │    │
│  │ 评分     │   │ 评分     │   │ 评分     │   │ 评分     │    │
│  └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘    │
│       │             │             │             │          │
│       └─────────────┴─────────────┴─────────────┘          │
│                         │                                   │
│                         ▼                                   │
│                  ┌─────────────┐                            │
│                  │ 综合质量评分  │                            │
│                  │ 写入_quality │                            │
│                  │ _scores     │                            │
│                  └─────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

#### 6.5.3 关键功能

| 功能 | 说明 | 应用场景 |
|-----|------|----------|
| **导入血缘记录** | 记录SOURCE_API→STORAGE_MONGO血缘 | 追溯数据来源 |
| **批次追踪** | 创建BATCH节点，关联导入批次 | 问题批次定位 |
| **质量评估** | 完整性/一致性/时效性/准确性评分 | 数据质量监控 |
| **变更检测** | 对比本次与上次导入的差异 | 数据异常发现 |
| **失败记录** | 记录导入失败原因和重试状态 | 问题排查 |

#### 6.5.4 意义解读

> **为什么数据接入层血缘嵌入是"记忆系统"？**
> 
> 数据从上游系统流入时，如果不记录"它从哪来"，之后就永远无法追溯。数据接入层血缘嵌入在数据"出生"时就建立第一道记忆——记录来源、时间、质量，为后续的所有追溯和分析奠定基础。
> 
> **核心价值**:
> - **来源可追溯**: 知道每条数据来自哪个上游系统、哪个API、什么时间
> - **质量可评估**: 导入时即评估数据质量，早发现早处理
> - **批次可追踪**: 问题数据可追溯到具体导入批次
> - **变更可感知**: 发现数据异常变化，及时告警

---

### 模块6: 监控治理

#### 6.6.1 模块定位

**监控治理是系统的"免疫系统"**，负责持续监控语义层和血缘层的健康状况——发现问题、告警、修复，确保系统长期稳定运行。

#### 6.6.2 核心功能

```
┌─────────────────────────────────────────────────────────────┐
│                  监控治理 (Monitoring & Governance)           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 血缘健康监控                         │   │
│  │                                                     │   │
│  │  • 孤儿节点检测: 无入边且无出边的节点                │   │
│  │  • 断链检测: 存在边但节点缺失                        │   │
│  │  • 覆盖率监控: 已注册集合的血缘覆盖率                │   │
│  │  • 新鲜度监控: 血缘记录的最后观测时间                │   │
│  │  • 每日生成血缘健康报告                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 数据质量监控                         │   │
│  │                                                     │   │
│  │  • 按域汇总质量评分                                  │   │
│  │  • 质量评分趋势图(近30天)                            │   │
│  │  • 低质量字段TOP10                                   │   │
│  │  • 质量告警列表                                      │   │
│  │  • 质量仪表盘页面                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 语义层健康监控                       │   │
│  │                                                     │   │
│  │  • 字段画像覆盖率监控                                │   │
│  │  • 术语表完整性检查                                  │   │
│  │  • 跨域映射一致性检查                                │   │
│  │  • 语义定义过期检测                                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 告警与通知                           │   │
│  │                                                     │   │
│  │  • 血缘异常告警(孤儿节点/断链)                       │   │
│  │  • 质量告警(低质量字段)                              │   │
│  │  • 语义定义过期告警                                  │   │
│  │  • 通知渠道: 邮件/企业微信/钉钉                      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

#### 6.6.3 关键功能

| 功能 | 说明 | 应用场景 |
|-----|------|----------|
| **血缘健康监控** | 孤儿节点/断链/覆盖率/新鲜度检测 | 确保血缘图谱完整性 |
| **质量监控** | 质量评分趋势/低质量字段TOP10 | 数据质量持续改进 |
| **语义层监控** | 字段画像覆盖率/术语表完整性 | 语义知识持续完善 |
| **告警通知** | 异常自动告警 | 及时发现问题 |

#### 6.6.4 意义解读

> **为什么监控治理是"免疫系统"？**
> 
> 语义层和血缘层是动态变化的——新表加入、字段变更、上游系统升级。如果没有监控治理，这些变化会导致语义过时、血缘断裂、质量下降。监控治理持续扫描系统健康状况，自动发现并修复问题，确保语义和血缘知识始终准确、完整、新鲜。
> 
> **核心价值**:
> - **问题早发现**: 自动检测血缘断裂、语义过时、质量下降
> - **持续改进**: 通过监控报表发现薄弱环节，持续优化
> - **知识保鲜**: 确保语义定义和血缘关系与实际情况一致
> - **风险预防**: 在问题影响业务前及时发现并修复

---

## 七、数据模型设计

### 7.1 新增MongoDB集合

| 集合名 | 用途 | 预估文档数 | 索引 |
|--------|------|-----------|------|
| `_semantic_definitions` | 语义实体/字段定义(L1-L4) | ~1000 | `entity_name`, `collection_name+field_name` |
| `_physical_mappings` | 物理映射 | ~2000 | `logical_field`, `physical_field+collection` |
| `_lineage_nodes` | 血缘节点 | ~10000 | `node_id`(唯一), `node_type`, `namespace` |
| `_lineage_edges` | 血缘边 | ~50000 | `from_node+to_node`, `edge_type` |
| `_data_quality_scores` | 质量评分 | ~50000 | `collection+field+date`, `score` |
| `_semantic_terms` | 术语表 | ~200 | `term_name`(唯一) |
| `_association_chains` | 关联链 | ~50 | `chain_name`(唯一), `domain` |

### 7.2 集合Schema详细定义

#### `_semantic_definitions` (整合L1-L4)

```javascript
{
  "_id": ObjectId,
  "definition_type": "entity" | "field",
  
  // 实体定义时
  "entity_name": "SecurityAsset",
  "display_name": "证券资产",
  "description": "可交易的标准化金融资产...",
  "primary_identifier": {"field": "AST_CD", "description": "证券代码"},
  "domains": ["asset", "trading", "valuation"],
  "related_entities": [{"entity": "Issuer", "relation": "issued_by", "key": "ISR_ID"}],
  "mapped_tables": ["dwd_ast_info", "dwd_ast_info_ch"],
  
  // 字段定义时
  "collection_name": "dwd_ast_info",
  "field_name": "AST_CD",
  
  // L1: 基础语义
  "l1_foundation": {
    "display_name": "证券代码",
    "data_type": "string",
    "length": 32,
    "business_definition": "唯一标识一只可交易证券的代码",
    "business_category": "标识类",
    "example_values": ["BOND_2024_001", "STK_688521_SH"],
    "enum_values": null,
    "enum_source": null,
    "unit": null,
    "unit_conversion": null
  },
  
  // L2: 关联语义
  "l2_relational": {
    "is_primary_key": true,
    "is_foreign_key": false,
    "foreign_key_ref": null,
    "is_unique": true,
    "is_indexed": true,
    "index_type": "btree",
    "related_tables": ["dwd_ast_info_ch", "dwd_trd_trade", "dwd_val_detail"],
    "related_fields": [
      {"collection": "dwd_ast_info_ch", "field": "AST_CD", "relation": "1:1"},
      {"collection": "dwd_trd_trade", "field": "AST_CD", "relation": "1:N"}
    ],
    "cardinality": "1:N",
    "cross_domain_mapping": {
      "zy_system": "AST_CD",
      "jy_system": "SEC_ID",
      "ta_system": "FUND_CODE"
    },
    "mapping_type": "direct",
    "mapping_logic": null,
    "association_chains": ["asset_to_issuer", "asset_to_valuation", "asset_to_trade"],
    "join_conditions": [
      "{asset_table}.AST_CD = {target_table}.AST_CD"
    ],
    "is_cross_domain_key": true,
    "cross_domain_key_type": "primary"
  },
  
  // L3: 特征语义
  "l3_characteristic": {
    "tags": ["主键", "跨域关联键", "检索键"],
    "custom_tags": [],
    "sensitivity_level": "P1",
    "is_pii": false,
    "masking_rule": null,
    "masking_config": null,
    "is_temporal": false,
    "temporal_type": null,
    "temporal_granularity": null,
    "temporal_format": null,
    "is_computed": false,
    "computation_formula": null,
    "computation_dependencies": [],
    "computation_trigger": null,
    "is_searchable": true,
    "search_weight": 10,
    "full_text_index": false,
    "search_analyzer": null,
    "is_aggregatable": false,
    "default_aggregation": null,
    "aggregation_restrictions": ["标识字段不可聚合"],
    "is_active": true,
    "valid_from": ISODate("2024-01-01"),
    "valid_to": null
  },
  
  // L4: 质量语义 (最新评估)
  "l4_quality": {
    "assessment_date": ISODate("2024-06-03"),
    "assessment_period": "daily",
    "total_records": 100000,
    "sample_size": 10000,
    "uniqueness_score": 100.0,
    "completeness_score": 100.0,
    "consistency_score": 98.5,
    "timeliness_score": 100.0,
    "accuracy_score": 100.0,
    "stability_score": 100.0,
    "overall_score": 99.7,
    "quality_level": "green",
    "issues": [],
    "score_history": [
      {"date": "2024-06-01", "overall_score": 99.5},
      {"date": "2024-06-02", "overall_score": 99.6}
    ]
  },
  
  // 血缘摘要
  "lineage_summary": {
    "upstream_count": 1,
    "downstream_count": 5,
    "last_import_batch": "batch_20240603_001",
    "last_import_time": ISODate("2024-06-03T02:00:00Z")
  },
  
  "version": "1.0",
  "status": "active",
  "created_at": ISODate,
  "updated_at": ISODate
}
```

---

## 八、接口契约设计

### 8.1 语义层API

| 方法 | 路径 | 说明 | 请求体/参数 | 响应 |
|------|------|------|------------|------|
| GET | `/api/v1/semantic/entities` | 列出所有语义实体 | `?domain={domain}` | `[{entity_name, display_name, ...}]` |
| GET | `/api/v1/semantic/entity/{name}` | 获取实体详情 | - | `{entity_name, display_name, mapped_tables, ...}` |
| GET | `/api/v1/semantic/field/{collection}/{field}` | 获取字段完整画像(L1-L4) | - | `{field_name, l1_foundation, l2_relational, l3_characteristic, l4_quality}` |
| GET | `/api/v1/semantic/schema/{collection}` | 获取语义增强Schema | - | `{collection, fields: {...}, foreign_keys, ...}` |
| GET | `/api/v1/semantic/search` | 语义搜索 | `?q={keyword}&type={entity|field}` | `[{name, type, relevance, ...}]` |
| GET | `/api/v1/semantic/terms` | 术语表 | `?term={term_name}` | `[{term, definition, related_fields}]` |

### 8.2 血缘API

| 方法 | 路径 | 说明 | 请求体/参数 | 响应 |
|------|------|------|------------|------|
| GET | `/api/v1/lineage/graph` | 血缘图谱 | `?root_id={id}&direction={up|down}&depth={n}` | `{nodes: [...], edges: [...]}` |
| GET | `/api/v1/lineage/impact` | 影响分析 | `?node_id={id}&field={field}` | `{affected_nodes: [...], risk_level}` |
| GET | `/api/v1/lineage/source` | 溯源查询 | `?node_id={id}` | `{source_chain: [...]}` |
| POST | `/api/v1/lineage/deeplink` | 生成DeepLink | `{lineage_id, target_view, intent}` | `{url, lineage_id}` |
| POST | `/api/v1/lineage/register` | 注册血缘 | `{node, edges}` | `{node_id, edge_ids}` |

### 8.3 质量API

| 方法 | 路径 | 说明 | 请求体/参数 | 响应 |
|------|------|------|------------|------|
| GET | `/api/v1/quality/score/{collection}` | 集合质量评分 | `?field={field}&date={date}` | `{collection, overall_score, dimensions: {...}}` |
| GET | `/api/v1/quality/badge/{collection}` | 质量徽章 | - | `{badge: "green|yellow|red", score, issues: [...]}` |
| GET | `/api/v1/quality/dashboard` | 质量仪表盘 | `?domain={domain}` | `{domains: [...], trends: [...], alerts: [...]}` |

---

## 九、前后端链路改造

### 9.1 后端改造清单

| 文件 | 改造内容 | 优先级 |
|------|----------|--------|
| `app/services/collection_registry.py` | 扩展`_seed_domain_metadata`写入`_semantic_definitions` | P0 |
| `app/services/generic_query_engine.py` | `find()`/`aggregate()`返回增加`_semantic_meta` | P0 |
| `app/services/generic_query_engine.py` | 集成血缘采集装饰器 | P0 |
| `app/services/data_hub_service.py` | `import_from_upstream()`集成血缘记录 | P0 |
| `app/services/data_hub_service.py` | 导入完成后触发质量评估 | P1 |
| `app/agent/services/data_context.py` | 注入`SemanticLayerClient` | P0 |
| `app/agent/tools/data_query_tool.py` | 使用语义增强Schema | P1 |
| `app/api/zy_data.py` | 透传`_semantic_meta`到前端 | P0 |
| `app/api/semantic.py` | **新增**: 语义层API路由 | P0 |
| `app/api/lineage.py` | **新增**: 血缘API路由 | P0 |
| `app/api/quality.py` | **新增**: 质量API路由 | P1 |
| `app/models/semantic.py` | **新增**: 语义层数据模型(L1-L4) | P0 |
| `app/models/lineage.py` | **新增**: 血缘数据模型 | P0 |
| `app/models/quality.py` | **新增**: 质量数据模型 | P1 |
| `app/services/semantic_layer.py` | **新增**: 语义层服务 | P0 |
| `app/services/lineage_tracker.py` | **新增**: 血缘追踪服务 | P0 |
| `app/services/lineage_graph.py` | **新增**: 血缘图谱查询 | P0 |
| `app/services/quality_service.py` | **新增**: 质量评估服务 | P1 |
| `app/services/deeplink_service.py` | **新增**: DeepLink生成 | P1 |
| `app/config/semantic_catalog.py` | **新增**: 语义元数据配置 | P0 |
| `scripts/seed_semantic_layer.py` | **新增**: 语义层初始化脚本 | P0 |
| `scripts/refresh_lineage.py` | **新增**: 血缘刷新脚本 | P1 |

### 9.2 前端改造清单

| 文件/组件 | 改造内容 | 优先级 |
|-----------|----------|--------|
| `zyDataDomain.js` | 解析`_semantic_meta`，渲染字段中文名 | P0 |
| `components/FieldTooltip.vue` | **新增**: 字段语义Tooltip组件 | P1 |
| `components/SemanticTable.vue` | **新增**: 语义增强表格组件 | P1 |
| `pages/LineageGraph.vue` | **新增**: 血缘图谱可视化页面 | P1 |
| `pages/QualityDashboard.vue` | **新增**: 质量仪表盘页面 | P2 |
| `components/MiniLineageTree.vue` | **新增**: Mini血缘树组件 | P1 |
| `components/DeepLinkButton.vue` | **新增**: DeepLink跳转按钮 | P1 |
| `utils/semanticClient.js` | **新增**: 前端语义层客户端 | P0 |
| `utils/lineageClient.js` | **新增**: 前端血缘客户端 | P1 |

---

## 十、Agent链路改造

### 10.1 DataContext增强

```python
# app/agent/services/data_context.py

class DataContext:
    def __init__(self, conversation_id: str, semantic_client: Optional[SemanticLayerClient] = None):
        self.conversation_id = conversation_id
        self._store: dict[str, dict] = {}
        self._tool_history: list[dict] = []
        self._step_counter: int = 0
        self._last_access: float = time.time()
        self._created_at: float = time.time()
        self._semantic_client = semantic_client  # 新增
        self._lineage_session: Optional[str] = None  # 新增: 血缘会话ID
    
    async def get_semantic_schema(self, collection: str) -> dict:
        """获取语义增强的Schema"""
        if self._semantic_client:
            return await self._semantic_client.get_schema(collection)
        return {}
    
    async def explain_field(self, collection: str, field: str) -> str:
        """解释字段含义"""
        if self._semantic_client:
            profile = await self._semantic_client.get_field_profile(collection, field)
            return f"{profile['display_name']}: {profile['business_definition']}"
        return ""
    
    def store(self, data, tool_name, params, key=None):
        # 现有逻辑...
        # 新增: 记录血缘
        if self._lineage_session:
            lineage_tracker.record_tool_execution(
                session_id=self._lineage_session,
                tool_name=tool_name,
                params=params,
                output_key=key,
            )
```

### 10.2 DataQueryTool增强

```python
# app/agent/tools/data_query_tool.py

class DataQueryTool:
    async def execute(self, collection: str, query: str, ...):
        # 1. 获取语义增强Schema
        semantic_schema = await self.data_context.get_semantic_schema(collection)
        
        # 2. 将Schema语义注入Prompt
        prompt = self._build_prompt_with_semantics(query, semantic_schema)
        
        # 3. 执行查询
        result = await self.query_engine.find(collection, ...)
        
        # 4. 存储结果（自动记录血缘）
        key = self.data_context.store(result, "data_query", {...})
        
        # 5. 返回带语义元数据的结果
        return {
            "data": result["data"],
            "_semantic_meta": result.get("_semantic_meta", {}),
            "lineage_summary": await self._get_lineage_summary(key),
        }
```

---

## 十一、改造范围清单

### 11.1 改造文件汇总（22个）

| 类别 | 数量 | 文件列表 |
|------|------|----------|
| **改造现有文件** | 7 | `collection_registry.py`, `generic_query_engine.py`, `data_hub_service.py`, `data_context.py`, `data_query_tool.py`, `zy_data.py`, `settings.py` |
| **新增服务文件** | 6 | `semantic_layer.py`, `lineage_tracker.py`, `lineage_graph.py`, `quality_service.py`, `deeplink_service.py`, `semantic_client.py`(Agent) |
| **新增模型文件** | 3 | `semantic.py`, `lineage.py`, `quality.py` |
| **新增API文件** | 3 | `semantic.py`, `lineage.py`, `quality.py` |
| **新增配置/脚本** | 3 | `semantic_catalog.py`, `seed_semantic_layer.py`, `refresh_lineage.py` |

### 11.2 新增MongoDB集合（7个）

| 集合名 | 用途 | 预估规模 |
|--------|------|----------|
| `_semantic_definitions` | 语义定义(L1-L4) | ~1000条 |
| `_physical_mappings` | 物理映射 | ~2000条 |
| `_lineage_nodes` | 血缘节点 | ~10000条 |
| `_lineage_edges` | 血缘边 | ~50000条 |
| `_data_quality_scores` | 质量评分 | ~50000条 |
| `_semantic_terms` | 术语表 | ~200条 |
| `_association_chains` | 关联链 | ~50条 |

### 11.3 前端改造范围

| 组件/页面 | 类型 | 工作量 |
|-----------|------|--------|
| `zyDataDomain.js`语义解析 | 改造 | 2天 |
| FieldTooltip组件 | 新增 | 1天 |
| SemanticTable组件 | 新增 | 2天 |
| MiniLineageTree组件 | 新增 | 2天 |
| DeepLinkButton组件 | 新增 | 1天 |
| LineageGraph页面 | 新增 | 5天 |
| QualityDashboard页面 | 新增 | 3天 |
| semanticClient.js | 新增 | 1天 |
| lineageClient.js | 新增 | 1天 |

---

## 十二、实施路线图

### Phase 1: 语义层基础 + 血缘骨架（Week 1-2）

**目标**: 搭建语义层和血缘追踪的基础设施

| 任务 | 工时 | 负责人 | 交付物 |
|------|------|--------|--------|
| 设计语义层数据模型(L1-L4) | 2天 | 架构师 | `models/semantic.py` |
| 设计血缘数据模型 | 2天 | 架构师 | `models/lineage.py` |
| 实现语义层服务 | 3天 | 后端 | `services/semantic_layer.py` |
| 实现血缘追踪服务 | 3天 | 后端 | `services/lineage_tracker.py` |
| 实现静态注册采集 | 2天 | 后端 | `scripts/seed_semantic_layer.py` |
| 扩展CollectionRegistry | 1天 | 后端 | 改造`collection_registry.py` |
| 语义层API路由 | 2天 | 后端 | `api/semantic.py` |
| 血缘API路由 | 2天 | 后端 | `api/lineage.py` |
| 单元测试 | 2天 | QA | 测试报告 |

**里程碑**: 语义层API可查询，血缘骨架可展示基础图谱

---

### Phase 2: 前后端链路增强 + Agent集成（Week 3-4）

**目标**: 实现前后端语义增强和Agent语义感知

| 任务 | 工时 | 负责人 | 交付物 |
|------|------|--------|--------|
| GenericQueryEngine语义增强 | 2天 | 后端 | 改造`generic_query_engine.py` |
| DataHubService血缘嵌入 | 2天 | 后端 | 改造`data_hub_service.py` |
| DataContext语义注入 | 2天 | 后端 | 改造`data_context.py` |
| DataQueryTool语义增强 | 2天 | 后端 | 改造`data_query_tool.py` |
| 动态观测采集器 | 3天 | 后端 | 装饰器/上下文管理器 |
| 前端Schema语义解析 | 2天 | 前端 | 改造`zyDataDomain.js` |
| FieldTooltip组件 | 1天 | 前端 | `components/FieldTooltip.vue` |
| SemanticTable组件 | 2天 | 前端 | `components/SemanticTable.vue` |
| Agent语义Prompt工程 | 2天 | 算法 | Prompt模板 |
| 集成测试 | 2天 | QA | 测试报告 |

**里程碑**: 前端表格展示字段中文名，Agent能解释字段含义

---

### Phase 3: 血缘图谱 + 质量评估（Week 5）

**目标**: 实现血缘图谱可视化和数据质量评估

| 任务 | 工时 | 负责人 | 交付物 |
|------|------|--------|--------|
| 血缘图谱查询服务 | 2天 | 后端 | `services/lineage_graph.py` |
| 影响分析服务 | 2天 | 后端 | 影响分析API |
| DeepLink服务 | 1天 | 后端 | `services/deeplink_service.py` |
| 质量评估服务 | 2天 | 后端 | `services/quality_service.py` |
| 质量API路由 | 1天 | 后端 | `api/quality.py` |
| LineageGraph页面 | 3天 | 前端 | `pages/LineageGraph.vue` |
| MiniLineageTree组件 | 2天 | 前端 | `components/MiniLineageTree.vue` |
| DeepLinkButton组件 | 1天 | 前端 | `components/DeepLinkButton.vue` |
| 集成测试 | 1天 | QA | 测试报告 |

**里程碑**: 血缘图谱页面可用，质量评分API可查询

---

### Phase 4: 监控治理 + 性能优化（Week 6）

**目标**: 完善监控治理和性能优化

| 任务 | 工时 | 负责人 | 交付物 |
|------|------|--------|--------|
| 事后回溯采集器 | 2天 | 后端 | 日志分析脚本 |
| 血缘健康监控 | 2天 | 后端 | 监控报表 |
| 质量仪表盘页面 | 2天 | 前端 | `pages/QualityDashboard.vue` |
| 性能优化（索引/缓存） | 2天 | 后端 | 性能测试报告 |
| 性能优化（前端渲染） | 1天 | 前端 | 性能测试报告 |
| 文档完善 | 2天 | 架构师 | API文档/开发指南 |
| 端到端测试 | 2天 | QA | 测试报告 |
| 用户验收 | 1天 | 产品 | 验收报告 |

**里程碑**: 系统上线，文档完整

---

### 总体时间线

```
Week 1-2:  [████████████████████] Phase 1: 语义层基础 + 血缘骨架
Week 3-4:  [████████████████████] Phase 2: 前后端链路 + Agent集成
Week 5:    [██████████]          Phase 3: 血缘图谱 + 质量评估
Week 6:    [██████████]          Phase 4: 监控治理 + 性能优化
```

**总工期**: 6周  
**总工时**: ~120人天  
**团队配置**: 2后端 + 1前端 + 0.5算法 + 0.5QA

---

## 十三、风险与对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| 语义层建设工作量超预期 | 中 | 高 | 优先覆盖核心字段（跨域关联键），非核心字段后续迭代 |
| 血缘采集性能开销 | 中 | 中 | 异步非阻塞采集，内存队列+批量写入，目标<5ms |
| 前端兼容性 | 低 | 中 | 渐进式增强，旧版忽略新字段，不影响现有功能 |
| MongoDB图查询性能 | 中 | 中 | 合理设计索引，深度限制（默认3层），必要时预计算热点路径 |
| 数据一致性 | 低 | 高 | 血缘记录与业务操作同一事务，失败时记录补偿日志 |
| 术语表维护成本 | 中 | 低 | 建立术语表维护流程，业务变更时同步更新 |
| Agent Prompt溢出 | 中 | 中 | 语义信息按需加载，限制注入Prompt的字段数量 |

---

## 附录

### A. 关键设计决策记录

| 决策ID | 决策内容 | 选择 | 理由 | 日期 |
|--------|----------|------|------|------|
| ADR-001 | 语义层与Registry关系 | 扩展而非替换 | 保护现有`DOMAIN_METADATA`投资 | 2026-06-03 |
| ADR-002 | 血缘存储模型 | 图模型(节点+边)存MongoDB | 与现有技术栈一致，避免引入Neo4j | 2026-06-03 |
| ADR-003 | 血缘粒度 | 字段级 | 满足金融数据精度要求 | 2026-06-03 |
| ADR-004 | Agent集成方式 | 依赖注入 | 保持现有架构不变，增量增强 | 2026-06-03 |
| ADR-005 | 前端语义获取 | API内嵌`_semantic_meta` | 减少请求次数，支持离线缓存 | 2026-06-03 |
| ADR-006 | 采集模型 | 三层(静态+动态+回溯) | 冷启动有骨架，运行时有血肉，事后可补录 | 2026-06-03 |
| ADR-007 | 节点ID格式 | 结构化`{type}:{namespace}:{name}:{version}` | 自描述、支持前缀查询、版本化 | 2026-06-03 |
| ADR-008 | 语义画像分层 | 四层(L1-L4) | 从基础到质量，层层递进，按需使用 | 2026-06-03 |
| ADR-009 | 质量评分维度 | 六维度(唯一性/完整性/一致性/时效性/准确性/稳定性) | 覆盖金融数据核心质量要求 | 2026-06-03 |

### B. 参考文档

- `stock-research-end/docs/data_lineage_architecture_design.md` — 血缘架构设计V1
- `data-semantic-layer-design` Skill — 语义层设计工作流
- `session-2026-06-02-data-lineage-architecture-v2.md` — 血缘架构V2
- `session-2026-06-03-semantic-lineage-fullstack-embedding.md` — 全链路嵌入设计V4

---

**文档结束**
