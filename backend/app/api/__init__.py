"""API包"""

from app.api.asset import router as asset_router
from app.api.model_template import router as model_template_router
from app.api.strategy_model import router as strategy_model_router
from app.portfolio import portfolio_router
from app.api.backtests import router as backtests_router

__all__ = [
    "asset_router",
    "model_template_router",
    "strategy_model_router",
    "portfolio_router",
    "backtests_router",
]
