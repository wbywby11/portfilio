# -*- coding: utf-8 -*-
"""进程内重建模拟雪球的回测记录（复刻 run-by-model 保存链路）。

背景：旧记录的净值曲线被 aggregate_snapshots 截断（日频调仓策略只保留
前段+末日），修复后需重新生成一条正确的记录。

用法：python scripts/regen_snowball_record.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL_ID = "6a71961edf5c07bf2cd2dd07"
START = "20191231"
END = "20260731"
INITIAL_CASH = 1_000_000.0


async def main() -> None:
    from bson import ObjectId
    import pandas as pd

    from app.config.database import Database
    from app.services.strategy_model_service import StrategyModelService, build_backtest_params
    from app.services.backtest_service import BacktestService
    from app.services.market_service import MarketService
    from app.services.asset_service import AssetService
    from app.api.backtests import _run_backtest_core, BacktestRequest
    from app.models.strategy_model import (
        BacktestRecord, BacktestResult as ModelBacktestResult,
        EquityPoint, ReturnPoint, PositionRecord, AssetPosition, WeightChangePoint,
    )

    Database.connect()

    model_service = StrategyModelService()
    backtest_service = BacktestService(model_service)
    model = await model_service.get_model(MODEL_ID)
    if model is None:
        raise SystemExit("模型不存在")

    request_data = backtest_service.to_backtest_request(
        model=model, start_date=START, end_date=END,
        initial_cash=INITIAL_CASH, lookback_days=500,
    )
    model_data = await model_service.collection.find_one({"_id": ObjectId(MODEL_ID)})
    request_data["strategy_params"] = build_backtest_params(model=model, overrides={}, model_data=model_data)

    request = BacktestRequest(**request_data)
    market_service = MarketService()
    asset_service = AssetService()

    print("开始回测 ...")
    result = await _run_backtest_core(request, market_service, asset_service)
    assert result.code == 200 and result.data, f"回测失败: {result.message}"

    backtest_data = result.data
    snapshots = backtest_data.get("snapshots", []) if isinstance(backtest_data, dict) else getattr(backtest_data, "snapshots", [])

    def _get(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    assert snapshots, "无快照"
    initial_val = _get(snapshots[0], "total_value") or INITIAL_CASH
    asset_names_map = _get(backtest_data, "asset_names") or {}

    print(f"快照数: {len(snapshots)}  (meta={_get(backtest_data, '_snapshot_meta')})")

    equity_curve = [
        EquityPoint(
            date=_get(s, "time"),
            value=_get(s, "total_value"),
            unit_value=(_get(s, "total_value") or 0) / initial_val if initial_val != 0 else 1.0,
            cumulative_return=((_get(s, "total_value") or 0) / initial_val - 1) if initial_val != 0 else 0.0,
            portfolio_volatility=_get(s, "portfolio_volatility"),
            drawdown=_get(s, "drawdown"),
            rebalance_type=_get(s, "rebalance_type"),
        )
        for s in snapshots
    ]
    return_curve = [
        ReturnPoint(
            date=_get(s, "time"),
            daily_return=0.0,
            cumulative_return=((_get(s, "total_value") or 0) / initial_val - 1) if initial_val != 0 else 0.0,
        )
        for s in snapshots
    ]
    positions_record = [
        PositionRecord(
            date=_get(s, "time"),
            portfolio_value=_get(s, "total_value"),
            cash=_get(s, "cash"),
            rebalance_reason=_get(s, "rebalance_reason"),
            positions=[
                AssetPosition(
                    asset_code=code,
                    asset_name=asset_names_map.get(code) if asset_names_map else None,
                    weight=weight,
                    market_value=(_get(s, "total_value") or 0) * weight,
                )
                for code, weight in (_get(s, "weights") or {}).items()
            ],
        )
        for s in snapshots if _get(s, "is_rebalance_day")
    ]
    weight_changes = [
        WeightChangePoint(
            date=(_get(s, "time").strftime('%Y-%m-%d') if hasattr(_get(s, "time"), "strftime") else str(_get(s, "time"))[:10]),
            weights=_get(s, "weights") or {},
        )
        for s in snapshots if _get(s, "is_rebalance_day")
    ]

    model_result = ModelBacktestResult(
        total_return=_get(backtest_data, "total_return", 0.0) or 0.0,
        annual_return=_get(backtest_data, "annual_return", 0.0) or 0.0,
        annual_volatility=_get(backtest_data, "volatility", 0.0) or 0.0,
        sharpe_ratio=_get(backtest_data, "sharpe_ratio", 0.0) or 0.0,
        max_drawdown=_get(backtest_data, "max_drawdown", 0.0) or 0.0,
        calmar_ratio=_get(backtest_data, "calmar_ratio"),
        win_rate=_get(backtest_data, "win_rate"),
        equity_curve=equity_curve,
        return_curve=return_curve,
        positions=positions_record,
        weight_changes=weight_changes,
        asset_names=asset_names_map,
        selected_asset_count=_get(backtest_data, "selected_asset_count"),
    )

    record = BacktestRecord(
        model_id=MODEL_ID,
        start_date=pd.to_datetime(START),
        end_date=pd.to_datetime(END),
        initial_capital=INITIAL_CASH,
        result=model_result,
        remark="重建记录：修复日频调仓快照聚合截断导致的净值曲线假跳涨",
    )
    record_id = await backtest_service.save_backtest_record(record)
    print("新记录已保存:", record_id)

    # 校验曲线连续性
    s = pd.Series([p.unit_value for p in equity_curve],
                  index=pd.to_datetime([p.date for p in equity_curve]))
    print(f"曲线: {len(s)} 点, {s.index[0].date()} ~ {s.index[-1].date()}, 末值 {s.iloc[-1]:.4f}")
    ret = s.pct_change().abs()
    print(f"最大单日变化: {ret.max()*100:.3f}%")


if __name__ == "__main__":
    asyncio.run(main())
