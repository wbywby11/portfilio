"""
将 ZY 数据域数据导入到 asset_allocation 数据库 (后端默认数据库)

使用方法:
  cd d:\portfilio
  python scripts/import_to_asset_allocation.py
"""
import json
import sys
from pathlib import Path
from pymongo import MongoClient

# 配置
MONGO_URI = "mongodb://localhost:27017"
TARGET_DB = "asset_allocation"  # 后端默认数据库
SOURCE_JSON = Path(__file__).parent / "zy_data_domain_seeds_v2.json"

def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

def main():
    print("="*70)
    print("  ZY 数据域 - 导入到 asset_allocation 数据库")
    print("="*70)
    print(f"目标数据库: {TARGET_DB}")
    
    # 检查 JSON 文件
    if not SOURCE_JSON.exists():
        print(f"❌ JSON 文件不存在: {SOURCE_JSON}")
        print(f"   请先运行: node scripts/extract_zy_mock_seeds_v2.js")
        sys.exit(1)
    
    # 读取 JSON
    print(f"读取文件: {SOURCE_JSON}")
    with open(SOURCE_JSON, 'r', encoding='utf-8') as f:
        seeds_data = json.load(f)
    
    print(f"✅ 读取成功,共 {len(seeds_data)} 个集合")
    
    # 连接 MongoDB
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client[TARGET_DB]
        print(f"✅ MongoDB 连接成功!")
        print(f"   目标数据库: {db.name}")
    except Exception as e:
        print(f"❌ MongoDB 连接失败: {e}")
        sys.exit(1)
    
    # 导入数据
    print_section("开始导入数据")
    
    total_imported = 0
    
    for collection_name, records in seeds_data.items():
        if not records or not isinstance(records, list):
            continue
        
        coll = db[collection_name]
        
        # 清理记录
        cleaned_records = []
        for idx, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            
            # 确保有 _id
            if '_id' not in record:
                record['_id'] = f"m_{collection_name}_{str(idx + 1).zfill(4)}"
            
            # 添加审计字段
            if 'etl_dt' not in record:
                record['etl_dt'] = "20250324"
            if 'src_sys' not in record:
                record['src_sys'] = 'MOCK'
            
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
    
    # 验证结果
    print_section("导入结果验证")
    
    collections = db.list_collection_names()
    print(f"✅ MongoDB 总集合数: {len(collections)}")
    
    # 按域统计
    domain_stats = {}
    for coll_name in sorted(collections):
        if coll_name.startswith('system') or coll_name.startswith('zy_registry'):
            continue
        
        # 确定域
        if coll_name.startswith('dwd_ast_'):
            domain = '资产域'
        elif coll_name.startswith('dwd_isr_'):
            domain = '主体域'
        elif coll_name.startswith('dwd_ptl_') or coll_name == 'tag_ptl_info':
            domain = '产品域'
        elif coll_name.startswith('dwd_val_'):
            domain = '估值域'
        elif coll_name.startswith('dwd_trn_'):
            domain = '交易域'
        elif coll_name.startswith('dwd_cust_'):
            domain = '客户域'
        elif coll_name.startswith('dwd_seller_'):
            domain = '销售域'
        elif coll_name.startswith('dwd_rsk_') or coll_name.startswith('dwd_crdt_'):
            domain = '风险/信用域'
        elif coll_name.startswith('dwd_mkt_'):
            domain = '行情域'
        elif coll_name == 'dwd_cash_acc':
            domain = '现金域'
        else:
            domain = '其他'
        
        if domain not in domain_stats:
            domain_stats[domain] = {'count': 0, 'tables': []}
        
        count = db[coll_name].count_documents({})
        domain_stats[domain]['count'] += count
        domain_stats[domain]['tables'].append((coll_name, count))
    
    print("\n按域统计:")
    for domain, stats in domain_stats.items():
        print(f"\n{domain} ({len(stats['tables'])} 张表, {stats['count']} 条记录)")
        for table, count in stats['tables']:
            print(f"  - {table}: {count} 条")
    
    # 样例查询
    print_section("样例数据查询")
    
    sample_collections = ['dwd_ast_info', 'dwd_isr_institution', 'dwd_ptl_info']
    
    for coll_name in sample_collections:
        if coll_name in collections:
            doc = db[coll_name].find_one({})
            if doc:
                doc_id = doc.pop('_id', None)
                etl_dt = doc.pop('etl_dt', None)
                src_sys = doc.pop('src_sys', None)
                count = db[coll_name].count_documents({})
                print(f"\n{coll_name} 样例 (记录数: {count}):")
                preview = dict(list(doc.items())[:6])
                print(f"  {preview}")
    
    # 完成
    print_section("导入完成")
    print(f"✅ 新增/更新记录数: {total_imported}")
    print(f"✅ asset_allocation 集合数: {len(collections)}")
    print(f"\n🚀 现在重启后端后,智能对话 API 将可查询到数据!")
    
    client.close()

if __name__ == "__main__":
    main()