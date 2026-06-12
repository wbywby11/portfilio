from pymongo import MongoClient
import re

client = MongoClient('mongodb://localhost:27017')
db = client['asset_allocation']

# 直接用 Python 过滤
index_type_assets = list(db['assets'].find({'asset_type': '指数类'}))
etf_in_index = [a for a in index_type_assets if 'ETF' in a.get('name', '')]

print("=== ETF 数据分布 ===")
print(f"asset_type = '指数类' 中名称含 ETF: {len(etf_in_index)}")
print(f"asset_type = '指数类' 的总数: {len(index_type_assets)}")
print(f"asset_type = '基金' 中总数: {db['assets'].count_documents({'asset_type': '基金'})}")

print("\n=== 指数类资产中所有 ETF ===")
print(f"总数: {len(etf_in_index)}")
print("\n前30条:")
for i, asset in enumerate(etf_in_index[:30], 1):
    code = asset.get('code')
    name = asset.get('name')
    print(f"{i:2d}. {code:20s} - {name}")

if len(etf_in_index) > 30:
    print(f"\n... 以及其他 {len(etf_in_index) - 30} 条")

print(f"\n总计 ETF 数量: {len(etf_in_index)}")

