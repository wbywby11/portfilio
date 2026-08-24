# -*- coding: utf-8 -*-
"""组合层权重模型。

支持固定权重、风险预算、四象限信号驱动等多种组合权重策略。
组合层以「第二段引擎运行」落地：子策略 NAV 折算合成资产，经
PortfolioWeightAllocator 适配后由统一引擎逐日撮合（旧路径
CompositeEngine 在 NAV 层复合，双跑验证后退役）。

核心组件
--------
- PortfolioWeightModel: 组合权重模型抽象基类
- FixedWeightModel: 固定权重（默认行为）
- RiskBudgetWeightModel: 基于滚动波动率的风险预算权重
- QuadrantWeightModel: 四象限信号驱动权重（支持事件驱动 / 月度象限 / 月度逆波动率三种模式）
- PortfolioWeightAllocator: 权重模型 → 统一引擎 allocator 适配器
"""

from app.portfolio.weight_models.base import PortfolioWeightModel
from app.portfolio.weight_models.fixed import FixedWeightModel
from app.portfolio.weight_models.risk_budget import RiskBudgetWeightModel
from app.portfolio.weight_models.quadrant import QuadrantWeightModel, REBALANCE_MODES
from app.portfolio.weight_models.engine_adapter import PortfolioWeightAllocator

__all__ = [
    "PortfolioWeightModel",
    "FixedWeightModel",
    "RiskBudgetWeightModel",
    "QuadrantWeightModel",
    "REBALANCE_MODES",
    "PortfolioWeightAllocator",
]
