# -*- coding: utf-8 -*-
"""监控调仓映射的执行延迟与自然频率测试（B1 / B2）.

覆盖：
1. `_resolve_declared_execution_delay`：声明 0/1/2、未声明、负数、非整数；
2. `_build_monthly_rebalance_map`：T+0 / T+1 / T+2 / 未声明缺省 T+2 /
   信号日非行情交易日顺延 / 末端不足延迟回退；
3. `_build_event_driven_rebalance_map`：自然频率开关默认关闭、
   显式声明后 weekly 信号日 = 每周第一个交易日、event_dates 路径不变。

全部使用桩适配器，不连库、不起服务。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.monitor.rebalance_planning import RebalancePlanningMixin  # noqa: E402


# ---------------------------------------------------------------------------
# 桩
# ---------------------------------------------------------------------------


class _FakePipeline:
    def __init__(self, schedule: dict):
        self._schedule = schedule

    def get_execution_schedule(self):
        return self._schedule


class _FakeAdapter:
    def __init__(self, schedule: dict):
        self.pipeline = _FakePipeline(schedule)

    def compute_weights(self, prices_df, as_of):
        n = len(prices_df.columns)
        return {c: 1.0 / n for c in prices_df.columns}


class _Planner(RebalancePlanningMixin):
    """只挂适配器桩的混入宿主，避开 MonitorService 的库依赖."""

    def __init__(self, schedule: dict):
        self._engine_adapter = _FakeAdapter(schedule)

    def _inject_monitor_panels(self):  # 桩：无面板
        return None


def _prices(n_days: int = 70) -> pd.DataFrame:
    dates = pd.bdate_range("2022-01-03", periods=n_days)
    return pd.DataFrame(
        {"A.TEST": [100.0 + i for i in range(n_days)],
         "B.TEST": [50.0 + i for i in range(n_days)]},
        index=dates,
    )


def _trade_dates(prices: pd.DataFrame) -> list:
    return list(prices.index)


def _month_ends(prices: pd.DataFrame) -> list:
    """按月取 prices.index 分组末值（与 _build_monthly_rebalance_map 同口径）."""
    out = []
    for _, group in prices.groupby([prices.index.year, prices.index.month]):
        out.append(group.index[-1])
    return sorted(out)


# ---------------------------------------------------------------------------
# 1. 声明延迟解析
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "schedule, expected",
    [
        ({"rebalance_freq": "month_end", "execution_delay": 0}, 0),
        ({"rebalance_freq": "month_end", "execution_delay": 1}, 1),
        ({"rebalance_freq": "month_end", "execution_delay": 2}, 2),
        ({"rebalance_freq": "month_end"}, 2),            # 未声明 → 缺省 T+2
        ({"rebalance_freq": "month_end", "execution_delay": None}, 2),
        ({"rebalance_freq": "month_end", "execution_delay": -1}, 2),   # 负数回落
        ({"rebalance_freq": "month_end", "execution_delay": "x"}, 2),  # 非整数回落
    ],
)
def test_resolve_declared_delay(schedule, expected):
    planner = _Planner(schedule)
    assert planner._resolve_declared_execution_delay(None) == expected


def test_resolve_delay_without_adapter():
    class _NoAdapter(RebalancePlanningMixin):
        _engine_adapter = None

    assert _NoAdapter()._resolve_declared_execution_delay(None) == 2


# ---------------------------------------------------------------------------
# 2. 月末路径执行日
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("delay, offset", [(0, 0), (1, 1), (2, 2)])
def test_monthly_execute_date_follows_declared_delay(delay, offset):
    prices = _prices()
    dates = _trade_dates(prices)
    planner = _Planner({"rebalance_freq": "month_end", "execution_delay": delay})

    result = planner._build_monthly_rebalance_map(
        prices, dates, [], rt=None
    )
    assert result, "月末映射不应为空"

    # 每个月末信号都应映射到「其后第 delay 个交易日」；delay=0 即信号日自身
    for calc_date in _month_ends(prices):
        calc_str = calc_date.strftime("%Y-%m-%d")
        hits = [d for d, v in result.items() if v["calc_date"] == calc_str]
        if not hits:
            continue  # 末端不足延迟时被跳过
        future = [d for d in dates if d > calc_date]
        if offset == 0:
            expected = calc_date
        elif len(future) >= offset:
            expected = future[offset - 1]
        else:
            expected = future[-1]
        assert hits[0] == expected


def test_monthly_undeclared_delay_defaults_to_t_plus_2():
    prices = _prices()
    dates = _trade_dates(prices)
    planner = _Planner({"rebalance_freq": "month_end"})
    result = planner._build_monthly_rebalance_map(prices, dates, [], rt=None)

    calc_date = _month_ends(prices)[0]
    future = [d for d in dates if d > calc_date]
    expected = future[1] if len(future) >= 2 else future[0]
    assert result[expected]["calc_date"] == calc_date.strftime("%Y-%m-%d")


def test_monthly_signal_on_non_trade_day_shifts_forward():
    """delay=0 且信号日不在行情交易日历时，顺延到其后第一个交易日."""
    # 构造 prices 轴含周六（模拟多市场交易日），且该周六是当月最后一个日期；
    # 交易日历只含工作日
    jan = pd.bdate_range("2022-01-03", "2022-01-28")
    feb = pd.bdate_range("2022-02-01", "2022-03-04")
    axis = jan.append(pd.DatetimeIndex([pd.Timestamp("2022-01-29")])).append(feb)
    prices = pd.DataFrame({"A.TEST": range(len(axis)), "B.TEST": range(len(axis))},
                          index=axis, dtype=float)
    trade_dates = [d for d in axis if d != pd.Timestamp("2022-01-29")]

    planner = _Planner({"rebalance_freq": "month_end", "execution_delay": 0})
    result = planner._build_monthly_rebalance_map(prices, trade_dates, [], rt=None)

    assert "2022-01-29" in {v["calc_date"] for v in result.values()}
    hit = [d for d, v in result.items() if v["calc_date"] == "2022-01-29"]
    assert hit and hit[0] == pd.Timestamp("2022-02-01")


# ---------------------------------------------------------------------------
# 3. 自然频率路径
# ---------------------------------------------------------------------------


def test_natural_frequency_requires_explicit_flag():
    """声明 daily 但未声明 natural_frequency：不接管，返回 None（存量零影响）."""
    planner = _Planner({"rebalance_freq": "daily", "execution_delay": 0})
    assert planner._build_event_driven_rebalance_map(
        _prices(), _trade_dates(_prices()), [], rt=None
    ) is None


def test_natural_frequency_weekly_uses_first_trade_day_of_week():
    prices = _prices()
    planner = _Planner({
        "rebalance_freq": "weekly",
        "execution_delay": 1,
        "natural_frequency": True,
    })
    result = planner._build_event_driven_rebalance_map(
        prices, _trade_dates(prices), [], rt=None
    )
    assert result, "weekly 自然频率应产出执行日"

    dates = list(prices.index)
    for exec_ts, info in result.items():
        signal = pd.Timestamp(info["calc_date"])
        # 信号日必须是所在自然周的第一个交易日
        week = [d for d in dates if d.isocalendar()[:2] == signal.isocalendar()[:2]]
        assert signal == week[0]
        # T+1：执行日 = 信号日后一个交易日
        pos = dates.index(signal)
        assert exec_ts == dates[pos + 1]


def test_event_dates_path_unchanged():
    """声明 event_dates 时不看 natural_frequency，信号日=事件日."""
    prices = _prices()
    dates = list(prices.index)
    events = [dates[5], dates[20]]
    planner = _Planner({
        "rebalance_freq": "daily",
        "execution_delay": 0,
        "event_dates": [d.strftime("%Y-%m-%d") for d in events],
    })
    result = planner._build_event_driven_rebalance_map(
        prices, dates, [], rt=None
    )
    assert set(result.keys()) == set(events)
