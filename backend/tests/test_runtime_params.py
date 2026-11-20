# -*- coding: utf-8 -*-
"""运行时参数键约定单测（app/allocation/runtime_params.py）.

覆盖三类清单与两个取值口径：

- ``normalize_runtime_params``：历史参数名归一为现名，现名为空时回退历史名；
- ``resolve_weight_caps`` / ``parse_mapping_param``：资产权重约束的唯一取值口径，
  dict 与 JSON 字符串两种形态都要解析出同样的结果；
- ``effective_param_names``：门禁与保存净化共用的放行集（白名单 ∪ 固化键）；
- ``SAVE_INJECTED_PARAM_KEYS`` 必须与 ``strategy_model_service`` 的 ``_enforce_*``
  实际写入键一致——两侧任一新增固化键而未同步，本测试失败（防再次漂移）。

不触库，不启引擎。
"""
from __future__ import annotations

import pytest

from app.allocation.runtime_params import (
    MANUAL_ALLOCATION_TEMPLATE_CODES,
    PARAM_NAME_ALIASES,
    RISK_BUDGET_TARGET_VOL_TEMPLATE_CODES,
    RUNTIME_PARAM_WHITELIST,
    SAVE_INJECTED_PARAM_KEYS,
    SHARPE_RISK_BUDGET_TEMPLATE_CODES,
    WEIGHT_CAPS_PARAM_NAMES,
    canonical_param_name,
    effective_param_names,
    is_runtime_param,
    normalize_runtime_params,
    parse_mapping_param,
    resolve_weight_caps,
    save_injected_keys_for,
)
from app.services import strategy_model_service as sms


# ============================================================
# 一、历史参数名归一
# ============================================================

def test_normalize_maps_legacy_name_to_current():
    out = normalize_runtime_params({"max_weight_dict": {"A": 0.2}, "target_vol": 0.05})
    assert out == {"weight_caps": {"A": 0.2}, "target_vol": 0.05}
    assert "max_weight_dict" not in out


def test_normalize_prefers_non_empty_current_name():
    out = normalize_runtime_params({
        "weight_caps": {"A": 0.3},
        "max_weight_dict": {"A": 0.2},
    })
    assert out["weight_caps"] == {"A": 0.3}


def test_normalize_falls_back_when_current_name_is_empty():
    """现名存在但为空字典时视为「未设置」，否则约束会被空字典静默吃掉."""
    out = normalize_runtime_params({
        "weight_caps": {},
        "max_weight_dict": {"A": 0.2},
    })
    assert out["weight_caps"] == {"A": 0.2}


def test_normalize_does_not_inject_empty_current_name():
    out = normalize_runtime_params({"max_weight_dict": {}})
    assert "weight_caps" not in out
    assert out == {}


def test_normalize_does_not_mutate_input():
    src = {"max_weight_dict": {"A": 0.2}}
    normalize_runtime_params(src)
    assert src == {"max_weight_dict": {"A": 0.2}}


def test_normalize_accepts_empty_input():
    assert normalize_runtime_params(None) == {}
    assert normalize_runtime_params({}) == {}


def test_canonical_param_name():
    for legacy, current in PARAM_NAME_ALIASES.items():
        assert canonical_param_name(legacy) == current
    assert canonical_param_name("target_vol") == "target_vol"


# ============================================================
# 二、资产权重约束取值口径
# ============================================================

def test_resolve_weight_caps_from_current_name():
    assert resolve_weight_caps({"weight_caps": {"A": 0.2, "B": 1}}) == {"A": 0.2, "B": 1.0}


def test_resolve_weight_caps_falls_back_to_legacy_name():
    assert resolve_weight_caps({"max_weight_dict": {"A": 0.2}}) == {"A": 0.2}


def test_resolve_weight_caps_empty_current_name_uses_legacy():
    """与门禁同一口径：现名为空 → 用历史名，约束不丢."""
    caps = resolve_weight_caps({"weight_caps": {}, "max_weight_dict": {"A": 0.2}})
    assert caps == {"A": 0.2}


def test_resolve_weight_caps_parses_json_string():
    caps = resolve_weight_caps({"weight_caps": '{"A": 0.2, "B": 0.35}'})
    assert caps == {"A": 0.2, "B": 0.35}


def test_resolve_weight_caps_drops_unparsable_values():
    caps = resolve_weight_caps({"weight_caps": {"A": 0.2, "B": "很多", "C": None}})
    assert caps == {"A": 0.2}


def test_resolve_weight_caps_strips_code_and_returns_empty_when_unset():
    assert resolve_weight_caps({"weight_caps": {"  A  ": "0.2"}}) == {"A": 0.2}
    assert resolve_weight_caps({}) == {}
    assert resolve_weight_caps(None) == {}
    assert resolve_weight_caps({"weight_caps": "not-json"}) == {}


def test_weight_caps_param_names_cover_alias_pair():
    assert WEIGHT_CAPS_PARAM_NAMES == ("weight_caps", "max_weight_dict")
    assert set(PARAM_NAME_ALIASES) == {"max_weight_dict"}


