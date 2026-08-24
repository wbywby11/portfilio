"""执行调度参数化：信号日识别 + 执行日推算.

将回测引擎中"什么时候调仓"的调度逻辑从引擎内部抽取为独立模块，
策略通过 get_execution_schedule() 声明调度规则，引擎通过 ScheduleResolver 消费。

核心概念：
- 信号日（signal date）：策略计算权重的日期（由 rebalance_freq 决定）
- 执行日（execute date）：实际成交的日期（信号日 + execution_delay 个交易日，遇排除日顺延）
- 当 execution_delay=0 时，信号日 = 执行日（T+0，默认行为）
- 自定义信号日历（signal_calendar）：原型指数的调排期常基于其自带交易日表
  （如 GMSI 2.0 的 trade_dates.xlsx，与真实行情日历存在缺日差异）。声明该
  日历后，信号日识别与延迟计数在自定义日历上完成；「信号日 + delay」得到
  新权重生效日，实际成交日回映射为行情日历上生效日前最后一个交易日，
  使新权重从生效日起承接全日收益（对齐原型 exec_weights.loc[生效日]=w 口径）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd


@dataclass
class ExecutionSchedule:
    """策略的执行调度规则声明."""

    # 调仓频率：daily / weekly / monthly / month_end / quarterly / yearly
    rebalance_freq: str = "monthly"

    # 信号日到执行日的交易日延迟数（0=当日执行，2=信号日后第2个交易日执行）
    execution_delay: int = 0

    # 排除日集合（YYYY-MM-DD 格式字符串）。执行日落排除日则顺延到下一个交易日
    skip_dates: Set[str] = field(default_factory=set)

    # 资产选择起始日（用于初始化仓位，部分策略需要从更早的日期开始预计算）
    selection_start_date: Optional[str] = None

    # 自定义信号日历：信号日识别与执行延迟计数使用该日历而非行情日历。
    # 解析出的「信号日 + execution_delay」为新权重生效日，实际成交日 =
    # 行情日历上生效日前最后一个交易日（收盘成交，次日起承接全日收益）。
    signal_calendar: Optional[List[pd.Timestamp]] = None

    # 事件驱动信号日：由外部直接声明的信号日列表（如组合层权重模型的
    # 信号值变化日）。声明后 rebalance_freq 的周期识别失效，信号日 =
    # event_dates ∩ [start, end]；执行日仍按 execution_delay 推算。
    event_dates: Optional[List[pd.Timestamp]] = None


class ScheduleResolver:
    """根据 ExecutionSchedule + 交易日历，解析信号日与执行日的映射关系.

    用法：
        resolver = ScheduleResolver(schedule, trade_dates)
        signal_to_exec = resolver.build_signal_to_execute_map(start, end)
        exec_to_signal = resolver.build_execute_to_signal_map(start, end)
    """

    def __init__(
        self,
        schedule: ExecutionSchedule,
        trade_dates: List[pd.Timestamp],
    ) -> None:
        self._schedule = schedule
        # 排序并去重，确保单调递增
        self._trade_dates = sorted(set(trade_dates))
        signal_calendar = schedule.signal_calendar or None
        self._signal_calendar = (
            sorted(set(signal_calendar)) if signal_calendar else None
        )
        self._skip_dates = {
            pd.Timestamp(d) for d in (schedule.skip_dates or set())
        }
        event_dates = schedule.event_dates or None
        self._event_dates = (
            sorted(set(event_dates)) if event_dates else None
        )
        # 全历史信号日缓存：先在完整日历上分组得到全量信号日，
        # 再按 [start, end] 过滤，保证窗口不变式（见 resolve_signal_dates）
        self._cached_signal_dates: Optional[List[pd.Timestamp]] = None

    def resolve_signal_dates(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> List[pd.Timestamp]:
        """根据 rebalance_freq 识别 [start, end] 范围内的所有信号日.

        信号日是策略计算权重的日期，不含执行延迟。
        声明自定义信号日历时，在自定义日历上识别信号日（如原型指数的
        月末以自带交易日表的月末为准，可能与行情日历月末相差数日）。
        例外：日频调仓的信号日 = 全部行情交易日——日频通道的原型在每个
        有行情的交易日重算信号，自定义日历若缺真实交易日（如 GMSI 2.0
        自带交易日表缺 308 天）会漏掉调仓日、信号停滞在旧值；自定义日历
        仅用于分组点识别（周/月月末）与延迟计数。

        窗口不变式：先在**全历史日历**（不切片）上按自然周/月/季分组
        得到全量信号日，再按 [start, end] 过滤返回。由此保证
        signal_dates(A, B) == signal_dates(全历史) ∩ [A, B]，
        消除"窗口首日必为信号日、窗口内末月末日必为月末"的切片 artifact。

        事件驱动：声明 event_dates 时直接返回其与 [start, end] 的交集
        （全量事件日在构造时已给定，窗口过滤不变式天然成立）。
        """
        if self._event_dates is not None:
            return [d for d in self._event_dates if start <= d <= end]

        freq = self._schedule.rebalance_freq
        if freq == "daily":
            return [
                d for d in self._trade_dates
                if start <= d <= end
            ]

        all_signals = self._all_signal_dates()
        if not all_signals:
            return []
        return [d for d in all_signals if start <= d <= end]

    def _all_signal_dates(self) -> List[pd.Timestamp]:
        """在全历史日历上识别全量信号日（结果缓存，分组只算一次）."""
        if self._cached_signal_dates is not None:
            return self._cached_signal_dates

        freq = self._schedule.rebalance_freq
        calendar = (
            self._signal_calendar
            if self._signal_calendar is not None
            else self._trade_dates
        )
        if not calendar:
            self._cached_signal_dates = []
            return []

        idx = pd.DatetimeIndex(calendar)

        if freq == "weekly":
            # 每周第一个交易日
            signals = _first_of_group(idx, lambda d: d.isocalendar()[1] + d.year * 100)
        elif freq == "monthly":
            # 每月第一个交易日
            signals = _first_of_group(idx, lambda d: d.year * 100 + d.month)
        elif freq == "month_end":
            # 每月最后一个交易日
            signals = _last_of_group(idx, lambda d: d.year * 100 + d.month)
        elif freq == "quarterly":
            # 每季度第一个交易日
            signals = _first_of_group(idx, lambda d: d.year * 100 + (d.month - 1) // 3)
        elif freq == "yearly":
            # 每年第一个交易日
            signals = _first_of_group(idx, lambda d: d.year)
        else:
            # 兜底：每日
            signals = [pd.Timestamp(d) for d in calendar]

        self._cached_signal_dates = signals
        return signals

    def resolve_execute_date(self, signal_date: pd.Timestamp) -> Optional[pd.Timestamp]:
        """计算信号日对应的执行日（成交日）.

        默认口径：信号日 + execution_delay 个行情交易日，遇排除日顺延；
        execution_delay=0 时直接返回信号日本身。

        自定义信号日历口径（对齐原型指数 exec_weights.loc[生效日]=w）：
        「信号日 + delay」在自定义日历上计数得到新权重生效日，成交日 =
        行情日历上生效日前最后一个交易日（收盘成交，新权重从生效日起
        承接全日收益）。生效日不在行情日历中时返回 None，对齐原型
        「执行日无行情则跳过赋值、沿用旧权重」的语义，由调用方过滤。
        """
        delay = self._schedule.execution_delay
        if self._signal_calendar is not None and delay > 0:
            effective = self._shift_on_calendar(
                signal_date, self._signal_calendar, delay
            )
            if effective is None:
                return None
            td = self._trade_dates
            pos = np.searchsorted(td, effective)
            if pos >= len(td) or td[pos] != effective:
                # 生效日非行情交易日：原型跳过该次调仓，维持旧权重
                return None
            if pos == 0:
                return None
            candidate = td[pos - 1]
            while candidate in self._skip_dates:
                candidate = self._next_trade_date(candidate)
            return candidate

        if delay <= 0:
            # T+0：执行日 = 信号日，仍需检查排除日
            candidate = signal_date
            while candidate in self._skip_dates:
                candidate = self._next_trade_date(candidate)
            return candidate

        # T+N：从信号日起向后数 delay 个交易日
        candidate = signal_date
        for _ in range(delay):
            candidate = self._next_trade_date(candidate)
        # 排除日顺延
        while candidate in self._skip_dates:
            candidate = self._next_trade_date(candidate)
        return candidate

    def build_signal_to_execute_map(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> Dict[pd.Timestamp, pd.Timestamp]:
        """构建信号日 → 执行日映射表（生效日无行情的信号日被过滤）."""
        signal_dates = self.resolve_signal_dates(start, end)
        result: Dict[pd.Timestamp, pd.Timestamp] = {}
        for sd in signal_dates:
            ed = self.resolve_execute_date(sd)
            if ed is not None:
                result[sd] = ed
        return result

    def build_execute_to_signal_map(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> Dict[pd.Timestamp, pd.Timestamp]:
        """构建执行日 → 信号日映射表（反向索引）.

        引擎在循环中用此表判断"今天是否是某个信号的执行日"。
        """
        s2e = self.build_signal_to_execute_map(start, end)
        return {ed: sd for sd, ed in s2e.items()}

    def _next_trade_date(self, date: pd.Timestamp) -> pd.Timestamp:
        """返回 date 之后的下一个交易日.

        若 date 已是最后一个交易日，则返回 date + 1 日历日（兜底）。
        """
        td = self._trade_dates
        pos = np.searchsorted(td, date, side="right")
        if pos < len(td):
            return td[pos]
        # 兜底：交易日列表已耗尽
        return date + pd.Timedelta(days=1)

    @staticmethod
    def _shift_on_calendar(
        date: pd.Timestamp,
        calendar: List[pd.Timestamp],
        steps: int,
    ) -> Optional[pd.Timestamp]:
        """在指定日历上从 date 向后数 steps 个日历日.

        date 不在日历中时，从其后第一个日历日起步（对齐原型
        td_pos 查表语义：信号日必在日历内，此处仅作容错）。
        日历耗尽时返回 None。
        """
        pos = np.searchsorted(calendar, date)
        if pos < len(calendar) and calendar[pos] != date:
            # date 不在日历：从其后第一个日历日作为第 1 步
            target = pos + steps - 1
        else:
            target = pos + steps
        if 0 <= target < len(calendar):
            return calendar[target]
        return None


# ---- 调度解析（引擎与 Step1 共用的唯一口径） ----

def _coerce_calendar_dates(raw) -> Optional[List[pd.Timestamp]]:
    """将调度声明中的自定义日历（signal_calendar / event_dates）规范化.

    支持 ISO 字符串 / datetime / Timestamp 混排；非法条目跳过，
    空日历返回 None（回退行情日历语义）。
    """
    if not raw:
        return None
    dates: List[pd.Timestamp] = []
    for d in raw:
        ts = pd.to_datetime(d, errors="coerce")
        if ts is not None and not pd.isna(ts):
            dates.append(pd.Timestamp(ts.normalize()))
    return sorted(set(dates)) if dates else None


def resolve_execution_schedule(strategy, config) -> ExecutionSchedule:
    """从策略声明 + 用户配置解析执行调度（引擎与 generate_targets 同源）.

    优先级：策略 get_execution_schedule() 声明 > config.rebalance_freq 兜底；
    config.execution_delay 可覆盖策略声明的延迟值。自定义信号日历与
    事件驱动日期随声明一并透传。
    """
    sched_dict = None
    probe = strategy._base_strategy if hasattr(strategy, "_base_strategy") else strategy
    if hasattr(probe, "get_execution_schedule"):
        sched_dict = probe.get_execution_schedule()

    user_delay = getattr(config, "execution_delay", None)
    if sched_dict:
        sched_dict = dict(sched_dict)
        if user_delay is not None:
            sched_dict["execution_delay"] = int(user_delay)
        return ExecutionSchedule(
            rebalance_freq=sched_dict.get("rebalance_freq", config.rebalance_freq),
            execution_delay=sched_dict.get("execution_delay", 0),
            skip_dates=sched_dict.get("skip_dates", set()),
            selection_start_date=sched_dict.get("selection_start_date"),
            signal_calendar=_coerce_calendar_dates(sched_dict.get("signal_calendar")),
            event_dates=_coerce_calendar_dates(sched_dict.get("event_dates")),
        )
    # 策略未声明调度时，仍可使用用户配置的 execution_delay
    return ExecutionSchedule(
        rebalance_freq=config.rebalance_freq,
        execution_delay=int(user_delay) if user_delay is not None else 0,
    )


# ---- 辅助函数 ----

def _first_of_group(
    idx: pd.DatetimeIndex,
    key_fn,
) -> List[pd.Timestamp]:
    """从 DatetimeIndex 中按 key_fn 分组，取每组第一个日期."""
    result = []
    prev_key = None
    for d in idx:
        k = key_fn(d)
        if k != prev_key:
            result.append(pd.Timestamp(d))
            prev_key = k
    return result


def _last_of_group(
    idx: pd.DatetimeIndex,
    key_fn,
) -> List[pd.Timestamp]:
    """从 DatetimeIndex 中按 key_fn 分组，取每组最后一个日期."""
    groups: Dict = {}
    for d in idx:
        k = key_fn(d)
        groups[k] = pd.Timestamp(d)
    return sorted(groups.values())
