# -*- coding: utf-8 -*-
"""将 Mongo / pandas 的各类时间表示统一为无时区的日历日 Timestamp，保证 dict/set 成员判断一致。

另提供资产日历的前瞻外推工具（infer_trading_weekdays / next_forward_trade_day /
build_forward_calendar）：历史段用资产实际行情日期，超出资产覆盖范围的未来段
按推断的星期模式外推，供实盘发布生效日、期权观察日等前瞻型场景使用，不依赖
Mongo trade_dates 集合（该集合仅研究员策略 sharpe_18/hybrid_12 使用）。
"""
from typing import List, Optional, Set

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


def coerce_trade_dates(trade_dates: list, prices_df: pd.DataFrame,
                       source: str = "trade_dates") -> list:
    """规范化逐日推演使用的日历.

    Args:
        trade_dates: Mongo trade_dates 集合的交易日
        prices_df: 资产价格矩阵，索引为日期
        source: 日历口径（经 MonitorRuntimeConfig.calendar_source 透传）：
            - "prices"（系统策略默认）直接用价格矩阵索引，即所选资产价格
              日期并集，使监控轴与回测轴（DataFeed.prices.index）同源；
            - "trade_dates"（函数默认值，仅研究员策略 sharpe_18/hybrid_12
              显式声明使用）用 Mongo 交易日历，无数据时回退为价格索引。

    Returns:
        日期列表（source="trade_dates" 时为规范化 Timestamp）；均无数据时返回空列表
    """
    if source == "prices":
        if prices_df is not None and not prices_df.empty:
            if trade_dates:
                logger.info(
                    "按策略声明 calendar_source=prices 改用价格日历（{} 个日期），"
                    "忽略 Mongo trade_dates 集合的 {} 条记录",
                    len(prices_df.index), len(trade_dates),
                )
            return sorted(prices_df.index.tolist())
        logger.warning(
            "策略声明 calendar_source=prices 但价格矩阵为空，回退交易日历"
        )
    if trade_dates:
        return [normalize_calendar_timestamp(d) for d in trade_dates]
    if prices_df is not None and not prices_df.empty:
        logger.warning(
            "交易日历仍为空（请检查 Mongo trade_dates 集合），"
            "暂用价格数据的日期索引作为交易日列表"
        )
        return sorted(prices_df.index.tolist())
    return []


def normalize_date_strs(dates) -> List[str]:
    """把混合类型（str/Timestamp/datetime）日期列表统一为 YYYY-MM-DD 字符串。

    无法解析的元素跳过；不去重、不排序（由调用方决定）。
    """
    out: List[str] = []
    for d in dates or []:
        try:
            out.append(normalize_calendar_timestamp(d).strftime("%Y-%m-%d"))
        except (ValueError, TypeError):
            continue
    return out


def infer_trading_weekdays(hist_dates) -> Set[int]:
    """从历史资产日期推断交易日落在哪些星期（0=周一..6=周日）。

    hist_dates 为空时返回空集合，由调用方决定兜底，不做静默假设。
    """
    weekdays: Set[int] = set()
    for ds in normalize_date_strs(hist_dates):
        weekdays.add(pd.Timestamp(ds).weekday())
    return weekdays


def _extrapolate_weekdays(mask: Set[int], start, end) -> List[str]:
    """[start, end] 闭区间内、星期命中 mask 的日历日（YYYY-MM-DD 升序）。"""
    if not mask:
        return []
    cur = pd.Timestamp(start).normalize()
    last = pd.Timestamp(end).normalize()
    out: List[str] = []
    while cur <= last:
        if cur.weekday() in mask:
            out.append(cur.strftime("%Y-%m-%d"))
        cur += pd.Timedelta(days=1)
    return out


def next_forward_trade_day(hist_dates, base_date) -> Optional[str]:
    """base_date 之后的下一个交易日（YYYY-MM-DD）。

    优先取资产日历里晚于 base_date 的最早实际日期；base_date 已超出资产日历
    覆盖范围（未来）时，按资产日历推断的星期模式向后外推。资产日历为空或
    无法推断星期模式时返回 None，由调用方走自然日兜底。
    """
    norm = sorted(set(normalize_date_strs(hist_dates)))
    if not norm:
        return None
    base = pd.Timestamp(base_date).normalize()
    base_str = base.strftime("%Y-%m-%d")
    later = [ds for ds in norm if ds > base_str]
    if later:
        return later[0]
    mask = infer_trading_weekdays(norm)
    if not mask:
        return None
    cur = base + pd.Timedelta(days=1)
    for _ in range(400):  # 上限约 13 个月，防呆；命中星期即返回
        if cur.weekday() in mask:
            return cur.strftime("%Y-%m-%d")
        cur += pd.Timedelta(days=1)
    return None


def build_forward_calendar(hist_dates, start, end) -> List[str]:
    """[start, end] 区间日历（YYYY-MM-DD 升序去重）。

    资产实际交易日（落在区间内的）直接采用；区间内、资产日历覆盖范围
    [最早, 最晚实际日期] 之外的部分（早于最早或晚于最晚）按推断的星期模式
    外推；覆盖范围内部的缺日视为真实非交易日，不填充。资产日历为空时返回
    空列表，由调用方走自然日兜底。
    """
    norm = sorted(set(normalize_date_strs(hist_dates)))
    if not norm:
        return []
    s = pd.Timestamp(start).normalize()
    e = pd.Timestamp(end).normalize()
    if s > e:
        return []
    first = pd.Timestamp(norm[0])
    last = pd.Timestamp(norm[-1])
    mask = infer_trading_weekdays(norm)
    out: Set[str] = {ds for ds in norm if s <= pd.Timestamp(ds) <= e}
    if s < first:
        out.update(_extrapolate_weekdays(mask, s, min(first - pd.Timedelta(days=1), e)))
    if e > last:
        out.update(_extrapolate_weekdays(mask, max(last + pd.Timedelta(days=1), s), e))
    return sorted(out)
