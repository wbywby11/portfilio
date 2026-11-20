# -*- coding: utf-8 -*-
"""bond_factor_score_index 回归与单元测试.

基线数据全部来自 ``tests/regression/bond_factor_score_index/`` 归档（随仓库走，
不依赖任何外部原型目录）：

  baseline_nav.csv            官方点位 rebase 100 + 变体A 基线净值 + 调样生效日标记
  prices.parquet              387 券全收益价格指数矩阵
  factor_panel_2026Q4.csv     2026Q4 全池 548 行因子截面（含官方得分/官方入选）
  factor_panel_snapshots.csv  27 期历史成分快照截面
  panel_periods.csv           28 期 as_of(决策日) ↔ effective(生效日) 对照

覆盖四层：打分公式 → 选样名单 → 净值（引擎归因约定）→ 注册与错误路径。

用法：
  py -m pytest tests/regression/test_bond_factor_score_index.py -s
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.standalone_strategies.bond_factor_score_index.strategy import (  # noqa: E402
    BondFactorScoreIndexStrategy,
    equal_weights,
    rank_score,
    target_distance_score,
)

BASELINE_DIR = PROJECT_ROOT / "tests" / "regression" / "bond_factor_score_index"

# 官方得分复现容差：原型对账实测 max_err=2.8e-14，放两位数量级仍远小于打分尺度
SCORE_TOL = 1e-6
# 变体A 基线复现容差：等权权重 round(1/N, 8) 引入的累积误差量级
NAV_SELF_TOL = 1e-6
# 与官方点位的可执行口径累计差（不含现金桶），归档实测 2.633e-4，留余量
NAV_OFFICIAL_TOL = 5e-4
# 调样日阶跃阈值：变体A 无阶跃（探针实测 <1e-5），变体B 有 3.9e-4 阶跃
REBALANCE_STEP_TOL = 1e-4


# ---------------------------------------------------------------------------
# 归档夹具
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def q4_panel() -> pd.DataFrame:
    """2026Q4 全池因子截面（index=code，含官方得分列供对账）."""
    df = pd.read_csv(BASELINE_DIR / "factor_panel_2026Q4.csv", encoding="utf-8-sig")
    return df.set_index("code")


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    """387 券全收益价格指数矩阵."""
    return pd.read_parquet(BASELINE_DIR / "prices.parquet")


@pytest.fixture(scope="module")
def baseline_nav() -> pd.DataFrame:
    """官方 rebase 点位 + 变体A 基线净值 + 调样生效日标记."""
    df = pd.read_csv(
        BASELINE_DIR / "baseline_nav.csv", index_col=0, parse_dates=True, encoding="utf-8-sig"
    )
    return df


@pytest.fixture(scope="module")
def panels() -> dict:
    """注入形态的面板字典 {as_of Timestamp: 截面 DataFrame(index=code)}.

    27 期历史成分快照（无因子列 → constituent_snapshot 模式）
    + 1 期 2026Q4 全池因子截面（→ factor_score 模式）。
    """
    snap = pd.read_csv(
        BASELINE_DIR / "factor_panel_snapshots.csv", encoding="utf-8-sig", dtype={"name": str}
    )
    q4 = pd.read_csv(BASELINE_DIR / "factor_panel_2026Q4.csv", encoding="utf-8-sig")
    out: dict = {}
    for as_of, grp in snap.groupby("as_of_date"):
        out[pd.Timestamp(as_of)] = grp.drop(columns=["as_of_date"]).set_index("code")
    # 全池因子期：as_of 由期日对照表给出（不写死日期常量）
    periods = pd.read_csv(BASELINE_DIR / "panel_periods.csv", encoding="utf-8-sig")
    q4_asof = pd.Timestamp(
        periods.loc[periods["panel_kind"] == "factor_score", "as_of_date"].iloc[-1]
    )
    out[q4_asof] = q4.drop(
        columns=[
            "official_issue_score", "official_issuer_score",
            "official_duration_score", "official_composite_score", "official_selected",
        ]
    ).set_index("code")
    return out


@pytest.fixture(scope="module")
def periods() -> pd.DataFrame:
    return pd.read_csv(BASELINE_DIR / "panel_periods.csv", encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# 1. 打分公式（纯函数）
# ---------------------------------------------------------------------------


def test_rank_score_matches_manual_formula():
    """名次分 = 100*(rank_max-1)/(N-1)，最小值得 0、最大值得 100."""
    s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    got = rank_score(s)
    assert np.allclose(got.values, [0.0, 25.0, 50.0, 75.0, 100.0])


def test_rank_score_ties_share_max_rank():
    """并列取 max 名次 → 同值同分，且分母固定 N-1（非 rank 极差）."""
    s = pd.Series([1.0, 2.0, 2.0, 2.0, 5.0])
    got = rank_score(s)
    # 三个并列 2.0 的 max 名次均为 4 → 100*(4-1)/(5-1)=75
    assert np.allclose(got.values, [0.0, 75.0, 75.0, 75.0, 100.0])


def test_rank_score_denominator_is_n_minus_one_not_rank_span():
    """末位并列时若用 rank 极差做分母会整体抬升尺度，此处锁死 N-1 口径."""
    s = pd.Series([1.0, 1.0, 1.0, 4.0])
    got = rank_score(s)
    # 并列 1.0 的 max 名次=3 → 100*(3-1)/3；若误用极差 (4-3)=1 会得 100/1 量级
    assert np.allclose(got.values, [200.0 / 3.0] * 3 + [100.0])


def test_rank_score_rejects_single_row():
    """N<2 时 N-1=0，必须报错而不是产出 inf/0."""
    with pytest.raises(ValueError, match="名次打分截面仅 1 行"):
        rank_score(pd.Series([1.0]))


def test_target_distance_score_peaks_at_target_and_clamps_at_span():
    """命中目标得 100；偏离全距归零；超出全距不为负."""
    s = pd.Series([2.5, 0.0, 5.0, 10.0, 20.0])
    got = target_distance_score(s, target=2.5, span=7.5)
    assert np.allclose(got.values, [100.0, 66.6666666667, 66.6666666667, 0.0, 0.0], atol=1e-9)


def test_target_distance_score_rejects_non_positive_span():
    with pytest.raises(ValueError, match="全距 span=0.0 非法"):
        target_distance_score(pd.Series([1.0, 2.0]), target=1.0, span=0.0)


def test_equal_weights_sum_exactly_one():
    """每只严格 1/N（指数等权口径），合计在容差内为 1."""
    w = equal_weights(["C", "A", "B"])
    assert w.index.tolist() == ["A", "B", "C"]
    assert abs(w.sum() - 1.0) <= 1e-12
    assert np.allclose(w.values, 1.0 / 3.0, rtol=0, atol=1e-12)


def test_equal_weights_large_n_still_sums_to_one():
    """N=548 时浮点累加偏差仍在容差内，不需残差修正券."""
    w = equal_weights([f"C{i:04d}" for i in range(548)])
    assert abs(w.sum() - 1.0) <= 1e-9
    assert w.max() - w.min() <= 1e-12


def test_equal_weights_rejects_empty_selection():
    with pytest.raises(ValueError, match="入选集合为空"):
        equal_weights([])


def test_equal_weights_dedups_repeated_codes():
    w = equal_weights(["A", "A", "B"])
    assert len(w) == 2 and abs(w.sum() - 1.0) <= 1e-12


# ---------------------------------------------------------------------------
# 2. 打分复现（vs 官方得分列）
# ---------------------------------------------------------------------------


def test_composite_scores_reproduce_official(q4_panel):
    """548 行三因子得分与综合分逐项复现官方（原型对账实测 ~1e-14）."""
    strat = BondFactorScoreIndexStrategy()
    cfg = strat._parse_config({})
    screened, dropped = strat._screen(q4_panel, cfg)
    assert dropped == 0, "2026Q4 全池截面不应有打分因子缺失"
    scored = strat._score(screened, cfg)

    pairs = [
        ("_score_issue_size", "official_issue_score", "发行规模分"),
        ("_score_issuer_size", "official_issuer_score", "主体规模分"),
        ("_score_modified_duration", "official_duration_score", "久期分"),
        ("_composite_score", "official_composite_score", "综合分"),
    ]
    for got_col, want_col, label in pairs:
        err = (scored[got_col] - q4_panel[want_col].astype(float)).abs()
        assert err.max() < SCORE_TOL, f"{label} 最大偏差 {err.max():.3e} 超容差"


def test_score_weights_are_20_20_60(q4_panel):
    """综合分权重锁定 0.2/0.2/0.6：改权重后与官方不再一致（防口径漂移）."""
    strat = BondFactorScoreIndexStrategy()
    cfg = strat._parse_config({"score_weights": "0.34,0.33,0.33"})
    scored = strat._score(strat._screen(q4_panel, cfg)[0], cfg)
    err = (scored["_composite_score"] - q4_panel["official_composite_score"].astype(float)).abs()
    assert err.max() > 1.0, "均等权重竟然复现官方，说明测试无效"


# ---------------------------------------------------------------------------
# 3. 选样复现（vs 官方名单）
# ---------------------------------------------------------------------------


def test_selection_reproduces_official_60_bonds(q4_panel, prices):
    """548 → 60 名单与官方完全一致（含分组构成）."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2026-09-30")
    w = strat.allocate(prices, _as_of=as_of, _panel_factor_panel={as_of: q4_panel})

    official = set(q4_panel.loc[q4_panel["official_selected"] == "是"].index.astype(str))
    got = set(w[w > 0].index.astype(str))
    assert len(official) == 60
    assert got == official, (
        f"名单不一致：仅自算 {sorted(got - official)[:5]}，仅官方 {sorted(official - got)[:5]}"
    )


