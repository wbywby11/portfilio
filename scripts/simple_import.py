from pymongo import MongoClient
import sys

# 重定向输出到文件
output_file = open('import_result.txt', 'w', encoding='utf-8')
sys.stdout = output_file

print("开始导入...")

try:
    client = MongoClient('mongodb://localhost:27017', serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client['asset_allocation']
    print("✓ MongoDB 连接成功\n")
    
    # 示例数据
    data = {
        'dwd_isr_institution': [
            {'ISR_ID': 'ISR000001', 'ISR_NM': '财政部', 'ISR_TYPE': 'SOVEREIGN', 'BIZ_DT': '20250324', 'etl_dt': '20250324', 'src_sys': 'MOCK'}
        ],
        'dwd_ast_info': [
            {'AST_CD': '019601.IB', 'AST_NM': '25国债03', 'AST_TYPE': 'BOND', 'ISR_ID': 'ISR000001', 'BIZ_DT': '20250324', 'etl_dt': '20250324', 'src_sys': 'MOCK'}
        ]
    }
    
    total = 0
    for coll_name, records in data.items():
        db[coll_name].delete_many({})
        db[coll_name].insert_many(records)
        count = len(records)
        total += count
        print(f"✓ {coll_name}: {count} 条")
    
    print(f"\n总计导入: {total} 条")
    print("✓ 导入完成!")
    
    client.close()
    
except Exception as e:
    print(f"✗ 错误: {e}")
    import traceback
    traceback.print_exc()

output_file.close()
print("完成! 请查看 import_result.txt")
