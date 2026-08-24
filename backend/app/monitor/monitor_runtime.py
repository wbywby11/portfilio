# -*- coding: utf-8 -*-
"""
实盘监控运行时配置：从已发布策略的 live_snapshot 解析资产宇宙、波动率参数与权重上限，
未命中时由调用方回退到 app.monitor.config 全局默认值。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.monitor import config
from app.monitor.mongo_asset_codes import canonical_price_code

# 展示用资产类别顺序
_CLASS_ORDER = ("权益", "固定收益", "大宗商品", "其他")


@dataclass
class MonitorRuntimeConfig:
    """单次监控运行使用的参数（与全局 config 对齐字段语义）。"""

    asset_list: List[str]  # 与行情列、持仓键一致：通常为 Mongo asset_code 原样（如 SH000300_TEST）
    target_vol: float
    vol_trigger_threshold: float
    max_leverage: float
    weight_caps: Dict[str, float]
    risk_budget_both: float = 0.25
    risk_budget_single: float = 0.125
    # 混合动量/反转窗口（None 表示未使用策略覆盖，仅 legacy_runtime 全为 None）
    mom_windows: Optional[Tuple[int, ...]] = None
    posi_windows: Optional[Tuple[int, ...]] = None
    smom_windows: Optional[Tuple[int, ...]] = None
    macd_windows: Optional[Tuple[int, ...]] = None
    macd_long_window: Optional[int] = None
    reversal_windows: Optional[Tuple[int, ...]] = None
    min_history_momentum: Optional[int] = None
    min_history_reversal: Optional[int] = None
    # 主观配置模板：仅按预设调仓日 + 初始化权重，不走混合动量月末映射与波动率重置
    manual_allocation_mode: bool = False
    template_code: str = "risk_budget_target_vol"  # 策略模板类型
    selector_type: Optional[str] = None  # 资产选择器类型（sharpe/hybrid 等），monitor 路由键
    strategy_params: Dict[str, Any] = field(default_factory=dict)  # 策略特有参数透传
    asset_names: Optional[Dict[str, str]] = None  # code→name 映射（来自策略模型/资产主数据）
    trading_costs: Optional[Dict[str, float]] = None   # 策略自带交易费率（代码→单次费率）
    replication_costs: Optional[Dict[str, float]] = None  # 策略自带复制费率（代码→年化费率）


def _parse_json_if_string(val: Any) -> Any:
    if isinstance(val, str) and val.strip().startswith(("{", "[")):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val


def _normalize_parameters(params: Any) -> Dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in params.items():
        out[k] = _parse_json_if_string(v)
    return out


def _float_param(params: Dict[str, Any], key: str) -> Optional[float]:
    v = params.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_int_list(val: Any) -> Optional[List[int]]:
    if val is None:
        return None
    if isinstance(val, (list, tuple)):
        out: List[int] = []
        for x in val:
            try:
                out.append(int(float(x)))
            except (TypeError, ValueError):
                continue
        return out if out else None
    if isinstance(val, str):
        parts = [p.strip() for p in val.replace(";", ",").split(",") if p.strip()]
        out = []
        for p in parts:
            try:
                out.append(int(float(p)))
            except (TypeError, ValueError):
                continue
        return out if out else None
    try:
        return [int(float(val))]
    except (TypeError, ValueError):
        return None


def _overlay_selection_params_from_model(model: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """策略文档顶层保存的动量/反转窗口字段覆盖合并后的 parameters。"""
    if model is None:
        return params
    out = dict(params)
    for key in (
        "momentum_windows",
        "mom_windows",
        "posi_windows",
        "smom_windows",
        "macd_windows",
        "macd_long_window",
        "reversal_windows",
        "min_history_days",
    ):
        v = getattr(model, key, None)
        if v is not None:
            out[key] = v
    return out


def _resolve_selection_windows_from_params(params: Dict[str, Any]) -> Tuple[
    Tuple[int, ...],
    Tuple[int, ...],
    Tuple[int, ...],
    Tuple[int, ...],
    int,
    Tuple[int, ...],
    int,
    int,
]:
    """
    从合并参数解析 MOM/POSI/SMOM/MACD 各 4 档窗口、MACD 长期窗、反转 2 窗、动量/反转最小历史长度。
    缺省与 app.monitor.config / 编制规则一致。
    """
    legacy_mom = _parse_int_list(params.get("momentum_windows"))
    base_mom = legacy_mom or _parse_int_list("20,60,120,250") or [20, 60, 120, 250]
    mom = _parse_int_list(params.get("mom_windows")) or list(base_mom)
    posi = _parse_int_list(params.get("posi_windows")) or list(base_mom)
    smom = _parse_int_list(params.get("smom_windows")) or list(base_mom)
    macd = _parse_int_list(params.get("macd_windows")) or _parse_int_list("40,80,120,160") or [40, 80, 120, 160]
    macd_long_raw = params.get("macd_long_window")
    if macd_long_raw is not None:
        try:
            macd_long = int(float(macd_long_raw))
        except (TypeError, ValueError):
            macd_long = 250
    else:
        macd_long = 250
    rev = _parse_int_list(params.get("reversal_windows")) or _parse_int_list("10,22") or [10, 22]
    if len(rev) != 2:
        rev = [10, 22]
    try:
        mhd_i = int(float(params.get("min_history_days", 260)))
    except (TypeError, ValueError):
        mhd_i = 260
    mx_win = 0
    for lst in (mom, posi, smom, macd):
        if lst:
            mx_win = max(mx_win, max(lst))
    mx_win = max(mx_win, macd_long)
    min_hist_mom = max(mhd_i, mx_win)
    min_hist_rev = max(rev)
    return (
        tuple(mom),
        tuple(posi),
        tuple(smom),
        tuple(macd),
        macd_long,
        tuple(rev),
        min_hist_mom,
        min_hist_rev,
    )


def _pass_through_universe(codes: List[Any]) -> List[str]:
    """策略/快照中的资产标识原样保留（去空、去重、保序），不映射为 12 类中文名。"""
    out: List[str] = []
    seen: set[str] = set()
    for c in codes:
        if c is None:
            continue
        s = str(c).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def normalize_strategy_asset_codes(raw: Any) -> Optional[List[str]]:
    """模型「选择资产」asset_codes：兼容 list/tuple；其它类型返回 None（由调用方回退快照/参数）。"""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if x is not None and str(x).strip()]
    return None


def _asset_names_from_snapshot(snap: Dict[str, Any]) -> List[str]:
    raw = snap.get("asset_codes")
    codes: List[Any] = []
    if isinstance(raw, (list, tuple)):
        codes = list(raw)
    elif isinstance(raw, str) and raw.strip():
        parsed = _parse_asset_codes_param(raw)
        codes = list(parsed) if parsed else []
    return _pass_through_universe(codes)


def _parse_asset_codes_param(raw: Any) -> Optional[List[str]]:
    """解析 parameters 中的资产代码列表（list / JSON 数组字符串 / 逗号分隔）。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        parsed = _parse_json_if_string(raw)
        if isinstance(parsed, list) and parsed:
            return [str(x).strip() for x in parsed if str(x).strip()]
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        return parts if parts else None
    if isinstance(raw, list) and raw:
        return [str(x).strip() for x in raw if str(x).strip()]
    return None


