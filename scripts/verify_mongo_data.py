#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 MongoDB 中的数据"""

from pymongo import MongoClient

try:
    client = MongoClient('mongodb://localhost:27017', serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client['asset_allocation']
    
    print("="*60)
    print("MongoDB 数据验证")
    print("="*60)
    
    collections = sorted([name for name in db.list_collection_names() if name.startswith('dwd_')])
    
    total = 0
    for name in collections:
        count = db[name].count_documents({})
        total += count
        print(f"  {name}: {count} 条")
    
    print(f"\n{'='*60}")
    print(f"总计: {len(collections)} 个集合, {total} 条记录")
    print(f"{'='*60}")
    
    client.close()
    
except Exception as e:
    print(f"错误: {e}")
    print("\n可能原因:")
    print("  1. MongoDB 服务未启动")
    print("  2. 连接地址不正确")
    print("  3. 端口被占用")
