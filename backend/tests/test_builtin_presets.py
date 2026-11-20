# -*- coding: utf-8 -*-
"""内置策略预设的结构守卫.

预设是「策略原型的配置声明」，一旦结构写错，前端展开出的资产池与参数
会与原型不一致，且不会在运行时立刻报错（只会算错）。本测试覆盖四类偏离：

1. **归属**：``template_code`` 必须在策略清单里且为独立策略形态；
2. **键域**：``parameters`` 与 ``asset_selection.groups`` 的键必须是该模板
   参数 schema 里真实存在的参数名，否则配了也不生效；
3. **结构**：组内无重复代码、组间无重叠、code 唯一且带模板前缀；
4. **取值**：V6/V7 四档的 ``select_count`` 与池规模逐格断言，不写「其余同上」。

另测 ``preset_content_hash`` 的稳定性与敏感性——``preset_version`` 靠它判断
「模型所基于的预设定义是否已被改动」，hash 不稳会让所有模型误报「基于旧版」。

不触库、不启引擎、不依赖行情数据。
"""
from __future__ import annotations

import copy

import pytest

from app.allocation.builtin_presets import (
    PRESET_CODE_SEP,
    PRESETS,
    find_preset,
    get_presets_for,
    list_preset_summaries,
    preset_content_hash,
)
from app.allocation.strategy_manifest import STRATEGY_MANIFEST, resolve_class


def _schema_param_names(template_code: str) -> set:
    """模板参数 schema 暴露的参数名集合."""
    cls = resolve_class(template_code)
    return {p.name for p in cls.get_param_schema().params}


def _all_group_codes(preset: dict) -> list:
    """预设展开前的全部资产代码（仅 explicit 模式的 groups）."""
    out: list = []
    groups = (preset.get("asset_selection") or {}).get("groups") or {}
    for codes in groups.values():
        out.extend(codes or [])
    return out


# ============================================================
# 一、归属与键域
# ============================================================

def test_presets_not_empty():
    assert PRESETS, "预设清单为空，前端下拉将没有任何可选项"


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_template_code_registered_as_standalone(preset):
    """预设只能挂在已注册的独立策略模板上."""
    code = preset["template_code"]
    assert code in STRATEGY_MANIFEST, f"template_code {code!r} 未在 STRATEGY_MANIFEST 注册"
    assert STRATEGY_MANIFEST[code].strategy_form == "standalone", (
        f"{code} 不是独立策略形态，预设的资产分组写回逻辑只对独立策略成立"
    )


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_parameter_keys_exist_in_schema(preset):
    """参数键必须是 schema 里真实存在的参数名."""
    valid = _schema_param_names(preset["template_code"])
    unknown = sorted(set(preset.get("parameters") or {}) - valid)
    assert not unknown, f"{preset['code']} 含 schema 未定义的参数：{unknown}"


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_group_keys_exist_in_schema(preset):
    """分组键必须是 schema 里的 *_codes 参数名，否则写回时无人消费."""
    valid = _schema_param_names(preset["template_code"])
    groups = (preset.get("asset_selection") or {}).get("groups") or {}
    unknown = sorted(set(groups) - valid)
    assert not unknown, f"{preset['code']} 含 schema 未定义的分组参数：{unknown}"


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_parameters_do_not_declare_codes(preset):
    """声明层单一事实源：parameters 里不写任何分组代码参数。

    分组只存在于 asset_selection 一处，写回由 resolve 统一完成；
    否则两份来源必然漂移。判定按契约声明的 group_params，
    不按 ``*_codes`` 后缀——``series_codes`` 这类非分组参数不在此列。
    """
    cls = resolve_class(preset["template_code"])
    group_params = set(cls.get_data_contract().group_params or {})
    leaked = sorted(k for k in (preset.get("parameters") or {}) if k in group_params)
    assert not leaked, f"{preset['code']} 的 parameters 里出现了分组代码字段：{leaked}"


# ============================================================
# 二、结构
# ============================================================

def test_preset_codes_unique_and_prefixed():
    codes = [p["code"] for p in PRESETS]
    assert len(codes) == len(set(codes)), "预设 code 重复"
    for p in PRESETS:
        assert p["code"].startswith(f"{p['template_code']}{PRESET_CODE_SEP}"), (
            f"预设 code {p['code']!r} 未以 {p['template_code']}{PRESET_CODE_SEP} 开头"
        )


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_group_codes_no_duplicate_within_group(preset):
    groups = (preset.get("asset_selection") or {}).get("groups") or {}
    for name, codes in groups.items():
        assert len(codes) == len(set(codes)), f"{preset['code']} 的 {name} 组内有重复代码"


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_group_codes_no_overlap_between_groups(preset):
    seen: dict = {}
    groups = (preset.get("asset_selection") or {}).get("groups") or {}
    for name, codes in groups.items():
        for code in codes:
            assert code not in seen, (
                f"{preset['code']} 中 {code} 同时出现在 {seen[code]} 与 {name} 两组"
            )
            seen[code] = name


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_rebalance_frequency_declared(preset):
    assert preset.get("rebalance_frequency"), f"{preset['code']} 未声明调仓频率"


