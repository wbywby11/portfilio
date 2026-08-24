"""ExecutionEngine：目标权重 → 成交执行（计算内核层，模式无关）.

将目标权重信号按当前持仓与价格转换为成交（Order/Trade），
支持可选手续费率/滑点；指数口径场景（监控、GMSI2 对齐）可配零成本。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from app.backtesting.config import BacktestConfig
from app.backtesting.types import Position, Trade, Bar
from app.backtesting.signal import TargetWeightSignal


@dataclass
class ExecutionResult:
    """一次调仓执行后的结果: 新持仓 + 交易列表."""

    position: Position
    trades: List[Trade]


class ExecutionEngine:
    """订单执行与成本计算模块.

    采用市价单 + 线性手续费/滑点模型。
    通过 Bar.get_price() 按优先级取价（vwap → close），
    当 DataFeed 加载了 VWAP 宽表时自动使用更真实的成交价，
    缺失时无感回退到收盘价，所有策略自动受益。
    维护平均买入成本用于计算每笔交易的已实现盈亏 (pnl)。
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config
        self._avg_cost: Dict[str, float] = {}  # {asset_code: 加权平均买入价}

    def rebalance_to_target(
        self,
        bar: Bar,
        current_position: Position,
        target_signal: TargetWeightSignal,
    ) -> ExecutionResult:
        """按照目标权重进行一次调仓."""

        # 防御性检查：确保 bar.close 是字典
        if not isinstance(bar.close, dict):
            raise TypeError(
                f"bar.close 必须是字典类型，实际类型为 {type(bar.close)}。"
                f"可能是数据格式问题，请检查数据源。"
            )

        # 通过 Bar.get_price() 取价：vwap 优先，close 回退
        def _price(code: str) -> float:
            return bar.get_price(code)

        # 当前组合总市值
        total_value = current_position.cash + sum(
            qty * _price(code)
            for code, qty in current_position.quantity.items()
        )

        target_weights = target_signal.target_weights
        target_value = {code: total_value * w for code, w in target_weights.items()}

        # 目标持仓数量
        target_qty = {
            code: (target_value.get(code, 0.0) / (_price(code) or 1e-8))
            for code in target_weights.keys()
        }

        trades: List[Trade] = []
        new_quantity = current_position.quantity.copy()
        cash = current_position.cash

        for code in target_weights.keys():
            current_qty = new_quantity.get(code, 0.0)
            desired_qty = target_qty.get(code, 0.0)
            delta = desired_qty - current_qty

            if abs(delta) < 1e-6:
                continue

            side = "buy" if delta > 0 else "sell"
            trade_qty = abs(delta)
            price = _price(code)

            gross = trade_qty * price
            commission = gross * self._config.commission_rate
            slippage_cost = gross * self._config.slippage
            total_cost = commission + slippage_cost

            # 计算 pnl 并更新平均成本
            avg_cost = self._avg_cost.get(code, 0.0)
            if side == "buy":
                cash -= gross + total_cost
                # 更新加权平均买入价
                old_cost_total = avg_cost * current_qty
                new_cost_total = old_cost_total + price * trade_qty
                new_qty_total = current_qty + trade_qty
                self._avg_cost[code] = new_cost_total / new_qty_total if new_qty_total > 0 else price
                new_quantity[code] = current_qty + trade_qty
                # 买入时 pnl 仅记录交易成本（负值）
                trade_pnl = -total_cost
            else:
                cash += gross - total_cost
                # 卖出时 pnl = (卖出价 - 平均成本) * 数量 - 交易费用
                trade_pnl = (price - avg_cost) * trade_qty - total_cost
                new_quantity[code] = current_qty - trade_qty
                # 清仓时重置平均成本
                if new_quantity.get(code, 0.0) < 1e-6:
                    self._avg_cost.pop(code, None)

            trades.append(
                Trade(
                    time=bar.time,
                    thscode=code,
                    side=side,
                    quantity=trade_qty,
                    price=price,
                    commission=commission,
                    slippage_cost=slippage_cost,
                    pnl=trade_pnl,
                )
            )

        position = Position(quantity=new_quantity, cash=cash)
        return ExecutionResult(position=position, trades=trades)
