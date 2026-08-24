"""信号日窗口不变式守卫测试（守卫 G8 / 对账 W1）.

断言：signal_dates(A, B) == signal_dates(全历史) ∩ [A, B]

旧实现先按 [start, end] 切片再分组，导致"窗口首日必被判为信号日、
窗口内末月末日必被判为月末"的切片 artifact。修复后 ScheduleResolver
先在全历史日历（行情日历或命名信号日历，不切片）上分组得到全量信号日，
再按 [start, end] 过滤。本测试对行情日历与自定义命名日历两套路径、
全部 rebalance_freq 逐一断言不变式，并显式覆盖窗口起点落在月中/周中
的 artifact 场景。
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.backtesting.schedule import ExecutionSchedule, ScheduleResolver

# ---- 测试日历构造 ----

# 行情日历：2014-01-02 起约 10 年的工作日（近似 A 股交易日）
TRADE_DATES = list(pd.bdate_range("2014-01-02", periods=2600))

# 命名信号日历：行情日历挖掉约 10% 的日期（模拟原型自带交易日表缺日，
# 如 GMSI 2.0 trade_dates.xlsx 缺 308 天），并保证月末日期不完全重合
NAMED_CALENDAR = [d for i, d in enumerate(TRADE_DATES) if i % 10 != 3]

FREQS = ["daily", "weekly", "monthly", "month_end", "quarterly", "yearly"]

# 典型查询窗口：起点刻意落在月中/周中/季中，暴露切片 artifact
WINDOWS = [
    ("2016-03-15", "2018-07-20"),   # 起点月中
    ("2014-01-02", "2024-01-01"),   # 全历史口径
    ("2019-11-11", "2019-12-31"),   # 短窗口跨年末
    ("2020-02-03", "2020-02-28"),   # 单月内
    ("2015-09-01", "2023-06-30"),   # GMSI 验收同款起点（月初非首日）
]


def _make_resolver(freq: str, named: bool) -> ScheduleResolver:
    schedule = ExecutionSchedule(
        rebalance_freq=freq,
        signal_calendar=NAMED_CALENDAR if named else None,
    )
    return ScheduleResolver(schedule, TRADE_DATES)


@pytest.mark.parametrize("named", [False, True], ids=["market_calendar", "named_calendar"])
@pytest.mark.parametrize("freq", FREQS)
@pytest.mark.parametrize("start,end", WINDOWS)
def test_signal_date_window_invariant(freq: str, named: bool, start: str, end: str):
    """signal_dates(A,B) 必须等于 signal_dates(全历史) ∩ [A,B]（精确相等）."""
    resolver = _make_resolver(freq, named)

    s, e = pd.Timestamp(start), pd.Timestamp(end)
    windowed = resolver.resolve_signal_dates(s, e)

    full_start = pd.Timestamp(TRADE_DATES[0])
    full_end = pd.Timestamp(TRADE_DATES[-1])
    full = resolver.resolve_signal_dates(full_start, full_end)
    expected = [d for d in full if s <= d <= e]

    assert windowed == expected, (
        f"freq={freq} named={named} window=[{start},{end}]: "
        f"窗口切片结果与全历史交集不一致（切片 artifact）"
    )


@pytest.mark.parametrize("named", [False, True], ids=["market_calendar", "named_calendar"])
def test_window_first_day_is_not_phantom_monthly_signal(named: bool):
    """窗口首日为月中普通交易日时，monthly 不得将其判为信号日."""
    resolver = _make_resolver("monthly", named)
    # 2016-03-15 是周二、月中；该月真实首个交易日是 2016-03-01
    start, end = pd.Timestamp("2016-03-15"), pd.Timestamp("2016-06-30")
    signals = resolver.resolve_signal_dates(start, end)
    assert start not in signals, "窗口首日被误判为月度信号日（切片 artifact）"
    # 4/5/6 月的月首信号日必须存在
    assert pd.Timestamp("2016-04-01") in signals
    assert pd.Timestamp("2016-05-02") in signals or pd.Timestamp("2016-05-03") in signals


@pytest.mark.parametrize("named", [False, True], ids=["market_calendar", "named_calendar"])
def test_month_end_not_phantom_at_window_tail(named: bool):
    """窗口末日非真实月末时，month_end 不得将其判为信号日."""
    resolver = _make_resolver("month_end", named)
    # 2018-07-20 是月中周五，不是 7 月最后交易日（2018-07-31）
    start, end = pd.Timestamp("2018-01-01"), pd.Timestamp("2018-07-20")
    signals = resolver.resolve_signal_dates(start, end)
    assert end not in signals, "窗口末日被误判为月末信号日（切片 artifact）"
    # 真实月末信号日必须存在
    assert pd.Timestamp("2018-06-29") in signals or pd.Timestamp("2018-06-30") in signals


def test_signal_dates_sorted_and_deduped():
    """全历史分组结果保持单调递增（跨年份分组键不碰撞）."""
    for freq in FREQS:
        resolver = _make_resolver(freq, named=False)
        signals = resolver.resolve_signal_dates(
            pd.Timestamp(TRADE_DATES[0]), pd.Timestamp(TRADE_DATES[-1])
        )
        assert signals == sorted(set(signals)), f"freq={freq} 信号日未排序或含重复"


def test_custom_calendar_month_end_follows_named_calendar():
    """命名日历路径下，月末信号日以命名日历的月末为准."""
    resolver = _make_resolver("month_end", named=True)
    full_start = pd.Timestamp(NAMED_CALENDAR[0])
    full_end = pd.Timestamp(NAMED_CALENDAR[-1])
    signals = resolver.resolve_signal_dates(full_start, full_end)
    # 每个信号日必须是命名日历中其所属月份的最后一个日历日
    month_last: dict = {}
    for d in NAMED_CALENDAR:
        key = (d.year, d.month)
        if key not in month_last or d > month_last[key]:
            month_last[key] = d
    expected_set = set(month_last.values())
    for sd in signals:
        assert sd in expected_set, (
            f"{sd} 不是命名日历的月末，却成为 month_end 信号日"
        )
