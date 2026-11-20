# -*- coding: utf-8 -*-
"""执行语义零漂移门禁（回测引擎演进 P0 的基线，S2–S5 每步必跑）.

基线与 CLI 已统一到 ``tests/execution_baseline/``（``run_baseline.py check
--layer engine`` 是同一套断言的手动入口）。本文件保留为 pytest 侧的四类断言：

1. **夹具完整性**：``engine_parity.json`` 存在，且其 SHA256 与
   ``fingerprint.json`` 的 engine 层记录一致（防夹具被手改）。
2. **四路径零漂移**：单策略 / 组合 / 敏感性 / 监控（含生产 gross NAV 口径
   ``monitor_gross`` 与分支覆盖探针 ``monitor`` 两组），逐字段 ``abs=0``
   （float 精确相等，不设任何容差）。
3. **跨路径同一性（计划前提检验）**：``run_composite_unified`` 的
   ``portfolio_nav`` / ``portfolio_trades`` 与直驱 ``run_unified`` 的结果
   逐字段 ``abs=0``——证明组合路径与单策略路径共用同一执行语义与记账。
4. **基线非平凡性**：夹具必须真的覆盖到成本分支、净额配平分支、遗留资产
   分支、杠杆缩放分支与监控强制清仓分支，否则「零漂移」是空跑假绿。

禁止事项
--------
- 禁止 rebase 夹具来让本文件变绿（S2–S5 是纯重构，夹具是闸门不是可调参数）。
- 禁止放宽容差（本文件不引入任何 rtol/atol）。
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.execution_baseline.engine_layer import GOLDEN_PATH, build, load_golden
from tests.execution_baseline.run_baseline import load_fingerprint
from tests.execution_parity import builders as B
from tests.execution_parity.compare import compare, format_diffs, summarize

N_SNAPSHOTS_EXPECTED = B.N_DAYS - B.WARMUP


# ======================================================================
#  夹具（模块级只跑一次：四路径合计约 12 次引擎运行）
# ======================================================================

@pytest.fixture(scope="module")
def golden():
    if not GOLDEN_PATH.exists():
        pytest.fail(
            f"零漂移基线夹具不存在: {GOLDEN_PATH}\n"
            f"请先执行: py tests\\execution_baseline\\run_baseline.py rebase --layer engine"
        )
    data, sha = load_golden()
    return data, sha


@pytest.fixture(scope="module")
def actual():
    data, text, sha = build()
    return data, sha


@pytest.fixture(scope="module")
def prices():
    return B.make_prices()


def _assert_zero_drift(golden_sub, actual_sub, label: str) -> None:
    diffs = compare(golden_sub, actual_sub, root=f"$.{label}")
    if diffs:
        pytest.fail(
            f"[{label}] 零漂移失败：{summarize(diffs)}\n"
            f"差异明细（前 40 条）:\n{format_diffs(diffs)}"
        )


# ======================================================================
#  1. 夹具完整性
# ======================================================================

class TestFixtureIntegrity:
    def test_golden_fixture_exists_and_sha_recorded(self, golden):
        _, sha = golden
        assert len(sha) == 64, "夹具 SHA256 长度异常"
        recorded = ((load_fingerprint().get("layers") or {}).get("engine") or {}).get("sha256")
        assert recorded, (
            "fingerprint.json 缺少 engine 层 SHA 记录（应由 "
            "run_baseline.py rebase --layer engine 生成）"
        )
        assert recorded == sha, (
            f"夹具文件 SHA256 与 fingerprint 记录不一致，夹具可能被手改：\n"
            f"  文件   = {sha}\n  记录   = {recorded}"
        )

    def test_golden_covers_four_paths(self, golden):
        data, _ = golden
        for key in ("meta", "single", "composite", "sensitivity", "monitor", "monitor_gross"):
            assert key in data, f"夹具缺少子树: {key}"
        assert set(data["single"].keys()) == set(B.CONFIG_KEYS), (
            f"夹具 single 路径的 config 键不完整: {sorted(data['single'].keys())}"
        )
        assert set(data["composite"].keys()) == set(B.COMPOSITE_VARIANTS.keys())
        assert len(data["sensitivity"]) == len(B.SENSITIVITY_GRID)
        # 监控路径必须同时冻结两个费率口径（见 builders.MONITOR_VARIANTS）
        assert set(data["monitor"].keys()) == set(data["monitor_gross"].keys()), (
            "monitor 与 monitor_gross 子树字段集不一致，两者应除费率外完全同构"
        )


# ======================================================================
#  2. 四路径零漂移（abs=0）
# ======================================================================

class TestZeroDrift:
    def test_single_strategy_path(self, golden, actual):
        g, _ = golden
        a, _ = actual
        _assert_zero_drift(g["single"], a["single"], "single")

    def test_composite_path(self, golden, actual):
        g, _ = golden
        a, _ = actual
        _assert_zero_drift(g["composite"], a["composite"], "composite")

    def test_sensitivity_path(self, golden, actual):
        g, _ = golden
        a, _ = actual
        _assert_zero_drift(g["sensitivity"], a["sensitivity"], "sensitivity")

    def test_monitor_path(self, golden, actual):
        g, _ = golden
        a, _ = actual
        _assert_zero_drift(g["monitor"], a["monitor"], "monitor")

    def test_monitor_gross_path(self, golden, actual):
        """生产口径（gross NAV，``trading_cost = {}``）的监控路径."""
        g, _ = golden
        a, _ = actual
        _assert_zero_drift(g["monitor_gross"], a["monitor_gross"], "monitor_gross")

    def test_full_baseline_sha_identical(self, golden, actual):
        """整份基线的 SHA256 一致（等价于全字段 abs=0，且能捕捉结构增删）."""
        _, g_sha = golden
        _, a_sha = actual
        assert g_sha == a_sha, (
            f"基线 SHA256 不一致：\n  夹具 = {g_sha}\n  实跑 = {a_sha}"
        )


# ======================================================================
#  3. 跨路径同一性（计划前提检验）
# ======================================================================

class TestCrossPathIdentity:
    """组合路径必须与单策略路径共用同一执行语义与记账.

    ``composite_runner.py:276-278`` 表明 ``portfolio_nav`` 是
    ``[s.total_value for s in result.snapshots]`` 的原样透传，``:316`` 表明
    ``portfolio_trades`` 是 ``result.trades`` 的原样透传。因此复刻
    ``run_composite_unified`` 步骤 1–8 直驱 ``run_unified``，两者必须逐字段
    ``abs=0``。若不等，说明「统一引擎」前提不成立——按计划要求立即中止。
    """

    @pytest.mark.parametrize("variant", sorted(B.COMPOSITE_VARIANTS.keys()))
    def test_composite_nav_and_trades_equal_direct_run_unified(self, prices, variant):
        composite = B.run_composite_path(prices)[variant]
        direct = B.run_composite_direct(prices, variant)

        nav_from_direct = [
            [B._d(s.time), B._f(s.total_value)] for s in direct.snapshots
        ]
        diffs = compare(composite["portfolio_nav"], nav_from_direct, root="$.portfolio_nav")
        assert not diffs, (
            f"[{variant}] 组合路径 portfolio_nav 与直驱 run_unified 不一致"
            f"（计划前提不成立）：{summarize(diffs)}\n{format_diffs(diffs)}"
        )

        trades_from_direct = [
            {
                "time": B._d(t.time), "thscode": str(t.thscode), "side": str(t.side),
                "quantity": B._f(t.quantity), "price": B._f(t.price),
                "commission": B._f(t.commission), "slippage_cost": B._f(t.slippage_cost),
                "pnl": B._f(t.pnl),
            }
            for t in direct.trades
        ]
        diffs = compare(composite["portfolio_trades"], trades_from_direct, root="$.portfolio_trades")
        assert not diffs, (
            f"[{variant}] 组合路径 portfolio_trades 与直驱 run_unified 不一致"
            f"（计划前提不成立）：{summarize(diffs)}\n{format_diffs(diffs)}"
        )
        assert len(trades_from_direct) > 0, f"[{variant}] 组合路径未产生任何成交，检验无意义"


# ======================================================================
#  4. 基线非平凡性（防空跑假绿）
# ======================================================================

class TestBaselineNonTrivial:
    """夹具必须真的走到各条分支，否则 abs=0 只是「两边都是空」."""

    def test_all_single_configs_produce_full_snapshot_series(self, golden):
        g, _ = golden
        for key in B.CONFIG_KEYS:
            got = g["single"][key]["n_snapshots"]
            assert got == N_SNAPSHOTS_EXPECTED, (
                f"single/{key} 快照数 {got} != 期望 {N_SNAPSHOTS_EXPECTED}"
            )

    def test_cost_branches_actually_fire(self, golden):
        g, _ = golden
        zero = g["single"]["zero_cost"]
        flat = g["single"]["flat_rate"]
        assert zero["n_trades"] > 0, "zero_cost 未产生成交"
        assert zero["metrics"]["total_commission"] == 0.0
        assert zero["metrics"]["total_slippage"] == 0.0
        assert flat["n_trades"] > 0, "flat_rate 未产生成交"
        assert flat["metrics"]["total_commission"] > 0.0, "统一手续费未生效"
        assert flat["metrics"]["total_slippage"] > 0.0, "滑点未生效"

    def test_net_amount_branch_changes_result(self, golden):
        """commission_by_code 非空 → execution.py:75-84 净额配平必须改变结果."""
        g, _ = golden
        flat = g["single"]["flat_rate"]
        by_code = g["single"]["by_code"]
        assert by_code["n_trades"] > 0
        assert by_code["metrics"]["total_commission"] > 0.0
        # 净额配平改变 invest_value → 目标数量改变 → 成交与净值都必须不同
        assert by_code["trades"] != flat["trades"], (
            "by_code 与 flat_rate 成交完全相同 → 净额配平分支未生效"
        )
        assert by_code["snapshots"][-1]["total_value"] != flat["snapshots"][-1]["total_value"], (
            "by_code 与 flat_rate 期末净值相同 → 净额配平分支未生效"
        )

    def test_initial_weights_branch_and_legacy_asset_held(self, golden):
        """期初建仓必须成交；遗留资产在回测侧必须始终不被清仓（execution.py:98）."""
        g, _ = golden
        iw = g["single"]["initial_weights"]
        legacy = B.LEGACY_CODE
        assert iw["n_trades"] > 0
        buy_legacy = [t for t in iw["trades"] if t["thscode"] == legacy]
        assert len(buy_legacy) == 1, (
            f"遗留资产 {legacy} 应只在期初建仓成交一次，实际 {len(buy_legacy)} 次"
        )
        assert buy_legacy[0]["side"] == "buy"
        last_qty = iw["snapshots"][-1]["weights"].get(legacy, 0.0)
        assert last_qty > 0.0, (
            f"回测侧遗留资产 {legacy} 期末权重为 0 → 与 execution.py:98 "
            f"「只遍历 target_weights」的不清仓语义不符"
        )

    def test_empty_target_produces_no_rebalance_trades(self, golden):
        """空 target：期初建仓后每次调仓零成交，持仓保持不动."""
        g, _ = golden
        et = g["single"]["empty_target"]
        assert et["n_trades"] > 0, "期初建仓应产生成交"
        dates = {t["time"] for t in et["trades"]}
        assert len(dates) == 1, f"空 target 应只在期初建仓日成交，实际成交日: {sorted(dates)}"
        first_day = et["snapshots"][0]["time"]
        assert dates == {first_day}, f"成交日 {dates} 不是首日 {first_day}"
        # 期末仍持有期初建仓的资产
        last_w = et["snapshots"][-1]["weights"]
        assert last_w.get(B.TRADABLE[0], 0.0) > 0.0
        assert last_w.get(B.TRADABLE[1], 0.0) > 0.0

    def test_sensitivity_grid_constraints_bite_and_self_consistent(self, golden):
        """杠杆缩放必须真的改变结果；不咬合的网格点必须与无约束点完全相同."""
        g, _ = golden
        keys = list(g["sensitivity"].keys())
        by_label = {k.split("_", 2)[2]: k for k in keys}
        base = g["sensitivity"][by_label["no_constraint"]]
        loose = g["sensitivity"][by_label["loose_both"]]
        lev08 = g["sensitivity"][by_label["leverage_0.8"]]
        lev10 = g["sensitivity"][by_label["leverage_1.0"]]
        cap = g["sensitivity"][by_label["cap_A_0.35"]]

        assert compare(base, loose) == [], (
            "loose_both（杠杆 1.5 / 上限 0.60）应与 no_constraint 完全相同："
            "上限与杠杆均不咬合"
        )
        assert lev08["snapshots"] != base["snapshots"], "leverage_0.8 未改变结果 → 缩放未生效"
        assert lev10["snapshots"] != base["snapshots"], "leverage_1.0 未改变结果 → 缩放未生效"
        assert cap["snapshots"] != base["snapshots"], "cap_A_0.35 未改变结果 → 单资产上限未生效"
        # 杠杆 >1 的轮动期必然出现负现金（买入额超过组合总值）
        neg_cash = [s for s in base["snapshots"] if s["cash"] < 0.0]
        assert neg_cash, "轮动权重含 sum>1 的杠杆期，基线应出现负现金"

    def test_composite_cost_bites(self, golden):
        g, _ = golden
        zero = g["composite"]["zero_cost"]
        cost = g["composite"]["with_cost"]
        assert len(zero["portfolio_nav"]) > 0
        assert len(zero["portfolio_nav"]) == len(cost["portfolio_nav"])
        assert len(zero["portfolio_trades"]) > 0, "组合路径未产生母层成交"
        assert zero["portfolio_nav"] != cost["portfolio_nav"], (
            "组合层成本未改变 NAV → commission_rate/slippage 未透传到母层撮合"
        )
        assert len(zero["rebalance_dates"]) > 0, "组合路径未产生调仓日"

    def test_monitor_traditional_path_covers_cost_and_forced_liquidation(self, golden):
        """监控侧：交易费必须真的扣，遗留资产必须被强制清零（与回测侧相反）."""
        g, _ = golden
        mon = g["monitor"]
        legacy = B.LEGACY_CODE
        assert mon["n_days"] == N_SNAPSHOTS_EXPECTED, (
            f"监控基线天数 {mon['n_days']} != {N_SNAPSHOTS_EXPECTED}"
        )
        assert mon["n_rebalance_days"] >= 8, (
            f"监控月度调仓日过少（{mon['n_rebalance_days']}），未充分覆盖调仓分支"
        )
        assert mon["final_total_trading_cost"] > 0.0, "监控交易费恒为 0 → 成本分支未覆盖"
        assert mon["final_quantities"].get(legacy, None) == 0.0, (
            f"监控侧遗留资产 {legacy} 期末数量应为 0（portfolio_tracker.py:413-415 "
            f"强制清仓），实际 {mon['final_quantities'].get(legacy)}"
        )
        assert mon["final_nav"] > 0.0
        # nav_history 只在 process_day 的步骤 E 追加（portfolio_tracker.py:923），
        # 而期初建仓走 _initialize_positions_traditional（:188-196 只置零兼容字段、
        # 不追加历史）。基线 rows = 1 个 init 行 + (n_days-1) 次 process_day，
        # 故 nav_history_len 恒等于 n_days - 1。
        assert mon["nav_history_len"] == mon["n_days"] - 1, (
            f"nav_history 未逐日追加: len={mon['nav_history_len']} n_days={mon['n_days']}"
        )

    def test_monitor_gross_variant_is_production_zero_cost_and_differs_from_probe(self, golden):
        """``monitor_gross`` 必须是零成本（生产 gross NAV 口径），且与探针口径不同.

        已核实生产上 ``PortfolioTracker.trading_cost`` 恒为空字典
        （``portfolio_tracker.py:43`` / ``:59`` / ``:69``，``_resolve_trading_cost``
        未配置时恒返回 0.0）。因此：

        - ``monitor_gross`` 代表生产行为 → 累计成本必须精确为 0；
        - ``monitor``（0.0003）不代表生产，但必须保留——否则
          ``portfolio_tracker.py:391-400`` 的扣费算术在基线里是死代码，
          S4 的 ``RebalanceFill`` 照搬这段时改错也不会被发现。
        两者 NAV 必须不同，否则说明其中一组没真的跑到对应分支。
        """
        g, _ = golden
        probe = g["monitor"]
        gross = g["monitor_gross"]

        assert gross["final_total_trading_cost"] == 0.0, (
            f"生产口径（trading_cost={{}}）累计成本应精确为 0，"
            f"实际 {gross['final_total_trading_cost']!r}"
        )
        assert all(r["total_trading_cost"] == 0.0 for r in gross["rows"]), (
            "生产口径下逐日累计成本均应恒为 0"
        )
        assert probe["final_total_trading_cost"] > 0.0, "探针口径未覆盖扣费分支"
        assert probe["final_nav"] != gross["final_nav"], (
            f"两个费率口径的期末 NAV 相同（probe={probe['final_nav']!r} "
            f"gross={gross['final_nav']!r}）→ 扣费分支未真实改变结果"
        )
        # 两组除费率外完全同构：天数 / 调仓次数 / 遗留资产强制清零应一致
        assert probe["n_days"] == gross["n_days"] == N_SNAPSHOTS_EXPECTED
        assert probe["n_rebalance_days"] == gross["n_rebalance_days"]
        assert gross["final_quantities"].get(B.LEGACY_CODE, None) == 0.0, (
            "生产口径下遗留资产同样应被强制清零（portfolio_tracker.py:413-415）"
        )

    def test_backtest_monitor_legacy_asset_divergence_is_frozen(self, golden):
        """C1-3（遗留资产处理差异）必须被基线如实记录，不得在 S2–S5 内被悄悄抹平.

        回测侧：``execution.py:98`` 只遍历 ``target_weights.keys()`` → 遗留资产继续持有；
        监控侧：``portfolio_tracker.py:413-415`` → 遗留资产强制清零。
        这是计划中登记的已知差异，收敛属 P5（可选），不在本批次范围。
        """
        g, _ = golden
        legacy = B.LEGACY_CODE
        bt_w = g["single"]["initial_weights"]["snapshots"][-1]["weights"].get(legacy, 0.0)
        mon_q = g["monitor"]["final_quantities"].get(legacy, 0.0)
        assert bt_w > 0.0, "回测侧遗留资产期末权重应 > 0"
        assert mon_q == 0.0, "监控侧遗留资产期末数量应 == 0"
