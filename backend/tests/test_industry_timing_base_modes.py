# -*- coding: utf-8 -*-
"""``industry_timing_target_vol`` 月末配置双口径守卫：默认不变 + 逆波动率备选.

该策略的月末大类配置新增了 ``base_alloc_mode`` 两选一：

* ``risk_budget``（默认）—— 权益/债券组内等风险贡献 + 四桶目标波动等式，原型口径；
* ``inverse_vol`` —— 不分组、不做风险平价，按各资产多窗口年化波动倒数的
  ``(1/N)×(1/σ)`` 分配后整体缩放到 ``vol_target``，剩余进现金代理，nous 口径。

三类风险在测试里各自被锁住：

1. **默认口径不变**：缺省参数必须仍走 ``risk_budget``，且该分支的解与「直接用
   协方差手工调 ``_bucket_mapping`` + ``_solve_buckets``」逐位一致——任何人把
   逆波动率逻辑掺进默认分支，这条会挂；
2. **备选口径的数学性质**：权重与 ``1/σ`` 成正比、合计恒为 1、现金等于残余、
   风险资产组合波动恰等于 ``vol_target``、多窗口取最大值——并与
   ``nous_low_vol`` 的 ``asset_volatility`` / ``portfolio_volatility`` 交叉验证，
   保证「复现的是同一套口径」而不是另写一套形似的；
3. **失败路径不静默降级**：非法模式、历史不足、σ 不可估、目标波动超过无杠杆
   上限都直接报错，不裁权重、不退化等权。

不触库、不启引擎、不依赖真实行情。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.standalone_strategies.industry_timing_target_vol.strategy import (
    IndustryTimingTargetVolStrategy,
    _inverse_vol_config,
    _multi_window_vol,
    _solve_buckets,
    _bucket_mapping,
    _weighted_port_vol,
)

_TAG = "industry_timing_target_vol"

# 与 allocate 里 assets 的顺序一致：权益 4 → 黄金 1 → 债券 4 → 现金 1
_ASSETS = ("EQ1", "EQ2", "EQ3", "EQ4", "GOLD", "B1", "B2", "B3", "B4", "CASH")

# 年化波动率（含现金腿：risk_budget 分支要解协方差，恒定价格会让协方差非正定）
_VOLS = {
    "EQ1": 0.20, "EQ2": 0.24, "EQ3": 0.18, "EQ4": 0.16,
    "GOLD": 0.14,
    "B1": 0.02, "B2": 0.03, "B3": 0.04, "B4": 0.05,
    "CASH": 0.001,
}

# 回测里模式与窗口都是参数，测试用短窗口压耗时
_BASE_PARAMS = {
    "base_alloc_mode": "risk_budget",
    "cov_window": 252,
    "cov_windows": (63, 252),
    "vol_target": 0.0125,
    "vol_max": 0.015,
    "min_history_days": 300,
    "anchor": None,
}


def _prices(days: int = 320, end: str = "2024-12-31", seed: int = 20261103,
            vols: dict | None = None) -> pd.DataFrame:
    """生成到 ``end`` 为止的日频价格；``end`` 恰为当月最后一个工作日."""
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=days)
    sigma = {k: v / np.sqrt(252.0) for k, v in dict(_VOLS if vols is None else vols).items()}
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {code: 100.0 * np.exp(np.cumsum(rng.normal(0.0, sigma[code], len(idx))))
         for code in _ASSETS},
        index=idx,
    )


def _params(**overrides):
    """策略参数（去掉测试专用的 anchor 占位，其余透传）."""
    out = {k: v for k, v in _BASE_PARAMS.items() if k != "anchor"}
    out.update(overrides)
    return out


@pytest.fixture(scope="module")
def px() -> pd.DataFrame:
    return _prices()


@pytest.fixture()
def strategy() -> IndustryTimingTargetVolStrategy:
    return IndustryTimingTargetVolStrategy()


# ============================================================
# 一、默认口径不变（回归保护）
# ============================================================

def test_default_mode_is_risk_budget(strategy):
    """缺省参数必须仍走原型口径，窗口默认与 nous 一致."""
    cfg = strategy._parse_config({})

    assert cfg["base_alloc_mode"] == "risk_budget"
    assert cfg["inv_vol_windows"] == (22, 65, 130)


def test_risk_budget_solution_matches_bucket_math(px, strategy):
    """默认分支的解必须等于「协方差 → 组内等风险贡献 → 四桶目标波动」直算.

    这条是口径锚：逆波动率逻辑若渗进 risk_budget 分支，权重会立刻偏离。
    """
    assets = list(_ASSETS)
    cfg = strategy._parse_config(_params(base_alloc_mode="risk_budget"))

    got = strategy._orig_weights(px, assets, cfg, {})

    rets = px[assets].pct_change(fill_method=None).iloc[1:]
    cov = rets.tail(cfg["cov_window"]).cov().to_numpy() * float(cfg["ann_days"])
    mapping = _bucket_mapping(cov)
    buckets, _loss = _solve_buckets(mapping.T @ cov @ mapping, float(cfg["vol_target"]))
    expected = mapping @ buckets

    np.testing.assert_allclose(got, expected, rtol=0, atol=1e-12)


def test_schema_exposes_both_modes(strategy):
    """前端要能选到两种口径；默认值必须落在 options 内."""
    schema = IndustryTimingTargetVolStrategy.get_param_schema()
    params = {p.name: p for p in schema.params}

    mode = params["base_alloc_mode"]
    assert mode.type == "select"
    assert mode.default == "risk_budget"
    assert {value for value, _label in mode.options} == {"risk_budget", "inverse_vol"}

    win = params["inv_vol_windows"]
    assert win.type == "text"
    assert win.default == "22,65,130"
    assert win.group == "advanced"
    assert win.condition == {"field": "base_alloc_mode", "value": "inverse_vol"}, (
        "倒数波动窗口只在逆波动率模式下生效，缺失 condition 会让默认口径的用户"
        "看到一个不影响结果的参数"
    )


# ============================================================
# 二、逆波动率口径的数学性质
# ============================================================

def test_inverse_vol_weights_proportional_to_inverse_sigma(px, strategy):
    """风险资产权重之比 = 波动率之比的倒数."""
    cfg = strategy._parse_config(_params(base_alloc_mode="inverse_vol", vol_target=0.001))
    assets = list(_ASSETS)

    w, _info = _inverse_vol_config(px, assets, cfg)

    vols = _multi_window_vol(px[assets[:-1]], cfg["inv_vol_windows"], cfg["ann_days"])
    for i in range(len(assets) - 1):
        for j in range(i + 1, len(assets) - 1):
            expected = float(vols[assets[j]]) / float(vols[assets[i]])
            assert w[i] / w[j] == pytest.approx(expected, rel=1e-9)


def test_inverse_vol_sums_to_one_and_cash_takes_remainder(px, strategy):
    """目标可达时：权重合计 1，现金代理 = 1 − 风险资产合计."""
    cfg = strategy._parse_config(_params(base_alloc_mode="inverse_vol", vol_target=0.001))

    w, info = _inverse_vol_config(px, list(_ASSETS), cfg)

    assert info["capped"] is False
    assert w.sum() == pytest.approx(1.0, abs=1e-12)
    assert w[-1] > 0
    assert w[-1] == pytest.approx(1.0 - w[:-1].sum(), abs=1e-12)
    assert (w >= 0).all()


def test_inverse_vol_hits_target_vol_when_reachable(px, strategy):
    """目标可达时，缩放后风险资产组合波动恰等于 vol_target（nous 的 _vol_scale 口径）."""
    cfg = strategy._parse_config(_params(base_alloc_mode="inverse_vol", vol_target=0.001))
    assets = list(_ASSETS)

    w, info = _inverse_vol_config(px, assets, cfg)
    realized = _weighted_port_vol(
        px[assets[:-1]],
        pd.Series(w[:-1], index=assets[:-1]),
        cfg["inv_vol_windows"],
        cfg["ann_days"],
    )

    assert info["capped"] is False
    assert realized == pytest.approx(float(cfg["vol_target"]), rel=1e-9)


def test_unreachable_target_caps_to_full_invest(strategy):
    """目标波动在无杠杆下不可达时：按 nous 同款压回满仓，波动低于目标且审计记 capped.

    本策略默认池的常态分支：真实中债年化波动约 0.3%~1.2%，1/σ 组合的事前波动
    只有约 33bp，而目标 125bp 需要 3.8 倍权重。必须与 nous 的 ``_vol_scale`` 一致
    （报错会让该选项在默认参数下不可用）；关键是不能静默：``inv_vol_capped``
    与缩放倍数写进审计。
    """
    px = _prices(vols={**_VOLS, "B1": 0.003, "B2": 0.005, "B3": 0.008, "B4": 0.012})
    cfg = strategy._parse_config(_params(base_alloc_mode="inverse_vol"))
    assets = list(_ASSETS)

    w, info = _inverse_vol_config(px, assets, cfg)

    assert info["capped"] is True
    assert info["normalized_vol"] < float(cfg["vol_target"])
    assert w.sum() == pytest.approx(1.0, abs=1e-12)
    assert w[-1] == pytest.approx(0.0, abs=1e-12)
    realized = _weighted_port_vol(
        px[assets[:-1]],
        pd.Series(w[:-1], index=assets[:-1]),
        cfg["inv_vol_windows"],
        cfg["ann_days"],
    )
    # scale 作用在未归一化的 1/σ 权重上；压回满仓后的实际波动 = 1/σ 组合的归一化波动
    assert realized == pytest.approx(info["normalized_vol"], rel=1e-9)
    assert realized < float(cfg["vol_target"])


def test_multi_window_vol_takes_maximum():
    """短窗口波动更高时取短窗口值（多窗口取最大，不是取最近窗口）."""
    idx = pd.bdate_range("2024-01-01", periods=200)
    # 前 180 天 ±0.05%，后 20 天 ±5%：短窗口波动远高于长窗口
    rets = np.concatenate([np.tile([0.0005, -0.0005], 90), np.tile([0.05, -0.05], 10)])
    px = pd.DataFrame({"X": 100.0 * np.exp(np.cumsum(rets))}, index=idx)

    vol = _multi_window_vol(px, (20, 150), 252).iloc[0]

    seg = px["X"].pct_change(fill_method=None).iloc[1:]
    short = float(seg.iloc[-20:].std()) * np.sqrt(252.0)
    long = float(seg.iloc[-150:].std()) * np.sqrt(252.0)
    assert short > long
    assert vol == pytest.approx(short, rel=1e-12)


def test_volatility_matches_nous_low_vol(px):
    """与 nous_low_vol 的波动率口径逐位一致（复现同一套算法，不另写形似的）."""
    from app.standalone_strategies.nous_low_vol.strategy import (
        asset_volatility,
        portfolio_volatility,
    )

    windows = (22, 65, 130)
    annualize = np.sqrt(252.0)
    mine = _multi_window_vol(px, windows, 252)
    theirs = asset_volatility(px, len(px) - 1, windows, annualize)
    np.testing.assert_allclose(mine[list(px.columns)].to_numpy(),
                               theirs[list(px.columns)].to_numpy(), rtol=1e-12)

    w = pd.Series(
        [0.11, 0.09, 0.08, 0.07, 0.05, 0.12, 0.1, 0.09, 0.08, 0.01],
        index=list(px.columns),
    )
    assert _weighted_port_vol(px, w, windows, 252) == pytest.approx(
        portfolio_volatility(px, w, len(px) - 1, windows, annualize), rel=1e-12
    )


# ============================================================
# 三、失败路径：报错而非裁剪（禁静默降级）
# ============================================================

def test_invalid_mode_rejected(strategy):
    """模式拼错直接报错，不回退到默认口径."""
    with pytest.raises(ValueError, match="base_alloc_mode"):
        strategy._parse_config({"base_alloc_mode": "equal_weight"})


def test_insufficient_history_raises(strategy):
    """全部窗口都凑不满时报错，不跳过资产、不缩小窗口."""
    px = _prices(days=40)
    cfg = strategy._parse_config(
        _params(base_alloc_mode="inverse_vol", inv_vol_windows="65,130", min_history_days=300)
    )

    with pytest.raises(ValueError, match="无法估计"):
        _inverse_vol_config(px, list(_ASSETS), cfg)


def test_zero_volatility_asset_raises(px, strategy):
    """某资产价格恒定（σ=0）时 1/σ 无意义，报错而不是给它无穷权重."""
    bad = px.copy()
    bad["B3"] = 100.0
    cfg = strategy._parse_config(_params(base_alloc_mode="inverse_vol"))

    with pytest.raises(ValueError, match="无法估计"):
        _inverse_vol_config(bad, list(_ASSETS), cfg)


def test_param_consistency_gates_windows_only_in_inverse_mode(strategy):
    """窗口超过最小历史只在逆波动率模式下拦截；默认口径不受该参数影响."""
    groups = {
        "equity_codes": ",".join(_ASSETS[:4]),
        "commodity_codes": _ASSETS[4],
        "bond_codes": ",".join(_ASSETS[5:9]),
        "cash_codes": _ASSETS[9],
        "industry_codes": "I1,I2,I3,I4,I5",
        "market_codes": "MKT",
    }
    common = {**groups, "inv_vol_windows": "900", "min_history_days": 300}

    reason = strategy._check_param_consistency(
        pd.DataFrame(), {**common, "base_alloc_mode": "inverse_vol"}
    )
    assert reason and "倒数波动窗口" in reason

    assert strategy._check_param_consistency(
        pd.DataFrame(), {**common, "base_alloc_mode": "risk_budget"}
    ) is None, "risk_budget 下 inv_vol_windows 不参与计算，不应拦住运行"


# ============================================================
# 四、缓存隔离与审计透出
# ============================================================

def test_cache_key_separates_modes(px, strategy):
    """切模式不得命中上一模式的解；各自重复调用稳定命中自己的缓存."""
    assets = list(_ASSETS)
    cfg_rb = strategy._parse_config(_params(base_alloc_mode="risk_budget"))
    cfg_iv = strategy._parse_config(_params(base_alloc_mode="inverse_vol"))

    w_rb = strategy._orig_weights(px, assets, cfg_rb, {})
    w_iv = strategy._orig_weights(px, assets, cfg_iv, {})

    assert not np.allclose(w_rb, w_iv), "两种口径给出相同解，说明模式分支没生效"
    np.testing.assert_array_equal(strategy._orig_weights(px, assets, cfg_rb, {}), w_rb)
    np.testing.assert_array_equal(strategy._orig_weights(px, assets, cfg_iv, {}), w_iv)
    assert len(strategy._state["bucket_cache"]) == 2


def test_audit_and_metrics_expose_mode(strategy):
    """审计与监控指标都要写明本期用的哪套口径，前端据此区分历史净值."""
    cfg = strategy._parse_config(_params(base_alloc_mode="inverse_vol", inv_vol_windows="22,65"))
    groups = {key: [] for key in ("EQ", "GOLD", "BOND", "CASH", "IND", "MKT")}
    groups["EQ"] = list(_ASSETS[:4])
    groups["GOLD"] = [_ASSETS[4]]
    groups["BOND"] = list(_ASSETS[5:9])
    groups["CASH"] = [_ASSETS[9]]
    final = np.zeros(10)
    final[0] = 1.0

    audit = strategy._audit(
        cfg=cfg, groups=groups, neutral=final, final=final, alpha=1.0,
        dar=1.0, active=False, event_date=None, event_w={},
        signal_date=pd.Timestamp("2024-12-31"),
    )

    assert audit["base_alloc_mode"] == "inverse_vol"
    assert audit["inv_vol_windows"] == [22, 65]

    metrics = strategy.compute_monitoring_metrics(pd.Series(dtype=float), pd.DataFrame())
    assert metrics["base_alloc_mode"] == "inverse_vol"
    assert metrics["inv_vol_capped"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
