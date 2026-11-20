# -*- coding: utf-8 -*-
"""发布冻结快照：构建、指纹与回放。

发布即冻结的落地点：发布时把运行口径字段固化为 published_snapshot，
实盘发布再复制为 live_snapshot。下游（组合引用、回测、绩效、日常监控）
统一读快照，避免受发布后草稿字段变化影响。
"""
import hashlib
import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Optional

from app.backtesting.schedule import parse_declared_vol_reset_policy
from app.models.strategy_model import StrategyModel
from app.monitor.live_publish_log_scope import merge_parameters_with_top_level_windows
from app.services.strategy_fingerprint import normalize_codes, normalize_fingerprint_payload

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 发布冻结快照
# ---------------------------------------------------------------------------
# 策略快照：发布时刻决定运行口径的全部配置字段（名称/描述等展示字段不进入快照）
_STRATEGY_SNAPSHOT_FIELDS = (
    "template_code",
    "selector_type",
    "asset_codes",
    "asset_names",
    "rebalance_frequency",
    "enable_momentum_selection",
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
    "controller_code",
    "controller_parameters",
    "structured_params",
    "initial_nav",
)

# 注意：vol_reset_policy 由策略类派生（StrategyModel 无同名字段），只写入快照，
# 不进 _STRATEGY_SNAPSHOT_FIELDS。后者被 apply_published_snapshot 反向用于
# 回填模型，派生字段写回 model 会造出一个 pydantic 未声明的属性。


def _declared_vol_reset_policy(model: StrategyModel) -> Dict[str, bool]:
    """从策略类的 get_execution_schedule() 取波控三键声明.

    vol_reset_policy 属于运行口径，但 StrategyModel 没有同名字段，只能由策略类
    派生。读不到（类未注册 / 不可无参实例化 / 未声明）时返回空字典，语义是
    「策略未声明」，消费方按各自默认值走；类加载或调用失败记 warning，避免把
    实现故障静默成「未声明」。
    """
    code = str(getattr(model, "template_code", "") or "").strip()
    if not code:
        return {}
    from app.allocation.strategy_manifest import resolve_class_safe

    cls = resolve_class_safe(code)
    if cls is None:
        logger.warning("发布快照: 策略类未注册，vol_reset_policy 未冻结 template_code=%s", code)
        return {}
    try:
        probe = cls()
    except TypeError as exc:
        logger.warning(
            "发布快照: 策略类不可无参实例化，vol_reset_policy 未冻结 "
            "template_code=%s err=%s", code, exc,
        )
        return {}
    getter = getattr(probe, "get_execution_schedule", None)
    if not callable(getter):
        return {}
    try:
        schedule = getter() or {}
    except Exception as exc:  # noqa: BLE001 —— 声明读不到不能拖垮发布
        logger.warning(
            "发布快照: get_execution_schedule 调用失败 template_code=%s err=%s", code, exc,
        )
        return {}
    if not isinstance(schedule, dict):
        return {}
    return parse_declared_vol_reset_policy(schedule.get("vol_reset_policy"))


