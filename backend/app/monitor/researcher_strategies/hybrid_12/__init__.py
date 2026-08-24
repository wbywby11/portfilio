"""混合动量12策略模块（独立引擎）

包含：
- HybridMomentum12Strategy: 策略元数据（供注册表使用）
- run_backtest: 独立回测引擎入口（不依赖 CompositionPipeline）
"""

from app.monitor.researcher_strategies.hybrid_12.strategy import HybridMomentum12Strategy
from app.monitor.researcher_strategies.hybrid_12.engine import run_backtest

__all__ = ["HybridMomentum12Strategy", "run_backtest"]
