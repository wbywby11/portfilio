"""子策略独立执行器：组合与子策略之间的唯一交互面。

契约
----
调用方只给「策略码 / 参数 / 资产池 / 区间 / 起始净值」，执行器负责其余全部执行
细节：composition 推导、调仓频率校正、DataFeed 构建（含 ``get_extra_panels``
声明的截面面板）、引擎运行、绩效计算与净值序列归一化。调用方（组合回测、
组合监控、组合绩效、策略表现监控）只消费返回的 ``IsolatedStrategyResult``，
不自行构造 DataFeed、不解析 strategy_type、不感知面板存在与否。

面板与 composition 都按 ``strategy_type`` 静态解析，缺策略码在入口即报错，
不在下游静默退化成「空面板」或「全资产池默认 composition」。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from app.allocation.runtime_params import resolve_weight_caps

logger = logging.getLogger(__name__)

# 回测指标的统一无风险利率（与单策略回测通道同口径）
_RISK_FREE_RATE = 0.02

# 模型里可能存中文频率，进 BacktestConfig 前统一映射
_FREQ_MAP = {
    "日": "daily", "周": "weekly", "月": "monthly",
    "季": "quarterly", "年": "yearly",
}


@dataclass
class IsolatedStrategyResult:
    """一次独立策略回测的产出（组合层唯一可见的契约）.

    ``nav_series`` 已按 ``initial_nav`` 归一化，可直接进组合层合成；
    snapshots / trades 供穿透权重与交易明细展示，不参与组合层决策。
    """

    strategy_type: str
    name: str
    snapshots: List[Any] = field(default_factory=list)
    trades: List[Any] = field(default_factory=list)
    nav_series: Optional[pd.Series] = None
    performance: Any = None

    @property
    def has_nav(self) -> bool:
        return self.nav_series is not None and len(self.nav_series) > 0


def build_risk_config(strategy_params: Dict[str, Any]):
    """从策略参数推导风控配置（单策略与子策略共用的唯一实现）.

    ``max_total_leverage`` 为 None 时不强制归一化，允许权重和小于/大于 1；
    ``allow_short`` 时保留负权重（KI 后做空对冲类策略）。
    资产权重约束取值口径见
    :func:`app.allocation.runtime_params.resolve_weight_caps`。
    """
    from app.backtesting.risk import RiskConfig

    strategy_params = strategy_params or {}
    max_total_leverage = (
        strategy_params.get("max_total_leverage")
        or strategy_params.get("max_leverage")
    )
    if max_total_leverage is not None:
        try:
            max_total_leverage = float(max_total_leverage)
        except (TypeError, ValueError):
            max_total_leverage = None
    max_weight_dict = resolve_weight_caps(strategy_params) or None
    allow_negative = bool(strategy_params.get("allow_short", False))
    try:
        return RiskConfig(
            max_total_leverage=max_total_leverage,
            max_weight_dict=max_weight_dict,
            allow_negative_weights=allow_negative,
        )
    except TypeError:
        # 兼容移植环境：旧版 RiskConfig 无 max_total_leverage/allow_negative_weights
        return RiskConfig()


def _normalize_freq(value: Optional[str]) -> str:
    """把模型/请求里的频率归一为 BacktestConfig 接受的取值."""
    text = str(value or "").strip()
    if not text:
        return "monthly"
    return _FREQ_MAP.get(text, text)


def _nav_from_snapshots(snapshots: Sequence[Any], initial_nav: float) -> Optional[pd.Series]:
    """从引擎快照提取 NAV 序列并归一化到 ``initial_nav``."""
    if not snapshots:
        return None
    series = pd.Series({s.time: s.total_value for s in snapshots}).sort_index()
    if len(series) == 0 or float(series.iloc[0]) == 0.0:
        return None
    return series / float(series.iloc[0]) * float(initial_nav)


async def execute_isolated_strategy(
    strategy_type: str,
    strategy_params: dict,
    start_date: str,
    end_date: str,
    initial_nav: float = 1000.0,
    *,
    thscodes: Sequence[str],
    name: str = "",
    rebalance_freq: Optional[str] = None,
    commission_rate: Optional[float] = None,
    slippage: Optional[float] = None,
    initial_cash: float = 10_000_000.0,
    lookback_days: int = 500,
    inception_weights: Optional[Dict[str, float]] = None,
    inception_weights_auto_normalize: bool = False,
    progress_cb=None,
) -> IsolatedStrategyResult:
    """执行一次独立的策略回测并返回净值序列.

    Args:
        strategy_type: 策略码（= 模型 template_code），面板与 composition 按它解析
        strategy_params: 扁平化策略参数（含 selector/controller 参数）
        start_date / end_date: 回测区间，YYYYMMDD
        initial_nav: 净值归一化基准（组合层传组合起始净值）
        thscodes: 资产池（价格矩阵列）
        rebalance_freq: 模型/请求频率；策略声明 ``force_month_end`` 时以声明为准
        commission_rate / slippage: None 时用 BacktestConfig 默认（0，gross 口径）
        inception_weights: 仅调用方显式要求时传入（组合管理通道的期初建仓口径）
        progress_cb: 引擎逐日进度回调 ``(done, total, bar_time) -> None``

    Raises:
        ValueError: 策略码/资产池为空、策略未注册、区间无行情、无有效交易日
    """
    from app.backtesting.config import BacktestConfig
    from app.backtesting.data_feed import DataFeed, resolve_lookback_days
    from app.backtesting.composition_builder import build_strategy_composition
    from app.backtesting.runner import RunSpec, run_unified
    from app.backtesting.analytics import PerformanceAnalyzer
    from app.allocation.services.registry import create_strategy_service_from_database
    from app.services.market_service import MarketService

    code = str(strategy_type or "").strip()
    if not code:
        raise ValueError(
            "execute_isolated_strategy 缺少 strategy_type：面板声明与 composition "
            "都按策略码静态解析，不能为空"
        )
    pool = [str(c) for c in (thscodes or [])]
    if not pool:
        raise ValueError(f"[{code}] 资产池为空，无法执行回测")
    params = dict(strategy_params or {})

    spec = build_strategy_composition(code, pool, params)
    freq = "month_end" if spec.force_month_end else _normalize_freq(rebalance_freq)

    config_kwargs: Dict[str, Any] = {
        "name": name or f"{code}_isolated",
        "thscodes": pool,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "rebalance_freq": freq,
        "initial_cash": float(initial_cash),
        "initial_nav": float(initial_nav),
    }
    if commission_rate is not None:
        config_kwargs["commission_rate"] = float(commission_rate)
    if slippage is not None:
        config_kwargs["slippage"] = float(slippage)
    config = BacktestConfig(**config_kwargs)
    if inception_weights:
        config.initial_weights = {str(k): float(v) for k, v in inception_weights.items()}
        config.initial_weights_auto_normalize = bool(inception_weights_auto_normalize)

    effective_lookback = resolve_lookback_days(
        params, int(lookback_days), strategy_type=code
    )
    data_feed = await DataFeed.from_market_service(
        MarketService(), config,
        lookback_days=effective_lookback,
        strategy_type=code,
    )
    if data_feed.prices.empty:
        raise ValueError(
            f"[{code}] 区间 {start_date}~{end_date} 无行情数据（资产池 {len(pool)} 只），"
            f"请检查资产代码与行情导入"
        )

    strategy_service = await create_strategy_service_from_database(MarketService())
    try:
        strategy_cls = strategy_service.get_strategy_class(code)
    except KeyError as exc:
        raise ValueError(f"策略类型不存在: {code}") from exc
    allocator = strategy_cls()

    run_spec = RunSpec(
        config=config,
        data_feed=data_feed,
        allocator=allocator,
        thscodes=pool,
        composition=spec.composition,
        strategy_params=params,
        risk_config=build_risk_config(params),
        progress_cb=progress_cb,
    )
    # 引擎是同步 CPU 密集计算，放工作线程避免阻塞事件循环（组合路径多子策略串行）
    result = await asyncio.to_thread(run_unified, run_spec)
    if not result.snapshots:
        raise ValueError(f"[{code}] 区间 {start_date}~{end_date} 内无有效交易日")

    max_leverage = params.get("max_total_leverage") or params.get("max_leverage")
    max_leverage = float(max_leverage) if max_leverage is not None else None
    performance = await asyncio.to_thread(
        PerformanceAnalyzer(risk_free_rate=_RISK_FREE_RATE).from_results,
        result.snapshots,
        result.trades,
        max_leverage=max_leverage,
    )

    return IsolatedStrategyResult(
        strategy_type=code,
        name=name or config.name,
        snapshots=list(result.snapshots),
        trades=list(result.trades),
        nav_series=_nav_from_snapshots(result.snapshots, initial_nav),
        performance=performance,
    )


async def execute_model_isolated(
    model,
    *,
    start_date: str,
    end_date: str,
    initial_nav: float = 1000.0,
    model_service=None,
    model_data: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
    cost_overrides: Optional[Dict[str, float]] = None,
    apply_inception_weights: bool = False,
    progress_cb=None,
) -> IsolatedStrategyResult:
    """把一条策略模型翻译成一次独立回测并执行.

    「模型 → 请求参数」的组装（build_backtest_params / 选择器参数 / 成本覆盖）
    属于子策略执行域，收在本函数内；组合层只给模型、区间与起始净值。

    Args:
        model: StrategyModel 实例
        model_service: 模型服务（缺省新建），用于拉取原始 MongoDB 文档
        model_data: 已拉取的原始文档，避免重复查询
        apply_inception_weights: 是否应用参数里的期初建仓权重（组合管理通道为 True，
            组合回测/监控为 False，与各自原有口径一致）
    """
    from bson import ObjectId

    from app.services.backtest_service import BacktestService
    from app.services.strategy_model_service import StrategyModelService

    service = model_service or StrategyModelService()
    if model_data is None and getattr(model, "id", None):
        model_data = await service.collection.find_one({"_id": ObjectId(str(model.id))})

    request_data = BacktestService(service).to_backtest_request(
        model=model,
        start_date=start_date,
        end_date=end_date,
        initial_nav=initial_nav,
        model_data=model_data,
        **(cost_overrides or {}),
    )
    params = request_data.get("strategy_params") or {}
    inception_weights = params.get("inception_weights") if apply_inception_weights else None
    if not isinstance(inception_weights, dict):
        inception_weights = None

    return await execute_isolated_strategy(
        request_data["strategy_type"],
        params,
        start_date,
        end_date,
        initial_nav,
        thscodes=request_data.get("thscodes") or [],
        name=name or request_data.get("name", ""),
        rebalance_freq=request_data.get("rebalance_freq"),
        commission_rate=request_data.get("commission_rate"),
        slippage=request_data.get("slippage"),
        initial_cash=float(request_data.get("initial_cash") or 10_000_000.0),
        lookback_days=int(request_data.get("lookback_days") or 500),
        inception_weights=inception_weights,
        inception_weights_auto_normalize=bool(
            params.get("inception_weights_auto_normalize", False)
        ),
        progress_cb=progress_cb,
    )
