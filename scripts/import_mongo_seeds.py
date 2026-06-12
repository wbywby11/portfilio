"""
MongoDB 种子数据导入工具

功能:
- 批量执行 mongo-seed/*.js 脚本
- 导入 ZY 数据域 82 张表数据

使用方法:
  cd d:\portfilio
  python scripts/import_mongo_seeds.py
"""
import os
import sys
from pathlib import Path
from pymongo import MongoClient, ASCENDING

# 配置
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"
SEEDS_DIR = Path(__file__).parent.parent / "mongo-seed"

# 脚本执行顺序(按域)
SEED_SCRIPTS = [
    ("_keys.js", "共享主键池"),
    ("01_asset_domain.js", "资产域 (12张表)"),
    ("02_subject_domain.js", "主体域 (3张表)"),
    ("03_product_domain.js", "产品域 (12张表)"),
    ("04_valuation_domain.js", "估值域 (10张表)"),
    ("05_transaction_domain.js", "交易域 (7张表)"),
    ("06_seller_domain.js", "销售域 (1张表)"),
    ("07_customer_domain.js", "客户域 (9张表)"),
    ("08_risk_domain.js", "风险域 (7张表)"),
    ("09_market_domain.js", "行情域 (18张表)"),
]

def print_section(title):
    """打印分隔线"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

def load_js_as_dict(js_content):
    """
    解析 JS 文件中的变量定义
    将 JavaScript 变量语法转换为 Python dict
    """
    import re
    
    result = {}
    
    # 移除注释
    js_content = re.sub(r'//.*$', '', js_content, flags=re.MULTILINE)
    js_content = re.sub(r'/\*[\s\S]*?\*/', '', js_content)
    
    # 解析 ZY_KEYS.recreate 定义
    recreate_pattern = r'ZY_KEYS\.recreate\s*\(\s*[\'"]([^\'"]+)[\'"]'
    collections = re.findall(recreate_pattern, js_content)
    
    # 解析 var xxxSeed = [...] 数组定义
    seed_pattern = r'var\s+(\w+)\s*=\s*\[([\s\S]*?)\];'
    matches = re.findall(seed_pattern, js_content)
    
    for var_name, array_content in matches:
        # 解析数组中的对象
        objects = []
        # 使用更宽松的匹配来捕获对象
        obj_pattern = r'\{([^}]+(?:\{[^}]*\}[^}]*)*)\}'
        objs = re.findall(obj_pattern, array_content)
        
        for obj_str in objs:
            try:
                obj = parse_js_object(obj_str)
                if obj:
                    objects.append(obj)
            except:
                pass
        
        if objects:
            result[var_name.replace('Seed', '')] = objects
    
    return result, collections

def parse_js_object(obj_str):
    """解析单个 JS 对象为 Python dict"""
    import re
    
    obj_str = obj_str.strip()
    if not obj_str:
        return None
    
    result = {}
    
    # 匹配键值对
    # 键可能是 unquoted, 'quoted', "double quoted"
    # 值可能是 number, 'string', "string", null, true, false
    
    # 先匹配所有可能的键值对
    patterns = [
        # 数字值 (包括科学计数法如 1.5e8)
        r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*(?:,|})',
        # null 值
        r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*null\s*(?:,|})',
        # true/false 值
        r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(true|false)\s*(?:,|})',
        # 单引号字符串
        r"([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*'([^']*)'\s*(?:,|})",
        # 双引号字符串
        r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*"([^"]*)"\s*(?:,|})',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, obj_str)
        for key, value in matches:
            if key in ('true', 'false', 'null'):
                continue
            if value == 'null':
                result[key] = None
            elif value == 'true':
                result[key] = True
            elif value == 'false':
                result[key] = False
            else:
                # 判断是数字还是字符串
                try:
                    if '.' in value or 'e' in value.lower():
                        result[key] = float(value)
                    else:
                        result[key] = int(value)
                except:
                    result[key] = value
    
    return result if result else None

def execute_seed_script(script_path, description, db):
    """执行单个种子脚本"""
    print(f"\n📦 导入: {description}")
    print(f"   脚本: {script_path}")
    
    with open(script_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 如果是 _keys.js,只执行变量定义
    if script_path.name == '_keys.js':
        # 执行 _keys.js 中的变量定义
        exec_globals = {}
        exec_locals = {}
        try:
            exec(content, exec_globals, exec_locals)
            return exec_locals.get('ZY_KEYS')
        except Exception as e:
            print(f"   ⚠️  _keys.js 执行跳过 (内联使用)")
            return None
    
    # 解析 JS 文件
    data_dict, collections = load_js_as_dict(content)
    
    print(f"   📊 解析到 {len(data_dict)} 个数据集合: {list(data_dict.keys())}")
    
    # 导入数据
    total_imported = 0
    for collection_name, records in data_dict.items():
        if not records:
            continue
        
        coll = db[collection_name]
        
        # 先删除已存在的数据(如果是重新导入)
        # coll.delete_many({})
        
        # 插入数据
        try:
            result = coll.insert_many(records, ordered=False)
            count = len(result.inserted_ids)
            total_imported += count
            print(f"   ✅ {collection_name}: +{count} 条")
        except Exception as e:
            # 处理唯一索引冲突
            if 'duplicate key' in str(e).lower():
                print(f"   ⚠️  {collection_name}: 跳过(已存在)")
            else:
                print(f"   ❌ {collection_name}: {e}")
    
    return total_imported

def main():
    print("="*70)
    print("  ZY 数据域 - MongoDB 种子数据导入工具")
    print("="*70)
    print(f"MongoDB: {MONGO_URI}")
    print(f"数据库: {DB_NAME}")
    print(f"脚本目录: {SEEDS_DIR}")
    
    # 连接 MongoDB
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client[DB_NAME]
        print(f"\n✅ MongoDB 连接成功!")
    except Exception as e:
        print(f"\n❌ MongoDB 连接失败: {e}")
        print(f"   请确保 MongoDB 服务已启动")
        sys.exit(1)
    
    # 执行所有种子脚本
    total_records = 0
    zy_keys = None
    
    for script_name, description in SEED_SCRIPTS:
        script_path = SEEDS_DIR / script_name
        
        if not script_path.exists():
            print(f"\n⚠️  脚本不存在: {script_path}")
            continue
        
        try:
            imported = execute_seed_script(script_path, description, db)
            if isinstance(imported, int):
                total_records += imported
        except Exception as e:
            print(f"\n❌ 执行失败: {e}")
            import traceback
            traceback.print_exc()
    
    # 验证结果
    print_section("导入结果验证")
    
    collections = db.list_collection_names()
    print(f"✅ 总集合数: {len(collections)}")
    
    # 按域统计
    domain_stats = {
        "资产域 (ast)": [],
        "主体域 (isr)": [],
        "产品域 (ptl)": [],
        "估值域 (val)": [],
        "交易域 (trn)": [],
        "销售域 (seller)": [],
        "客户域 (cust)": [],
        "风险域 (rsk/crdt)": [],
        "行情域 (mkt)": [],
    }
    
    for coll_name in sorted(collections):
        count = db[coll_name].count_documents({})
        
        # 判断属于哪个域
        if 'ast' in coll_name:
            domain_stats["资产域 (ast)"].append((coll_name, count))
        elif 'isr' in coll_name:
            domain_stats["主体域 (isr)"].append((coll_name, count))
        elif 'ptl' in coll_name:
            domain_stats["产品域 (ptl)"].append((coll_name, count))
        elif 'val' in coll_name:
            domain_stats["估值域 (val)"].append((coll_name, count))
        elif 'trn' in coll_name:
            domain_stats["交易域 (trn)"].append((coll_name, count))
        elif 'seller' in coll_name:
            domain_stats["销售域 (seller)"].append((coll_name, count))
        elif 'cust' in coll_name:
            domain_stats["客户域 (cust)"].append((coll_name, count))
        elif 'rsk' in coll_name or 'crdt' in coll_name:
            domain_stats["风险域 (rsk/crdt)"].append((coll_name, count))
        elif 'mkt' in coll_name:
            domain_stats["行情域 (mkt)"].append((coll_name, count))
    
    for domain, tables in domain_stats.items():
        if tables:
            print(f"\n{domain}:")
            domain_total = 0
            for table_name, count in tables:
                print(f"  - {table_name}: {count} 条")
                domain_total += count
            print(f"  小计: {domain_total} 条")
    
    # 样例查询
    print_section("样例数据查询")
    
    sample_queries = [
        ("dwd_ast_info", {"AST_TYPE": "BOND"}),
        ("dwd_isr_institution", {"ISR_TYPE": "BANK"}),
        ("dwd_ptl_info", {"PORT_TYPE": "MIXED"}),
    ]
    
    for coll_name, filter_dict in sample_queries:
        if coll_name in collections:
            doc = db[coll_name].find_one(filter_dict)
            if doc:
                # 移除 MongoDB 内部字段
                doc.pop('_id', None)
                doc.pop('etl_dt', None)
                doc.pop('src_sys', None)
                doc.pop('created_at', None)
                doc.pop('updated_at', None)
                print(f"\n{coll_name} 样例:")
                print(f"  {doc}")
    
    # 完成
    print_section("导入完成")
    print(f"✅ 共导入 {len(collections)} 个集合")
    print(f"✅ 可通过 API 查询: http://localhost:8000/api/v1/zy-data/{{collection}}")
    
    client.close()

if __name__ == "__main__":
    main()