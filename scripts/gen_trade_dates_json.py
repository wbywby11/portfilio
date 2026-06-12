"""
将 trade_dates.xlsx 转换为 MongoDB 可导入的 JSON 文件
"""
import pandas as pd
import json

INPUT_FILE = r"D:\portfilio\scripts\trade_dates.xlsx"
OUTPUT_FILE = r"D:\portfilio\scripts\trade_dates.json"

# 读取 Excel
df = pd.read_excel(INPUT_FILE, index_col=0)
df.index = pd.to_datetime(df.index)

# 也读取 trade_dates 列作为补充
col_dates = pd.to_datetime(df["trade_dates"])

# 合并所有日期并去重
all_dates = set(df.index.tolist()) | set(col_dates.tolist())

# 手动补充附件中有但文件中可能缺失的最新日期
extra = ["2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15", "2026-05-18"]
for d in extra:
    all_dates.add(pd.Timestamp(d))

dates = sorted(all_dates)
print(f"总交易日数: {len(dates)}")
print(f"范围: {dates[0].date()} ~ {dates[-1].date()}")

# 生成 MongoDB Extended JSON 格式
records = []
for d in dates:
    records.append({
        "date": {"$date": d.strftime("%Y-%m-%dT00:00:00.000Z")}
    })

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False)

print(f"已生成 {OUTPUT_FILE}")
print(f"共 {len(records)} 条记录")
