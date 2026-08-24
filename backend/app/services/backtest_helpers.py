"""回测公共辅助函数 — 从 api/backtests.py 提取的跨端点复用工具函数.

包含：
- 策略类型判断
- 主观策略复制费率构建
- JSON 安全序列化（nan/inf/极端值清理）
- 快照聚合（减少响应体积）
- 交易调仓标签注入
- NAV 序列提取
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ==================== 策略类型判断 ====================

def is_manual_strategy(strategy_type: str) -> bool:
    """主观策略不应用指数编制规则权重上限；仅动量/量化策略需限制。"""
    _st = (strategy_type or "").strip().lower()
    return _st in ("manual_allocation", "manual_allocation_strategy") or "manual" in _st



# ==================== JSON 安全序列化 ====================

# 极端浮点数上限（用于防止手续费、收益率等异常值导致显示/序列化问题）
SANITIZE_FLOAT_ABS_MAX = 1e12

# 回测绩效指标合理范围（数据缺失/不一致时避免回撤、收益率、波动率、卡玛等极端值）
PERF_TOTAL_RETURN_MIN = -1.0
PERF_TOTAL_RETURN_MAX = 10.0
PERF_ANNUAL_VOLATILITY_MAX = 5.0
PERF_MAX_DRAWDOWN_MIN = -1.0
PERF_MAX_DRAWDOWN_MAX = 0.0
PERF_RATIO_ABS_MAX = 50.0
PERF_COMMISSION_ABS_MAX = 1e9  # 单笔手续费绝对值上限


def sanitize_performance_metrics(perf: Dict[str, Any]) -> Dict[str, Any]:
    """对回测绩效指标做合理范围限制与 nan/inf 清理，避免数据缺失或不一致时出现极端值。"""
    if not perf or not isinstance(perf, dict):
        return perf
    out = dict(perf)
    for key in ("total_return", "annual_return"):
        if key in out and out[key] is not None:
            v = safe_float_for_json(out[key], 0.0)
            out[key] = max(PERF_TOTAL_RETURN_MIN, min(PERF_TOTAL_RETURN_MAX, v))
    for key in ("volatility", "annual_volatility"):
        if key in out and out[key] is not None:
            v = safe_float_for_json(out[key], 0.0)
            out[key] = max(0.0, min(PERF_ANNUAL_VOLATILITY_MAX, v))
    if "max_drawdown" in out and out["max_drawdown"] is not None:
        v = safe_float_for_json(out["max_drawdown"], 0.0)
        out["max_drawdown"] = max(PERF_MAX_DRAWDOWN_MIN, min(PERF_MAX_DRAWDOWN_MAX, v))
    for key in ("sharpe_ratio", "calmar_ratio"):
        if key in out and out[key] is not None:
            v = safe_float_for_json(out[key], 0.0)
            out[key] = max(-PERF_RATIO_ABS_MAX, min(PERF_RATIO_ABS_MAX, v))
    return out


def safe_float_for_json(x: Any, default: float = 0.0) -> float:
    """将 inf/nan 转为有限值，避免 JSON 序列化报错。"""
    if x is None:
        return default
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return default
    except (TypeError, ValueError):
        return default
    return float(x)


def cap_extreme_float(v: float, default: float = 0.0) -> float:
    """将 inf/nan/极端大数转为合理范围，避免显示异常。"""
    if not math.isfinite(v):
        return default
    if abs(v) > SANITIZE_FLOAT_ABS_MAX:
        return (SANITIZE_FLOAT_ABS_MAX if v > 0 else -SANITIZE_FLOAT_ABS_MAX)
    return v


def sanitize_dict_for_json(obj: Any, default_float: float = 0.0) -> Any:
    """递归将 dict/list 中的 inf/nan/极端浮点数转为有限值，避免 JSON 序列化及显示异常。支持 numpy 标量。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: sanitize_dict_for_json(v, default_float) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_dict_for_json(v, default_float) for v in obj]
    # 处理 numpy 标量（np.float64 等，isinstance(x, float) 为 False）
    try:
        import numpy as np
        if isinstance(obj, (np.floating, np.integer)):
            v = float(obj)
            if math.isnan(v) or math.isinf(v):
                return default_float if isinstance(obj, np.floating) else 0
            out = v if isinstance(obj, np.floating) else int(obj)
            return cap_extreme_float(out, default_float) if isinstance(obj, np.floating) else out
    except (ImportError, TypeError, ValueError):
        pass
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return default_float
        return cap_extreme_float(obj, default_float)
    return obj


# ==================== 快照聚合（减少响应体积） ====================

