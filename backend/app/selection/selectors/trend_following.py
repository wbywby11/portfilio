"""趋势跟踪资产选择器.

从 trend_cross_sectional.py._trend_following() 提取的趋势跟踪信号逻辑：
- 每个品种独立判断多空方向
- 计算过去 N 日累计收益 -> sign 决定方向
- 波动率倒数加权分配仓位
- 归一化到 sum(|w|) = 1
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.selection.selectors.base import BaseAssetSelector
from app.selection.types import SelectionResult


class TrendFollowingSelector(BaseAssetSelector):
    """趋势跟踪选择器：累计收益方向 -> inv_vol 加权 -> 多空信号.

    核心特点：
    - 每个品种独立判断多空方向（sign of rolling momentum）
    - 波动率倒数加权分配仓位大小
    - 支持入场阈值（sigma 倍数过滤噪声）

    参数:
        tf_lookback:   趋势跟踪窗口（交易日，默认 25）
        tf_threshold:  入场阈值（sigma 倍数，0=直接用方向，默认 0.0）
    """

    @classmethod
    def get_param_schema(cls):
        return {
            "selector_type": "trend_following",
            "display_name": "趋势跟踪",
            "description": "基于趋势跟踪的多空信号选择器，每个品种独立判断方向",
            "params": [
                {
                    "name": "tf_lookback",
                    "label": "趋势跟踪窗口",
                    "type": "number",
                    "default": 25,
                    "min_value": 5,
                    "max_value": 120,
                    "step": 1,
                    "description": "趋势跟踪信号回顾期（交易日，GMSI 2.0 对齐口径默认 25）",
                },
                {
                    "name": "tf_threshold",
                    "label": "趋势入场阈值",
                    "type": "number",
                    "default": 0.0,
                    "min_value": 0.0,
                    "max_value": 3.0,
                    "step": 0.1,
                    "description": "趋势跟踪入场阈值（sigma 倍数，0=直接用方向）",
                },
            ],
        }

    def select(
        self,
        prices: pd.DataFrame,
        n_assets: int,
        **params,
    ) -> SelectionResult:
        """执行趋势跟踪信号选择.

        Args:
            prices: 候选资产价格矩阵
            n_assets: 不使用（趋势跟踪对所有资产独立判断）
            **params:
                - tf_lookback: 趋势窗口（默认 25）
                - tf_threshold: 入场阈值（默认 0.0）

        Returns:
            SelectionResult: 选择结果（scores 为方向信号，tags 为 long/short/neutral）
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        tf_lookback = int(params.get("tf_lookback", 25))
        tf_threshold = float(params.get("tf_threshold", 0.0))

        returns = prices.pct_change(fill_method=None)

        # 过去 N 日累计收益（向量化：Π(1+r)-1 ≡ expm1(Σln(1+r))，
        # 避免逐窗口 Python lambda，日频策略回测提速显著）
        momentum = np.expm1(
            np.log1p(returns).rolling(tf_lookback, min_periods=tf_lookback).sum()
        )

        # 波动率
        vol = returns.rolling(20, min_periods=10).std()

        # 方向信号
        latest_momentum = momentum.iloc[-1]
        latest_vol = vol.iloc[-1]

        if tf_threshold > 0:
            roll_std = returns.rolling(tf_lookback, min_periods=tf_lookback).std().iloc[-1]
            signals = pd.Series(0.0, index=latest_momentum.index)
            for asset in latest_momentum.index:
                m = latest_momentum.get(asset, 0)
                s = roll_std.get(asset, 0)
                if pd.isna(m) or pd.isna(s) or s == 0:
                    continue
                if m > tf_threshold * s:
                    signals[asset] = 1
                elif m < -tf_threshold * s:
                    signals[asset] = -1
        else:
            signals = pd.Series(
                np.sign(np.where(latest_momentum.isna(), 0, latest_momentum.values)),
                index=latest_momentum.index,
            ).fillna(0)

        # 波动率倒数加权（vol 未知品种按 inv_vol=1.0，与原型 fillna(1.0) 一致；
        # 归一化分母仅含持仓品种，对齐原型 abs_weights = signals.abs() * inv_vol
        # 口径：空仓品种不入分母，避免持仓权重被平摊品种稀释）
        inv_vol = 1.0 / latest_vol.replace(0, np.nan).replace(np.inf, np.nan).fillna(1.0)
        inv_vol = inv_vol.fillna(0)
        total = float((signals.abs() * inv_vol).sum())
        if total > 0:
            weights = signals * inv_vol / total
        else:
            weights = signals * 0

        # 构造结果
        selected = [a for a in weights.index if abs(weights.get(a, 0)) > 0]
        scores = weights.to_dict()
        tags = {}
        for a in prices.columns:
            s = signals.get(a, 0)
            if s > 0:
                tags[a] = "long"
            elif s < 0:
                tags[a] = "short"
            else:
                tags[a] = "neutral"

        ranking = pd.DataFrame({
            "Asset": list(weights.index),
            "Signal": [signals.get(a, 0) for a in weights.index],
            "Weight": [weights.get(a, 0) for a in weights.index],
        }).set_index("Asset")

        return SelectionResult(
            selected_assets=selected,
            scores=scores,
            ranking=ranking,
            timestamp=pd.Timestamp.now().isoformat(),
            selector_type="trend_following",
            params=params,
            tags=tags,
        )
