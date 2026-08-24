# -*- coding: utf-8 -*-
"""监控与回测同源测试（P4 Step2：回测与监控同源）.

验证"监控段 == 回测同区段切片"：回测 = 全历史区间 ``run_unified``；
监控 = 样本外窗口的同一 ``run_unified``。基于 ScheduleResolver 的窗口
不变式（全历史日历分组得全量信号日再按窗口过滤），当监控窗口起点取在
某个调仓信号日时，两次运行应当同源：

  - 窗口内调仓日集合逐日一致（不因窗口切片产生多余/缺失的调仓日）；
  - 归一化后逐日净值增速一致（同一持仓轨迹，只差整体缩放）；
  - Step1 ``generate_targets`` 的调仓快照在全区间与子区间逐条一致
    （调度解析与权重生成同源）。

同源不变式与成本模型无关，此处以零费率运行隔离换手成本差异。
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.risk import RiskConfig
from app.backtesting.runner import RunSpec, run_unified, generate_targets


def _make_prices(n_days: int = 420, n_assets: int = 4, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n_days)
    codes = [f"ASSET{i}.TEST" for i in range(n_assets)]
    rets = rng.normal(0.0004, 0.01, size=(n_days, n_assets))
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=dates, columns=codes)


def _month_first_signals(index: pd.DatetimeIndex) -> list:
    """在日历上识别每月首个交易日（monthly 信号日）."""
    out = []
    prev = None
    for d in index:
        if prev is None or (d.year, d.month) != (prev.year, prev.month):
            out.append(d)
        prev = d
    return out


def _config(prices: pd.DataFrame, start: pd.Timestamp, name: str) -> BacktestConfig:
    return BacktestConfig(
        name=name,
        thscodes=list(prices.columns),
        start_date=start.strftime("%Y%m%d"),
        end_date=prices.index[-1].strftime("%Y%m%d"),
        rebalance_freq="monthly",
        initial_cash=10_000_000.0,
        commission_rate=0.0,
        slippage=0.0,
    )


_COMPOSITION = {"selector": None, "allocator": "risk_parity", "controller": None}


def _make_allocator():
    from app.allocation.models.risk_parity import RiskParityStrategy

    return RiskParityStrategy()


def _make_spec(config, prices) -> RunSpec:
    return RunSpec(
        config=config,
        data_feed=DataFeed(prices=prices.copy(), config=config),
        allocator=_make_allocator(),
        thscodes=list(prices.columns),
        composition=dict(_COMPOSITION),
        strategy_params={},
        risk_config=RiskConfig(),
    )


class TestMonitorHomology:
    """监控段 == 回测同区段切片."""

    def _setup(self):
        prices = _make_prices()
        full_start = prices.index[60]
        # 监控窗口起点：取中段某个月度信号日（月初首个交易日）
        signals = _month_first_signals(prices.index)
        mon_start = next(d for d in signals if d >= prices.index[220])
        full_config = _config(prices, full_start, "homology_full")
        mon_config = _config(prices, mon_start, "homology_monitor")
        return prices, mon_start, full_config, mon_config

    def test_rebalance_dates_identical(self):
        """窗口内调仓日集合：全区间切片 == 监控区间运行."""
        prices, mon_start, full_config, mon_config = self._setup()
        full = run_unified(_make_spec(full_config, prices))
        mon = run_unified(_make_spec(mon_config, prices))

        full_reb = [s.time for s in full.snapshots if s.is_rebalance_day and s.time >= mon_start]
        mon_reb = [s.time for s in mon.snapshots if s.is_rebalance_day]
        assert full_reb, "全区间切片内应存在调仓日"
        assert mon_reb, "监控区间内应存在调仓日（首日为期初建仓）"
        assert full_reb == mon_reb, (
            f"调仓日切片不一致：全区间 {full_reb} vs 监控区间 {mon_reb}"
        )

    def test_nav_growth_identical(self):
        """归一化净值逐日一致：监控段 == 回测同区段切片（只差整体缩放）."""
        prices, mon_start, full_config, mon_config = self._setup()
        full = run_unified(_make_spec(full_config, prices))
        mon = run_unified(_make_spec(mon_config, prices))

        full_nav = pd.Series(
            {s.time: s.total_value for s in full.snapshots}
        )
        mon_nav = pd.Series({s.time: s.total_value for s in mon.snapshots})

        overlap = full_nav.loc[mon_start:]
        assert list(overlap.index) == list(mon_nav.index), "快照日历应逐日对齐"
        base_full = overlap.iloc[0]
        base_mon = mon_nav.iloc[0]
        norm_full = overlap / base_full
        norm_mon = mon_nav / base_mon
        for t in norm_full.index:
            assert norm_full[t] == pytest.approx(norm_mon[t], rel=1e-9, abs=0), (
                f"净值增速在 {t} 出现分叉：回测 {norm_full[t]} vs 监控 {norm_mon[t]}"
            )

    def test_weights_trajectory_identical(self):
        """逐日持仓权重轨迹一致（同一配置决策链）."""
        prices, mon_start, full_config, mon_config = self._setup()
        full = run_unified(_make_spec(full_config, prices))
        mon = run_unified(_make_spec(mon_config, prices))

        full_map = {s.time: s.weights for s in full.snapshots if s.time >= mon_start}
        mon_map = {s.time: s.weights for s in mon.snapshots}
        assert set(full_map) == set(mon_map)
        for t, w_full in full_map.items():
            w_mon = mon_map[t]
            for code in set(w_full) | set(w_mon):
                assert (w_full.get(code) or 0.0) == pytest.approx(
                    w_mon.get(code) or 0.0, rel=0, abs=1e-12
                ), f"{t} 权重分叉：{code}"

    def test_generate_targets_homologous(self):
        """Step1 同源：全区间与监控区间的调仓快照逐条一致."""
        prices, mon_start, full_config, mon_config = self._setup()
        targets_full = [
            t for t in generate_targets(_make_spec(full_config, prices))
            if t["signal_date"] >= mon_start
        ]
        targets_mon = [
            t for t in generate_targets(_make_spec(mon_config, prices))
            if t["signal_date"] >= mon_start
        ]
        assert targets_full, "全区间应生成调仓快照"
        assert len(targets_full) == len(targets_mon), (
            f"快照条数不一致：{len(targets_full)} vs {len(targets_mon)}"
        )
        for tf, tm in zip(targets_full, targets_mon):
            assert tf["signal_date"] == tm["signal_date"]
            assert tf["execute_date"] == tm["execute_date"]
            assert tf["target_weights"].keys() == tm["target_weights"].keys()
            for code, w in tf["target_weights"].items():
                assert w == pytest.approx(tm["target_weights"][code], rel=0, abs=1e-12)
            assert tf["risk_weights"].keys() == tm["risk_weights"].keys()


if __name__ == "__main__":
    t = TestMonitorHomology()
    t.test_rebalance_dates_identical()
    print("[PASS] test_rebalance_dates_identical")
    t.test_nav_growth_identical()
    print("[PASS] test_nav_growth_identical")
    t.test_weights_trajectory_identical()
    print("[PASS] test_weights_trajectory_identical")
    t.test_generate_targets_homologous()
    print("[PASS] test_generate_targets_homologous")
    print("\nAll monitor homology tests passed!")
