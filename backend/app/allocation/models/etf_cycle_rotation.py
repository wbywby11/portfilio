"""等权分配策略.

对选中的资产做等权 1/N 分配。
选择逻辑由资产选择模块驱动，分配层只做等权。
"""

from __future__ import annotations

import pandas as pd

from app.allocation.models.base import BaseStrategyModel


class ETFCycleRotationStrategy(BaseStrategyModel):
    """等权策略（纯分配，选择由资产选择模块驱动）.

    allocate() 仅做等权 1/N 分配，选择逻辑通过 composition 配置
    委托给资产选择模块执行。
    """

    @classmethod
    def get_param_schema(cls):
        """返回参数Schema — 无自有参数.

        选择器参数由前端「资产选择」区域配置。
        """
        from app.allocation.models.param_schema import StrategyParamSchema

        return StrategyParamSchema(
            strategy_type="etf_cycle_rotation",
            display_name="等权",
            description="对选中的资产做等权 1/N 分配，资产筛选请在「资产选择」区域配置。",
            params=[],
            composition={
                "selector": "etf_rotation",
                "allocator": "etf_cycle_rotation",
                "controller": None,
                "schedule": {"rebalance_freq": "weekly", "execution_delay": 0},
            },
        )

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """纯等权分配.

        对传入的（已被选择模块筛选过的）资产做等权 1/N 分配。

        Args:
            prices: 收盘价矩阵（已过滤为选中资产的列）
            **params: 策略参数

        Returns:
            Series, 各资产等权权重 1/N
        """
        if prices.empty:
            return pd.Series(dtype=float)
        n = len(prices.columns)
        if n == 0:
            return pd.Series(dtype=float)
        return pd.Series(1.0 / n, index=prices.columns)
