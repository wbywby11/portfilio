# ZY 数据域关联 Mock 数据设计文档

> 生成时间: 2026-05-26  
> 目标: 生成具有复杂关联关系的 Mock 数据，支持 AI 发现多层次业务关联

---

## 一、设计理念

### 1.1 关联类型定义

| 关联类型 | 定义 | 示例 | AI分析价值 |
|---------|------|------|-----------|
| **直接关联** | 外键直接引用主键 | `dwd_ast_info.ISR_ID` → `dwd_isr_institution.ISR_ID` | 可直接 JOIN 查询 |
| **间接关联** | 通过中间表关联 | 客户→产品→资产→发行人 | 发现深层业务关系 |
| **高度关联** | 多表共享同一主键 | 资产的估值/收益率/现金流等 | 构建360°视图 |
| **重度关联** | 一对多/多对多关系 | 一个产品持有多个资产 | 发现集中度风险 |
| **轻度关联** | 可选关联 | 部分资产有质押信息 | 发现特殊状态 |

### 1.2 核心关联链路

#### 链路 1：投资穿透（客户→产品→资产→发行人）
```
dwd_cust_info (客户信息)
    ↓ CUSTOMER_ID
dwd_cust_ptl_hld (客户持仓)
    ↓ PORT_ID
dwd_ptl_info (产品信息)
    ↓ PORT_ID
dwd_ptl_ast_hld (产品持仓)
    ↓ AST_CD
dwd_ast_info (资产信息)
    ↓ ISR_ID
dwd_isr_institution (发行人信息)
```

**AI 可以分析**：
- 某客户间接持有哪些资产？
- 某客户对某发行人的风险敞口？
- 某产品的客户结构？
- 风险传导路径？

#### 链路 2：资产全景视图（高度关联）
```
dwd_ast_info (基础信息)
    ├→ dwd_ast_info_ch (中债估值)
    ├→ dwd_ast_info_zg (中证估值)
    ├→ dwd_ast_yield_info (收益率)
    ├→ dwd_ast_cf_plan (现金流计划)
    ├→ dwd_ast_pledge (质押状态)
    ├→ dwd_ast_fiveclass (五级分类)
    └→ dwd_ast_exe_plan (行权计划)
```

**AI 可以分析**：
- 资产的估值是否合理？
- 是否存在质押风险？
- 现金流是否健康？
- 信用评级变化？

#### 链路 3：风险传染路径
```
dwd_isr_institution (发行人)
    ↓ 发行
dwd_ast_info (债券)
    ↓ 被持有
dwd_ptl_ast_hld (产品持仓)
    ↓ 属于
dwd_ptl_info (产品)
    ↓ 被投资
dwd_cust_ptl_hld (客户持仓)
    ↓ 影响
dwd_cust_info (客户)
```

**AI 可以分析**：
- 某发行人违约会影响哪些客户？
- 风险传导路径是什么？
- 影响金额有多大？
- 是否需要预警？

---

## 二、数据实体设计

### 2.1 主键池定义

#### 机构/发行人（8个）
```json
{
  "ISR000001": {"name": "中华人民共和国财政部", "type": "SOVEREIGN", "credit": "AAA", "region": "北京"},
  "ISR000002": {"name": "国家开发银行", "type": "POLICY_BANK", "credit": "AAA", "region": "北京"},
  "ISR000003": {"name": "中国工商银行", "type": "COMMERCIAL_BANK", "credit": "AAA", "region": "北京"},
  "ISR000004": {"name": "中国农业发展银行", "type": "POLICY_BANK", "credit": "AAA", "region": "北京"},
  "ISR000005": {"name": "万科企业", "type": "CORPORATE", "credit": "AA-", "region": "广东"},
  "ISR000006": {"name": "华能新能源", "type": "CORPORATE", "credit": "AAA", "region": "北京"},
  "ISR000007": {"name": "招商银行", "type": "COMMERCIAL_BANK", "credit": "AAA", "region": "广东"},
  "ISR000008": {"name": "中国平安", "type": "CORPORATE", "credit": "AAA", "region": "广东"}
}
```

#### 资产（12个）
```json
{
  "019601.IB": {"name": "25国债03", "type": "BOND", "issuer": "ISR000001"},
  "019735.IB": {"name": "25特别国债03", "type": "BOND", "issuer": "ISR000001"},
  "230210.IB": {"name": "23国开10", "type": "BOND", "issuer": "ISR000002"},
  "220215.IB": {"name": "22国开15", "type": "BOND", "issuer": "ISR000002"},
  "2480006.IB": {"name": "24工商银行MTN001", "type": "BOND", "issuer": "ISR000003"},
  "112311.SZ": {"name": "24万科MTN003", "type": "BOND", "issuer": "ISR000005"},
  "600036.SH": {"name": "招商银行", "type": "STOCK", "issuer": "ISR000007"},
  "601318.SH": {"name": "中国平安", "type": "STOCK", "issuer": "ISR000008"},
  "510300.SH": {"name": "沪深300ETF", "type": "FUND", "issuer": "ISR000007"},
  "511260.SH": {"name": "十年国债ETF", "type": "FUND", "issuer": "ISR000003"},
  "127080.SZ": {"name": "2024华能新能ABS001", "type": "ABS", "issuer": "ISR000006"},
  "180401.IB": {"name": "24农发绿色债01", "type": "BOND", "issuer": "ISR000004"}
}
```

