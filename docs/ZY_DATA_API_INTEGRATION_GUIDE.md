# ZY 数据域后端 API 集成指南

## 📦 文件清单

已创建的文件:
- ✅ `scripts/zy_data_api_implementation.py` - 完整的 FastAPI 路由实现
- ✅ `scripts/import_zy_data_domain_mock.py` - MongoDB 数据导入脚本
- ✅ `docs/ZY_DATA_DOMAIN_MOCK_IMPORT_GUIDE.md` - 完整操作指南

## 🚀 集成步骤

### 步骤 1: 部署 API 文件到后端项目

```bash
# 假设后端项目在 d:\portfilio-end
cd d:\portfilio-end

# 创建 API 文件
mkdir -p app/api/v1

# 复制 API 实现
copy d:\portfilio\scripts\zy_data_api_implementation.py app\api\v1\zy_data.py
```

### 步骤 2: 注册路由

编辑 `d:\portfilio-end\app\main.py`:

```python
from fastapi import FastAPI
from app.api.v1 import zy_data  # 添加这行

app = FastAPI()

# 注册 ZY 数据域路由 (添加这部分)
app.include_router(zy_data.router)

# ... 其他路由注册
```

### 步骤 3: 导入 Mock 数据到 MongoDB

```bash
cd d:\portfilio

# 方法 1: 从浏览器导出(推荐)
# 1. 打开前端应用 → F12 → Console
# 2. 运行: console.log(localStorage.getItem('zy_data_domain_mock_v3'))
# 3. 复制输出保存到 scripts/zy_data_domain_seeds.json
# 4. 运行导入:
python scripts/import_zy_data_domain_mock.py

# 方法 2: 使用 mongo-seed 脚本(如果已准备)
cd mongo-seed
# 运行现有的种子脚本
```

### 步骤 4: 启动后端服务

```bash
cd d:\portfilio-end

# 启动 FastAPI 服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 步骤 5: 测试 API

```bash
# 1. 健康检查
curl http://localhost:8000/api/v1/zy-data/health

# 2. 查看可用集合
curl http://localhost:8000/api/v1/zy-data/collections

# 3. 查询资产信息
curl "http://localhost:8000/api/v1/zy-data/dwd_ast_info?page=1&pageSize=10"

# 4. 带过滤查询
curl "http://localhost:8000/api/v1/zy-data/dwd_ast_info?filters_json=%7B%22AST_TYPE%22%3A%22BOND%22%7D"

# 5. 统计记录数
curl http://localhost:8000/api/v1/zy-data/dwd_ast_info/count
```

### 步骤 6: 前端验证

打开前端应用,智能对话应该能够查询到 ZY 数据域数据了。

## 📋 API 接口文档

### 1. 列出所有集合

```
GET /api/v1/zy-data/collections
```

响应:
```json
{
  "collections": [
    "dwd_ast_info",
    "dwd_ptl_info",
    "dwd_isr_institution",
    ...
  ]
}
```

### 2. 查询集合数据(分页)

```
GET /api/v1/zy-data/{collection}?page=1&pageSize=20&filters_json={}
```

参数:
- `collection` (路径): 集合名称
- `page` (查询): 页码,默认 1
- `pageSize` (查询): 每页数量,默认 20,最大 100
- `filters_json` (查询): 过滤条件,JSON 字符串

示例:
```
GET /api/v1/zy-data/dwd_ast_info?page=1&pageSize=10&filters_json={"AST_TYPE":"BOND"}
```

响应:
```json
{
  "records": [
    {
      "_id": "...",
      "AST_CD": "019601.IB",
      "AST_NM": "25国债03",
      ...
    }
  ],
  "total": 12,
  "page": 1,
  "pageSize": 10
}
```

### 3. 统计记录数

```
GET /api/v1/zy-data/{collection}/count
```

响应:
```json
{
  "count": 12
}
```

### 4. 新增记录

```
POST /api/v1/zy-data/{collection}
Content-Type: application/json

