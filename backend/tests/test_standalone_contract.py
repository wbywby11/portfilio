# -*- coding: utf-8 -*-
"""独立策略交付契约守卫：支持范围边界 / 波控裁决声明 / 监控参数同口径.

三类「不报错但会算错」的偏离，都要在改代码时被测试挡下来：

1. **C0 交付边界**：``nous_low_vol`` 当前交三套口径——
   V5 FOF 三档、V6 直投版 3（含 HK_EQ 第 7 分组 + C8 混合预算）、V7。
   - description 必须写明支持与不支持的范围，前端据此提示；
   - 参数 schema 不得出现尚未实现能力的入参（C3 静态/动态模式、混合预算原始 dict）
      ——没有参数入口，就不存在「配了不生效」的假配置；
   - 已实现能力必须实际暴露参数，否则前端配不出来。
2. **D1 波控裁决**：裁决规则只在 ``schedule.resolve_vol_reset_policy`` 定义，
   策略在 ``get_execution_schedule()`` 里声明；发布快照冻结该声明，
   MonitorRuntimeConfig 透传，SignalDetector 据此分支。未声明的策略快照不写
   该键，由消费方各自回退（引擎 LEGACY 保住存量净值、监控 PROTOTYPE 保住现行行为）。
3. **D2 监控口径**：``SignalDetector._vol_params`` 读策略参数 ``vol_windows``
   / ``annualization_factor``，与回测侧 ``_realized_vol`` 同口径；参数非法时
   回退全局配置并告警，不静默改用局部值。

不触库、不启引擎、不依赖行情数据。
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from app.backtesting.schedule import (
    VOL_RESET_POLICY_LEGACY_ENGINE,
    VOL_RESET_POLICY_PROTOTYPE,
    resolve_execution_schedule,
    resolve_vol_reset_policy,
)
from app.monitor import config as monitor_config
from app.monitor.signal_detector import SignalDetector
from app.standalone_strategies.nous_low_vol.strategy import NousLowVolStrategy


def _param_names(schema) -> set:
    """参数 schema 里暴露给前端的参数名集合."""
    return {p.name for p in schema.params}


# ============================================================
# 一、C0 交付边界（V5 三档 + V6 直投版 3 + V7）
# ============================================================

def test_nous_low_vol_description_states_v5_scope():
    """description 必须同时写明支持范围与不支持清单."""
    desc = NousLowVolStrategy.get_param_schema().description or ""

    for token in ("V5", "FOF40", "FOF50", "FOF40S", "V6", "V7", "V2~V4", "暂不支持"):
        assert token in desc, (
            f"description 缺少范围声明「{token}」：前端靠这段文字提示交付边界，"
            f"缺失会让用户以为所有版本都可用"
        )


@pytest.mark.parametrize("name", [
    "aeq_floor_mode",   # C3 静态/动态模式
    "mix_budget",       # C8 原始 dict（由 mix_budget_cap + 四个系数替代）
])
def test_nous_low_vol_hides_unconfigurable_params(name):
    """越界参数不提供入口：配了不生效比看不到更糟.

    后续若真的实现某个能力，先把它从本名单移除并补上实际消费路径，
    不要让参数先于实现出现在前端。
    """
    assert name not in _param_names(NousLowVolStrategy.get_param_schema()), (
        f"{name} 出现在参数 schema 中，但当前交付范围内没有对应实现"
    )


@pytest.mark.parametrize("name", [
    "hk_eq_codes",          # HK_EQ 第 7 分组（V6 直投版）
    "mix_budget_cap",       # C8 混合风险预算上限
    "mix_budget_w_eq",      # C8 四个系数
    "mix_budget_w_gold",
    "mix_budget_w_comm",
    "mix_budget_w_qdii",
    "require_full_invest",  # 允许留现金（A 债未入选无法回填）
])
def test_nous_low_vol_exposes_implemented_params(name):
    """已实现的能力必须暴露入参，否则前端配不出对应口径."""
    assert name in _param_names(NousLowVolStrategy.get_param_schema()), (
        f"{name} 未出现在参数 schema 中，前端无法配置已实现的能力"
    )


# ============================================================
# 二、D1 波控裁决声明
# ============================================================

def test_nous_low_vol_declares_prototype_vol_reset_policy():
    """策略声明必须与原型规则逐键一致（三键全开）."""
    schedule = NousLowVolStrategy().get_execution_schedule()

    assert schedule["vol_reset_policy"] == VOL_RESET_POLICY_PROTOTYPE
    assert schedule["rebalance_freq"] == "month_end"
    assert schedule["execution_delay"] == 2


def test_resolver_carries_declared_policy_through():
    """声明经 resolve_execution_schedule 原样透传成三键布尔字典."""
    config = SimpleNamespace(rebalance_freq="month_end", execution_delay=None)

    schedule = resolve_execution_schedule(NousLowVolStrategy(), config)

    assert schedule.vol_reset_policy == VOL_RESET_POLICY_PROTOTYPE
    assert schedule.execution_delay == 2


def test_resolver_leaves_policy_empty_for_undeclared_strategy():
    """未声明时保持空字典：默认值由消费方决定，不能替存量策略选口径.

    若这里替策略补成全 True，所有未声明 vol_reset_policy 的存量策略净值
    都会变——那不是修 bug，是改口径。
    """
    class _PlainStrategy:
        pass

    config = SimpleNamespace(rebalance_freq="monthly", execution_delay=0)

    schedule = resolve_execution_schedule(_PlainStrategy(), config)

    assert schedule.vol_reset_policy == {}


def test_policy_defaults_differ_between_engine_and_monitor():
    """同一份空声明在两通道各自回退：引擎保历史、监控保现行."""
    assert resolve_vol_reset_policy(None) == VOL_RESET_POLICY_PROTOTYPE
    assert (
        resolve_vol_reset_policy(None, VOL_RESET_POLICY_LEGACY_ENGINE)
        == VOL_RESET_POLICY_LEGACY_ENGINE
    )


def test_policy_partial_declaration_keeps_other_defaults():
    """只声明一键时，其余键按默认补全，调用方永远拿到完整三键."""
    policy = resolve_vol_reset_policy({"monthly_priority": False})

    assert policy == {**VOL_RESET_POLICY_PROTOTYPE, "monthly_priority": False}


def test_policy_ignores_unknown_keys():
    """拼错的键名不得被当成有效开关（否则等于静默不生效）."""
    policy = resolve_vol_reset_policy({"monthly_priorty": False})

    assert policy == VOL_RESET_POLICY_PROTOTYPE


# ---- 声明透传：策略 → 发布快照 → 监控运行态 ----------------------------
#
# 三通道同口径的链路：策略在 get_execution_schedule() 里声明三键 → 发布时冻结进
# published_snapshot → 监控由 monitor_runtime_from_snapshot 透传到
# MonitorRuntimeConfig.vol_reset_policy → SignalDetector 据此分支。任一环不写该
# 键，监控就会按默认值执行且不报错，所以每一环都用断言锁住。


def test_published_snapshot_freezes_declared_vol_policy():
    """发布快照必须冻结策略声明的波控三键（监控只读快照，不加载策略类）."""
    from app.models.strategy_model import StrategyModel
    from app.services.published_snapshot import build_published_snapshot

    model = StrategyModel(
        name="独立策略快照桩",
        template_code="nous_low_vol",
        asset_codes=["A"],
        rebalance_frequency="monthly",
    )
    snap = build_published_snapshot(model)

    assert snap.get("vol_reset_policy") == VOL_RESET_POLICY_PROTOTYPE, (
        "发布快照未冻结策略声明的 vol_reset_policy：监控侧拿不到声明，"
        "只能按默认值执行，与引擎侧策略自述偏离"
    )


def test_published_snapshot_omits_policy_for_undeclared_strategy():
    """未声明的策略不写该键：空字典 = 未声明，默认值由消费方定."""
    from app.models.strategy_model import StrategyModel
    from app.services.published_snapshot import build_published_snapshot

    model = StrategyModel(
        name="未声明策略快照桩",
        template_code="manual_allocation",
        asset_codes=["A"],
        rebalance_frequency="monthly",
    )

    assert "vol_reset_policy" not in build_published_snapshot(model)


def test_monitor_runtime_carries_policy_from_snapshot():
    """监控运行态从快照取三键；缺键保持空，由信号检测按默认值补齐."""
    from app.monitor.monitor_runtime import monitor_runtime_from_snapshot

    snap = {
        "template_code": "nous_low_vol",
        "parameters": {},
        "asset_codes": ["A"],
        "vol_reset_policy": {"monthly_priority": False, "skip_interval_conflict": False},
    }
    rt = monitor_runtime_from_snapshot(snap)
    assert rt is not None
    assert rt.vol_reset_policy == {"monthly_priority": False, "skip_interval_conflict": False}
    # 缺声明的键按监控默认值补齐，不静默变 False
    assert resolve_vol_reset_policy(rt.vol_reset_policy) == {
        **VOL_RESET_POLICY_PROTOTYPE,
        "monthly_priority": False,
        "skip_interval_conflict": False,
    }

    bare = monitor_runtime_from_snapshot({k: v for k, v in snap.items() if k != "vol_reset_policy"})
    assert bare is not None and bare.vol_reset_policy == {}


def test_apply_snapshot_does_not_backfill_policy_into_model():
    """派生键不回填模型：写回会造出 pydantic 未声明的属性."""
    from app.models.strategy_model import StrategyModel
    from app.services.published_snapshot import apply_published_snapshot

    model = StrategyModel(
        name="回填桩",
        template_code="nous_low_vol",
        asset_codes=["A"],
        rebalance_frequency="monthly",
    )
    applied = apply_published_snapshot(
        model,
        {"asset_codes": ["A", "B"], "vol_reset_policy": VOL_RESET_POLICY_PROTOTYPE},
    )

    assert applied.asset_codes == ["A", "B"]
    assert "vol_reset_policy" not in applied.__dict__


# ============================================================
# 三、D2 监控读取策略参数
# ============================================================

def _rt(**params):
    """最小运行态桩：只需 strategy_params."""
    return SimpleNamespace(strategy_params=params)


def test_vol_params_reads_strategy_params():
    """逗号分隔文本按策略默认写法解析，年化因子取声明值."""
    windows, annualize = SignalDetector._vol_params(
        _rt(vol_windows="30,90", annualization_factor=15.0)
    )

    assert windows == (30, 90)
    assert annualize == pytest.approx(15.0)


def test_vol_params_accepts_list_form():
    """参数被 JSON 反序列化成 list 时同样可解析."""
    windows, _ = SignalDetector._vol_params(_rt(vol_windows=[10, 20]))

    assert windows == (10, 20)


def test_vol_params_defaults_to_global_config():
    """未声明时用全局配置，与 monitor.config 单源."""
    windows, annualize = SignalDetector._vol_params(_rt())

    assert windows == tuple(monitor_config.VOL_WINDOWS)
    assert annualize == pytest.approx(np.sqrt(monitor_config.ANNUALIZE_FACTOR))


def test_vol_params_ignores_none_rt():
    """rt 缺失也走全局默认，不抛异常（检测器可能在初始化阶段被调用）."""
    windows, annualize = SignalDetector._vol_params(None)

    assert windows == tuple(monitor_config.VOL_WINDOWS)
    assert annualize == pytest.approx(np.sqrt(monitor_config.ANNUALIZE_FACTOR))


@pytest.mark.parametrize("raw", ["abc", "0,-5", "", 0])
def test_vol_params_falls_back_on_invalid_windows(raw):
    """非法窗口整组回退，不做「过滤掉坏值留下好值」的半截解析."""
    windows, _ = SignalDetector._vol_params(_rt(vol_windows=raw))

    assert windows == tuple(monitor_config.VOL_WINDOWS)


@pytest.mark.parametrize("raw", [-1, 0, "abc"])
def test_vol_params_falls_back_on_invalid_annualize(raw):
    """非正数年化因子回退全局值，不允许负数直接进开方."""
    _, annualize = SignalDetector._vol_params(_rt(annualization_factor=raw))

    assert annualize == pytest.approx(np.sqrt(monitor_config.ANNUALIZE_FACTOR))


# ============================================================
# 四、原型 NAV 对账的登记状态（防「有策略无验收」）
# ============================================================

# 独立策略 code → 当前验收状态。新增独立策略必须在这里出现一行：写明用什么
# 归档数据对账，或为什么还没有 NAV 基线。
_ALIGNMENT_STATUS = {
    "nous_low_vol": (
        "原型 NAV 对账模块已移除：它按名称引用库内已入库的模型实例，本地/远端"
        "任一环境缺该实例就报错，验收结论不可复现。基线清单与原型 NAV 仍归档在 "
        "tests/regression/manifests/nous_low_vol.yaml 与 "
        "nous_low_vol_fof40_none_nav.csv（V5 FOF40 无波控档）。当前以本文件的"
        "参数暴露/隐藏与波控声明契约、test_industry_timing_base_modes.py 的 "
        "test_volatility_matches_nous_low_vol（波动率口径逐位交叉验证）、"
        "test_builtin_presets.py 的 v6/v7 预设资产与参数替代"
    ),
    "factor_score_index": (
        "原型 NAV 未归档；当前以 tests/test_factor_panel_dataset.py 的截面解析与"
        "打分守卫、research/数据文档 的导入门禁替代"
    ),
    "bond_factor_score_index": (
        "以 tests/regression/test_bond_factor_score_index.py 的逐期成分对账"
        "（panel_periods.csv）替代 NAV 对账"
    ),
    "dividend_garp": (
        "以 tests/regression/dividend_garp_recon_equity.csv 的逐日 NAV 对账"
        "（原型 out_py/nav_daily.csv，2021-01-04 起共 1389 日，逐日偏差上限"
        " 3.60e-06、调仓日 69/69、权重 Δ≤7.3e-09）替代原型清单"
    ),
    "industry_timing_target_vol": (
        "以 tests/regression/industry_timing_target_vol_recon.csv 的逐日 NAV 对账"
        "（2017-07-24 ~ 2026-07-17 共 2181 日，逐日偏差上限 8.63e-08、"
        "相对偏差上限 6.57e-08）替代原型清单"
    ),
    "erp_timing_enhance": (
        "全区间原型 NAV 基线未归档：源数据 tushare fund_nav.adj_nav 自 2026-06-02 起"
        "退化为 accum_nav，池内 45 只存在复权口径断裂（其中 3 只单日跳变 >20% 被数据"
        "契约剔除），基线待行情重取后补。当前以最近一期（2026-10-13）逐层核对替代："
        "ERP 分位 q_erp=0.6619565217391304、三战术信号 S=-3、权益仓位"
        " w_equity=0.01968817300493271 与原型手工核算逐位一致；回测/监控/组合三通道"
        "调仓日与选样集合一致，组合与回测 total_return 相对差 1e-16 量级"
    ),
}


def test_every_standalone_strategy_has_alignment_status():
    """独立策略清单与验收登记表必须一一对应.

    登记表缺项就是「有策略无验收」的静默失效形态。本断言把现状固定
    下来：新增独立策略必须先回答「原型怎么对账」。
    """
    from app.allocation.strategy_manifest import STRATEGY_MANIFEST

    standalone = {
        code for code, entry in STRATEGY_MANIFEST.items()
        if entry.strategy_form == "standalone"
    }

    assert standalone == set(_ALIGNMENT_STATUS), (
        f"独立策略与验收登记表不一致：未登记 "
        f"{sorted(standalone - set(_ALIGNMENT_STATUS))}；"
        f"登记表多余 {sorted(set(_ALIGNMENT_STATUS) - standalone)}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
