# -*- coding: utf-8 -*-
"""调仓执行日提取（事件日志口径）。

监控侧有两个入口需要「哪些日期构成调仓周期边界」：
- report_generator：/monitor/performance 与暂停快照
- performance_cache：绩效页缓存与区间指标

两处共用本函数，保证胜率的周期切分完全一致。兼容两套事件字段口径：
- 旧格式：monthly_rebalance / vol_reset_execute / subjective_rebalance
- 新格式：monthly / vol_reset(stage=execute) / subjective
"""

from typing import Any, Dict, Iterable, List, Optional


def rebalance_dates_from_event_log(
    event_log: Optional[Iterable[Dict[str, Any]]],
) -> List[str]:
    """从事件日志提取调仓执行日（升序、去重、YYYY-MM-DD）。

    只取「实际执行」的事件：vol_reset 的 trigger/skipped 阶段不是调仓日，
    init 是建仓日而非周期边界，均不纳入。
    """
    marks = set()
    for ev in event_log or []:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type", "") or ev.get("event_type", "")
        stage = ev.get("stage", "")
        if etype in (
            "monthly_rebalance", "vol_reset_execute",
            "subjective_rebalance", "monthly", "subjective",
        ):
            executed = True
        elif etype == "vol_reset" and stage == "execute":
            executed = True
        else:
            executed = False
        if not executed:
            continue
        day = str(ev.get("date") or "")[:10]
        if day:
            marks.add(day)
    return sorted(marks)
