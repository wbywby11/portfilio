"""计算引擎基础数据类型（计算内核层，模式无关）.

Bar / Position / Order / Trade / PortfolioSnapshot：全部计算模式共享。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional

import pandas as pd


@dataclass
class Bar:
    """单个时间点的行情数据.

    close 为 {thscode: close_price}，是回测引擎的主要价格来源。
    extra 承载额外的价格维度（如 vwap、open、high、low）和技术指标，
    结构为 {"vwap": {code: price}, "open": {code: price}, ...}。
    DataFeed.iter_bars() 在构造 Bar 时自动填充 extra；
    ExecutionEngine 通过 get_price() 按优先级取价，所有策略自动受益。
    """

    time: pd.Timestamp
    close: Dict[str, float]
    extra: Optional[Dict[str, Dict[str, float]]] = None

    def get_price(self, code: str, priority: list[str] | None = None) -> float:
        """按优先级获取某标的的执行价格.

        默认优先级 ["vwap", "close"]：优先 VWAP（更真实的成交参考），
        缺失时回退到收盘价。所有调用方（ExecutionEngine、BacktestEngine）
        统一使用此方法取价，保证价格源选择逻辑集中且一致。
        """
        if priority is None:
            priority = ["vwap", "close"]
        for source in priority:
            if source == "close":
                val = self.close.get(code)
                if val is not None and val > 0:
                    return float(val)
            elif self.extra and source in self.extra:
                val = self.extra[source].get(code)
                if val is not None and val > 0:
                    return float(val)
        # 兜底：收盘价（即使为0或None也返回）
        return float(self.close.get(code, 0.0))


@dataclass
class Position:
    """组合持仓状态（仅支持多头，第一版不考虑卖空/融资融券）."""

    quantity: Dict[str, float]  # {thscode: shares}
    cash: float


@dataclass
class Order:
    """订单结构（第一版主要由执行引擎内部使用，可后续扩展）。"""

    time: pd.Timestamp
    thscode: str
    side: str          # "buy" / "sell"
    quantity: float
    price: float | None = None  # 限价单可填，不填表示市价


@dataclass
class Trade:
    """成交记录."""

    time: pd.Timestamp
    thscode: str
    side: str
    quantity: float
    price: float
    commission: float
    slippage_cost: float
    pnl: float = 0.0  # 预估盈亏：卖出时为已实现盈亏(含费用)，买入时为负交易成本


@dataclass
class PortfolioSnapshot:
    """某一时间点的组合快照，用于后续绩效分析."""

    time: pd.Timestamp
    total_value: float
    cash: float
    holdings_value: float
    weights: Dict[str, float]
    is_rebalance_day: bool = False  # 标记是否为调仓日
    rebalance_type: str | None = None  # 调仓类型："regular" / "vol_reset" 等
    portfolio_volatility: float | None = None  # 当日组合波动率（用于监控）
    monitoring_metrics: Dict[str, Any] = field(default_factory=dict)  # 扩展监控指标库
    rebalance_reason: str | None = None  # 调仓原因（周期性调仓 / 条件触发等）
    signal_date: Optional[pd.Timestamp] = None  # 若为延迟执行日，记录原始信号日
    execution_delay_days: int = 0  # 延迟的交易日数（0=当日执行）
