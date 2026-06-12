# ZY 数据域 Mock 数据查询解决方案 - 快速指南

## 🎯 问题

智能对话 Agent 查询 ZY 数据域时返回"无数据",但前端页面可以正常显示。

## 🔍 原因

- **前端 Mock 数据**: 存储在浏览器 localStorage (约 82 张表,200+ 条真实数据)
- **智能对话查询**: 访问后端 MongoDB 数据库 (空)
- **数据隔离**: 前端和后端数据源不同步

## ✅ 解决方案

在后端 `portfilio-end` 项目中添加 ZY 数据域查询 API,使智能对话可以查询 MongoDB 中的数据。

## 📦 已创建的文件

### 1. 后端 API 实现
- **文件**: `scripts/zy_data_api_implementation.py`
- **功能**: 完整的 FastAPI 路由实现 (CRUD + 分页 + 过滤)
- **接口**: `/api/v1/zy-data/` 系列

### 2. 数据导入脚本
- **文件**: `scripts/import_zy_data_domain_mock.py`
- **功能**: 将 Mock 数据从 JSON 导入 MongoDB

### 3. 部署脚本
- **文件**: `scripts/deploy_zy_data_api.py`
- **功能**: 自动部署 API 到后端项目

### 4. 测试脚本
- **文件**: `scripts/test_zy_data_api.py`
- **功能**: 验证 API 功能 (8 个测试用例)

### 5. 文档
- **文件**: `docs/ZY_DATA_API_INTEGRATION_GUIDE.md`
- **内容**: 完整集成指南和 API 文档

- **文件**: `docs/ZY_DATA_DOMAIN_MOCK_IMPORT_GUIDE.md`
- **内容**: Mock 数据导入指南

## 🚀 快速开始 (3 步完成)

### 步骤 1: 部署 API 到后端

```bash
cd d:\portfilio
python scripts/deploy_zy_data_api.py
```

这会自动:
- ✅ 检查后端项目
- ✅ 复制 API 文件
- ✅ 注册路由
- ✅ 验证部署

### 步骤 2: 导入 Mock 数据

**方法 A: 从浏览器导出 (推荐)**

```javascript
// 1. 打开前端应用,按 F12
// 2. 在 Console 中运行:
console.log(localStorage.getItem('zy_data_domain_mock_v3'));
// 3. 复制输出的 JSON
// 4. 保存到 scripts/zy_data_domain_seeds.json
```

```bash
# 5. 运行导入
python scripts/import_zy_data_domain_mock.py
```

**方法 B: 使用已有的种子数据**

如果 `mongo-seed/` 目录已有数据,直接运行现有的种子脚本。

### 步骤 3: 启动并测试

```bash
# 启动后端
cd d:\portfilio-end
uvicorn app.main:app --reload --port 8000

# 测试 API
cd d:\portfilio
python scripts/test_zy_data_api.py
```

## 📋 API 接口一览

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/zy-data/collections` | 列出所有集合 |
| GET | `/api/v1/zy-data/{collection}` | 查询数据(分页+过滤) |
| GET | `/api/v1/zy-data/{collection}/count` | 统计记录数 |
| POST | `/api/v1/zy-data/{collection}` | 新增记录 |
| PUT | `/api/v1/zy-data/{collection}/{id}` | 更新记录 |
| DELETE | `/api/v1/zy-data/{collection}/{id}` | 删除记录 |
| GET | `/api/v1/zy-data/health` | 健康检查 |

## 🔧 使用示例

### 查询资产信息

```bash
# 基本查询
curl "http://localhost:8000/api/v1/zy-data/dwd_ast_info?page=1&pageSize=10"

# 带过滤
curl "http://localhost:8000/api/v1/zy-data/dwd_ast_info?filters_json=%7B%22AST_TYPE%22%3A%22BOND%22%7D"
```

### 查询产品净值

```bash
curl "http://localhost:8000/api/v1/zy-data/dwd_ptl_info?page=1&pageSize=5"
```

### Python 调用

```python
import requests
import json

