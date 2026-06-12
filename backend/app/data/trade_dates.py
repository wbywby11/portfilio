# -*- coding: utf-8 -*-
"""交易日历：从项目根目录 ``data/trade_dates.xlsx`` 加载，供策略发布、回测等复用。"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set, Tuple

import pandas as pd


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def load_trade_dates(path: Optional[Path] = None) -> Optional[Tuple[List[pd.Timestamp], Set[pd.Timestamp]]]:
    """
    加载交易日列表与集合。

    Excel 需含列 ``trade_dates``，否则使用第一列。失败或文件不存在时返回 ``None``。
    """
    default = _project_root() / "data" / "trade_dates.xlsx"
    p = path or default
    if not p.exists():
        return None
    try:
        df = pd.read_excel(p)
        col = df["trade_dates"] if "trade_dates" in df.columns else df.iloc[:, 0]
        dates = pd.to_datetime(col).dropna().unique().tolist()
        trade_dates_list = sorted(pd.Timestamp(d).normalize() for d in dates)
        return trade_dates_list, set(trade_dates_list)
    except Exception:
        return None


def get_future_trade_dates(
    base_ts: pd.Timestamp,
    n: int = 1,
    trade_dates_list: Optional[List[pd.Timestamp]] = None,
) -> List[pd.Timestamp]:
    """
    返回严格晚于 ``base_ts`` 日历日的连续 ``n`` 个交易日（按 ``trade_dates_list`` 顺序）。

    若 ``trade_dates_list`` 为 ``None``，会先 ``load_trade_dates()``；加载失败则返回空列表。
    """
    if n <= 0:
        return []
    if trade_dates_list is None:
        loaded = load_trade_dates()
        if not loaded:
            return []
        trade_dates_list = loaded[0]
    base = pd.Timestamp(base_ts).normalize()
    out: List[pd.Timestamp] = []
    for d in trade_dates_list:
        dn = pd.Timestamp(d).normalize()
        if dn > base:
            out.append(dn)
            if len(out) >= n:
                break
    return out