#### 产品/组合（5个）
```json
{
  "PORT001": {"name": "稳健配置一号", "type": "MIXED", "risk": "R3", "aum": 1250000000},
  "PORT002": {"name": "纯债精选二号", "type": "BOND", "risk": "R2", "aum": 2800000000},
  "PORT003": {"name": "混合增强三号", "type": "MIXED", "risk": "R3", "aum": 870000000},
  "PORT004": {"name": "短融货币四号", "type": "MMF", "risk": "R1", "aum": 5000000000},
  "PORT005": {"name": "指数增强五号", "type": "INDEX", "risk": "R4", "aum": 650000000}
}
```

#### 客户（7个）
```json
{
  "CUS0000001": {"name": "张明远", "type": "IND", "risk": "C3"},
  "CUS0000002": {"name": "李秀芬", "type": "IND", "risk": "C2"},
  "CUS0000003": {"name": "王建国", "type": "IND", "risk": "C4"},
  "CUS0000004": {"name": "陈雅琴", "type": "IND", "risk": "C1"},
  "CUS0000005": {"name": "深圳市前海资产管理有限公司", "type": "INST", "risk": "C4"},
  "CUS0000006": {"name": "上海浦东新区社会保险基金管理中心", "type": "INST", "risk": "C2"},
  "CUS0000007": {"name": "广东省教育基金会", "type": "INST", "risk": "C2"}
}
```

### 2.2 关联规则

#### 产品持仓规则
```json
{
  "PORT001": {
    "019601.IB": 0.15,
    "230210.IB": 0.12,
    "2480006.IB": 0.08,
    "600036.SH": 0.10,
    "510300.SH": 0.20,
    "511260.SH": 0.18,
    "112311.SZ": 0.05
  },
  "PORT002": {
    "019601.IB": 0.25,
    "019735.IB": 0.20,
    "230210.IB": 0.18,
    "2480006.IB": 0.15,
    "180401.IB": 0.12
  },
  "PORT003": {
    "600036.SH": 0.15,
    "601318.SH": 0.12,
    "510300.SH": 0.18,
    "019601.IB": 0.10,
    "230210.IB": 0.08
  }
}
```

#### 客户投资规则
```json
{
  "CUS0000001": ["PORT001", "PORT002"],
  "CUS0000002": ["PORT002", "PORT004"],
  "CUS0000003": ["PORT001", "PORT003", "PORT005"],
  "CUS0000005": ["PORT001", "PORT003"],
  "CUS0000006": ["PORT002", "PORT004"],
  "CUS0000007": ["PORT001"]
}
```

#### 资产质押规则
```json
{
  "019601.IB": {"ratio": 0.95, "inst": "中国人民银行", "note": "央行公开市场操作"},
  "230210.IB": {"ratio": 0.90, "inst": "中央国债登记结算公司", "note": "银行间质押式回购"},
  "2480006.IB": {"ratio": 0.85, "inst": "上海清算所", "note": "上清所质押式回购"},
  "180401.IB": {"ratio": 0.88, "inst": "中央国债登记结算公司", "note": "绿色债券质押"},
  "112311.SZ": {"ratio": 0, "note": "不可质押，评级低于AA"}
}
```

---

## 三、AI 分析场景示例

### 场景 1：客户风险敞口分析

**问题**：张明远持有产品的底层资产中，对万科的风险敞口有多大？

**分析链路**：
```
CUS0000001 (张明远)
  → PORT001 (投资500万)
    → 112311.SZ (持仓5%)
      → ISR000005 (万科)
  → PORT002 (投资300万)
    → 不含万科资产

风险敞口 = 500万 × 5% = 25万
```

### 场景 2：集中度风险预警

**问题**：哪些产品存在单一资产集中度过高风险？

**分析**：
```
PORT002 持有 019601.IB (25%) → 超过10%限制 → WARNING
PORT002 持有 019735.IB (20%) → 超过10%限制 → WARNING
```

### 场景 3：评级下调影响分析

**问题**：万科评级下调会影响哪些客户？

**分析链路**：
```
ISR000005 (万科) AA → AA- 评级下调
  → 112311.SZ (万科MTN)
    → PORT001 (持有5%)
      → CUS0000001 (张明远)
      → CUS0000003 (王建国)
      → CUS0000005 (前海资产)
      → CUS0000007 (教育基金会)
    → PORT003 (持有?)
      → ...

影响客户数: 4个
影响金额: 需要汇总计算
```

### 场景 4：估值对比分析

**问题**：中债估值和中证估值是否存在显著差异？

