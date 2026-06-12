from __future__ import annotations

from dataclasses import dataclass
from typing import List

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

    第一版采用市价单 + 线性手续费/滑点模型。
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config

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
        prices = bar.close
        # 当前组合总市值
        total_value = current_position.cash + sum(
            qty * prices.get(code, 0.0)
            for code, qty in current_position.quantity.items()
        )

        target_weights = target_signal.target_weights
        target_value = {code: total_value * w for code, w in target_weights.items()}

        # 目标持仓数量
        target_qty = {
            code: (target_value.get(code, 0.0) / prices.get(code, 1e-8))
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
            price = prices.get(code, 0.0)

            gross = trade_qty * price
            commission = gross * self._config.commission_rate
            slippage_cost = gross * self._config.slippage
            total_cost = commission + slippage_cost

            if side == "buy":
                cash -= gross + total_cost
                new_quantity[code] = current_qty + trade_qty
            else:
                cash += gross - total_cost
                new_quantity[code] = current_qty - trade_qty

            trades.append(
                Trade(
                    time=bar.time,
                    thscode=code,
                    side=side,
                    quantity=trade_qty,
                    price=price,
                    commission=commission,
                    slippage_cost=slippage_cost,
                )
            )

        position = Position(quantity=new_quantity, cash=cash)
        return ExecutionResult(position=position, trades=trades)
