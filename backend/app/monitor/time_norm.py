# -*- coding: utf-8 -*-
"""将 Mongo / pandas 的各类时间表示统一为无时区的日历日 Timestamp，保证 dict/set 成员判断一致。"""
import pandas as pd
from loguru import logger


def normalize_calendar_timestamp(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").replace(tzinfo=None)
    return pd.Timestamp(t.strftime("%Y-%m-%d"))


def normalize_datetime_index(idx) -> pd.DatetimeIndex:
    name = getattr(idx, "name", None)
    out = [normalize_calendar_timestamp(x) for x in idx]
    return pd.DatetimeIndex(out, name=name)


def coerce_trade_dates(trade_dates: list, prices_df: pd.DataFrame) -> list:
    """规范化交易日；仅在 Mongo 与 data/trade_dates.xlsx 均无数据时回退为价格索引。"""
    if trade_dates:
        return [normalize_calendar_timestamp(d) for d in trade_dates]
    if prices_df is not None and not prices_df.empty:
        logger.warning(
            "交易日历仍为空（请检查 Mongo trade_dates 集合或 data/trade_dates.xlsx），"
            "暂用价格数据的日期索引作为交易日列表"
        )
        return sorted(prices_df.index.tolist())
    return []