def _asset_names_from_parameters(params: Dict[str, Any]) -> Optional[List[str]]:
    """
    从可变参数中取监控资产列表（原样）。
    键优先级：monitor_asset_codes > universe_asset_codes > live_monitor_asset_codes
    """
    for key in ("monitor_asset_codes", "universe_asset_codes", "live_monitor_asset_codes"):
        codes = _parse_asset_codes_param(params.get(key))
        if codes:
            u = _pass_through_universe(codes)
            return u if u else None
    return None


def _resolve_monitor_asset_list(
    snap: Dict[str, Any],
    params: Dict[str, Any],
    current_asset_codes: Optional[List[str]] = None,
) -> List[str]:
    """
    解析监控底层资产标识（与 Mongo asset_code、行情列一致，原样）：
    1) 模型当前 asset_codes（选择资产）
    2) parameters 中 monitor/universe 类列表
    3) live_snapshot.asset_codes
    若均为空，由 monitor_runtime_from_snapshot 回退为全局 ASSET_LIST（默认监控）。
    """
    if current_asset_codes is not None and len(current_asset_codes) > 0:
        return _pass_through_universe(list(current_asset_codes))
    from_params = _asset_names_from_parameters(params)
    if from_params is not None:
        return from_params
    return _asset_names_from_snapshot(snap)