**分析**：
```
019601.IB:
  中债估值: 99.5600
  中证估值: 99.5320
  差异: 0.028 (0.028%) → 正常

112311.SZ:
  中证估值: 95.8800
  中债估值: 无
  原因: 信用债可能无中债估值
```

### 场景 5：流动性分析

**问题**：未来30天有哪些现金流到期？

**分析**：
```
查询 dwd_ast_cf_plan WHERE CF_DT BETWEEN '20250324' AND '20250423'

结果:
- 019601.IB: 20250715 付息 4875万
- 230210.IB: 20250615 付息 16.68亿
- 2480006.IB: 20250915 付息+本金 1.55亿
```

---

## 四、数据生成建议

### 4.1 数据量建议

| 集合 | 记录数 | 说明 |
|------|--------|------|
| dwd_isr_institution | 8-10 | 机构/发行人 |
| dwd_ast_info | 12 | 资产基础信息 |
| dwd_ptl_info | 5 | 产品/组合 |
| dwd_cust_info | 7 | 客户 |
| dwd_ptl_ast_hld | 20-30 | 产品持仓 |
| dwd_cust_ptl_hld | 10-15 | 客户持仓 |
| dwd_ast_info_ch | 8-10 | 中债估值 |
| dwd_ast_info_zg | 5-8 | 中证估值 |
| dwd_ast_yield_info | 10-12 | 收益率 |
| dwd_ast_cf_plan | 20-30 | 现金流计划 |
| dwd_ast_pledge | 6-8 | 质押状态 |
| dwd_rsk_limit_check | 10-15 | 风控限额 |
| dwd_crdt_rating_change | 1-2 | 评级变动 |

### 4.2 关联完整性检查

生成数据后应验证：
- ✓ 所有 `ISR_ID` 都能在 `dwd_isr_institution` 中找到
- ✓ 所有 `AST_CD` 都能在 `dwd_ast_info` 中找到
- ✓ 所有 `PORT_ID` 都能在 `dwd_ptl_info` 中找到
- ✓ 所有 `CUSTOMER_ID` 都能在 `dwd_cust_info` 中找到
- ✓ 产品持仓比例总和 ≈ 100%
- ✓ 客户持仓金额与产品 AUM 匹配

### 4.3 数据真实性建议

1. **时间序列**：提供历史估值数据（过去30天）
2. **价格联动**：收益率变动与价格变动符合债券定价原理
3. **业务逻辑**：
   - 国债收益率 < 政金债 < 商业银行债 < 企业债
   - 久期越长，凸性越大
   - 评级越低，收益率越高
4. **异常数据**：故意设置一些异常，测试 AI 发现能力：
   - 超标的风控限额
   - 评级下调
   - 估值差异过大
   - 质押率异常

---

## 五、生成脚本使用

### 5.1 执行生成

```bash
cd d:\portfilio
python scripts/generate_associated_mock_simple.py
```

输出文件：`scripts/zy_data_mock_associated.json`

### 5.2 导入 MongoDB

```bash
python scripts/import_associated_mock_to_mongo.py
```

或手动导入：

```python
import json
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017')
db = client['asset_allocation']

with open('scripts/zy_data_mock_associated.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for collection_name, records in data.items():
    if records:
        db[collection_name].insert_many(records)
        print(f"✓ {collection_name}: {len(records)} 条")
```

### 5.3 验证数据

```python
# 验证关联完整性
from pymongo import MongoClient

db = MongoClient('mongodb://localhost:27017')['asset_allocation']

# 检查所有持仓的资产是否存在
holdings = db.dwd_ptl_ast_hld.find()
assets = set(r['AST_CD'] for r in db.dwd_ast_info.find())

for h in holdings:
    if h['AST_CD'] not in assets:
        print(f"✗ 持仓引用了不存在的资产: {h['AST_CD']}")

print("✓ 关联验证完成")
```

---

## 六、预期 AI 分析能力

### 6.1 基础查询
- ✓ 单表查询（SELECT * FROM ...）
- ✓ 条件过滤（WHERE ...）
- ✓ 排序分页（ORDER BY ... LIMIT ...）

### 6.2 关联查询
- ✓ 直接 JOIN（外键关联）
- ✓ 多层 JOIN（间接关联）
- ✓ 聚合统计（GROUP BY, COUNT, SUM）

### 6.3 高级分析
- ✓ 风险敞口计算
- ✓ 集中度分析
- ✓ 风险传染路径
- ✓ 估值合理性评估
- ✓ 流动性预测
- ✓ 异常检测

### 6.4 业务洞察
- ✓ 客户画像（风险偏好、投资偏好）
- ✓ 产品分析（持仓集中度、风险水平）
- ✓ 资产分析（收益风险比、流动性）
- ✓ 市场洞察（评级趋势、估值趋势）

---

**文档结束**

使用此设计文档，可以生成具有丰富关联关系的 Mock 数据，充分发挥 AI 的分析能力。
