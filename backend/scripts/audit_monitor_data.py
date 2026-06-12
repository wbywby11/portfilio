# -*- coding: utf-8 -*-
"""
监控用数据对齐审计（Mongo + 与监控代码一致的加载方式）

与日常 run_daily/run_init 使用同一套 SyncDataProvider，输出：
- 各资产在 asset_prices 中的行数、首尾日期
- 透视后的价格面板：行数、每列缺失率、全局索引与交易日列表的差异
- 汇率 fx 覆盖
- 每月「月末计算日」：价格索引月末 vs 交易日历月末（易与 Excel 单表不一致）

用法（项目根目录，需可连 Mongo）:
  python scripts/audit_monitor_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def _month_end_from_index(idx: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """与 MonitorService._build_monthly_rebalance_map 一致：按价格索引分组取每月最后一行。"""
    if len(idx) == 0:
        return []
    s = pd.Series(range(len(idx)), index=idx)
    out = []
    for (_, _), group in s.groupby([idx.year, idx.month]):
        out.append(group.index[-1])
    return sorted(set(pd.Timestamp(x).normalize() for x in out))


def _month_end_trade_dates(trade_dates: list) -> list[pd.Timestamp]:
    """每月最后一个出现在 trade_dates 中的日期。"""
    if not trade_dates:
        return []
    ts = sorted(pd.Timestamp(str(d)).normalize() for d in trade_dates)
    by_ym: dict[tuple[int, int], pd.Timestamp] = {}
    for t in ts:
        by_ym[(t.year, t.month)] = t
    return sorted(by_ym.values())


def main() -> None:
    from app.config.database import get_sync_db
    from app.config.settings import settings
    from app.monitor import config
    from app.monitor.data_provider import SyncDataProvider
    from app.monitor.mongo_asset_codes import stored_price_code
    from app.monitor.time_norm import normalize_calendar_timestamp

    db = get_sync_db()
    suf = (settings.MONGO_ASSET_CODE_SUFFIX or "").strip()
    if suf:
        print(f"=== MONGO_ASSET_CODE_SUFFIX={suf!r}（原始 asset_prices 查询将使用标准码+此后缀）===\n")
    prov = SyncDataProvider(db=db)

    print("=== Mongo 集合（配置名）===")
    for k, v in config.MONGO_COLLECTIONS.items():
        try:
            n = db[v].estimated_document_count()
        except Exception as e:
            n = f"? ({e})"
        print(f"  {k}: {v}  ~docs={n}")

    print("\n=== asset_prices：按 asset_code 统计（原始文档）===")
    coll = db[config.MONGO_COLLECTIONS["prices"]]
    codes = list(config.ASSET_NAME_TO_CODE.values())
    for code in codes:
        stored = stored_price_code(code)
        c = coll.count_documents({"asset_code": stored})
        cur = coll.find({"asset_code": stored}).sort("date", 1).limit(1)
        first = next(cur, None)
        cur2 = coll.find({"asset_code": stored}).sort("date", -1).limit(1)
        last = next(cur2, None)
        d0 = first["date"] if first else None
        d1 = last["date"] if last else None
        label = f"{code}" if stored == code else f"{code} -> {stored}"
        print(f"  {label}: count={c}  first={d0}  last={d1}")

    # 抽样检查 date 字段类型
    sample = coll.find_one({"asset_code": stored_price_code(codes[0])}) if codes else None
    if sample:
        dv = sample.get("date")
        print(f"\n  抽样 date 类型: {type(dv).__name__}  value={dv!r}")

    print("\n=== SyncDataProvider.load_prices() 透视后面板 ===")
    prices = prov.load_prices()
    if prices.empty:
        print("  面板为空，无法继续对比。")
        return
    print(f"  行数={len(prices)}  列={list(prices.columns)}")
    print(f"  索引: {prices.index.min()} ~ {prices.index.max()}")
    for col in prices.columns:
        s = prices[col]
        na = float(s.isna().mean())
        print(f"  {col}: 缺失比例 {na:.4f}")

    trade_dates = prov.load_trade_dates()
    td_set = {normalize_calendar_timestamp(d) for d in trade_dates}
    idx_set = set(prices.index.normalize())

    only_in_prices = sorted(idx_set - td_set)
    only_in_td = sorted(td_set - idx_set)
    print(f"\n=== 价格索引 vs 交易日（集合差）===")
    print(f"  交易日数量: {len(trade_dates)}")
    print(f"  在价格索引中但不在 trade_dates 中: {len(only_in_prices)} 行")
    if only_in_prices[:5]:
        print(f"    样例: {[x.strftime('%Y-%m-%d') for x in only_in_prices[:5]]} ...")
    print(f"  在 trade_dates 中但不在价格索引中: {len(only_in_td)} 行")
    if only_in_td[:5]:
        print(f"    样例: {[x.strftime('%Y-%m-%d') for x in only_in_td[:5]]} ...")

    print("\n=== 月末计算日：价格索引 vs 交易日历 ===")
    me_px = _month_end_from_index(prices.index)
    me_td = _month_end_trade_dates(trade_dates)
    me_px_set = {pd.Timestamp(x).normalize() for x in me_px}
    me_td_set = {pd.Timestamp(x).normalize() for x in me_td}
    diff_px = sorted(me_px_set - me_td_set)
    diff_td = sorted(me_td_set - me_px_set)
    print(f"  按价格索引的月末数: {len(me_px_set)}")
    print(f"  按交易日的月末数: {len(me_td_set)}")
    if diff_px:
        print(f"  价格月末但非交易日月末（前10）: {[d.strftime('%Y-%m-%d') for d in diff_px[:10]]}")
    if diff_td:
        print(f"  交易日月末但无该日价格行（前10）: {[d.strftime('%Y-%m-%d') for d in diff_td[:10]]}")

    print("\n=== 汇率 fx ===")
    fx = prov.load_fx()
    if fx.empty:
        print("  空（若 Mongo 无数据应已回退 fx.xlsx）")
    else:
        print(f"  行数={len(fx)}  {fx.index.min()} ~ {fx.index.max()}")

    print("\n=== 说明 ===")
    print("  监控主循环按 prices 透视索引逐日推进；缺失收盘价按 0 收益处理。")
    print("  月度权重 calc_date 取「价格索引上每月最后一行」，T+2 用 trade_dates。")
    print("  若与同事的「统一交易日一行」Excel 不一致，净值与调仓日可能系统性偏离。")


if __name__ == "__main__":
    main()