def test_parse_mapping_param_shapes():
    assert parse_mapping_param({"A": 1}) == {"A": 1}
    assert parse_mapping_param('{"A": 1}') == {"A": 1}
    assert parse_mapping_param("[1, 2]") == {}
    assert parse_mapping_param("{'A': 1}") == {}
    assert parse_mapping_param(3.5) == {}
    assert parse_mapping_param(None) == {}
    assert parse_mapping_param("   ") == {}


# ============================================================
# 三、放行集：白名单 ∪ 按模板固化键
# ============================================================

@pytest.mark.parametrize("key", sorted(RUNTIME_PARAM_WHITELIST))
def test_whitelist_keys_are_runtime_params_for_any_template(key):
    assert is_runtime_param(key) is True
    assert is_runtime_param(key, "risk_parity") is True
    assert key in effective_param_names("risk_parity")


def test_unknown_key_is_not_runtime_param():
    assert is_runtime_param("not_a_param", "vol_scaled_budget") is False
    assert is_runtime_param("", None) is False


def test_save_injected_keys_only_apply_to_own_template():
    keys = save_injected_keys_for("sharpe_risk_budget")
    assert "monitor_start_days" in keys
    assert is_runtime_param("monitor_start_days", "sharpe_risk_budget") is True
    # 别的模板不认这个固化键
    assert is_runtime_param("monitor_start_days", "risk_parity") is False
    assert save_injected_keys_for("risk_parity") == frozenset()
    assert save_injected_keys_for(None) == frozenset()


def test_effective_param_names_is_union():
    names = effective_param_names("manual_allocation")
    assert names == RUNTIME_PARAM_WHITELIST | SAVE_INJECTED_PARAM_KEYS["manual_allocation"]


def test_legacy_template_codes_share_family_keys():
    """历史 code 与正式 code 属同一家族，固化键必须一致."""
    for code in MANUAL_ALLOCATION_TEMPLATE_CODES:
        assert SAVE_INJECTED_PARAM_KEYS[code] == SAVE_INJECTED_PARAM_KEYS["manual_allocation"]
    for code in RISK_BUDGET_TARGET_VOL_TEMPLATE_CODES:
        assert (
            SAVE_INJECTED_PARAM_KEYS[code]
            == SAVE_INJECTED_PARAM_KEYS["risk_budget_target_vol"]
        )
    for code in SHARPE_RISK_BUDGET_TEMPLATE_CODES:
        assert (
            SAVE_INJECTED_PARAM_KEYS[code]
            == SAVE_INJECTED_PARAM_KEYS["sharpe_risk_budget"]
        )


# ============================================================
# 四、固化键与保存路径实际写入键对齐（防漂移）
# ============================================================

def _enforced_parameter_keys(template_code: str) -> set:
    """跑一遍保存侧固化函数，取它实际写进 parameters 的键."""
    model_dict = {"template_code": template_code, "parameters": {}}
    sms._enforce_manual_allocation_monitor_fixed_on_dict(model_dict)
    sms._enforce_risk_budget_target_vol_fixed_on_dict(model_dict)
    sms._enforce_sharpe_risk_budget_fixed_on_dict(model_dict)
    return set(model_dict["parameters"])


@pytest.mark.parametrize(
    "template_code", sorted(SAVE_INJECTED_PARAM_KEYS), ids=sorted(SAVE_INJECTED_PARAM_KEYS)
)
def test_save_injected_keys_match_enforcers(template_code):
    """声明的固化键必须与 _enforce_* 实际写入的键完全一致.

    多声明 → 门禁放行了一个没人写的键；少声明 → 保存写下的键被门禁阻断。
    """
    assert _enforced_parameter_keys(template_code) == set(SAVE_INJECTED_PARAM_KEYS[template_code])


def test_enforced_keys_never_block_the_gate():
    """保存固化的键必须被门禁放行：否则「存得下、跑不了回测」.

    固化键在 schema 内时取 schema 默认值（避免取值超范围干扰本用例的结论），
    schema 外时取任意值——门禁不应因「不在参数定义中」而报 parameter_invalid。
    未在 manifest 注册的历史 code 不参与（它们由 template_not_found 阻断）。
    """
    from app.allocation.strategy_manifest import resolve_class_safe
    from app.services import strategy_preset_service as svc

    checked = 0
    for template_code in sorted(SAVE_INJECTED_PARAM_KEYS):
        strategy_cls = resolve_class_safe(template_code)
        if strategy_cls is None:
            continue
        checked += 1
        defaults = {p.name: p.default for p in strategy_cls.get_param_schema().params}
        params = {
            key: (defaults[key] if key in defaults else 0)
            for key in SAVE_INJECTED_PARAM_KEYS[template_code]
        }
        issues = [
            i for i in svc._check_parameters(template_code, params)
            if i.type == "parameter_invalid"
        ]
        assert not issues, (
            f"{template_code} 的固化键被门禁阻断: {[i.message for i in issues]}"
        )
    assert checked, "没有可解析的固化模板，本用例失去意义"
