"""API包"""

from app.api.asset import router as asset_router
from app.api.model_template import router as model_template_router
from app.api.strategy_model import router as strategy_model_router
from app.api.portfolio import router as portfolio_router
from app.api.benchmark import router as benchmark_router
from app.api.strategies import router as strategies_router
from app.api.backtests import router as backtests_router
from app.api.financial_product import router as financial_product_router
from app.api.investment_manager import router as investment_manager_router

__all__ = [
    "asset_router",
    "model_template_router",
    "strategy_model_router",
    "portfolio_router",
    "benchmark_router",
    "strategies_router",
    "backtests_router",
    "financial_product_router",
    "investment_manager_router",
]