# ============================================================
# 三、V6/V7 逐格断言（对 research/涌鑫低波版指数/低波版模型/config_versions.py）
# ============================================================

# (preset_code, select_count, 池规模, 各组规模)
# 原型定义：_POOL_V6 = 5 债 + 5 A股 + 2 港股 + 4 商品 = 16
#           V6_D1 = 去掉 159531（A股 4）→ 15
#           V6_D2 = 去掉 159262（港股 1）→ 15
#           V7    = 5 债 + 3 A股 + 3 QDII + 4 商品 = 15
_V6V7_EXPECT = [
    (
        f"nous_low_vol{PRESET_CODE_SEP}v6_d1", 11, 15,
        {"a_bond_codes": 5, "a_eq_codes": 4, "hk_eq_codes": 2,
         "qdii_codes": 0, "qdii_usd_codes": 0, "comm_codes": 4, "gold_codes": 0},
    ),
    (
        f"nous_low_vol{PRESET_CODE_SEP}v6_d2", 11, 15,
        {"a_bond_codes": 5, "a_eq_codes": 5, "hk_eq_codes": 1,
         "qdii_codes": 0, "qdii_usd_codes": 0, "comm_codes": 4, "gold_codes": 0},
    ),
    (
        f"nous_low_vol{PRESET_CODE_SEP}v6_d3", 12, 16,
        {"a_bond_codes": 5, "a_eq_codes": 5, "hk_eq_codes": 2,
         "qdii_codes": 0, "qdii_usd_codes": 0, "comm_codes": 4, "gold_codes": 0},
    ),
    (
        f"nous_low_vol{PRESET_CODE_SEP}v7", 11, 15,
        {"a_bond_codes": 5, "a_eq_codes": 3, "hk_eq_codes": 0,
         "qdii_codes": 3, "qdii_usd_codes": 0, "comm_codes": 4, "gold_codes": 0},
    ),
]


@pytest.mark.parametrize(
    "preset_code,select_count,pool_size,group_sizes", _V6V7_EXPECT,
    ids=[row[0] for row in _V6V7_EXPECT],
)
def test_v6_v7_matches_prototype(preset_code, select_count, pool_size, group_sizes):
    preset = find_preset(preset_code)
    assert preset is not None, f"未找到预设 {preset_code}"

    assert preset["parameters"]["select_count"] == select_count
    assert preset["min_history_days"] == 260

    groups = preset["asset_selection"]["groups"]
    assert {k: len(v) for k, v in groups.items()} == group_sizes
    assert len(_all_group_codes(preset)) == pool_size


def test_v6_d1_excludes_zhongzheng2000_only():
    """V6_D1 的差异点是 A 股端缺 159531，港股端仍两只全含."""
    groups = find_preset(f"nous_low_vol{PRESET_CODE_SEP}v6_d1")["asset_selection"]["groups"]
    assert "159531.SZ" not in groups["a_eq_codes"]
    assert "510880.SH" in groups["a_eq_codes"]
    assert groups["hk_eq_codes"] == ["513600.SH", "159262.SZ"]


def test_v6_d2_excludes_hk_tech_only():
    """V6_D2 的差异点是港股端缺 159262，A 股端仍五只全含."""
    groups = find_preset(f"nous_low_vol{PRESET_CODE_SEP}v6_d2")["asset_selection"]["groups"]
    assert groups["hk_eq_codes"] == ["513600.SH"]
    assert "159531.SZ" in groups["a_eq_codes"]
    assert "510880.SH" in groups["a_eq_codes"]


