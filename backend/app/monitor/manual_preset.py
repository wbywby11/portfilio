# -*- coding: utf-8 -*-
"""
监控服务 Mixin：主观配置（manual_allocation）预设调仓步进与观察指标

自 monitor_service.py 平移而来，方法体保持不变，仅按职责归组：
1. 预设调仓日步进暂停辅助（step pause helpers）
2. 调仓日观察指标（组合/单资产波动率）计算与挂载
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any
from loguru import logger

from app.monitor import config
from app.monitor.types import PortfolioState
from app.monitor.time_norm import normalize_calendar_timestamp


class ManualPresetMixin:
    """主观配置策略的预设调仓步进与观察指标辅助方法。

    依赖宿主（MonitorService）属性：reporter、vol_calculator。
    """

    def _manual_preset_step_active(
        self, manual_preset_step: bool, rt
    ) -> bool:
        """主观配置策略下，是否启用预设调仓日步进暂停（每处理完一个调仓日当周停一次，便于查看绩效）。"""
        return bool(
            manual_preset_step
            and rt is not None
            and getattr(rt, "manual_allocation_mode", False)
        )

    @staticmethod
    def _should_pause_after_manual_preset_day(
        day_index: int,
        processing_dates: List,
        monthly_rebalance_dates: set,
    ) -> bool:
        """当日为预设调仓日且本日已推演完毕时，在当日结束后暂停（暂停日=调仓日当日）。"""
        if day_index < 0 or day_index >= len(processing_dates):
            return False
        return processing_dates[day_index] in monthly_rebalance_dates

    @staticmethod
    def _first_future_manual_preset_index(
        processing_dates: List,
        monthly_rebalance_dates: set,
        after_index: int,
    ) -> Optional[int]:
        for j in range(after_index + 1, len(processing_dates)):
            if processing_dates[j] in monthly_rebalance_dates:
                return j
        return None

    @staticmethod
    def _manual_preset_step_pending_after_pause(
        day_index: int,
        processing_dates: List,
    ) -> bool:
        """暂停后若行情上仍有更晚的交易日未推演，则需要「继续执行」续跑。"""
        return day_index < len(processing_dates) - 1

    @staticmethod
    def _pause_payload_as_of_date(ps: PortfolioState) -> str:
        d = ps.date
        if d is None:
            return ""
        if hasattr(d, "strftime"):
            return d.strftime("%Y-%m-%d")
        s = str(d)
        return s[:10] if len(s) >= 10 else s

    @staticmethod
    def _set_manual_preset_step_flags(
        state,
        pending: bool,
        next_preset_yyyy_mm_dd: Optional[str] = None,
    ) -> None:
        state.manual_preset_step_pending = bool(pending)
        state.manual_preset_next_date = (
            next_preset_yyyy_mm_dd if pending else None
        )

    def _manual_preset_step_pause_payload(
        self,
        ps: PortfolioState,
        processing_dates: List,
        monthly_rebalance_dates: set,
        day_index: int,
        last_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        next_j = self._first_future_manual_preset_index(
            processing_dates, monthly_rebalance_dates, day_index
        )
        next_preset_date = (
            processing_dates[next_j].strftime("%Y-%m-%d") if next_j is not None else ""
        )
        remaining: List[str] = []
        for j in range(day_index + 1, len(processing_dates)):
            if processing_dates[j] in monthly_rebalance_dates:
                remaining.append(processing_dates[j].strftime("%Y-%m-%d"))
        perf_dict = self.reporter.calc_performance_api_dict(ps)
        nav_hist = ps.nav_history or []
        init_only = bool(
            last_result and last_result.get("rebalance_type") == "init"
        )
        tw = ps.target_weights or {}
        current_target_weights = {
            str(k): float(v) for k, v in tw.items() if v is not None
        }
        return {
            "paused": True,
            "manual_preset_step": True,
            "as_of_date": self._pause_payload_as_of_date(ps),
            "next_preset_date": next_preset_date,
            "remaining_preset_dates": remaining,
            "init_only_before_next_preset": init_only,
            "nav_history_length": len(nav_hist),
            "base_nav": float(config.BASE_VALUE),
            "current_target_weights": current_target_weights,
            "performance": perf_dict,
            "nav": float(ps.nav) if ps.nav is not None else 0.0,
            "day_count": ps.day_count,
        }

    # ============================================================
    # 调仓日观察指标（组合/单资产波动率）
    # ============================================================

    def _manual_allocation_rebalance_observation(
        self,
        prices_df: pd.DataFrame,
        date_str: str,
        target_weights: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        主观策略调仓日：与回测调仓后一致，用「调仓后目标权重」在历史价上计算组合/单资产波动率等观察指标。
        口径与 VolatilityCalculator.calc_portfolio_volatility_raw / calc_asset_volatility_raw 一致（VOL_WINDOWS 多窗取 max）。
        """
        out: Dict[str, Any] = {}
        try:
            if prices_df is None or getattr(prices_df, "empty", True):
                return out
            dt = normalize_calendar_timestamp(pd.Timestamp(str(date_str)[:10]))
            if dt not in prices_df.index:
                return out
            idx = prices_df.index.get_loc(dt)
            if isinstance(idx, slice):
                return out
            min_rows = int(config.VOL_WINDOWS[0]) if config.VOL_WINDOWS else 22
            if idx < min_rows - 1:
                return out
            w_raw = {str(k).strip(): float(v or 0) for k, v in (target_weights or {}).items()}
            w_pos = {k: v for k, v in w_raw.items() if v > 0 and k in prices_df.columns}
            if not w_pos:
                return out
            port_vol_raw = self.vol_calculator.calc_portfolio_volatility_raw(prices_df, w_pos, dt)
            try:
                port_vol = float(port_vol_raw)
            except (TypeError, ValueError):
                port_vol = None
            if port_vol is not None and (np.isnan(port_vol) or np.isinf(port_vol)):
                port_vol = None
            asset_vols = self.vol_calculator.calc_asset_volatility_raw(prices_df, dt)
            av_clean: Dict[str, float] = {}
            if isinstance(asset_vols, dict):
                for code in w_pos:
                    val = asset_vols.get(code)
                    if val is None:
                        continue
                    try:
                        fv = float(val)
                    except (TypeError, ValueError):
                        continue
                    if np.isnan(fv) or np.isinf(fv):
                        continue
                    av_clean[code] = fv
            mm = {
                "portfolio_volatility": port_vol,
                "asset_volatility": av_clean,
            }
            out["portfolio_volatility"] = port_vol
            out["monitoring_metrics"] = mm
            return out
        except Exception as e:
            logger.warning(f"主观策略调仓日观察指标计算失败 {date_str}: {e}")
            return {}

    def _attach_manual_rebalance_observation(
        self,
        state: PortfolioState,
        date_str: str,
        prices_df: pd.DataFrame,
        rt,
        is_rebalance_day: bool,
        result: Dict[str, Any],
    ) -> None:
        if rt is None or not getattr(rt, "manual_allocation_mode", False) or not is_rebalance_day:
            return
        obs = self._manual_allocation_rebalance_observation(
            prices_df, date_str, dict(state.target_weights or {})
        )
        if not obs:
            return
        result["rebalance_observation"] = obs
        for ev in reversed(state.event_log):
            if ev.get("date") != date_str:
                continue
            et = ev.get("type", "") or ev.get("event_type", "")
            st = ev.get("stage", "")
            if et == "init":
                ev["rebalance_observation"] = obs
                break
            if et == "subjective":
                ev["rebalance_observation"] = obs
                break
            if et == "monthly":
                ev["rebalance_observation"] = obs
                break
            if et == "vol_reset" and st == "execute":
                ev["rebalance_observation"] = obs
                break
