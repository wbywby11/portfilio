# -*- coding: utf-8 -*-
"""回测 ↔ 监控 逐日 parity harness（回测引擎演进 P3/S15）.

为什么需要这个文件
------------------
``tests/execution_baseline/`` 的两层门禁都不做回测与监控的互比：

- ``engine_layer`` 是「四路径各自 vs 冻结夹具」，防的是重构漂移；
- ``regression_layer`` 是「当前链路 vs ``d408639`` 的黄金基线」，防的是无法
  归因的新增差异。

于是「同一条策略跑回测得到的净值，与跑日常监控得到的净值，差在哪一天、差多少、
为什么差」这个问题在系统里**没有任何断言覆盖**。两侧净值一旦分叉，只能靠人肉
对 Excel，而分叉的真实原因（成本口径 / 执行延迟 / 遗留资产处理）从不显式出现。
本文件补上这块：把两条既有路径的逐日输出对齐比对，产出**首差异可定位 +
口径可归因 + 事件序列可复现**的报告。

复用什么、不重造什么
--------------------
输入构造完全复用 ``tests.execution_parity.builders``：回测侧走
``run_unified``，监控侧走 ``run_monitor_path``（直驱 ``PortfolioTracker``，
不经 MonitorService / Mongo）。本文件只做「对齐 + 比对 + 归因」三件事。

实测得到的两条关键事实（决定了下面的容差与断言）
----------------------------------------------
1. 把成本口径与执行延迟对齐、并去掉遗留资产后，两侧 240 个交易日的净值
   **最大偏差 9.095e-13**（净值量级 1e3，即 rel ≈ 9e-16，属 1 ULP 级）。
   差异来源是换算路径不同：回测 ``total_value`` 除以 ``initial_cash/
   initial_nav`` 得到净值，监控直接维护 ``nav``。两侧日常记账是同一个数。
2. 保留遗留资产（``LEGACY_CODE``：期初建仓后永不出现在目标权重）时，首个
   **语义级**分叉日是首次月度调仓的**次一交易日**，绝对差 0.878 并逐日累积到
   4.21。调仓当日两侧净值仍相等——监控清仓只是把持仓换成现金，总值不变；
   分叉从次日不同的持仓结构开始累积。

因此 ``PARITY_REL_TOL`` 取 1e-12：比浮点噪声（1e-15 量级）高三个数量级，比
语义分叉（1e-4 量级）低八个数量级，不会把任一类误判成另一类。

禁止事项
--------
- 禁止用「放宽容差」让含遗留资产的对比变绿——那会把唯一的真实分叉藏起来。
- 禁止修改 ``builders.py`` 的固定种子常量（会连带破坏 ``engine_parity.json``
  夹具的 SHA，触发引擎层门禁）。本文件需要的口径变体一律在本地构造。
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
from typing import Any, Dict, Iterator, List, NamedTuple, Optional

import pytest

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.execution_parity import builders as B  # noqa: E402

#: 同口径判据（净值相对差）。取值依据见模块 docstring 的两条实测事实。
PARITY_REL_TOL = 1e-12

#: 回测金额 → 监控净值的换算因子（``initial_cash / initial_nav``）。
NAV_SCALE = B.INITIAL_CASH / 1000.0


# ======================================================================
#  1. 两侧路径的驱动
# ======================================================================

@contextmanager
def _monitor_initial_weights(weights: Dict[str, float]) -> Iterator[None]:
    """临时替换监控路径的期初建仓表.

    ``run_monitor_path`` 直接读模块级 ``MONITOR_INITIAL_WEIGHTS``，而那份表
    含遗留资产且被 ``engine_parity.json`` 夹具冻结。要跑「去掉遗留资产」这个
    消融组，只能临时替换、跑完还原——不改 builders 就不会动夹具。
    """
    original = dict(B.MONITOR_INITIAL_WEIGHTS)
    B.MONITOR_INITIAL_WEIGHTS = dict(weights)
    try:
        yield
    finally:
        B.MONITOR_INITIAL_WEIGHTS = original


def run_backtest_side(
    prices,
    initial_weights: Dict[str, float],
    *,
    commission_rate: float = 0.0,
    slippage: float = 0.0,
    execution_delay: int = 0,
) -> Dict[str, Any]:
    """回测侧：与监控同口径的 ``run_unified`` 归一化结果.

    默认参数即「对齐口径」——零成本 + T+0，与监控的 gross + 当日执行一致。
    ``execution_delay`` 保留为入参，用于演示延迟错开时的分叉形态。
    """
    from app.backtesting.data_feed import DataFeed
    from app.backtesting.risk import RiskConfig
    from app.backtesting.runner import RunSpec, run_unified

    config = B._base_config(
        "parity_backtest_monitor", prices,
        commission_rate=commission_rate, slippage=slippage,
        execution_delay=execution_delay,
        initial_weights=dict(initial_weights),
    )
    result = run_unified(RunSpec(
        config=config,
        data_feed=DataFeed(prices=prices.copy(), config=config),
        strategy=B.RotatingWeightStrategy(),
        risk_config=RiskConfig(),
    ))
    normalized = B.normalize_backtest_result(result)
    normalized["config"] = config
    return normalized


def run_pair(
    prices,
    initial_weights: Dict[str, float],
    *,
    monitor_trading_cost: Optional[Dict[str, float]] = None,
    commission_rate: float = 0.0,
    slippage: float = 0.0,
    execution_delay: int = 0,
) -> Dict[str, Any]:
    """跑一次「回测 + 监控」配对，返回两侧归一化结果与各自的执行口径.

    Args:
        monitor_trading_cost: 监控侧按资产费率表。``{}`` = 生产 gross 口径；
            ``None`` 交给 ``run_monitor_path`` 用 ``MONITOR_TRADING_COST``
            配满全部资产（分支覆盖探针口径）。
    """
    from app.backtesting.policy import from_backtest_config, from_monitor_tracker
    from app.monitor.portfolio_tracker import PortfolioTracker

    backtest = run_backtest_side(
        prices, initial_weights,
        commission_rate=commission_rate, slippage=slippage,
        execution_delay=execution_delay,
    )
    with _monitor_initial_weights(initial_weights):
        monitor = B.run_monitor_path(prices, trading_cost=monitor_trading_cost)

    # 监控侧口径从一个与 run_monitor_path 同构的 tracker 取（该函数不返回
    # tracker，重建一个只为读 trading_cost；费率表就是传进去的那份）。
    probe = PortfolioTracker()
    probe.trading_cost = dict(
        monitor_trading_cost if monitor_trading_cost is not None
        else {c: B.MONITOR_TRADING_COST for c in prices.columns}
    )
    return {
        "backtest": backtest,
        "monitor": monitor,
        "policy_backtest": from_backtest_config(backtest["config"]),
        "policy_monitor": from_monitor_tracker(probe),
    }


# ======================================================================
#  2. 逐日对齐
# ======================================================================

class AlignedDay(NamedTuple):
    """同一交易日两侧的可比字段.

    时点提醒（易错，来自 ``run_monitor_path`` 的实现顺序）：监控一行的
    ``nav`` / ``quantities`` 是 ``execute_rebalance`` **之后**的时点，而
    ``daily_asset_weights`` 来自 ``process_day`` 的返回值，是调仓**之前**的
    时点。因此权重不能与回测快照的 ``weights``（调仓后）直接比，本 harness
    只用权重做「遗留资产是否被清零」这类符号判断，净值才是逐日 parity 的量。

    现金不入表：两侧口径不同（回测含费时可透支为负，监控 gross 下恒约
    为零），近零值做相对比会退化成噪声，而现金差异已经体现在净值里。
    """

    date: str
    bt_nav: float
    mon_nav: float
    bt_weights: Dict[str, float]
    mon_weights: Dict[str, float]
    bt_is_rebalance: bool
    bt_rebalance_type: Optional[str]
    bt_signal_date: Optional[str]
    bt_execution_delay: int
    mon_kind: str


def align_days(backtest: Dict[str, Any], monitor: Dict[str, Any]) -> List[AlignedDay]:
    """按交易日对齐两侧逐日输出（两侧日期轴已由 ``test_daily_axis_identical`` 保证一致）."""
    bt_rows = {s["time"]: s for s in backtest["snapshots"]}
    mon_rows = {r["date"]: r for r in monitor["rows"]}
    out: List[AlignedDay] = []
    for date in sorted(bt_rows):
        bt = bt_rows[date]
        mon = mon_rows.get(date)
        if mon is None:
            continue
        out.append(AlignedDay(
            date=date,
            bt_nav=bt["total_value"] / NAV_SCALE,
            mon_nav=mon["nav"],
            bt_weights=dict(bt["weights"]),
            mon_weights=dict(mon.get("daily_asset_weights") or {}),
            bt_is_rebalance=bool(bt["is_rebalance_day"]),
            bt_rebalance_type=bt["rebalance_type"],
            bt_signal_date=bt["signal_date"],
            bt_execution_delay=int(bt["execution_delay_days"]),
            mon_kind=str(mon["kind"]),
        ))
    return out


class NavDiff(NamedTuple):
    """一处逐日净值差异（相对差超容差才计入）."""

    date: str
    backtest: float
    monitor: float
    abs_diff: float
    rel_diff: float


def compare_nav(days: List[AlignedDay], tol: float = PARITY_REL_TOL) -> List[NavDiff]:
    """逐日比净值，返回相对差超容差的条目（空列表 = 同口径）."""
    out: List[NavDiff] = []
    for d in days:
        abs_diff = abs(d.bt_nav - d.mon_nav)
        scale = max(abs(d.bt_nav), abs(d.mon_nav), 1e-12)
        rel_diff = abs_diff / scale
        if rel_diff > tol:
            out.append(NavDiff(d.date, d.bt_nav, d.mon_nav, abs_diff, rel_diff))
    return out


def first_divergence(days: List[AlignedDay], tol: float = PARITY_REL_TOL) -> Optional[NavDiff]:
    """首个语义级分叉（``compare_nav`` 的第一条）."""
    diffs = compare_nav(days, tol)
    return diffs[0] if diffs else None


# ======================================================================
#  3. 归因
# ======================================================================

def attribute_policies(policy_backtest, policy_monitor) -> List[str]:
    """成本口径归因：``ExecutionPolicy.diff`` 的人话输出.

    这是报告的首行——两侧净值分叉时，先回答「是不是成本口径不同」，
    再去看结构性差异，顺序反了就会把口径问题当成计算 bug 追查。
    """
    return policy_backtest.diff(policy_monitor)


def rebalance_schedule_gap(days: List[AlignedDay]) -> Dict[str, List[str]]:
    """两侧调仓日轴的差集（执行延迟是否对齐的直接证据）."""
    bt_days = {d.date for d in days if d.bt_is_rebalance}
    mon_days = {d.date for d in days if d.mon_kind == "rebalance"}
    return {
        "backtest": sorted(bt_days),
        "monitor": sorted(mon_days),
        "backtest_only": sorted(bt_days - mon_days),
        "monitor_only": sorted(mon_days - bt_days),
    }


def legacy_asset_gap(days: List[AlignedDay], legacy_code: str) -> Dict[str, Any]:
    """遗留资产在两侧的处置差异（回测保留 / 监控强制清零）.

    回测 ``execution.py`` 只遍历 ``target_weights.keys()``，不在目标权重里的
    资产既不买也不卖；监控 ``portfolio_tracker`` 在调仓时把不在目标权重里的
    持仓强制清零。同一份期初建仓因此走向两种持仓结构。
    """
    held_by_backtest = [d.date for d in days if d.bt_weights.get(legacy_code, 0.0) > 0]
    held_by_monitor = [d.date for d in days if d.mon_weights.get(legacy_code, 0.0) > 0]
    return {
        "legacy_code": legacy_code,
        "backtest_held_days": len(held_by_backtest),
        "monitor_held_days": len(held_by_monitor),
        "backtest_held_first": held_by_backtest[0] if held_by_backtest else None,
        "monitor_held_first": held_by_monitor[0] if held_by_monitor else None,
    }


def event_sequence(days: List[AlignedDay], date: str, context: int = 1) -> List[str]:
    """指定日期前后 ``context`` 个交易日的两侧事件序列（复现首差异当日的现场）."""
    dates = [d.date for d in days]
    if date not in dates:
        return [f"<{date} 不在可比日期轴上>"]
    at = dates.index(date)
    window = days[max(0, at - context): at + context + 1]
    lines: List[str] = []
    for d in window:
        mark = ">>" if d.date == date else "  "
        lines.append(
            f"{mark} {d.date}  回测: rebalance={d.bt_is_rebalance}"
            f" type={d.bt_rebalance_type} signal_date={d.bt_signal_date}"
            f" delay={d.bt_execution_delay}"
            f" | 监控: kind={d.mon_kind}"
        )
    return lines


def format_report(pair: Dict[str, Any], days: List[AlignedDay]) -> str:
    """人话报告：口径 → 首差异 → 归因 → 事件序列（失败信息直接用它）."""
    diffs = compare_nav(days)
    first = diffs[0] if diffs else None
    policy_lines = attribute_policies(pair["policy_backtest"], pair["policy_monitor"])
    schedule = rebalance_schedule_gap(days)
    legacy = legacy_asset_gap(days, B.LEGACY_CODE)

    lines = [
        "回测 / 监控 逐日 parity 报告",
        "-" * 62,
        f"可比交易日: {len(days)}（{days[0].date} ~ {days[-1].date}）" if days else "可比交易日: 0",
        f"回测口径: cost_basis={pair['policy_backtest'].cost_basis}"
        f" hash={pair['policy_backtest'].policy_hash()}",
        f"监控口径: cost_basis={pair['policy_monitor'].cost_basis}"
        f" hash={pair['policy_monitor'].policy_hash()}",
        "",
        "成本口径归因（ExecutionPolicy.diff）:",
    ]
    lines += [f"  - {t}" for t in policy_lines] if policy_lines else ["  <无差异>"]

    lines += ["", "调仓日轴:",
              f"  回测 {len(schedule['backtest'])} 天 / 监控 {len(schedule['monitor'])} 天",
              f"  仅回测: {schedule['backtest_only']}",
              f"  仅监控: {schedule['monitor_only']}"]

    lines += ["", "遗留资产处置:",
              f"  {legacy['legacy_code']}：回测持有 {legacy['backtest_held_days']} 天，"
              f"监控持有 {legacy['monitor_held_days']} 天"]

    lines += ["", f"逐日净值差异（rel > {PARITY_REL_TOL:g}）: {len(diffs)} / {len(days)}"]
    if first:
        lines += [
            "",
            f"首差异日: {first.date}",
            f"  字段   回测                 监控                 绝对差        相对差",
            f"  nav    {first.backtest:<20.10f} {first.monitor:<20.10f} "
            f"{first.abs_diff:<13.3e} {first.rel_diff:.3e}",
            "",
            "该日前后事件序列:",
        ]
        lines += [f"  {t}" for t in event_sequence(days, first.date)]
    else:
        lines += ["  <全区间同口径：两侧净值逐日一致到浮点精度>"]
    return "\n".join(lines)


# ======================================================================
#  4. 夹具
# ======================================================================

#: 消融组的期初建仓：与 ``MONITOR_INITIAL_WEIGHTS`` 同权重总量（和为 1），
#: 但把遗留资产的那 10% 摊给 ``TRADABLE[3]``，使四资产全在目标权重表内。
NO_LEGACY_WEIGHTS: Dict[str, float] = {
    B.TRADABLE[0]: 0.30, B.TRADABLE[1]: 0.30, B.TRADABLE[2]: 0.20, B.TRADABLE[3]: 0.20,
}


@pytest.fixture(scope="module")
def prices():
    return B.make_prices()


@pytest.fixture(scope="module")
def control_pair(prices):
    """对照组：含遗留资产 + 对齐口径（gross + T+0）."""
    return run_pair(prices, dict(B.MONITOR_INITIAL_WEIGHTS), monitor_trading_cost={})


@pytest.fixture(scope="module")
def ablation_pair(prices):
    """消融组：去掉遗留资产 + 对齐口径（gross + T+0）."""
    return run_pair(prices, dict(NO_LEGACY_WEIGHTS), monitor_trading_cost={})


@pytest.fixture(scope="module")
def cost_pair(prices):
    """口径错开组：含费回测（net）vs gross 监控——演示成本口径归因."""
    return run_pair(
        prices, dict(B.MONITOR_INITIAL_WEIGHTS),
        monitor_trading_cost={},
        commission_rate=B.MONITOR_TRADING_COST, slippage=0.0, execution_delay=0,
    )


N_DAYS_EXPECTED = B.N_DAYS - B.WARMUP


# ======================================================================
#  5. 同口径 parity：对齐成本与执行延迟后，两侧净值必须逐日一致
# ======================================================================

class TestAlignedParity:
    """消融组：把遗留资产从期初建仓里去掉，其余口径全部对齐.

    这是本文件唯一的**等式**断言（其余都是归因断言）。它成立才能说明
    回测与监控共用同一套记账，两侧净值不一致时才有资格去谈「差异可归因」
    而不是「两边本来就是两套数」。
    """

    def test_daily_axis_identical(self, control_pair):
        """两侧交易日轴逐日对齐（parity 的前提：不对齐就谈不上逐日比）."""
        bt_dates = [s["time"] for s in control_pair["backtest"]["snapshots"]]
        mon_dates = [r["date"] for r in control_pair["monitor"]["rows"]]
        assert len(bt_dates) == N_DAYS_EXPECTED, (
            f"回测快照天数异常：{len(bt_dates)} != {N_DAYS_EXPECTED}"
        )
        assert bt_dates == mon_dates, (
            "回测与监控的交易日轴不一致，逐日 parity 无法进行：\n"
            f"  仅回测: {sorted(set(bt_dates) - set(mon_dates))[:5]}\n"
            f"  仅监控: {sorted(set(mon_dates) - set(bt_dates))[:5]}"
        )

    def test_initial_day_nav_exact(self, ablation_pair):
        """建仓当日两侧净值精确相等（同一期初、同一价格、零成本）."""
        days = align_days(ablation_pair["backtest"], ablation_pair["monitor"])
        d0 = days[0]
        assert d0.mon_kind == "init", f"监控首行应为 init，实际 {d0.mon_kind}"
        assert d0.bt_nav == d0.mon_nav == 1000.0, (
            f"建仓日净值不一致：回测={d0.bt_nav!r} 监控={d0.mon_nav!r}"
        )

    def test_no_legacy_full_period_parity(self, ablation_pair):
        """**核心断言**：去掉遗留资产后，全区间逐日净值 rel ≤ 1e-12.

        残留的 1e-16 量级偏差来自换算路径不同（回测 ``total_value`` 除以
        ``initial_cash / initial_nav``，监控直接维护 ``nav``），不是语义差异。
        """
        days = align_days(ablation_pair["backtest"], ablation_pair["monitor"])
        assert len(days) == N_DAYS_EXPECTED
        # 非平凡性：两侧都真的跑了调仓，否则「相等」是空跑假绿
        assert int(ablation_pair["monitor"]["n_rebalance_days"]) > 0, "监控侧未发生任何调仓"
        assert ablation_pair["backtest"]["n_trades"] > 0, "回测侧未产生任何成交"

        diffs = compare_nav(days)
        assert not diffs, (
            "对齐口径且无遗留资产时，回测与监控的逐日净值应一致到浮点精度：\n"
            + format_report(ablation_pair, days)
        )

    def test_float_level_deviation_is_below_semantic_scale(self, ablation_pair):
        """容差非平凡：同口径下确实存在非零偏差，但远小于语义分叉量级.

        防止 ``PARITY_REL_TOL`` 被误设成「大到什么都算相等」。实测同口径最大
        rel ≈ 9e-16，而遗留资产引发的语义分叉 rel ≈ 9e-4——两者差 12 个数量级。
        """
        days = align_days(ablation_pair["backtest"], ablation_pair["monitor"])
        rel = [
            abs(d.bt_nav - d.mon_nav) / max(abs(d.bt_nav), abs(d.mon_nav), 1e-12)
            for d in days
        ]
        assert max(rel) > 0.0, "两侧净值逐位相同，说明比较的可能不是两条独立路径"
        assert max(rel) < PARITY_REL_TOL / 1000, (
            f"同口径最大相对偏差 {max(rel):.3e} 已接近容差 {PARITY_REL_TOL:g}，"
            f"容差失去区分能力（语义分叉量级约 1e-4）"
        )


# ======================================================================
#  6. 首差异可定位 + 口径归因
# ======================================================================

class TestDivergenceAttribution:
    """对照组：保留遗留资产，验证分叉可定位、可归因、可复现."""

    def test_first_divergence_is_day_after_first_rebalance(self, control_pair):
        """首个语义分叉日 = 首次月度调仓的次一交易日.

        调仓当日两侧净值仍相等：监控清仓只是把持仓换成现金，总值不变；
        分叉从次日不同的持仓结构开始累积（监控已不含遗留资产那一份持仓）。
        """
        days = align_days(control_pair["backtest"], control_pair["monitor"])
        first = first_divergence(days)
        assert first is not None, (
            "含遗留资产时应出现语义分叉。若本断言失败，说明遗留资产分支已被"
            "改动，本文件第六节的归因结论需重新核实（不得直接放宽到 assert True）。\n"
            + format_report(control_pair, days)
        )
        schedule = rebalance_schedule_gap(days)
        assert schedule["monitor"], "监控侧未识别到任何月度调仓日"
        first_rebalance = schedule["monitor"][0]
        dates = [d.date for d in days]
        expected = dates[dates.index(first_rebalance) + 1]
        assert first.date == expected, (
            f"首差异日应为首次调仓（{first_rebalance}）的次一交易日 {expected}，"
            f"实际为 {first.date}\n" + format_report(control_pair, days)
        )

    def test_first_divergence_reports_both_sides(self, control_pair):
        """首差异能定位到「日期 + 字段 + 两侧值 + 绝对/相对差」四要素."""
        days = align_days(control_pair["backtest"], control_pair["monitor"])
        first = first_divergence(days)
        assert first is not None
        report = format_report(control_pair, days)
        assert first.date in report, "报告未包含首差异日期"
        assert "nav" in report, "报告未包含发生差异的字段名"
        assert f"{first.backtest:<20.10f}".strip() in report, "报告未包含回测侧值"
        assert f"{first.monitor:<20.10f}".strip() in report, "报告未包含监控侧值"
        assert first.abs_diff > 0 and first.rel_diff > PARITY_REL_TOL

    def test_divergence_attributed_to_legacy_liquidation(self, control_pair, ablation_pair):
        """首差异根因归到遗留资产清仓：回测保留、监控强制清零.

        归因不靠推测，靠消融：同一交易日，把遗留资产从期初建仓去掉后
        差异消失（``test_no_legacy_full_period_parity`` 已断言全区间）。
        """
        days = align_days(control_pair["backtest"], control_pair["monitor"])
        first = first_divergence(days)
        assert first is not None
        day = next(d for d in days if d.date == first.date)
        assert day.bt_weights.get(B.LEGACY_CODE, 0.0) > 0, (
            f"首差异日回测应仍持有遗留资产 {B.LEGACY_CODE}（execution.py 只遍历 "
            f"target_weights.keys()，不在目标权重里的持仓既不买也不卖）"
        )
        assert day.mon_weights.get(B.LEGACY_CODE, 0.0) == 0.0, (
            f"首差异日监控应已清零遗留资产 {B.LEGACY_CODE}"
            f"（portfolio_tracker 在调仓时强制清算不在目标权重里的持仓）"
        )
        # 消融对照：同一天在去掉遗留资产后不再是语义分叉日
        ab_days = align_days(ablation_pair["backtest"], ablation_pair["monitor"])
        assert first_divergence(ab_days) is None, (
            "去掉遗留资产后仍有语义分叉，说明分叉不只来自遗留资产，归因不完整"
        )

    def test_legacy_held_by_backtest_only_after_first_rebalance(self, control_pair):
        """首次调仓之后，遗留资产只在回测侧存续."""
        days = align_days(control_pair["backtest"], control_pair["monitor"])
        schedule = rebalance_schedule_gap(days)
        first_rebalance = schedule["monitor"][0]
        after = [d for d in days if d.date > first_rebalance]
        assert after, "首次调仓之后没有可比交易日"
        assert all(d.mon_weights.get(B.LEGACY_CODE, 0.0) == 0.0 for d in after), (
            "监控侧在首次调仓后仍持有遗留资产，与 portfolio_tracker 的强制清算不符"
        )
        assert all(d.bt_weights.get(B.LEGACY_CODE, 0.0) > 0.0 for d in after), (
            "回测侧在首次调仓后不再持有遗留资产，与 execution.py 的不清仓行为不符"
        )

    def test_rebalance_schedule_aligned_when_delay_zero(self, control_pair):
        """T+0 下两侧月度调仓日轴完全重合（执行延迟已对齐的证据）.

        唯一例外是建仓当日：回测标为 ``is_rebalance_day=True``（期初建仓走
        manual_adjustment 分支），监控标为 ``kind='init'``——同一件事的两种标签。
        """
        days = align_days(control_pair["backtest"], control_pair["monitor"])
        schedule = rebalance_schedule_gap(days)
        init_day = days[0].date
        assert schedule["backtest_only"] == [init_day], (
            f"除建仓日外回测不应有额外调仓日，实际: {schedule['backtest_only']}"
        )
        assert schedule["monitor_only"] == [], (
            f"监控不应有回测没有的调仓日，实际: {schedule['monitor_only']}"
        )

    def test_aligned_pair_has_no_cost_basis_diff(self, ablation_pair):
        """对齐口径时 ``ExecutionPolicy.diff`` 必须为空（不误报）.

        两侧 ``fill_model`` 不同（close vs rebalance）不应被当成成本口径差异：
        它们是两种经济语义，而本组实测证明在零成本下两者数值等价。
        """
        pb, pm = ablation_pair["policy_backtest"], ablation_pair["policy_monitor"]
        assert pb.fill_model != pm.fill_model, "两侧成交模型应不同，否则本断言无意义"
        assert pb.is_cost_equivalent(pm, assets=B.CODES)
        assert attribute_policies(pb, pm) == [], (
            "对齐口径下不应报出成本差异（误报会淹没真正的分叉根因）"
        )

    def test_cost_basis_flagged_when_misaligned(self, cost_pair):
        """口径错开时报告首行就指出成本口径（S16 的价值所在）."""
        from app.backtesting.policy import COST_BASIS_GROSS, COST_BASIS_NET

        pb, pm = cost_pair["policy_backtest"], cost_pair["policy_monitor"]
        assert pb.cost_basis == COST_BASIS_NET and pm.cost_basis == COST_BASIS_GROSS
        assert not pb.is_cost_equivalent(pm, assets=B.CODES)
        lines = attribute_policies(pb, pm)
        assert lines, "含费回测 vs gross 监控必须报出口径差异"
        assert "成交口径不同" in lines[0], f"首行应为成本口径归因，实际: {lines[0]}"
        assert pb.policy_hash() != pm.policy_hash(), "不同口径的 policy_hash 不应相同"

        days = align_days(cost_pair["backtest"], cost_pair["monitor"])
        assert first_divergence(days) is not None, (
            "成本口径不同的两侧应逐日分叉；若不分叉，说明回测侧未真正计费"
        )
        report = format_report(cost_pair, days)
        assert "成交口径不同" in report

    def test_fill_model_keeps_policy_hash_distinct(self, ablation_pair):
        """``fill_model`` 参与哈希：两种成交语义必须能被指纹区分.

        两侧有效费率逐资产相等（都为零），但 ``fill_model`` 一个是 close
        （回测增量成交）一个是 rebalance（监控扣费后重建），因此哈希不同。
        这是刻意的：指纹相同会让人误以为两条路径的成交方式也一样。
        ``source`` 不参与哈希，所以差异只可能来自 fill_model 本身。
        """
        pb, pm = ablation_pair["policy_backtest"], ablation_pair["policy_monitor"]
        assert pb.policy_hash() != pm.policy_hash(), (
            "fill_model 不同的两侧哈希应不同（否则指纹无法区分两种成交语义）"
        )
        for code in B.CODES:
            assert pb.effective_cost_of(code) == pm.effective_cost_of(code) == 0.0

    def test_event_sequence_covers_divergence_day(self, control_pair):
        """报告包含首差异日前后的两侧事件序列（现场可复现）."""
        days = align_days(control_pair["backtest"], control_pair["monitor"])
        first = first_divergence(days)
        assert first is not None
        seq = event_sequence(days, first.date, context=1)
        assert len(seq) == 3, f"事件序列应覆盖前一日/当日/后一日，实际 {len(seq)} 行"
        assert any(line.startswith(">>") and first.date in line for line in seq), (
            "事件序列未标记首差异当日"
        )
        assert any("kind=" in line and "rebalance=" in line for line in seq), (
            "事件序列应同时包含两侧的执行标记"
        )
        assert format_report(control_pair, days).count(first.date) >= 2, (
            "报告应在首差异段与事件序列两处出现该日期"
        )


# ======================================================================
#  7. S14：分段运行的 fold 状态续接
# ======================================================================

MONITOR_SERVICE_PATH = BACKEND_ROOT / "app" / "services" / "monitor_service.py"

#: 波动率重置的 fold 状态变量名（含模型口径的并行变量）
FOLD_SEED_NAMES = frozenset({
    "vol_signal_dates", "vol_reset_execute_dates",
    "vol_signal_dates_model", "vol_reset_execute_dates_model",
})

#: 必须写回 fold 状态的函数（三条逐日推演实现 + 模型口径单日推演）
#: 批次改造后 run_* 是「建批次 → 推演 → 收尾」外壳，fold 状态的读与逐日
#: 写回都在 _run_*_impl 里；委托关系由 test_run_entrypoints_delegate_to_impl 钉住。
FOLD_WRITEBACK_FUNCS = frozenset({
    "_run_init_impl", "_run_daily_impl", "_run_range_impl", "_step_model_track_day",
})

#: 对外入口 → 承载逐日循环的实现
RUN_ENTRY_TO_IMPL = {
    "run_init": "_run_init_impl",
    "run_daily": "_run_daily_impl",
    "run_range": "_run_range_impl",
}


def _monitor_service_methods():
    import ast
    tree = ast.parse(MONITOR_SERVICE_PATH.read_text(encoding="utf-8"))
    cls = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "MonitorService"
    )
    return [
        n for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _entrypoint_fold_seeds() -> Dict[str, Dict[str, str]]:
    """三条逐日推演实现对 fold 状态变量的初值表达式（函数名 → 变量名 → 源码）."""
    import ast
    out: Dict[str, Dict[str, str]] = {}
    for fn in _monitor_service_methods():
        if fn.name not in RUN_ENTRY_TO_IMPL.values():
            continue
        seeds: Dict[str, str] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in FOLD_SEED_NAMES:
                    seeds[target.id] = ast.unparse(node.value)
        out[fn.name] = seeds
    return out


def _fold_writebacks() -> Dict[str, set]:
    """各函数通过 ``_remember_fold_date`` 写回的字段名集合."""
    import ast
    out: Dict[str, set] = {}
    for fn in _monitor_service_methods():
        attrs = set()
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_remember_fold_date"):
                continue
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                attrs.add(str(node.args[1].value))
        if attrs:
            out[fn.name] = attrs
    return out


def _blank_portfolio_state(**overrides):
    """最小可构造的 ``PortfolioState``（字段集与 ``run_monitor_path`` 一致）."""
    from app.monitor.types import PortfolioState
    kwargs: Dict[str, Any] = dict(
        date="2022-03-28", nav=1000.0, nav_base=1000.0,
        positions_cny={}, positions_local={}, apl_local={},
        target_weights={}, last_rebalance_date="", last_rebalance_fx={},
    )
    kwargs.update(overrides)
    return PortfolioState(**kwargs)


class TestFoldStateContinuity:
    """S14：波动率重置的 fold 状态必须能跳段落续接.

    缺陷背景：``run_daily`` / ``run_range`` 按 ``processing_dates`` 分段推进，
    段与段之间只能靠落库状态续接；而两个 fold 集合原本每次运行都从空集
    起步，「触发日到执行日间存在其他信号则跳过执行」这条规则跳段静默失效。
    ``run_init`` 单段跑完整区间，因此 regression 层（单段语义）无法验证本修复，
    必须在这里专门覆盖。

    真实的 ``run_daily`` 需要 Mongo 与行情，下面的行为用例覆盖它依赖的那条
    纯状态链路（运行时集合 → 落库字符串 → 下一段还原），再用两个 AST 契约
    用例守住「三个入口记得读落库初值、记得逐日写回」这两个真正的断点。
    """

    @pytest.fixture(scope="class")
    def service(self):
        from app.services.monitor_service import MonitorService
        return MonitorService()

    # ---- AST 契约：两个断点不得回退 ----

    def test_run_entrypoints_delegate_to_impl(self):
        """三个对外入口必须委托到承载 fold 状态的实现.

        否则把 ``_run_*_impl`` 改名即可让下面三个契约用例静默失去覆盖。
        """
        import ast
        sources = {fn.name: ast.unparse(fn) for fn in _monitor_service_methods()}
        for entry, impl in sorted(RUN_ENTRY_TO_IMPL.items()):
            assert entry in sources, f"MonitorService 缺少对外入口 {entry}"
            assert f"self.{impl}(" in sources[entry], (
                f"{entry} 未委托到 {impl}；fold 状态契约需随实现位置同步更新"
            )

    def test_segmented_entrypoints_seed_from_persisted_state(self):
        """``_run_daily_impl`` / ``_run_range_impl`` 的 fold 初值必须从落库状态还原."""
        seeds = _entrypoint_fold_seeds()
        for name in ("_run_daily_impl", "_run_range_impl"):
            got = seeds.get(name) or {}
            assert set(got) == FOLD_SEED_NAMES, (
                f"{name} 的 fold 初值赋值不完整：期望 {sorted(FOLD_SEED_NAMES)}，"
                f"实际 {sorted(got)}"
            )
            for var, expr in sorted(got.items()):
                assert "_fold_dates_to_ts" in expr, (
                    f"{name} 的 {var} 初值不是从落库状态还原：{expr}\n"
                    "分段运行靠落库状态续接；从 set() 起步会让「触发日到执行日"
                    "之间存在其他信号则跳过波动率重置」这条规则跳段静默失效。"
                )

    def test_run_init_seeds_fresh_by_design(self):
        """``_run_init_impl`` 的 fold 初值必须是空集——这是设计，不是遗漏.

        ``run_init`` 单段跑完整区间，全部信号日在本段内重新推导；若从落库
        状态还原反而会重复计入历史信号日。本用例把该区分固定下来，防止
        日后「一并修正」成与 run_daily 一致而引入反向缺陷。
        """
        seeds = _entrypoint_fold_seeds()["_run_init_impl"]
        assert set(seeds) == FOLD_SEED_NAMES
        for var, expr in sorted(seeds.items()):
            assert expr == "set()", (
                f"_run_init_impl 的 {var} 初值应为 set()（单段全区间语义），实际：{expr}"
            )

    def test_all_entrypoints_write_back_fold_dates(self):
        """四个函数都必须逐日写回两个 fold 集合.

        逐日写回而不是循环末尾统一回写：三个入口各有「主观步进暂停」与
        「正常结束」两个 ``save_state`` 出口，逐日写回才能保证任一出口落库
        的状态都带着完整集合。
        """
        writebacks = _fold_writebacks()
        missing = FOLD_WRITEBACK_FUNCS - set(writebacks)
        assert not missing, f"以下函数未写回 fold 状态：{sorted(missing)}"
        for name in sorted(FOLD_WRITEBACK_FUNCS):
            assert writebacks[name] == {"vol_signal_dates", "vol_execute_dates"}, (
                f"{name} 写回的 fold 字段不完整：{sorted(writebacks[name])}"
            )

    # ---- 行为：纯状态链路 ----

    def test_fold_dates_to_ts_roundtrips_persisted_strings(self, service):
        import pandas as pd
        assert service._fold_dates_to_ts(["2022-12-07", "2023-02-07"]) == {
            pd.Timestamp("2022-12-07"), pd.Timestamp("2023-02-07"),
        }

    def test_fold_dates_to_ts_tolerates_legacy_documents(self, service):
        """存量文档无该键（None / 缺失）时得到空集，行为与修复前一致."""
        assert service._fold_dates_to_ts(None) == set()
        assert service._fold_dates_to_ts([]) == set()

    def test_remember_fold_date_is_idempotent(self, service):
        """重复写入同一日不得重复计数（否则集合会逐次运行膨胀）."""
        import pandas as pd
        ps = _blank_portfolio_state()
        for value in (pd.Timestamp("2022-12-07"), pd.Timestamp("2022-12-07"), "2022-12-07"):
            service._remember_fold_date(ps, "vol_signal_dates", value)
        assert ps.vol_signal_dates == ["2022-12-07"]
        # 空值不入集合：非波动率调仓日的 exec_date 为 None
        service._remember_fold_date(ps, "vol_execute_dates", None)
        assert ps.vol_execute_dates == []

    def test_fold_fields_survive_state_roundtrip(self, service):
        """``PortfolioState`` → ``MonitorState`` → ``PortfolioState``：fold 三字段不丢."""
        import pandas as pd
        ps = _blank_portfolio_state(
            state_version=1,
            vol_signal_dates=["2022-12-07", "2023-02-07"],
            vol_execute_dates=["2022-12-09", "2023-02-09"],
        )
        state = service._portfolio_state_to_state(ps, "parity_fold_test")
        assert state.vol_signal_dates == ["2022-12-07", "2023-02-07"]
        assert state.vol_execute_dates == ["2022-12-09", "2023-02-09"]
        assert state.state_version == 1

        back = service._state_to_portfolio_state(state)
        assert back.vol_signal_dates == ps.vol_signal_dates
        assert back.vol_execute_dates == ps.vol_execute_dates
        assert back.state_version == ps.state_version
        assert service._fold_dates_to_ts(back.vol_signal_dates) == {
            pd.Timestamp("2022-12-07"), pd.Timestamp("2023-02-07"),
        }

    def test_fold_fields_survive_in_place_update(self, service):
        """``original=`` 分支（run_daily 常用路径）同样带 fold 字段."""
        import pandas as pd
        ps = _blank_portfolio_state(vol_signal_dates=["2022-12-07"])
        state = service._portfolio_state_to_state(ps, "parity_fold_test")
        service._remember_fold_date(ps, "vol_execute_dates", pd.Timestamp("2022-12-09"))
        updated = service._portfolio_state_to_state(ps, "parity_fold_test", original=state)
        assert updated is state, "original 分支应就地更新并返回同一对象"
        assert updated.vol_execute_dates == ["2022-12-09"]
        assert updated.vol_signal_dates == ["2022-12-07"]

    def test_legacy_document_without_fold_keys_loads(self, service):
        """存量落库文档没有 fold 键时能加载，且退化为修复前行为（空集）."""
        from app.models.monitor import MonitorState
        ps = _blank_portfolio_state(
            vol_signal_dates=["2022-12-07"], vol_execute_dates=["2022-12-09"],
        )
        state = service._portfolio_state_to_state(ps, "parity_fold_test")
        legacy = state.model_dump()
        for key in ("vol_signal_dates", "vol_execute_dates", "state_version"):
            legacy.pop(key, None)
        restored = MonitorState(**legacy)
        back = service._state_to_portfolio_state(restored)
        assert back.vol_signal_dates == []
        assert back.vol_execute_dates == []
        assert back.state_version == 1
        assert service._fold_dates_to_ts(back.vol_signal_dates) == set()

    def test_segmented_run_resumes_from_persisted_fold_state(self, service):
        """分段续接的行为等价形式：段 1 积累的集合，段 2 必须完整拿到.

        这是 S14 修复的核心断言。断点就在「运行时集合 → 落库 → 下一段还原」
        这条链上：修复前每一段都从空集起步，段 2 看不到段 1 的触发日。
        """
        import pandas as pd

        # 段 1：三个触发日 + 两个执行日
        ps = _blank_portfolio_state()
        for date in ("2022-12-07", "2023-01-06", "2023-02-07"):
            service._remember_fold_date(ps, "vol_signal_dates", pd.Timestamp(date))
        for date in ("2022-12-09", "2023-01-10"):
            service._remember_fold_date(ps, "vol_execute_dates", pd.Timestamp(date))
        persisted = service._portfolio_state_to_state(ps, "parity_fold_test")

        # 段 2：从落库文档重建运行时初值
        ps2 = service._state_to_portfolio_state(persisted)
        seed_signal = service._fold_dates_to_ts(ps2.vol_signal_dates)
        seed_execute = service._fold_dates_to_ts(ps2.vol_execute_dates)
        assert seed_signal == {
            pd.Timestamp(d) for d in ("2022-12-07", "2023-01-06", "2023-02-07")
        }, "段 2 未拿到段 1 的全部触发日，「触发日到执行日间有其他信号则跳过」无法判定"
        assert seed_execute == {
            pd.Timestamp(d) for d in ("2022-12-09", "2023-01-10")
        }, "段 2 未拿到段 1 的全部执行日，执行日去重会失效（同一天重复执行）"
        # 规则依赖点：判定 2023-01-10 这次执行是否该跳过，要能看到 2023-01-06 的触发
        assert pd.Timestamp("2023-01-06") in seed_signal
        assert pd.Timestamp("2023-01-10") in seed_execute

        # 段 2 继续积累，不覆盖段 1
        service._remember_fold_date(ps2, "vol_signal_dates", pd.Timestamp("2023-03-07"))
        persisted2 = service._portfolio_state_to_state(ps2, "parity_fold_test", original=persisted)
        assert persisted2.vol_signal_dates == [
            "2022-12-07", "2023-01-06", "2023-02-07", "2023-03-07",
        ]

    def test_persisted_state_carries_execution_policy(self, service):
        """S16：落库状态带 ``execution_policy``，且通用监控为 gross 口径."""
        from app.backtesting.policy import COST_BASIS_GROSS, ExecutionPolicy
        state = service._portfolio_state_to_state(
            _blank_portfolio_state(), "parity_policy_test",
        )
        assert state.execution_policy, "落库状态缺少 execution_policy，分叉时无法归因"
        policy = ExecutionPolicy.from_dict(state.execution_policy)
        assert policy.cost_basis == COST_BASIS_GROSS, (
            "通用监控的 PortfolioTracker.trading_cost 恒空，应为 gross 口径"
        )
        assert policy.source == "monitor_tracker"
        assert policy.policy_hash() == state.execution_policy["policy_hash"], (
            "落库的 policy_hash 与重新计算的指纹不一致"
        )


# ======================================================================
#  8. S13：事件口径归一（parity 报告的事件序列靠它读存量）
# ======================================================================

class TestEventLogNormalization:
    """同一个 ``monitor_states.event_log`` 里共存两套历史口径.

    通用步进写 ``type`` / ``stage`` / ``calc_date``；组合监控写
    ``event_type`` / ``details.weights``。而 ``operation_recorder.
    _sync_single_event`` 只读 ``type``，组合监控的事件因此被静默跳过。
    ``normalize_event`` 把两套口径映射到同一字段集，使读取方不必先判断
    这条事件是哪条路径写的。
    """

    def test_normalize_unifies_both_legacy_shapes(self):
        from app.backtesting.events import EVENT_FIELDS, EVENT_MONTHLY, normalize_event
        stepper_shape = {
            "date": "2022-12-09", "type": "monthly", "stage": "execute",
            "calc_date": "2022-12-07", "description": "执行月度调仓",
        }
        portfolio_shape = {
            "date": "2022-12-09", "event_type": "monthly_rebalance",
            "description": "月度调仓",
            "details": {"weights": {"ASSET0.TEST": 0.5, "ASSET1.TEST": 0.5}},
        }
        a, b = normalize_event(stepper_shape), normalize_event(portfolio_shape)
        assert a["type"] == b["type"] == EVENT_MONTHLY, (
            "两套口径的类型名应归一到同一个规范值"
        )
        assert a["signal_date"] == "2022-12-07", "通用步进的 calc_date 应映射为 signal_date"
        assert b["new_weights"] == {"ASSET0.TEST": 0.5, "ASSET1.TEST": 0.5}, (
            "组合监控的 details.weights 应映射为 new_weights"
        )
        # 两套口径归一后都覆盖全部规范字段（历史键如 calc_date / event_type
        # 附加保留），比对时不会因缺键报错。
        assert set(EVENT_FIELDS) <= set(a), (
            f"通用步进口径归一后缺规范字段：{sorted(set(EVENT_FIELDS) - set(a))}"
        )
        assert set(EVENT_FIELDS) <= set(b), (
            f"组合监控口径归一后缺规范字段：{sorted(set(EVENT_FIELDS) - set(b))}"
        )
        assert "calc_date" in a and "event_type" in b, "历史键应附加保留以供归因"

    def test_normalized_portfolio_event_becomes_readable_by_recorder(self):
        """归一化后组合监控的事件具备 ``type`` 键——不再被静默跳过."""
        from app.backtesting.events import EVENT_MONTHLY, normalize_event
        raw = {"date": "2022-12-09", "event_type": "monthly_rebalance", "description": "x"}
        assert "type" not in raw, "前提：原始组合监控事件没有 type 键"
        assert normalize_event(raw)["type"] == EVENT_MONTHLY

    def test_make_event_assigns_seq_within_date(self):
        from app.backtesting.events import EVENT_MONTHLY, EVENT_VOL_RESET, make_event
        log: List[dict] = []
        first = make_event("2022-12-09", EVENT_MONTHLY, event_log=log)
        log.append(first)
        second = make_event("2022-12-09", EVENT_VOL_RESET, event_log=log)
        log.append(second)
        other_day = make_event("2022-12-12", EVENT_MONTHLY, event_log=log)
        assert (first["seq"], second["seq"], other_day["seq"]) == (0, 1, 0), (
            "seq 应按同日计数，跳日重置（同日多条事件的先后顺序是差异定位的一部分）"
        )
        assert make_event("2022-12-09", EVENT_MONTHLY)["seq"] is None, (
            "不传 event_log 时 seq 应为 None（不能假造序号）"
        )

    def test_events_of_date_filters_and_orders(self):
        from app.backtesting.events import EVENT_MONTHLY, EVENT_VOL_RESET, events_of_date, make_event
        log: List[dict] = []
        for event_type in (EVENT_VOL_RESET, EVENT_MONTHLY):
            log.append(make_event("2022-12-09", event_type, event_log=log))
        log.append(make_event("2022-12-12", EVENT_MONTHLY, event_log=log))
        picked = events_of_date(log, "2022-12-09")
        assert [ev["type"] for ev in picked] == [EVENT_VOL_RESET, EVENT_MONTHLY]
        assert [ev["seq"] for ev in picked] == [0, 1]
        assert len(events_of_date(log, "2022-12-12")) == 1
        assert events_of_date(log, "2023-01-01") == []
        assert events_of_date(None, "2022-12-09") == []

    def test_event_key_and_comparable_fields(self):
        from app.backtesting.events import (
            EVENT_FIELDS, EVENT_MONTHLY, comparable_fields, event_key, make_event,
        )
        ev = make_event(
            "2022-12-09", EVENT_MONTHLY, signal_date="2022-12-07",
            description="执行月度调仓（计算日 2022-12-07）",
        )
        assert event_key(ev) == "2022-12-09|monthly|execute|"
        fields = comparable_fields(ev)
        assert "description" not in fields, "自由文本不参与比对（措辞变化不得报成差异）"
        assert set(fields) == set(EVENT_FIELDS) - {"description"}
        # 归一化幂等：已规范的事件再过一次不变
        assert comparable_fields(ev) == comparable_fields(dict(fields, description="改了措辞"))

    def test_normalize_keeps_unknown_legacy_keys(self):
        """规范之外的历史键附加保留，避免读取方丢信息."""
        from app.backtesting.events import normalize_event
        raw = {"date": "2022-12-09", "event_type": "monthly_rebalance", "legacy_note": "keep"}
        normalized = normalize_event(raw)
        assert normalized["legacy_note"] == "keep"
        assert normalized["event_type"] == "monthly_rebalance", "原始类型名应保留以供归因"
        assert normalize_event(None)["date"] is None, "空事件应返回全 None 的规范壳"


# ======================================================================
#  9. 诊断入口（不影响 pytest 采集）
# ======================================================================

def _main() -> int:
    """直接跑本文件即输出对照组的归因报告.

    两侧净值分叉时用这个入口拿报告，比在 pytest 失败信息里翻更方便：

        py tests\\test_backtest_monitor_parity.py
    """
    prices = B.make_prices()
    print("== 对照组：含遗留资产 + 对齐口径（gross + T+0）==")
    control = run_pair(prices, dict(B.MONITOR_INITIAL_WEIGHTS), monitor_trading_cost={})
    print(format_report(control, align_days(control["backtest"], control["monitor"])))

    print("\n\n== 口径错开组：含费回测（net）vs gross 监控 ==")
    cost = run_pair(
        prices, dict(B.MONITOR_INITIAL_WEIGHTS), monitor_trading_cost={},
        commission_rate=B.MONITOR_TRADING_COST, slippage=0.0, execution_delay=0,
    )
    print(format_report(cost, align_days(cost["backtest"], cost["monitor"])))

    print("\n\n== 消融组：去掉遗留资产 + 对齐口径 ==")
    ablation = run_pair(prices, dict(NO_LEGACY_WEIGHTS), monitor_trading_cost={})
    print(format_report(ablation, align_days(ablation["backtest"], ablation["monitor"])))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
