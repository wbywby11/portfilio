# -*- coding: utf-8 -*-
"""
日常监控「实盘发布记录」用：从策略模型解析与监控运行时一致的生效参数、底层资产与窗口，
用于写入变更日志的 monitor_scoped_changes（仅这些字段参与对比）。
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, Optional

from app.monitor.monitor_runtime import (
    monitor_runtime_from_snapshot,
    normalize_strategy_asset_codes,
    _overlay_selection_params_from_model,
    resolve_monitor_asset_display_label,
)

# 主观配置：实盘发布记录中不展示与日常监控无关的对比项
_SUBJECTIVE_TEMPLATE_CODES = frozenset({"manual_allocation", "manual_allocation_strategy"})
SUBJECTIVE_MONITOR_SCOPED_DIFF_KEYS_TO_DROP = frozenset(
    {
        "target_vol",
        "vol_trigger_threshold",
        "vol_reset_threshold",
        "volatility_threshold",
        "max_total_leverage",
        "mom_windows",
        "posi_windows",
        "smom_windows",
        "macd_windows",
        "macd_long_window",
        "reversal_windows",
        "momentum_windows",
        "min_history_days",
        "min_history_momentum",
        "min_history_reversal",
        "live_volatility_threshold",
        "enable_vol_reset",
        "fill_missing",
        "auto_normalize",
        "max_leverage",
        "weight_caps",
        "max_weight_dict",
        "tie_break_window",
    }
)


def filter_monitor_scoped_diff_for_subjective_template(
    diff: Dict[str, Dict[str, Any]],
    template_code: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """主观策略：从变更明细中去掉量化/波动相关键，仅保留资产与主观权重类。"""
    if not diff or (template_code or "") not in _SUBJECTIVE_TEMPLATE_CODES:
        return diff
    return {k: v for k, v in diff.items() if k not in SUBJECTIVE_MONITOR_SCOPED_DIFF_KEYS_TO_DROP}

# 实盘发布记录：仅对比「上次快照 → 本次发布」时关心的字段（不含调仓模式等）
LIVE_PUBLISH_MONITOR_KEYS = frozenset(
    {
        "resolved_asset_list",
        "target_vol",
        "vol_trigger_threshold",
        "max_total_leverage",
        "weight_caps",
        "mom_windows",
        "posi_windows",
        "smom_windows",
        "macd_windows",
        "macd_long_window",
        "reversal_windows",
        "min_history_momentum",
        "min_history_reversal",
        "live_volatility_threshold",
    }
)


def _json_safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _json_safe(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, float):
        return round(v, 10)
    if isinstance(v, Decimal):
        try:
            return round(float(v), 10)
        except (TypeError, ValueError, OverflowError):
            return str(v)
    return v


def normalize_parameters_to_flat_dict(params: Any) -> Dict[str, Any]:
    """
    将 parameters 统一为扁平 dict。
    兼容表单/历史数据中的 { items: [{ name, value }] }，否则 target_vol 等只在 items 里、
    与扁平快照逐键对比时会漏检（表现为仅版本号有变更）。
    """
    if not isinstance(params, dict):
        return {}
    items = params.get("items")
    if isinstance(items, list):
        flat: Dict[str, Any] = {}
        for it in items:
            if isinstance(it, dict) and "name" in it and "value" in it:
                flat[str(it["name"])] = it["value"]
        for k, v in params.items():
            if k != "items":
                flat[k] = v
        return flat
    return dict(params)


def _norm_cmp(v: Any) -> Any:
    """用于判断两值是否「对日志而言」相同。"""
    if v is None:
        return None
    if isinstance(v, Decimal):
        try:
            return round(float(v), 6)
        except (TypeError, ValueError, OverflowError):
            return str(v)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        try:
            return round(float(v), 6)
        except (TypeError, ValueError, OverflowError):
            return str(v)
    if isinstance(v, dict):
        try:
            return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)
        except TypeError:
            return str(v)
    if isinstance(v, (list, tuple)):
        return tuple(_norm_cmp(x) for x in v)
    if isinstance(v, str) and "," in v:
        # 窗口类 "20, 60, 120" 与 "20,60,120" 视为相同
        parts = [p.strip() for p in v.split(",") if p.strip()]
        return ",".join(parts)
    return v


def _mode_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).lower()
    if "manual" in s:
        return "manual"
    if "auto" in s or s == "auto":
        return "auto"
    return str(v)


def _win_tup(t: Optional[tuple]) -> Optional[str]:
    if not t:
        return None
    return ",".join(str(x) for x in t)


def _runtime_to_scoped_core(rt: Any) -> Dict[str, Any]:
    """监控运行时配置 → 与日志对比用的核心字段（资产、波动杠杆、窗口）。"""
    return {
        "resolved_asset_list": list(rt.asset_list),
        "target_vol": float(rt.target_vol),
        "vol_trigger_threshold": float(rt.vol_trigger_threshold),
        "max_total_leverage": float(rt.max_leverage),
        "weight_caps": _json_safe(dict(rt.weight_caps)),
        "mom_windows": _win_tup(rt.mom_windows),
        "posi_windows": _win_tup(rt.posi_windows),
        "smom_windows": _win_tup(rt.smom_windows),
        "macd_windows": _win_tup(rt.macd_windows),
        "macd_long_window": int(rt.macd_long_window) if rt.macd_long_window is not None else None,
        "reversal_windows": _win_tup(rt.reversal_windows),
        "min_history_momentum": int(rt.min_history_momentum)
        if rt.min_history_momentum is not None
        else None,
        "min_history_reversal": int(rt.min_history_reversal)
        if rt.min_history_reversal is not None
        else None,
    }


def merge_parameters_with_top_level_windows(model: Any, parameters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """与监控运行时一致：将策略文档顶层动量/反转窗口写入 parameters 再参与解析。"""
    p = normalize_parameters_to_flat_dict(parameters)
    return _overlay_selection_params_from_model(model, p)


def extract_monitor_scoped_from_published_snapshot(
    snap: Optional[Dict[str, Any]],
    live_volatility_threshold: Optional[float],
    model_for_overlay: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    依据落库的 live_snapshot.parameters（冻结内容）+ 可选的顶层窗口覆盖（与 monitor_runtime 一致）。
    model_for_overlay 传当前 StrategyModel 时，可把仅存在文档顶层的 mom_windows 等并入解析，
    避免「快照里无窗口键 → 仅用默认」与发布后 effective 状态不一致导致 diff 为空。
    首次发布时 snap 为空则返回 {}。
    """
    if not snap or not isinstance(snap, dict) or not snap:
        return {}
    snap = dict(snap)
    if not isinstance(snap.get("parameters"), dict):
        snap["parameters"] = {}
    snap["parameters"] = normalize_parameters_to_flat_dict(snap.get("parameters"))
    codes = normalize_strategy_asset_codes(snap.get("asset_codes"))
    # 从模型获取 asset_names（code→name 映射）
    an = getattr(model_for_overlay, "asset_names", None) if model_for_overlay else None
    _asset_names = dict(an) if isinstance(an, dict) and an else None
    rt = monitor_runtime_from_snapshot(
        snap,
        live_volatility_threshold,
        current_parameters=snap["parameters"],
        current_asset_codes=codes,
        model_for_selection=model_for_overlay,
        asset_names=_asset_names,
    )
    if rt is None:
        return {}
    out = _runtime_to_scoped_core(rt)
    out["live_volatility_threshold"] = live_volatility_threshold
    return out


