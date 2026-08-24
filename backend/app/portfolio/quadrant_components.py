"""四象限权重模型组件组装（组合层共享构建块）.

从 weight_model_params 组装四象限权重模型 + 再平衡信号 + 执行调度，
供组合回测 API（app/api/backtests.py 的两个 run-portfolio 端点）与
组合服务（portfolio_service._run_composite 的绩效/回撤链路）复用，
保证"回测与监控/绩效同一组装口径"，避免多处组装导致参数断点。

只负责组装，不含象限计算逻辑（在 QuadrantWeightModel 内）。

支持三种调仓模式（rebalance_mode）：
- signal_driven: 事件驱动，象限切换即触发，T+2 生效
- monthly_quadrant: 月度定期，逆波动率 + 象限 Boost
- monthly_inv_vol: 月度定期，仅逆波动率（无需信号标的）
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd

from app.backtesting.schedule import ExecutionSchedule
from app.portfolio.weight_models import QuadrantWeightModel
from app.services.market_service import MarketService

# 四象限权重模型可配置参数集合：由域内 schema 派生，避免白名单与构造签名漂移。
# 注：signal_code 不在 schema 中（非构造参数），在组装过滤前已单独 pop，不受此集合影响。
QUADRANT_PARAM_KEYS = frozenset(
    p["name"] for p in QuadrantWeightModel.get_param_schema()["params"]
)


async def build_quadrant_weight_components(
    weight_model_params: Dict[str, Any],
    start_date: str,
    end_date: str,
) -> Tuple[QuadrantWeightModel, Optional[pd.Series], ExecutionSchedule, bool]:
    """组装四象限权重模型 + 再平衡信号 + 执行调度.

    Returns:
        (weight_model, rebalance_signal, execution_schedule, weight_drift) 四元组；
        weight_drift=False 表示周期内权重恒定（月度模式，对齐原型）。
    """
    wm_params = dict(weight_model_params or {})
    rebalance_mode = wm_params.pop("rebalance_mode", "signal_driven")
    # 兜底信号标的与原型 signal_engine 一致（沪深300）；前端显式配置时以配置为准
    signal_code = wm_params.pop("signal_code", "000300.SH")

    # 仅传入 QuadrantWeightModel 认识的构造参数，避免多余字段导致报错
    filtered_params = {k: v for k, v in wm_params.items() if k in QUADRANT_PARAM_KEYS}

    if rebalance_mode == "monthly_inv_vol":
        # 月度逆波动率模式：无需信号标的，无需象限信号，月度定期再平衡
        weight_model = QuadrantWeightModel(
            signal_prices=None,
            rebalance_mode="monthly_inv_vol",
            **{k: v for k, v in filtered_params.items() if k != "quadrant_strategy_map"},
        )
        rebalance_signal = None  # 无事件信号，走周期驱动
        execution_schedule = ExecutionSchedule(rebalance_freq="monthly", execution_delay=1)
        # 月度模式：周期内权重恒定（对齐原型 monthly 模式，无月内漂移）
        return weight_model, rebalance_signal, execution_schedule, False

    # signal_driven / monthly_quadrant 模式：需要加载信号标的价格
    _sma = int(wm_params.get("sma_window", 60))
    _hv = int(wm_params.get("hv_window", 20))
    _vpct = int(wm_params.get("vol_percentile_window", 252))
    lookback_trading = _sma + _hv + _vpct + 60  # 额外 60 交易日缓冲
    lookback_calendar = int(lookback_trading * 1.6)  # 交易日 → 日历日
    sig_start = pd.to_datetime(start_date) - pd.Timedelta(days=lookback_calendar)
    sig_end = pd.to_datetime(end_date)

    market_service = MarketService()
    signal_prices = await market_service.get_price_series(
        signal_code, sig_start.to_pydatetime(), sig_end.to_pydatetime()
    )
    if signal_prices is None or signal_prices.empty:
        raise ValueError(f"信号标的 {signal_code} 无行情数据，无法启用四象限调权")

    weight_model = QuadrantWeightModel(
        signal_prices=signal_prices,
        rebalance_mode=rebalance_mode,
        **filtered_params,
    )

    if rebalance_mode == "signal_driven":
        # 事件驱动：象限变化即触发，T+2 生效；非周期模式保持权重漂移
        rebalance_signal = weight_model.get_quadrant_series()
        execution_schedule = ExecutionSchedule(rebalance_freq="daily", execution_delay=2)
        return weight_model, rebalance_signal, execution_schedule, True
    else:
        # monthly_quadrant：月度定期再平衡，权重模型内部仍做象限 Boost；
        # 周期内权重恒定（对齐原型 monthly_quadrant 模式，无月内漂移）
        rebalance_signal = None
        execution_schedule = ExecutionSchedule(rebalance_freq="monthly", execution_delay=1)
        return weight_model, rebalance_signal, execution_schedule, False
