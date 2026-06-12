"""策略服务层 - 统一的策略管理与调度服务.

本模块提供策略的注册、配置管理、参数验证和权重计算服务。
采用服务化架构，支持前后端解耦和未来的微服务扩展。
"""

from app.strategies.services.strategy_service import StrategyService
from app.strategies.services.config import StrategyConfig

__all__ = ["StrategyService", "StrategyConfig"]
