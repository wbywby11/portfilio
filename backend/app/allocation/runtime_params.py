# -*- coding: utf-8 -*-
"""策略模型 ``parameters`` 的运行时键约定（保存 / 门禁 / 运行时唯一来源）。

``strategy_models.parameters`` 里不只有模板 schema 声明的可配置参数，还有三类
由系统写入、被 Pipeline / 回测引擎 / 日常监控消费的键：

- :data:`RUNTIME_PARAM_WHITELIST`：跨模板通用的运行时键（前端注入或模型级调度声明）；
- :data:`SAVE_INJECTED_PARAM_KEYS`：保存路径按模板固化的监控/风控参数；
- :data:`PARAM_NAME_ALIASES`：模板重构后的历史参数名 → 现名。

三份清单必须被「保存净化」与「回测门禁」同时承认。此前它们分散在
:mod:`app.services.strategy_model_service`（保存侧白名单）与各运行时消费点，
门禁只认 schema，于是出现两类相反的错误：

1. 配置能存下来、回测页却被 ``parameter_invalid`` 阻断（如 ``selector_parameters``、
   ``manual_weight_adjustments``、旧名 ``max_weight_dict``）；
2. 门禁放行、运行时约束却静默失效（现名 ``weight_caps`` 为空字典时不回退旧名）。

本模块把三份清单与权重约束的取值口径收敛到一处：保存侧
（:mod:`app.services.strategy_model_service`）、门禁侧
（:mod:`app.services.strategy_preset_service`）与全部运行时消费点都从这里取。

本模块不 import 任何 app 内模块，可被 allocation / services / backtesting /
monitor / portfolio 各层安全引用（不产生循环依赖）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

__all__ = [
    "RUNTIME_PARAM_WHITELIST",
    "SAVE_INJECTED_PARAM_KEYS",
    "PARAM_NAME_ALIASES",
    "WEIGHT_CAPS_PARAM_NAMES",
    "RISK_BUDGET_TARGET_VOL_TEMPLATE_CODES",
    "MANUAL_ALLOCATION_TEMPLATE_CODES",
    "SHARPE_RISK_BUDGET_TEMPLATE_CODES",
    "canonical_param_name",
    "is_runtime_param",
    "save_injected_keys_for",
    "effective_param_names",
    "normalize_runtime_params",
    "parse_mapping_param",
    "resolve_weight_caps",
]


# ---------------------------------------------------------------------------
# 一、跨模板通用的运行时键（非 schema 参数，但系统执行时需要）
# ---------------------------------------------------------------------------

RUNTIME_PARAM_WHITELIST: FrozenSet[str] = frozenset({
    "manual_weight_adjustments",  # 主观配置预设调仓记录
    "selector_parameters",        # 选择器动态参数（前端注入）
    "weight_caps",                # 资产权重约束配置
    "max_weight_dict",            # 资产权重约束（历史名，见 PARAM_NAME_ALIASES）
    "manual_weights",             # 主观权重配置
    "execution_delay",            # 模型级执行延迟覆盖（Pipeline 调度声明）
    "signal_timing",              # 模型级信号时点覆盖（prev_close/execution_bar）
    "preserve_price_gaps",        # 缺日保真（信号计算保留品种缺日 NaN，数据源层消费）
    "inception_weights",          # 模型级期初建仓权重（指数基日满仓口径）
    "inception_weights_auto_normalize",  # 期初建仓权重是否归一化
    "calendar_source",            # 模型级日历口径（监控 time_norm 消费：trade_dates/prices）
})


# ---------------------------------------------------------------------------
# 二、保存路径按模板固化的参数（与 strategy_model_service 的 _enforce_* 对齐）
# ---------------------------------------------------------------------------

#: 风险预算目标波动率（含历史 code ``risk_budget_vol_target``）
RISK_BUDGET_TARGET_VOL_TEMPLATE_CODES: FrozenSet[str] = frozenset({
    "risk_budget_target_vol", "risk_budget_vol_target",
})

#: 主观固定权重（含历史 code ``manual_allocation_strategy``）
MANUAL_ALLOCATION_TEMPLATE_CODES: FrozenSet[str] = frozenset({
    "manual_allocation", "manual_allocation_strategy",
})

#: 夏普率风险预算
SHARPE_RISK_BUDGET_TEMPLATE_CODES: FrozenSet[str] = frozenset({"sharpe_risk_budget"})

# _apply_manual_allocation_fixed_parameters 写入的键
_MANUAL_ALLOCATION_FIXED_KEYS: FrozenSet[str] = frozenset({
    "max_leverage", "auto_normalize", "fill_missing",
    "target_vol", "vol_reset_threshold", "enable_vol_reset",
})

# _enforce_risk_budget_target_vol_fixed_on_dict 写入的键
_RISK_BUDGET_TARGET_VOL_FIXED_KEYS: FrozenSet[str] = frozenset({
    "lookback_days", "vol_reset_threshold", "enable_vol_reset",
})

# _enforce_sharpe_risk_budget_fixed_on_dict 写入的键
_SHARPE_RISK_BUDGET_FIXED_KEYS: FrozenSet[str] = frozenset({
    "target_vol", "max_leverage", "select_count", "vol_windows", "sharp_windows",
    "enable_vol_reset", "vol_reset_threshold", "vol_trigger_threshold",
    "monitor_start_days", "min_history_days",
})

_SAVE_INJECTED_BY_FAMILY: Tuple[Tuple[FrozenSet[str], FrozenSet[str]], ...] = (
    (MANUAL_ALLOCATION_TEMPLATE_CODES, _MANUAL_ALLOCATION_FIXED_KEYS),
    (RISK_BUDGET_TARGET_VOL_TEMPLATE_CODES, _RISK_BUDGET_TARGET_VOL_FIXED_KEYS),
    (SHARPE_RISK_BUDGET_TEMPLATE_CODES, _SHARPE_RISK_BUDGET_FIXED_KEYS),
)

#: ``{template_code: 保存时固化的参数名}``。
#: 由 ``tests/test_runtime_params.py`` 与 ``_enforce_*`` 函数的实际写入键核对，
#: 任一侧新增固化键而未同步此处，测试会失败（防止再次漂移）。
SAVE_INJECTED_PARAM_KEYS: Dict[str, FrozenSet[str]] = {
    code: keys
    for codes, keys in _SAVE_INJECTED_BY_FAMILY
    for code in codes
}


# ---------------------------------------------------------------------------
# 三、历史参数名 → 现名
# ---------------------------------------------------------------------------

#: 模板重构后仍在库里的历史参数名。运行时以现名优先、历史名兜底。
PARAM_NAME_ALIASES: Dict[str, str] = {
    "max_weight_dict": "weight_caps",
}

#: 资产权重约束的全部候选键（按优先级排序）
WEIGHT_CAPS_PARAM_NAMES: Tuple[str, ...] = ("weight_caps", "max_weight_dict")


# ---------------------------------------------------------------------------
# 四、判定与归一
# ---------------------------------------------------------------------------

def canonical_param_name(name: str) -> str:
    """把历史参数名归一为现名（非历史名原样返回）.

    Args:
        name: 参数名

    Returns:
        现名；未登记别名时返回入参本身
    """
    return PARAM_NAME_ALIASES.get(str(name or ""), str(name or ""))


def save_injected_keys_for(template_code: Optional[str]) -> FrozenSet[str]:
    """返回该模板保存时固化的参数名集合（无固化返回空集）."""
    return SAVE_INJECTED_PARAM_KEYS.get(str(template_code or ""), frozenset())


def is_runtime_param(name: str, template_code: Optional[str] = None) -> bool:
    """判断参数名是否属于「系统写入并被运行时消费」的键.

    门禁据此放行：这些键不是模板可配置参数，但删除它们会让选择器、
    主观调仓、模型级调度声明与监控固化值失效。

    Args:
        name: 参数名
        template_code: 模板代码（用于匹配按模板固化的键），可为空

    Returns:
        True 表示属运行时键，门禁不应因「不在 schema 中」而阻断
    """
    key = str(name or "")
    if key in RUNTIME_PARAM_WHITELIST:
        return True
    return key in save_injected_keys_for(template_code)


def effective_param_names(template_code: Optional[str]) -> FrozenSet[str]:
    """返回该模板 schema 之外仍需保留/放行的参数名全集.

    保存净化（``_sanitize_params_by_schema``）与回测门禁
    （``_check_parameters``）共用：前者决定「哪些键能存下来」，
    后者决定「哪些键不算未定义参数」，两者不同源就会出现
    「能保存、不能回测」。
    """
    return RUNTIME_PARAM_WHITELIST | save_injected_keys_for(template_code)


def normalize_runtime_params(parameters: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """历史参数名归一为现名，返回新字典（不改入参）.

    口径与 :func:`resolve_weight_caps` 一致：现名存在但为空
    （``{}`` / ``""`` / ``None``）视为「未设置」，回退历史名的值。
    否则模型里同时存 ``weight_caps={}`` 与 ``max_weight_dict={"A": 0.2}`` 时，
    权重约束会被空字典静默吃掉——门禁看到的与运行时生效的会不一致。

    Args:
        parameters: 模型 ``parameters`` 或门禁入参，可为空

    Returns:
        归一后的参数字典；历史名不再出现在结果中
    """
    out: Dict[str, Any] = dict(parameters or {})
    for legacy, current in PARAM_NAME_ALIASES.items():
        if legacy not in out:
            continue
        legacy_value = out.pop(legacy)
        if not out.get(current) and legacy_value:
            out[current] = legacy_value
    return out


def parse_mapping_param(value: Any) -> Dict[str, Any]:
    """把「字典或 JSON 字符串」形态的参数统一解析为字典.

    历史模型与前端表单都可能把字典参数存成 JSON 字符串；各消费点此前
    各写一份 ``json.loads`` + 兜底，解析失败时静默变成空字典。此处统一：
    非字典、非法 JSON、JSON 解析结果不是字典，一律返回 ``{}``。

    Args:
        value: 原始参数值

    Returns:
        解析后的字典；无法解析时返回空字典
    """
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def resolve_weight_caps(params: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    """资产权重约束的有效值（全部消费点的唯一实现）.

    取值顺序：``weight_caps``（现名）→ ``max_weight_dict``（历史名），
    现名为空视为未设置。值可以是字典或 JSON 字符串；条目值无法转
    ``float`` 的丢弃（与监控 ``_merge_weight_caps`` 的历史口径一致）。

    Args:
        params: 策略参数字典（模型 ``parameters`` 或组装后的 ``strategy_params``）

    Returns:
        ``{资产代码: 权重上限}``；未配置或无法解析时返回空字典（= 不限制）
    """
    source = params or {}
    caps: Dict[str, float] = {}
    for key in WEIGHT_CAPS_PARAM_NAMES:
        parsed = parse_mapping_param(source.get(key))
        if not parsed:
            continue
        for code, value in parsed.items():
            try:
                caps[str(code).strip()] = float(value)
            except (TypeError, ValueError):
                continue
        break
    return caps
