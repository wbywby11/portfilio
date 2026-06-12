# ==========================================
# ZY 数据域关联 Mock 数据导入说明
# ==========================================

## 已生成的文件

### 1. 数据生成脚本
- `scripts/generate_and_import_associated_mock.py` - 完整版（496行）
  包含所有10个集合的完整关联数据

### 2. 设计文档
- `scripts/zy_data_associated_mock_design.md` - 关联关系设计文档

### 3. 辅助脚本
- `scripts/generate_associated_mock_simple.py` - 简化版生成脚本
- `scripts/generate_associated_mock_data.py` - 复杂版生成脚本
- `scripts/verify_mongo_data.py` - MongoDB 数据验证脚本

---

## 导入步骤

### 方法 1: 直接运行 Python 脚本（推荐）

```bash
cd d:\portfilio
python scripts/generate_and_import_associated_mock.py
```

### 方法 2: 在 Python 交互环境中执行

```bash
cd d:\portfilio
python
```

然后在 Python 中执行：

```python
exec(open('scripts/generate_and_import_associated_mock.py').read())
generate_and_import()
```

### 方法 3: 使用 mongosh 导入 JSON 文件

先生成 JSON 文件：

```python
# 在 generate_and_import_associated_mock.py 的 generate_and_import() 函数中
# 添加保存 JSON 的代码

import json
with open('zy_data_mock_associated.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
```

然后使用 mongosh：

```bash
mongosh asset_allocation --eval "load('import_script.js')"
```

---

## 数据结构说明

### 生成的集合清单

| 序号 | 集合名称 | 记录数 | 关联关系 |
|------|---------|--------|---------|
| 1 | dwd_isr_institution | 8 | 机构基础表 |
| 2 | dwd_ast_info | 12 | ISR_ID → dwd_isr_institution |
| 3 | dwd_ptl_info | 5 | MGR_INST → dwd_isr_institution |
| 4 | dwd_ptl_ast_hld | 22 | PORT_ID → dwd_ptl_info, AST_CD → dwd_ast_info |
| 5 | dwd_cust_info | 7 | 客户基础表 |
| 6 | dwd_cust_ptl_hld | 12 | CUSTOMER_ID → dwd_cust_info, PORT_ID → dwd_ptl_info |
| 7 | dwd_ast_info_ch | 7 | AST_CD → dwd_ast_info |
| 8 | dwd_rsk_limit_check | 6 | PORT_ID → dwd_ptl_info |
| 9 | dwd_crdt_rating_change | 1 | ISR_ID → dwd_isr_institution |
| 10 | dwd_ast_pledge | 5 | AST_CD → dwd_ast_info |

**总计**: 10个集合, 85条记录

---

## 关联关系类型

### 1. 直接关联（外键引用）
```
dwd_ast_info.ISR_ID → dwd_isr_institution.ISR_ID
dwd_ptl_ast_hld.AST_CD → dwd_ast_info.AST_CD
dwd_cust_ptl_hld.PORT_ID → dwd_ptl_info.PORT_ID
```

### 2. 间接关联（穿透链路）
```
客户 → 产品 → 资产 → 发行人
dwd_cust_info → dwd_cust_ptl_hld → dwd_ptl_ast_hld → dwd_ast_info → dwd_isr_institution
```

### 3. 高度关联（多表共享）
```
资产实体被以下表关联：
- dwd_ast_info (基础信息)
- dwd_ast_info_ch (中债估值)
- dwd_ast_pledge (质押状态)
```

### 4. 重度关联（一对多）
```
一个产品持有多个资产：
PORT001 → 7只资产
PORT002 → 5只资产
PORT003 → 5只资产
```

### 5. 轻度关联（可选）
```
只有部分资产有质押信息：
5/12 只资产有质押记录
```

---

## AI 分析场景

### 场景 1: 客户风险敞口穿透
**问题**: 张明远对万科的风险敞口有多大？

**分析链路**:
```
CUS0000001 (张明远)
  → PORT001 (投资500万)
    → 112311.SZ (持仓5%)
      → ISR000005 (万科)

风险敞口 = 500万 × 5% = 25万
```

### 场景 2: 集中度风险预警
**问题**: 哪些产品存在单一资产集中度过高？

**分析**:
```
PORT001 持有 510300.SH (20%) → 超过10%限制 → BREACH
PORT002 持有 019601.IB (25%) → 超过10%限制 → BREACH
```

### 场景 3: 评级下调影响
**问题**: 万科评级下调会影响哪些客户？

**分析链路**:
```
ISR000005 (万科) AA → AA-
  → 112311.SZ (万科MTN)
    → PORT001, PORT003 (持有该债券)
      → CUS0000001, CUS0000003, CUS0000005, CUS0000007
```

### 场景 4: 质押风险分析
**问题**: 哪些资产的质押率异常？

**分析**:
```
019601.IB (国债) 质押率 95% → 正常
112311.SZ (万科债) 质押率 0% → 不可质押（评级低）
```

---

## 验证数据

导入完成后，运行验证脚本：

```bash
python scripts/verify_mongo_data.py
```

或手动验证：

```python
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017')
db = client['asset_allocation']

# 检查集合数量
collections = [n for n in db.list_collection_names() if n.startswith('dwd_')]
print(f"集合数量: {len(collections)}")

# 检查记录总数
total = sum(db[n].count_documents({}) for n in collections)
print(f"总记录数: {total}")

# 验证关联完整性
holdings = list(db.dwd_ptl_ast_hld.find())
assets = set(r['AST_CD'] for r in db.dwd_ast_info.find())
invalid = [h for h in holdings if h['AST_CD'] not in assets]
print(f"无效持仓引用: {len(invalid)}")

client.close()
```

---

## 故障排除

### 问题 1: MongoDB 连接失败
**解决方案**:
```bash
# 检查 MongoDB 服务状态
Get-Service -Name MongoDB

# 如果未启动，启动服务
Start-Service MongoDB
```

### 问题 2: 权限不足
**解决方案**:
```bash
# 使用管理员权限运行 PowerShell
# 或以管理员身份运行 Python
```

### 问题 3: 端口冲突
**解决方案**:
```bash
# 检查 27017 端口是否被占用
netstat -ano | findstr 27017

# 修改连接地址
MONGO_URI = "mongodb://localhost:27018"  # 使用其他端口
```

---

## 下一步

数据导入成功后，您可以：

1. **在智能对话中测试 data_query 工具**
   - 查询单个表：`查询 dwd_ast_info 的所有资产`
   - 关联查询：`查询 PORT001 持有哪些资产`
   - 穿透查询：`查询张明远间接持有万科的金额`

2. **验证 AI 分析能力**
   - 风险敞口分析
   - 集中度预警
   - 评级影响分析
   - 质押风险评估

3. **扩展数据**
   - 添加历史估值数据（过去30天）
   - 添加现金流计划数据
   - 添加交易记录数据

---

**生成时间**: 2026-05-26  
**设计目标**: 支持 AI 发现多层次业务关联关系
