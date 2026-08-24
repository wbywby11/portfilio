"""滚动窗口波动率监测控制器.

从 risk_budget_target_vol / sharpe_risk_budget 策略中提取通用的波动率监测逻辑，
支持多窗口滚动波动率计算、阈值触发判断与等比例权重缩放。

参数化配置：
- vol_window_short:      短期波动率窗口（默认 22 交易日）
- vol_window_medium:     中期波动率窗口（默认 65 交易日）
- vol_window_long:       长期波动率窗口（默认 130 交易日）
- vol_windows:           [兼容旧格式] 逗号分隔字符串或列表（默认 [22, 65, 130]）
- min_data_days:         最少历史数据天数，不足则不触发（默认 130）
- annualization_factor:  年化因子（默认 260 交易日）
- trigger_operator:      触发比较符，'>' 或 '>='（默认 '>'）
- fillna_zero:           是否对缺失收益率填充 0（默认 True，与编制规则一致）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import pandas as pd

from app.control.base import BaseMonitor
from app.formula.returns import compute_simple_returns
from app.formula.rolling_volatility import compute_portfolio_volatility

_log = logging.getLogger(__name__)


class RollingVolMonitor(BaseMonitor):
    """基于多窗口滚动波动率的监测控制器.

    计算组合年化波动率（取多窗口最大值），当波动率超过阈值时触发重置信号，
    并按 target_vol / vol_trigger 等比例缩放权重。

    与 risk_budget_target_vol、sharpe_risk_budget 策略的监测逻辑完全一致，
    保证向后兼容。
    """

    # ------------------------------------------------------------------
    # 内部工具：对齐权重与价格列
    # ------------------------------------------------------------------

    @staticmethod
    def _align_weights_prices(
        current_weights: pd.Series,
        prices: pd.DataFrame,
    ) -> tuple[pd.Series, pd.DataFrame] | None:
        """对齐权重 index 与 prices columns，返回 (aligned_weights, prices_sub).

        无法对齐时返回 None。
        """
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
        return weights_aligned, prices_sub

    @staticmethod
    def _parse_vol_windows(value: Any) -> List[int]:
        """将 vol_windows 参数规范化为整数列表.

        兼容列表（[22, 65, 130]）与逗号分隔字符串（"22,65,130"，前端文本框
        传入的形态）两种输入；解析失败时回退默认 [22, 65, 130]。
        """
        default = [22, 65, 130]
        if value is None:
            return default
        if isinstance(value, str):
            try:
                parsed = [int(w.strip()) for w in value.split(",") if w.strip()]
            except ValueError:
                return default
            return parsed or default
        if isinstance(value, (list, tuple)):
            try:
                parsed = [int(w) for w in value]
            except (ValueError, TypeError):
                return default
            return parsed or default
        return default

    @staticmethod
    def _resolve_vol_windows(params: Dict[str, Any]) -> List[int]:
        """从参数中解析波动率窗口列表.

        优先读取三个独立字段 vol_window_short/medium/long（新版前端），
        回退到旧版 vol_windows 字符串/列表格式。
        """
        short = params.get("vol_window_short")
        medium = params.get("vol_window_medium")
        long_ = params.get("vol_window_long")
        if short is not None or medium is not None or long_ is not None:
            raw = [int(x) for x in [short or 22, medium or 65, long_ or 130]]
            return sorted(set(raw))
        # 回退：旧 vol_windows 字符串/列表
        return RollingVolMonitor._parse_vol_windows(params.get("vol_windows"))

    # ------------------------------------------------------------------
    # 核心：计算组合波动率
    # ------------------------------------------------------------------

    def _compute_portfolio_vol(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        vol_windows: List[int],
        annualization_factor: int,
        fillna_zero: bool,
        min_data_days: int,
    ) -> float | None:
        """对齐并计算组合多窗口滚动年化波动率.

        数据不足 min_data_days 时返回 None。
        """
        aligned = self._align_weights_prices(current_weights, prices)
        if aligned is None:
            return None
        weights_aligned, prices_sub = aligned

        if len(prices_sub) < min_data_days:
            return None

        returns = compute_simple_returns(prices_sub)
        return compute_portfolio_volatility(
            returns=returns,
            weights=weights_aligned,
            windows=vol_windows,
            annualization_factor=annualization_factor,
            fillna_zero=fillna_zero,
        )

    # ------------------------------------------------------------------
    # BaseMonitor 接口实现
    # ------------------------------------------------------------------

    def compute_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> Dict[str, Any]:
        """计算监控指标：返回 {"portfolio_volatility": vol}."""
        vol_windows = self._resolve_vol_windows(params)
        annualization_factor = int(params.get("annualization_factor", 260))
        fillna_zero = bool(params.get("fillna_zero", True))
        min_data_days = int(params.get("min_data_days", max(vol_windows) if vol_windows else 130))

        vol = self._compute_portfolio_vol(
            current_weights, prices,
            vol_windows=vol_windows,
            annualization_factor=annualization_factor,
            fillna_zero=fillna_zero,
            min_data_days=min_data_days,
        )
        if vol is None:
            return {"portfolio_volatility": None}
        return {"portfolio_volatility": vol}

    def check_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> tuple[bool, float | None]:
        """检查波动率是否超过阈值.

        参数:
            enable_vol_reset:     是否启用（默认 True）
            vol_reset_threshold:  阈值（默认 0.06）
            trigger_operator:     '>' 或 '>='（默认 '>'）
        """
        if not params.get("enable_vol_reset", True):
            return False, None

        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))
        trigger_op = params.get("trigger_operator", ">")
        vol_windows = self._resolve_vol_windows(params)
        annualization_factor = int(params.get("annualization_factor", 260))
        fillna_zero = bool(params.get("fillna_zero", True))
        min_data_days = int(params.get("min_data_days", max(vol_windows) if vol_windows else 130))

        current_vol = self._compute_portfolio_vol(
            current_weights, prices,
            vol_windows=vol_windows,
            annualization_factor=annualization_factor,
            fillna_zero=fillna_zero,
            min_data_days=min_data_days,
        )
        if current_vol is None:
            return False, None

        if trigger_op == ">=":
            triggered = current_vol >= vol_reset_threshold
        else:
            triggered = current_vol > vol_reset_threshold

        return triggered, current_vol

    def compute_reset_weights(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> pd.Series:
        """波动率触发时的重置权重：等比例缩放.

        缩放公式：w_new = w_current × (target_vol / vol_trigger)

        优先使用外部传入的 _vol_trigger（信号日已实现波动率），
        保证执行日缩放基准与信号日一致（编制规则 4.3.4）。
        未传入时在本地重算当前波动率。
        """
        if not params.get("enable_vol_reset", True):
            return current_weights

        target_vol = float(params.get("target_vol", 0.05))
        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))

        # 优先使用信号日 VolTrigger
        vol_trigger = params.get("_vol_trigger") or params.get("vol_trigger")
        if vol_trigger is not None and float(vol_trigger) > 0:
            scale_factor = min(1.0, target_vol / float(vol_trigger))
            return current_weights * scale_factor

        # 兼容：本地重算
        vol_windows = self._resolve_vol_windows(params)
        annualization_factor = int(params.get("annualization_factor", 260))
        fillna_zero = bool(params.get("fillna_zero", True))
        min_data_days = int(params.get("min_data_days", max(vol_windows) if vol_windows else 130))

        current_vol = self._compute_portfolio_vol(
            current_weights, prices,
            vol_windows=vol_windows,
            annualization_factor=annualization_factor,
            fillna_zero=fillna_zero,
            min_data_days=min_data_days,
        )
        if current_vol is None or current_vol <= vol_reset_threshold:
            return current_weights

        scale_factor = min(1.0, target_vol / current_vol)
        return current_weights * scale_factor