def test_selection_matches_official_per_pool_group(q4_panel, prices):
    """两个券池分组各自 10 / 50 只，与官方逐组一致."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2026-09-30")
    w = strat.allocate(prices, _as_of=as_of, _panel_factor_panel={as_of: q4_panel})
    got = set(w[w > 0].index.astype(str))
    for grp, expect_n in [("其它信用债", 10), ("金融债/地方债/二永债", 50)]:
        sub = q4_panel[q4_panel["industry"] == grp]
        official_grp = set(sub.loc[sub["official_selected"] == "是"].index.astype(str))
        got_grp = got & set(sub.index.astype(str))
        assert len(official_grp) == expect_n, f"{grp} 官方入选 {len(official_grp)}≠{expect_n}"
        assert got_grp == official_grp, f"{grp} 分组名单不一致"


def test_weights_are_equal_and_sum_to_one(q4_panel, prices):
    """等权 1/60，合计为 1，未入选券权重为 0，权重轴覆盖整个资产池."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2026-09-30")
    w = strat.allocate(prices, _as_of=as_of, _panel_factor_panel={as_of: q4_panel})
    held = w[w > 0]
    assert len(held) == 60
    assert abs(w.sum() - 1.0) <= 1e-9
    assert held.max() - held.min() <= 1e-12, "等权应逐只相等（不做十进位舍入）"
    assert abs(held.max() - 1.0 / 60) <= 1e-12
    assert set(w.index) == set(prices.columns), "权重须覆盖整个资产池（未入选填 0）"