def _resolve_config_scalar_by_asset_key(
    asset_key: str,
    name_keyed_map: Dict[str, Any],
    default: Any,
    asset_names: Optional[Dict[str, str]] = None,
) -> Any:
    """
    编制规则表（WEIGHT_CAPS / TRADING_COST 等）以中文资产名为键；
    策略模型监控使用 Mongo asset_code 时，需映射到同一数值，否则与 config.py 基准监控不一致。

    查找顺序：
    1. name_keyed_map 直接命中（中文名为键）
    2. asset_names（策略模型/资产主数据 code→name）→ 中文名 → name_keyed_map
    3. 全局 ASSET_CODE_TO_NAME → 中文名 → name_keyed_map
    4. 夏普率 SHARPE_CODE_TO_NAME → 中文名 → name_keyed_map
    5. canonical_price_code 规范化后重试 3 & 4
    6. _TEST 后缀剥离后重试
    7. 返回 default
    """
    if not asset_key:
        return default
    k = str(asset_key).strip()
    if k in name_keyed_map:
        return name_keyed_map[k]
    # 辅助：通过 code_to_name 映射表查找中文名后取值
    def _lookup_via_code_map(code: str) -> Any:
        # 优先使用策略模型的 asset_names（code→name）
        if asset_names and code in asset_names:
            cn = asset_names[code]
            if cn in name_keyed_map:
                return name_keyed_map[cn]
        # 再查全局 12 资产映射
        if code in config.ASSET_CODE_TO_NAME:
            cn = config.ASSET_CODE_TO_NAME[code]
            if cn in name_keyed_map:
                return name_keyed_map[cn]
        # 再查夏普率 18 资产映射
        if code in config.SHARPE_CODE_TO_NAME:
            cn = config.SHARPE_CODE_TO_NAME[code]
            if cn in name_keyed_map:
                return name_keyed_map[cn]
        return None
    # 原始 code 查找
    result = _lookup_via_code_map(k)
    if result is not None:
        return result
    # canonical code 查找
    base = canonical_price_code(k)
    if base != k:
        result = _lookup_via_code_map(base)
        if result is not None:
            return result
    # _TEST 后缀剥离
    if k.endswith("_TEST") and len(k) > len("_TEST"):
        bare = k[: -len("_TEST")]
        result = _lookup_via_code_map(bare)
        if result is not None:
            return result
    return default


def resolve_weight_cap_for_asset(asset_key: str, asset_names: Optional[Dict[str, str]] = None) -> float:
    # 合并全局 + 夏普率权重上限表（夏普率资产优先）
    merged = dict(config.WEIGHT_CAPS)
    merged.update(config.SHARPE_WEIGHT_CAPS)
    v = _resolve_config_scalar_by_asset_key(asset_key, merged, 1.0, asset_names=asset_names)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 1.0


def resolve_trading_cost_for_asset(asset_key: str, asset_names: Optional[Dict[str, str]] = None) -> float:
    # 合并全局 + 夏普率交易费率表
    merged = dict(config.TRADING_COST)
    merged.update(config.SHARPE_TRADING_COST)
    v = _resolve_config_scalar_by_asset_key(asset_key, merged, 0.001, asset_names=asset_names)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.001


def resolve_replication_cost_for_asset(asset_key: str, asset_names: Optional[Dict[str, str]] = None) -> float:
    # 合并全局 + 夏普率复制费率表
    merged = dict(config.REPLICATION_COST)
    merged.update(config.SHARPE_REPLICATION_COST)
    v = _resolve_config_scalar_by_asset_key(asset_key, merged, 0.005, asset_names=asset_names)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.005


def resolve_asset_currency_for_monitor(asset_key: str, asset_names: Optional[Dict[str, str]] = None) -> str:
    # 合并全局 + 夏普率资产货币映射表
    merged = dict(config.ASSET_CURRENCY)
    merged.update(config.SHARPE_ASSET_CURRENCY)
    v = _resolve_config_scalar_by_asset_key(asset_key, merged, "CNH", asset_names=asset_names)
    return str(v) if v is not None else "CNH"


def _merge_weight_caps(asset_list: List[str], params: Dict[str, Any], asset_names: Optional[Dict[str, str]] = None) -> Dict[str, float]:
    caps = {a: resolve_weight_cap_for_asset(a, asset_names=asset_names) for a in asset_list}
    raw = params.get("weight_caps", params.get("max_weight_dict"))
    if isinstance(raw, str):
        raw = _parse_json_if_string(raw)
    if not isinstance(raw, dict):
        return caps
    for key, val in raw.items():
        try:
            w = float(val)
        except (TypeError, ValueError):
            continue
        ks = str(key).strip()
        if ks in caps:
            caps[ks] = w
    return caps


def legacy_runtime() -> MonitorRuntimeConfig:
    return MonitorRuntimeConfig(
        asset_list=list(config.ASSET_LIST),
        target_vol=float(config.TARGET_VOL),
        vol_trigger_threshold=float(config.VOL_TRIGGER_THRESHOLD),
        max_leverage=float(config.MAX_LEVERAGE),
        weight_caps={k: float(v) for k, v in config.WEIGHT_CAPS.items()},
        risk_budget_both=0.25,
        risk_budget_single=0.125,
    )


