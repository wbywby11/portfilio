"""
将 ZY 数据域 Mock 数据导入 MongoDB

用途：将前端 localStorage 中的 REALISTIC_SEEDS 数据写入 MongoDB，
      使智能对话 Agent 可以通过后端 API 查询到数据。

使用方法：
  cd d:\portfilio
  python scripts/import_zy_data_domain_mock.py
"""
import json
import sys
from pathlib import Path
from pymongo import MongoClient
from datetime import datetime

# MongoDB 配置
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"

# ZY 数据域 Mock 数据文件路径
MOCK_JS_PATH = Path(__file__).parent.parent / "src" / "api" / "zyDataDomain.mock.js"

# 业务日期
BIZ_DT = "20250324"


def extract_realistic_seeds_from_js():
    """
    从 zyDataDomain.mock.js 中提取 REALISTIC_SEEDS 数据
    
    注意：由于是 JS 文件，这里使用简化的 JSON 提取方式。
    如果提取失败，可以手动将数据保存为 JSON 文件。
    """
    # 尝试读取 JSON 格式的种子数据（如果已提取）
    json_path = Path(__file__).parent / "zy_data_domain_seeds.json"
    if json_path.exists():
        print(f"✓ 从 JSON 文件加载种子数据: {json_path}")
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # 否则提示用户需要手动提取
    print(f"⚠ 未找到 JSON 格式的种子数据文件: {json_path}")
    print(f"  请从 {MOCK_JS_PATH} 中手动提取 REALISTIC_SEEDS 对象并保存为 JSON")
    print(f"  或使用以下步骤自动提取（需要 Node.js）:")
    print(f"    node -e \"")
    print(f"      const fs = require('fs');")
    print(f"      const content = fs.readFileSync('{MOCK_JS_PATH}', 'utf-8');")
    print(f"      const match = content.match(/const REALISTIC_SEEDS = ({[\\s\\S]*?});/);")
    print(f"      if (match) {{")
    print(f"        // 注意：需要手动清理 JS 语法转为 JSON")
    print(f"        console.log(match[1]);")
    print(f"      }}")
    print(f"    \" > {json_path}")
    return None


def import_seeds_to_mongodb(seeds_data):
    """
    将种子数据导入 MongoDB
    
    Args:
        seeds_data: dict, key 为 collection 名称, value 为记录列表
    """
    if not seeds_data:
        print("✗ 种子数据为空，无法导入")
        return
    
    print(f"\n开始导入 ZY 数据域 Mock 数据到 MongoDB...")
    print(f"MongoDB URI: {MONGO_URI}")
    print(f"数据库: {DB_NAME}")
    print(f"集合数量: {len(seeds_data)}")
    
    try:
        # 连接 MongoDB
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        
        # 测试连接
        client.admin.command('ping')
        print("✓ MongoDB 连接成功\n")
        
        total_imported = 0
        
        for collection_name, records in seeds_data.items():
            if not records:
                continue
            
            print(f"导入集合: {collection_name} ({len(records)} 条记录)")
            
            # 清理并标准化记录
            cleaned_records = []
            for idx, record in enumerate(records):
                # 确保有 _id
                if '_id' not in record:
                    record['_id'] = f"m_{collection_name}_{str(idx + 1).zfill(4)}"
                
                # 确保有审计字段
                record['etl_dt'] = record.get('etl_dt', BIZ_DT)
                record['src_sys'] = record.get('src_sys', 'MOCK')
                record['imported_at'] = datetime.now().isoformat()
                
                cleaned_records.append(record)
            
            # 使用 upsert 避免重复导入
            result = db[collection_name].bulk_write([
                {
                    'updateOne': {
                        'filter': {'_id': record['_id']},
                        'update': {'$set': record},
                        'upsert': True
                    }
                }
                for record in cleaned_records
            ])
            
            imported = result.upserted_count
            total_imported += imported
            print(f"  ✓ 新增/更新: {imported} 条\n")
        
        print(f"\n{'='*60}")
        print(f"导入完成！")
        print(f"总计导入: {total_imported} 条记录")
        print(f"集合数量: {len([r for r in seeds_data.values() if r])} 个")
        print(f"{'='*60}\n")
        
        # 验证导入结果
        print("验证导入结果:")
        for collection_name in seeds_data.keys():
            count = db[collection_name].count_documents({})
            print(f"  {collection_name}: {count} 条")
        
        client.close()
        print(f"\n✓ MongoDB 连接已关闭")
        
    except Exception as e:
        print(f"\n✗ 导入失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    print("="*60)
    print("ZY 数据域 Mock 数据导入工具")
    print("="*60)
    
    # 提取种子数据
    seeds_data = extract_realistic_seeds_from_js()
    
    if seeds_data:
        # 导入到 MongoDB
        import_seeds_to_mongodb(seeds_data)
    else:
        print("\n请提供种子数据 JSON 文件后重试")
        print("文件路径: scripts/zy_data_domain_seeds.json")


if __name__ == "__main__":
    main()