def test_issuer_cap_respected_per_group(q4_panel, prices):
    """单发行人限额：其它信用债 ≤2、金融债/地方债/二永债 ≤10."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2026-09-30")
    w = strat.allocate(prices, _as_of=as_of, _panel_factor_panel={as_of: q4_panel})
    held = w[w > 0].index
    info = q4_panel.loc[held]
    for grp, cap in [("其它信用债", 2), ("金融债/地方债/二永债", 10)]:
        counts = info[info["industry"] == grp].groupby("issuer").size()
        assert counts.max() <= cap, f"{grp} 单发行人最多 {counts.max()} 只 > 限额 {cap}"


def test_issuer_cap_drops_lower_scored_duplicates(q4_panel):
    """同发行人超限时保留综合分更高者（限额在取前 K 之前生效）."""
    strat = BondFactorScoreIndexStrategy()
    cfg = strat._parse_config({})
    scored = strat._score(strat._screen(q4_panel, cfg)[0], cfg)
    capped, dropped = strat._issuer_cap(scored, cfg, pd.Timestamp("2026-09-30"))
    assert dropped > 0, "548 行券池应触发发行人限额淘汰"
    # 被淘汰的券：同组同发行人内必存在综合分不低于它的保留券
    lost = scored.index.difference(capped.index)
    for code in lost[:20]:
        row = scored.loc[code]
        peers = capped[(capped["industry"] == row["industry"])
                       & (capped["issuer"] == row["issuer"])]
        assert len(peers) > 0 and peers["_composite_score"].max() >= row["_composite_score"]


def test_selected_are_topk_by_score_within_group(q4_panel):
    """限额后每组按综合分取前 K：入选券得分不低于同组任何未入选券."""
    strat = BondFactorScoreIndexStrategy()
    cfg = strat._parse_config({})
    scored = strat._score(strat._screen(q4_panel, cfg)[0], cfg)
    capped, _ = strat._issuer_cap(scored, cfg, pd.Timestamp("2026-09-30"))
    selected = strat._select_topk(capped, cfg, pd.Timestamp("2026-09-30"))
    for grp, k in cfg["pool_topk"].items():
        in_grp = capped[capped["industry"] == grp]
        sel_scores = in_grp.loc[[c for c in selected if c in in_grp.index], "_composite_score"]
        unsel_scores = in_grp.drop(index=sel_scores.index)["_composite_score"]
        assert len(sel_scores) == min(k, len(in_grp))
        if len(unsel_scores):
            assert sel_scores.min() >= unsel_scores.max() - 1e-12, f"{grp} 前 K 截断错误"


# ---------------------------------------------------------------------------
# 4. 成分快照模式（历史期无全池因子截面）
# ---------------------------------------------------------------------------


def test_snapshot_panel_selects_all_constituents_equal_weight(panels, prices, periods):
    """快照期：全截面入选等权，与当期官方成分数一致."""
    strat = BondFactorScoreIndexStrategy()
    snap_asofs = sorted(
        pd.Timestamp(r.as_of_date)
        for r in periods.itertuples() if r.panel_kind == "constituent_snapshot"
    )
    checked = 0
    for as_of in snap_asofs[::6]:  # 抽样 5 期，覆盖首末期
        panel = panels[as_of]
        hist = prices.loc[:max(as_of, prices.index[0])]
        w = strat.allocate(hist, _as_of=max(as_of, prices.index[0]),
                           _panel_factor_panel={as_of: panel})
        held = set(w[w > 0].index)
        assert held == set(panel.index.astype(str)), f"{as_of.date()} 快照期应全选"
        assert abs(w.sum() - 1.0) <= 1e-9
        checked += 1
    assert checked >= 4


def test_snapshot_period_count_matches_rebalance_calendar(periods):
    """28 期 = 27 期快照 + 1 期全池因子，与调样生效日数一致."""
    assert len(periods) == 28
    assert (periods["panel_kind"] == "constituent_snapshot").sum() == 27
    assert (periods["panel_kind"] == "factor_score").sum() == 1


def test_monitoring_metrics_distinguish_selection_source(q4_panel, panels, prices, periods):
    """审计指标 selection_source 区分 factor_score / constituent_snapshot."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2026-09-30")
    strat.allocate(prices, _as_of=as_of, _panel_factor_panel={as_of: q4_panel})
    m = strat.compute_monitoring_metrics(pd.Series(dtype=float), prices)
    assert m["selection_source"] == "factor_score"
    assert m["candidate_count"] == 548 and m["selected_count"] == 60
    assert m["screened_out"] == 0 and m["issuer_cap_dropped"] > 0
    assert m["weight_method"] == "equal" and abs(m["max_weight"] - 1 / 60) < 1e-9
    assert m["lag_trading_days"] == 0 and m["panel_as_of"] == "2026-09-30"
    assert abs(m["top5_weight_sum"] - 5 / 60) < 1e-9

    # 快照期：执行日须 ≥ 面板期日（引擎口径：信号日=面板期日）
    strat2 = BondFactorScoreIndexStrategy()
    snap_asof = pd.Timestamp(
        periods.loc[periods["panel_kind"] == "constituent_snapshot", "as_of_date"].iloc[5]
    )
    panel = panels[snap_asof]
    exec_day = prices.index[prices.index >= snap_asof][0]
    strat2.allocate(prices.loc[:exec_day], _as_of=exec_day,
                    _panel_factor_panel={snap_asof: panel})
    m2 = strat2.compute_monitoring_metrics(pd.Series(dtype=float), prices)
    assert m2["selection_source"] == "constituent_snapshot"
    assert m2["selected_count"] == len(panel) and m2["issuer_cap_dropped"] == 0
    assert m2["rebalance_count"] == 1, "跨期状态按实例隔离，不得共享模块级变量"
    assert strat.compute_monitoring_metrics(pd.Series(dtype=float), prices)[
        "rebalance_count"] == 1, "另一实例不得被污染"


