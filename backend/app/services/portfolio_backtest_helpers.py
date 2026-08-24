"""组合回测共享构建块（自 app/api/backtests.py 平移，P8 治理）.

两个组合回测端点（run-portfolio / run-portfolio-by-id）与监控同源
验证链路（app.monitor.portfolio_backtest_monitor）共用的子策略回测、
四象限组件组装、产品层叠加、穿透分析与结果组装。

app/api/backtests.py 保留再导出，兼容既有 import 面。
"""
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

import pandas as pd
from fastapi import HTTPException

from app.schemas.backtests import SubStrategyResultOut, PortfolioBacktestResultOut
from app.services.backtest_service import BacktestService
from app.services.backtest_execution import _build_risk_config
from app.backtesting.portfolio_analytics import compute_lookthrough_weights
from app.analysis.performance import collect_warnings, compute_drawdown_series

from app.services.backtest_helpers import (
    extract_nav_series as _extract_nav_series,
)

# 四象限权重模型组件组装已下沉到组合层共享构建块
# （app/portfolio/quadrant_components.py），回测 API 与组合服务
# （绩效/回撤链路）同一组装口径，避免参数断点。
from app.portfolio.quadrant_components import build_quadrant_weight_components


async def _maybe_apply_product_layer(
    portfolio_result,
    weight_model_params: Optional[Dict[str, Any]],
    initial_nav: float,
):
    """若 weight_model_params.product_layer 启用，将产品层叠加到组合结果上。

    产品层（对齐原型 VolTargetController）将策略组合 + 短债 + 现金按目标波动率
    配置，产出最终产品净值。启用后 portfolio_result 的 portfolio_nav /
    portfolio_returns / performance 均替换为产品层口径（绩效经统一内核重算）。

    Returns: (portfolio_result, product_layer_summary or None)
    """
    from app.backtesting.product_layer import (
        resolve_product_layer_config,
        run_product_layer_for_nav,
        summarize_product_layer,
    )
    from app.portfolio.composite_runner import _performance_from_nav
    from app.backtesting.analytics import PerformanceAnalyzer
    from app.analysis.performance import DEFAULT_RISK_FREE_RATE

    pl_cfg = resolve_product_layer_config(weight_model_params)
    if not pl_cfg:
        return portfolio_result, None

    product_out = await run_product_layer_for_nav(portfolio_result.portfolio_nav, pl_cfg)
    if not product_out:
        logger.warning("[product_layer] 产品层数据不足，本次回测不启用产品层")
        return portfolio_result, None

    product_nav = product_out["nav"]
    product_nav = product_nav / product_nav.iloc[0] * float(initial_nav)

    portfolio_result.portfolio_nav = product_nav
    portfolio_result.portfolio_returns = product_out["daily_ret"]
    portfolio_result.performance = _performance_from_nav(
        product_nav,
        PerformanceAnalyzer(risk_free_rate=DEFAULT_RISK_FREE_RATE),
        getattr(portfolio_result, "rebalance_dates", None),
    )
    summary = summarize_product_layer(product_out)
    logger.info(
        f"[product_layer] 已应用产品层: 控制器={summary.get('controller')}, "
        f"vol_target={summary.get('vol_target')}, cash_fixed={summary.get('cash_fixed')}, "
        f"最终权重={summary.get('final_weights')}"
    )
    return portfolio_result, summary


def _collect_cost_overrides(request) -> Dict[str, float]:
    """从组合回测请求中收集显式给出的交易成本参数。

    只收录 `is not None` 的字段，因此用户传 0 能真正关闭手续费/滑点，
    而不传时仍沿用子策略默认费率。
    """
    overrides: Dict[str, float] = {}
    for field_name in ("commission_rate", "slippage"):
        value = getattr(request, field_name, None)
        if value is not None:
            overrides[field_name] = float(value)
    return overrides


