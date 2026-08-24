"""
策略模型服务层

职责：策略模型 CRUD 与参数聚合（resolve_full_params/build_backtest_params）。
已按职责拆分的兄弟服务：
- 回测记录 → backtest_service.py
- 实盘发布 → live_publish_service.py
- 参数版本/快照 → param_version_service.py
"""
import json
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from bson import ObjectId

from app.config.database import Database
from app.models.strategy_model import StrategyModel, ModelStatus
from app.services.asset_service import AssetService
from app.services.model_template_service import ModelTemplateService
from app.monitor.live_publish_log_scope import (
    collect_asset_codes_from_scoped_diff,
    compute_monitor_scoped_diff,
    drop_live_version_from_scoped_diff,
    extract_monitor_scoped_from_model,
    filter_monitor_scoped_diff_for_subjective_template,
    rewrite_resolved_asset_list_diff_for_display,
    summarize_monitor_scoped_diff_zh,
)


def _merge_model_asset_name_maps(
    model_before: Any,
    model_after: Any,
) -> Dict[str, str]:
    """合并前后模型的 asset_names，供底层资产展示名解析。"""
    out: Dict[str, str] = {}
    for m in (model_before, model_after):
        if m is None:
            continue
        an = getattr(m, "asset_names", None)
        if isinstance(an, dict):
            for k, v in an.items():
                if v is not None and str(v).strip():
                    out[str(k)] = str(v).strip()
    return out


# ---------------------------------------------------------------------------
# 选择器顶层字段清单（用于 resolve_full_params 聚合）
# ---------------------------------------------------------------------------
_SELECTOR_TOP_LEVEL_FIELDS = (
    "enable_momentum_selection",
    "selector_type",
    "asset_selection_count",
    "min_history_days",
    "momentum_windows",
    "mom_windows",
    "posi_windows",
    "smom_windows",
    "macd_windows",
    "macd_long_window",
    "reversal_windows",
    "sharp_windows",
    "tie_break_window",
)


def resolve_full_params(model) -> Dict[str, Any]:
    """将 StrategyModel 的散落参数聚合为结构化三层对象。

    返回格式::

        {
            "allocator": { ... },   # 分配器参数（parameters dict 去掉 selector_parameters）
            "selector": {            # 选择器参数（顶层字段 + selector_parameters 合并）
                "enabled": bool,
                "type": str | None,
                "params": { ... },
            },
            "controller": {          # 控制器
                "enabled": bool,
                "code": str | None,
                "params": { ... },
            },
        }

    此方法只做读取聚合，不修改 model。
    """
    # ── allocator ──
    raw_params = dict(getattr(model, "parameters", None) or {})
    sel_params_in_params = raw_params.pop("selector_parameters", None)
    allocator = raw_params

    # ── selector ──
    sel_dict: Dict[str, Any] = {}
    sel_enabled = bool(getattr(model, "enable_momentum_selection", False))
    sel_type = getattr(model, "selector_type", None)
    # 规范化旧别名：hybrid/reversal -> momentum_reversal（真实选择器注册名），
    # 确保前端按 'sel_' + type 能匹配到真实模板（sel_momentum_reversal）
    if sel_type in ("hybrid", "reversal"):
        sel_type = "momentum_reversal"
    # 从顶层字段收集
    for field in _SELECTOR_TOP_LEVEL_FIELDS:
        v = getattr(model, field, None)
        if v is not None:
            sel_dict[field] = v
    # 合并 parameters.selector_parameters（新架构优先）
    if isinstance(sel_params_in_params, dict) and sel_params_in_params:
        sel_dict.update(sel_params_in_params)
    # 聚合视图中的 selector_type 也同步为规范名，避免前端读到旧别名
    if sel_dict.get("selector_type") in ("hybrid", "reversal"):
        sel_dict["selector_type"] = "momentum_reversal"
    selector = {
        "enabled": sel_enabled,
        "type": sel_type,
        "params": sel_dict,
    }

    # ── controller ──
    ctrl_code = getattr(model, "controller_code", None)
    ctrl_params = getattr(model, "controller_parameters", None)
    # 'none' 哨兵 = 显式声明无控制器（覆盖模板默认），聚合视图按禁用展示
    ctrl_disabled = ctrl_code is not None and str(ctrl_code).strip().lower() in ("none", "null")
    controller = {
        "enabled": bool(ctrl_code) and not ctrl_disabled,
        "code": None if ctrl_disabled else ctrl_code,
        "params": {} if ctrl_disabled else (dict(ctrl_params) if isinstance(ctrl_params, dict) else {}),
    }

    return {
        "allocator": allocator,
        "selector": selector,
        "controller": controller,
    }