def build_published_snapshot(
    model: StrategyModel,
    universe_version: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建发布冻结快照。

    策略快照冻结模板/选择器/资产/参数/窗口/调仓频率/控制器；
    组合快照冻结成员、权重、权重模型参数、初始净值与调仓频率。
    快照只包含运行口径字段，不含状态、实盘与回测摘要等可变字段。

    资产池绑定（S09）：``parameters["asset_universe_ref"]`` 非空时，额外冻结
    ``asset_universe_ref`` / ``asset_universe_version`` 两个键，并在拿到生效版本时
    用其 ``asset_codes`` 覆盖 ``asset_codes``（池子的历史由版本表保存，快照只记
    指向哪个版本）。未绑定资产池的模型**逐字段不变**。
    解析动作在调用方（services 层）做，本函数保持同步纯函数、不查库。
    """
    if getattr(model, "is_portfolio", False):
        members = []
        for sub in model.sub_strategies or []:
            item = dict(sub)
            item["weight"] = float(item.get("weight") or 0)
            members.append(item)
        snap: Dict[str, Any] = {
            "kind": "portfolio",
            "name": model.name,
            "is_portfolio": True,
            "sub_strategies": members,
            "weight_model_type": model.weight_model_type,
            "weight_model_params": deepcopy(model.weight_model_params or {}),
            "initial_nav": float(model.initial_nav or 1000.0),
            "rebalance_frequency": model.rebalance_frequency,
            "asset_codes": list(model.asset_codes or []),
            "asset_names": dict(model.asset_names or {}),
        }
    else:
        snap = {
            "kind": "strategy",
            "name": model.name,
            "is_portfolio": False,
            "parameters": merge_parameters_with_top_level_windows(
                model, model.parameters or {}
            ),
        }
        for field in _STRATEGY_SNAPSHOT_FIELDS:
            value = getattr(model, field, None)
            snap[field] = deepcopy(value) if isinstance(value, (dict, list)) else value
        # 波控三键只在策略声明时冻结；未声明不写键，下游按自身默认值走
        declared_policy = _declared_vol_reset_policy(model)
        if declared_policy:
            snap["vol_reset_policy"] = declared_policy
        inception = getattr(model, "inception_date", None)
        snap["inception_date"] = inception.isoformat() if inception else None

        # 资产池绑定：ref 非空才写三个键（未绑定模型不加任何键）
        params_obj = getattr(model, "parameters", None)
        universe_ref = params_obj.get("asset_universe_ref") if isinstance(params_obj, dict) else None
        if universe_ref:
            snap["asset_universe_ref"] = str(universe_ref)
            snap["asset_universe_version"] = None
            if universe_version:
                codes = normalize_codes(universe_version.get("asset_codes") or [])
                if codes:
                    snap["asset_codes"] = codes
                version_no = int(universe_version.get("version") or 0)
                snap["asset_universe_version"] = version_no or None

    snap["frozen_at"] = datetime.now().isoformat()
    return snap


def compute_config_fingerprint(snapshot: Dict[str, Any]) -> str:
    """计算发布快照指纹（忽略构建时间，用于核对下游运行版本）.

    序列化前先做类型归一：参数值若混入 DataFrame/Series（如某些模板把
    行情矩阵写进 parameters），``json.dumps`` 会隐式做真值判断而抛
    ``ValueError``；归一成「类型+形状+列名+索引/数值摘要」后序列化稳定。
    不含这类对象的快照序列化字节不变，既有指纹值不变。
    """
    payload = {k: v for k, v in (snapshot or {}).items() if k != "frozen_at"}
    canonical = json.dumps(
        normalize_fingerprint_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def apply_published_snapshot(
    model: StrategyModel, snapshot: Optional[Dict[str, Any]]
) -> StrategyModel:
    """返回应用了发布快照的模型副本（不修改原对象，不落库）。"""
    if not snapshot:
        return model
    update: Dict[str, Any] = {}
    if snapshot.get("is_portfolio"):
        for field in (
            "sub_strategies",
            "weight_model_type",
            "weight_model_params",
            "initial_nav",
            "rebalance_frequency",
            "asset_codes",
            "asset_names",
        ):
            if field in snapshot:
                update[field] = deepcopy(snapshot[field])
    else:
        for field in _STRATEGY_SNAPSHOT_FIELDS:
            if field in snapshot:
                update[field] = deepcopy(snapshot[field])
        if "parameters" in snapshot:
            update["parameters"] = deepcopy(snapshot["parameters"] or {})
        inception = snapshot.get("inception_date")
        if inception:
            try:
                update["inception_date"] = datetime.fromisoformat(str(inception))
            except ValueError:
                pass
    if not update:
        return model
    return model.model_copy(deep=True, update=update)
