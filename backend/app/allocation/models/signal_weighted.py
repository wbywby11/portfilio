"""Signal-weighted allocator — converts selector signal scores to allocation weights.

This class exposes a single entry point:

    allocate(prices: DataFrame, **params) -> Series

Inputs
------
- prices: cleaned price matrix (index: datetime, columns: asset identifiers)
- params (optional):
    - _signal_weights: signal scores from upstream selectors (dict: asset -> score)
    - signal_normalize: whether to normalize weights to sum=1 (default: True)
    - min_weight: lower bound per asset (default: 0.0)
    - max_weight: upper bound per asset (default: 1.0)

Output
------
Series indexed by asset codes with allocation weights.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.allocation.models.base import BaseStrategyModel


class SignalWeightedStrategy(BaseStrategyModel):
    """Signal-weighted allocation strategy.

    Converts signal scores produced by upstream selectors into portfolio weights.
    When no signal input is available, falls back to equal weight.
    """

    @classmethod
    def get_param_schema(cls):
        """返回信号加权策略的参数Schema."""
        from app.allocation.models.param_schema import StrategyParamSchema, ParamSchema

        return StrategyParamSchema(
            strategy_type="signal_weighted",
            display_name="信号加权",
            description=(
                "根据上游选择器输出的信号分数分配权重，信号越强权重越大。"
                "无信号时退化为等权配置。支持归一化、权重约束等。"
            ),
            params=[
                ParamSchema(
                    name="signal_normalize",
                    label="信号归一化",
                    type="boolean",
                    default=True,
                    required=False,
                    description="是否将信号权重归一化到总和为1（推荐开启）",
                ),
                ParamSchema(
                    name="min_weight",
                    label="单资产最小权重",
                    type="number",
                    default=0.0,
                    required=False,
                    min_value=0.0,
                    max_value=0.5,
                    description="每个资产的最小分布权重",
                ),
                ParamSchema(
                    name="max_weight",
                    label="单资产最大权重",
                    type="number",
                    default=1.0,
                    required=False,
                    min_value=0.01,
                    max_value=1.0,
                    description="每个资产的最大分布权重",
                ),
            ],
        )

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """Convert signal scores to allocation weights.

        Args:
            prices: Date × Ticker price matrix.
            **params:
                _signal_weights: dict of {asset_code: signal_score} from selectors.
                signal_normalize: normalize to sum(|w|)=1 (default True).
                min_weight: per-asset lower bound (default 0.0).
                max_weight: per-asset upper bound (default 1.0).

        Returns:
            Series indexed by asset codes with allocation weights.
        """
        assets = list(prices.columns)
        n_assets = len(assets)

        signal_weights = params.get("_signal_weights")

        if signal_weights and isinstance(signal_weights, dict):
            weights = pd.Series(
                [float(signal_weights.get(a, 0.0)) for a in assets],
                index=prices.columns,
            )
        else:
            # Fallback: equal weight
            weights = pd.Series(
                [1.0 / n_assets] * n_assets, index=prices.columns
            )

        min_weight = float(params.get("min_weight", 0.0))
        max_weight = float(params.get("max_weight", 1.0))

        weights = weights.clip(lower=min_weight, upper=max_weight)

        signal_normalize = params.get("signal_normalize", True)
        if signal_normalize:
            positive_mask = weights > 0
            total = weights.abs().sum()
            if total > 0:
                weights = weights / total

        return weights
