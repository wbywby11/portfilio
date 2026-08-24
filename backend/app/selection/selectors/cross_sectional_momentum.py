"""截面动量资产选择器.

从 momentum_risk_parity.py 提取的截面动量择时逻辑：
- 计算 rolling 动量分数（累计收益率）
- 选出 top_n 品种
- 返回 selection_mask (0/1)

与 MomentumSelector 的区别：
- MomentumSelector 使用 SHARP 多窗口动量因子
- CrossSectionalMomentumSelector 使用简单的 rolling 累计收益率
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.selection.selectors.base import BaseAssetSelector
from app.selection.types import SelectionResult


class CrossSectionalMomentumSelector(BaseAssetSelector):
    """截面动量选择器：rolling 动量分数 -> 选 top_n.

    核心特点：
    - 计算过去 N 日的累计收益率作为动量分数
    - 按动量分数降序排序，选前 top_n 个品种
    - 返回 0/1 选择掩码

    参数:
        momentum_window: 动量回顾窗口（交易日，默认 20）
    """

    @classmethod
    def get_param_schema(cls):
        return {
            "selector_type": "cross_sectional_momentum",
            "display_name": "截面动量",
            "description": "基于 rolling 累计收益率的截面动量择时，选出动量最强的 top_n 品种",
            "params": [
                {
                    "name": "momentum_window",
                    "label": "动量回顾窗口",
                    "type": "number",
                    "default": 20,
                    "min_value": 5,
                    "max_value": 120,
                    "step": 1,
                    "description": "截面动量回顾窗口（交易日）",
                },
            ],
        }

    def select(
        self,
        prices: pd.DataFrame,
        n_assets: int,
        **params,
    ) -> SelectionResult:
        """执行截面动量资产选择.

        Args:
            prices: 候选资产价格矩阵（index: 日期，columns: 资产代码）
            n_assets: 选择资产数量 (top_n)
            **params:
                - momentum_window: 动量回顾窗口（默认 20）

        Returns:
            SelectionResult: 选择结果
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        momentum_window = int(params.get("momentum_window", 20))
        returns = prices.pct_change(fill_method=None).iloc[1:]

        # 计算动量分数：rolling 累计收益率
        momentum = returns.rolling(
            momentum_window, min_periods=momentum_window
        ).apply(lambda x: np.prod(1 + x) - 1)

        # 历史窗口不足（如回测首日）：无动量可算，返回全资产（与下方空动量分支同语义）
        if momentum.empty:
            return SelectionResult(
                selected_assets=list(prices.columns),
                scores={},
                ranking=pd.DataFrame(),
                timestamp=pd.Timestamp.now().isoformat(),
                selector_type="cross_sectional_momentum",
                params=params,
            )

        # 使用最后一行的动量分数进行排序
        latest_momentum = momentum.iloc[-1].dropna()
        if latest_momentum.empty:
            # 数据不足，返回全资产
            return SelectionResult(
                selected_assets=list(prices.columns),
                scores={},
                ranking=pd.DataFrame(),
                timestamp=pd.Timestamp.now().isoformat(),
                selector_type="cross_sectional_momentum",
                params=params,
            )

        n_total = len(latest_momentum)
        top_n = min(n_assets, n_total)

        # 按动量降序排序，选前 top_n
        sorted_assets = latest_momentum.sort_values(ascending=False)
        selected = sorted_assets.index[:top_n].tolist()
        scores = sorted_assets.to_dict()

        # 构造排名表
        ranking = pd.DataFrame({
            "Asset": sorted_assets.index,
            "MomentumScore": sorted_assets.values,
            "Rank": range(1, len(sorted_assets) + 1),
            "Selected": [a in selected for a in sorted_assets.index],
        }).set_index("Asset")

        return SelectionResult(
            selected_assets=selected,
            scores=scores,
            ranking=ranking,
            timestamp=pd.Timestamp.now().isoformat(),
            selector_type="cross_sectional_momentum",
            params=params,
        )
