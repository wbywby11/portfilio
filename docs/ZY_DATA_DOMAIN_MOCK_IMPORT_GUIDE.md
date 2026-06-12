# ZY 数据域 Mock 数据入库指南

## 问题分析

### 现状
1. **Mock 数据存储位置**: 前端 `localStorage` (浏览器本地存储)
   - 文件: `src/api/zyDataDomain.mock.js`
   - 存储键: `zy_data_domain_mock_v3`
   - 包含约 82 张表的真实种子数据 (REALISTIC_SEEDS)

2. **智能对话查询路径**: Agent → 后端 API `/api/v1/zy-data/{collection}` → MongoDB
   - 如果后端未实现此路由或 MongoDB 无数据 → 返回"无数据"

3. **数据隔离问题**: 
   - 前端 mock 数据在 localStorage,后端无法访问
   - 智能对话 Agent 只能查询后端 MongoDB
   - 导致"智能对话说无数据"

## 解决方案

### 方案 A: 将 Mock 数据导入 MongoDB (推荐)

#### 步骤 1: 导出 Mock 数据为 JSON

由于 `zyDataDomain.mock.js` 包含大量真实数据,需要提取 `REALISTIC_SEEDS` 对象:

**方法 1: 使用浏览器控制台导出**
```javascript
// 1. 打开浏览器开发者工具 (F12)
// 2. 在 Console 中运行:
const data = localStorage.getItem('zy_data_domain_mock_v3');
const parsed = JSON.parse(data);
console.log(JSON.stringify(parsed, null, 2));
// 3. 复制输出内容,保存为 scripts/zy_data_domain_seeds.json
```

**方法 2: 手动从源码提取**
1. 打开 `src/api/zyDataDomain.mock.js`
2. 找到 `const REALISTIC_SEEDS = {` (约第 73 行)
3. 复制整个对象(到约第 900 行)
4. 使用在线工具将 JS 对象转为 JSON
5. 保存为 `scripts/zy_data_domain_seeds.json`

#### 步骤 2: 导入到 MongoDB

```bash
# 确保 MongoDB 已启动
cd d:\portfilio
python scripts/import_zy_data_domain_mock.py
```

脚本会:
- 连接 MongoDB (`mongodb://localhost:27017`)
- 读取 `scripts/zy_data_domain_seeds.json`
- 将所有集合数据导入 `portfilio` 数据库
- 使用 upsert 避免重复导入
- 显示导入统计和验证结果

#### 步骤 3: 验证数据

```bash
# 使用 MongoDB Shell 验证
mongosh portfilio

# 查看导入的集合
show collections

# 查看某个集合的数据量
db.dwd_ast_info.countDocuments({})
db.dwd_ptl_info.countDocuments({})

# 查看样例数据
db.dwd_ast_info.findOne()
```

### 方案 B: 封装后端查询工具(如果后端未实现 API)

如果后端 `/api/v1/zy-data/` 路由未实现,需要创建:

#### 后端实现示例 (FastAPI)

创建文件: `portfilio-end/app/api/v1/zy_data.py`

```python
from fastapi import APIRouter, Query, HTTPException
from pymongo import MongoClient
from typing import Optional, Dict, Any
import json

router = APIRouter(prefix="/api/v1/zy-data", tags=["ZY数据域"])

# MongoDB 连接
client = MongoClient("mongodb://localhost:27017")
db = client["portfilio"]

@router.get("/collections")
def list_collections():
    """列出所有可用的 collection"""
    return {"collections": db.list_collection_names()}

@router.get("/{collection}")
def query_collection(
    collection: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    filters_json: Optional[str] = None
):
    """查询集合数据(支持分页和过滤)"""
    if collection not in db.list_collection_names():
        raise HTTPException(status_code=404, detail=f"Collection '{collection}' not found")
    
    # 解析过滤器
    filters = {}
    if filters_json:
        try:
            filters = json.loads(filters_json)
        except:
            raise HTTPException(status_code=400, detail="Invalid filters_json")
    
    # 查询数据
    query = {**filters}
    total = db[collection].count_documents(query)
    cursor = db[collection].find(query).skip((page - 1) * pageSize).limit(pageSize)
    records = list(cursor)
    
    # 转换 _id 为字符串
    for rec in records:
        rec['_id'] = str(rec['_id'])
    
    return {
        "records": records,
        "total": total,
        "page": page,
        "pageSize": pageSize
    }

@router.get("/{collection}/count")
def count_collection(collection: str):
    """统计集合记录数"""
    if collection not in db.list_collection_names():
        raise HTTPException(status_code=404, detail=f"Collection '{collection}' not found")
    
    return {"count": db[collection].count_documents({})}
```

注册路由: `portfilio-end/app/main.py`

```python
from app.api.v1 import zy_data
app.include_router(zy_data.router)
```

## 快速操作清单

### 立即可执行的步骤:

```bash
# 1. 确认 MongoDB 是否运行
mongosh --eval "db.runCommand('ping')"

# 2. 如果未运行,启动 MongoDB
# Windows:
net start MongoDB

# 3. 从浏览器导出 localStorage 数据
# 打开前端应用 → F12 → Console → 运行导出命令

# 4. 保存 JSON 到 scripts/zy_data_domain_seeds.json

# 5. 运行导入脚本
python scripts/import_zy_data_domain_mock.py

# 6. 验证导入
mongosh portfilio --eval "db.getCollectionNames()"
```

## 智能对话工具封装建议

如果 Agent 需要专用查询工具,可以封装:

