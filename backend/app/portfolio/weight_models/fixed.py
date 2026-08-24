# -*- coding: utf-8 -*-
"""固定权重模型。"""

from __future__ import annotations

from typing import Dict

import pandas as pd

from app.portfolio.weight_models.base import PortfolioWeightModel


class FixedWeightModel(PortfolioWeightModel):
    """固定权重模型：每次再平衡都重置为目标权重。等同重构前默认行为。"""

    def __init__(self, weights: Dict[str, float]) -> None:
        """
        Args:
            weights: 各子策略的目标配置权重（和应为 1.0）
        """
        total = sum(weights.values())
        if total <= 0:
            raise ValueError(f"权重总和无效: {total}")
        self._weights = {k: v / total for k, v in weights.items()}

    def compute_weights(
        self,
        sub_navs: Dict[str, pd.Series],
        as_of: pd.Timestamp,
    ) -> Dict[str, float]:
        return dict(self._weights)