# ---------------------------------------------------------------------------
# 5. 净值回归（引擎归因约定：收盘成交、新权重次日起息）
# ---------------------------------------------------------------------------


def _simulate_nav(
    strat: BondFactorScoreIndexStrategy,
    prices: pd.DataFrame,
    panels: dict,
    params: dict | None = None,
) -> pd.Series:
    """按引擎日循环约定复算净值：持仓量（份额）记账，权重在两次调仓间自然漂移.

    与 BacktestEngine 一致的关键点：
    - 调仓在信号日**收盘成交**：当日净值不受调仓影响，新持仓自次日起承接收益
    - 面板期日 = 决策日（生效日前一交易日）→ 次日恰为生效日，与指数
      「生效日收益用新权重」口径一致
    - 不用固定权重递推：那等价于每日再平衡回等权，与引擎持仓量语义不同
    """
    dates = list(prices.index)
    asof_set = set(panels.keys())
    base_params = dict(params or {})
    navs: list = []
    qty: dict = {}
    cash = 100.0
    for i, d in enumerate(dates):
        px = prices.iloc[i]
        value = cash + sum(q * px[c] for c, q in qty.items())
        navs.append(value)
        if i == 0 or d in asof_set:
            w = strat.allocate(
                prices.iloc[: i + 1],
                _as_of=d,
                _panel_factor_panel=panels,
                **base_params,
            )
            qty = {c: w[c] * value / px[c] for c in w.index if w[c] > 0 and px[c] > 0}
            cash = value - sum(q * px[c] for c, q in qty.items())
    return pd.Series(navs, index=pd.DatetimeIndex(dates), name="sys_nav")


def test_nav_reproduces_archived_variant_a_baseline(prices, panels, baseline_nav):
    """系统口径净值须复现归档变体A基线（等权+漂移，无现金桶）."""
    sys_nav = _simulate_nav(BondFactorScoreIndexStrategy(), prices, panels)
    want = baseline_nav["variant_a_sim"]
    common = sys_nav.index.intersection(want.index)
    assert len(common) == len(want), f"交易日数不一致：{len(common)} vs {len(want)}"
    rel = ((sys_nav.loc[common] - want.loc[common]).abs() / want.loc[common])
    assert rel.max() < NAV_SELF_TOL, (
        f"净值偏离归档基线 max_rel={rel.max():.3e} at {rel.idxmax().date()}"
    )