### Agent Tool 示例

```python
from typing import Dict, Any

def query_zy_data_domain(
    collection: str,
    filters: Dict[str, Any] = None,
    page: int = 1,
    page_size: int = 20
) -> Dict[str, Any]:
    """
    查询 ZY 数据域数据
    
    Args:
        collection: 集合名称 (如 dwd_ast_info, dwd_ptl_info)
        filters: 过滤条件 (如 {"AST_TYPE": "BOND"})
        page: 页码
        page_size: 每页数量
    
    Returns:
        查询结果 {records, total, page, pageSize}
    """
    # 实现同方案 B 的 API 逻辑
    pass
```

### Agent 调用示例

```python
# 查询债券信息
result = query_zy_data_domain(
    collection="dwd_ast_info",
    filters={"AST_TYPE": "BOND"},
    page=1,
    page_size=10
)

# 查询产品净值
result = query_zy_data_domain(
    collection="dwd_ptl_info",
    filters={"PORT_ID": "PORT001"}
)
```

## 数据表清单

Mock 数据包含以下主要集合(约 82 张):

### 资产域 (14 张)
- dwd_ast_info - 资产基本信息
- dwd_ast_info_ch - 中债估值
- dwd_ast_info_zg - 中证估值
- dwd_ast_yield_info - 收益率信息
- dwd_ast_cf_plan - 现金流计划
- dwd_ast_pledge - 质押信息
- dwd_ast_party - 参与方信息
- dwd_ast_exe_plan - 行权计划
- dwd_ast_fund_manager - 基金经理
- dwd_ast_bottom_raito - 底层资产比例
- dwd_ast_fiveclass - 五级分类
- dwd_ast_calc_rule - 计算规则

### 主体域 (2 张)
- dwd_isr_institution - 机构信息
- dwd_isr_institution_finance - 机构财务

### 产品域 (12 张)
- dwd_ptl_info - 产品基本信息
- tag_ptl_info - 产品标签
- dwd_ptl_acc - 产品账户
- dwd_ptl_cedetail - 申赎明细
- dwd_ptl_fee - 费率信息
- dwd_ptl_managers - 基金经理
- dwd_ptl_open_plan - 开放计划
- dwd_ptl_asset_config_info - 资产配置
- dwd_ptl_acct_bal - 账户余额
- dwd_ptl_ast_hld - 资产持仓
- dwd_ptl_holder_summary - 持有人汇总
- dwd_cash_acc - 现金账户

### 估值域 (10 张)
- dwd_val_valtable - 估值表
- dwd_val_voucher - 凭证
- dwd_val_summary - 估值汇总
- dwd_val_detail - 估值明细
- dwd_val_notice - 估值公告
- dwd_val_bal - 余额表
- dwd_val_acc - 会计科目
- dwd_val_rpt_bs - 资产负债表
- dwd_val_rpt_is - 利润表
- dwd_val_rpt_cf - 现金流量表

### 交易域 (7 张)
- dwd_trn_trade_ast - 资产交易
- dwd_trn_trade_ptl - 产品交易
- dwd_trn_trade_val - 交易估值
- dwd_trn_trade_zg - 交易结算
- dwd_trn_trade_jy - 交易费用
- dwd_trn_order - 委托订单

### 客户域 (9 张)
- dwd_cust_info - 客户信息
- dwd_cust_make_pstn_info - 客户持仓
- dwd_cust_trans_acct_info - 交易账户
- dwd_cust_trans_apply_info_s5 - S5渠道申请
- dwd_cust_trans_apply_info_ta - TA渠道申请
- dwd_cust_trans_apply_info_yh - 银行渠道申请
- dwd_cust_trans_cfm_info - 确认信息
- dwd_cust_trans_divd_info - 分红信息
- dwd_cust_trans_srl_info - 流水信息

### 销售域 (1 张)
- dwd_seller_info - 销售信息

### 风险域 (7 张)
- dwd_rsk_limit_check - 风控检查
- dwd_rsk_sentiment - 舆情信息
- dwd_rsk_credit - 信用信息
- dwd_rsk_credit_position - 信用头寸
- dwd_crdt_rating_change - 评级变动
- dwd_crdt_agme_info - 协议信息

### 交易对手 (1 张)
- dwd_isr_trd_cntp - 交易对手

## 注意事项

1. **数据一致性**: Mock 数据中 `BIZ_DT=20250324`,导入后保持一致性
2. **字段映射**: 确保 MongoDB collection 名称与前端调用一致
3. **索引优化**: 为常用查询字段创建索引 (如 AST_CD, PORT_ID, ISR_ID)
4. **权限控制**: 后端 API 应添加认证和授权
5. **数据更新**: 定期同步最新 Mock 数据到 MongoDB

## 后续优化

1. **数据种子脚本**: 将导入逻辑整合到 `mongo-seed/` 目录
2. **API 文档**: 使用 Swagger/OpenAPI 自动生成文档
3. **缓存策略**: 对热点数据添加 Redis 缓存
4. **数据校验**: 添加 Pydantic 模型校验
5. **监控告警**: 添加查询性能监控

## 总结

**核心问题**: Mock 数据在前端 localStorage,后端 MongoDB 无数据

**解决方案**: 
1. 导出 localStorage 数据为 JSON
2. 使用 Python 脚本导入 MongoDB
3. (可选) 实现后端查询 API
4. (可选) 封装 Agent 查询工具

**预期效果**: 智能对话 Agent 可以通过后端 API 查询到 ZY 数据域的 82 张表数据
