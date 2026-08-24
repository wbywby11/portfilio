"""资产选择模块 - 动量筛选、反转筛选与资产池管理.

提供可插拔的选择器注册表，供回测引擎、组合流水线和 AI Agent 调用。

用法:
    from app.selection import create_selector, SELECTION_REGISTRY

    selector = create_selector("momentum")
    result = selector.select(prices, n_assets=5, min_history_days=260)

注册表:
    SELECTION_REGISTRY 字典映射 selector_type 字符串到对应的 Selector 类。
    新增选择器只需：
    1. 继承 BaseAssetSelector 并实现 select() 方法
    2. 在 SELECTION_REGISTRY 中注册
"""

from __future__ import annotations

from typing import Dict, Type

from app.selection.selectors.base import BaseAssetSelector
from app.selection.selectors.momentum_reversal import MomentumReversalSelector
from app.selection.selectors.sharpe import SharpeSelector
from app.selection.selectors.cross_sectional_momentum import CrossSectionalMomentumSelector
from app.selection.selectors.trend_following import TrendFollowingSelector
from app.selection.selectors.cross_sectional_long_short import CrossSectionalLongShortSelector
from app.selection.selectors.etf_rotation import ETFRotationSelector
from app.selection.selectors.etf_discount import ETFDiscountSelector

# ---------------------------------------------------------------------------
# 注册表：selector_type -> Selector 类
# ---------------------------------------------------------------------------
SELECTION_REGISTRY: Dict[str, Type[BaseAssetSelector]] = {
    "momentum_reversal": MomentumReversalSelector,
    "sharpe": SharpeSelector,
    "cross_sectional_momentum": CrossSectionalMomentumSelector,
    "trend_following": TrendFollowingSelector,
    "cross_sectional_long_short": CrossSectionalLongShortSelector,
    "etf_rotation": ETFRotationSelector,
    "etf_discount": ETFDiscountSelector,
}


def create_selector(selector_type: str) -> BaseAssetSelector:
    """工厂方法：根据 selector_type 创建对应的 Selector 实例.

    Args:
        selector_type: 注册在 SELECTION_REGISTRY 中的类型名称

    Returns:
        BaseAssetSelector 实例

    Raises:
        ValueError: selector_type 未在注册表中注册
    """
    cls = SELECTION_REGISTRY.get(selector_type)
    if cls is None:
        available = ", ".join(sorted(SELECTION_REGISTRY.keys()))
        raise ValueError(
            f"未知的 selector_type: {selector_type!r}。"
            f"可用类型: {available}"
        )
    return cls()


__all__ = [
    "BaseAssetSelector",
    "SELECTION_REGISTRY",
    "create_selector",
]
