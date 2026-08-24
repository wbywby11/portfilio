"""精确定位差异引入的日期"""
import csv, sys, os
sys.path.insert(0, r'd:\project\portfilio\portfilio-end')
import asyncio
from app.config.database import Database

# 原型NAV
proto = {}
with open(r'd:\project\portfilio\大类资产模型研究实验最新在用\results\prototype_nav_daily.csv', 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    next(reader)
    for row in reader:
        proto[row[0]] = float(row[1])

# 监测NAV + 事件
async def get_data():
    Database.connect()
    db = Database.db
    doc = await db['monitor_states'].find_one(
        {"monitor_id": "6a2b8d5fb67c1b1b54540b0d"},
        {"nav_history": 1, "_id": 0, "event_log": 1}
    )
    return doc

doc = asyncio.run(get_data())
monitor = {}
for entry in doc['nav_history']:
    monitor[entry['date'][:10]] = entry['nav']

# 逐日对比，找首次差异>0.01的日期
all_dates = sorted(set(proto.keys()) & set(monitor.keys()))
prev_diff = 0
print("=== 差异变化点 ===")
for i, d in enumerate(all_dates):
    p, m = proto[d], monitor[d]
    diff = m - p
    if i > 0 and abs(diff) > 0.01 and abs(prev_diff) < 0.01:
        # 首次差异出现
        print(f"首次差异出现: {d}, proto={p:.4f}, mon={m:.4f}, diff={diff:.6f}")
        # 输出前后5天
        start = max(0, i - 5)
        end = min(len(all_dates), i + 5)
        for j in range(start, end):
            dd = all_dates[j]
            pp, mm = proto[dd], monitor[dd]
            marker = " <<<" if dd == d else ""
            print(f"  {dd} | proto={pp:.4f} | mon={mm:.4f} | diff={mm-pp:.6f}{marker}")
    elif abs(diff - prev_diff) > 0.5:
        # 差异突然增大
        print(f"差异跳变: {d}, prev_diff={prev_diff:.6f}, diff={diff:.6f}, 变化={diff-prev_diff:.6f}")
        # 查找对应事件
        for ev in doc['event_log']:
            ed = ev.get('date', '')[:10]
            if ed == d:
                print(f"  事件: {ev.get('type')} {ev.get('stage','')} | {str(ev.get('description',''))[:80]}")
    prev_diff = diff

# 找首次差异>0.01前后的调仓事件
print("\n=== 2015年5月-7月的所有事件 ===")
for ev in doc['event_log']:
    ed = ev.get('date', '')
    if '2015-05' <= ed[:7] <= '2015-07':
        etype = ev.get('type', '')
        stage = ev.get('stage', '')
        desc = str(ev.get('description', ''))[:100]
        tc = ev.get('trading_cost', '')
        print(f"  {ed} {etype:12s} {stage:10s} | tc={tc} | {desc}")
        # 对应NAV
        d10 = ed[:10]
        if d10 in proto and d10 in monitor:
            print(f"    proto_NAV={proto[d10]:.4f} mon_NAV={monitor[d10]:.4f} diff={monitor[d10]-proto[d10]:.6f}")
