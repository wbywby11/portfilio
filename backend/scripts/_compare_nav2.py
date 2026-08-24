"""对比原型与监测NAV - 输出到文件"""
import csv, sys, os
sys.path.insert(0, r'd:\project\portfilio\portfilio-end')
import asyncio
from app.config.database import Database

# 读取原型
proto = {}
with open(r'd:\project\portfilio\大类资产模型研究实验最新在用\results\prototype_nav_daily.csv', 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    next(reader)
    for row in reader:
        proto[row[0]] = float(row[1])

async def get_monitor_nav():
    Database.connect()
    db = Database.db
    doc = await db['monitor_states'].find_one(
        {"monitor_id": "6a2b8d5fb67c1b1b54540b0d"},
        {"nav_history": 1, "_id": 0, "event_log": 1}
    )
    return doc

doc = asyncio.run(get_monitor_nav())
monitor = {}
for entry in doc['nav_history']:
    monitor[entry['date'][:10]] = entry['nav']

all_dates = sorted(set(proto.keys()) & set(monitor.keys()))

out = []
out.append(f"原型日期数: {len(proto)}, 监测日期数: {len(monitor)}, 共有: {len(all_dates)}")

diffs = []
for d in all_dates:
    p, m = proto[d], monitor[d]
    diffs.append((d, p, m, m - p, (m - p) / p * 100))

# 首次偏离
out.append("\n=== 首次NAV差异 > 0.01 ===")
for d, p, m, diff, pct in diffs:
    if abs(diff) > 0.01:
        out.append(f"  {d} | proto={p:.4f} | mon={m:.4f} | diff={diff:.6f}")
        break

# 前30天对比
out.append("\n=== 前30天逐日对比 ===")
for d, p, m, diff, pct in diffs[:30]:
    out.append(f"  {d} | proto={p:.4f} | mon={m:.4f} | diff={diff:.6f}")

# 差异增长率
out.append("\n=== 差异变化趋势(每月首日) ===")
prev_month = ""
for d, p, m, diff, pct in diffs:
    ym = d[:7]
    if ym != prev_month:
        out.append(f"  {d} | proto={p:.2f} | mon={m:.2f} | diff={diff:.4f} ({pct:.4f}%)")
        prev_month = ym

with open(r'd:\project\portfilio\portfilio-end\scripts\_nav_diff.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print("Done")
