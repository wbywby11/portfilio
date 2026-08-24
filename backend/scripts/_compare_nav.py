"""对比原型与监测系统的逐日NAV，找出差异分叉点"""
import csv, os

# 读取原型NAV
proto = {}
proto_path = r'd:\project\portfilio\大类资产模型研究实验最新在用\results\prototype_nav_daily.csv'
with open(proto_path, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    next(reader)  # skip header
    for row in reader:
        proto[row[0]] = float(row[1])

# 读取监测系统NAV（从MongoDB nav_history）
import asyncio, sys
sys.path.insert(0, r'd:\project\portfilio\portfilio-end')

from app.config.database import Database

async def get_monitor_nav():
    Database.connect()
    db = Database.db
    doc = await db['monitor_states'].find_one(
        {"monitor_id": "6a2b8d5fb67c1b1b54540b0d"},
        {"nav_history": 1, "_id": 0, "event_log": 1}
    )
    return doc

doc = asyncio.run(get_monitor_nav())
nav_hist = doc['nav_history']
event_log = doc.get('event_log', [])

monitor = {}
for entry in nav_hist:
    d = entry['date'][:10]  # YYYY-MM-DD
    monitor[d] = entry['nav']

# 按日期对齐对比
all_dates = sorted(set(proto.keys()) & set(monitor.keys()))
print(f"原型日期数: {len(proto)}")
print(f"监测日期数: {len(monitor)}")
print(f"共有日期数: {len(all_dates)}")

# 找前20个差异最大的日期
diffs = []
for d in all_dates:
    p = proto[d]
    m = monitor[d]
    diff = m - p
    pct = diff / p * 100
    diffs.append((d, p, m, diff, pct))

# 找NAV首次显著偏离的位置
print("\n=== NAV首次显著偏离(>0.50)的前10个日期 ===")
big_diffs = [x for x in diffs if abs(x[3]) > 0.50]
for d, p, m, diff, pct in big_diffs[:10]:
    print(f"  {d} | 原型={p:.2f} | 监测={m:.2f} | 差={diff:.4f} ({pct:.4f}%)")

# 找差异最大的日期
diffs_sorted = sorted(diffs, key=lambda x: abs(x[3]), reverse=True)
print(f"\n=== 差异最大的10个日期 ===")
for d, p, m, diff, pct in diffs_sorted[:10]:
    print(f"  {d} | 原型={p:.2f} | 监测={m:.2f} | 差={diff:.4f} ({pct:.4f}%)")

# 最后10天对比
print(f"\n=== 最后10天对比 ===")
for d, p, m, diff, pct in diffs[-10:]:
    print(f"  {d} | 原型={p:.2f} | 监测={m:.2f} | 差={diff:.4f} ({pct:.4f}%)")

# 调仓事件对比
print(f"\n=== 监测系统调仓事件({len(event_log)}个) ===")
for ev in event_log:
    ed = ev.get('date', '')
    etype = ev.get('type', '')
    stage = ev.get('stage', '')
    desc = str(ev.get('description', ''))[:80]
    # 查对应日期原型NAV
    p_nav = proto.get(ed[:10], None)
    m_nav = monitor.get(ed[:10], None)
    nav_str = f"原型={p_nav:.2f} 监测={m_nav:.2f}" if p_nav and m_nav else ""
    print(f"  {ed} {etype:12s} {stage:10s} | {nav_str} | {desc}")

# 原型波动率事件
print(f"\n=== 原型波动率事件 ===")
proto_events_path = r'd:\project\portfilio\大类资产模型研究实验最新在用\results\波动率重置事件.xlsx'
if os.path.exists(proto_events_path):
    import pandas as pd
    vol_df = pd.read_excel(proto_events_path)
    for _, row in vol_df.iterrows():
        sig = str(row.get('信号日期', ''))[:10]
        exe = str(row.get('执行日期', ''))[:10]
        executed = row.get('是否执行', '')
        vol_t = row.get('VolTrigger', 0)
        scale = row.get('缩放因子', 0)
        print(f"  信号={sig} 执行={exe} 执行={executed} vol={vol_t:.4f} scale={scale:.4f}")