def test_v6_v7_constraint_params():
    """V6/V7 只保留 C0 + C8 两条约束，其余全部关闭."""
    for code, mix_w_qdii, qdii_cap in (
        (f"nous_low_vol{PRESET_CODE_SEP}v6_d1", 1.0, 0),
        (f"nous_low_vol{PRESET_CODE_SEP}v6_d2", 1.0, 0),
        (f"nous_low_vol{PRESET_CODE_SEP}v6_d3", 1.0, 0),
        (f"nous_low_vol{PRESET_CODE_SEP}v7", 3.75, 0.03),
    ):
        params = find_preset(code)["parameters"]
        assert params["mix_budget_cap"] == 0.20
        assert params["mix_budget_w_qdii"] == mix_w_qdii
        assert params["qdii_cap"] == qdii_cap
        # 关闭项
        assert params["comm_cap"] == 0
        assert params["risk_budget_cap"] == 0
        assert params["abond_floor"] == 0
        assert params["abond_cap"] == 0
        assert params["abond_usd_cap"] == 0
        assert params["aeq_floor_offset"] == 0
        assert params["aq_floor"] == 0
        assert params["aeq_risk_cap"] == 0
        assert params["comm_cap_per"] == 0
        # 无波控
        assert params["target_vol"] == 0
        assert params["enable_daily_vol_control"] is False


# ============================================================
# 四、preset_content_hash
# ============================================================

@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_hash_is_stable(preset):
    """同一份定义多次计算结果一致——跨进程也不能变（故不能用内置 hash）."""
    assert preset_content_hash(preset) == preset_content_hash(preset)
    assert len(preset_content_hash(preset)) == 8


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_hash_changes_on_parameter_change(preset):
    """任一参数改动都必须改变 hash（不假设每个预设都有 select_count）."""
    params = preset["parameters"]
    key = next(k for k, v in sorted(params.items()) if isinstance(v, (int, float)))
    mutated = copy.deepcopy(preset)
    mutated["parameters"][key] = params[key] + 1
    assert preset_content_hash(mutated) != preset_content_hash(preset)


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_hash_changes_on_asset_pool_change(preset):
    """显式分组砍掉一只资产后 hash 必须改变；标签池没有显式分组，此项不适用."""
    groups = preset["asset_selection"].get("groups") or {}
    non_empty = [k for k, v in groups.items() if v]
    if not non_empty:
        pytest.skip("标签池预设不声明显式分组")
    mutated = copy.deepcopy(preset)
    first = non_empty[0]
    mutated["asset_selection"]["groups"][first] = groups[first][:-1]
    assert preset_content_hash(mutated) != preset_content_hash(preset)


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_hash_ignores_display_text(preset):
    """name / description 是说明文字，改动不构成预设版本变化."""
    mutated = copy.deepcopy(preset)
    mutated["name"] = mutated["name"] + "（改名）"
    mutated["description"] = "说明文字调整"
    assert preset_content_hash(mutated) == preset_content_hash(preset)


# ============================================================
# 五、查询接口
# ============================================================

def test_get_presets_for_filters_by_template():
    got = get_presets_for("nous_low_vol")
    assert len(got) == 4
    assert all(p["template_code"] == "nous_low_vol" for p in got)
    assert get_presets_for("risk_parity") == []


def test_list_preset_summaries_shape():
    summaries = list_preset_summaries("nous_low_vol")
    assert len(summaries) == 4
    for item in summaries:
        assert set(item) == {
            "code", "template_code", "name", "description",
            "version_tag", "source", "preset_version",
        }
        assert item["source"] == "builtin"
        assert len(item["preset_version"]) == 8
    # 全量查询覆盖全部预设
    assert len(list_preset_summaries()) == len(PRESETS)


def test_find_preset_unknown_returns_none():
    assert find_preset("not_a_preset") is None


# ============================================================
# 六、其余五个独立策略的预设
# ============================================================

_STANDALONE_TEMPLATES = [
    "nous_low_vol",
    "factor_score_index",
    "bond_factor_score_index",
    "dividend_garp",
    "industry_timing_target_vol",
    "erp_timing_enhance",
]


def test_every_standalone_template_has_preset():
    """六个独立策略都至少有一个预设，否则前端下拉存在空白页."""
    for code in _STANDALONE_TEMPLATES:
        assert get_presets_for(code), f"模板 {code} 没有任何预设"


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["code"])
def test_tag_mode_declares_tags(preset):
    """标签模式必须声明非空 tags，否则 resolve 会报 blocking 的 tag_empty."""
    card = preset["asset_selection"]
    if card.get("mode") not in ("tags", "hybrid"):
        return
    assert card.get("tags"), f"{preset['code']} 是 {card['mode']} 模式但未声明 tags"


def test_factor_presets_use_tag_pool():
    """股池/券池会随时间变化，两个因子策略走标签池而不是写死代码."""
    for code, tag in (
        ("factor_score_index", "pool:equity_quality_growth"),
        ("bond_factor_score_index", "pool:bond_phoenix50"),
    ):
        presets = get_presets_for(code)
        assert len(presets) == 1
        card = presets[0]["asset_selection"]
        assert card["mode"] == "tags"
        assert card["tags"] == [tag]
        # 标签池不声明显式分组（这两个模板也没有 *_codes 参数）
        assert not card.get("groups")


