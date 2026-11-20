"""runner：计算引擎的唯一运行入口（模式编排层）.

所有"按策略模型逐日推进计算"的场景（全量回测、监控推演、组合子策略回测、
信号追踪回放、敏感性分析）一律经 :func:`run_unified` 运行，引擎组件
（CompositionPipeline / RiskManager / ExecutionEngine / BacktestEngine）
的构造只在本模块发生，避免多处构造导致口径分叉。

两步计算的第二步（Step2 回测/监控）由此入口承载；第一步（Step1 生成
配置结果）见 :func:`generate_targets`。模式差异（费率、起止日、风控口径）
通过 RunSpec / BacktestConfig 表达，不在策略逻辑内分叉。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.engine import BacktestEngine, BacktestResult
from app.backtesting.execution import ExecutionEngine
from app.backtesting.risk import RiskManager, RiskConfig
from app.backtesting.strategy_api import IStrategy


@dataclass
class RunSpec:
    """一次引擎运行的统一描述.

    strategy 与 (allocator + composition) 二选一：
    - strategy：直接传入已构建的 IStrategy（少数特殊场景，如信号追踪回放）；
    - allocator + composition + strategy_params：由 runner 构建
      CompositionPipeline（常规路径，单策略/组合子策略均走此路）。
    """

    config: BacktestConfig
    data_feed: DataFeed

    # 常规路径：runner 内部构建 CompositionPipeline
    allocator: Optional[Any] = None
    composition: Optional[Dict[str, Any]] = None
    strategy_params: Dict[str, Any] = field(default_factory=dict)
    thscodes: Optional[List[str]] = None  # None → 使用 config.thscodes

    # 特殊路径：直传已构建策略
    strategy: Optional[IStrategy] = None

    # 风控口径：None → 默认 RiskConfig()（不约束杠杆/单资产上限）
    risk_config: Optional[RiskConfig] = None

    # 逐日进度回调（可选）：``(done, total, bar_time) -> None``。
    # 引擎在工作线程同步调用，按 1% 节流在引擎侧完成；回调异常不阻断回测。
    # 组合监控用它把「回测到哪一天」实时写进任务进度。
    progress_cb: Optional[Any] = None


def _resolve_contract(allocator: Any):
    """取 allocator 类声明的数据契约（未声明或无此能力时返回 None）.

    契约为空（``DataContract()`` 全缺省）时门禁快速返回，存量策略零影响。
    """
    if allocator is None:
        return None
    getter = getattr(type(allocator), "get_data_contract", None)
    if not callable(getter):
        return None
    # 声明本身报错属于策略包配置错误，直接向上抛，不静默放行
    return getter()


def _strategy_label(allocator: Any, composition: Optional[Dict[str, Any]]) -> str:
    """异常文本里的策略标识：优先 composition 的 allocator code，回退类名."""
    code = (composition or {}).get("allocator")
    if code:
        return str(code)
    if allocator is not None:
        return type(allocator).__name__
    return "unknown"


def _gate_static(
    allocator: Any,
    thscodes: List[str],
    composition: Optional[Dict[str, Any]],
    strategy_params: Dict[str, Any],
) -> None:
    """运行前门禁（静态面）：资产数量/分组划分/日历口径声明.

    引擎层不查库，``asset_meta`` 留空（``expected_asset_class`` 的库侧校验
    由 services/strategy_data_contract_service.py 在实盘发布时补做）。
    不满足即抛 DataContractError，不降级、不跳过资产、不放宽断言。
    """
    from app.backtesting.data_contract import validate_static

    contract = _resolve_contract(allocator)
    if contract is None or contract.is_empty:
        return
    report = validate_static(contract, list(thscodes or []), strategy_params)
    report.raise_if_failed(_strategy_label(allocator, composition))


def _gate_prices(spec: "RunSpec", strategy: IStrategy) -> None:
    """运行前门禁（数据面）：历史长度/日历一致性/价格异常 + 策略自定义检查.

    价格矩阵取 ``DataFeed.strategy_prices``（仅置 inf→NaN，保留缺日）；
    不能用 ``DataFeed.prices``，后者经 sanitize_prices 已 ffill 缺日、
    并把单日涨跌超阈值的点用前一日价格填充，在其上校验日历一致性与
    单日跳变会恒通过。未提供保真矩阵时回退 prices。
    """
    from app.backtesting.data_contract import (
        merge_reports,
        validate_custom,
        validate_with_prices,
    )

    allocator = spec.allocator
    if allocator is None:
        # 特殊路径（直传已构建策略）：CompositionPipeline 持有 allocator
        allocator = getattr(strategy, "_allocator", None)
    contract = _resolve_contract(allocator)
    if contract is None or contract.is_empty:
        return

    codes = list(spec.thscodes or spec.config.thscodes or [])
    params = spec.strategy_params or {}
    prices = getattr(spec.data_feed, "strategy_prices", None)
    if prices is None:
        prices = spec.data_feed.prices

    report = merge_reports(
        validate_with_prices(contract, codes, params, prices),
        validate_custom(contract, allocator, prices, params),
    )
    report.raise_if_failed(_strategy_label(allocator, spec.composition))


def build_strategy(spec: RunSpec) -> IStrategy:
    """按 spec 构建策略对象（CompositionPipeline 唯一构造点）."""
    if spec.strategy is not None:
        return spec.strategy
    if spec.allocator is None or spec.composition is None:
        raise ValueError(
            "RunSpec 必须提供 strategy，或同时提供 allocator 与 composition"
        )
    return build_pipeline(
        allocator=spec.allocator,
        thscodes=spec.thscodes or spec.config.thscodes,
        composition=spec.composition,
        strategy_params=spec.strategy_params or {},
    )


def build_pipeline(
    allocator: Any,
    thscodes: List[str],
    composition: Optional[Dict[str, Any]],
    strategy_params: Optional[Dict[str, Any]] = None,
) -> IStrategy:
    """构建 CompositionPipeline 的公开入口（唯一构造点，本模块内实现）.

    供不运行逐日引擎的 Step1 权重生成构建块（监控适配器、研究员策略、
    模拟交易）复用；引擎层外禁止直接构造 CompositionPipeline，
    由 tests/test_backtesting_boundary.py 静态守卫。

    本函数是四条通道（回测 / 监控适配器 / 组合子策略 / 模拟交易）的
    唯一构造点，故静态面数据契约门禁挂在此处：契约不满足直接报错，
    不构造引擎。
    """
    from app.backtesting.composition_pipeline import CompositionPipeline

    _gate_static(allocator, thscodes, composition, strategy_params or {})

    return CompositionPipeline(
        allocator=allocator,
        thscodes=thscodes,
        composition=composition,
        strategy_params=strategy_params or {},
    )


def _resolve_cost_owner(spec: "RunSpec", strategy: IStrategy) -> Any:
    """定位真正声明费率的策略对象（契约同 ``_gate_prices``）.

    ``CompositionPipeline._base_strategy`` 返回自身，不能用来取 allocator；
    优先 ``spec.allocator``，其次 pipeline 持有的 ``_allocator``，最后才是
    包装对象自身（直传已构建策略的路径）。
    """
    owner = spec.allocator
    if owner is None:
        owner = getattr(strategy, "_allocator", None)
    if owner is None:
        owner = getattr(strategy, "_base_strategy", None)
    return owner if owner is not None else strategy


def _apply_trading_costs(spec: "RunSpec", strategy: IStrategy) -> None:
    """把策略声明的分资产费率回填到 config（成交时由 ExecutionEngine 扣除）.

    策略通过 ``get_trading_costs(params)`` 自述费率表；未声明（默认空 dict）时
    不影响 ``commission_rate``，存量策略行为不变。费率与执行日无关，与原型
    ``Σ|目标−调仓前实际权重| × 费率`` 同口径（Engine 按实际成交额计费）。

    ``spec.strategy_params`` 为空时回退策略对象自身持有的参数字典，避免
    参数未透传导致费率被静默跳过（声明了费率却不生效会直接体现为净值偏高）。
    """
    owner = _resolve_cost_owner(spec, strategy)
    getter = getattr(owner, "get_trading_costs", None)
    if not callable(getter):
        return
    params = spec.strategy_params
    if not params:
        params = getattr(owner, "_strategy_params", None) or {}
    costs = getter(params) or {}
    if costs:
        spec.config.commission_by_code = {str(k): float(v) for k, v in costs.items()}


def run_unified(spec: RunSpec) -> BacktestResult:
    """唯一引擎运行入口：构建引擎组件并逐日推进.

    Returns:
        BacktestResult（snapshots / trades / config）
    """
    strategy = build_strategy(spec)
    _gate_prices(spec, strategy)
    _apply_trading_costs(spec, strategy)
    engine = BacktestEngine(
        config=spec.config,
        data_feed=spec.data_feed,
        strategy=strategy,
        risk_manager=RiskManager(spec.risk_config),
        execution_engine=ExecutionEngine(spec.config),
        progress_cb=spec.progress_cb,
    )
    return engine.run()


def generate_targets(spec: RunSpec) -> List[Dict[str, Any]]:
    """Step1 生成配置结果：只产出各调仓日配置快照，不推演净值.

    与 run_unified 共用同一策略构建（build_strategy）与同一调度解析
    （schedule.resolve_execution_schedule，含自定义信号日历与事件驱动），
    保证“生成的配置”与“回测/监控实际执行的配置”同源一致。
    单策略与组合（合成资产 + 组合 allocator）同一入口。

    每个快照包含决策链三段：
    - candidates：选择层候选（CompositionPipeline 的选择结果；无选择层
      时为全候选池）；
    - target_weights：策略层原始目标权重（含后处理）；
    - risk_weights：风控后权重（RiskManager 同口径约束，与引擎执行前
      应用的约束一致）。

    Returns:
        list[{signal_date, execute_date, candidates, target_weights,
              risk_weights, trigger_type, reason}]
    """
    strategy = build_strategy(spec)
    prices = spec.data_feed.prices
    if prices.empty:
        return []
    trade_dates = list(prices.index)

    # 行情日历注入：与引擎同口径（声明 set_price_calendar 的策略）
    if hasattr(strategy, "set_price_calendar"):
        strategy.set_price_calendar(trade_dates)

    # 面板注入：与引擎同口径，必须在 resolve_execution_schedule 之前
    # （面板期日作为 event_dates 驱动调仓）
    if hasattr(strategy, "set_panels"):
        strategy.set_panels(
            getattr(spec.data_feed, "panels", None),
            getattr(spec.data_feed, "panel_dates", None),
        )

    from app.backtesting.schedule import ScheduleResolver, resolve_execution_schedule

    schedule = resolve_execution_schedule(strategy, spec.config)
    resolver = ScheduleResolver(schedule, trade_dates)
    # 全历史窗口解析再过滤，与引擎 run(start, end) 的窗口不变式同源
    signal_map = resolver.build_signal_to_execute_map(trade_dates[0], trade_dates[-1])

    risk = RiskManager(spec.risk_config)
    thscodes = spec.thscodes or spec.config.thscodes
    pipeline = strategy._base_strategy if hasattr(strategy, "_base_strategy") else strategy

    snapshots: List[Dict[str, Any]] = []
    for sig_date in sorted(signal_map.keys()):
        hist = prices.loc[:sig_date]
        if len(hist) < 2:
            continue
        try:
            signal = strategy.generate_target_weights(hist, sig_date)
        except Exception:
            continue
        weights = getattr(signal, "target_weights", None) or {}
        if not weights:
            continue

        # 候选：选择层结果（无选择层/非 Pipeline 时为全候选池）
        candidates = list(thscodes)
        try:
            if hasattr(pipeline, "_run_selection"):
                active, _, _ = pipeline._run_selection(hist, sig_date)
                candidates = list(active)
        except Exception:
            pass  # 候选展示失败不影响权重快照

        # 风控后权重：与引擎执行前同口径
        risk_signal = risk.apply_risk_checks(signal, hist)

        snapshots.append({
            "signal_date": sig_date,
            "execute_date": signal_map[sig_date],
            "candidates": candidates,
            "target_weights": {k: float(v) for k, v in weights.items() if v is not None},
            "risk_weights": {
                k: float(v) for k, v in risk_signal.target_weights.items() if v is not None
            },
            "trigger_type": getattr(signal, "trigger_type", None),
            "reason": getattr(signal, "reason", None),
        })
    return snapshots
