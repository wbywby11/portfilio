from pymongo import MongoClient

print("连接 MongoDB...")
client = MongoClient('mongodb://localhost:27017')
db = client['asset_allocation']

print("获取集合列表...")
collections = [n for n in db.list_collection_names() if n.startswith('dwd_')]
print(f"找到 {len(collections)} 个 dwd_ 集合\n")

for name in sorted(collections):
    count = db[name].count_documents({})
    if count > 0:
        print(f"✓ {name}: {count} 条")

print(f"\n完成!")
client.close()