def test_nav_tracks_official_points_within_cash_bucket_attribution(
    prices, panels, baseline_nav
):
    """与官方点位累计差 ≤ 容差（差额归因于指数现金桶，不做隐式模拟）."""
    sys_nav = _simulate_nav(BondFactorScoreIndexStrategy(), prices, panels)
    off = baseline_nav["official_rebased"]
    common = sys_nav.index.intersection(off.index)
    rel = ((sys_nav.loc[common] - off.loc[common]).abs() / off.loc[common])
    assert rel.max() < NAV_OFFICIAL_TOL, f"与官方点位最大相对偏差 {rel.max():.3e}"
    # 收益相关性：形态须一致（非成本/权重错位型偏差）
    rs = sys_nav.loc[common].pct_change(fill_method=None).dropna()
    ro = off.loc[common].pct_change(fill_method=None).dropna()
    both = rs.index.intersection(ro.index)
    corr = float(np.corrcoef(rs.loc[both].values, ro.loc[both].values)[0, 1])
    assert corr > 0.999, f"日收益相关系数 {corr:.6f} 过低"


def test_nav_has_no_rebalance_day_step(prices, panels, baseline_nav):
    """调样日不得出现阶跃（阶跃=权重错位一天，即变体B 的失效形态）."""
    sys_nav = _simulate_nav(BondFactorScoreIndexStrategy(), prices, panels)
    off = baseline_nav["official_rebased"]
    common = sys_nav.index.intersection(off.index)
    rel = ((sys_nav.loc[common] - off.loc[common]).abs() / off.loc[common])
    rebalance_days = pd.DatetimeIndex(
        baseline_nav.index[baseline_nav["rebalance_effective"].astype(bool)]
    )
    jumps = rel.diff().abs().reindex(rebalance_days).dropna()
    assert jumps.max() < REBALANCE_STEP_TOL, (
        f"调样日相对偏差跳变 {jumps.max():.3e} at {jumps.idxmax().date()}，"
        f"疑似新权重晚一天生效"
    )


def test_wrong_panel_date_convention_produces_rebalance_step(prices, baseline_nav, panels):
    """反向验证：把面板期日改成生效日（变体B）会在调样日产生阶跃.

    该用例锁定「期日=决策日」的设计选择不是任意的——换约定即失效。
    """
    periods = pd.read_csv(BASELINE_DIR / "panel_periods.csv", encoding="utf-8-sig")
    shifted = {}
    for r in periods.itertuples():
        src = pd.Timestamp(r.as_of_date)
        dst = pd.Timestamp(r.effective_date)
        if src in panels and dst in set(prices.index):
            shifted[dst] = panels[src]
    if len(shifted) < 20:
        pytest.skip("可平移期数不足，无法做反向验证")
    sys_nav = _simulate_nav(BondFactorScoreIndexStrategy(), prices, shifted)
    off = baseline_nav["official_rebased"]
    common = sys_nav.index.intersection(off.index)
    rel = ((sys_nav.loc[common] - off.loc[common]).abs() / off.loc[common])
    rebalance_days = pd.DatetimeIndex(
        baseline_nav.index[baseline_nav["rebalance_effective"].astype(bool)]
    )
    jumps = rel.diff().abs().reindex(rebalance_days).dropna()
    assert jumps.max() > REBALANCE_STEP_TOL, (
        f"变体B 未出现阶跃（max={jumps.max():.3e}），反向验证失效"
    )


def test_rebalance_dates_align_with_panel_period_days(panels, periods, prices):
    """调仓日序列 = 面板期日（决策日），且决策日+1 交易日 = 生效日."""
    dates = list(prices.index)
    idx_of = {d: i for i, d in enumerate(dates)}
    for r in periods.itertuples():
        as_of, eff = pd.Timestamp(r.as_of_date), pd.Timestamp(r.effective_date)
        if as_of not in idx_of:
            continue  # 首期 as_of=基日，在价格轴外（引擎期初建仓消费）
        assert as_of in panels, f"决策日 {as_of.date()} 无对应面板期"
        assert dates[idx_of[as_of] + 1] == eff, (
            f"{as_of.date()} 的次交易日不是生效日 {eff.date()}"
        )


# ---------------------------------------------------------------------------
# 6. 注册与元信息（三通道同源的前提）
# ---------------------------------------------------------------------------


