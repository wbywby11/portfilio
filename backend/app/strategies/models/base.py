"""Base interface for strategy models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, Any

import pandas as pd

if TYPE_CHECKING:
    from app.strategies.models.param_schema import StrategyParamSchema


def _default_portfolio_vol(
    current_weights: pd.Series,
    prices: pd.DataFrame,
) -> float | None:
    """对齐权重与价格并计算组合年化波动率（与 risk_budget_target_vol 一致）.
    无法计算时返回 None。
    """
    from app.strategies.formula.returns import compute_simple_returns
    from app.strategies.formula.rolling_volatility import compute_portfolio_volatility

    weights = current_weights.copy()
    weights.index = weights.index.astype(str)
    price_cols_str = {str(c): c for c in prices.columns}
    common = [price_cols_str[k] for k in weights.index if k in price_cols_str]
    if not common:
        return None
    prices_sub = prices[common].copy()
    weights_aligned = weights.reindex([str(c) for c in common]).dropna()
    if weights_aligned.empty:
        return None
    weights_aligned.index = [price_cols_str[k] for k in weights_aligned.index]
    returns = compute_simple_returns(prices_sub)
    vol_windows = [22, 65, 130]
    return compute_portfolio_volatility(
        returns=returns,
        weights=weights_aligned,
        windows=vol_windows,
        annualization_factor=260,
    )


class BaseStrategyModel(ABC):
    """Abstract base class for allocation strategies.

    All concrete strategies take cleaned price data and hyper-parameters
    and return a weight vector.
    """

    @abstractmethod
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """Compute allocation weights from price data.

        prices: DataFrame indexed by datetime, columns are asset identifiers.
        Returns: Series indexed by asset identifiers, values are weights.
        """
        raise NotImplementedError
    
    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> Dict[str, Any]:
        """计算监控指标（如组合波动率等）。
        
        子类可以重写此方法以返回特定的风险监控指标。
        
        Args:
            current_weights: 当前持仓权重
            prices: 资产价格历史数据
            **params: 策略参数
            
        Returns:
            Dict[str, Any]: 监控指标字典，例如 {"portfolio_volatility": 0.05}
        """
        return {}

    def check_volatility_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> tuple[bool, float | None]:
        """检查是否触发波动率阈值重置（所有策略可选的默认实现）。
        
        当 enable_vol_reset 为 True 且组合年化波动率 >= vol_reset_threshold 时触发。
        子类（如目标波动率策略）可重写以使用 target_vol 等自定义逻辑。
        
        Args:
            current_weights: 当前持仓权重
            prices: 资产价格历史数据
            **params: 策略参数，需含 enable_vol_reset、vol_reset_threshold
        
        Returns:
            (是否触发, 当前组合年化波动率；无法计算时返回 None)
        """
        if not params.get("enable_vol_reset", True):
            return False, None
        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))
        current_vol = _default_portfolio_vol(current_weights, prices)
        if current_vol is None:
            return False, None
        return (current_vol >= vol_reset_threshold, current_vol)

    def compute_volatility_reset_weights(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> pd.Series:
        """波动率阈值触发时的重置权重（所有策略可选的默认实现）。
        
        当 enable_vol_reset 为 True 且组合波动率 >= 阈值时，按比例缩放权重使组合波动率降至阈值。
        子类（如目标波动率策略）可重写以使用 target_vol 等自定义逻辑。
        
        Args:
            current_weights: 当前持仓权重
            prices: 资产价格历史数据
            **params: 策略参数
        
        Returns:
            重置后的权重（未触发或未启用时返回 current_weights）
        """
        if not params.get("enable_vol_reset", True):
            return current_weights
        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))
        current_vol = _default_portfolio_vol(current_weights, prices)
        if current_vol is None or current_vol < vol_reset_threshold:
            return current_weights
        scale_factor = vol_reset_threshold / current_vol
        return current_weights * scale_factor

    @classmethod
    def get_param_schema(cls) -> StrategyParamSchema:
        """返回策略的参数Schema定义.
        
        子类可选实现此方法，用于前端动态生成参数配置表单。
        默认返回空Schema（无参数）。
        """
        from app.strategies.models.param_schema import StrategyParamSchema
        
        return StrategyParamSchema(
            strategy_type=cls.__name__,
            display_name=cls.__name__,
            description="",
            params=[]
        )
