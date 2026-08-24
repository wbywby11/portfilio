"""walk_diff 递归对比器：黄金基线 vs 本次链路输出。

对比规则：
- float：相对 + 绝对容差取宽（1e-12），NaN == NaN 视为相等；
- dict：键并集逐键对比，VOLATILE_KEYS 中的键跳过；
- list：长度不同直接记 diff，相同则逐元素对比；
- 其它标量：!= 即 diff。

VOLATILE_KEYS 准入标准：与业务数值无关的标识 / 时间戳 / 相对当前日期类字段
才允许剔除；任何净值、权重、绩效指标字段禁止加入。
"""
from __future__ import annotations

import math
from typing import Any, List

FLOAT_RTOL = 1e-12
FLOAT_ATOL = 1e-12

# 易变字段：文档 ObjectId / 落库时间戳 / 执行耗时 / 相对"今天"的倒计时
VOLATILE_KEYS = frozenset({
    "_id",
    "id",
    "record_id",
    "model_id",
    "portfolio_id",
    "portfolio_model_id",
    "strategy_model_id",
    "monitor_id",
    "backtest_record_id",
    "fetch_id",
    "created_at",
    "updated_at",
    "completed_at",
    "published_at",
    "live_published_at",
    "live_effective_date",
    "inception_date",
    "backtest_date",
    "captured_at",
    "execution_time",
    "timestamp",
    "duration_ms",
    "run_id",
    "days_until",  # 相对当前日期的倒计时（monthly_rebalance.days_until）
})


def _float_equal(a: float, b: float) -> bool:
    """浮点相等：NaN==NaN 视为相等，其余相对+绝对容差取宽。"""
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isinf(a) or math.isinf(b):
        return a == b
    return math.isclose(a, b, rel_tol=FLOAT_RTOL, abs_tol=FLOAT_ATOL)


def walk_diff(path: str, before: Any, after: Any, diffs: List[str]) -> None:
    """递归对比 before/after，将差异路径追加进 diffs。

    Args:
        path: 当前节点路径（如 "C2_run_by_model.data.equity_curve[3].value"）
        before: 基线值
        after: 本次值
        diffs: 差异累积列表（原地追加）
    """
    # bool 是 int 子类，先单独判等避免 True==1 混淆
    if isinstance(before, bool) or isinstance(after, bool):
        if before is not after:
            diffs.append(f"{path}: {before!r} != {after!r}")
        return
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        if not _float_equal(float(before), float(after)):
            diffs.append(f"{path}: {before!r} != {after!r}")
        return
    if type(before) is not type(after):
        diffs.append(f"{path}: 类型不同 {type(before).__name__} != {type(after).__name__}")
        return
    if isinstance(before, dict):
        for key in sorted(set(before) | set(after)):
            if key in VOLATILE_KEYS:
                continue
            if key not in before:
                diffs.append(f"{path}.{key}: 基线缺失该键")
            elif key not in after:
                diffs.append(f"{path}.{key}: 本次输出缺失该键")
            else:
                walk_diff(f"{path}.{key}", before[key], after[key], diffs)
        return
    if isinstance(before, list):
        if len(before) != len(after):
            diffs.append(f"{path}: 列表长度不同 {len(before)} != {len(after)}")
            return
        for i, (b, a) in enumerate(zip(before, after)):
            walk_diff(f"{path}[{i}]", b, a, diffs)
        return
    if before != after:
        diffs.append(f"{path}: {before!r} != {after!r}")


def compare(golden: Any, current: Any) -> List[str]:
    """对比黄金基线与本次输出，返回差异路径列表（空列表 = 完全一致）。"""
    diffs: List[str] = []
    walk_diff("$", golden, current, diffs)
    return diffs