def build_backtest_params(
    model,
    overrides: Optional[Dict[str, Any]] = None,
    model_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """统一组装回测 strategy_params，合并 allocator + selector + controller 参数。

    所有回测入口（run_backtest_by_model / portfolio_service / agent_tools）都应
    通过此函数获取 strategy_params，以确保参数来源唯一、不遗漏。

    Args:
        model: StrategyModel 实例
        overrides: 请求级覆盖参数（如 n_momentum, reversal_windows 等）
        model_data: 原始 MongoDB 文档（用于回退读取模型字段）

    Returns:
        扁平化的 strategy_params 字典，可直接放入 BacktestRequest.strategy_params
    """
    overrides = overrides or {}

    # ── 1. allocator 基础参数 ──
    base = dict(getattr(model, "parameters", None) or {})
    # 选择器参数单独处理：既可嵌在 parameters.selector_parameters 里（策略模型编辑器
    # 的存法），也可散落在模型顶层字段。此处先取出嵌套字典，稍后与顶层字段合并，
    # 不能直接丢弃 —— 否则 n_momentum/n_reversal/各窗口参数会全部失效。
    nested_sel_params = base.pop("selector_parameters", None)
    if not isinstance(nested_sel_params, dict):
        nested_sel_params = {}

    # ── 2. 选择器参数注入 ──
    sel_enabled = bool(
        getattr(model, "enable_momentum_selection", False)
        or (model_data and model_data.get("enable_momentum_selection", False))
    )
    sel_type = (
        getattr(model, "selector_type", None)
        or (model_data and model_data.get("selector_type"))
    )

    if sel_enabled or sel_type:
        base["enable_momentum_selection"] = True
        if sel_type:
            base["selector_type"] = sel_type

        # 嵌套的选择器参数先铺开（顶层字段优先级更高，随后覆盖）
        for k, v in nested_sel_params.items():
            if v is not None:
                base[k] = v

        # 从模型顶层字段注入选择器参数（回退到 model_data）
        for field in _SELECTOR_TOP_LEVEL_FIELDS:
            if field in ("enable_momentum_selection", "selector_type"):
                continue  # 已单独处理
            v = getattr(model, field, None)
            if v is None and model_data:
                v = model_data.get(field)
            if v is not None:
                base[field] = v

        # 保留原始子字典：CompositionPipeline 会从 selector_parameters 二次读取，
        # 用于覆盖 composition["selection_params"] 中的同名项
        merged_sel_params = dict(nested_sel_params)
        for field in _SELECTOR_TOP_LEVEL_FIELDS:
            if field in ("enable_momentum_selection", "selector_type"):
                continue
            if field in base:
                merged_sel_params[field] = base[field]
        if merged_sel_params:
            base["selector_parameters"] = merged_sel_params

    # multi_signal 策略（如 trend_cross_sectional）无 selector_type，但
    # Pipeline._run_multi_signal 仍需从 selector_parameters 读 tf/cs 参数；
    # 未启用选择分支时从嵌套字典/模型顶层聚合字段回退保留
    if "selector_parameters" not in base:
        fallback_sel = dict(nested_sel_params)
        model_sel_field = getattr(model, "selector_parameters", None) or (
            model_data and model_data.get("selector_parameters")
        )
        if isinstance(model_sel_field, dict):
            for k, v in model_sel_field.items():
                fallback_sel.setdefault(k, v)
        if fallback_sel:
            base["selector_parameters"] = fallback_sel

    # ── 3. 控制器参数注入 ──
    ctrl_code = getattr(model, "controller_code", None) or (model_data and model_data.get("controller_code"))
    if ctrl_code:
        # 'none' 哨兵 = 显式声明无控制器（覆盖模板默认 controller，
        # 定标类策略用策略参数 vol_targeting_* 替代控制器），不注入控制器参数
        if str(ctrl_code).strip().lower() in ("none", "null"):
            base["controller_code"] = "none"
        else:
            # 注入 controller_code：composition_builder 据此覆盖模板默认 controller
            base["controller_code"] = ctrl_code
            # 派生 vol_control_type：统一走归一函数（去 ctrl_ 前缀），保证 CONTROL_REGISTRY 可解析
            from app.backtesting.composition_builder import normalize_controller_code
            vol_ctrl_type = (
                (model_data and model_data.get("vol_control_type"))
                or getattr(model, "vol_control_type", None)
            )
            if not vol_ctrl_type:
                vol_ctrl_type = normalize_controller_code(ctrl_code)
            if vol_ctrl_type:
                base["vol_control_type"] = vol_ctrl_type

            ctrl_params = getattr(model, "controller_parameters", None) or (
                model_data and model_data.get("controller_parameters")
            ) or {}
            if isinstance(ctrl_params, dict) and ctrl_params:
                base["controller_parameters"] = dict(ctrl_params)
                if vol_ctrl_type:
                    for k, v in ctrl_params.items():
                        base[k] = v

    # ── 4. 波动率阈值重置 ──
    vol_thresh = overrides.get("vol_reset_threshold")
    if vol_thresh is None:
        vol_thresh = (
            getattr(model, "vol_reset_threshold", None)
            or base.get("vol_reset_threshold")
            or base.get("vol_trigger_threshold")
            or (model_data and (
                model_data.get("vol_reset_threshold")
                or (model_data.get("parameters") or {}).get("vol_reset_threshold")
                or (model_data.get("parameters") or {}).get("vol_trigger_threshold")
            ))
        )
    if vol_thresh is not None:
        try:
            base["vol_reset_threshold"] = float(vol_thresh)
        except (TypeError, ValueError):
            base["vol_reset_threshold"] = 0.06
    else:
        # 仅当策略配置了控制器或已启用波动率重置时才注入默认值
        # 避免纯分配策略（如 risk_parity，无 controller）被污染携带 vol_reset_threshold
        _has_ctrl = bool(ctrl_code)
        _has_vol_cfg = bool(
            base.get("enable_vol_reset")
            or base.get("vol_trigger_threshold")
        )
        if _has_ctrl or _has_vol_cfg:
            base["vol_reset_threshold"] = 0.06
        # 否则不注入 —— 策略没有波动率重置，不应携带此参数

    if overrides.get("enable_vol_reset") is not None:
        base["enable_vol_reset"] = overrides["enable_vol_reset"]

    # ── 5. 请求级覆盖（最高优先级） ──
    _REQUEST_OVERRIDE_KEYS = (
        "n_momentum", "n_reversal", "reversal_windows",
        "momentum_windows", "macd_windows", "sharp_windows",
        "tie_break_window", "min_history_days",
        "asset_selection_count", "selector_type",
        "enable_momentum_selection", "n_assets_for_allocation",
    )
    for key in _REQUEST_OVERRIDE_KEYS:
        if key in overrides and overrides[key] is not None:
            base[key] = overrides[key]

    return base


def _strip_non_editable_monitor_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """风险预算与编制规则一致，由监控引擎固定，不作为策略模型可变传参持久化。"""
    if not isinstance(params, dict):
        return params
    out = dict(params)
    out.pop("risk_budget_both", None)
    out.pop("risk_budget_single", None)
    return out


# ---------------------------------------------------------------------------
# Schema-Driven 参数净化：只保留模板 schema 声明的参数 + 运行时必要字段
# ---------------------------------------------------------------------------

# 运行时必要字段白名单（非 schema 参数但系统执行时需要）
_RUNTIME_PARAM_WHITELIST = frozenset({
    "manual_weight_adjustments",  # 主观配置预设调仓记录
    "selector_parameters",        # 选择器动态参数（前端注入）
    "weight_caps",                # 资产权重约束配置
    "max_weight_dict",            # 资产权重约束（旧名兼容）
    "manual_weights",             # 主观权重配置
    "execution_delay",            # 模型级执行延迟覆盖（Pipeline 调度声明）
    "signal_timing",              # 模型级信号时点覆盖（prev_close/execution_bar）
    "preserve_price_gaps",        # 缺日保真（信号计算保留品种缺日 NaN，数据源层消费）
    "inception_weights",          # 模型级期初建仓权重（指数基日满仓口径）
    "inception_weights_auto_normalize",  # 期初建仓权重是否归一化
})


def _get_schema_param_names(template_code: str) -> Optional[set]:
    """根据 template_code 获取其 schema 声明的参数名集合。
    
    Returns:
        参数名集合，或 None（未知模板 / 加载失败时）。
    """
    from app.allocation.strategy_manifest import get_class_paths
    
    class_path = get_class_paths().get(template_code)
    if not class_path:
        return None
    
    try:
        mod_path, cls_name = class_path.rsplit(".", 1)
        mod = __import__(mod_path, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        schema = cls.get_param_schema()
        return {p.name for p in schema.params}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "获取模板 %s schema 参数失败: %s", template_code, e
        )
        return None


def _sanitize_params_by_schema(
    params: Dict[str, Any],
    template_code: str,
) -> Dict[str, Any]:
    """根据模板 schema 定义，只保留 schema 声明的参数 + 运行时必要字段。
    
    这是参数管理的核心净化函数，确保存储的 parameters 不包含：
    - 前端误注入的无关参数
    - 历史残留的污染数据
    - 其他策略泄漏的参数
    
    Args:
        params: 待净化的参数字典
        template_code: 策略模板代码
        
    Returns:
        净化后的参数字典（仅包含 schema 声明 + 运行时白名单中的参数）
    """
    if not isinstance(params, dict):
        return params
    
    schema_names = _get_schema_param_names(template_code)
    if schema_names is None:
        # 未知模板或加载失败，不干预
        return params
    
    # 保留：schema 声明的参数 + 运行时白名单
    kept = {
        k: v for k, v in params.items()
        if k in schema_names or k in _RUNTIME_PARAM_WHITELIST
    }
    return kept


_RISK_BUDGET_TARGET_VOL_CODES = frozenset({"risk_budget_target_vol", "risk_budget_vol_target"})
_MANUAL_ALLOCATION_TEMPLATE_CODES = frozenset({"manual_allocation", "manual_allocation_strategy"})
_SHARPE_RISK_BUDGET_TEMPLATE_CODES = frozenset({"sharpe_risk_budget"})


def _normalize_selector_type(model_dict: Dict[str, Any]) -> None:
    """规范化 selector_type：去除 sel_ 前缀，统一映射为真实选择器注册名。

    前端可能发送 'sel_sharpe' / 'sharpe' / 'sel_momentum_reversal' 等，
    存储时统一去除 sel_ 前缀；旧别名 hybrid/reversal 统一映射为
    momentum_reversal（SELECTION_REGISTRY 中的真实注册名，与前端模板
    sel_momentum_reversal 对应），避免存入不存在的 'hybrid' 导致
    前端按模板 code 匹配失败、选择器参数无法回填。
    """
    sel = model_dict.get("selector_type") or ""
    if not sel:
        return
    # 去除 sel_ 前缀
    if sel.startswith("sel_"):
        sel = sel[4:]
    # 旧别名统一映射为真实选择器注册名
    if sel in ("hybrid", "reversal"):
        sel = "momentum_reversal"
    model_dict["selector_type"] = sel


def _is_risk_budget_target_vol_template(template_code: Optional[str]) -> bool:
    return (template_code or "") in _RISK_BUDGET_TARGET_VOL_CODES


def _is_manual_allocation_template(template_code: Optional[str]) -> bool:
    return (template_code or "") in _MANUAL_ALLOCATION_TEMPLATE_CODES


def _is_sharpe_risk_budget_template(template_code: Optional[str]) -> bool:
    return (template_code or "") in _SHARPE_RISK_BUDGET_TEMPLATE_CODES


def _apply_manual_allocation_fixed_parameters(params: Dict[str, Any]) -> None:
    """主观配置：日常监控不使用的参数固定为产品默认。"""
    params["max_leverage"] = 1
    params["auto_normalize"] = False
    params["fill_missing"] = "zero"
    params["target_vol"] = 0.05
    params["vol_reset_threshold"] = 0.06
    params["enable_vol_reset"] = False


def _enforce_manual_allocation_monitor_fixed_on_dict(model_dict: Dict[str, Any]) -> None:
    if not _is_manual_allocation_template(model_dict.get("template_code")):
        return
    params = dict(model_dict.get("parameters") or {})
    _apply_manual_allocation_fixed_parameters(params)
    model_dict["parameters"] = params
    model_dict["min_history_days"] = 260
    model_dict["momentum_windows"] = "20,60,120,250"
    model_dict["mom_windows"] = "20,60,120,250"
    model_dict["posi_windows"] = "20,60,120,250"
    model_dict["smom_windows"] = "20,60,120,250"
    model_dict["macd_windows"] = "40,80,120,160"
    model_dict["macd_long_window"] = 250
    model_dict["reversal_windows"] = "10,22"


def _enforce_risk_budget_target_vol_fixed_on_dict(model_dict: Dict[str, Any]) -> None:
    """风险预算目标波动率：固定最小历史 260、波动重置阈值 0.06、回看期 260、并列决胜 22。"""
    if not _is_risk_budget_target_vol_template(model_dict.get("template_code")):
        return
    params = dict(model_dict.get("parameters") or {})
    params["lookback_days"] = 260
    params["vol_reset_threshold"] = 0.06
    params["enable_vol_reset"] = True
    model_dict["parameters"] = params
    model_dict["min_history_days"] = 260
    model_dict["tie_break_window"] = 22


def _enforce_sharpe_risk_budget_fixed_on_dict(model_dict: Dict[str, Any]) -> None:
    """夏普率风险预算策略：固定所有核心参数，确保与原型 step1/step2/step3 完全一致。

    固化值（与原型对齐）：
    - target_vol=0.05, max_leverage=4.0, select_count=13
    - vol_windows='22,65,130', sharp_windows='22,65,260'
    - tie_break_window=22, min_history_days=260
    - enable_vol_reset=True, vol_reset_threshold=0.06, vol_trigger_threshold=0.06
    - monitor_start_days=60
    - selector_type='sharpe', asset_selection_count=13
    """
    if not _is_sharpe_risk_budget_template(model_dict.get("template_code")):
        return
    params = dict(model_dict.get("parameters") or {})
    # 波动率/风控参数
    params["target_vol"] = 0.05
    params["max_leverage"] = 4.0
    params["select_count"] = 13
    params["vol_windows"] = "22,65,130"
    params["sharp_windows"] = "22,65,260"
    params["enable_vol_reset"] = True
    params["vol_reset_threshold"] = 0.06
    params["vol_trigger_threshold"] = 0.06
    params["monitor_start_days"] = 60
    params["min_history_days"] = 260
    model_dict["parameters"] = params
    # 顶层字段（资产选择策略相关）
    model_dict["min_history_days"] = 260
    model_dict["tie_break_window"] = 22
    model_dict["selector_type"] = "sharpe"
    model_dict["asset_selection_count"] = 13
    model_dict["sharp_windows"] = "22,65,260"
    model_dict["momentum_windows"] = "22,65,260"
    model_dict["enable_momentum_selection"] = True


def _merge_strategy_parameters_for_update(
    existing: Optional[StrategyModel],
    update_data: Dict[str, Any],
    template_code: Optional[str] = None,
) -> Dict[str, Any]:
    """合并更新参数与已有参数，并按 schema 净化。
    
    Args:
        existing: 已有模型
        update_data: 本次更新数据
        template_code: 模板代码（用于 schema 净化）
    """
    base = dict(getattr(existing, "parameters", None) or {}) if existing else {}
    if isinstance(update_data.get("parameters"), dict):
        base.update(update_data["parameters"])
    merged = _strip_non_editable_monitor_params(base)
    
    # Schema-Driven 净化：只保留模板 schema 声明的参数 + 运行时必要字段
    tpl_code = template_code or update_data.get("template_code") or (
        getattr(existing, "template_code", None) if existing else None
    )
    if tpl_code:
        merged = _sanitize_params_by_schema(merged, tpl_code)
    
    return dict(merged) if isinstance(merged, dict) else {}


def _float_weight(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _sync_manual_allocation_weights_to_asset_codes(
    parameters: Dict[str, Any],
    new_asset_codes: List[Any],
) -> Dict[str, Any]:
    """
    主观配置：底层资产变更时，初始化权重与预设调仓日权重与 asset_codes 对齐。
    移除已删除资产的键；新增资产补 0（小数权重）。
    """
    params = dict(parameters or {})
    codes = [
        str(c).strip()
        for c in (new_asset_codes or [])
        if c is not None and str(c).strip()
    ]
    if not codes:
        return params

    mw_raw = params.get("manual_weights")
    if isinstance(mw_raw, dict):
        params["manual_weights"] = {c: _float_weight(mw_raw.get(c)) for c in codes}

    mwa = params.get("manual_weight_adjustments")
    parsed: Any = mwa
    if isinstance(mwa, str):
        try:
            parsed = json.loads(mwa)
        except (TypeError, ValueError):
            parsed = None
    if isinstance(parsed, list):
        new_list: List[Any] = []
        for item in parsed:
            if not isinstance(item, dict):
                new_list.append(item)
                continue
            row = dict(item)
            w = row.get("weights")
            if isinstance(w, dict):
                row["weights"] = {c: _float_weight(w.get(c)) for c in codes}
            new_list.append(row)
        params["manual_weight_adjustments"] = new_list

    return params


class StrategyModelService:
    """策略模型服务 - 策略配置管理
    
    职责：
    1. 管理策略模型的 CRUD 操作
    2. 存储策略配置（模板、参数、资产池、调仓频率等）
    
    注意：
    - 回测记录查询/保存与回测请求转换请使用 BacktestService
    - 实盘发布相关操作请使用 LivePublishService
    - 参数版本快照请使用 ParamVersionService
    """
    
    def __init__(self):
        self._db = None
        self._collection = None
        self._backtest_collection = None
        self._live_change_collection = None
        self._live_monitoring_collection = None
        self._param_version_collection = None
        self.asset_service = AssetService()
        self.template_service = ModelTemplateService()

    async def _enrich_asset_name_map_from_db(
        self,
        base: Dict[str, str],
        scoped_diff: Dict[str, Dict[str, Any]],
    ) -> Dict[str, str]:
        """用资产主数据补全展示名（策略 asset_names 未覆盖或键不一致时）。"""
        codes = collect_asset_codes_from_scoped_diff(scoped_diff)
        if not codes:
            return base
        fetched = await self.asset_service.resolve_display_names_for_codes(codes)
        out = dict(base)
        for k, v in (fetched or {}).items():
            if v and str(v).strip():
                sk = str(k).strip()
                prev = out.get(sk)
                if prev is None or not str(prev).strip():
                    out[sk] = str(v).strip()
        return out
    
    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            from app.config.collections import COL_STRATEGY_MODELS
            self._collection = self.db[COL_STRATEGY_MODELS]
        return self._collection

    @property
    def backtest_collection(self):
        if self._backtest_collection is None:
            from app.config.collections import COL_BACKTEST_RECORDS
            self._backtest_collection = self.db[COL_BACKTEST_RECORDS]
        return self._backtest_collection

    @property
    def live_change_collection(self):
        if self._live_change_collection is None:
            from app.config.collections import COL_STRATEGY_LIVE_CHANGE_LOGS
            self._live_change_collection = self.db[COL_STRATEGY_LIVE_CHANGE_LOGS]
        return self._live_change_collection

    @property
    def live_monitoring_collection(self):
        if self._live_monitoring_collection is None:
            from app.config.collections import COL_STRATEGY_LIVE_MONITORING_RECORDS
            self._live_monitoring_collection = self.db[COL_STRATEGY_LIVE_MONITORING_RECORDS]
        return self._live_monitoring_collection

    @property
    def param_version_collection(self):
        if self._param_version_collection is None:
            from app.config.collections import COL_STRATEGY_PARAM_VERSIONS
            self._param_version_collection = self.db[COL_STRATEGY_PARAM_VERSIONS]
        return self._param_version_collection
    
    async def create_model(self, model: StrategyModel) -> str:
        """创建模型"""
        model_dict = model.dict(by_alias=True, exclude={'id'})
        if isinstance(model_dict.get("parameters"), dict):
            model_dict["parameters"] = _strip_non_editable_monitor_params(model_dict["parameters"])
            # Schema-Driven 净化：只保留模板 schema 声明的参数 + 运行时必要字段
            tpl_code = model_dict.get("template_code")
            if tpl_code:
                model_dict["parameters"] = _sanitize_params_by_schema(model_dict["parameters"], tpl_code)
        _enforce_risk_budget_target_vol_fixed_on_dict(model_dict)
        _enforce_manual_allocation_monitor_fixed_on_dict(model_dict)
        _enforce_sharpe_risk_budget_fixed_on_dict(model_dict)
        _normalize_selector_type(model_dict)

        # 投资组合：自动计算 asset_codes 为子策略并集
        if model_dict.get("is_portfolio") and model_dict.get("sub_strategies"):
            all_codes = set()
            for sub in model_dict["sub_strategies"]:
                sub_model = await self.get_model(sub.get("model_id", ""))
                if sub_model:
                    all_codes.update(sub_model.asset_codes)
            model_dict["asset_codes"] = sorted(list(all_codes))

        result = await self.collection.insert_one(model_dict)
        model_id = str(result.inserted_id)
        # 创建初始参数版本 v1
        try:
            saved_model = await self.get_model(model_id)
            if saved_model:
                from app.services.param_version_service import ParamVersionService
                await ParamVersionService().create_param_version(
                    model_id, saved_model, change_summary="初始创建"
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "创建初始参数版本失败 model_id=%s: %s", model_id, e
            )
        return model_id
    
    async def get_model(self, model_id: str) -> Optional[StrategyModel]:
        """获取单个模型"""
        data = await self.collection.find_one({"_id": ObjectId(model_id)})
        if data:
            data['_id'] = str(data['_id'])
            return StrategyModel(**data)
        return None

    async def resolve_sub_strategies(
        self, portfolio_model: StrategyModel
    ) -> List[Tuple[StrategyModel, float]]:
        """解析投资组合的子策略列表，返回 (子策略模型, 配置权重) 元组列表"""
        result = []
        for sub in portfolio_model.sub_strategies:
            sub_model = await self.get_model(sub.get("model_id", ""))
            if sub_model:
                weight = float(sub.get("weight", 0))
                result.append((sub_model, weight))
        return result
    
    async def list_models(
        self,
        status: Optional[ModelStatus] = None,
        template_code: Optional[str] = None,
        rebalance_frequency: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        include_portfolio: bool = False,
    ) -> List[StrategyModel]:
        """查询模型列表（默认排除组合模型 is_portfolio=True）"""
        query = {}
        if not include_portfolio:
            query["is_portfolio"] = {"$ne": True}
        if status:
            query["status"] = status
        if template_code:
            query["template_code"] = template_code
        if rebalance_frequency:
            query["rebalance_frequency"] = rebalance_frequency
        
        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        models = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            models.append(StrategyModel(**doc))
        
        return models
    
    async def update_model(self, model_id: str, update_data: Dict[str, Any]) -> bool:
        """更新模型"""
        if isinstance(update_data.get("parameters"), dict):
            update_data["parameters"] = _strip_non_editable_monitor_params(update_data["parameters"])
        change_source = update_data.pop("_change_source", "strategy")
        change_operator = update_data.pop("_change_operator", None)
        existing_model = await self.get_model(model_id)
        tpl_code = update_data.get("template_code")
        if tpl_code is None and existing_model is not None:
            tpl_code = getattr(existing_model, "template_code", None)
        
        # Schema-Driven 净化：对非特殊模板，直接净化 parameters
        if isinstance(update_data.get("parameters"), dict) and tpl_code:
            if not (
                _is_risk_budget_target_vol_template(str(tpl_code))
                or _is_sharpe_risk_budget_template(str(tpl_code))
                or _is_manual_allocation_template(str(tpl_code))
            ):
                update_data["parameters"] = _sanitize_params_by_schema(
                    update_data["parameters"], tpl_code
                )
        
        if _is_risk_budget_target_vol_template(str(tpl_code or "")):
            update_data["min_history_days"] = 260
            update_data["tie_break_window"] = 22
            if isinstance(update_data.get("parameters"), dict):
                merged_params = _merge_strategy_parameters_for_update(existing_model, update_data)
                merged_params["lookback_days"] = 260
                merged_params["vol_reset_threshold"] = 0.06
                merged_params["enable_vol_reset"] = True
                update_data["parameters"] = merged_params
            else:
                # 不整包替换 parameters，避免仅改名称等非参数字段时误标实盘快照过期
                update_data["parameters.lookback_days"] = 260
                update_data["parameters.vol_reset_threshold"] = 0.06
                update_data["parameters.enable_vol_reset"] = True
        if _is_sharpe_risk_budget_template(str(tpl_code or "")):
            update_data["min_history_days"] = 260
            update_data["tie_break_window"] = 22
            update_data["selector_type"] = "sharpe"
            update_data["asset_selection_count"] = 13
            update_data["sharp_windows"] = "22,65,260"
            update_data["momentum_windows"] = "22,65,260"
            update_data["enable_momentum_selection"] = True
            if isinstance(update_data.get("parameters"), dict):
                merged_params = _merge_strategy_parameters_for_update(existing_model, update_data)
                merged_params["target_vol"] = 0.05
                merged_params["max_leverage"] = 4.0
                merged_params["select_count"] = 13
                merged_params["vol_windows"] = "22,65,130"
                merged_params["sharp_windows"] = "22,65,260"
                merged_params["enable_vol_reset"] = True
                merged_params["vol_reset_threshold"] = 0.06
                merged_params["vol_trigger_threshold"] = 0.06
                merged_params["monitor_start_days"] = 60
                merged_params["min_history_days"] = 260
                update_data["parameters"] = merged_params
            else:
                update_data["parameters.target_vol"] = 0.05
                update_data["parameters.max_leverage"] = 4.0
                update_data["parameters.select_count"] = 13
                update_data["parameters.vol_windows"] = "22,65,130"
                update_data["parameters.enable_vol_reset"] = True
                update_data["parameters.vol_reset_threshold"] = 0.06
                update_data["parameters.vol_trigger_threshold"] = 0.06
                update_data["parameters.monitor_start_days"] = 60
        if _is_manual_allocation_template(str(tpl_code or "")) and (
            "parameters" in update_data
            or "template_code" in update_data
            or "asset_codes" in update_data
        ):
            merged_params = _merge_strategy_parameters_for_update(existing_model, update_data)
            new_ac = update_data.get("asset_codes")
            if isinstance(new_ac, list):
                merged_params = _sync_manual_allocation_weights_to_asset_codes(
                    merged_params, new_ac
                )
                # 去掉已移除资产在 asset_names 中的条目，避免展示名与底层资产不一致
                if existing_model is not None and "asset_names" not in update_data:
                    an = dict(getattr(existing_model, "asset_names", None) or {})
                    keep = {str(x).strip() for x in new_ac if x is not None and str(x).strip()}
                    update_data["asset_names"] = {
                        str(k).strip(): v
                        for k, v in an.items()
                        if str(k).strip() in keep
                    }
            _apply_manual_allocation_fixed_parameters(merged_params)
            update_data["parameters"] = merged_params
            update_data["min_history_days"] = 260
            update_data["momentum_windows"] = "20,60,120,250"
            update_data["mom_windows"] = "20,60,120,250"
            update_data["posi_windows"] = "20,60,120,250"
            update_data["smom_windows"] = "20,60,120,250"
            update_data["macd_windows"] = "40,80,120,160"
            update_data["macd_long_window"] = 250
            update_data["reversal_windows"] = "10,22"
        if existing_model and existing_model.live_publish_enabled:
            sensitive_keys = {"asset_codes", "parameters", "rebalance_frequency", "template_code"}
            if any(k in update_data for k in sensitive_keys):
                update_data["live_snapshot_outdated"] = True

        _normalize_selector_type(update_data)
        update_data['updated_at'] = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(model_id)},
            {"$set": update_data}
        )
        if result.modified_count > 0 and existing_model and existing_model.live_publish_enabled:
            updated_model = await self.get_model(model_id)
            if not updated_model:
                return result.modified_count > 0
            before_scoped = extract_monitor_scoped_from_model(existing_model)
            after_scoped = extract_monitor_scoped_from_model(updated_model)
            scoped_diff = compute_monitor_scoped_diff(before_scoped, after_scoped)
            scoped_diff = filter_monitor_scoped_diff_for_subjective_template(
                scoped_diff, getattr(updated_model, "template_code", None)
            )
            scoped_diff = drop_live_version_from_scoped_diff(scoped_diff)
            if scoped_diff:
                names = _merge_model_asset_name_maps(existing_model, updated_model)
                names = await self._enrich_asset_name_map_from_db(names, scoped_diff)
                scoped_diff = rewrite_resolved_asset_list_diff_for_display(scoped_diff, names)
                summary_zh = summarize_monitor_scoped_diff_zh(scoped_diff)
                # 延迟 import：LivePublishService 依赖本模块，避免顶层循环 import
                from app.services.live_publish_service import LivePublishService
                await LivePublishService(model_service=self).log_live_change(
                    model_id=model_id,
                    action="strategy_update",
                    source=change_source,
                    operator=change_operator,
                    live_version=existing_model.live_version,
                    before={
                        "asset_codes": existing_model.asset_codes,
                        "parameters": existing_model.parameters,
                        "rebalance_frequency": existing_model.rebalance_frequency,
                    },
                    after={
                        "asset_codes": update_data.get("asset_codes", updated_model.asset_codes),
                        "parameters": update_data.get("parameters", updated_model.parameters),
                        "rebalance_frequency": update_data.get(
                            "rebalance_frequency", updated_model.rebalance_frequency
                        ),
                    },
                    change_summary=summary_zh or None,
                    monitor_scoped_changes=scoped_diff,
                )
        # 参数变更时自动创建参数版本快照
        if result.modified_count > 0:
            _PARAM_RELATED_KEYS = {
                "parameters", "selector_type", "controller_code",
                "controller_parameters", "enable_momentum_selection",
                "asset_codes", "asset_selection_count", "min_history_days",
                "momentum_windows", "sharp_windows",
            }
            if any(k in update_data for k in _PARAM_RELATED_KEYS):
                try:
                    updated_for_version = await self.get_model(model_id)
                    if updated_for_version:
                        from app.services.param_version_service import ParamVersionService
                        pv_service = ParamVersionService()
                        change_summary = pv_service.build_param_change_summary(
                            existing_model, updated_for_version
                        )
                        await pv_service.create_param_version(
                            model_id, updated_for_version,
                            change_summary=change_summary,
                        )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        "创建参数版本快照失败 model_id=%s: %s", model_id, e
                    )
        return result.modified_count > 0
    
    async def delete_model(self, model_id: str) -> bool:
        """
        删除模型及其关联的回测记录
        
        Args:
            model_id: 模型ID
            
        Returns:
            是否删除成功
        """
        # 先检查模型是否存在
        model = await self.get_model(model_id)
        if not model:
            return False
        
        # 删除所有关联的回测记录
        await self.backtest_collection.delete_many({"model_id": model_id})
        
        # 级联清理监控侧残留（孤儿引用会导致前端反复 404）：
        # 监控状态（monitor_id = 模型ID）+ 监测策略条目（source_ref = 模型ID）
        db = self.collection.database
        await db["monitor_states"].delete_many({"monitor_id": model_id})
        await db["monitored_strategies"].delete_many(
            {"source_ref": model_id, "source_type": {"$in": ["system_strategy", "portfolio"]}}
        )
        
        # 删除模型
        result = await self.collection.delete_one({"_id": ObjectId(model_id)})
        return result.deleted_count > 0