{
  "AST_CD": "TEST001.IB",
  "AST_NM": "测试债券",
  ...
}
```

### 5. 更新记录

```
PUT /api/v1/zy-data/{collection}/{record_id}
Content-Type: application/json

{
  "AST_NM": "更新后的名称",
  ...
}
```

### 6. 删除记录

```
DELETE /api/v1/zy-data/{collection}/{record_id}
```

### 7. 健康检查

```
GET /api/v1/zy-data/health
```

响应:
```json
{
  "status": "ok",
  "database": "portfilio",
  "collections": 82
}
```

## 🔧 配置说明

### MongoDB 连接

默认配置在 `zy_data_api_implementation.py` 中:

```python
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"
```

**推荐**: 从环境变量读取:

```python
import os

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB_NAME", "portfilio")
```

### 环境变量 (.env)

```env
# MongoDB 配置
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=portfilio

# FastAPI 配置
API_PORT=8000
API_HOST=0.0.0.0
```

## 🧪 自动化测试脚本

创建测试文件 `scripts/test_zy_data_api.py`:

```python
"""
ZY 数据域 API 测试脚本
"""
import requests
import json

BASE_URL = "http://localhost:8000/api/v1/zy-data"

def test_health():
    """测试健康检查"""
    print("\n=== 测试健康检查 ===")
    resp = requests.get(f"{BASE_URL}/health")
    print(f"状态码: {resp.status_code}")
    print(f"响应: {json.dumps(resp.json(), indent=2, ensure_ascii=False)}")
    assert resp.status_code == 200

def test_list_collections():
    """测试列出集合"""
    print("\n=== 测试列出集合 ===")
    resp = requests.get(f"{BASE_URL}/collections")
    print(f"状态码: {resp.status_code}")
    print(f"集合数量: {len(resp.json()['collections'])}")
    print(f"集合列表: {resp.json()['collections'][:5]}...")
    assert resp.status_code == 200

def test_query_assets():
    """测试查询资产"""
    print("\n=== 测试查询资产 ===")
    resp = requests.get(
        f"{BASE_URL}/dwd_ast_info",
        params={"page": 1, "pageSize": 5}
    )
    print(f"状态码: {resp.status_code}")
    print(f"总数: {resp.json()['total']}")
    print(f"返回记录: {len(resp.json()['records'])}")
    if resp.json()['records']:
        print(f"样例: {resp.json()['records'][0]}")
    assert resp.status_code == 200

def test_query_with_filter():
    """测试带过滤查询"""
    print("\n=== 测试带过滤查询 ===")
    filters = {"AST_TYPE": "BOND"}
    resp = requests.get(
        f"{BASE_URL}/dwd_ast_info",
        params={
            "page": 1,
            "pageSize": 10,
            "filters_json": json.dumps(filters)
        }
    )
    print(f"状态码: {resp.status_code}")
    print(f"过滤条件: {filters}")
    print(f"匹配记录: {resp.json()['total']}")
    assert resp.status_code == 200

def test_count():
    """测试统计"""
    print("\n=== 测试统计 ===")
    resp = requests.get(f"{BASE_URL}/dwd_ast_info/count")
    print(f"状态码: {resp.status_code}")
    print(f"记录数: {resp.json()['count']}")
    assert resp.status_code == 200

def test_not_found():
    """测试 404"""
    print("\n=== 测试 404 ===")
    resp = requests.get(f"{BASE_URL}/nonexistent_collection")
    print(f"状态码: {resp.status_code}")
    print(f"错误信息: {resp.json()['detail']}")
    assert resp.status_code == 404

if __name__ == "__main__":
    print("开始测试 ZY 数据域 API...")
    
    try:
        test_health()
        test_list_collections()
        test_query_assets()
        test_query_with_filter()
        test_count()
        test_not_found()
        
        print("\n✅ 所有测试通过!")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
