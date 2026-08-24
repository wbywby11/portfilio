# -*- coding: utf-8 -*-
"""
组合管理模块

独立的组合管理功能模块，包含：
- 组合 CRUD（手工创建、单策略创建、多策略创建）
- 模拟交易（逐日推进、成交记录、快照）
- 权重管理（等权、风险平价、最小方差）
- 绩效计算与归因分析

对外暴露两个路由：
- portfolio_router: 组合管理 API (/api/v1/portfolios)
- sim_trade_router: 模拟交易 API (/api/v1/sim-trade)
"""

from app.portfolio.portfolio_router import router as portfolio_router
from app.portfolio.sim_trade_router import router as sim_trade_router

__all__ = ["portfolio_router", "sim_trade_router"]
