"""诊断：确认prices_df列名和预计算权重键名映射"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.database import Database
from app.monitor.data_provider import MongoDataProvider
from app.services.monitor_service import MonitorService

async def main():
    Database.connect()
    db = Database.db
    
    # 查看sharpe_rebalance_weights的一条记录
    doc = await db['sharpe_rebalance_weights'].find_one({"calc_date": "2014-01-31"})
    if doc:
        pw = doc.get('weights', {})
        print(f"预计算权重键名: {list(pw.keys())}")
    
    # 查看 mongo_asset_codes 映射表
    codes = await db['asset_prices'].find({"asset_code": {"$regex": "^SH|^SZ|^ZZ|^SPX|^NDX|^N225|^ZQGZ|^UST|^CVTBND|^GLD|^B00Y|^SHCU|^SHAL|^SHSN|^DM"}}, {"asset_code": 1, "asset_name": 1, "_id": 0}).limit(25).to_list(25)
    print(f"\n资产代码→名称映射:")
    for c in codes:
        print(f"  {c.get('asset_code')} → {c.get('asset_name')}")
    
    # 用 MonitorService 加载 prices 看列名
    svc = MonitorService()
    # 模拟 _prepare_monitor_run
    from app.services.strategy_model_service import StrategyModelService
    svc_model = StrategyModelService()
    model = await svc_model.get_model("6a2b8d5fb67c1b1b54540b0d")
    if model:
        from app.monitor.monitor_runtime import monitor_runtime_from_model
        rt = monitor_runtime_from_model(model)
        svc._monitor_runtime = rt
        svc.tracker.configure(rt)
        print(f"\ntracker.asset_list: {list(svc.tracker.asset_list)}")
        
        # 加载 prices
        from app.monitor.data_provider import MongoDataProvider
        provider = MongoDataProvider()
        prices_df = await provider.load_prices(asset_columns=list(svc.tracker.asset_list))
        from app.monitor.monitor_runtime import slice_prices_df
        prices_df = slice_prices_df(prices_df, rt)
        print(f"\nprices_df.columns: {list(prices_df.columns)}")
        print(f"prices_df shape: {prices_df.shape}")

if __name__ == "__main__":
    asyncio.run(main())
