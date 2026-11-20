# -*- coding: utf-8 -*-
"""执行事件的规范结构与归一化。

事件是「本日发生了什么」的只读描述，用途是回测与监控逐日差异定位、审计追溯；
状态真相源始终是 ``PortfolioState`` / ``Position``，事件不参与重放，也不作为
任何计算的输入。

为什么需要这一层：同一份 ``monitor_states.event_log`` 里历史上并存三套字段口径——
通用步进路径写 ``type`` / ``stage`` / ``calc_date``，组合监控路径写
``event_type`` / ``details.weights``，而 ``models.monitor.EventLogEntry`` 又是按
后者定义的。消费方各认一套，例如 ``operation_recorder._sync_single_event`` 只读
``type``，组合监控写入的事件在它那里会被静默跳过。比对两侧差异时这种分裂直接
导致「字段对不上」而不是「数值对不上」，无法归因。

本模块给出唯一规范字段集，并提供 :func:`normalize_event` 把存量与异构口径映射
进来：写入方按规范写，读取方按规范读，历史数据不需要迁移。
"""

from typing import Any, Dict, List, Optional

# =============================================================================
# 规范取值
# =============================================================================

#: 事件类型
EVENT_INIT = "init"                # 基日初始化持仓
EVENT_MONTHLY = "monthly"          # 月度调仓
EVENT_VOL_RESET = "vol_reset"      # 波动率重置
EVENT_SUBJECTIVE = "subjective"    # 主观调仓

#: 阶段：仅 vol_reset 会跨越多个交易日，需要区分；其余类型恒为 execute
STAGE_TRIGGER = "trigger"          # 信号日触发，等待执行
STAGE_EXECUTE = "execute"          # 已执行
STAGE_SKIPPED = "skipped"          # 触发后被规则跳过

#: 规范字段顺序。构造与归一化都按此序输出，使逐字段比对的差异位置稳定可读。
EVENT_FIELDS = (
    "date",
    "type",
    "stage",
    "seq",
    "signal_date",
    "execute_date",
    "description",
    "trading_cost",
    "old_weights",
    "new_weights",
    "vol_trigger",
    "scale_factor",
    "override_id",
)

#: 比对时忽略的字段：自由文本与展示用途，两侧措辞不同不代表行为不同
_COMPARISON_IGNORE = frozenset({"description"})


# =============================================================================
# 构造
# =============================================================================

def make_event(
    date: str,
    event_type: str,
    *,
    stage: str = STAGE_EXECUTE,
    signal_date: Optional[str] = None,
    execute_date: Optional[str] = None,
    description: str = "",
    trading_cost: Optional[float] = None,
    old_weights: Optional[Dict[str, float]] = None,
    new_weights: Optional[Dict[str, float]] = None,
    vol_trigger: Optional[float] = None,
    scale_factor: Optional[float] = None,
    override_id: Optional[str] = None,
    event_log: Optional[List[dict]] = None,
) -> dict:
    """构造一条规范事件。

    Args:
        date: 事件发生日 ``YYYY-MM-DD``
        event_type: :data:`EVENT_INIT` 等类型常量
        stage: :data:`STAGE_TRIGGER` 等阶段常量
        signal_date: 信号日（月度调仓=计算日，波动率重置=触发日）
        execute_date: 计划执行日（仅波动率重置触发事件有值）
        event_log: 传入已有日志时自动计算 ``seq``（同日内第几条，从 0 起）；
            同日多条事件的先后顺序是差异定位的一部分，不能靠列表下标推断

    Returns:
        按 :data:`EVENT_FIELDS` 顺序排列的 dict；未提供的字段为 ``None``，
        保证任意两条事件的键集合恒等，比对时无需处理缺键。
    """
    seq = None
    if event_log is not None:
        seq = sum(
            1 for ev in event_log
            if str((ev or {}).get("date") or "")[:10] == str(date)[:10]
        )
    return {
        "date": str(date)[:10],
        "type": event_type,
        "stage": stage,
        "seq": seq,
        "signal_date": str(signal_date)[:10] if signal_date else None,
        "execute_date": str(execute_date)[:10] if execute_date else None,
        "description": description,
        "trading_cost": trading_cost,
        "old_weights": dict(old_weights) if old_weights else None,
        "new_weights": dict(new_weights) if new_weights else None,
        "vol_trigger": vol_trigger,
        "scale_factor": scale_factor,
        "override_id": override_id,
    }


