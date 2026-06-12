# 数据血缘 × 数据语义层 — 前后端全链路嵌入需求设计书

**版本**: v1.0  
**设计日期**: 2026-06-03  
**目标项目**: `portfilio-end` (金融资管数据平台)  
**关联项目**: `stock-research-end` (投研智能体平台)  

---

## 目录

1. [战略愿景与目标](#一战略愿景与目标)
2. [现状基线分析](#二现状基线分析)
3. [差距分析矩阵](#三差距分析矩阵)
4. [总体架构设计](#四总体架构设计)
5. [六大模块详细需求](#五六大模块详细需求)
6. [数据模型设计](#六数据模型设计)
7. [接口契约设计](#七接口契约设计)
8. [前后端链路改造](#八前后端链路改造)
9. [Agent链路改造](#九agent链路改造)
10. [改造范围清单](#十改造范围清单)
11. [实施路线图](#十一实施路线图)
12. [风险与对策](#十二风险与对策)

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
| 语义层覆盖 | 概念层(9域82表) | 概念层+逻辑层+物理层 | 字段级语义覆盖率100% |
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

## 四、总体架构设计

### 4.1 四层架构

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
│  │  - 概念层管理    │ │  - 静态注册      │ │  - 导入血缘      │ │  - 告警  │  │
│  │  - 逻辑层管理    │ │  - 动态观测      │ │  - 质量评估      │ │  - 报表  │  │
│  │  - 物理层映射    │ │  - 事后回溯      │ │  - 变更检测      │ │  - 审计  │  │
│  │  - 术语表        │ │  - 影响分析      │ │                 │ │          │  │
│  │  - 语义搜索      │ │  - 图谱查询      │ │                 │ │          │  │
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

### 4.2 核心设计原则

| 原则 | 说明 | 具体措施 |
|------|------|----------|
| **保护现有投资** | 不替换`DOMAIN_METADATA`，而是扩展 | 语义层作为独立集合，通过`collection_name`关联 |
| **技术栈一致** | 继续使用MongoDB | 图模型用节点+边集合存储，不引入Neo4j |
| **增量增强** | Agent架构不变 | `SemanticLayerClient`作为`DataContext`的依赖注入 |
| **零侵入采集** | 血缘采集不阻塞主流程 | 异步内存队列+批量写入，目标<5ms/调用 |
| **结构化节点ID** | 自描述、可前缀查询 | 格式: `{type}:{namespace}:{name}:{version}` |

---

## 五、六大模块详细需求

### 模块1: 语义层服务 (Semantic Layer Service)

#### 1.1 概念层扩展

**需求编号**: SEM-001  
**需求名称**: 语义实体定义管理  
**优先级**: P0  
**描述**: 基于现有`DOMAIN_METADATA`构建语义实体定义，建立业务实体与数据表的映射关系。

**功能需求**:
- 定义6大核心语义实体: SecurityAsset(证券资产)、Issuer(发行主体)、InvestmentProduct(投资产品)、Customer(客户)、Trade(交易流水)、Valuation(估值记录)
- 每个实体包含: 英文名、中文名、业务定义、主键字段、覆盖域列表、关联实体列表
- 实体与表的映射: 一个实体可对应多张表（如SecurityAsset对应资产域12张表）
- 提供CRUD API: `POST /api/v1/semantic/entity`, `GET /api/v1/semantic/entity/{name}`

**数据模型**:
```python
class SemanticEntity(BaseModel):
    entity_name: str           # "SecurityAsset"
    display_name: str          # "证券资产"
    description: str           # "可交易的标准化金融资产..."
    primary_identifier: dict   # {"field": "AST_CD", "description": "证券代码"}
    domains: list[str]         # ["asset", "trading", "valuation", "market", "risk"]
    related_entities: list[dict]  # [{"entity": "Issuer", "relation": "issued_by", "key": "ISR_ID"}]
    mapped_tables: list[str]   # ["dwd_ast_info", "dwd_ast_info_ch", ...]
    created_at: datetime
    updated_at: datetime
```

**验收标准**:
- [ ] 6大实体全部定义完成
- [ ] 每个实体至少映射到2张表
- [ ] API支持按域过滤查询实体

---

**需求编号**: SEM-002  
**需求名称**: 跨域关联语义链定义  
**优先级**: P0  
**描述**: 定义实体间的关联路径，支持跨域查询和数据血缘追踪。

**功能需求**:
- 定义典型关联链: 资产→主体、产品→估值、客户→产品、交易→资产/产品、估值→产品/资产
- 每条关联链包含: 路径（域→表→键→ cardinality）、join条件、业务含义
- 关联链用于: 血缘图谱构建、跨域查询推荐、影响分析

**数据模型**:
```python
class AssociationChain(BaseModel):
    chain_name: str            # "asset_to_valuation"
    description: str           # "证券资产 → 估值明细"
    path: list[dict]           # [{"domain": "asset", "table": "dwd_ast_info", "key": "AST_CD", "cardinality": "1"}, ...]
    join_condition: str        # "asset.AST_CD = valuation.AST_CD"
    business_meaning: str      # "查询某证券的历史估值记录"
```

---

#### 1.2 逻辑层建设

**需求编号**: SEM-003  
**需求名称**: 字段级语义画像  
**优先级**: P0  
**描述**: 为核心字段构建详细的语义画像，包括基础语义、跨域映射、关联语义、特征标签、质量画像。

**功能需求**:
- 字段语义画像包含5个维度:
  1. **基础语义**: 中文名、数据类型、业务定义、示例值
  2. **跨域映射**: 字段在不同系统中的名称映射（如ZY系统`AST_CD` vs JY系统`SEC_ID`）
  3. **关联语义**: 主键/外键关系、关联表、cardinality
  4. **特征标签**: ["主键", "跨域关联键", "业务主键", "检索键", "敏感字段", "时序字段"]
  5. **质量画像**: 唯一性、完整性、一致性、时效性评分
- 优先覆盖关键字段: AST_CD、ISR_ID、PORT_ID、CUSTOMER_ID、BIZ_DT等跨域关联键
- 提供API: `GET /api/v1/semantic/field/{collection}/{field_name}`

**数据模型**:
```python
class FieldSemanticProfile(BaseModel):
    collection_name: str
    field_name: str
    
    # 基础语义
    display_name: str
    data_type: str
    business_definition: str
    example_values: list[str]
    
    # 跨域映射
    cross_domain_mapping: dict  # {"zy_system": "AST_CD", "jy_system": "SEC_ID", "mapping_type": "direct"}
    
    # 关联语义
    is_primary_key: bool
    is_foreign_key: bool
    foreign_key_ref: Optional[str]  # "dwd_ast_info.AST_CD"
    related_tables: list[str]
    
    # 特征标签
    tags: list[str]
    
    # 质量画像
    quality_profile: dict  # {"uniqueness": "全局唯一", "completeness": "非空", ...}
```

**验收标准**:
- [ ] 至少500个核心字段完成语义画像
- [ ] 跨域关联键100%覆盖
- [ ] 字段画像API响应时间<100ms

---

**需求编号**: SEM-004  
**需求名称**: 核心术语表  
**优先级**: P1  
**描述**: 建立统一业务术语表，消除跨域/跨系统的术语歧义。

**功能需求**:
- 术语表字段: 术语、英文、定义、取值范围、相关字段、同义词
- 覆盖核心术语: 证券代码、组合代码、主体代码、数据日期、交易日、估值日期、币种、风险等级
- 术语表驱动: Agent解释字段时引用术语表定义
- 提供API: `GET /api/v1/semantic/term/{term_name}`, `GET /api/v1/semantic/terms`

---

#### 1.3 物理层映射

**需求编号**: SEM-005  
**需求名称**: 物理映射管理  
**优先级**: P1  
**描述**: 建立逻辑字段到物理存储的映射关系，支持多源数据整合。

**功能需求**:
- 物理映射包含: 逻辑字段名、物理字段名、存储位置(MongoDB集合)、数据类型、约束条件
- 支持多源映射: 一个逻辑字段可映射到多个物理字段（如ZY系统的`AST_CD`和JY系统的`SEC_ID`）
- 映射版本管理: 支持字段变更的历史版本追踪
- 提供API: `GET /api/v1/semantic/mapping/{logical_field}`

**数据模型**:
```python
class PhysicalMapping(BaseModel):
    logical_field: str         # "security_code"
    physical_fields: list[dict]  # [{"collection": "dwd_ast_info", "field": "AST_CD", "system": "ZY"}, ...]
    data_type: str
    constraints: list[str]
    version: str
    effective_date: datetime
    deprecated: bool
```

---

### 模块2: 血缘追踪服务 (Lineage Tracking Service)

#### 2.1 核心数据模型

**需求编号**: LIN-001  
**需求名称**: 血缘节点与边模型  
**优先级**: P0  
**描述**: 定义血缘追踪的核心数据模型，支持10种节点类型和4种边类型。

**节点类型枚举**:
| 类型 | 说明 | 示例 |
|------|------|------|
| `SOURCE_API` | 上游数据源API | `get_py_result:subject_opinion_risk` |
| `STORAGE_MONGO` | MongoDB存储集合 | `storage_mongo:asset:dwd_ast_info` |
| `TRANSFORM_TOOL` | 数据转换工具 | `transform_tool:data_query_tool` |
| `CONSUMER_UI` | 前端消费组件 | `consumer_ui:frontend:pie_risk_level` |
| `CONSUMER_AGENT` | Agent消费 | `consumer_agent:chat:data_analyze` |
| `ENTITY` | 业务实体 | `entity:SecurityAsset:BOND_2024_001` |
| `FIELD` | 字段级节点 | `field:asset:dwd_ast_info:AST_CD` |
| `REPORT` | 报表/成果物 | `report:daily_valuation:20240601` |
| `SESSION` | 对话会话 | `session:chat:conv_abc123` |
| `BATCH` | 导入批次 | `batch:subject_opinion_risk:batch_xyz` |

**边类型枚举**:
| 类型 | 说明 |
|------|------|
| `DATA_FLOW` | 数据流向 |
| `CONTROL_FLOW` | 控制依赖 |
| `TRIGGER` | 触发关系 |
| `DERIVED_FROM` | 派生关系 |

**节点ID格式**: `{type}:{namespace}:{name}:{version}`
- 示例: `storage_mongo:asset:dwd_ast_info:1.0`
- 优势: 自描述、支持前缀查询、版本化

**数据模型**:
```python
class LineageNode(BaseModel):
    node_id: str              # 结构化ID
    node_type: NodeType
    name: str
    namespace: str
    version: str = "1.0"
    
    # 类型专属配置
    source_config: Optional[SourceConfig] = None      # SOURCE_API用
    storage_config: Optional[StorageConfig] = None    # STORAGE_MONGO用
    transform_config: Optional[TransformConfig] = None # TRANSFORM_TOOL用
    consumer_config: Optional[ConsumerConfig] = None  # CONSUMER_UI/AGENT用
    
    # 通用元数据
    owner: str = "system"
    description: str = ""
    tags: list[str] = []
    sla_level: str = "P1"
    
    created_at: datetime
    updated_at: datetime
    last_seen_at: Optional[datetime] = None

class LineageEdge(BaseModel):
    edge_id: str
    edge_type: EdgeType
    from_node: str            # 上游节点ID
    to_node: str              # 下游节点ID
    data_flow: Optional[DataFlowMeta] = None  # 字段映射、转换逻辑
    confidence: float = 1.0   # 0.0-1.0
    is_manual: bool = False
    first_observed_at: datetime
    last_observed_at: datetime
    observation_count: int = 1
```

---

#### 2.2 三层采集模型

**需求编号**: LIN-002  
**需求名称**: 静态注册层  
**优先级**: P0  
**描述**: 系统启动时从现有元数据自动生成基础血缘骨架。

**功能需求**:
- 从`ConnectorDefinition`生成: SOURCE_API → STORAGE_MONGO 边
- 从`DOMAIN_METADATA.foreign_keys`生成: 表间关联边（STORAGE_MONGO → STORAGE_MONGO）
- 从`chart_recipes`生成: STORAGE_MONGO → CONSUMER_UI 边
- 系统启动时执行一次，后续增量更新

**采集逻辑**:
```python
# 1. ConnectorDefinition → SOURCE_API + STORAGE_MONGO + DATA_FLOW边
for conn in CONNECTOR_REGISTRY.values():
    source_node = LineageNode(
        node_id=f"source_api:{conn.family}:{conn.connector_id}:1.0",
        node_type=NodeType.SOURCE_API,
        source_config=SourceConfig(
            data_source=conn.family,
            api_name=conn.resource_default,
            endpoint_url=conn.default_upstream_url,
        ),
    )
    storage_node = LineageNode(
        node_id=f"storage_mongo:{conn.connector_id}:{conn.records_collection}:1.0",
        node_type=NodeType.STORAGE_MONGO,
        storage_config=StorageConfig(
            mongo_collection=conn.records_collection,
            primary_key=conn.primary_key,
        ),
    )
    edge = LineageEdge(
        edge_type=EdgeType.DATA_FLOW,
        from_node=source_node.node_id,
        to_node=storage_node.node_id,
    )

# 2. DOMAIN_METADATA.foreign_keys → 跨表关联边
for domain, domain_info in DOMAIN_METADATA.items():
    for table_name, table_meta in domain_info["tables"].items():
        for fk_field, ref in table_meta.get("foreign_keys", {}).items():
            ref_table, ref_field = ref.split(".")
            edge = LineageEdge(
                edge_type=EdgeType.DATA_FLOW,
                from_node=f"storage_mongo:{domain}:{ref_table}:1.0",
                to_node=f"storage_mongo:{domain}:{table_name}:1.0",
                data_flow=DataFlowMeta(schema_mapping={fk_field: ref_field}),
            )
```

---

**需求编号**: LIN-003  
**需求名称**: 动态观测层  
**优先级**: P0  
**描述**: 运行时零侵入采集工具调用链和查询血缘。

**功能需求**:
- 集成点1: `DataHubService.import_from_upstream()`完成后，记录 SOURCE_API → STORAGE_MONGO 血缘
- 集成点2: `GenericQueryEngine.find()/aggregate()`执行后，记录 STORAGE_MONGO → TRANSFORM_TOOL 血缘
- 集成点3: `DataContext.store()`存储工具输出时，记录 TRANSFORM_TOOL → CONSUMER_AGENT 血缘
- 集成点4: `DataQueryTool.execute()`完成后，记录完整工具调用链
- 性能目标: <5ms延迟, <1%存储开销, <0.1%丢失率
- 实现方式: 异步内存队列+批量写入，装饰器/上下文管理器零侵入植入

**装饰器示例**:
```python
@lineage_observe(node_type=NodeType.TRANSFORM_TOOL, operation="query")
async def find(self, collection, filters, ...):
    # 原有逻辑不变
    ...
```

---

**需求编号**: LIN-004  
**需求名称**: 事后回溯层  
**优先级**: P1  
**描述**: 从现有审计日志反推未注册的血缘关系。

**功能需求**:
- 从`_query_audit_log`反推: 查询模式、高频查询路径、未注册集合的访问
- 从`DataContext._tool_history`反推: 工具调用链、数据流方向
- 从MongoDB profiler日志反推: 慢查询、聚合模式
- 定期执行（每日凌晨），补录缺失血缘

---

#### 2.3 血缘查询与影响分析

**需求编号**: LIN-005  
**需求名称**: 血缘图谱查询  
**优先级**: P0  
**描述**: 提供血缘图谱的查询和可视化数据接口。

**功能需求**:
- 正向追溯: 从数据源出发，追踪所有下游依赖
- 反向溯源: 从消费端出发，追溯所有上游来源
- 字段级影响分析: 给定字段变更，评估影响范围
- 深度控制: 支持指定遍历深度（默认3层，最大10层）
- 提供API:
  - `GET /api/v1/lineage/graph?root_id={id}&direction=downstream&depth=3`
  - `GET /api/v1/lineage/impact?node_id={id}&field={field_name}`
  - `GET /api/v1/lineage/source?node_id={id}`

---

**需求编号**: LIN-006  
**需求名称**: DeepLink路由协议  
**优先级**: P1  
**描述**: 实现对话成果物到前端界面的关联跳转。

**功能需求**:
- URL格式: `/lineage?dl={base64_payload}&view={graph|table|timeline}&focus={node_id}`
- 7种锚点类型: SYMBOL | DATE | FIELD | CHART_POINT | TABLE_CELL | TOOL_CALL | SESSION
- 5种意图路由:
  - `VIEW_LINEAGE` → 完整血缘图谱
  - `VIEW_SOURCE` → 数据来源详情
  - `VIEW_IMPACT` → 影响分析
  - `VIEW_QUALITY` → 数据质量
  - `VIEW_HISTORY` → 变更历史
- 提供API: `POST /api/v1/lineage/deeplink`

---

### 模块3: 前后端链路语义增强

#### 3.1 Schema语义标注

**需求编号**: FEB-001  
**需求名称**: 语义增强Schema返回  
**优先级**: P0  
**描述**: API返回的Schema中嵌入字段级语义元数据。

**功能需求**:
- 在`GenericQueryEngine.find()`返回结果中增加`_semantic_meta`字段
- `_semantic_meta`包含:
  - `collection`: 集合语义信息（display_name, description, domain）
  - `fields`: 字段语义映射（field_name → display_name, description, tags, quality_score）
  - `foreign_keys`: 外键关系提示
  - `typical_queries`: 典型查询示例
- 前端可利用`_semantic_meta`渲染字段Tooltip、表头中文名、枚举值提示

**返回格式示例**:
```json
{
  "data": [...],
  "total": 100,
  "page_info": {...},
  "_semantic_meta": {
    "collection": {
      "display_name": "资产基础信息表",
      "description": "记录所有资产的代码、名称、类型...",
      "domain": "asset"
    },
    "fields": {
      "AST_CD": {
        "display_name": "证券代码",
        "description": "唯一标识一只可交易证券的代码",
        "tags": ["主键", "跨域关联键"],
        "quality_score": 0.95
      },
      "COUPON_RATE": {
        "display_name": "票面利率",
        "description": "债券的票面年利率",
        "tags": ["数值字段"],
        "unit": "%",
        "quality_score": 0.88
      }
    },
    "foreign_keys": {
      "ISR_ID": "dwd_isr_institution.ISR_ID"
    }
  }
}
```

---

#### 3.2 前端语义展示

**需求编号**: FEB-002  
**需求名称**: 字段Tooltip与表头语义化  
**优先级**: P1  
**描述**: 前端表格展示字段中文名和业务含义Tooltip。

**功能需求**:
- 表格列头优先显示`display_name`，鼠标悬停显示`description`
- 关键字段（如AST_CD、ISR_ID）显示标签徽章（主键、外键、关联键）
- 枚举值字段显示下拉提示（如风险等级R1-R5的含义）
- 数值字段显示单位（如%、万元、BP）
- 质量评分低的字段显示警告图标

---

**需求编号**: FEB-003  
**需求名称**: 血缘图谱可视化页面  
**优先级**: P1  
**描述**: 实现血缘图谱的前端可视化展示。

**功能需求**:
- Mini血缘树: 对话界面中紧凑展示工具调用链（深度2）
- 全屏血缘图谱: 独立页面展示完整血缘关系（深度5+）
- 节点交互: 点击节点显示详情卡片（名称、类型、来源、质量评分）
- 边交互: 悬停边显示转换逻辑和字段映射
- 筛选功能: 按节点类型、域、时间范围筛选
- 导出功能: 支持导出PNG/SVG/JSON

---

### 模块4: Agent语义增强

#### 4.1 语义感知DataContext

**需求编号**: AGT-001  
**需求名称**: SemanticLayerClient集成  
**优先级**: P0  
**描述**: 为DataContext注入语义层客户端，使Agent具备语义感知能力。

**功能需求**:
- 创建`SemanticLayerClient`类，封装语义层查询接口
- `SemanticLayerClient`作为`DataContext`的可选依赖注入
- Agent查询时，自动获取字段语义描述注入Prompt
- Agent解释查询结果时，引用术语表定义

**集成方式**:
```python
class DataContext:
    def __init__(self, conversation_id: str, semantic_client: Optional[SemanticLayerClient] = None):
        self.conversation_id = conversation_id
        self._semantic_client = semantic_client  # 新增
        # ... 现有代码 ...
    
    async def get_semantic_schema(self, collection: str) -> dict:
        """获取语义增强的Schema"""
        if self._semantic_client:
            return await self._semantic_client.get_schema(collection)
        return {}  # 降级为无语义
```

---

#### 4.2 智能查询推荐

**需求编号**: AGT-002  
**需求名称**: 基于语义的查询推荐  
**优先级**: P1  
**描述**: Agent根据用户意图推荐最优查询路径。

**功能需求**:
- 基于语义实体识别用户查询意图（如"查茅台的估值"→识别为SecurityAsset+Valuation）
- 推荐跨域关联链（如"查茅台的发行人财务"→推荐asset→issuer→finance路径）
- 推荐字段选择（如"查估值"→推荐VAL_NET_PRC、VAL_FULL_PRC等关键字段）
- 推荐过滤条件（如"最近一周"→自动添加BIZ_DT范围）

---

#### 4.3 血缘解释能力

**需求编号**: AGT-003  
**需求名称**: Agent血缘解释  
**优先级**: P1  
**描述**: Agent能够解释数据的来源和流转路径。

**功能需求**:
- 用户问"这个数据从哪来"→Agent调用血缘服务返回来源链路
- 用户问"这个字段什么意思"→Agent调用术语表返回定义
- 用户问"改了会影响什么"→Agent调用影响分析返回下游依赖
- 解释结果以自然语言+Mini血缘树形式呈现

---

### 模块5: 数据接入层血缘嵌入

#### 5.1 导入血缘记录

**需求编号**: DHS-001  
**需求名称**: DataHub导入血缘  
**优先级**: P0  
**描述**: 在数据导入流程中嵌入血缘记录。

**功能需求**:
- `DataHubService.import_from_upstream()`完成后，自动创建:
  - SOURCE_API节点（记录上游API信息）
  - STORAGE_MONGO节点（记录目标集合信息）
  - BATCH节点（记录批次信息）
  - DATA_FLOW边（SOURCE_API → STORAGE_MONGO）
  - TRIGGER边（BATCH → STORAGE_MONGO）
- 记录导入参数、时间、数据量、成功率
- 失败时记录错误信息和重试状态

---

#### 5.2 质量评估

**需求编号**: DHS-002  
**需求名称**: 导入数据质量评估  
**优先级**: P1  
**描述**: 对导入数据进行自动质量评估。

**功能需求**:
- 完整性评分: 非空字段占比
- 一致性评分: 外键完整性、枚举值合规
- 时效性评分: 数据日期与导入日期的差距
- 准确性评分: 数值范围合理性（如收益率>-50%且<100%）
- 质量评分写入`_data_quality_scores`集合
- 低质量数据触发告警

---

### 模块6: 监控治理

#### 6.1 血缘健康监控

**需求编号**: MON-001  
**需求名称**: 血缘图谱健康度监控  
**优先级**: P1  
**描述**: 监控血缘图谱的完整性和准确性。

**功能需求**:
- 孤儿节点检测: 无入边且无出边的节点
- 断链检测: 存在边但节点缺失的情况
- 覆盖率监控: 已注册集合的血缘覆盖率
- 新鲜度监控: 血缘记录的最后观测时间
- 每日生成血缘健康报告

---

#### 6.2 数据质量监控

**需求编号**: MON-002  
**需求名称**: 数据质量仪表盘  
**优先级**: P2  
**描述**: 展示全域数据质量评分和趋势。

**功能需求**:
- 按域汇总质量评分
- 质量评分趋势图（近30天）
- 低质量字段TOP10
- 质量告警列表
- 提供API: `GET /api/v1/quality/dashboard`

---

## 六、数据模型设计

### 6.1 新增MongoDB集合

| 集合名 | 用途 | 预估文档数 | 索引 |
|--------|------|-----------|------|
| `_semantic_definitions` | 语义实体/字段定义 | ~1000 | `entity_name`, `collection_name+field_name` |
| `_physical_mappings` | 物理映射 | ~2000 | `logical_field`, `physical_field+collection` |
| `_lineage_nodes` | 血缘节点 | ~10000 | `node_id`(唯一), `node_type`, `namespace` |
| `_lineage_edges` | 血缘边 | ~50000 | `from_node+to_node`, `edge_type` |
| `_data_quality_scores` | 质量评分 | ~50000 | `collection+field+date`, `score` |
| `_semantic_terms` | 术语表 | ~200 | `term_name`(唯一) |
| `_association_chains` | 关联链 | ~50 | `chain_name`(唯一), `domain` |

### 6.2 集合Schema详细定义

#### `_semantic_definitions`

```javascript
{
  "_id": ObjectId,
  "definition_type": "entity" | "field",  // 实体定义 or 字段定义
  
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
  "display_name": "证券代码",
  "data_type": "string",
  "business_definition": "唯一标识一只可交易证券的代码",
  "example_values": ["BOND_2024_001", "STK_688521_SH"],
  "cross_domain_mapping": {"zy_system": "AST_CD", "jy_system": "SEC_ID"},
  "is_primary_key": true,
  "is_foreign_key": false,
  "foreign_key_ref": null,
  "tags": ["主键", "跨域关联键"],
  "quality_profile": {
    "uniqueness": "全局唯一",
    "completeness": "非空",
    "consistency": "跨域一致",
    "timeliness": "静态"
  },
  
  "created_at": ISODate,
  "updated_at": ISODate
}
```

#### `_lineage_nodes`

```javascript
{
  "_id": ObjectId,
  "node_id": "storage_mongo:asset:dwd_ast_info:1.0",  // 结构化ID
  "node_type": "STORAGE_MONGO",
  "name": "dwd_ast_info",
  "namespace": "asset",
  "version": "1.0",
  
  // 类型专属配置
  "source_config": null,
  "storage_config": {
    "mongo_collection": "dwd_ast_info",
    "database": "asset_allocation",
    "primary_key": "AST_CD"
  },
  "transform_config": null,
  "consumer_config": null,
  
  // 通用元数据
  "owner": "system",
  "description": "资产基础信息表",
  "tags": ["asset", "master_data"],
  "sla_level": "P1",
  
  "created_at": ISODate,
  "updated_at": ISODate,
  "last_seen_at": ISODate
}
```

#### `_lineage_edges`

```javascript
{
  "_id": ObjectId,
  "edge_id": "edge_abc123",
  "edge_type": "DATA_FLOW",
  "from_node": "source_api:get_py_result:subject_opinion_risk:1.0",
  "to_node": "storage_mongo:subject_opinion_risk:subject_risk_records:1.0",
  "data_flow": {
    "schema_mapping": {"risk_id": "risk_id", "biz_date": "biz_date"},
    "transform_logic": "直接写入",
    "data_volume": 10000
  },
  "confidence": 1.0,
  "is_manual": false,
  "first_observed_at": ISODate,
  "last_observed_at": ISODate,
  "observation_count": 42
}
```

---

## 七、接口契约设计

### 7.1 语义层API

| 方法 | 路径 | 说明 | 请求体/参数 | 响应 |
|------|------|------|------------|------|
| GET | `/api/v1/semantic/entities` | 列出所有语义实体 | `?domain={domain}` | `[{entity_name, display_name, ...}]` |
| GET | `/api/v1/semantic/entity/{name}` | 获取实体详情 | - | `{entity_name, display_name, mapped_tables, ...}` |
| GET | `/api/v1/semantic/field/{collection}/{field}` | 获取字段语义画像 | - | `{field_name, display_name, tags, quality_profile, ...}` |
| GET | `/api/v1/semantic/schema/{collection}` | 获取语义增强Schema | - | `{collection, fields: {...}, foreign_keys, ...}` |
| GET | `/api/v1/semantic/search` | 语义搜索 | `?q={keyword}&type={entity|field}` | `[{name, type, relevance, ...}]` |
| GET | `/api/v1/semantic/terms` | 术语表 | `?term={term_name}` | `[{term, definition, related_fields}]` |

### 7.2 血缘API

| 方法 | 路径 | 说明 | 请求体/参数 | 响应 |
|------|------|------|------------|------|
| GET | `/api/v1/lineage/graph` | 血缘图谱 | `?root_id={id}&direction={up|down}&depth={n}` | `{nodes: [...], edges: [...]}` |
| GET | `/api/v1/lineage/impact` | 影响分析 | `?node_id={id}&field={field}` | `{affected_nodes: [...], risk_level}` |
| GET | `/api/v1/lineage/source` | 溯源查询 | `?node_id={id}` | `{source_chain: [...]}` |
| POST | `/api/v1/lineage/deeplink` | 生成DeepLink | `{lineage_id, target_view, intent}` | `{url, lineage_id}` |
| POST | `/api/v1/lineage/register` | 注册血缘 | `{node, edges}` | `{node_id, edge_ids}` |

### 7.3 质量API

| 方法 | 路径 | 说明 | 请求体/参数 | 响应 |
|------|------|------|------------|------|
| GET | `/api/v1/quality/score/{collection}` | 集合质量评分 | `?field={field}&date={date}` | `{collection, overall_score, dimensions: {...}}` |
| GET | `/api/v1/quality/badge/{collection}` | 质量徽章 | - | `{badge: "green|yellow|red", score, issues: [...]}` |
| GET | `/api/v1/quality/dashboard` | 质量仪表盘 | `?domain={domain}` | `{domains: [...], trends: [...], alerts: [...]}` |

---

## 八、前后端链路改造

### 8.1 后端改造清单

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
| `app/models/semantic.py` | **新增**: 语义层数据模型 | P0 |
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

### 8.2 前端改造清单

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

## 九、Agent链路改造

### 9.1 DataContext增强

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

### 9.2 DataQueryTool增强

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

## 十、改造范围清单

### 10.1 改造文件汇总（22个）

| 类别 | 数量 | 文件列表 |
|------|------|----------|
| **改造现有文件** | 7 | `collection_registry.py`, `generic_query_engine.py`, `data_hub_service.py`, `data_context.py`, `data_query_tool.py`, `zy_data.py`, `settings.py` |
| **新增服务文件** | 6 | `semantic_layer.py`, `lineage_tracker.py`, `lineage_graph.py`, `quality_service.py`, `deeplink_service.py`, `semantic_client.py`(Agent) |
| **新增模型文件** | 3 | `semantic.py`, `lineage.py`, `quality.py` |
| **新增API文件** | 3 | `semantic.py`, `lineage.py`, `quality.py` |
| **新增配置/脚本** | 3 | `semantic_catalog.py`, `seed_semantic_layer.py`, `refresh_lineage.py` |

### 10.2 新增MongoDB集合（7个）

| 集合名 | 用途 | 预估规模 |
|--------|------|----------|
| `_semantic_definitions` | 语义定义 | ~1000条 |
| `_physical_mappings` | 物理映射 | ~2000条 |
| `_lineage_nodes` | 血缘节点 | ~10000条 |
| `_lineage_edges` | 血缘边 | ~50000条 |
| `_data_quality_scores` | 质量评分 | ~50000条 |
| `_semantic_terms` | 术语表 | ~200条 |
| `_association_chains` | 关联链 | ~50条 |

### 10.3 前端改造范围

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

## 十一、实施路线图

### Phase 1: 语义层基础 + 血缘骨架（Week 1-2）

**目标**: 搭建语义层和血缘追踪的基础设施

| 任务 | 工时 | 负责人 | 交付物 |
|------|------|--------|--------|
| 设计语义层数据模型 | 2天 | 架构师 | `models/semantic.py` |
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

## 十二、风险与对策

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

### B. 参考文档

- `stock-research-end/docs/data_lineage_architecture_design.md` — 血缘架构设计V1
- `data-semantic-layer-design` Skill — 语义层设计工作流
- `session-2026-06-02-data-lineage-architecture-v2.md` — 血缘架构V2
- `session-2026-06-03-semantic-lineage-fullstack-embedding.md` — 全链路嵌入设计V4

---

**文档结束**
