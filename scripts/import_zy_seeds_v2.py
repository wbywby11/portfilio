"""
ZY 数据域数据导入工具 V2

直接从 zyDataDomain.mock.js 的 REALISTIC_SEEDS 导入数据
与后端 collection_registry.py 中的 83 个集合名称完全匹配

使用方法:
  cd d:\portfilio
  python scripts/import_zy_seeds_v2.py
"""
import json
import re
import sys
from pathlib import Path
from pymongo import MongoClient

# 配置
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"
MOCK_FILE = Path(__file__).parent.parent / "src" / "api" / "zyDataDomain.mock.js"
BIZ_DT = "20250324"

def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

def extract_realistic_seeds():
    """从 zyDataDomain.mock.js 提取 REALISTIC_SEEDS 数据"""
    print(f"读取文件: {MOCK_FILE}")
    
    with open(MOCK_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 定位 REALISTIC_SEEDS 对象
    start_match = re.search(r'const REALISTIC_SEEDS\s*=\s*\{', content)
    if not start_match:
        raise ValueError("未找到 REALISTIC_SEEDS 定义")
    
    start_idx = start_match.start()
    
    # 计算大括号匹配以找到结束位置
    brace_count = 0
    end_idx = start_idx
    in_string = False
    string_char = ''
    escape_next = False
    
    for i in range(start_idx, len(content)):
        char = content[i]
        
        if escape_next:
            escape_next = False
            continue
        
        if char == '\\':
            escape_next = True
            continue
        
        if char in ('"', "'", '`') and not in_string:
            in_string = True
            string_char = char
            continue
        
        if in_string and char == string_char:
            in_string = False
            continue
        
        if not in_string:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i
                    break
    
    js_obj = content[start_idx:end_idx + 1]
    
    # 转换 JS 对象为 Python 可解析格式
    # 1. 移除注释
    js_obj = re.sub(r'//.*$', '', js_obj, flags=re.MULTILINE)
    js_obj = re.sub(r'/\*[\s\S]*?\*/', '', js_obj)
    
    # 2. 转换单引号为双引号
    js_obj = re.sub(r'(\s)([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*', r'\1"\2": ', js_obj)
    js_obj = re.sub(r":\s*'([^']*)'", r': "\1"', js_obj)
    
    # 3. 移除尾部逗号
    js_obj = re.sub(r',(\s*[}\]])', r'\1', js_obj)
    
    # 移除 "const REALISTIC_SEEDS = " 前缀
    js_obj = re.sub(r'^const\s+REALISTIC_SEEDS\s*=\s*', '', js_obj)
    
    try:
        seeds = json.loads(js_obj)
        print(f"✅ 解析成功,共 {len(seeds)} 个集合")
        return seeds
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败: {e}")
        # 尝试更宽松的解析
        return parse_js_object_flexible(js_obj)

def parse_js_object_flexible(js_str):
    """更宽松的 JS 对象解析"""
    result = {}
    
    # 分割键值对
    # 找到所有 collection: [...] 块
    pattern = r'"([dwt][a-z_]+)"\s*:\s*\[([\s\S]*?)\](?=,|\})'
    matches = re.findall(pattern, js_str)
    
    for collection_name, array_content in matches:
        objects = []
        
        # 分割每个对象 { ... }
        obj_pattern = r'\{([^}]+(?:\{[^}]*\}[^}]*)*)\}'
        objs = re.findall(obj_pattern, array_content)
        
        for obj_str in objs:
            obj = parse_single_object(obj_str)
            if obj:
                objects.append(obj)
        
        if objects:
            result[collection_name] = objects
    
    return result

def parse_single_object(obj_str):
    """解析单个 JS 对象"""
    result = {}
    
    # 匹配各种类型的值
    patterns = [
        # 键名: 数字 (包括科学计数法)
        (r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*(?:,|})', 'number'),
        # 键名: null
        (r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*null\s*(?:,|})', 'null'),
        # 键名: true/false
        (r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(true|false)\s*(?:,|})', 'bool'),
        # 键名: 单引号字符串
        (r"([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*'([^']*)'\s*(?:,|})", 'single_string'),
        # 键名: 双引号字符串
        (r'([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*"([^"]*)"\s*(?:,|})', 'double_string'),
    ]
    
    for pattern, value_type in patterns:
        matches = re.findall(pattern, obj_str)
        for key, value in matches:
            if key in ('true', 'false', 'null'):
                continue
            if value_type == 'null':
                result[key] = None
            elif value_type == 'bool':
                result[key] = value == 'true'
            elif value_type == 'number':
                try:
                    result[key] = float(value) if '.' in value or 'e' in value.lower() else int(value)
                except:
                    result[key] = value
            else:
                result[key] = value
    
    return result if result else None

def main():
    print("="*70)
    print("  ZY 数据域 - 从 Mock 数据导入 MongoDB")
    print("="*70)
    
    # 连接 MongoDB
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client[DB_NAME]
        print(f"✅ MongoDB 连接成功!")
    except Exception as e:
        print(f"❌ MongoDB 连接失败: {e}")
        sys.exit(1)
    
    # 提取种子数据
    try:
        seeds = extract_realistic_seeds()
    except Exception as e:
        print(f"❌ 数据提取失败: {e}")
        sys.exit(1)
    
    # 导入数据
    print_section("开始导入数据")
    
    total_imported = 0
    total_skipped = 0
    
    for collection_name, records in seeds.items():
        # 检查记录数
        if not records:
            continue
        
        coll = db[collection_name]
        
        # 清理记录,确保有审计字段
        cleaned_records = []
        for idx, record in enumerate(records):
            # 确保有 _id
            if '_id' not in record:
                record['_id'] = f"m_{collection_name}_{str(idx + 1).zfill(4)}"
            
            # 添加审计字段
            record['etl_dt'] = record.get('etl_dt', BIZ_DT)
            record['src_sys'] = record.get('src_sys', 'MOCK')
            
            cleaned_records.append(record)
        
        # 使用 upsert 避免重复
        try:
            for record in cleaned_records:
                coll.update_one(
                    {'_id': record['_id']},
                    {'$set': record},
                    upsert=True
                )
            
            count = len(cleaned_records)
            total_imported += count
            print(f"✅ {collection_name}: +{count} 条")
        except Exception as e:
            print(f"❌ {collection_name}: {e}")
            total_skipped += len(cleaned_records)
    
    # 验证结果
    print_section("导入结果验证")
    
    # 获取后端注册的集合
    try:
        from pathlib import Path
        import re
        
        registry_file = Path("d:/portfilio-end/app/services/collection_registry.py")
        if registry_file.exists():
            content = registry_file.read_text()
            pattern = r'"(dwd_[a-z_]+|tag_[a-z_]+)"'
            registered = set(re.findall(pattern, content))
            print(f"后端注册集合数: {len(registered)}")
    except:
        registered = set()
    
    # 查看 MongoDB 集合
    collections = db.list_collection_names()
    print(f"MongoDB 集合数: {len(collections)}")
    
    # 按域统计
    domain_stats = {}
    for coll_name in sorted(collections):
        if coll_name.startswith('system'):
            continue
        
        # 提取域前缀
        if coll_name.startswith('dwd_ast_') or coll_name.startswith('dwd_isr_') or coll_name.startswith('dwd_ptl_') or \
           coll_name.startswith('dwd_val_') or coll_name.startswith('dwd_trn_') or \
           coll_name.startswith('dwd_cust_') or coll_name.startswith('dwd_rsk_') or \
           coll_name.startswith('dwd_crdt_') or coll_name.startswith('dwd_mkt_') or \
           coll_name.startswith('tag_'):
            prefix = coll_name.split('_')[0] + '_' + coll_name.split('_')[1]
            domain = {
                'dwd_ast': '资产域',
                'dwd_isr': '主体域',
                'dwd_ptl': '产品域',
                'dwd_val': '估值域',
                'dwd_trn': '交易域',
                'dwd_cust': '客户域',
                'dwd_rsk': '风险域',
                'dwd_crdt': '信用域',
                'dwd_mkt': '行情域',
                'tag': '标签域',
            }.get(prefix, prefix)
            
            if domain not in domain_stats:
                domain_stats[domain] = {'count': 0, 'tables': []}
            
            count = db[coll_name].count_documents({})
            domain_stats[domain]['count'] += count
            domain_stats[domain]['tables'].append((coll_name, count))
    
    print("\n按域统计:")
    for domain, stats in domain_stats.items():
        print(f"\n{domain} ({len(stats['tables'])} 张表, {stats['count']} 条记录):")
        for table, count in stats['tables'][:5]:  # 只显示前5个
            print(f"  - {table}: {count} 条")
        if len(stats['tables']) > 5:
            print(f"  ... 还有 {len(stats['tables']) - 5} 张表")
    
    # 样例查询
    print_section("样例数据查询")
    
    sample_queries = [
        ("dwd_ast_info", {}),
        ("dwd_isr_institution", {}),
        ("dwd_ptl_info", {}),
    ]
    
    for coll_name, filter_dict in sample_queries:
        if coll_name in collections:
            doc = db[coll_name].find_one(filter_dict)
            if doc:
                doc.pop('_id', None)
                doc.pop('etl_dt', None)
                doc.pop('src_sys', None)
                print(f"\n{coll_name} 样例:")
                # 只显示前几个字段
                preview = {k: v for k, v in list(doc.items())[:8]}
                print(f"  {preview}")
    
    # 完成
    print_section("导入完成")
    print(f"✅ 导入记录数: {total_imported}")
    print(f"⚠️  跳过记录数: {total_skipped}")
    print(f"✅ MongoDB 集合数: {len(collections)}")
    print(f"\n🚀 可通过 API 查询:")
    print(f"   GET http://localhost:8000/api/v1/zy-data/{{collection}}")
    print(f"   GET http://localhost:8000/api/v1/zy-data/collections")
    
    client.close()

if __name__ == "__main__":
    main()