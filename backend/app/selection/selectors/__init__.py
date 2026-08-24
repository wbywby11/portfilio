"""资产选择器实现."""

from app.selection.selectors.base import BaseAssetSelector
from app.selection.selectors.momentum_reversal import MomentumReversalSelector
from app.selection.selectors.sharpe import SharpeSelector
from app.selection.selectors.cross_sectional_momentum import CrossSectionalMomentumSelector
from app.selection.selectors.trend_following import TrendFollowingSelector
from app.selection.selectors.cross_sectional_long_short import CrossSectionalLongShortSelector
from app.selection.selectors.etf_rotation import ETFRotationSelector
from app.selection.selectors.etf_discount import ETFDiscountSelector

__all__ = [
    'BaseAssetSelector',
    'MomentumReversalSelector',
    'SharpeSelector',
    'CrossSectionalMomentumSelector',
    'TrendFollowingSelector',
    'CrossSectionalLongShortSelector',
    'ETFRotationSelector',
    'ETFDiscountSelector',
]