def config_baseline_eligible_strategy_dict(
    asset_names: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    日常监控准入列表中的「config.py 基准」项（monitor_id=default）。
    与 legacy_runtime / run_init(run_daily) 未绑定策略模型时的全局配置一致，供与实盘策略对比参数与绩效。
    """
    rt = legacy_runtime()
    am = dict(asset_names or {})
    codes: List[str] = []
    for nm in config.ASSET_LIST:
        c = config.ASSET_NAME_TO_CODE.get(nm)
        if c:
            codes.append(c)
    for c in codes:
        if c not in am:
            am[c] = config.ASSET_CODE_TO_NAME.get(c, c)
    labels = live_effective_asset_display_labels(codes, am) or []
    assets_cn = list(rt.asset_list)
    classes = _ordered_asset_classes(assets_cn)
    mw = config.MOMENTUM_WINDOWS
    le_params = {
        "target_vol_pct": round(float(rt.target_vol) * 100, 2),
        "vol_reset_threshold_pct": round(float(rt.vol_trigger_threshold) * 100, 2),
        "max_total_leverage": round(float(rt.max_leverage), 4),
        "asset_classes": classes,
        "mom_windows": ",".join(str(x) for x in mw["MOM"]),
        "posi_windows": ",".join(str(x) for x in mw["POSI"]),
        "smom_windows": ",".join(str(x) for x in mw["SMOM"]),
        "macd_windows": ",".join(str(x) for x in mw["MACD"]),
        "macd_long_window": 250,
        "reversal_windows": ",".join(str(x) for x in config.REVERSAL_WINDOWS),
        "min_history_days": 260,
        "min_history_momentum": int(config.MIN_HISTORY_MOMENTUM),
        "min_history_reversal": int(config.MIN_HISTORY_REVERSAL),
    }
    tail = _short_asset_rollcall(list(labels) if labels else codes)
    le_summary = (
        f"目标波动{rt.target_vol * 100:.1f}% "
        f"重置阈值{rt.vol_trigger_threshold * 100:.1f}% "
        f"· config.py 基准 · 底层：{tail}"
    )
    return {
        "id": "default",
        "name": "系统基准（config.py）",
        "template_code": "risk_budget_target_vol",
        "selector_type": "hybrid",
        "live_version": None,
        "live_effective_date": None,
        "live_effective_summary": le_summary,
        "live_effective_assets": codes,
        "asset_names": am,
        "live_effective_asset_labels": labels,
        "live_effective_params": le_params,
        "is_config_baseline": True,
    }


def monitor_runtime_from_snapshot(
    snap: Dict[str, Any],
    live_volatility_threshold: Optional[float] = None,
    current_parameters: Optional[Dict[str, Any]] = None,
    current_asset_codes: Optional[List[str]] = None,
    model_for_selection: Optional[Any] = None,
    asset_names: Optional[Dict[str, str]] = None,
) -> Optional[MonitorRuntimeConfig]:
    """由 live_snapshot 构建运行时配置；快照无效时返回 None。

    current_parameters 为策略模型当前库里的 parameters，与快照合并时后者覆盖前者键冲突，
    以便编辑器中修改的 target_vol、vol_reset_threshold、monitor_asset_codes 等与监控计算、展示联动。
    current_asset_codes 为模型顶层 asset_codes（表单「选择资产」），优先于 parameters 与快照内 asset_codes。
    model_for_selection 为完整 StrategyModel 时，合并顶层动量/反转窗口字段（与日常监控联动）。
    asset_names 为 code→name 映射（来自策略模型或资产主数据），用于查找编制规则表中的配置值。
    """
    if not isinstance(snap, dict) or not snap:
        return None

    snap_params = _normalize_parameters(snap.get("parameters") or {})
    cur_params = _normalize_parameters(current_parameters or {})
    params = {**snap_params, **cur_params}
    params = _overlay_selection_params_from_model(model_for_selection, params)
    asset_list = _resolve_monitor_asset_list(snap, params, current_asset_codes)
    if not asset_list:
        asset_list = list(config.ASSET_LIST)

    target_vol = _float_param(params, "target_vol")
    if target_vol is None:
        target_vol = float(config.TARGET_VOL)

    # 优先使用合并后 parameters 中的重置阈值（含当前模型编辑结果），再回退顶栏 live_volatility_threshold
    vol_trigger = _float_param(params, "vol_reset_threshold")
    if vol_trigger is None:
        vol_trigger = _float_param(params, "volatility_threshold")
    if vol_trigger is None and live_volatility_threshold is not None:
        vol_trigger = float(live_volatility_threshold)
    if vol_trigger is None:
        vol_trigger = float(config.VOL_TRIGGER_THRESHOLD)

    # 优先读取策略模型保存的 max_leverage（前端/后端强制固化写入），
    # 兼容旧快照中的 max_total_leverage 字段名，再回退全局配置。
    max_leverage = _float_param(params, "max_leverage")
    if max_leverage is None:
        max_leverage = _float_param(params, "max_total_leverage")
    if max_leverage is None:
        max_leverage = float(config.MAX_LEVERAGE)

    # 风险预算固定为编制规则 2/8、1/8，与 app.monitor.config 基准一致；不作为策略模型可变传参
    leg = legacy_runtime()
    rb_both = float(leg.risk_budget_both)
    rb_single = float(leg.risk_budget_single)

    weight_caps = _merge_weight_caps(asset_list, params, asset_names=asset_names)

    mw = _resolve_selection_windows_from_params(params)

    tc = str(snap.get("template_code") or "").strip().lower()
    sel_type = str(snap.get("selector_type") or "").strip().lower() or None
    # 兼容：若快照未存 selector_type，从模型顶层读取
    if not sel_type and model_for_selection:
        sel_type = getattr(model_for_selection, 'selector_type', None)
    manual_allocation_mode = tc in ("manual_allocation", "manual_allocation_strategy")

    if manual_allocation_mode:
        weight_caps = {a: 1.0 for a in asset_list}
        # 主观日常监控：不启用波动率重置；总仓位上限 1（权重和≤100%）
        max_leverage = 1.0
        return MonitorRuntimeConfig(
            asset_list=asset_list,
            target_vol=target_vol,
            vol_trigger_threshold=vol_trigger,
            max_leverage=max_leverage,
            weight_caps=weight_caps,
            risk_budget_both=rb_both,
            risk_budget_single=rb_single,
            mom_windows=mw[0],
            posi_windows=mw[1],
            smom_windows=mw[2],
            macd_windows=mw[3],
            macd_long_window=mw[4],
            reversal_windows=mw[5],
            min_history_momentum=mw[6],
            min_history_reversal=mw[7],
            manual_allocation_mode=manual_allocation_mode,
            template_code=tc or "manual_allocation",
            selector_type=sel_type,
            strategy_params={},
            asset_names=asset_names,
        )

    # 通用路径：所有其他策略（包括 etf_cycle_rotation、risk_parity 等）
    # 不再区分 allocation_only_mode，统一透传 template_code 和 strategy_params
    # 由下游 engine_adapter 动态解析 allocator
    strategy_params: Dict[str, Any] = {}
    for k, v in params.items():
        strategy_params[k] = v

    return MonitorRuntimeConfig(
        asset_list=asset_list,
        target_vol=target_vol,
        vol_trigger_threshold=vol_trigger,
        max_leverage=max_leverage,
        weight_caps=weight_caps,
        risk_budget_both=rb_both,
        risk_budget_single=rb_single,
        mom_windows=mw[0],
        posi_windows=mw[1],
        smom_windows=mw[2],
        macd_windows=mw[3],
        macd_long_window=mw[4],
        reversal_windows=mw[5],
        min_history_momentum=mw[6],
        min_history_reversal=mw[7],
        manual_allocation_mode=False,
        template_code=tc or "vol_scaled_budget",
        selector_type=sel_type,
        strategy_params=strategy_params,
        asset_names=asset_names,
    )


def monitor_runtime_from_model(model: Any) -> Optional[MonitorRuntimeConfig]:
    """
    从 StrategyModel 构建运行时配置。
    未实盘发布、无有效快照时返回 None（调用方使用 legacy_runtime）。
    """
    if not getattr(model, "live_publish_enabled", False):
        return None
    snap = getattr(model, "live_snapshot", None) or {}
    cur_codes = getattr(model, "asset_codes", None)
    codes_list = normalize_strategy_asset_codes(cur_codes)
    # 从模型获取 code→name 映射，优先使用模型配置的资产名称
    an = getattr(model, "asset_names", None)
    asset_names = dict(an) if isinstance(an, dict) and an else None
    return monitor_runtime_from_snapshot(
        snap if isinstance(snap, dict) else {},
        getattr(model, "live_volatility_threshold", None),
        current_parameters=getattr(model, "parameters", None),
        current_asset_codes=codes_list,
        model_for_selection=model,
        asset_names=asset_names,
    )


def _ordered_asset_classes(asset_list: List[str]) -> List[str]:
    found = set()
    for a in asset_list:
        c = config.ASSET_CLASS_MAP.get(a, "")
        if not c:
            base = canonical_price_code(str(a))
            cn = config.ASSET_CODE_TO_NAME.get(base) or config.ASSET_CODE_TO_NAME.get(str(a).strip())
            if cn:
                c = config.ASSET_CLASS_MAP.get(cn, "")
        if c:
            found.add(c)
    ordered: List[str] = []
    for c in _CLASS_ORDER:
        if c in found:
            ordered.append(c)
    for c in sorted(found):
        if c not in ordered:
            ordered.append(c)
    return ordered


def _short_asset_rollcall(names: List[str], max_len: int = 100) -> str:
    """摘要用资产名单，过长时截断并标注总数。"""
    if not names:
        return "—"
    j = "、".join(names)
    if len(j) <= max_len:
        return j
    acc: List[str] = []
    L = 0
    for n in names:
        sep = "、" if acc else ""
        chunk = sep + n
        if L + len(chunk) > max_len - 8:
            return "、".join(acc) + f"…等共{len(names)}项"
        acc.append(n)
        L += len(chunk)
    return j


def resolve_monitor_asset_display_label(
    key: str,
    asset_names: Optional[Dict[str, str]] = None,
) -> str:
    """
    将监控/持仓使用的资产键转为展示名称：全局中文名保持原样；
    否则优先资产主数据（asset_names，键可为代码或去 Mongo 后缀后的代码），再回退 config 映射，最后为键本身。
    """
    if not key:
        return ""
    am = asset_names or {}
    if key in config.ASSET_NAME_TO_CODE:
        return key
    if key in am:
        return am[key]
    base = canonical_price_code(key)
    if base in am:
        return am[base]
    if key.endswith("_TEST") and len(key) > len("_TEST"):
        bare = key[: -len("_TEST")]
        if bare in am:
            return am[bare]
        if bare in config.ASSET_CODE_TO_NAME:
            return config.ASSET_CODE_TO_NAME[bare]
    if base in config.ASSET_CODE_TO_NAME:
        return config.ASSET_CODE_TO_NAME[base]
    if key in config.ASSET_CODE_TO_NAME:
        return config.ASSET_CODE_TO_NAME[key]
    return key


def resolve_asset_class_for_monitor(asset_key: str) -> str:
    """
    将持仓/权重使用的资产键（中文名、标准 asset_code、带 MONGO 后缀的存储码）解析为
    ASSET_CLASS_MAP 中的类别（权益/固定收益/大宗商品）。
    与 resolve_monitor_asset_display_label 的键空间一致；无法识别时返回空字符串。
    """
    if not asset_key:
        return ""
    k = str(asset_key).strip()
    if k in config.ASSET_CLASS_MAP:
        return str(config.ASSET_CLASS_MAP[k])
    base = canonical_price_code(k)
    for code in (k, base):
        if code in config.ASSET_CODE_TO_NAME:
            cn = config.ASSET_CODE_TO_NAME[code]
            cls = config.ASSET_CLASS_MAP.get(cn)
            if cls:
                return str(cls)
    if k.endswith("_TEST") and len(k) > len("_TEST"):
        bare = k[: -len("_TEST")]
        if bare in config.ASSET_CODE_TO_NAME:
            cn = config.ASSET_CODE_TO_NAME[bare]
            cls = config.ASSET_CLASS_MAP.get(cn)
            if cls:
                return str(cls)
    return ""


def live_effective_asset_display_labels(
    assets: Optional[List[str]],
    asset_names: Optional[Dict[str, str]] = None,
) -> Optional[List[str]]:
    if assets is None:
        return None
    return [resolve_monitor_asset_display_label(a, asset_names) for a in assets]


def _flatten_parameters_dict(params: Any) -> Dict[str, Any]:
    """与 live_publish_log_scope.normalize_parameters_to_flat_dict 同逻辑，避免循环 import。"""
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


def live_effective_structured_params(
    live_publish_enabled: bool,
    live_snapshot: Optional[Dict[str, Any]],
    live_volatility_threshold: Optional[float],
    current_parameters: Optional[Dict[str, Any]] = None,
    current_asset_codes: Optional[List[str]] = None,
    model_for_selection: Optional[Any] = None,
    published_only: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    实盘可变参数结构化数据（不含底层资产名单），供监控页单独可视化，
    避免与「底层资产」标签重复堆叠长文案。
    model_for_selection 传入策略模型时，顶层动量/反转窗口字段与快照合并，与监控计算一致。

    published_only=True：仅依据 live_snapshot 内冻结内容解析，不合并当前策略草稿 parameters / 顶层窗口，
    用于「实盘生效参数」展示（仅实盘发布后快照变化才反映到新数字）。
    """
    if not live_publish_enabled or not live_snapshot:
        return None
    snap = live_snapshot if isinstance(live_snapshot, dict) else {}
    if published_only:
        flat = _flatten_parameters_dict(snap.get("parameters") or {})
        codes = normalize_strategy_asset_codes(snap.get("asset_codes"))
        rt = monitor_runtime_from_snapshot(
            snap,
            live_volatility_threshold,
            current_parameters=flat,
            current_asset_codes=codes,
            model_for_selection=None,
        )
    else:
        rt = monitor_runtime_from_snapshot(
            snap,
            live_volatility_threshold,
            current_parameters=current_parameters,
            current_asset_codes=current_asset_codes,
            model_for_selection=model_for_selection,
        )
    if rt is None:
        return None
    assets = list(rt.asset_list)
    classes = _ordered_asset_classes(assets)
    flat_snap = _flatten_parameters_dict(snap.get("parameters") or {})

    if getattr(rt, "manual_allocation_mode", False):
        out: Dict[str, Any] = {"is_manual_allocation": True}
        raw_adj = flat_snap.get("manual_weight_adjustments")
        n = 0
        dates_preview: List[str] = []
        adj_for_api: List[Dict[str, Any]] = []
        if isinstance(raw_adj, list):
            for it in raw_adj:
                if isinstance(it, dict) and it.get("date"):
                    n += 1
                    dval = it["date"]
                    if hasattr(dval, "strftime"):
                        ds = dval.strftime("%Y-%m-%d")
                    else:
                        ds = str(dval).strip()
                    ymd = ds[:10] if len(ds) >= 10 else ds
                    if len(dates_preview) < 5:
                        dates_preview.append(ymd)
                    w_src = it.get("weights")
                    w_flat: Dict[str, float] = {}
                    if isinstance(w_src, dict):
                        for ak, av in w_src.items():
                            sk = str(ak).strip()
                            if not sk:
                                continue
                            try:
                                w_flat[sk] = float(av or 0)
                            except (TypeError, ValueError):
                                w_flat[sk] = 0.0
                    adj_for_api.append(
                        {
                            "date": ymd,
                            "auto_normalize": bool(it.get("auto_normalize")),
                            "weights": w_flat,
                        }
                    )
        adj_for_api.sort(key=lambda x: str(x.get("date") or ""))
        out["manual_weight_adjustments"] = adj_for_api
        out["manual_preset_rebalance_count"] = n
        out["manual_preset_dates_preview"] = "、".join(dates_preview) if dates_preview else "—"
        mw = flat_snap.get("manual_weights")
        mw_out: Dict[str, float] = {}
        if isinstance(mw, dict):
            for ak, av in mw.items():
                sk = str(ak).strip()
                if not sk:
                    continue
                try:
                    mw_out[sk] = float(av or 0)
                except (TypeError, ValueError):
                    mw_out[sk] = 0.0
        if mw_out:
            out["manual_weights"] = mw_out
            try:
                s = sum(float(v or 0) for v in mw_out.values())
                out["manual_initial_weights_sum_pct"] = round(s * 100, 2)
            except (TypeError, ValueError):
                pass
        else:
            out["manual_weights"] = {}
        return out

    out: Dict[str, Any] = {
        "target_vol_pct": round(float(rt.target_vol) * 100, 2),
        "vol_reset_threshold_pct": round(float(rt.vol_trigger_threshold) * 100, 2),
        "max_total_leverage": round(float(rt.max_leverage), 4),
        "asset_classes": classes,
    }
    # 夏普率风险预算策略：实盘参数已固化，日常监控不展示详细参数
    if getattr(rt, "selector_type", "") == "sharpe":
        return out
    # 与 run_daily 使用的 MonitorRuntimeConfig 一致，展示各因子窗口与最小历史长度
    if rt.mom_windows:
        out["mom_windows"] = ",".join(str(x) for x in rt.mom_windows)
        out["posi_windows"] = ",".join(str(x) for x in (rt.posi_windows or rt.mom_windows))
        out["smom_windows"] = ",".join(str(x) for x in (rt.smom_windows or rt.mom_windows))
    if rt.macd_windows:
        out["macd_windows"] = ",".join(str(x) for x in rt.macd_windows)
    if rt.macd_long_window is not None:
        out["macd_long_window"] = int(rt.macd_long_window)
    if rt.reversal_windows:
        out["reversal_windows"] = ",".join(str(x) for x in rt.reversal_windows)
    if rt.min_history_momentum is not None:
        out["min_history_momentum"] = int(rt.min_history_momentum)
    if rt.min_history_reversal is not None:
        out["min_history_reversal"] = int(rt.min_history_reversal)
    if "min_history_days" in flat_snap:
        try:
            out["min_history_days"] = int(float(flat_snap["min_history_days"]))
        except (TypeError, ValueError):
            pass
    return out


def live_effective_display_bundle(
    live_publish_enabled: bool,
    live_snapshot: Optional[Dict[str, Any]],
    live_volatility_threshold: Optional[float],
    current_parameters: Optional[Dict[str, Any]] = None,
    current_asset_codes: Optional[List[str]] = None,
    asset_names: Optional[Dict[str, str]] = None,
    published_only: bool = False,
) -> Tuple[Optional[str], Optional[List[str]]]:
    """
    实盘展示用：返回 (摘要文案, 参与监控计算的资产标识列表，与选择资产/行情列一致)。
    与 monitor_runtime_from_snapshot 解析规则一致（含 parameters / asset_codes 可变传参）。
    摘要中「底层」一段使用资产展示名（asset_names / 全局映射），与列表接口 live_effective_asset_labels 一致。

    published_only=True：仅使用落库 live_snapshot，不合并策略表单草稿。
    """
    if not live_publish_enabled or not live_snapshot:
        return None, None
    snap = live_snapshot if isinstance(live_snapshot, dict) else {}
    if published_only:
        flat = _flatten_parameters_dict(snap.get("parameters") or {})
        codes = normalize_strategy_asset_codes(snap.get("asset_codes"))
        rt = monitor_runtime_from_snapshot(
            snap,
            live_volatility_threshold,
            current_parameters=flat,
            current_asset_codes=codes,
            model_for_selection=None,
        )
    else:
        rt = monitor_runtime_from_snapshot(
            snap,
            live_volatility_threshold,
            current_parameters=current_parameters,
            current_asset_codes=current_asset_codes,
        )
    if rt is None:
        return None, None
    assets = list(rt.asset_list)
    classes = _ordered_asset_classes(assets)
    cls_part = "·".join(classes) if classes else "—"
    tail_labels = live_effective_asset_display_labels(assets, asset_names) or assets
    tail = _short_asset_rollcall(tail_labels)
    if getattr(rt, "manual_allocation_mode", False):
        flat = _flatten_parameters_dict(snap.get("parameters") or {})
        raw_adj = flat.get("manual_weight_adjustments")
        n_adj = len(raw_adj) if isinstance(raw_adj, list) else 0
        summary = (
            f"主观配置 · 总仓位≤100% · {cls_part} · 底层：{tail} · 预设调仓{n_adj}日"
        )
        return summary, assets
    summary = (
        f"目标波动{rt.target_vol * 100:.1f}% "
        f"重置阈值{rt.vol_trigger_threshold * 100:.1f}% "
        f"· {cls_part} · 底层：{tail}"
    )
    return summary, assets


def format_live_effective_summary(
    live_publish_enabled: bool,
    live_snapshot: Optional[Dict[str, Any]],
    live_volatility_threshold: Optional[float],
    current_parameters: Optional[Dict[str, Any]] = None,
    current_asset_codes: Optional[List[str]] = None,
    asset_names: Optional[Dict[str, str]] = None,
    published_only: bool = False,
) -> Optional[str]:
    """供 API 列表/详情展示的短文案；未实盘时返回 None。"""
    s, _ = live_effective_display_bundle(
        live_publish_enabled,
        live_snapshot,
        live_volatility_threshold,
        current_parameters=current_parameters,
        current_asset_codes=current_asset_codes,
        asset_names=asset_names,
        published_only=published_only,
    )
    return s


def slice_prices_df(prices_df: Any, rt: Optional[MonitorRuntimeConfig]) -> Any:
    """按运行时资产列表截取价格列；rt 为 None 时原样返回。"""
    import pandas as pd

    if rt is None or prices_df is None or getattr(prices_df, "empty", True):
        return prices_df
    cols = [c for c in rt.asset_list if c in prices_df.columns]
    if not cols:
        return prices_df
    # 避免整表 .copy()：监控与月度预计算仅读取价格，不原地修改 DataFrame
    try:
        return prices_df.loc[:, cols]
    except Exception:
        return prices_df[cols]