async def _build_quadrant_weight_components(
    weight_model_params: Dict[str, Any],
    start_date: str,
    end_date: str,
):
    """组装四象限权重模型组件（委托组合层共享构建块，信号标的无行情时报 400）."""
    try:
        return await build_quadrant_weight_components(
            weight_model_params, start_date, end_date
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def _run_sub_strategy_backtests(
    sub_entries: List[Dict[str, Any]],
    start_date: str,
    end_date: str,
    initial_nav: float,
    model_service,
    cost_overrides: Optional[Dict[str, float]] = None,
):
    """逐个执行子策略回测并汇总结果（两个组合回测端点共用）。

    Parameters
    ----------
    sub_entries : List[Dict]
        标准化子策略清单，每项含：
        - model: StrategyModel 子策略模型
        - weight: 配置权重
        - name: 子策略展示名称
        - fetch_id: 用于拉取原始 MongoDB 文档的 ID（可为空）
    cost_overrides : Dict[str, float] or None
        组合级交易成本覆盖（commission_rate / slippage）。只包含调用方显式给出的键，
        因此 0 能正常生效；None 或缺键时沿用子策略自身默认。

    Returns
    -------
    (sub_nav_series, sub_weights, sub_results_out, all_trades, sub_snapshots_by_key)
    """
    from bson import ObjectId as _ObjId

    backtest_service = BacktestService(model_service)
    sub_nav_series: Dict[str, pd.Series] = {}
    sub_weights: Dict[str, float] = {}
    sub_results_out: List[SubStrategyResultOut] = []
    all_trades: List[Dict[str, Any]] = []  # 组合级交易明细（带策略来源标签）
    sub_snapshots_by_key: Dict[str, list] = {}  # 子策略快照（用于穿透分析）

    for entry in sub_entries:
        sub_model = entry["model"]
        weight = entry["weight"]
        sub_name = entry["name"]
        fetch_id = entry["fetch_id"]
        # 子策略可配置独立回测起点（sub_strategies[].backtest_start，YYYYMMDD）：
        # 对齐四象限原型口径——子策略 NAV 从自身更早起点运行（如雪球 2018-12-31 开约），
        # 组合层再截取到组合起始日并重新归一化，保证合约/选择器相位与原型一致。
        sub_start = entry.get("sub_start") or start_date

        # 获取原始 MongoDB 文档，确保所有字段都能被正确读取
        sub_model_data = (
            await model_service.collection.find_one({"_id": _ObjId(fetch_id)})
            if fetch_id else None
        )

        sub_request_data = backtest_service.to_backtest_request(
            model=sub_model,
            start_date=sub_start,
            end_date=end_date,
            initial_nav=initial_nav,
            model_data=sub_model_data,
            **(cost_overrides or {}),
        )
        sub_result = await _execute_single_strategy_backtest(sub_request_data, initial_nav)
        nav_series = _extract_nav_series(sub_result, initial_nav=initial_nav)

        # 子策略起点早于组合起点时：截取到组合起始日并重新归一化
        # （原型同语义：子策略全区间跑，组合层 nav[nav.index >= BACKTEST_START] 后按日收益复合）
        if nav_series is not None and len(nav_series) > 0:
            _combo_start = pd.to_datetime(start_date)
            _mask = nav_series.index >= _combo_start
            if _mask.any() and (not _mask.all() or float(nav_series.iloc[0]) != initial_nav):
                _tail = nav_series.loc[_mask]
                if len(_tail) > 0 and float(_tail.iloc[0]) > 0:
                    nav_series = _tail * (float(initial_nav) / float(_tail.iloc[0]))

        # 收集子策略交易记录，标注策略来源
        for t in sub_result.get("trades", []):
            all_trades.append({
                "strategy_name": sub_name,
                "time": t.time.strftime("%Y-%m-%d") if hasattr(t.time, "strftime") else str(t.time),
                "thscode": t.thscode,
                "side": t.side,
                "quantity": float(t.quantity),
                "price": float(t.price),
                "commission": float(t.commission),
                "slippage_cost": float(t.slippage_cost),
            })

        if nav_series is not None and len(nav_series) > 0:
            key = sub_model.id or sub_model.name
            sub_nav_series[key] = nav_series
            sub_weights[key] = weight
            # 收集子策略快照用于穿透分析
            _snaps = sub_result.get("snapshots", [])
            if _snaps:
                sub_snapshots_by_key[key] = _snaps
            equity_curve = [
                {"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 4)}
                for d, v in zip(nav_series.index, nav_series.values)
            ]
            sub_results_out.append(SubStrategyResultOut(
                model_id=sub_model.id or "",
                name=sub_name,
                weight=weight,
                annual_return=sub_result.get("annual_return", 0),
                annual_volatility=sub_result.get("annual_volatility", 0),
                sharpe_ratio=sub_result.get("sharpe_ratio", 0),
                max_drawdown=sub_result.get("max_drawdown", 0),
                equity_curve=equity_curve,
            ))

    return sub_nav_series, sub_weights, sub_results_out, all_trades, sub_snapshots_by_key


def _build_portfolio_equity_outputs(portfolio_result, sub_snapshots_by_key):
    """构建富化 equity_curve 与穿透后资产级权重历史（两个组合回测端点共用）。"""
    # 穿透分析：计算资产级持仓权重 = 策略权重 × 子策略内资产权重
    lookthrough_weights = compute_lookthrough_weights(
        sub_snapshots_by_key, portfolio_result.weight_history,
        getattr(portfolio_result, "rebalance_dates", []),
    )
    # 构建富化的 equity_curve：包含 drawdown、is_rebalance_day、weights（穿透后资产级）
    rebalance_dates_str = set(
        d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        for d in getattr(portfolio_result, "rebalance_dates", [])
    )
    portfolio_equity = []
    # drawdown 曲线与汇总 max_drawdown 同源，均由统一绩效内核计算
    drawdown_series = compute_drawdown_series(portfolio_result.portfolio_nav)
    for i, (d, v) in enumerate(zip(portfolio_result.portfolio_nav.index,
                                   portfolio_result.portfolio_nav.values)):
        date_str = d.strftime("%Y-%m-%d")
        point = {
            "date": date_str,
            "value": round(float(v), 4),
            "drawdown": round(float(drawdown_series.iloc[i]), 6),
            "is_rebalance_day": date_str in rebalance_dates_str,
        }
        # 穿透后的资产级权重
        if date_str in lookthrough_weights:
            point["weights"] = lookthrough_weights[date_str]
        portfolio_equity.append(point)

    # 权重历史（穿透后资产级）
    weight_history_out = []
    for date_str, asset_weights in sorted(lookthrough_weights.items()):
        entry = {"date": date_str}
        entry.update(asset_weights)
        weight_history_out.append(entry)

    return portfolio_equity, weight_history_out


def _build_portfolio_analytics(sub_nav_series, sub_weights, portfolio_nav, sub_contributions=None):
    """子策略相关性与收益归因分析（统一使用 portfolio_analytics 模块）。

    sub_contributions 为组合引擎输出的逐日贡献矩阵，提供时归因贡献精确可加
    （Σ 贡献 + residual = 组合总收益）。
    """
    from app.backtesting.portfolio_analytics import (
        compute_correlation_drag,
        compute_sub_strategy_attribution,
    )
    corr_result = compute_correlation_drag(sub_nav_series, sub_weights)
    correlation_out = {
        "avg_correlation": corr_result.avg_correlation,
        "diversification_ratio": corr_result.diversification_ratio,
        "correlation_drag": corr_result.correlation_drag,
    }
    if corr_result.correlation_matrix is not None:
        correlation_out["correlation_matrix"] = corr_result.correlation_matrix.to_dict()

    attribution_out = compute_sub_strategy_attribution(
        sub_nav_series, portfolio_nav, sub_weights,
        sub_contributions=sub_contributions,
    )
    return correlation_out, attribution_out


async def _save_portfolio_backtest_record(
    record_model_id: str,
    start_date: str,
    end_date: str,
    initial_nav: float,
    perf,
    portfolio_nav,
    sub_results_out: List[SubStrategyResultOut],
    model_service,
) -> Optional[str]:
    """保存组合回测记录，失败不影响返回。返回记录 ID 或 None。"""
    try:
        from app.models.strategy_model import BacktestRecord, BacktestResult as MBR
        bt_result = MBR(
            total_return=perf.total_return,
            annual_return=perf.annual_return,
            annual_volatility=perf.annual_volatility,
            sharpe_ratio=perf.sharpe_ratio,
            max_drawdown=perf.max_drawdown,
            calmar_ratio=perf.calmar_ratio,
            latest_unit_value=round(float(portfolio_nav.iloc[-1]), 4) if len(portfolio_nav) > 0 else 1.0,
            sub_strategies=[
                {
                    "model_id": s.model_id,
                    "name": s.name,
                    "weight": s.weight,
                    "annual_return": s.annual_return,
                    "annual_volatility": s.annual_volatility,
                    "sharpe_ratio": s.sharpe_ratio,
                    "max_drawdown": s.max_drawdown,
                }
                for s in sub_results_out
            ],
        )
        record = BacktestRecord(
            model_id=record_model_id,
            start_date=pd.to_datetime(start_date),
            end_date=pd.to_datetime(end_date),
            initial_capital=initial_nav,
            result=bt_result,
        )
        return await BacktestService(model_service).save_backtest_record(record)
    except Exception as save_err:
        logger.warning(f"保存组合回测记录失败（不影响返回）: {save_err}")
        return None


async def _build_portfolio_backtest_result(
    portfolio_result,
    sub_nav_series: Dict[str, "pd.Series"],
    sub_weights: Dict[str, float],
    sub_results_out: List[SubStrategyResultOut],
    all_trades: List[Dict[str, Any]],
    sub_snapshots_by_key: Dict[str, list],
    record_model_id: str,
    start_date: str,
    end_date: str,
    initial_nav: float,
    model_service,
    product_layer_out: Optional[Dict[str, Any]] = None,
) -> PortfolioBacktestResultOut:
    """组合回测后处理（两个组合回测端点共用）：
    穿透分析 → 净值曲线富化 → 相关性/归因 → 保存回测记录 → 组装输出。

    record_model_id 由调用方指定（端点 A 传 strategy_model ID，端点 B 传 portfolio ID）。
    """
    perf = portfolio_result.performance
    portfolio_equity, weight_history_out = _build_portfolio_equity_outputs(
        portfolio_result, sub_snapshots_by_key
    )
    correlation_out, attribution_out = _build_portfolio_analytics(
        sub_nav_series, sub_weights, portfolio_result.portfolio_nav,
        sub_contributions=getattr(portfolio_result, "sub_contributions", None),
    )
    backtest_record_id = await _save_portfolio_backtest_record(
        record_model_id, start_date, end_date, initial_nav,
        perf, portfolio_result.portfolio_nav, sub_results_out, model_service,
    )

    return PortfolioBacktestResultOut(
        total_return=perf.total_return,
        annual_return=perf.annual_return,
        annual_volatility=perf.annual_volatility,
        sharpe_ratio=perf.sharpe_ratio,
        max_drawdown=perf.max_drawdown,
        calmar_ratio=perf.calmar_ratio,
        win_rate=getattr(perf, "win_rate", None),
        equity_curve=portfolio_equity,
        sub_strategies=sub_results_out,
        weight_history=weight_history_out,
        correlation_analysis=correlation_out,
        attribution=attribution_out,
        warnings=collect_warnings(
            getattr(perf, "warnings", None),
            (attribution_out or {}).get("warnings"),
        ),
        backtest_record_id=backtest_record_id,
        trades=all_trades,
        product_layer=product_layer_out,
    )


async def _execute_single_strategy_backtest(
    request_data: Dict[str, Any],
    initial_nav: float,
) -> Dict[str, Any]:
    """执行单策略回测并返回结果字典。

    注意：initial_cash（回测起始资金，用于仓位计算）与 initial_nav（组合起始净值，用于归一化）
    是两个独立的概念。initial_cash 来自 request_data（默认 10M），用于回测引擎的仓位大小计算；
    initial_nav 传入 BacktestConfig 但主要用于后续 extract_nav_series 的归一化基准。
    组合回测时 NAV 会被归一化到 initial_nav，因此 initial_cash 的绝对值不影响复合结果。
    """
    from app.backtesting.config import BacktestConfig
    from app.backtesting.data_feed import DataFeed
    from app.backtesting.composition_builder import build_strategy_composition
    from app.backtesting.runner import RunSpec, run_unified
    from app.backtesting.analytics import PerformanceAnalyzer
    from app.services.market_service import MarketService
    from app.allocation.services.registry import create_strategy_service_from_database

    strategy_params = request_data.get("strategy_params") or {}
    # composition 必须与单策略回测同源推导：直接取 COMPOSITION_DEFAULTS 会让 selector
    # 恒为 None，选择器不执行，带标签预算的分配模型（vol_scaled_budget/tag_based）会
    # 退化成全资产池等分预算，与单策略回测结果严重背离。
    spec = build_strategy_composition(
        request_data["strategy_type"], request_data["thscodes"], strategy_params,
    )

    # 交易成本必须从 request_data 读取：此前遗漏导致组合回测的子策略恒用
    # BacktestConfig 默认费率（0.03% + 0.05%），前端/调用方设置的 0 成本无法生效。
    # 用 `is not None` 判断而非 or/get 默认值，确保 0 是有效取值。
    _commission = request_data.get("commission_rate")
    _slippage = request_data.get("slippage")
    # 月末调仓：与单策略回测一致（按编制规则使用月末最后一个交易日）
    _rebalance_freq = "month_end" if spec.force_month_end else request_data.get("rebalance_freq", "monthly")
    config = BacktestConfig(
        name=request_data["name"],
        thscodes=request_data["thscodes"],
        start_date=request_data["start_date"],
        end_date=request_data["end_date"],
        rebalance_freq=_rebalance_freq,
        initial_cash=request_data.get("initial_cash", 10_000_000.0),
        initial_nav=initial_nav,
        **({"commission_rate": float(_commission)} if _commission is not None else {}),
        **({"slippage": float(_slippage)} if _slippage is not None else {}),
    )

    market_service = MarketService()
    # 统一使用 lookback_days=500，与 portfolio_service._run_sub_strategy_backtest 对齐
    # 确保动量策略 min_history_days=260 有足够的历史数据缓冲
    data_feed = await DataFeed.from_market_service(market_service, config, lookback_days=500)
    strategy_service = await create_strategy_service_from_database(market_service)
    strategy_cls = strategy_service.get_strategy_class(request_data["strategy_type"])

    # 经唯一引擎入口运行；风控口径与单策略回测对齐：读取策略参数里的杠杆与单资产上限
    result = run_unified(RunSpec(
        config=config,
        data_feed=data_feed,
        allocator=strategy_cls(),
        thscodes=request_data["thscodes"],
        composition=spec.composition,
        strategy_params=strategy_params,
        risk_config=_build_risk_config(strategy_params),
    ))

    analyzer = PerformanceAnalyzer(risk_free_rate=0.02)
    _sub_max_lev = (request_data.get("strategy_params") or {}).get("max_leverage")
    _sub_max_lev = float(_sub_max_lev) if _sub_max_lev is not None else None
    perf = analyzer.from_results(result.snapshots, max_leverage=_sub_max_lev)

    return {
        "annual_return": perf.annual_return,
        "annual_volatility": perf.annual_volatility,
        "sharpe_ratio": perf.sharpe_ratio,
        "max_drawdown": perf.max_drawdown,
        "win_rate": perf.win_rate,
        "snapshots": result.snapshots,
        "trades": result.trades,
    }
