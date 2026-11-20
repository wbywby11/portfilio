"""组合回测共享构建块（自 app/api/backtests.py 平移，P8 治理）.

两个组合回测端点（run-portfolio / run-portfolio-by-id）与监控同源
验证链路（app.monitor.portfolio_backtest_monitor）共用的子策略回测、
四象限组件组装、产品层叠加、穿透分析与结果组装。

app/api/backtests.py 保留再导出，兼容既有 import 面。
"""
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

import pandas as pd
from fastapi import HTTPException

from app.schemas.backtests import SubStrategyResultOut, PortfolioBacktestResultOut
from app.services.backtest_service import BacktestService
from app.backtesting.portfolio_analytics import compute_lookthrough_weights
from app.analysis.performance import collect_warnings, compute_drawdown_series

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
        # 产品层只是叠加了现金/短债的净值变换，组合调仓成交不变，成本仍应保留
        trades=getattr(portfolio_result, "portfolio_trades", None),
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
    progress_cb=None,
    engine_progress=None,
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
    progress_cb : async callable(done, total, message) or None
        子策略完成回调（监控路径用于任务进度上报；回测端点不传，行为不变）。
    engine_progress : callable(sub_idx, sub_name) -> sync callback or None
        子策略内部逐日进度工厂：入参为该子策略在本次组合中的序号（1 起）与名称，
        返回引擎直接调用的同步回调 ``(done, total, bar_time) -> None``。
        引擎跑在工作线程，故这里只提供同步回调，跨线程调度由调用方负责。

    Returns
    -------
    (sub_nav_series, sub_weights, sub_results_out, all_trades, sub_snapshots_by_key)

    契约：组合层与子策略的唯一交互面是「净值序列」——子策略的参数组装、数据
    与面板加载、引擎执行、绩效计算全部在
    ``single_strategy_executor.execute_model_isolated`` 内完成；本函数只负责
    调度子策略、收集净值序列与快照/交易明细，不构造 DataFeed、不解析
    strategy_type、不感知面板与调仓频率。
    """
    from app.services.single_strategy_executor import execute_model_isolated

    sub_nav_series: Dict[str, pd.Series] = {}
    sub_weights: Dict[str, float] = {}
    sub_results_out: List[SubStrategyResultOut] = []
    all_trades: List[Dict[str, Any]] = []  # 组合级交易明细（带策略来源标签）
    sub_snapshots_by_key: Dict[str, list] = {}  # 子策略快照（用于穿透分析）
    _total_subs = max(len(sub_entries), 1)

    for _sub_idx, entry in enumerate(sub_entries, start=1):
        sub_model = entry["model"]
        weight = entry["weight"]
        sub_name = entry["name"]
        # 子策略可配置独立回测起点（sub_strategies[].backtest_start，YYYYMMDD）：
        # 对齐四象限原型口径——子策略 NAV 从自身更早起点运行，组合层再截取到
        # 组合起始日并重新归一化，保证合约/选择器相位与原型一致。
        sub_start = entry.get("sub_start") or start_date

        sub_result = await execute_model_isolated(
            sub_model,
            start_date=sub_start,
            end_date=end_date,
            initial_nav=initial_nav,
            model_service=model_service,
            name=sub_name,
            cost_overrides=cost_overrides,
            progress_cb=(
                engine_progress(_sub_idx, sub_name)
                if engine_progress is not None else None
            ),
        )
        nav_series = sub_result.nav_series

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
        for t in sub_result.trades:
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
            if sub_result.snapshots:
                sub_snapshots_by_key[key] = list(sub_result.snapshots)
            equity_curve = [
                {"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 4)}
                for d, v in zip(nav_series.index, nav_series.values)
            ]
            perf = sub_result.performance
            sub_results_out.append(SubStrategyResultOut(
                model_id=sub_model.id or "",
                name=sub_name,
                weight=weight,
                annual_return=getattr(perf, "annual_return", 0) or 0,
                annual_volatility=getattr(perf, "annual_volatility", 0) or 0,
                sharpe_ratio=getattr(perf, "sharpe_ratio", 0) or 0,
                max_drawdown=getattr(perf, "max_drawdown", 0) or 0,
                annual_return_365=getattr(perf, "annual_return_365", None),
                annual_volatility_365=getattr(perf, "annual_volatility_365", None),
                sharpe_ratio_365=getattr(perf, "sharpe_ratio_365", None),
                n_trades=getattr(perf, "n_trades", 0) or 0,
                total_commission=getattr(perf, "total_commission", 0.0) or 0.0,
                total_slippage=getattr(perf, "total_slippage", 0.0) or 0.0,
                turnover=getattr(perf, "turnover", 0.0) or 0.0,
                equity_curve=equity_curve,
            ))
            # 子策略完成后上报一次：前端据此看到逐个子策略推进，
            # 而不是整段静默到合成结束。
            if progress_cb is not None:
                try:
                    await progress_cb(
                        _sub_idx, _total_subs,
                        f"子策略回测 {_sub_idx}/{_total_subs} 完成：{sub_name}",
                    )
                except Exception as exc:  # noqa: BLE001 —— 进度失败不影响回测
                    logger.warning(f"[组合回测] 子策略进度上报失败: {exc}")

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


def _build_portfolio_record_details(
    portfolio_equity: List[Dict[str, Any]],
    weight_history_out: List[Dict[str, Any]],
    portfolio_returns,
    initial_nav: float,
    asset_names: Dict[str, str],
):
    """把组合引擎输出转为回测记录明细（净值点/收益率点/权重变化/持仓记录）。"""
    from app.models.strategy_model import (
        AssetPosition,
        EquityPoint,
        PositionRecord,
        ReturnPoint,
        WeightChangePoint,
    )

    nav0 = float(initial_nav) if initial_nav else 0.0
    equity_points: List[EquityPoint] = []
    unit_values: List[float] = []
    for pt in portfolio_equity or []:
        value = float(pt.get("value") or 0.0)
        unit_value = value / nav0 if nav0 else 1.0
        unit_values.append(unit_value)
        equity_points.append(EquityPoint(
            date=pt.get("date"),
            value=value,
            unit_value=unit_value,
            cumulative_return=unit_value - 1.0,
            drawdown=pt.get("drawdown"),
        ))

    # 日收益与净值点等长时写入，否则留空（前端会从单位净值推导累计收益）
    return_points: List[ReturnPoint] = []
    returns_len = len(portfolio_returns) if portfolio_returns is not None else 0
    if returns_len > 0 and returns_len == len(equity_points):
        returns = list(portfolio_returns)
        for pt, day_ret, unit_value in zip(equity_points, returns, unit_values):
            ret = 0.0 if pd.isna(day_ret) else float(day_ret)
            return_points.append(ReturnPoint(
                date=pt.date,
                daily_return=ret,
                cumulative_return=unit_value - 1.0,
            ))

    weight_changes = [
        WeightChangePoint(
            date=entry.get("date"),
            weights={k: float(v) for k, v in entry.items() if k != "date"},
        )
        for entry in weight_history_out or []
        if entry.get("date")
    ]

    positions: List[PositionRecord] = []
    for pt in portfolio_equity or []:
        if not pt.get("is_rebalance_day"):
            continue
        weights = pt.get("weights") or {}
        if not weights:
            continue
        value = float(pt.get("value") or 0.0)
        positions.append(PositionRecord(
            date=pt.get("date"),
            portfolio_value=value,
            positions=[
                AssetPosition(
                    asset_code=code,
                    asset_name=(asset_names or {}).get(code),
                    weight=float(weight),
                    market_value=value * float(weight),
                )
                for code, weight in weights.items()
            ],
        ))

    return equity_points, return_points, weight_changes, positions


async def _collect_portfolio_asset_names(
    weight_history_out: List[Dict[str, Any]],
    sub_results_out: List[SubStrategyResultOut],
    model_service,
) -> Dict[str, str]:
    """按穿透后出现的资产代码，从子策略模型取资产名称（仅用于展示）。"""
    codes = set()
    for entry in weight_history_out or []:
        codes.update(k for k in entry.keys() if k != "date")
    if not codes:
        return {}
    names: Dict[str, str] = {}
    for sub in sub_results_out or []:
        try:
            model = await model_service.get_model(sub.model_id)
        except Exception as exc:
            logger.warning(f"获取子策略模型失败 model_id={sub.model_id}: {exc}")
            continue
        for code, name in (getattr(model, "asset_names", None) or {}).items():
            if code in codes and name:
                names.setdefault(code, name)
    return names


def _rename_correlation_matrix(
    matrix: Optional[Dict[str, Dict[str, float]]],
    sub_results_out: List[SubStrategyResultOut],
) -> Optional[Dict[str, Dict[str, float]]]:
    """把相关性矩阵的键从模型 ID 换成子策略名称，便于直接展示。"""
    if not matrix:
        return None
    name_map: Dict[str, str] = {}
    for s in sub_results_out or []:
        name_map[str(s.model_id)] = s.name
        name_map[s.name] = s.name
    return {
        name_map.get(str(row), str(row)): {
            name_map.get(str(col), str(col)): float(val)
            for col, val in (cols or {}).items()
        }
        for row, cols in matrix.items()
    }


async def _save_portfolio_backtest_record(
    record_model_id: str,
    start_date: str,
    end_date: str,
    initial_nav: float,
    perf,
    portfolio_nav,
    sub_results_out: List[SubStrategyResultOut],
    model_service,
    equity_points: Optional[list] = None,
    return_points: Optional[list] = None,
    weight_changes: Optional[list] = None,
    positions: Optional[list] = None,
    asset_names: Optional[Dict[str, str]] = None,
    correlation_matrix: Optional[Dict[str, Dict[str, float]]] = None,
) -> Optional[str]:
    """保存组合回测记录（含净值曲线、权重变化、持仓明细），失败不影响返回。"""
    try:
        from app.models.strategy_model import BacktestRecord, BacktestResult as MBR
        bt_result = MBR(
            total_return=perf.total_return,
            annual_return=perf.annual_return,
            annual_volatility=perf.annual_volatility,
            sharpe_ratio=perf.sharpe_ratio,
            max_drawdown=perf.max_drawdown,
            calmar_ratio=perf.calmar_ratio,
            annual_return_365=getattr(perf, "annual_return_365", None),
            annual_volatility_365=getattr(perf, "annual_volatility_365", None),
            sharpe_ratio_365=getattr(perf, "sharpe_ratio_365", None),
            calmar_ratio_365=getattr(perf, "calmar_ratio_365", None),
            latest_unit_value=round(float(portfolio_nav.iloc[-1]), 4) if len(portfolio_nav) > 0 else 1.0,
            equity_curve=equity_points or [],
            return_curve=return_points or [],
            weight_changes=weight_changes or [],
            positions=positions or [],
            asset_names=asset_names or None,
            correlation_matrix=correlation_matrix,
            sub_strategies=[
                {
                    "model_id": s.model_id,
                    "name": s.name,
                    "weight": s.weight,
                    "annual_return": s.annual_return,
                    "annual_volatility": s.annual_volatility,
                    "sharpe_ratio": s.sharpe_ratio,
                    "max_drawdown": s.max_drawdown,
                    "annual_return_365": s.annual_return_365,
                    "annual_volatility_365": s.annual_volatility_365,
                    "sharpe_ratio_365": s.sharpe_ratio_365,
                    "n_trades": s.n_trades,
                    "total_commission": s.total_commission,
                    "total_slippage": s.total_slippage,
                    "turnover": s.turnover,
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

    # 保存回测记录时同步写入明细，供历史详情页展示净值/回撤/权重/持仓
    asset_names = await _collect_portfolio_asset_names(
        weight_history_out, sub_results_out, model_service
    )
    correlation_matrix = _rename_correlation_matrix(
        (correlation_out or {}).get("correlation_matrix"), sub_results_out
    )
    equity_points, return_points, weight_changes, positions = _build_portfolio_record_details(
        portfolio_equity, weight_history_out,
        getattr(portfolio_result, "portfolio_returns", None),
        initial_nav, asset_names,
    )
    backtest_record_id = await _save_portfolio_backtest_record(
        record_model_id, start_date, end_date, initial_nav,
        perf, portfolio_result.portfolio_nav, sub_results_out, model_service,
        equity_points=equity_points,
        return_points=return_points,
        weight_changes=weight_changes,
        positions=positions,
        asset_names=asset_names,
        correlation_matrix=correlation_matrix,
    )

    return PortfolioBacktestResultOut(
        total_return=perf.total_return,
        annual_return=perf.annual_return,
        annual_volatility=perf.annual_volatility,
        sharpe_ratio=perf.sharpe_ratio,
        max_drawdown=perf.max_drawdown,
        calmar_ratio=perf.calmar_ratio,
        annual_return_365=getattr(perf, "annual_return_365", None),
        annual_volatility_365=getattr(perf, "annual_volatility_365", None),
        sharpe_ratio_365=getattr(perf, "sharpe_ratio_365", None),
        calmar_ratio_365=getattr(perf, "calmar_ratio_365", None),
        win_rate=getattr(perf, "win_rate", None),
        n_trades=getattr(perf, "n_trades", 0),
        total_commission=getattr(perf, "total_commission", 0.0),
        total_slippage=getattr(perf, "total_slippage", 0.0),
        turnover=getattr(perf, "turnover", 0.0),
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
