"""临时脚本：对A01 sharpe策略重新运行监测初始化并验证NAV"""
import asyncio
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.config.database import Database
from app.services.monitor_service import MonitorService

SHARPE_MONITOR_ID = "6a2b8d5fb67c1b1b54540b0d"
PROTOTYPE_NAV = 2277.187645

async def main():
    Database.connect()
    print(f"数据库连接已建立")
    
    svc = MonitorService()
    result = await svc.run_init(monitor_id=SHARPE_MONITOR_ID)
    print(f"\n=== A01 Sharpe 监测初始化结果 ===")
    print(f"最终日期: {result.get('date')}")
    print(f"最终NAV:  {result.get('nav'):.6f}")
    print(f"天数:     {result.get('day_count')}")
    print(f"波控次数: {result.get('vol_reset_count')}")
    print(f"交易费用: {result.get('total_trading_cost'):.4f}")
    print(f"复制费用: {result.get('total_replication_cost'):.4f}")
    print(f"\n原型目标NAV: {PROTOTYPE_NAV:.6f}")
    diff = result.get('nav', 0) - PROTOTYPE_NAV
    print(f"差异: {diff:.6f} ({abs(diff)/PROTOTYPE_NAV*100:.4f}%)")

if __name__ == "__main__":
    asyncio.run(main())
