# -*- coding: utf-8 -*-
"""单日推演初始日（步骤A）结果契约回归测试.

run_init 首日必走步骤A提前返回分支，服务层主循环以直取方式消费
``result['operation_events']``（双轨并行步进共享事件列表）等键。
历史缺陷：步骤A返回的 init_result 未携带这些键，导致初始化监控
首日即 KeyError('operation_events')（500）。本测试以桩宿主隔离
tracker/adapter，验证初始日结果与步骤F的契约一致，不依赖数据库。
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.monitor.daily_stepper import DailyStepperMixin
from app.monitor.types import PortfolioState

# 服务层（monitor_service.run_init/run_daily/run_range）直取或依赖的键
CONTRACT_KEYS = {
    "operation_events",
    "vol_reset_triggered",
    "vol_reset_execute_date",
    "executed_override_id",
    "asset_returns_local",
    "asset_returns_cny",
}


class _StubTracker:
    """最小 tracker 桩：仅覆盖初始日分支用到的接口."""

    asset_list = ["A.TEST", "B.TEST"]

    def get_all_fx_rates(self, date, fx_df):
        return {"CNY": 1.0}

    def get_all_asset_fx_rates(self, date, fx_df):
        return {a: 1.0 for a in self.asset_list}

    def initialize_positions(self, state, weights, fx_rates, prices_today=None):
        state.positions_cny = {a: state.nav * w for a, w in weights.items()}

    def calc_current_weights(self, state):
        return dict(state.target_weights)


class _StubHost(DailyStepperMixin):
    def __init__(self):
        self.tracker = _StubTracker()
        self._merged_monitor_params = {}

    def _get_engine_adapter(self, rt):
        return None

    def _attach_manual_rebalance_observation(
        self, state, date_str, prices_df, rt, is_rebalance_day, result
    ):
        return None


def _make_inputs():
    dates = pd.bdate_range("2025-02-10", periods=5)
    prices_df = pd.DataFrame(
        100.0, index=dates, columns=_StubTracker.asset_list
    )
    state = PortfolioState(
        date="",
        nav=1000.0,
        nav_base=1000.0,
        positions_cny={},
        positions_local={},
        apl_local={},
        target_weights={},
        last_rebalance_date="",
        last_rebalance_fx={},
    )
    return prices_df, pd.DataFrame(), list(dates), state


def test_init_day_result_carries_service_contract_keys():
    """初始日结果必须携带服务层直取的全部键（KeyError 回归防护）."""
    prices_df, fx_df, trade_dates, state = _make_inputs()
    host = _StubHost()
    base_str = str(prices_df.index[0])[:10]

    result = host._process_single_day(
        state, base_str, prices_df, fx_df, trade_dates,
        {}, set(), set(), [], None,
        base_date=base_str,
    )

    assert result["rebalance_type"] == "init"
    missing = CONTRACT_KEYS - set(result.keys())
    assert not missing, f"初始日结果缺失契约键: {missing}"
    # 服务层直取语义（monitor_service 双轨步进传参方式）
    shared = result["operation_events"]
    assert isinstance(shared, list)
    assert result["vol_reset_triggered"] is False


def test_init_day_reuses_shared_operation_events_list():
    """双轨语义：调用方传入共享事件列表时，初始日结果须原样带回."""
    prices_df, fx_df, trade_dates, state = _make_inputs()
    host = _StubHost()
    base_str = str(prices_df.index[0])[:10]
    shared_events = []

    result = host._process_single_day(
        state, base_str, prices_df, fx_df, trade_dates,
        {}, set(), set(), [], None,
        base_date=base_str,
        operation_events=shared_events,
    )

    assert result["operation_events"] is shared_events


def test_step_model_track_day_runs_without_name_error():
    """模型轨单日步进可执行：历史缺陷为函数体引用未定义的
    ``monthly_signal_dates``（NameError），被上层 KeyError 遮蔽，
    首缺陷修复后才暴露。此处以桩宿主直接调用未绑定方法回归防护。"""
    from app.services.monitor_service import MonitorService

    prices_df, fx_df, trade_dates, state = _make_inputs()
    host = _StubHost()
    host._monitor_runtime = None
    base_str = str(prices_df.index[0])[:10]

    prev_nav = MonitorService._step_model_track_day(
        host, state, base_str, prices_df.index[0], prices_df, fx_df, trade_dates,
        {}, set(), set(), set(), None, base_str, [],
        monthly_signal_dates=set(),
    )

    assert prev_nav == state.nav


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
