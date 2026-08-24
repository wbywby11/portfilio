"""Base interface for strategy models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional

import pandas as pd

if TYPE_CHECKING:
    from app.allocation.models.param_schema import StrategyParamSchema


def _default_portfolio_vol(
    current_weights: pd.Series,
    prices: pd.DataFrame,
) -> float | None:
    """对齐权重与价格并计算组合年化波动率（与 risk_budget_target_vol 一致）.
    无法计算时返回 None。
    """
    from app.formula.returns import compute_simple_returns
    from app.formula.rolling_volatility import compute_portfolio_volatility

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

    # ------------------------------------------------------------------
    # Control Monitor 委托机制
    # ------------------------------------------------------------------

    def _resolve_control_monitor(self, params: dict):
        """根据 params 中的 vol_control_type 从 CONTROL_REGISTRY 解析 Monitor 实例.

        Returns:
            BaseMonitor 实例，或 None（未配置 / 注册表中无对应类型时）。
        """
        monitor_type = params.get("vol_control_type")
        if not monitor_type:
            return None
        try:
            from app.control import create_monitor
            return create_monitor(monitor_type)
        except (ImportError, ValueError):
            return None

    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> Dict[str, Any]:
        """计算监控指标（如组合波动率等）。

        优先委托给 control monitor（若配置了 vol_control_type），
        否则使用内置默认实现（_default_portfolio_vol）。
        子类可重写此方法以提供特定逻辑。
        """
        monitor = self._resolve_control_monitor(params)
        if monitor is not None:
            return monitor.compute_metrics(current_weights, prices, **params)
        # 内置兜底
        vol = _default_portfolio_vol(current_weights, prices)
        return {"portfolio_volatility": vol} if vol is not None else {}

    def check_volatility_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> tuple[bool, float | None]:
        """检查是否触发波动率阈值重置。

        优先委托给 control monitor，否则使用内置默认实现。
        子类可重写以使用自定义逻辑。
        """
        monitor = self._resolve_control_monitor(params)
        if monitor is not None:
            return monitor.check_trigger(current_weights, prices, **params)
        # 内置兜底：仅在显式启用时才执行波动率重置
        if not params.get("enable_vol_reset", False):
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
        """波动率阈值触发时的重置权重。

        优先委托给 control monitor，否则使用内置默认实现。
        子类可重写以使用自定义逻辑。

        缩放公式：w_new = w_current * (target_vol / vol_trigger)
        """
        monitor = self._resolve_control_monitor(params)
        if monitor is not None:
            return monitor.compute_reset_weights(current_weights, prices, **params)
        # 内置兜底：仅在显式启用时才执行波动率重置
        if not params.get("enable_vol_reset", False):
            return current_weights
        target_vol = float(params.get("target_vol", 0.05))
        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))
        # 优先使用信号日 VolTrigger
        vol_trigger = params.get("_vol_trigger") or params.get("vol_trigger")
        if vol_trigger is not None and float(vol_trigger) > 0:
            scale_factor = min(1.0, target_vol / float(vol_trigger))
            return current_weights * scale_factor
        # 本地重算
        current_vol = _default_portfolio_vol(current_weights, prices)
        if current_vol is None or current_vol <= vol_reset_threshold:
            return current_weights
        scale_factor = min(1.0, target_vol / current_vol)
        return current_weights * scale_factor

    def get_capabilities(self) -> Dict[str, Any]:
        """从本策略 schema 读取能力声明（供回测引擎读取）.

        与 CompositionPipeline.get_capabilities 保持同一口径，使策略直接作为
        引擎策略使用时也能被识别。
        """
        try:
            schema = type(self).get_param_schema()
        except Exception:
            return {}
        return {
            "snapshot_weight_source": getattr(schema, "snapshot_weight_source", "actual"),
            "signal_timing": getattr(schema, "signal_timing", "prev_close"),
        }

    def get_execution_schedule(self) -> Optional[dict]:
        """声明策略的执行调度规则（可选）.

        返回 None 时使用引擎默认值（T+0，config.rebalance_freq）。
        返回 dict 可包含以下字段：
            - rebalance_freq: str — 调仓频率
            - execution_delay: int — 信号日到执行日的交易日延迟
            - skip_dates: Set[str] — 排除日集合
            - selection_start_date: str — 资产选择起始日
        """
        return None

    def on_daily_settle(self, time, position, total_value, bar_extra=None):
        """每日结算钩子（可选）.

        回测引擎在每日快照构建后调用此方法，策略可在此执行每日调整逻辑，
        如闲置资金利息、持仓成本拖拽、GC001 回购利息等。默认不做任何操作。
        子类重写时可返回：
            - None: 不做修改（与未实现此方法的策略行为一致）
            - (new_position, new_total_value): 更新后的持仓和总市值
        
        Args:
            time: 当前交易日
            position: 当前持仓状态
            total_value: 当前组合总市值
            bar_extra: Bar.extra 字典，含额外价格维度和技术指标（可选）
        """
        return None

    @classmethod
    def get_param_schema(cls) -> StrategyParamSchema:
        """返回策略的参数Schema定义.
        
        子类可选实现此方法，用于前端动态生成参数配置表单。
        默认返回空Schema（无参数）。
        """
        from app.allocation.models.param_schema import StrategyParamSchema
        
        return StrategyParamSchema(
            strategy_type=cls.__name__,
            display_name=cls.__name__,
            description="",
            params=[]
        )