def test_registered_in_strategy_manifest_as_standalone():
    """manifest 一行注册：standalone 形态 + composition 三层全 None."""
    from app.allocation.strategy_manifest import STRATEGY_MANIFEST

    entry = STRATEGY_MANIFEST["bond_factor_score_index"]
    assert entry.strategy_form == "standalone"
    assert entry.composition == {
        "selector": None, "allocator": "bond_factor_score_index", "controller": None,
    }
    assert entry.class_path.endswith("BondFactorScoreIndexStrategy")
    assert "research" not in entry.description.lower()
    assert "凤凰" not in entry.description and "附件" not in entry.description


def test_param_schema_has_no_composition_layers_and_exposes_all_knobs():
    """参数全进 schema（零隐藏参数）；internal_leverage=True 避免二次缩放."""
    schema = BondFactorScoreIndexStrategy.get_param_schema()
    names = {p.name for p in schema.params}
    assert {
        "score_factors", "score_weights", "rank_factors", "duration_target",
        "duration_span", "pool_caps", "pool_topk", "panel_max_lag_days",
    } <= names
    assert schema.internal_leverage is True
    assert schema.composition["selector"] is None
    assert schema.composition["controller"] is None
    advanced = {p.name for p in schema.params if getattr(p, "group", None) == "advanced"}
    assert "panel_max_lag_days" in advanced


def test_data_feed_options_declare_panel_event_dates():
    """面板期日驱动调仓 + 声明 factor_panel 加载 + 0 行历史门槛（数据解耦的唯一入口）.

    ``min_history_rows`` 由 app/monitor/engine_adapter.py 消费（未声明时按
    ``_DEFAULT_MIN_HISTORY_ROWS=30`` 行门槛）；声明 0 行使监控在首个价格日即可
    建仓，与回测首日口径一致。期望值保持精确相等：新增数据口径键必须在此登记。
    """
    strat = BondFactorScoreIndexStrategy()
    opts = strat.get_data_feed_options()
    assert opts == {
        "extra_panels": ["factor_panel"],
        "panel_event_dates": True,
        "min_history_rows": 0,
    }
    assert BondFactorScoreIndexStrategy.get_extra_panels() == ["factor_panel"]


def test_execution_schedule_has_no_date_constants():
    """调度只声明频率与零延迟，不含 selection_start_date / skip_dates."""
    sched = BondFactorScoreIndexStrategy().get_execution_schedule()
    assert sched == {"rebalance_freq": "daily", "execution_delay": 0}


def test_strategy_source_has_no_hardcoded_codes_or_dates():
    """源码不得出现具体券码、日期常量与 research 路径（数据/日期解耦）."""
    src = (
        PROJECT_ROOT / "app" / "standalone_strategies"
        / "bond_factor_score_index" / "strategy.py"
    ).read_text(encoding="utf-8")
    assert "research" not in src
    for token in (".IB", ".SH", ".SZ", "2019-12-31", "2026-10-08", "2026Q4"):
        assert token not in src, f"源码含硬编码 {token!r}"


# ---------------------------------------------------------------------------
# 7. 错误路径（静默降级禁令）
# ---------------------------------------------------------------------------


def test_raises_without_injected_panel(prices):
    with pytest.raises(ValueError, match="未注入 factor_panel"):
        BondFactorScoreIndexStrategy().allocate(prices)


def test_raises_without_as_of(prices, q4_panel):
    with pytest.raises(ValueError, match="未注入执行日 _as_of"):
        BondFactorScoreIndexStrategy().allocate(
            prices, _panel_factor_panel={pd.Timestamp("2026-09-30"): q4_panel}
        )


def test_raises_when_no_panel_before_execution_day(prices, q4_panel):
    """执行日早于最早期日 → 明确报错，不回退成全池等权."""
    early = pd.Timestamp("2015-01-05")
    with pytest.raises(ValueError, match="之前无可用券池截面"):
        BondFactorScoreIndexStrategy().allocate(
            prices.iloc[:5], _as_of=early,
            _panel_factor_panel={pd.Timestamp("2026-09-30"): q4_panel},
        )


def test_raises_when_panel_lag_exceeds_limit(prices, panels):
    """滞后超上限报错（数据陈旧不得静默沿用旧截面）."""
    asof_dates = sorted(panels.keys())
    late = prices.index[-1]
    strat = BondFactorScoreIndexStrategy()
    with pytest.raises(ValueError, match="超过上限"):
        strat.allocate(prices, _as_of=late, _panel_factor_panel=panels,
                       panel_max_lag_days=0)
    assert asof_dates[0] < late


def test_raises_on_undeclared_pool_group(prices, q4_panel):
    """截面出现未声明限额的分组 → 报错，不猜默认限额."""
    broken = q4_panel.copy()
    broken.loc[broken.index[0], "industry"] = "未知券池"
    with pytest.raises(ValueError, match="未在 pool_caps/pool_topk 声明"):
        BondFactorScoreIndexStrategy().allocate(
            prices, _as_of=pd.Timestamp("2026-09-30"),
            _panel_factor_panel={pd.Timestamp("2026-09-30"): broken},
        )


