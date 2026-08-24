from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd

from app.backtesting.signal import TargetWeightSignal

logger = logging.getLogger(__name__)


def _log_rebalance_weights(
    as_of: pd.Timestamp,
    final_weights: Dict[str, float],
    thscodes: list,
) -> None:
    """记录每次调仓计算出的权重（仅 DEBUG 级别，避免污染生产日志与标准输出）。"""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    date_str = as_of.strftime("%Y-%m-%d") if hasattr(as_of, "strftime") else str(as_of)
    total = sum(final_weights.get(c, 0.0) for c in thscodes)
    held = " ".join(
        f"{code}={final_weights.get(code, 0.0):.4f}"
        for code in thscodes
        if final_weights.get(code, 0.0) != 0
    )
    logger.debug("调仓 %s 权重和=%.6f 持仓=%s", date_str, total, held or "（空仓）")


class IStrategy(ABC):
    """回测框架内部使用的策略接口.

    负责基于历史价格数据生成目标权重信号。
    """

    @abstractmethod
    def generate_target_weights(
            self,
            history_prices: pd.DataFrame,
            as_of: pd.Timestamp,
    ) -> TargetWeightSignal:
        """基于历史价格生成 as_of 时点的目标权重信号."""
        raise NotImplementedError

    def compute_monitoring_metrics(
            self,
            current_weights: pd.Series,
            history_prices: pd.DataFrame,
    ) -> Dict[str, Any]:
        """计算监控指标（如组合波动率等）。"""
        return {}

    def get_capabilities(self) -> Dict[str, Any]:
        """声明策略能力，供回测引擎调整执行/展示行为。

        引擎只读此声明，不得按策略类名硬编码分支。已支持的键：
            - snapshot_weight_source: "actual" | "target"
              快照持仓权重口径，默认 "actual"。

        未声明的键由引擎取默认值。
        """
        return {}