# 查询债券资产
response = requests.get(
    "http://localhost:8000/api/v1/zy-data/dwd_ast_info",
    params={
        "page": 1,
        "pageSize": 20,
        "filters_json": json.dumps({"AST_TYPE": "BOND"})
    }
)

data = response.json()
print(f"总数: {data['total']}")
for asset in data['records']:
    print(f"{asset['AST_CD']}: {asset['AST_NM']}")
```

## 📊 数据表清单

主要包含以下域 (共 82 张表):

| 域 | 表数量 | 主要表 |
|---|--------|--------|
| 资产域 | 14 | dwd_ast_info, dwd_ast_info_ch, dwd_ast_yield_info |
| 主体域 | 2 | dwd_isr_institution, dwd_isr_institution_finance |
| 产品域 | 12 | dwd_ptl_info, dwd_ptl_ast_hld, dwd_ptl_fee |
| 估值域 | 10 | dwd_val_valtable, dwd_val_detail, dwd_val_rpt_bs |
| 交易域 | 7 | dwd_trn_trade_ast, dwd_trn_order |
| 客户域 | 9 | dwd_cust_info, dwd_cust_make_pstn_info |
| 销售域 | 1 | dwd_seller_info |
| 风险域 | 7 | dwd_rsk_limit_check, dwd_rsk_credit |
| 行情域 | 18 | dwd_mkt_bond, dwd_mkt_stock, dwd_mkt_index |
| 交易对手 | 1 | dwd_isr_trd_cntp |
| 其他 | 1 | dwd_cash_acc |

## ✅ 验证清单

- [ ] 后端 API 已部署 (`scripts/deploy_zy_data_api.py`)
- [ ] MongoDB 数据已导入 (`scripts/import_zy_data_domain_mock.py`)
- [ ] 后端服务已启动 (端口 8000)
- [ ] API 测试通过 (`scripts/test_zy_data_api.py`)
- [ ] 智能对话可以查询数据
- [ ] 前端页面正常工作

## 🐛 故障排查

### 问题 1: 后端项目不存在

```
❌ 后端项目不存在: d:\portfilio-end
```

**解决**:
- 确认后端项目实际路径
- 修改 `deploy_zy_data_api.py` 中的 `BACKEND_DIR` 变量
- 或手动复制 `zy_data_api_implementation.py` 到后端

### 问题 2: MongoDB 连接失败

```
pymongo.errors.ServerSelectionTimeoutError
```

**解决**:
```bash
# 检查 MongoDB 是否运行
mongosh --eval "db.runCommand('ping')"

# 启动 MongoDB (Windows)
net start MongoDB
```

### 问题 3: 集合为空

```
集合 'dwd_ast_info' 不存在
```

**解决**:
```bash
# 导入数据
python scripts/import_zy_data_domain_mock.py

# 验证
mongosh portfilio --eval "db.getCollectionNames()"
```

### 问题 4: CORS 错误

前端跨域请求失败,在 `main.py` 中添加:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## 📚 详细文档

- **API 集成指南**: [docs/ZY_DATA_API_INTEGRATION_GUIDE.md](docs/ZY_DATA_API_INTEGRATION_GUIDE.md)
- **Mock 导入指南**: [docs/ZY_DATA_DOMAIN_MOCK_IMPORT_GUIDE.md](docs/ZY_DATA_DOMAIN_MOCK_IMPORT_GUIDE.md)
- **API 实现代码**: [scripts/zy_data_api_implementation.py](scripts/zy_data_api_implementation.py)

## 🎯 预期效果

完成后:
1. ✅ 智能对话 Agent 可以查询 82 张表数据
2. ✅ 前端 ZY 数据域页面正常工作
3. ✅ 支持完整的 CRUD 操作
4. ✅ 支持分页、过滤、统计
5. ✅ 与前端 API 契约完全兼容

## 📞 需要帮助?

查看详细文档或联系开发团队。