def test_dividend_garp_pool_shape():
    presets = get_presets_for("dividend_garp")
    assert len(presets) == 1
    preset = presets[0]
    assert preset["asset_selection"]["mode"] == "explicit"
    groups = preset["asset_selection"]["groups"]
    assert {k: len(v) for k, v in groups.items()} == {
        "dividend_codes": 2, "growth_codes": 1, "bond_codes": 1,
    }
    assert len(_all_group_codes(preset)) == 4
    # 债腿用短期纯债基金指数而非 ETF（与对账模型同口径）
    assert groups["bond_codes"] == ["992618.SSI"]
    # 年费只挂在两只全收益指数上：ETF 复权净值已含管理费，重复计提会低估净值
    assert preset["parameters"]["tool_fee_codes"] == "931231CNY01.CSI,931579CNY01.CSI"
    assert "512890.OF" not in preset["parameters"]["tool_fee_codes"]
    # 估值序列代码与回看年数取自 schema 默认值，必须显式写死以免默认值变动
    assert preset["parameters"]["pe_code"] == "H00922_PE"
    assert preset["parameters"]["pe_years"] == 3
    assert preset["parameters"]["pe_hi"] == 0.80
    assert preset["parameters"]["pe_lo"] == 0.70


def test_industry_timing_pool_shape():
    presets = get_presets_for("industry_timing_target_vol")
    assert len(presets) == 1
    preset = presets[0]
    groups = preset["asset_selection"]["groups"]
    assert set(groups) == {
        "equity_codes", "commodity_codes", "bond_codes",
        "cash_codes", "industry_codes", "market_codes",
    }
    # 参数自洽：权益恰 4 只、现金与市场基准各 1 只、行业至少 5 只
    assert len(groups["equity_codes"]) == 4
    assert len(groups["cash_codes"]) == 1
    assert len(groups["market_codes"]) == 1
    assert len(groups["industry_codes"]) == 31
    # 42 = 4 权益 + 1 黄金 + 4 债 + 1 现金 + 31 行业 + 1 基准
    assert len(_all_group_codes(preset)) == 42
    # 最少历史必须大于 756 日协方差窗口
    assert preset["min_history_days"] == 760
    assert preset["parameters"]["min_history_days"] == 760
    # 目标波动不得高于波动上限（_check_param_consistency 的同口径）
    assert preset["parameters"]["vol_target"] <= preset["parameters"]["vol_max"]
    # 策略原生调仓频率为日频，预设不得降级为月频
    assert preset["rebalance_frequency"] == "日"
    # 择时候选去掉申万综合（801230.SL）：综合是各行业加权合成体，不是单一赛道
    candidates = preset["parameters"]["industry_candidates"].split(",")
    assert len(candidates) == 30
    assert "801230.SL" not in candidates
    assert set(candidates) < set(groups["industry_codes"])


def test_erp_timing_pool_shape():
    presets = get_presets_for("erp_timing_enhance")
    assert len(presets) == 1
    preset = presets[0]
    groups = preset["asset_selection"]["groups"]
    params = preset["parameters"]
    # 风格指数必须恰 6 只且顺序固定
    assert groups["style_codes"] == [
        "399372.SZ", "399373.SZ", "399374.SZ",
        "399375.SZ", "399376.SZ", "399377.SZ",
    ]
    # 宽基基准与债券腿各恰 1 只
    assert len(groups["bench_codes"]) == 1
    assert groups["bond_codes"] == ["CBA00121.CS"]
    # 基金池规模必须不少于选样数量
    assert len(groups["fund_codes"]) >= params["select_count"]
    # 池子为场内指数增强品种（增强 ETF + 增强 LOF），换池时必须同步改预设与测试
    assert len(groups["fund_codes"]) == 60
    # 持仓只买场内：不得出现场外基金代码
    assert all(c.endswith((".SH", ".SZ")) for c in groups["fund_codes"])
    # 159209 行情起点与 A500 指数发布时间矛盾（串位数据），不得入池
    assert "159209.SZ" not in groups["fund_codes"]
    # 赛道基准不得重复；创业板用指数 399006.SZ 而非 ETF 159915.SZ
    assert len(groups["track_codes"]) == len(set(groups["track_codes"]))
    assert "399006.SZ" in groups["track_codes"]
    assert "159915.SZ" not in groups["track_codes"]
    # 五条宏观序列顺序固定
    assert params["series_codes"] == "DIV,Y_CN10Y,Y_US10Y_RAW,FX_CFETS,LOAN_MLT"
