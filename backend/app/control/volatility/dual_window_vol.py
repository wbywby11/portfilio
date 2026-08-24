"""双层窗口波动率监测控制器.

从 momentum_risk_parity.py 和 trend_cross_sectional.py 提取的通用波动率控制逻辑：
- 使用短期窗口 + 长期窗口的滚动波动率平均值估计当前组合波动率
- 支持 leverage 缩放 (target_vol / vol_est)，上下界 clip
- 参数化配置：vc_short / vc_long 窗口、target_vol、leverage_bounds

与 RollingVolMonitor 的区别：
- RollingVolMonitor 使用多窗口取**最大值**（保守估计）
- DualWindowVolMonitor 使用双窗口取**平均值**（更平滑的波动率估计）
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

from app.control.base import BaseMonitor
from app.control.volatility.rolling_vol import RollingVolMonitor

_log = logging.getLogger(__name__)


class DualWindowVolMonitor(BaseMonitor):
    """双层窗口波动率监测控制器.

    波动率估计 = (短期滚动vol + 长期滚动vol) / 2
    阈值触发式重置：vol_est > vol_reset_threshold 时触发，
    仅向下缩放 min(1.0, target_vol/vol)，由引擎的波动率重置事件消费。

    注：波动率定标（目标波动率杠杆缩放）不是控制器职责，
    而是策略自身的收益层计算（见引擎 vol_targeting_enabled 参数）。

    参数:
        vol_method:            波动率估计方法（rolling=滚动标准差 / ewma=指数加权，默认 rolling）
        vc_short:              短期波动率窗口（默认 20 交易日）
        vc_long:               长期波动率窗口（默认 60 交易日）
        annualization_factor:  年化因子（默认 260 交易日）
        target_vol:            目标年化波动率（默认 0.03）
        vol_reset_threshold:   波动率重置阈值（默认 0.06）
        enable_vol_reset:      是否启用波动率重置（默认 True）
    """

    # ------------------------------------------------------------------
    # 内部：对齐权重与价格
    # ------------------------------------------------------------------

    @staticmethod
    def _align_weights_prices(
        current_weights: pd.Series,
        prices: pd.DataFrame,
    ) -> tuple[pd.Series, pd.DataFrame] | None:
        """复用 RollingVolMonitor 的对齐逻辑."""
        return RollingVolMonitor._align_weights_prices(current_weights, prices)

    # ------------------------------------------------------------------
    # 核心：计算组合波动率（双层窗口平均）
    # ------------------------------------------------------------------

    def _compute_portfolio_vol(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        vc_short: int,
        vc_long: int,
        annualization_factor: int,
        vol_method: str = "rolling",
    ) -> float | None:
        """对齐并计算组合年化波动率（双窗口平均）.

        vol_est = (vol_short + vol_long) / 2

        vol_method:
        - rolling: 滚动窗口标准差（经典口径）
        - ewma:    指数加权标准差（span=窗口，GMSI 2.0 扫描最优口径）
        """
        aligned = self._align_weights_prices(current_weights, prices)
        if aligned is None:
            return None
        weights_aligned, prices_sub = aligned

        returns = prices_sub.pct_change(fill_method=None)
        common_assets = returns.columns.intersection(weights_aligned.index)
        if len(common_assets) == 0:
            return None

        # 缺失收益（停牌/未上市）按 0 计（与 GMSI 原型 fillna(0) 口径一致）；
        # 不能 dropna 整行：否则部分资产上市前的历史会被整体剔除，
        # 导致 vol 估计窗口不足、定标失效
        portfolio_returns = (returns[common_assets].fillna(0) * weights_aligned[common_assets]).sum(axis=1)
        portfolio_returns = portfolio_returns.dropna()

        if len(portfolio_returns) < max(vc_short, vc_long):
            return None

        if vol_method == "ewma":
            min_short = max(5, vc_short // 2)
            vol_short_series = portfolio_returns.ewm(
                span=vc_short, min_periods=min_short
            ).std() * np.sqrt(annualization_factor)
            min_long = max(10, vc_long // 2)
            vol_long_series = portfolio_returns.ewm(
                span=vc_long, min_periods=min_long
            ).std() * np.sqrt(annualization_factor)
        else:
            # 短期滚动波动率
            min_short = max(5, vc_short // 2)
            vol_short_series = portfolio_returns.rolling(
                vc_short, min_periods=min_short
            ).std() * np.sqrt(annualization_factor)

            # 长期滚动波动率
            min_long = max(10, vc_long // 2)
            vol_long_series = portfolio_returns.rolling(
                vc_long, min_periods=min_long
            ).std() * np.sqrt(annualization_factor)

        # 取最新值并求平均
        vol_short = vol_short_series.iloc[-1]
        vol_long = vol_long_series.iloc[-1]

        if np.isnan(vol_short) or np.isnan(vol_long):
            return None

        vol_est = (vol_short + vol_long) / 2.0
        return float(vol_est)

    # ------------------------------------------------------------------
    # BaseMonitor 接口实现
    # ------------------------------------------------------------------

    def compute_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> Dict[str, Any]:
        """计算监控指标：返回 {"portfolio_volatility": vol_est}."""
        vc_short = int(params.get("vc_short", 20))
        vc_long = int(params.get("vc_long", 60))
        annualization_factor = int(params.get("annualization_factor", 260))
        vol_method = str(params.get("vol_method", "rolling")).lower()

        vol = self._compute_portfolio_vol(
            current_weights, prices,
            vc_short=vc_short,
            vc_long=vc_long,
            annualization_factor=annualization_factor,
            vol_method=vol_method,
        )
        if vol is None:
            return {"portfolio_volatility": None}
        return {"portfolio_volatility": vol}

    def check_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> tuple[bool, float | None]:
        """检查波动率是否超过阈值.

        参数:
            enable_vol_reset:     是否启用（默认 True）
            vol_reset_threshold:    阈值（默认 0.06）
        """
        if not params.get("enable_vol_reset", True):
            return False, None

        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))
        vc_short = int(params.get("vc_short", 20))
        vc_long = int(params.get("vc_long", 60))
        annualization_factor = int(params.get("annualization_factor", 260))
        vol_method = str(params.get("vol_method", "rolling")).lower()

        current_vol = self._compute_portfolio_vol(
            current_weights, prices,
            vc_short=vc_short,
            vc_long=vc_long,
            annualization_factor=annualization_factor,
            vol_method=vol_method,
        )
        if current_vol is None:
            return False, None

        triggered = current_vol > vol_reset_threshold
        return triggered, current_vol

    def compute_reset_weights(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> pd.Series:
        """波动率触发时的重置权重：等比例缩放.

        缩放公式：w_new = w_current * (target_vol / vol_trigger)

        优先使用外部传入的 _vol_trigger（信号日已实现波动率），
        保证执行日缩放基准与信号日一致。
        """
        if not params.get("enable_vol_reset", True):
            return current_weights

        target_vol = float(params.get("target_vol", 0.03))
        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))

        # 优先使用信号日 VolTrigger
        vol_trigger = params.get("_vol_trigger") or params.get("vol_trigger")
        if vol_trigger is not None and float(vol_trigger) > 0:
            scale_factor = min(1.0, target_vol / float(vol_trigger))
            return current_weights * scale_factor

        # 兼容：本地重算
        vc_short = int(params.get("vc_short", 20))
        vc_long = int(params.get("vc_long", 60))
        annualization_factor = int(params.get("annualization_factor", 260))
        vol_method = str(params.get("vol_method", "rolling")).lower()

        current_vol = self._compute_portfolio_vol(
            current_weights, prices,
            vc_short=vc_short,
            vc_long=vc_long,
            annualization_factor=annualization_factor,
            vol_method=vol_method,
        )
        if current_vol is None or current_vol <= vol_reset_threshold:
            return current_weights

        scale_factor = min(1.0, target_vol / current_vol)
        return current_weights * scale_factor
