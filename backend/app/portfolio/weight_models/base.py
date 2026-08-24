# -*- coding: utf-8 -*-
"""组合层权重模型抽象基类。

支持固定权重、风险预算、信号驱动等多种组合权重策略。
与 CompositeEngine 配合使用，实现动态子策略权重分配。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict

import pandas as pd


class PortfolioWeightModel(ABC):
    """组合层权重模型。支持固定权重、风险预算、信号驱动等模式。"""

    @abstractmethod
    def compute_weights(
        self,
        sub_navs: Dict[str, pd.Series],
        as_of: pd.Timestamp,
    ) -> Dict[str, float]:
        """根据子策略 NAV 历史计算目标权重。

        Args:
            sub_navs: 各子策略的 NAV 序列
            as_of: 计算截止日期

        Returns:
            Dict[str, float]: 子策略标识 → 目标权重（和为 1.0）
        """
