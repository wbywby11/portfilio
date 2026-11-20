# -*- coding: utf-8 -*-
"""预设解析与三级校验服务单测（app/services/strategy_preset_service.py）.

覆盖计划 §四 单测清单：

- ``classify``：每个机器码落到预期级别，未知码按引擎层 level 兜底；
- ``_check_structure``：重复代码 / 跨组重叠 / 标签为空 / 未知标签 / 空组 五类反例；
- ``_check_parameters``：未知参数名 / 类型错 / 超范围 / 条件不满足；
- ``_check_assets``：空池报 ``pool_empty``，契约已覆盖登记时不再重复查库；
- ``_expand_assets``：explicit / tags / hybrid 三模式，分组并集等于资产池；
- ``stamp_preset_trace``：版本号按当前定义重算、应用时间不因重复保存刷新。

不触库（``_load_tag_index`` 用 monkeypatch 桩替），不启引擎。
"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta

import pytest

from app.allocation.builtin_presets import find_preset, preset_content_hash
from app.allocation.runtime_params import (
    RUNTIME_PARAM_WHITELIST,
    save_injected_keys_for,
)
from app.allocation.strategy_manifest import get_class_paths, resolve_class
from app.services import strategy_preset_service as svc
from app.services.strategy_preset_service import (
    LEVEL_BLOCKING,
    LEVEL_DATA,
    LEVEL_WARNING,
    PresetIssue,
    classify,
    config_hash,
    stamp_preset_trace,
)


def _run(coro):
    """本仓未装 pytest-asyncio，协程统一用 asyncio.run 驱动."""
    return asyncio.run(coro)


def _issue_types(issues):
    return [i.type for i in issues]


def _level_of(issues, type_name):
    for i in issues:
        if i.type == type_name:
            return i.level
    return None


LOW_VOL = "nous_low_vol"


# ============================================================
# 一、三级分级映射
# ============================================================

# 计划 §1.1 映射表逐行断言：code -> 预期级别
_EXPECTED_LEVELS = [
    # preset service 自身
    ("template_not_found", LEVEL_BLOCKING),
    ("duplicate_code", LEVEL_BLOCKING),
    ("tag_empty", LEVEL_BLOCKING),
    ("group_overlap", LEVEL_BLOCKING),
    ("parameter_invalid", LEVEL_BLOCKING),
    # validate_static
    ("group_missing", LEVEL_BLOCKING),
    ("pool_not_covered", LEVEL_BLOCKING),
    ("group_member_not_in_pool", LEVEL_BLOCKING),
    ("asset_class_mismatch", LEVEL_BLOCKING),
    ("asset_not_found", LEVEL_DATA),
    # 资产面：只判池子与登记
    ("pool_empty", LEVEL_DATA),
    # preset service 提示类
    ("tag_unknown", LEVEL_WARNING),
    ("empty_group", LEVEL_WARNING),
    ("param_condition_unmet", LEVEL_WARNING),
]


@pytest.mark.parametrize("code,expected", _EXPECTED_LEVELS, ids=[c for c, _ in _EXPECTED_LEVELS])
def test_classify_maps_every_code(code, expected):
    # 即使引擎层给的是 error，映射表也优先（asset_not_found 就是这种）
    assert classify(code, "error") == expected
    assert classify(code, "warning") == expected


def test_classify_unknown_code_falls_back_to_engine_level():
    assert classify("some_new_engine_error", "error") == LEVEL_BLOCKING
    assert classify("some_new_engine_warning", "warning") == LEVEL_WARNING


# ============================================================
# 二、_check_structure
# ============================================================

def _structure(asset_selection, groups, pool, tag_index=None, asset_meta=None):
    return svc._check_structure(
        asset_selection, groups, pool, LOW_VOL, tag_index or {}, asset_meta
    )


def test_structure_duplicate_code_within_group():
    issues = _structure(
        {"mode": "explicit"},
        {"a_eq_codes": ["510300.SH", "510300.SH"]},
        ["510300.SH"],
    )
    assert _level_of(issues, "duplicate_code") == LEVEL_BLOCKING
    assert any("510300.SH" in i.assets for i in issues if i.type == "duplicate_code")


def test_structure_group_overlap_between_groups():
    issues = _structure(
        {"mode": "explicit"},
        {"a_eq_codes": ["510300.SH"], "hk_eq_codes": ["510300.SH"]},
        ["510300.SH"],
    )
    assert _level_of(issues, "group_overlap") == LEVEL_BLOCKING


def test_structure_tag_empty_when_mode_tags_without_tags():
    issues = _structure({"mode": "tags"}, {}, [])
    assert _level_of(issues, "tag_empty") == LEVEL_BLOCKING


def test_structure_tag_unknown_is_warning():
    issues = _structure(
        {"mode": "tags", "tags": ["pool:not_exists"]},
        {},
        [],
        tag_index={"pool:someone_else": ["X"]},
    )
    assert _level_of(issues, "tag_unknown") == LEVEL_WARNING


def test_structure_empty_group_requires_same_class_assets_in_pool():
    """池内存在该大类资产时才提示空组；池内根本没有该大类就不提示."""
    asset_selection = {
        "mode": "tags",
        "tags": ["pool:x"],
        "group_rules": {"a_eq_codes": {"tags": ["class:equity", "market:cn"]}},
    }
    groups = {"a_eq_codes": []}
    pool = ["510300.SH"]

    # 池内 510300.SH 是权益 → 提示空组
    issues = _structure(
        asset_selection, groups, pool, tag_index={"pool:x": pool},
        asset_meta={"510300.SH": {"asset_class": "权益"}},
    )
    assert _level_of(issues, "empty_group") == LEVEL_WARNING

    # 池内资产是固收 → 该组本来就不该有内容，不提示
    issues = _structure(
        asset_selection, groups, pool, tag_index={"pool:x": pool},
        asset_meta={"510300.SH": {"asset_class": "固收"}},
    )
    assert "empty_group" not in _issue_types(issues)


def test_structure_clean_config_has_no_issues():
    issues = _structure(
        {"mode": "explicit"},
        {"a_eq_codes": ["510300.SH"]},
        ["510300.SH"],
    )
    assert issues == []


# ============================================================
# 三、_check_parameters
# ============================================================

def test_parameters_unknown_name_is_blocking():
    issues = svc._check_parameters(LOW_VOL, {"not_a_param": 1})
    assert _level_of(issues, "parameter_invalid") == LEVEL_BLOCKING


def test_parameters_out_of_range_is_blocking():
    # select_count 的 max_value 是 50
    issues = svc._check_parameters(LOW_VOL, {"select_count": 999})
    assert _level_of(issues, "parameter_invalid") == LEVEL_BLOCKING


def test_parameters_wrong_type_is_blocking():
    # select_count 是 number，传非数值字符串
    issues = svc._check_parameters(LOW_VOL, {"select_count": "很多"})
    assert _level_of(issues, "parameter_invalid") == LEVEL_BLOCKING


def test_parameters_condition_unmet_is_warning():
    """关掉日度波控却仍把触发线调离默认值 → 提示但不阻断."""
    issues = svc._check_parameters(
        LOW_VOL, {"enable_daily_vol_control": False, "daily_vol_trigger": 0.08}
    )
    assert _level_of(issues, "param_condition_unmet") == LEVEL_WARNING


def test_parameters_condition_unmet_not_reported_at_default_value():
    """条件不满足但值仍是默认值时不报——默认值本就是该条件下的中性取值."""
    issues = svc._check_parameters(
        LOW_VOL, {"enable_daily_vol_control": False, "daily_vol_trigger": 0.04}
    )
    assert "param_condition_unmet" not in _issue_types(issues)


def test_parameters_template_not_found_is_blocking():
    issues = svc._check_parameters("not_a_template", {})
    assert _level_of(issues, "template_not_found") == LEVEL_BLOCKING


# ============================================================
# 四、_expand_assets 三模式
# ============================================================

_TAG_INDEX = {
    "pool:nous": ["510300.SH", "159915.SZ", "511260.SH", "518880.SH"],
    "class:equity": ["510300.SH", "159915.SZ"],
    "class:bond": ["511260.SH"],
    "class:comm": ["518880.SH"],
    "market:cn": ["510300.SH", "159915.SZ", "511260.SH"],
    "market:gold": ["518880.SH"],
}


def _stub_tag_index(monkeypatch):
    async def fake():
        return {k: list(v) for k, v in _TAG_INDEX.items()}

    monkeypatch.setattr(svc, "_load_tag_index", fake)


def test_expand_explicit_mode(monkeypatch):
    _stub_tag_index(monkeypatch)
    groups, pool, _ = _run(svc._expand_assets({
        "mode": "explicit",
        "groups": {
            "a_eq_codes": ["510300.SH", "159915.SZ"],
            "a_bond_codes": ["511260.SH"],
        },
    }))
    assert groups == {
        "a_eq_codes": ["510300.SH", "159915.SZ"],
        "a_bond_codes": ["511260.SH"],
    }
    assert sorted(pool) == ["159915.SZ", "510300.SH", "511260.SH"]
    # 并集等于资产池
    assert set(pool) == set(groups["a_eq_codes"]) | set(groups["a_bond_codes"])


def test_expand_tags_mode(monkeypatch):
    _stub_tag_index(monkeypatch)
    groups, pool, _ = _run(svc._expand_assets({
        "mode": "tags",
        "tags": ["pool:nous"],
        "group_rules": {
            "a_eq_codes": {"tags": ["class:equity", "market:cn"]},
            "a_bond_codes": {"tags": ["class:bond"]},
            "comm_codes": {"tags": ["class:comm"]},
        },
    }))
    assert sorted(pool) == ["159915.SZ", "510300.SH", "511260.SH", "518880.SH"]
    assert groups["a_eq_codes"] == ["159915.SZ", "510300.SH"]
    assert groups["a_bond_codes"] == ["511260.SH"]
    assert groups["comm_codes"] == ["518880.SH"]
    # 各组并集覆盖整个池子
    union = set()
    for codes in groups.values():
        union |= set(codes)
    assert union == set(pool)


def test_expand_hybrid_mode_explicit_group_wins(monkeypatch):
    _stub_tag_index(monkeypatch)
    groups, pool, _ = _run(svc._expand_assets({
        "mode": "hybrid",
        "tags": ["pool:nous"],
        "groups": {"a_eq_codes": ["510300.SH"]},   # 显式只给一只，优先
        "group_rules": {
            "a_eq_codes": {"tags": ["class:equity"]},
            "a_bond_codes": {"tags": ["class:bond"]},
        },
    }))
    assert groups["a_eq_codes"] == ["510300.SH"]
    assert groups["a_bond_codes"] == ["511260.SH"]
    assert "159915.SZ" in pool


def test_expand_tags_mode_empty_tags_yields_empty_pool(monkeypatch):
    _stub_tag_index(monkeypatch)
    groups, pool, _ = _run(svc._expand_assets({"mode": "tags", "tags": []}))
    assert pool == []
    assert groups == {}


# ============================================================
# 五、config_hash 与快照
# ============================================================

def test_config_hash_stable_and_sensitive():
    a = config_hash(["A", "B"], {"x": 1})
    assert a == config_hash(["A", "B"], {"x": 1})
    assert a != config_hash(["A", "B"], {"x": 2})
    assert a != config_hash(["A"], {"x": 1})
    assert len(a) == 8


def test_build_snapshot_records_rules_and_hash():
    snapshot = svc.build_asset_selection_snapshot(
        {"mode": "tags", "tags": ["pool:x"], "group_rules": {"a": {"tags": ["class:y"]}}},
        {"a": ["A", "B"]},
        ["A", "B"],
        {"select_count": 2},
    )
    assert snapshot["mode"] == "tags"
    assert snapshot["tags"] == ["pool:x"]
    assert snapshot["group_rules"] == {"a": {"tags": ["class:y"]}}
    assert snapshot["groups"] == {"a": ["A", "B"]}
    assert snapshot["expanded_codes"] == ["A", "B"]
    assert snapshot["applied_hash"] == config_hash(["A", "B"], {"select_count": 2})
    assert snapshot["expanded_at"]


# ============================================================
# 六、stamp_preset_trace
# ============================================================

def test_stamp_writes_version_from_current_definition():
    preset = find_preset("nous_low_vol__v6_d3")
    data = {"preset_code": preset["code"], "asset_codes": ["A"], "parameters": {"x": 1}}
    out = stamp_preset_trace(data)
    assert out["preset_version"] == preset_content_hash(preset)
    assert isinstance(out["preset_applied_at"], datetime)
    assert out["asset_selection_snapshot"]["applied_hash"] == config_hash(["A"], {"x": 1})


def test_stamp_ignores_frontend_supplied_version():
    preset = find_preset("nous_low_vol__v6_d3")
    data = {
        "preset_code": preset["code"],
        "preset_version": "deadbeef",   # 前端伪造
        "asset_codes": [],
        "parameters": {},
    }
    out = stamp_preset_trace(data)
    assert out["preset_version"] == preset_content_hash(preset)
    assert out["preset_version"] != "deadbeef"


def test_stamp_keeps_applied_at_when_preset_unchanged():
    preset = find_preset("nous_low_vol__v7")
    old = datetime.now() - timedelta(days=3)
    data = {
        "preset_code": preset["code"],
        "preset_applied_at": old,
        "asset_codes": [],
        "parameters": {},
    }
    out = stamp_preset_trace(data, previous_preset_code=preset["code"])
    assert out["preset_applied_at"] == old


def test_stamp_refreshes_applied_at_when_preset_changes():
    preset = find_preset("nous_low_vol__v7")
    old = datetime.now() - timedelta(days=3)
    data = {
        "preset_code": preset["code"],
        "preset_applied_at": old,
        "asset_codes": [],
        "parameters": {},
    }
    out = stamp_preset_trace(data, previous_preset_code="nous_low_vol__v6_d3")
    assert out["preset_applied_at"] > old


def test_stamp_clears_trace_when_preset_removed():
    data = {"preset_code": None, "preset_version": "abc12345",
            "asset_selection_snapshot": {"mode": "explicit"}}
    out = stamp_preset_trace(data)
    assert out["preset_version"] is None
    assert out["preset_applied_at"] is None
    assert out["asset_selection_snapshot"] is None


def test_stamp_raises_on_unknown_preset():
    with pytest.raises(ValueError):
        stamp_preset_trace({"preset_code": "no_such_preset"})


def test_stamp_uses_fallback_for_partial_update():
    preset = find_preset("nous_low_vol__v7")
    out = stamp_preset_trace(
        {"preset_code": preset["code"]},
        fallback_asset_codes=["511260.SH"],
        fallback_parameters={"select_count": 11},
    )
    assert out["asset_selection_snapshot"]["expanded_codes"] == ["511260.SH"]
    assert out["asset_selection_snapshot"]["applied_hash"] == config_hash(
        ["511260.SH"], {"select_count": 11}
    )


# ============================================================
# 七、PresetResolveResult 的门禁语义
# ============================================================

def _result(issues):
    return svc.PresetResolveResult(
        template_code=LOW_VOL, name="t", asset_codes=[], parameters={},
        rebalance_frequency="月", min_history_days=260, groups={}, issues=issues,
    )


def test_applicable_only_depends_on_blocking():
    warn = PresetIssue(level=LEVEL_WARNING, type="x", message="m")
    data = PresetIssue(level=LEVEL_DATA, type="history_too_short", message="m")
    blocking = PresetIssue(level=LEVEL_BLOCKING, type="group_missing", message="m")

    assert _result([warn]).applicable is True
    # data 缺口允许应用（先把配置存下来），但不可回测
    r = _result([warn, data])
    assert r.applicable is True
    assert r.backtest_ready is False
    # blocking 一律不可应用
    assert _result([blocking]).applicable is False
    assert _result([blocking]).backtest_ready is False


def test_to_dict_exposes_three_level_buckets():
    out = _result([
        PresetIssue(level=LEVEL_BLOCKING, type="a", message="m"),
        PresetIssue(level=LEVEL_DATA, type="b", message="m"),
        PresetIssue(level=LEVEL_WARNING, type="c", message="m"),
    ]).to_dict()
    assert [i["level"] for i in out["issues"]] == [
        LEVEL_BLOCKING, LEVEL_DATA, LEVEL_WARNING,
    ]
    assert out["applicable"] is False
    assert out["backtest_ready"] is False


# ---------------------------------------------------------------------------
# preset_derived_fields：派生标记（不落库，接口实时算）
# ---------------------------------------------------------------------------


def _model_with_preset(preset_code="nous_low_vol__v6_d3", **overrides):
    """按 V6_D3 构造一份「刚应用完预设、未手动调整」的模型文档."""
    preset = find_preset(preset_code)
    assert preset is not None
    groups = {k: list(v) for k, v in preset["asset_selection"]["groups"].items()}
    codes = []
    for members in groups.values():
        codes.extend(members)
    params = dict(preset["parameters"])
    for name, members in groups.items():
        params[name] = ",".join(members)
    doc = {
        "preset_code": preset_code,
        "preset_version": preset_content_hash(preset),
        "asset_codes": codes,
        "parameters": params,
        "asset_selection_snapshot": {
            "mode": "explicit",
            "applied_hash": config_hash(codes, params),
        },
    }
    doc.update(overrides)
    return doc, preset


def test_derived_fields_no_preset_returns_false():
    assert svc.preset_derived_fields({"asset_codes": [], "parameters": {}}) == {
        "preset_modified": False,
        "preset_outdated": False,
    }


def test_derived_fields_just_applied_is_not_modified():
    doc, _ = _model_with_preset()
    derived = svc.preset_derived_fields(doc)
    assert derived["preset_modified"] is False
    assert derived["preset_outdated"] is False


def test_derived_fields_parameter_change_marks_modified():
    doc, _ = _model_with_preset()
    doc["parameters"]["select_count"] = 99
    assert svc.preset_derived_fields(doc)["preset_modified"] is True


def test_derived_fields_asset_change_marks_modified():
    doc, _ = _model_with_preset()
    doc["asset_codes"] = doc["asset_codes"][:-1]
    assert svc.preset_derived_fields(doc)["preset_modified"] is True


def test_derived_fields_version_bump_marks_outdated():
    doc, _ = _model_with_preset()
    doc["preset_version"] = "deadbeef"
    derived = svc.preset_derived_fields(doc)
    assert derived["preset_outdated"] is True
    # 版本变化不影响「已调整」判定
    assert derived["preset_modified"] is False


def test_derived_fields_missing_preset_counts_as_outdated():
    doc, _ = _model_with_preset()
    doc["preset_code"] = "nous_low_vol__not_exist"
    derived = svc.preset_derived_fields(doc)
    assert derived["preset_outdated"] is True
    assert derived["preset_modified"] is False


def test_derived_fields_without_recorded_version_is_not_outdated():
    doc, _ = _model_with_preset()
    doc["preset_version"] = None
    assert svc.preset_derived_fields(doc)["preset_outdated"] is False


def test_derived_fields_accepts_model_object():
    """pydantic 实例与 Mongo 文档两种入参都要能算."""

    class _Stub:
        preset_code = "nous_low_vol__v6_d3"
        preset_version = None
        asset_codes = ["510300.SH"]
        parameters = {"select_count": 12}
        asset_selection_snapshot = {"applied_hash": "deadbeef"}

    derived = svc.preset_derived_fields(_Stub())
    assert derived["preset_modified"] is True
    assert derived["preset_outdated"] is False


# ---------------------------------------------------------------------------
# _check_assets：只校验池子与代码登记，不校验行情
# ---------------------------------------------------------------------------


def test_check_assets_empty_pool_is_data_error():
    issues = _run(svc._check_assets([], "nous_low_vol"))
    assert [i.type for i in issues] == ["pool_empty"]
    assert issues[0].level == LEVEL_DATA


def test_check_assets_skips_db_when_contract_declares_asset_class(monkeypatch):
    """契约声明了 expected_asset_class 时，登记检查已由 check_static_contract
    逐组完成，此处不重复查库——以触库即抛错证明未查询."""

    def _boom():
        raise AssertionError("契约已声明 expected_asset_class，不应再查 assets 集合")

    monkeypatch.setattr(svc.Database, "get_database", staticmethod(_boom))
    assert _run(svc._check_assets(["510300.SH"], "nous_low_vol")) == []


# ---------------------------------------------------------------------------
# _brief：宽池 issue 文案截断
# ---------------------------------------------------------------------------


def test_brief_lists_all_within_limit():
    codes = [f"{i:06d}.OF" for i in range(svc._MAX_LISTED_ASSETS)]
    text = svc._brief(codes)
    assert text == "、".join(codes)
    assert "等" not in text


def test_brief_truncates_long_list_with_total():
    # 354 只基金全列会让弹窗文案过万字符，必须只列前几项 + 总数
    codes = [f"{i:06d}.OF" for i in range(354)]
    text = svc._brief(codes)
    assert text.endswith("等 354 只")
    assert codes[-1] not in text
    assert len(text) < 150


# ---------------------------------------------------------------------------
# 参数门禁的判定口径：schema ∪ 运行时键（app/allocation/runtime_params.py）
# ---------------------------------------------------------------------------

# 经 LEGACY_ALIASES 解析为 vol_scaled_budget 的历史 code（截图里的「全天候」就是它）
TVB = "risk_budget_target_vol"


def _blocking_param_issues(template_code, parameters):
    return [
        i for i in svc._check_parameters(template_code, parameters)
        if i.type == "parameter_invalid"
    ]


def test_parameters_runtime_whitelist_keys_are_allowed():
    """前端注入与模型级调度声明的键不属模板参数，但不得阻断回测.

    这些键由保存白名单写进 ``parameters``，被 Pipeline / 引擎 / 监控消费；
    门禁不认它们就会出现「配置能存下来、回测页报 parameter_invalid」。
    """
    params = {
        "selector_parameters": {"mom_windows": "20,60"},
        "manual_weight_adjustments": [{"date": "2025-01-02", "weights": {}}],
        "signal_timing": "prev_close",
        "calendar_source": "prices",
        "execution_delay": 1,
        "preserve_price_gaps": True,
        "inception_weights": {"510300.SH": 0.5},
        "inception_weights_auto_normalize": True,
    }
    assert _blocking_param_issues(TVB, params) == []


def test_parameters_legacy_max_weight_dict_is_normalized_to_weight_caps():
    """历史名 ``max_weight_dict`` 归一为 ``weight_caps`` 后按现名规格校验.

    远端「全天候」模型即此场景：旧名存库、schema 只声明现名，
    门禁曾因此阻断回测。
    """
    assert _blocking_param_issues(TVB, {"max_weight_dict": {"510300.SH": 0.2}}) == []
    # 归一后的键同样不报错
    assert _blocking_param_issues(TVB, {"weight_caps": {"510300.SH": 0.2}}) == []


def test_parameters_save_injected_keys_allowed_for_manual_allocation():
    """保存时固化的监控参数不属 schema，但不得阻断."""
    params = {"target_vol": 0.05, "vol_reset_threshold": 0.06, "enable_vol_reset": False}
    assert _blocking_param_issues("manual_allocation", params) == []


def test_parameters_genuinely_unknown_key_still_blocks():
    """放行集之外的无关键仍然阻断（不能为了跑通而全面放行）."""
    issues = _blocking_param_issues(TVB, {"not_a_param_at_all": 1})
    assert len(issues) == 1
    assert issues[0].level == LEVEL_BLOCKING
    assert "not_a_param_at_all" in issues[0].message


_ALL_TEMPLATE_CODES = sorted(get_class_paths())


@pytest.mark.parametrize("template_code", _ALL_TEMPLATE_CODES, ids=_ALL_TEMPLATE_CODES)
def test_gate_allows_schema_defaults_plus_runtime_keys(template_code):
    """逐模板回归：schema 默认值 + 全部运行时键 + 本模板固化键必须通过参数门禁.

    任一模板的 schema 与运行时清单不同源（保存写下的键门禁不认），
    都会在此暴露为 ``parameter_invalid``。
    """
    schema = resolve_class(template_code).get_param_schema()
    params = {p.name: copy.deepcopy(p.default) for p in schema.params}
    for key in RUNTIME_PARAM_WHITELIST:
        params.setdefault(key, {})
    for key in save_injected_keys_for(template_code):
        params.setdefault(key, 0)

    issues = _blocking_param_issues(template_code, params)
    assert not issues, f"{template_code}: {[i.message for i in issues]}"


def _stub_db_checks(monkeypatch):
    """桩替契约/资产登记校验：validate_config 的这两个用例不关心资产面，也不触库."""
    async def _no_issues(*args, **kwargs):
        return []

    monkeypatch.setattr(svc, "_check_contract", _no_issues)
    monkeypatch.setattr(svc, "_check_assets", _no_issues)


def test_validate_config_unregistered_template_blocks_instead_of_raising(monkeypatch):
    """模板不可用时给出阻断结论，不抛错.

    抛 KeyError 会被 API 转 404，前端 catch 后清空问题清单并放行——
    一个根本跑不起来的模型看起来反而「可以回测」。
    """
    _stub_db_checks(monkeypatch)
    result = _run(svc.validate_config("risk_budget_vol_target", ["510300.SH"], {}))
    assert result.applicable is False
    assert result.backtest_ready is False
    assert _level_of(result.issues, "template_not_found") == LEVEL_BLOCKING


def test_validate_config_normalizes_legacy_weight_caps_in_result(monkeypatch):
    """返回的 parameters 里历史名已归一为现名，与运行时取值同口径."""
    _stub_db_checks(monkeypatch)
    result = _run(svc.validate_config(
        TVB, ["510300.SH"], {"max_weight_dict": {"510300.SH": 0.2}}
    ))
    assert result.parameters.get("weight_caps") == {"510300.SH": 0.2}
    assert "max_weight_dict" not in result.parameters
    assert _blocking_param_issues(TVB, result.parameters) == []
