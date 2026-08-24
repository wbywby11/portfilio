# -*- coding: utf-8 -*-
"""风险预算权重模型。"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from app.portfolio.weight_models.base import PortfolioWeightModel


class RiskBudgetWeightModel(PortfolioWeightModel):
    """风险预算权重模型：基于子策略的滚动波动率，动态调整权重使每个子策略的风险贡献相等。

    原理：
    - 计算每个子策略的滚动年化波动率
    - 权重与波动率成反比：w_i = (1/σ_i) / Σ(1/σ_j)
    - 当某个子策略波动率上升时，其权重自动降低
    """

    def __init__(
        self,
        lookback_days: int = 60,
        min_weight: float = 0.05,
        max_weight: float = 0.95,
    ) -> None:
        """
        Args:
            lookback_days: 滚动波动率计算窗口（交易日）
            min_weight: 单个子策略的最小权重
            max_weight: 单个子策略的最大权重
        """
        self._lookback = lookback_days
        self._min_w = min_weight
        self._max_w = max_weight

    def compute_weights(
        self,
        sub_navs: Dict[str, pd.Series],
        as_of: pd.Timestamp,
    ) -> Dict[str, float]:
        """基于滚动波动率计算风险预算权重。"""
        inv_vols: Dict[str, float] = {}

        for key, nav in sub_navs.items():
            nav_slice = nav[nav.index <= as_of]
            if len(nav_slice) < max(5, self._lookback // 2):
                # 数据不足，使用等权回退
                inv_vols[key] = 1.0
                continue

            lookback = nav_slice.iloc[-self._lookback:]
            rets = lookback.pct_change(fill_method=None).dropna()
            if len(rets) < 5:
                inv_vols[key] = 1.0
                continue

            vol = float(rets.std() * np.sqrt(260))
            if vol > 1e-8:
                inv_vols[key] = 1.0 / vol
            else:
                inv_vols[key] = 1.0

        # 归一化 + 约束
        total_inv = sum(inv_vols.values())
        if total_inv <= 0:
            n = len(inv_vols)
            return {k: 1.0 / n for k in inv_vols}

        raw_weights = {k: v / total_inv for k, v in inv_vols.items()}

        # 应用 min/max 约束
        clipped = {
            k: max(self._min_w, min(self._max_w, v))
            for k, v in raw_weights.items()
        }
        # 重新归一化
        total_clipped = sum(clipped.values())
        return {k: v / total_clipped for k, v in clipped.items()}