# =============================================================================
# 归一化（读存量与异构口径）
# =============================================================================

#: 组合监控路径的历史类型名 → 规范类型名
_TYPE_ALIASES = {
    "monthly_rebalance": EVENT_MONTHLY,
    "volatility_reset": EVENT_VOL_RESET,
}


def normalize_event(raw: Optional[dict]) -> dict:
    """把任意口径的事件映射到规范字段。

    兼容三套历史写法：

    - 通用步进路径：``type`` / ``stage`` / ``calc_date``
    - 组合监控路径：``event_type`` / ``details.weights``
    - 早期文档缺字段：一律补 ``None``

    不修改入参，返回新 dict。
    """
    if not raw:
        return {name: None for name in EVENT_FIELDS}

    details = raw.get("details") or {}
    raw_type = raw.get("type") or raw.get("event_type")
    event_type = _TYPE_ALIASES.get(raw_type, raw_type)

    # 信号日：月度调仓历史写 calc_date，波动率重置触发事件写 execute_date 而
    # 信号日即事件日本身
    signal_date = raw.get("signal_date") or raw.get("calc_date")
    if not signal_date and event_type == EVENT_VOL_RESET \
            and raw.get("stage") == STAGE_TRIGGER:
        signal_date = raw.get("date")

    new_weights = raw.get("new_weights")
    if not new_weights and isinstance(details, dict):
        new_weights = details.get("weights")

    normalized = {
        "date": str(raw.get("date") or "")[:10] or None,
        "type": event_type,
        "stage": raw.get("stage") or STAGE_EXECUTE,
        "seq": raw.get("seq"),
        "signal_date": str(signal_date)[:10] if signal_date else None,
        "execute_date": (
            str(raw["execute_date"])[:10] if raw.get("execute_date") else None
        ),
        "description": raw.get("description"),
        "trading_cost": raw.get("trading_cost"),
        "old_weights": (
            dict(raw["old_weights"]) if raw.get("old_weights") else None
        ),
        "new_weights": dict(new_weights) if new_weights else None,
        "vol_trigger": raw.get("vol_trigger"),
        "scale_factor": raw.get("scale_factor"),
        "override_id": raw.get("override_id"),
    }
    # 规范之外的历史键（如 details）不丢弃，附加保留以免读取方丢信息
    for key, value in raw.items():
        if key not in normalized and key != "details":
            normalized[key] = value
    return normalized


def events_of_date(event_log: Optional[List[dict]], date: str) -> List[dict]:
    """取某日的全部事件，归一化后按 ``seq`` 稳定排序。

    存量事件没有 ``seq``，此时保持原有列表顺序（写入顺序即时序）。
    """
    target = str(date)[:10]
    picked = [
        normalize_event(ev) for ev in (event_log or [])
        if str((ev or {}).get("date") or "")[:10] == target
    ]
    if all(ev.get("seq") is not None for ev in picked):
        picked.sort(key=lambda ev: ev["seq"])
    return picked


def event_key(ev: dict) -> str:
    """事件的身份标识：``date|type|stage|seq``，用于两侧事件配对。"""
    n = normalize_event(ev)
    return "{}|{}|{}|{}".format(
        n.get("date"), n.get("type"), n.get("stage"),
        n.get("seq") if n.get("seq") is not None else "",
    )


def comparable_fields(ev: dict) -> Dict[str, Any]:
    """取出参与比对的字段（剔除自由文本），供逐字段差异归因。"""
    n = normalize_event(ev)
    return {
        key: value for key, value in n.items()
        if key in EVENT_FIELDS and key not in _COMPARISON_IGNORE
    }
