"""指数净值计算器.

封装analysis.formulas.nav模块的公式，提供面向对象的接口。
根据文档《净值计算.md》实现指数净值分段累加的核心公式：

Index_{{s+t}} = Index_s + \sum_c APL_CNY_{{s+t}}^c

当前版本实现了**单一权重区间（无再平衡）**的净值计算：
- 假设在起始日s给定一组固定的目标权重TW_s^c
- 在区间内权重不再变化（无调仓），因此无交易费用（TC_t^c = 0）
- 支持复制费用（RC_t^c）和汇率（FX_t^c）

后续可以基于本模块扩展多次调仓（多周期s1, s2, ...）的分段累加逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

# 从 formulas 模块导入核心公式
from app.analysis.formulas.nav import calculate_index_nav


@dataclass
class IndexNavConfig:
    """指数净值计算配置.

    Attributes:
        initial_index: 起始净值（Index_s），默认1000
        risk_free_rate: 无风险利率（当前版本未直接使用，预留）
    """

    initial_index: float = 1000.0
    risk_free_rate: float = 0.0


class NAVCalculator:
    """指数净值计算器（单一权重区间版本）.

    用途：
        在给定：
        - 多个资产的TR样本点位序列 TR_t^c
        - 起始日s的目标权重 TW_s^c
        - 可选的复制费用率 rc^c
        - 可选的汇率 FX_t^c

        的情况下，计算从 s 到 T 的指数净值序列 Index_t。

    公式依据《净值计算.md》：

    1. 资产本币累计损益：
       APL_{{s+t}}^c = APL_{{s+t-1}}^c + PV_{{s+t-1}}^c * (TR_{{s+t}}^c / TR_{{s+t-1}}^c - 1) - TC_{{s+t}}^c - RC_{{s+t}}^c

       当前版本：
       - 无调仓：TC_{{s+t}}^c = 0
       - 复制费用：RC_{{s+t}}^c = PV_{{s+t-1}}^c * rc^c / 365

    2. 人民币计价累计损益：
       APL_CNY_{{s+t}}^c = APL_{{s+t}}^c * FX_{{s+t}}^c

    3. 指数净值：
       Index_{{s+t}} = Index_s + \sum_c APL_CNY_{{s+t}}^c

    注意：
        - 本版本不处理多次权重调整，只适用于“一个起点 s + 固定权重”的场景；
        - 与回测引擎中的净值计算逻辑是互补的：本模块适合离线指数编制与验证；
        - 后续可以在此基础上扩展多段权重/波动率重置等逻辑。
    """

    def __init__(self, config: Optional[IndexNavConfig] = None) -> None:
        self.config = config or IndexNavConfig()

    def compute_single_segment_index_nav(
        self,
        tr_series: Dict[str, pd.Series],
        weights: Dict[str, float],
        fx_series: Optional[Dict[str, pd.Series]] = None,
        replication_cost_rates: Optional[Dict[str, float]] = None,
    ) -> pd.Series:
        """计算单一权重区间的指数净值序列.

        Args:
            tr_series: 资产TR序列字典 {thscode: TR_t^c (pd.Series)}
            weights: 起始日s的目标权重 TW_s^c
            fx_series: 汇率序列 {thscode: FX_t^c}
            replication_cost_rates: 复制费用率 {thscode: rc^c}

        Returns:
            指数净值序列 Index_t (pd.Series)
        """
        return calculate_index_nav(
            tr_series=tr_series,
            weights=weights,
            initial_index=self.config.initial_index,
            fx_series=fx_series,
            replication_cost_rates=replication_cost_rates,
        )
