# -*- coding: utf-8 -*-
"""将 Mongo / pandas 的各类时间表示统一为无时区的日历日 Timestamp，保证 dict/set 成员判断一致。"""
import pandas as pd


def normalize_calendar_timestamp(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").replace(tzinfo=None)
    return pd.Timestamp(t.strftime("%Y-%m-%d"))


def normalize_datetime_index(idx) -> pd.DatetimeIndex:
    name = getattr(idx, "name", None)
    out = [normalize_calendar_timestamp(x) for x in idx]
    return pd.DatetimeIndex(out, name=name)
