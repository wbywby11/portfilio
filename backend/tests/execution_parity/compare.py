# -*- coding: utf-8 -*-
"""零漂移比对：逐字段 ``abs=0``（float 精确相等），返回差异路径清单.

与 ``tests/regression/compare.py`` 的 ``FLOAT_RTOL = FLOAT_ATOL = 1e-12`` 不同，
本模块**不设任何容差**——P0 的硬约束是「结果逐字段不变」，容差会把
浮点求和顺序变化（正是 S2/S4 最容易引入的漂移）藏起来。

比对规则
--------
- ``dict``：键集合必须完全一致（多出/缺失都算差异），再逐键递归。
- ``list``：长度必须一致，再逐位递归。
- ``float`` / ``int``：要求 ``a == b`` 精确成立；两侧同为 NaN 视为相等
  （NaN != NaN 会误报），单侧 NaN 记为差异。
- ``str`` / ``bool`` / ``None``：要求 ``==``。
- 类型不同：直接记差异，不做隐式转换。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, NamedTuple, Optional, Tuple


class Diff(NamedTuple):
    """一处差异：字段路径 + 基线值 + 实测值 + 绝对差（非数值为 None）."""

    path: str
    golden: Any
    actual: Any
    abs_diff: Optional[float]


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _abs_diff(a: Any, b: Any) -> Optional[float]:
    if _is_num(a) and _is_num(b):
        try:
            return abs(float(a) - float(b))
        except (OverflowError, ValueError):
            return None
    return None


def _walk(golden: Any, actual: Any, path: str, out: List[Diff]) -> None:
    if isinstance(golden, dict):
        if not isinstance(actual, dict):
            out.append(Diff(path, f"<dict>", f"<{type(actual).__name__}>", None))
            return
        gk, ak = set(golden.keys()), set(actual.keys())
        for k in sorted(gk - ak):
            out.append(Diff(f"{path}.{k}", golden[k], "<MISSING>", None))
        for k in sorted(ak - gk):
            out.append(Diff(f"{path}.{k}", "<MISSING>", actual[k], None))
        for k in sorted(gk & ak):
            _walk(golden[k], actual[k], f"{path}.{k}", out)
        return

    if isinstance(golden, list):
        if not isinstance(actual, list):
            out.append(Diff(path, "<list>", f"<{type(actual).__name__}>", None))
            return
        if len(golden) != len(actual):
            out.append(Diff(f"{path}.<len>", len(golden), len(actual), None))
        for i, (g, a) in enumerate(zip(golden, actual)):
            _walk(g, a, f"{path}[{i}]", out)
        return

    if isinstance(golden, bool) or isinstance(actual, bool):
        if golden is not actual:
            out.append(Diff(path, golden, actual, None))
        return

    if _is_num(golden) and _is_num(actual):
        g_nan = math.isnan(float(golden))
        a_nan = math.isnan(float(actual))
        if g_nan and a_nan:
            return
        if g_nan != a_nan or float(golden) != float(actual):
            out.append(Diff(path, golden, actual, _abs_diff(golden, actual)))
        return

    if type(golden) is not type(actual):
        out.append(Diff(path, f"<{type(golden).__name__}>", f"<{type(actual).__name__}>", None))
        return

    if golden != actual:
        out.append(Diff(path, golden, actual, _abs_diff(golden, actual)))


def compare(golden: Any, actual: Any, root: str = "$") -> List[Diff]:
    """返回全部差异（空列表 = 逐字段精确一致）."""
    out: List[Diff] = []
    _walk(golden, actual, root, out)
    return out


def summarize(diffs: List[Diff]) -> Dict[str, Any]:
    """差异摘要：条数、数值型最大 abs 差、按顶层路径分组的条数."""
    numeric = [d.abs_diff for d in diffs if d.abs_diff is not None]
    groups: Dict[str, int] = {}
    for d in diffs:
        top = d.path.split(".", 1)[0]
        groups[top] = groups.get(top, 0) + 1
    return {
        "n_diffs": len(diffs),
        "max_abs_diff": max(numeric) if numeric else 0.0,
        "by_top_path": dict(sorted(groups.items())),
    }


def format_diffs(diffs: List[Diff], limit: int = 40) -> str:
    """可读差异清单（默认只打印前 ``limit`` 条，避免刷屏）."""
    lines = []
    for d in diffs[:limit]:
        extra = f" abs={d.abs_diff:.17g}" if d.abs_diff is not None else ""
        lines.append(f"  {d.path}: golden={d.golden!r} actual={d.actual!r}{extra}")
    if len(diffs) > limit:
        lines.append(f"  ... 另有 {len(diffs) - limit} 条差异未打印")
    return "\n".join(lines)


def compare_subtree(
    golden: Dict[str, Any],
    actual: Dict[str, Any],
    subtree: str,
) -> Tuple[List[Diff], Dict[str, Any]]:
    """只比对基线中的某一棵子树（供分路径的 pytest 用例使用）."""
    g = golden.get(subtree)
    a = actual.get(subtree)
    if g is None:
        raise KeyError(f"基线中不存在子树: {subtree}")
    if a is None:
        raise KeyError(f"实测结果中不存在子树: {subtree}")
    diffs = compare(g, a, root=f"$.{subtree}")
    return diffs, summarize(diffs)