def aggregate_snapshots(snapshots: list, max_points: int = 500) -> dict:
    """对快照列表进行聚合处理，减少返回数据量。

    保留策略：
    - 总数 <= max_points 时不做采样，原样返回
    - 超过时：均匀采样 + 保留所有调仓日 + 保留首尾
    """
    total = len(snapshots)
    if total <= max_points:
        return {
            "snapshots": snapshots,
            "total_snapshots": total,
            "aggregated": False,
        }

    import numpy as np

    # 提取调仓日索引
    rebalance_indices = set()
    for i, s in enumerate(snapshots):
        is_reb = s.get("is_rebalance_day") if isinstance(s, dict) else getattr(s, "is_rebalance_day", False)
        if is_reb:
            rebalance_indices.add(i)

    # 均匀采样索引
    uniform_indices = set(np.linspace(0, total - 1, max_points, dtype=int).tolist())

    # 合并索引并排序
    all_indices = sorted(uniform_indices | rebalance_indices | {0, total - 1})

    # 如果合并后仍超过 max_points * 1.5，对调仓日做均匀降采样。
    # 注意：不能用 [:max_points*1.5] 从头截断 —— 日频调仓策略（如类雪球 Delta 对冲）
    # 的调仓日覆盖全部交易日，截断会只保留前段 + 最后一天，
    # 净值曲线中段整体丢失，前端呈现为末日“跳涨”的假象。
    if len(all_indices) > int(max_points * 1.5):
        reb_sorted = sorted(rebalance_indices)
        if len(reb_sorted) > max_points:
            reb_sampled_idx = np.linspace(0, len(reb_sorted) - 1, max_points, dtype=int)
            reb_sampled = {reb_sorted[i] for i in reb_sampled_idx}
        else:
            reb_sampled = rebalance_indices
        all_indices = sorted(uniform_indices | reb_sampled | {0, total - 1})

    sampled = [snapshots[i] for i in all_indices]

    return {
        "snapshots": sampled,
        "total_snapshots": total,
        "aggregated": True,
        "sampled_points": len(sampled),
    }


def apply_snapshot_aggregation(result_data: dict, max_points: int = 500) -> dict:
    """对回测结果 dict 中的 snapshots 字段应用聚合采样，就地修改并返回。

    向响应中注入 _snapshot_meta 字段，告知前端聚合状态：
    - total: 原始快照总数
    - aggregated: 是否做了采样
    - returned: 实际返回的快照数
    """
    if not isinstance(result_data, dict):
        return result_data
    snapshots = result_data.get("snapshots")
    if not snapshots or not isinstance(snapshots, list):
        return result_data
    agg = aggregate_snapshots(snapshots, max_points=max_points)
    result_data["snapshots"] = agg["snapshots"]
    result_data["_snapshot_meta"] = {
        "total": agg["total_snapshots"],
        "aggregated": agg["aggregated"],
        "returned": len(agg["snapshots"]),
    }
    return result_data


# ==================== 交易调仓标签 ====================

def rebalance_label_for_trade(rebalance_type: Optional[str], rebalance_reason: Optional[str]) -> str:
    """根据调仓类型与原因返回交易明细展示用的调仓类型标签。"""
    r = (rebalance_reason or "").strip()
    t = (rebalance_type or "").strip()
    if "期初建仓" in r or (t == "manual_adjustment" and ("期初建仓" in r or r == "")):
        return "初始化仓位"
    if t == "manual_adjustment":
        if "交互式" in r or r == "交互式调仓":
            return "交互式调仓"
        return "预设调仓"
    if t == "vol_reset":
        return "波动率重置"
    if t == "regular" or "周期性" in r:
        return "周期性调仓"
    return "周期性调仓"


def ensure_trades_rebalance_labels(result_data: Dict[str, Any]) -> None:
    """确保 result_data['trades'] 中每条交易都有 rebalance_label。就地修改。"""
    if not isinstance(result_data, dict):
        return
    trades = result_data.get("trades")
    snapshots = result_data.get("snapshots") or []
    if not isinstance(trades, list):
        return
    rebalance_by_date = {}
    for s in snapshots:
        is_reb = s.get("is_rebalance_day") if isinstance(s, dict) else getattr(s, "is_rebalance_day", False)
        if is_reb:
            t = s.get("time") if isinstance(s, dict) else getattr(s, "time", None)
            if t is not None:
                try:
                    key = pd.Timestamp(t).strftime("%Y-%m-%d") if hasattr(pd.Timestamp(t), "strftime") else str(t)[:10]
                    rt = s.get("rebalance_type") if isinstance(s, dict) else getattr(s, "rebalance_type", None)
                    rr = s.get("rebalance_reason") if isinstance(s, dict) else getattr(s, "rebalance_reason", None)
                    rebalance_by_date[key] = (rt, rr)
                except Exception:
                    pass
    for t in trades:
        if isinstance(t, dict) and t.get("rebalance_label") is None:
            tdt = t.get("time")
            key = ""
            if tdt is not None:
                try:
                    key = pd.Timestamp(tdt).strftime("%Y-%m-%d") if hasattr(pd.Timestamp(tdt), "strftime") else str(tdt)[:10]
                except Exception:
                    key = str(tdt)[:10] if tdt else ""
            rt, rr = rebalance_by_date.get(key, (None, None))
            t["rebalance_label"] = rebalance_label_for_trade(rt, rr)


# ==================== NAV 序列提取 ====================

def extract_nav_series(result: Dict[str, Any], initial_nav: float = 1.0) -> Optional[pd.Series]:
    """从回测结果中提取 NAV 序列，并归一化到指定的起始净值。

    Args:
        result: 回测结果字典，包含 snapshots 列表
        initial_nav: 目标起始净值，默认 1.0。组合回测时应传入组合的 initial_nav
                     以确保与 portfolio_service._run_sub_strategy_backtest 行为一致。
    """
    snapshots = result.get("snapshots", [])
    if not snapshots:
        return None
    nav_data = {s.time: s.total_value for s in snapshots}
    series = pd.Series(nav_data).sort_index()
    if len(series) > 0 and series.iloc[0] != 0:
        series = series / series.iloc[0] * initial_nav
    return series