def test_raises_when_selected_bond_missing_from_price_pool(q4_panel):
    """选中券不在资产池 → 报错并给出补数建议，不静默剔除."""
    narrow = pd.DataFrame(
        100.0, index=pd.date_range("2026-09-01", periods=5), columns=["ONLY.ONE"]
    )
    with pytest.raises(ValueError, match="不在资产池"):
        BondFactorScoreIndexStrategy().allocate(
            narrow, _as_of=pd.Timestamp("2026-09-30"),
            _panel_factor_panel={pd.Timestamp("2026-09-30"): q4_panel},
        )


def test_raises_when_all_factor_values_missing(prices, q4_panel):
    """无任何一行三打分因子齐全 → 初筛后无候选，报错而非兜底等权.

    每列各留一个有效值，避免落入 ``_is_constituent_snapshot`` 的「整列缺失」
    判定（那条分支由 test_all_nan_factor_columns_use_constituent_snapshot 覆盖）。
    """
    broken = q4_panel.iloc[:3].copy()
    factors = ("issue_size", "issuer_size", "modified_duration")
    for col in factors:
        broken[col] = np.nan
    for i, col in enumerate(factors):
        value = 3.5 if col == "modified_duration" else 1e9
        broken.iloc[i, broken.columns.get_loc(col)] = value
    with pytest.raises(ValueError, match="无候选"):
        BondFactorScoreIndexStrategy().allocate(
            prices, _as_of=pd.Timestamp("2026-09-30"),
            _panel_factor_panel={pd.Timestamp("2026-09-30"): broken},
        )


def test_all_nan_factor_columns_use_constituent_snapshot(panels, prices, periods):
    """打分因子列在但整列 NaN → 判为无因子期，走成分快照等权而非报无候选.

    data_feed 把整张面板所有期 union 后展平因子，早期期无因子但列仍在（值全
    NaN），只看列是否存在会把无因子期误判为有因子截面。本用例覆盖
    ``_is_constituent_snapshot`` 的「整列缺失」分支，与
    test_snapshot_panel_selects_all_constituents_equal_weight 覆盖的「无因子列」
    分支互补；口径由审计指标 ``selection_source`` 留痕。
    """
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp(
        periods.loc[periods["panel_kind"] == "constituent_snapshot", "as_of_date"].iloc[5]
    )
    panel = panels[as_of].copy()
    for col in ("issue_size", "issuer_size", "modified_duration"):
        panel[col] = np.nan
    exec_day = prices.index[prices.index >= as_of][0]

    w = strat.allocate(prices.loc[:exec_day], _as_of=exec_day,
                       _panel_factor_panel={as_of: panel})

    assert set(w[w > 0].index) == set(panel.index.astype(str))
    assert abs(w.sum() - 1.0) <= 1e-9
    m = strat.compute_monitoring_metrics(pd.Series(dtype=float), prices)
    assert m["selection_source"] == "constituent_snapshot"
    assert m["selected_count"] == len(panel)


def test_raises_on_empty_price_matrix(q4_panel):
    with pytest.raises(ValueError, match="价格矩阵为空"):
        BondFactorScoreIndexStrategy().allocate(
            pd.DataFrame(), _as_of=pd.Timestamp("2026-09-30"),
            _panel_factor_panel={pd.Timestamp("2026-09-30"): q4_panel},
        )


@pytest.mark.parametrize(
    "bad_params, match",
    [
        ({"score_weights": "0.5,0.5"}, "个数"),
        ({"score_weights": "0.5,abc,0.3"}, "非数值项"),
        ({"duration_span": 0}, "必须为正"),
        ({"pool_caps": "其它信用债:2"}, "分组键不一致"),
        ({"pool_caps": "其它信用债:-1,金融债/地方债/二永债:10"}, "取值为负"),
        ({"pool_caps": "其它信用债,金融债/地方债/二永债:10"}, "分组:整数"),
        ({"rank_factors": "not_a_factor"}, "不在打分因子内"),
        ({"panel_max_lag_days": "abc"}, "非法"),
    ],
)
def test_param_coherence_gate_rejects_incoherent_config(bad_params, match):
    """运行前门禁：参数不自洽即拒绝，不带病运行."""
    strat = BondFactorScoreIndexStrategy()
    problem = strat._check_params_coherent(None, bad_params)
    assert problem is not None and match in problem, f"{bad_params} 未被拦截：{problem}"


def test_param_coherence_gate_passes_default_config():
    assert BondFactorScoreIndexStrategy()._check_params_coherent(None, {}) is None


def test_allocate_rejects_incoherent_params_at_runtime(q4_panel, prices):
    """门禁之外，allocate 运行时同样不因非法参数静默降级."""
    with pytest.raises(ValueError, match="个数"):
        BondFactorScoreIndexStrategy().allocate(
            prices, _as_of=pd.Timestamp("2026-09-30"),
            _panel_factor_panel={pd.Timestamp("2026-09-30"): q4_panel},
            score_weights="0.5,0.5",
        )


