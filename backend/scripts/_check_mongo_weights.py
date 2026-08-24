"""检查MongoDB sharpe_rebalance_weights集合"""
import asyncio, sys, json
sys.path.insert(0, r'd:\project\portfilio\portfilio-end')
from app.config.database import Database

async def main():
    Database.connect()
    db = Database.db
    
    total = await db['sharpe_rebalance_weights'].count_documents({})
    print(f"sharpe_rebalance_weights 总文档数: {total}")
    
    if total > 0:
        sample = await db['sharpe_rebalance_weights'].find({}).limit(3).to_list(length=3)
        for doc in sample:
            print(json.dumps({k: v for k, v in doc.items() if k != 'weights'}, default=str, ensure_ascii=False))
            w = doc.get('weights', {})
            print(f"  weights keys: {list(w.keys())[:5]}...")
    
    # 也检查是否有其他 monitor_id
    monitor_ids = await db['sharpe_rebalance_weights'].distinct('monitor_id')
    print(f"\n所有 monitor_id: {monitor_ids}")

asyncio.run(main())
