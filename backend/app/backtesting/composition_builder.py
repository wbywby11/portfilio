"""三层 composition 装配的唯一来源.

历史上只有单策略回测入口（``/api/backtests/run``）会根据 ``strategy_params`` 里的
``enable_momentum_selection`` / ``selector_type`` 把选择器接进 ``CompositionPipeline``；
组合回测、日常监控、模拟交易等入口则直接取 ``COMPOSITION_DEFAULTS``，其 ``selector``
恒为 ``None``，导致同一个策略模型在单策略回测里会选资产、在组合里却退化成全池分配
（例如 vol_scaled_budget 的 tag_based 预算源因 ``asset_tags`` 全空而落进 1/N 等分分支）。

本模块把这段推导抽成 :func:`build_strategy_composition`，所有入口共用，确保
"策略模型 → composition" 的映射唯一。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.allocation.builtin_templates import COMPOSITION_DEFAULTS

# 使用 asset_selection_count 决定选择数量的选择器
_USES_N_ASSETS = frozenset({"etf_rotation", "cross_sectional_momentum"})

# 混合动量选择器的别名（统一归一到 momentum_reversal）
_HYBRID_ALIASES = frozenset({"reversal", "momentum_reversal", "hybrid"})

# 采用月末最后一个交易日调仓的分配模型（与指数编制规则一致）
_MONTH_END_ALLOCATORS = frozenset({
    "vol_scaled_budget", "risk_budget_target_vol", "sharpe_risk_budget",
})

# 哨兵：模型显式声明「无控制器」（用于覆盖模板默认控制器，
# 如 vol_scaled_budget 默认 rolling_vol，定标类策略用策略参数 vol_targeting_* 替代控制器）
_NO_CONTROLLER_CODES = frozenset({"none", "null"})


def normalize_controller_code(code: Any) -> Optional[str]:
    """把控制器代码归一为引擎控制器名.

    前端策略建模存的是模板代码（``ctrl_rolling_vol`` / ``ctrl_dual_window_vol``），
    引擎与 CONTROL_REGISTRY 用去前缀名（``rolling_vol`` / ``dual_window_vol``）。
    历史脚本入库的模型可能直接存引擎名，多种形态都必须等价，
    否则前端配置的控制器会被引擎静默忽略。
    """
    if not code:
        return None
    name = str(code)
    if name.startswith("ctrl_"):
        name = name[5:]
    return name or None


@dataclass
class CompositionSpec:
    """装配结果。"""

    composition: Dict[str, Any] = field(default_factory=dict)
    enable_selection: bool = False
    selected_asset_count: Optional[int] = None
    force_month_end: bool = False


def build_strategy_composition(
    strategy_type: str,
    thscodes: List[str],
    strategy_params: Dict[str, Any],
) -> CompositionSpec:
    """根据策略类型与扁平化参数推导 CompositionPipeline 的 composition 配置。

    Args:
        strategy_type: 分配模型 code（如 ``vol_scaled_budget``）
        thscodes: 候选资产池
        strategy_params: ``build_backtest_params()`` 产出的扁平参数

    Returns:
        CompositionSpec，其中 ``composition`` 可直接传给 CompositionPipeline。
    """
    strategy_params = strategy_params or {}
    base_composition = COMPOSITION_DEFAULTS.get(strategy_type, {
        "selector": None, "allocator": strategy_type, "controller": None,
    })
    # 模型级控制器覆盖：模型文档的 controller_code 优先于模板默认 controller。
    # 'none' 哨兵 = 显式声明无控制器（覆盖模板默认，如 vol_scaled_budget 的 rolling_vol）；
    # 其余归一掉前端模板代码的 ctrl_ 前缀，保证与引擎控制器名一致
    raw_ctrl = strategy_params.get("controller_code")
    if raw_ctrl is not None and str(raw_ctrl).strip().lower() in _NO_CONTROLLER_CODES:
        base_composition = {**base_composition, "controller": None}
    else:
        ctrl_override = normalize_controller_code(raw_ctrl)
        if ctrl_override:
            base_composition = {**base_composition, "controller": ctrl_override}

    raw_selector = strategy_params.get("selector_type") or ""
    enable_selection = bool(
        strategy_params.get("enable_momentum_selection", False)
        or (raw_selector and strategy_params.get("asset_selection_count") is not None)
    )
    if not enable_selection:
        return CompositionSpec(composition=dict(base_composition))

    selector_type, n_assets, selected_count, selection_params = _resolve_selector(
        strategy_type, thscodes, strategy_params, raw_selector,
    )

    composition = {
        **base_composition,
        "selector": selector_type,
        "n_assets": n_assets,
        "selection_params": selection_params,
    }
    n_for_alloc = strategy_params.get("n_assets_for_allocation")
    if n_for_alloc is not None and selector_type != "momentum_reversal":
        try:
            composition["n_assets_for_allocation"] = int(n_for_alloc)
        except (TypeError, ValueError):
            pass

    return CompositionSpec(
        composition=composition,
        enable_selection=True,
        selected_asset_count=selected_count,
        force_month_end=strategy_type in _MONTH_END_ALLOCATORS,
    )


def _resolve_selector(
    strategy_type: str,
    thscodes: List[str],
    params: Dict[str, Any],
    raw_selector: str,
):
    """推导选择器 code 与其专属参数。"""
    # 兼容前端 sel_ 前缀
    if raw_selector.startswith("sel_"):
        raw_selector = raw_selector[4:]
    if not raw_selector:
        raw_selector = "sharpe"

    n_total = len(thscodes or [])

    if raw_selector in _HYBRID_ALIASES:
        n_momentum = int(params.get("n_momentum", 7))
        n_reversal = int(params.get("n_reversal", 1))
        n_assets = n_momentum + n_reversal
        selection_params = {
            "min_history_days": params.get("min_history_days", 260),
            "momentum_windows": params.get("momentum_windows", "20,60,120,250"),
            "macd_windows": params.get("macd_windows", "40,80,120,160"),
            "reversal_windows": params.get("reversal_windows", "10,22"),
            "n_momentum": n_momentum,
            "n_reversal": n_reversal,
        }
        # 同分口径：index_rule（编制规则平均排名）/ strict（严格前N名，与原型一致）
        if params.get("tie_rule"):
            selection_params["tie_rule"] = params["tie_rule"]
        # tag_based 预算源：反转用价格序列偏度，反转候选池最小历史 22 日
        if strategy_type in ("vol_scaled_budget", "risk_budget_target_vol"):
            selection_params["use_price_skew"] = True
            selection_params["min_history_reversal"] = 22
        return "momentum_reversal", n_assets, n_assets, selection_params

    if raw_selector == "sharpe":
        _raw = params.get("asset_selection_count")
        n_assets = int(_raw) if _raw is not None else n_total
        selection_params = {
            "min_history_days": params.get("min_history_days", 260),
            "sharp_windows": params.get("sharp_windows")
                or params.get("momentum_windows", "22,65,260"),
            "tie_break_window": params.get("tie_break_window", 22),
        }
        return "sharpe", n_assets, n_assets, selection_params

    # 其他选择器：按各自 schema 精确取参
    selection_params: Dict[str, Any] = {}
    selected_count: Optional[int] = None
    if raw_selector in _USES_N_ASSETS:
        _raw = params.get("asset_selection_count")
        n_assets = int(_raw) if _raw is not None else n_total
        selected_count = n_assets
    else:
        n_assets = n_total

    if raw_selector == "etf_rotation":
        selection_params["sub_strategy"] = params.get("sub_strategy", "volatility")
        selection_params["lookback_days"] = int(params.get("lookback_days", 20))
        selection_params["return_cutoff_pct"] = float(params.get("return_cutoff_pct", 0.2))
        selection_params["bias_threshold"] = float(params.get("bias_threshold", 10.0))
        if "risk_index_code" in params:
            selection_params["risk_index_code"] = params["risk_index_code"]
        if "risk_drop_threshold" in params:
            selection_params["risk_drop_threshold"] = float(params["risk_drop_threshold"])
    elif raw_selector == "cross_sectional_momentum":
        selection_params["momentum_window"] = int(params.get("momentum_window", 20))
    elif raw_selector == "cross_sectional_long_short":
        selection_params["cs_lookback_months"] = int(params.get("cs_lookback_months", 8))
    elif raw_selector == "trend_following":
        selection_params["tf_lookback"] = int(params.get("tf_lookback", 25))
        selection_params["tf_threshold"] = float(params.get("tf_threshold", 0.0))
    elif raw_selector == "etf_discount":
        for k in ("window", "signal_type", "close_signal_type", "enable_tech_filter",
                  "std_filter_mode", "tech_min_pass", "enable_rolling_params",
                  "lookback_months"):
            if k in params:
                selection_params[k] = params[k]

    return raw_selector, n_assets, selected_count, selection_params