# ---------------------------------------------------------------------------
# 8. 参数可调（前端可配 ≠ 只有默认值能跑）
#
# 注：行情只覆盖 387 只历史成分券，2026Q4 全池 548 只中 443 只无行情。
# 默认参数下官方入选 60 只全部有行情（回测可跑）；改动参数可能选中无行情券，
# 此时策略报错要求补数（见 test_raises_when_selected_bond_missing_from_price_pool）。
# 故参数敏感性用例用「有行情子集」截面，只验证参数真的驱动计算。
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def q4_panel_priced(q4_panel, prices) -> pd.DataFrame:
    """2026Q4 截面的有行情子集（因子齐备、两个券池分组均有样本）."""
    sub = q4_panel[q4_panel.index.isin(prices.columns)]
    assert set(sub["industry"]) == {"其它信用债", "金融债/地方债/二永债"}
    return sub


def test_topk_param_changes_selection_count(q4_panel_priced, prices):
    """分组选取数量可调：改成 2/5 后入选数随之变化（参数真的进执行路径）."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2026-09-30")
    w = strat.allocate(prices, _as_of=as_of,
                       _panel_factor_panel={as_of: q4_panel_priced},
                       pool_topk="其它信用债:2,金融债/地方债/二永债:5")
    assert int((w > 0).sum()) == 7
    assert abs(w.sum() - 1.0) <= 1e-9


def test_topk_default_selects_up_to_available_count(q4_panel_priced, prices):
    """组内候选不足 K 时全选，不报错、不凑数."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2026-09-30")
    cfg = strat._parse_config({})
    scored = strat._score(strat._screen(q4_panel_priced, cfg)[0], cfg)
    capped, _ = strat._issuer_cap(scored, cfg, as_of)
    w = strat.allocate(prices, _as_of=as_of,
                       _panel_factor_panel={as_of: q4_panel_priced})
    for grp, k in cfg["pool_topk"].items():
        avail = len(capped[capped["industry"] == grp])
        got = int((w[w > 0].reindex(capped[capped["industry"] == grp].index) > 0).sum())
        assert got == min(k, avail)


def test_score_weight_param_changes_selection(q4_panel_priced, prices):
    """改打分权重后入选名单变化 → 权重参数确实驱动打分."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2026-09-30")
    kw = dict(_as_of=as_of, _panel_factor_panel={as_of: q4_panel_priced},
              pool_topk="其它信用债:5,金融债/地方债/二永债:20")
    base = strat.allocate(prices, **kw)
    alt = strat.allocate(prices, score_weights="0.0,0.0,1.0", **kw)
    assert set(base[base > 0].index) != set(alt[alt > 0].index)


def test_duration_target_param_changes_selection(q4_panel_priced, prices):
    """久期目标值可调：目标改成 6.0 年后入选名单变化（距目标打分生效）."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2026-09-30")
    kw = dict(_as_of=as_of, _panel_factor_panel={as_of: q4_panel_priced},
              pool_topk="其它信用债:5,金融债/地方债/二永债:20")
    base = strat.allocate(prices, **kw)
    alt = strat.allocate(prices, duration_target=6.0, **kw)
    assert set(base[base > 0].index) != set(alt[alt > 0].index)


def test_issuer_cap_param_tightens_selection(q4_panel_priced, prices):
    """单发行人限额收紧到 1 后，同发行人多券只保留一只."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2026-09-30")
    w = strat.allocate(prices, _as_of=as_of,
                       _panel_factor_panel={as_of: q4_panel_priced},
                       pool_caps="其它信用债:1,金融债/地方债/二永债:1",
                       pool_topk="其它信用债:5,金融债/地方债/二永债:20")
    info = q4_panel_priced.loc[w[w > 0].index]
    for grp in ("其它信用债", "金融债/地方债/二永债"):
        counts = info[info["industry"] == grp].groupby("issuer").size()
        assert len(counts) and counts.max() <= 1


def test_rank_factor_switch_changes_scoring(q4_panel):
    """名次/距目标打分可切换：把久期改为名次打分后得分分布改变."""
    strat = BondFactorScoreIndexStrategy()
    cfg_rank = strat._parse_config({"rank_factors": "issue_size,issuer_size,modified_duration"})
    cfg_base = strat._parse_config({})
    df = strat._screen(q4_panel, cfg_base)[0]
    s_rank = strat._score(df, cfg_rank)["_score_modified_duration"]
    s_dist = strat._score(df, cfg_base)["_score_modified_duration"]
    assert not np.allclose(s_rank.values, s_dist.values)
    # 名次打分下最低分必为 0、最高分必为 100；距目标打分则不一定
    assert abs(s_rank.min()) < 1e-12 and abs(s_rank.max() - 100.0) < 1e-12
