# -*- coding: utf-8 -*-
"""
生成可被 mongoimport 一键导入 trade_dates 集合的 JSON 文件。

输出三种格式（任选其一导入，推荐用 NDJSON 不带 --jsonArray）：
  1) trade_dates.ndjson         —— 一行一个对象，mongoimport 默认格式
  2) trade_dates.array.json     —— 数组格式，需要 --jsonArray
  3) trade_dates.dates_only.txt —— 仅日期字符串清单，便于人工核对/diff

数据来源（按优先级，先成功者为准）：
  A. 项目内 scripts/trade_dates.xlsx      （首选：与本系统保持一致）
  B. chinesecalendar 库自动推算           （备选：覆盖 2014~2030）
  C. 工作日近似 + 硬编码法定假期          （兜底：仅做应急）

集合字段：兼容多版本后端
  - date:      ISODate（Mongo 原生）
  - trade_date: 'YYYY-MM-DD' 字符串
  - market:    'CN'    （部分实现按 market 过滤）
  - source:    'xlsx' | 'chinesecalendar' | 'fallback'

使用示例：
  python gen_trade_calendar_mongo_import.py
  # 然后在生产环境执行：
  mongoimport \
      --uri "mongodb://USER:PASS@HOST:27017/portfilio?authSource=admin" \
      --collection trade_dates \
      --file trade_dates.ndjson \
      --mode upsert \
      --upsertFields trade_date
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Set

HERE = Path(__file__).resolve().parent

# ============================================================
# 1) 数据源：优先读现有 xlsx 与项目自带 JSON
# ============================================================

def _load_from_xlsx(path: Path) -> Optional[Set[date]]:
    """从 trade_dates.xlsx 读取交易日（与本系统保持一致）。"""
    if not path.exists():
        return None
    try:
        import pandas as pd  # 延迟引入，便于无 pandas 时跑兜底
    except ImportError:
        print(f"[WARN] 未安装 pandas，跳过 xlsx 读取：{path}", file=sys.stderr)
        return None
    try:
        df = pd.read_excel(path)
        # 兼容多种列名 / 索引列
        candidates = []
        for col in df.columns:
            if str(col).strip().lower() in ("date", "trade_date", "trade_dates", "交易日", "日期"):
                candidates.append(df[col])
        if not candidates and df.index.dtype.kind == "M":
            candidates.append(df.index.to_series())
        if not candidates:
            candidates.append(df.iloc[:, 0])

        all_dates: Set[date] = set()
        for ser in candidates:
            ser = pd.to_datetime(ser, errors="coerce").dropna()
            for ts in ser:
                all_dates.add(ts.date())
        if not all_dates:
            return None
        print(f"[INFO] 已从 xlsx 读取 {len(all_dates)} 条交易日：{path}")
        return all_dates
    except Exception as e:
        print(f"[WARN] 读取 xlsx 失败：{e}", file=sys.stderr)
        return None


def _load_from_existing_json(path: Path) -> Optional[Set[date]]:
    """从已有的 trade_dates.json（项目自带）读取，兼容数组与 NDJSON。"""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        records: List[dict] = []
        if text.startswith("["):
            records = json.loads(text)
        else:
            for line in text.splitlines():
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        out: Set[date] = set()
        for r in records:
            v = r.get("date") or r.get("trade_date")
            if isinstance(v, dict) and "$date" in v:
                v = v["$date"]
            if not v:
                continue
            ds = str(v)[:10]
            out.add(datetime.strptime(ds, "%Y-%m-%d").date())
        if out:
            print(f"[INFO] 已从已有 JSON 读取 {len(out)} 条交易日：{path}")
        return out or None
    except Exception as e:
        print(f"[WARN] 读取已有 JSON 失败：{e}", file=sys.stderr)
        return None


# ============================================================
# 2) chinesecalendar 自动推算（可选）
# ============================================================

def _load_from_chinesecalendar(start_year: int, end_year: int) -> Optional[Set[date]]:
    try:
        import chinese_calendar as cc  # pip install chinesecalendar
    except ImportError:
        print("[INFO] 未安装 chinesecalendar，跳过自动推算（pip install chinesecalendar）", file=sys.stderr)
        return None
    out: Set[date] = set()
    covered_years: List[int] = []
    skipped_years: List[int] = []
    for y in range(start_year, end_year + 1):
        try:
            d = date(y, 1, 1)
            end = date(y, 12, 31)
            while d <= end:
                # 工作日 + 周一至周五 + 非节假日 = A 股交易日
                # 调休的周末上班日因 weekday>=5 已被排除（A 股不开盘）
                if cc.is_workday(d) and d.weekday() < 5 and not cc.is_holiday(d):
                    out.add(d)
                d += timedelta(days=1)
            covered_years.append(y)
        except Exception as e:
            skipped_years.append(y)
            continue
    if covered_years:
        print(f"[INFO] 已用 chinesecalendar 推算 {len(out)} 条交易日，"
              f"覆盖年份 {covered_years[0]}~{covered_years[-1]}"
              + (f"，跳过 {skipped_years}（库未支持）" if skipped_years else ""))
    else:
        print(f"[WARN] chinesecalendar 库不支持任何请求年份 {start_year}~{end_year}", file=sys.stderr)
    return out or None


# ============================================================
# 3) 兜底：工作日 + 硬编码节假日（仅应急用）
# ============================================================

# 中国法定节假日（含调休休假日；不含调休补班日）。覆盖 2024~2026，按需补充
HARDCODED_HOLIDAYS = {
    # 2024
    "2024-01-01",
    "2024-02-09", "2024-02-10", "2024-02-11", "2024-02-12", "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16", "2024-02-17",
    "2024-04-04", "2024-04-05", "2024-04-06",
    "2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05",
    "2024-06-08", "2024-06-09", "2024-06-10",
    "2024-09-15", "2024-09-16", "2024-09-17",
    "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04", "2024-10-05", "2024-10-06", "2024-10-07",
    # 2025
    "2025-01-01",
    "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31", "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
    "2025-04-04", "2025-04-05", "2025-04-06",
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
    "2025-05-31", "2025-06-01", "2025-06-02",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04", "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
    # 2026（按已公布节假日；如有新规请同步）
    "2026-01-01", "2026-01-02", "2026-01-03",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-25", "2026-09-26", "2026-09-27",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
}


def _load_from_fallback(start_year: int, end_year: int) -> Set[date]:
    holidays = {datetime.strptime(s, "%Y-%m-%d").date() for s in HARDCODED_HOLIDAYS}
    out: Set[date] = set()
    d = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            out.add(d)
        d += timedelta(days=1)
    print(f"[INFO] 已用兜底规则生成 {len(out)} 条交易日（{start_year}~{end_year}，硬编码假期 {len(holidays)} 条）")
    return out


# ============================================================
# 4) 主流程
# ============================================================

def main() -> int:
    start_year = int(os.environ.get("CAL_START_YEAR", "2006"))
    end_year = int(os.environ.get("CAL_END_YEAR", "2026"))

    sources: List[tuple] = []

    xlsx_dates = _load_from_xlsx(HERE / "trade_dates.xlsx")
    if xlsx_dates:
        sources.append(("xlsx", xlsx_dates))

    json_dates = _load_from_existing_json(HERE / "trade_dates.json")
    if json_dates:
        sources.append(("existing_json", json_dates))

    cc_dates = _load_from_chinesecalendar(start_year, end_year)
    if cc_dates:
        sources.append(("chinesecalendar", cc_dates))

    if not sources:
        print("[WARN] 未找到任何可用源，使用硬编码兜底", file=sys.stderr)
        sources.append(("fallback", _load_from_fallback(start_year, end_year)))

    # 取并集，确保不同来源彼此补全
    all_dates: Set[date] = set()
    primary_source = sources[0][0]
    for name, ds in sources:
        all_dates |= ds

    # 仅保留区间内
    all_dates = {d for d in all_dates if start_year <= d.year <= end_year}
    if not all_dates:
        print("[ERROR] 合并后日期为空，无法导出", file=sys.stderr)
        return 1

    sorted_dates = sorted(all_dates)
    print(f"[INFO] 最终输出 {len(sorted_dates)} 条交易日："
          f"{sorted_dates[0]} ~ {sorted_dates[-1]} (来源={primary_source})")

    # ---- 输出 ----
    ndjson_path = HERE / "trade_dates.ndjson"
    array_path = HERE / "trade_dates.array.json"
    plain_path = HERE / "trade_dates.dates_only.txt"

    with ndjson_path.open("w", encoding="utf-8") as f_nd, \
         array_path.open("w", encoding="utf-8") as f_arr, \
         plain_path.open("w", encoding="utf-8") as f_pl:
        f_arr.write("[\n")
        for i, d in enumerate(sorted_dates):
            iso_z = d.strftime("%Y-%m-%dT00:00:00.000Z")
            ymd = d.strftime("%Y-%m-%d")
            doc = {
                "date": {"$date": iso_z},
                "trade_date": ymd,
                "market": "CN",
                "source": primary_source,
            }
            line = json.dumps(doc, ensure_ascii=False)
            f_nd.write(line + "\n")
            f_arr.write(("  " + line) + ("," if i < len(sorted_dates) - 1 else "") + "\n")
            f_pl.write(ymd + "\n")
        f_arr.write("]\n")

    print(f"[OK] NDJSON  -> {ndjson_path}")
    print(f"[OK] Array   -> {array_path}")
    print(f"[OK] Dates   -> {plain_path}")

    print()
    print("===== mongoimport 导入命令（任选其一）=====")
    print()
    print("# 1) NDJSON（推荐，幂等 upsert，按 trade_date 去重）")
    print('mongoimport \\')
    print('  --uri "mongodb://USER:PASS@HOST:27017/portfilio?authSource=admin" \\')
    print('  --collection trade_dates \\')
    print(f'  --file {ndjson_path.name} \\')
    print('  --mode upsert \\')
    print('  --upsertFields trade_date')
    print()
    print("# 2) Array JSON（首次导入空集合用 insert 即可）")
    print('mongoimport \\')
    print('  --uri "mongodb://USER:PASS@HOST:27017/portfilio?authSource=admin" \\')
    print('  --collection trade_dates \\')
    print(f'  --file {array_path.name} \\')
    print('  --jsonArray --mode insert')
    print()
    print("# 3) 创建唯一索引（mongosh 内执行，避免重复导入）")
    print('mongosh "mongodb://USER:PASS@HOST:27017/portfilio?authSource=admin" \\')
    print('  --eval "db.trade_dates.createIndex({trade_date: 1}, {unique: true});'
          ' db.trade_dates.createIndex({date: 1}, {unique: true});"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