def align_scoped_for_live_publish(d: Dict[str, Any]) -> Dict[str, Any]:
    """仅保留实盘发布对比关心的键（缺省为 None，便于与上次快照对齐）。"""
    return {k: d.get(k) for k in sorted(LIVE_PUBLISH_MONITOR_KEYS)}


def extract_monitor_scoped_from_model(model: Any) -> Dict[str, Any]:
    """
    与日常监控运行时一致：合并 live_snapshot、当前 parameters、顶层 asset_codes、顶层窗口覆盖。
    """
    snap = getattr(model, "live_snapshot", None) or {}
    if not isinstance(snap, dict):
        snap = {}
    if not snap:
        snap = {"parameters": normalize_parameters_to_flat_dict(getattr(model, "parameters", None)) or {}}
    else:
        snap = dict(snap)
        if not isinstance(snap.get("parameters"), dict):
            snap["parameters"] = {}
        else:
            snap["parameters"] = normalize_parameters_to_flat_dict(snap.get("parameters"))
    codes = normalize_strategy_asset_codes(getattr(model, "asset_codes", None))
    # 从模型获取 asset_names（code→name 映射）
    an = getattr(model, "asset_names", None)
    _asset_names = dict(an) if isinstance(an, dict) and an else None
    rt = monitor_runtime_from_snapshot(
        snap,
        getattr(model, "live_volatility_threshold", None),
        current_parameters=normalize_parameters_to_flat_dict(getattr(model, "parameters", None)),
        current_asset_codes=codes,
        model_for_selection=model,
        asset_names=_asset_names,
    )
    if rt is None:
        return {
            "live_publish_enabled": bool(getattr(model, "live_publish_enabled", False)),
            "live_volatility_threshold": getattr(model, "live_volatility_threshold", None),
            "live_rebalance_mode": _mode_str(getattr(model, "live_rebalance_mode", None)),
        }

    out: Dict[str, Any] = {
        "live_publish_enabled": bool(getattr(model, "live_publish_enabled", False)),
        "live_volatility_threshold": getattr(model, "live_volatility_threshold", None),
        "live_rebalance_mode": _mode_str(getattr(model, "live_rebalance_mode", None)),
        **_runtime_to_scoped_core(rt),
    }
    return out


