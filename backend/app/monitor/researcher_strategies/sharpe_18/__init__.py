"""夏普18策略模块（独立引擎）

包含：
- SharpeBudget18Strategy: 策略元数据（供注册表使用）
- run_backtest: 独立回测引擎入口（不依赖 CompositionPipeline）
"""

from app.monitor.researcher_strategies.sharpe_18.strategy import SharpeBudget18Strategy
from app.monitor.researcher_strategies.sharpe_18.engine import run_backtest

__all__ = ["SharpeBudget18Strategy", "run_backtest"]
