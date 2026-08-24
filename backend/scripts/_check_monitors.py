"""临时脚本：找到sharpe策略的正确monitor_id并重新运行"""
import asyncio
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.config.database import Database

async def main():
    Database.connect()
    db = Database.db
    
    # 查看策略模型
    print("=== 策略模型 ===")
    models = await db['strategy_models'].find({}, {"_id": 1, "name": 1, "template_code": 1, "asset_list": 1, "parameters": 1}).to_list(50)
    for m in models:
        al = m.get('asset_list', [])
        tc = m.get('template_code', '')
        mid = str(m.get('_id'))
        print(f"  _id={mid} name={m.get('name')} template={tc} assets={len(al)}")
        if al:
            print(f"    资产: {al}")
    
    # 查看各监测的 strategy_model_id
    print("\n=== 监测状态 + strategy_model_id ===")
    states = await db['monitor_states'].find({}, {"_id": 0, "monitor_id": 1, "strategy_model_id": 1, "nav": 1, "date": 1, "vol_reset_count": 1, "day_count": 1}).to_list(50)
    for s in states:
        print(f"  monitor_id={s.get('monitor_id')} model_id={s.get('strategy_model_id')} nav={s.get('nav',0):.2f} date={s.get('date')} vol_reset={s.get('vol_reset_count')} days={s.get('day_count')}")

    # 看看 sharpe_rebalance_weights 集合
    wc = await db['sharpe_rebalance_weights'].count_documents({})
    print(f"\n=== sharpe_rebalance_weights: {wc} 条 ===")

if __name__ == "__main__":
    asyncio.run(main())