```

运行测试:

```bash
cd d:\portfilio
python scripts/test_zy_data_api.py
```

## 🔐 安全建议

### 1. 添加认证

```python
from fastapi import Depends, HTTPException
from app.auth import get_current_user  # 您的认证模块

@router.get("/{collection}")
def query_collection(
    collection: str,
    current_user = Depends(get_current_user),  # 添加认证
    page: int = Query(1, ge=1),
    ...
):
    # 可以基于用户角色过滤数据
    pass
```

### 2. 添加速率限制

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.get("/{collection}")
@limiter.limit("100/minute")  # 每分钟 100 次
async def query_collection(request, ...):
    pass
```

### 3. 添加日志记录

已在实现中添加基础日志,建议集成到项目的日志系统。

## 📊 性能优化

### 1. 创建索引

为常用查询字段创建 MongoDB 索引:

```javascript
// 在 MongoDB Shell 中运行
use portfilio

// 资产表索引
db.dwd_ast_info.createIndex({AST_TYPE: 1})
db.dwd_ast_info.createIndex({ISR_ID: 1})
db.dwd_ast_info.createIndex({AST_CD: 1}, {unique: true})

// 产品表索引
db.dwd_ptl_info.createIndex({PORT_TYPE: 1})
db.dwd_ptl_info.createIndex({PORT_ID: 1}, {unique: true})

// 主体表索引
db.dwd_isr_institution.createIndex({ISR_TYPE: 1})
db.dwd_isr_institution.createIndex({ISR_ID: 1}, {unique: true})
```

### 2. 添加缓存

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def get_cached_collection_names():
    db = get_db()
    return db.list_collection_names()
```

### 3. 分页优化

对于大数据量集合,使用游标分页:

```python
# 替代 skip/limit
cursor = db[collection].find(query).sort("_id", 1).limit(pageSize)
if last_id:
    cursor = cursor.filter({"_id": {"$gt": last_id}})
```

## 🐛 故障排查

### 问题 1: MongoDB 连接失败

```
pymongo.errors.ServerSelectionTimeoutError
```

解决:
```bash
# 检查 MongoDB 是否运行
mongosh --eval "db.runCommand('ping')"

# 检查连接字符串
echo $MONGO_URI
```

### 问题 2: 集合不存在

```
集合 'xxx' 不存在
```

解决:
```bash
# 查看可用集合
mongosh portfilio --eval "db.getCollectionNames()"

# 导入数据
python scripts/import_zy_data_domain_mock.py
```

### 问题 3: CORS 错误

前端跨域请求失败,在 `main.py` 中添加:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],  # 前端地址
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## ✅ 验证清单

- [ ] API 文件已部署到后端项目
- [ ] 路由已在 main.py 中注册
- [ ] MongoDB 已启动且可访问
- [ ] Mock 数据已导入 MongoDB
- [ ] 后端服务已启动 (端口 8000)
- [ ] 健康检查接口返回正常
- [ ] 可以查询到集合列表
- [ ] 可以查询到数据记录
- [ ] 前端智能对话可以正常查询
- [ ] 过滤和分页功能正常
- [ ] 新增/更新/删除功能正常

## 📚 相关文档

- [ZY_DATA_DOMAIN_MOCK_IMPORT_GUIDE.md](./ZY_DATA_DOMAIN_MOCK_IMPORT_GUIDE.md) - 完整操作指南
- [zy_data_api_implementation.py](../scripts/zy_data_api_implementation.py) - API 实现代码
- [import_zy_data_domain_mock.py](../scripts/import_zy_data_domain_mock.py) - 数据导入脚本

## 🎯 预期效果

集成完成后:
1. ✅ 智能对话 Agent 可以通过 `/api/v1/zy-data/` 查询 82 张表数据
2. ✅ 前端 ZY 数据域管理页面继续正常工作
3. ✅ 支持分页、过滤、统计、CRUD 完整功能
4. ✅ 与前端 `zyDataDomain.js` API 契约完全兼容