def drop_live_version_from_scoped_diff(
    diff: Optional[Dict[str, Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    """
    实盘版本号仅作为变更日志文档顶层的 live_version 字段，表示该次发布记录；
    不参与 monitor_scoped_changes，避免与参数/资产/权重等重复展示或单独成条。
    """
    if not diff:
        return {}
    return {k: v for k, v in diff.items() if k != "live_version"}


def compute_monitor_scoped_diff(
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    keys = set(before.keys()) | set(after.keys())
    out: Dict[str, Dict[str, Any]] = {}
    for k in sorted(keys):
        b, a = before.get(k), after.get(k)
        if _norm_cmp(b) != _norm_cmp(a):
            out[k] = {"old": _json_safe(b), "new": _json_safe(a)}
    return out


def _diff_flat_parameter_dicts(
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """对两个已展平的 parameters dict 做全键并集 diff。"""
    out: Dict[str, Dict[str, Any]] = {}
    keys = set(before.keys()) | set(after.keys())
    for k in sorted(keys):
        b, a = before.get(k), after.get(k)
        if _norm_cmp(b) != _norm_cmp(a):
            out[k] = {"old": _json_safe(b), "new": _json_safe(a)}
    return out


def _parameters_from_snap(raw: Any) -> Dict[str, Any]:
    """从快照取出 parameters，兼容非 dict / None。"""
    if isinstance(raw, dict):
        return normalize_parameters_to_flat_dict(raw)
    return {}


def compute_snapshot_frozen_monitor_diff(
    old_snap: Dict[str, Any],
    new_snap: Dict[str, Any],
    model_before: Any,
    model_after: Any,
    live_vol_before: Optional[float],
    live_vol_after: Optional[float],
) -> Dict[str, Dict[str, Any]]:
    """
    基于「上次落库快照 vs 本次即将写入的快照」对比。

    1) **plain**：仅对两份快照里 parameters 展平后逐键对比——与 Mongo 冻结内容一致，避免仅依赖 overlay
       时 before/after 被算成相同（实盘发布日志仍以顶层 live_version 标记该次发布，明细可为空）。
    2) **merged**：merge_parameters_with_top_level_windows 后再 diff，补全「仅顶层文档有、旧快照 parameters 未写入」的窗口等。
    plain 与 merged 并集，同键以 merged 结果覆盖（更贴近运行时生效值）。
    """
    out: Dict[str, Dict[str, Any]] = {}
    old_snap = old_snap or {}
    new_snap = new_snap or {}

    old_codes = normalize_strategy_asset_codes(old_snap.get("asset_codes"))
    new_codes = normalize_strategy_asset_codes(new_snap.get("asset_codes"))
    if _norm_cmp(old_codes) != _norm_cmp(new_codes):
        out["resolved_asset_list"] = {
            "old": _json_safe(list(old_codes or [])),
            "new": _json_safe(list(new_codes or [])),
        }

    plain_old = _parameters_from_snap(old_snap.get("parameters"))
    plain_new = _parameters_from_snap(new_snap.get("parameters"))
    plain_diff = _diff_flat_parameter_dicts(plain_old, plain_new)
    out.update(plain_diff)

    before_m = merge_parameters_with_top_level_windows(model_before, plain_old)
    after_m = merge_parameters_with_top_level_windows(model_after, plain_new)
    merged_diff = _diff_flat_parameter_dicts(before_m, after_m)
    for k, v in merged_diff.items():
        out[k] = v

    if _norm_cmp(live_vol_before) != _norm_cmp(live_vol_after):
        out["live_volatility_threshold"] = {
            "old": _json_safe(live_vol_before),
            "new": _json_safe(live_vol_after),
        }
    return out


def merge_runtime_and_snapshot_diff(
    runtime_diff: Dict[str, Dict[str, Any]],
    snapshot_diff: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    合并运行时 diff 与「上次落库快照 vs 本次快照」的逐键差异。

    快照逐键结果后写入并覆盖同名字段：冻结 parameters / asset_codes 是权威来源；
    运行时解析在顶层窗口 overlay 下可能把「上次冻结 vs 本次冻结」算成无差异（plain diff 仍有），
    若运行时优先会错误覆盖快照 diff。因此同键以 snapshot_diff 为准。
    """
    merged = dict(runtime_diff)
    merged.update(snapshot_diff)
    return merged


def _coerce_asset_code_list(v: Any) -> list:
    """将日志里的 old/new 转为代码列表（兼容 list/tuple/JSON 反序列化）。"""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if x is not None and str(x).strip()]
    return []


def collect_asset_codes_from_scoped_diff(diff: Optional[Dict[str, Dict[str, Any]]]) -> list:
    """
    从 monitor_scoped_changes 中收集所有可能用到的资产代码，供主数据补全展示名。
    （resolved_asset_list / 权重类 dict / 预设调仓内 weights 键）
    """
    if not diff:
        return []
    codes: set = set()

    def _add_list(val: Any) -> None:
        if isinstance(val, (list, tuple)):
            for x in val:
                s = str(x).strip() if x is not None else ""
                if s:
                    codes.add(s)

    def _add_dict_side(val: Any) -> None:
        obj = val
        if isinstance(val, str):
            try:
                obj = json.loads(val)
            except (TypeError, ValueError):
                return
        if isinstance(obj, dict):
            for k in obj:
                s = str(k).strip()
                if s:
                    codes.add(s)

    def _add_adjustments_side(val: Any) -> None:
        arr = val
        if isinstance(val, str):
            try:
                arr = json.loads(val)
            except (TypeError, ValueError):
                return
        if not isinstance(arr, list):
            return
        for item in arr:
            if not isinstance(item, dict):
                continue
            w = item.get("weights")
            if isinstance(w, dict):
                for k in w:
                    s = str(k).strip()
                    if s:
                        codes.add(s)

    for key, pair in diff.items():
        if not isinstance(pair, dict):
            continue
        if key == "resolved_asset_list":
            _add_list(pair.get("old"))
            _add_list(pair.get("new"))
        elif key in ("manual_weights", "weight_caps", "max_weight_dict"):
            _add_dict_side(pair.get("old"))
            _add_dict_side(pair.get("new"))
        elif key == "manual_weight_adjustments":
            _add_adjustments_side(pair.get("old"))
            _add_adjustments_side(pair.get("new"))
    return sorted(codes)


def rewrite_resolved_asset_list_diff_for_display(
    diff: Dict[str, Dict[str, Any]],
    asset_names: Optional[Dict[str, str]],
) -> Dict[str, Dict[str, Any]]:
    """
    将 resolved_asset_list 从「整表 old/new 代码列表」改为仅展示增减的中文名：
    old 列：移除：…；new 列：新增：…。纯顺序调整且无增减时 new 列为说明文案。
    """
    if not diff or "resolved_asset_list" not in diff:
        return diff
    pair = diff.get("resolved_asset_list")
    if not isinstance(pair, dict):
        return diff
    old_raw, new_raw = pair.get("old"), pair.get("new")
    old_list = _coerce_asset_code_list(old_raw)
    new_list = _coerce_asset_code_list(new_raw)
    if not old_list and not new_list:
        return diff
    old_set, new_set = set(old_list), set(new_list)
    removed = [x for x in old_list if x not in new_set]
    added = [x for x in new_list if x not in old_set]
    am = asset_names or {}

    out = dict(diff)
    if not removed and not added:
        out["resolved_asset_list"] = {
            "old": "—",
            "new": "仅调整顺序，无增减",
        }
        return out

    def _labels(codes: list) -> list:
        return [resolve_monitor_asset_display_label(c, am) for c in codes]

    rlab, alab = _labels(removed), _labels(added)
    out["resolved_asset_list"] = {
        "old": ("移除：" + "、".join(rlab)) if rlab else "—",
        "new": ("新增：" + "、".join(alab)) if alab else "—",
    }
    return out


def summarize_monitor_scoped_diff_zh(diff: Dict[str, Dict[str, Any]]) -> str:
    """短中文摘要，供 change_summary 或列表展示。"""
    if not diff:
        return ""
    labels = {
        "resolved_asset_list": "底层资产",
        "target_vol": "目标波动",
        "vol_trigger_threshold": "波动重置阈值",
        "vol_reset_threshold": "波动重置阈值",
        "volatility_threshold": "波动率阈值",
        "max_total_leverage": "总杠杆上限",
        "max_leverage": "最大杠杆",
        "weight_caps": "资产权重约束",
        "max_weight_dict": "资产权重约束",
        "mom_windows": "MOM窗口",
        "posi_windows": "POSI窗口",
        "smom_windows": "SMOM窗口",
        "macd_windows": "MACD窗口",
        "macd_long_window": "MACD长期窗",
        "reversal_windows": "反转窗口",
        "momentum_windows": "动量窗口(legacy)",
        "min_history_days": "最小历史长度",
        "min_history_momentum": "动量最小历史",
        "min_history_reversal": "反转最小历史",
        "live_volatility_threshold": "实盘波动阈值",
        "live_rebalance_mode": "调仓模式",
        "live_publish_enabled": "实盘发布",
        "enable_vol_reset": "启用波动重置",
        "fill_missing": "缺失值填充",
        "auto_normalize": "保存时归一化",
        "manual_weights": "初始化权重",
        "manual_weight_adjustments": "预设调仓",
        "lookback_days": "回看天数",
        "tie_break_window": "并列决胜窗口",
        "rebalance_frequency": "调仓频率",
        "selector_type": "选择器类型",
    }
    parts = []
    for k in sorted(diff.keys()):
        if k == "live_version":
            continue
        if k == "resolved_asset_list":
            pair = diff[k]
            if isinstance(pair, dict):
                o, n = pair.get("old"), pair.get("new")
                if isinstance(o, str) and isinstance(n, str):
                    segs = []
                    for s in (o.strip(), n.strip()):
                        if s and s != "—":
                            segs.append(s)
                    if segs:
                        parts.append("；".join(segs))
                        continue
        lab = labels.get(k, k)
        parts.append(lab)
    if not parts:
        return ""
    body = "；".join(parts)
    if len(diff) == 1 and "resolved_asset_list" in diff:
        return body
    return body + " 已变更"
