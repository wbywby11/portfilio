"""单策略回测执行核心（自 app/api/backtests.py 平移，P8 治理）.

承接回测执行链路：配置构造、主观策略校验、资产校验、DataFeed 构建
（含 etf_discount 专用）、run_unified 调用、响应组装与异常翻译；
以及快照/交易序列化与风控配置推导（单策略与组合子策略共用）。
"""
from typing import Dict, Any, Optional
import traceback

import pandas as pd
from fastapi import HTTPException

from app.schemas.response import Response
from app.schemas.backtests import BacktestRequest, SnapshotOut, TradeOut, BacktestResultOut
from app.services.market_service import MarketService
from app.services.asset_service import AssetService
from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.allocation.services.registry import create_strategy_service_from_database
from app.analysis.formulas.drawdown import calculate_drawdown_series

from app.services.backtest_helpers import (
    sanitize_dict_for_json as _sanitize_dict_for_json,
    apply_snapshot_aggregation as _apply_snapshot_aggregation,
    rebalance_label_for_trade as _rebalance_label_for_trade,
)


async def _run_backtest_core(
    request: BacktestRequest,
    market_service: MarketService,
    asset_service: AssetService,
):
    """
    运行回测（使用新的 BacktestEngine）
    
    流程：
    1. 根据策略类型和参数创建策略实例
    2. 从 MarketService 加载历史行情数据
    3. 创建 DataFeed、RiskManager、ExecutionEngine
    4. 运行 BacktestEngine
    5. 返回回测结果
    
    注意：
    - 日期格式为 YYYYMMDD（如 20230101）
    - 策略参数必须符合该策略的Schema定义
    """
    try:
        # 1. 创建回测配置
        config = BacktestConfig(
            name=request.name,
            thscodes=request.thscodes,
            start_date=request.start_date,
            end_date=request.end_date,
            rebalance_freq=request.rebalance_freq,
            initial_cash=request.initial_cash,
            commission_rate=request.commission_rate,
            slippage=request.slippage,
            execution_delay=getattr(request, "execution_delay", None),
        )
        # 从 strategy_params 中提取 target_vol（控制模块参数），供前端波动率监控图使用
        _sp_for_tv = getattr(request, "strategy_params", None) or {}
        _tv = _sp_for_tv.get("target_vol")
        if _tv is not None:
            try:
                config.target_vol = float(_tv)
            except (TypeError, ValueError):
                pass
        # 交互式权重调整：转换为 {date_str: {weights?, auto_normalize}}，权重可选（不设则到该日由用户选择）
        if getattr(request, "manual_weight_adjustments", None):
            adj_dict = {}
            for item in request.manual_weight_adjustments:
                if isinstance(item, dict) and item.get("date"):
                    d = str(item["date"]).replace("-", "")[:8]
                    adj_dict[d] = {
                        "weights": dict(item["weights"]) if item.get("weights") is not None else {},
                        "auto_normalize": item.get("auto_normalize", False),
                    }
            config.manual_weight_adjustments = adj_dict if adj_dict else None

        strategy_type = getattr(request, "strategy_type", "") or ""

        # 主观策略仅按预设日期调仓：至少需一个预设调仓日（权重可到该日再选）
        if strategy_type in ("manual_allocation", "manual_allocation_strategy"):
            config.rebalance_only_on_preset_dates = True
            if not config.manual_weight_adjustments or len(config.manual_weight_adjustments) == 0:
                raise HTTPException(
                    status_code=400,
                    detail="主观配置策略需至少预设一个调仓日期（权重可留空，到该日再选择）。"
                )
            sp = getattr(request, "strategy_params", None) or {}
            max_leverage = float(sp.get("max_leverage", 4))
            if max_leverage < 1:
                max_leverage = 4
            # 期初建仓：使用策略默认权重（或本次回测覆盖的 manual_weights）在首日建仓
            mw = sp.get("manual_weights")
            if mw and isinstance(mw, dict) and len(mw) > 0:
                config.initial_weights = {k: float(v) for k, v in mw.items() if v is not None}
                total = sum(config.initial_weights.values())
                if total > max_leverage:
                    raise HTTPException(
                        status_code=400,
                        detail=f"初始权重总和 {total*100:.2f}% 超过最大杠杆 {max_leverage*100:.0f}%。请调整权重或策略参数「最大杠杆」。"
                    )
            # 预设调仓日权重：总仓位不得超过最大杠杆
            if config.manual_weight_adjustments:
                for d, adj in config.manual_weight_adjustments.items():
                    w = adj.get("weights") or {}
                    if w:
                        total = sum(float(v) for v in w.values() if v is not None)
                        if total > max_leverage:
                            raise HTTPException(
                                status_code=400,
                                detail=f"预设调仓日 {d} 的权重总和 {total*100:.2f}% 超过最大杠杆 {max_leverage*100:.0f}%。请调整权重或策略参数「最大杠杆」。"
                            )
                first_date = min(config.manual_weight_adjustments.keys())
                config.initial_weights_auto_normalize = config.manual_weight_adjustments[first_date].get("auto_normalize", False)

        # 2. 验证资产代码是否存在（特殊策略类型跳过，资产从专用集合加载）
        _SPECIALIZED_FEED_TYPES = {"etf_discount"}
        if strategy_type not in _SPECIALIZED_FEED_TYPES:
            if not request.thscodes:
                raise HTTPException(
                    status_code=400,
                    detail="资产代码列表为空，请检查策略模型的资产配置"
                )
            
            # 验证资产是否存在
            missing_assets = []
            for code in request.thscodes:
                asset_info = await asset_service.get_asset_by_code(code)
                if not asset_info:
                    missing_assets.append(code)
            
            if missing_assets:
                raise HTTPException(
                    status_code=400,
                    detail=f"以下资产代码不存在或未配置：{', '.join(missing_assets)}。请检查资产库中的资产配置。"
                )

        # 3. 创建数据源
        # 特殊策略类型（etf_discount）使用专用 DataFeed
        _SPECIALIZED_FEED_TYPES = {"etf_discount"}
        if strategy_type in _SPECIALIZED_FEED_TYPES:
            from app.backtesting.data_feed import build_specialized_data_feed
            data_feed = await build_specialized_data_feed(
                strategy_type=strategy_type,
                config=config,
                lookback_days=request.lookback_days,
            )
            # ETF Discount: 自动注入 ETF 代码列表
            if strategy_type == "etf_discount":
                sp = request.strategy_params or {}
                if not sp.get("etf_codes"):
                    import json
                    etf_cols = [
                        str(c) for c in data_feed.prices.columns
                        if not str(c).endswith("_discount") and not str(c).endswith("_dr")
                    ]
                    sp["etf_codes"] = json.dumps(etf_cols)
                request.strategy_params = sp
                # 更新 thscodes 为 ETF 代码（供回测引擎使用）
                config.thscodes = [
                    str(c) for c in data_feed.prices.columns
                    if not str(c).endswith("_discount") and not str(c).endswith("_dr")
                ]
        else:
            # momentum_reversal (7+1) / min_history_days>=260 需至少 400 日历天预加载（确保 260 交易日 + 缓冲）
            effective_lookback = request.lookback_days
            sp = request.strategy_params or {}
            sel = sp.get("selection_info") or sp
            if (
                sel.get("selector_type") == "momentum_reversal"
                or int(sp.get("min_history_days", 0)) >= 260
            ):
                effective_lookback = max(effective_lookback, 400)
            data_feed = await DataFeed.from_market_service(
                market_service=market_service,
                config=config,
                lookback_days=effective_lookback
            )
        
        if data_feed.prices.empty:
            # 提供更详细的错误信息
            start_str = (request.start_date or "")[:8]
            end_str = (request.end_date or "")[:8]
            hint = ""
            try:
                from datetime import datetime as dt
                today = dt.now().strftime("%Y%m%d")
                if start_str >= today or end_str >= today:
                    hint = "提示：当前日期范围包含今日或未来日期，历史行情可能尚未产生或尚未入库。请使用已过去的日期区间。\n"
            except Exception:
                pass
            error_msg = (
                f"无法获取历史行情数据。\n"
                f"资产代码：{', '.join(request.thscodes)}\n"
                f"日期范围：{request.start_date} 至 {request.end_date}\n"
                f"{hint}"
                f"可能原因：\n"
                f"1. 资产代码格式不正确（如多写、少写字符）\n"
                f"2. 指定日期范围内没有行情数据\n"
                f"3. 资产尚未导入行情数据\n"
                f"请检查资产库中的资产配置和行情数据导入情况。"
            )
            raise HTTPException(
                status_code=400,
                detail=error_msg
            )
        
        # 预设调仓日校验：须在回测区间内，且为有数据的交易日
        if config.manual_weight_adjustments:
            start_ymd = str(request.start_date).replace("-", "")[:8]
            end_ymd = str(request.end_date).replace("-", "")[:8]
            preset_keys = list(config.manual_weight_adjustments.keys())
            out_of_range = [d for d in preset_keys if d < start_ymd or d > end_ymd]
            if out_of_range:
                raise HTTPException(
                    status_code=400,
                    detail=f"调仓日不可超出回测时间区间。以下日期超出区间 [{start_ymd}, {end_ymd}]：{', '.join(sorted(out_of_range))}。请重新设置调仓日。"
                )
            trading_days = set(pd.Series(data_feed.prices.index).dt.strftime("%Y%m%d").astype(str).tolist())
            invalid_preset = [d for d in preset_keys if d not in trading_days]
            if invalid_preset:
                raise HTTPException(
                    status_code=400,
                    detail=f"以下调仓日在回测区间内无行情数据或为非交易日，请重新设置调仓日：{', '.join(sorted(invalid_preset))}"
                )
        
        # 检查是否有部分资产没有数据
        available_assets = list(data_feed.prices.columns)
        missing_data_assets = [code for code in request.thscodes if code not in available_assets]
        if missing_data_assets:
            import warnings
            warnings.warn(
                f"以下资产在指定日期范围内没有数据：{', '.join(missing_data_assets)}。"
                f"将使用有数据的资产进行回测。"
            )

        # 4. 创建策略实例（从数据库加载模板）
        strategy_service = await create_strategy_service_from_database(
            market_service=market_service
        )
        
        try:
            strategy_cls = strategy_service.get_strategy_class(request.strategy_type)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"策略类型不存在: {request.strategy_type}"
            )
        
        # 实例化策略模型
        try:
            strategy_impl = strategy_cls()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"策略实例化失败: {str(e)}\n"
                    f"策略类型: {request.strategy_type}\n"
                    f"请检查策略类的实现是否正确。"
                )
            )
        
        # 验证策略是否有 allocate 方法
        if not hasattr(strategy_impl, 'allocate'):
            raise HTTPException(
                status_code=500,
                detail=(
                    f"策略类 {strategy_cls.__name__} 没有实现 allocate 方法。\n"
                    f"策略必须实现 allocate(prices: DataFrame, **params) -> Series 接口。"
                )
            )
        
        # 检查是否启用资产选择并推导 composition（与组合回测/日常监控共用同一套推导）
        from app.backtesting.composition_builder import build_strategy_composition

        spec = build_strategy_composition(
            request.strategy_type, request.thscodes, request.strategy_params,
        )
        enable_selection = spec.enable_selection
        selected_asset_count: Optional[int] = spec.selected_asset_count
        composition = spec.composition

        # vol_scaled_budget (tag_based/selection_equal) 混合动量：按编制规则使用月末最后一个交易日
        if spec.force_month_end:
            config.rebalance_freq = "month_end"

        # 构建策略并经唯一引擎入口运行（selector=None 时自动跳过选择阶段）
        from app.backtesting.runner import RunSpec, run_unified
        try:
            result = run_unified(RunSpec(
                config=config,
                data_feed=data_feed,
                allocator=strategy_impl,
                thscodes=request.thscodes,
                composition=composition,
                strategy_params=request.strategy_params,
                # 支持最大杠杆>1 时权重和大于1，不强制归一化为和1
                risk_config=_build_risk_config(request.strategy_params),
            ))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"策略构建/回测执行失败: {str(e)}\n"
                    f"策略类型: {request.strategy_type}\n"
                    f"策略参数: {request.strategy_params}\n"
                    f"请检查策略参数配置是否正确。"
                )
            )
        
        # 7. 获取资产名称
        asset_names = {}
        for code in request.thscodes:
            asset_info = await asset_service.get_asset_by_code(code)
            asset_names[code] = asset_info.name if asset_info and asset_info.name else code
        
        # 8. 构建响应数据
        # 计算回撤序列
        total_values_series = pd.Series([s.total_value for s in result.snapshots])
        drawdown_series = calculate_drawdown_series(total_values_series) if not total_values_series.empty else pd.Series()
        
        # 返回权重：保留 0（未选资产），仅剔除 None，以便图注/图表展示全部候选资产（含 0 权重）
        def _weights_for_response(weights_dict):
            if not weights_dict:
                return weights_dict
            return {k: float(v) for k, v in weights_dict.items() if v is not None}
        
        snapshots_out = [
            SnapshotOut(
                time=s.time,
                total_value=s.total_value,
                cash=s.cash,
                holdings_value=s.holdings_value,
                weights=_weights_for_response(s.weights),
                is_rebalance_day=s.is_rebalance_day,
                rebalance_type=getattr(s, "rebalance_type", None),
                rebalance_reason=getattr(s, "rebalance_reason", None),
                portfolio_volatility=getattr(s, "portfolio_volatility", None),
                drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0,
                monitoring_metrics=getattr(s, "monitoring_metrics", {})
            )
            for i, s in enumerate(result.snapshots)
        ]
        
        rebalance_by_date = {}
        for s in result.snapshots:
            if getattr(s, "is_rebalance_day", False):
                dt = getattr(s, "time", None)
                if dt is not None:
                    key = pd.Timestamp(dt).strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                    rebalance_by_date[key] = (getattr(s, "rebalance_type", None), getattr(s, "rebalance_reason", None))
        trades_out = []
        for t in result.trades:
            tdt = getattr(t, "time", None)
            key = pd.Timestamp(tdt).strftime("%Y-%m-%d") if tdt is not None and hasattr(pd.Timestamp(tdt), "strftime") else (str(tdt)[:10] if tdt else "")
            rt, rr = rebalance_by_date.get(key, (None, None))
            trades_out.append(
                TradeOut(
                    time=t.time,
                    thscode=t.thscode,
                    side=t.side,
                    quantity=t.quantity,
                    price=t.price,
                    commission=t.commission,
                    slippage_cost=t.slippage_cost,
                    rebalance_label=_rebalance_label_for_trade(rt, rr)
                )
            )
        
        # 计算绩效指标
        from app.backtesting.analytics import PerformanceAnalyzer
        
        analyzer = PerformanceAnalyzer(risk_free_rate=0.02)
        _max_total_leverage = (request.strategy_params or {}).get("max_total_leverage") \
            or (request.strategy_params or {}).get("max_leverage")
        performance = analyzer.from_results(result.snapshots, result.trades, max_leverage=_max_total_leverage)
        
        backtest_result = BacktestResultOut(
            snapshots=snapshots_out,
            trades=trades_out,
            total_return=performance.total_return,
            annual_return=performance.annual_return,
            volatility=performance.annual_volatility,
            sharpe_ratio=performance.sharpe_ratio,
            max_drawdown=performance.max_drawdown,
            calmar_ratio=performance.calmar_ratio,
            win_rate=performance.win_rate,
            n_trades=performance.n_trades,
            total_commission=performance.total_commission,
            total_slippage=performance.total_slippage,
            turnover=performance.turnover,
            warnings=list(performance.warnings),
            asset_names=asset_names,
            selected_asset_count=selected_asset_count
        )
        
        _snap = backtest_result.snapshots if hasattr(backtest_result, "snapshots") else []
        print(f"[回测] 返回回测完成数据 snapshots={len(_snap)} trades={len(getattr(backtest_result, 'trades', None) or [])}")
        # 动量资产选择模式下，打印返回前端的调仓资产和权重
        if request.strategy_params.get("enable_momentum_selection"):
            import logging
            _log = logging.getLogger(__name__)
            for s in _snap:
                is_reb = getattr(s, "is_rebalance_day", False)
                if is_reb:
                    dt = getattr(s, "time", None)
                    dt_str = pd.Timestamp(dt).strftime("%Y-%m-%d") if dt is not None else ""
                    w = getattr(s, "weights", None) or {}
                    nonzero = [(c, v) for c, v in w.items() if v is not None and float(v) > 1e-9]
                    names = asset_names or {}
                    lines = [f"[动量选择-返回前端] 调仓日 {dt_str} 资产与权重:"]
                    for code, val in sorted(nonzero, key=lambda x: -x[1]):
                        name = names.get(code, code)
                        lines.append(f"  ・ {code} ({name}): {(float(val)*100):.2f}%")
                    if not nonzero:
                        lines.append("  （无权重>0的资产）")
                    _log.info("\n".join(lines))
        _data = backtest_result.model_dump() if hasattr(backtest_result, "model_dump") else backtest_result
        _apply_snapshot_aggregation(_data)
        return Response.success(data=_sanitize_dict_for_json(_data), message="回测完成")
        
    except ValueError as e:
        traceback.print_exc()
        # ValueError 通常是参数验证错误，返回400状态码
        # 如果错误信息包含换行符，保持格式以便前端正确显示
        error_detail = str(e)
        raise HTTPException(status_code=400, detail=error_detail)
    except RuntimeError as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"回测执行失败: {str(e)}")


def _snapshots_to_out(snapshots: list, _weights_for_response) -> list:
    """将引擎快照转为 SnapshotOut 并计算回撤"""
    if not snapshots:
        return []
    total_values_series = pd.Series([s.total_value for s in snapshots])
    drawdown_series = calculate_drawdown_series(total_values_series) if not total_values_series.empty else pd.Series()
    return [
        SnapshotOut(
            time=s.time,
            total_value=s.total_value,
            cash=s.cash,
            holdings_value=s.holdings_value,
            weights=_weights_for_response(s.weights),
            is_rebalance_day=s.is_rebalance_day,
            rebalance_type=getattr(s, "rebalance_type", None),
            rebalance_reason=getattr(s, "rebalance_reason", None),
            portfolio_volatility=getattr(s, "portfolio_volatility", None),
            drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0,
            monitoring_metrics=getattr(s, "monitoring_metrics", {}),
        )
        for i, s in enumerate(snapshots)
    ]


def _trade_to_dict(t: Any) -> Dict[str, Any]:
    """将引擎 Trade 转为可序列化 dict，用于步进回测累计交易列表."""
    return {
        "time": getattr(t, "time", None),
        "thscode": getattr(t, "thscode", ""),
        "side": getattr(t, "side", ""),
        "quantity": float(getattr(t, "quantity", 0) or 0),
        "price": float(getattr(t, "price", 0) or 0),
        "commission": float(getattr(t, "commission", 0) or 0),
        "slippage_cost": float(getattr(t, "slippage_cost", 0) or 0),
    }


def _build_risk_config(strategy_params: Dict[str, Any]):
    """从策略参数推导风控配置（单策略回测与组合子策略回测共用）。

    max_total_leverage 为 None 时不强制归一化，允许权重和小于/大于 1。
    """
    from app.backtesting.risk import RiskConfig

    strategy_params = strategy_params or {}
    max_total_leverage = strategy_params.get("max_total_leverage") or strategy_params.get("max_leverage")
    if max_total_leverage is not None:
        try:
            max_total_leverage = float(max_total_leverage)
        except (TypeError, ValueError):
            max_total_leverage = None
    max_weight_dict = strategy_params.get("weight_caps", strategy_params.get("max_weight_dict"))
    if not isinstance(max_weight_dict, dict) or not max_weight_dict:
        max_weight_dict = None
    # 类雪球 Delta 对冲等策略 allow_short=True 时，KI 后需保留负权重做空对冲，
    # 风控层不得将负权重截断为 0（对齐四象限原型 allow_short 语义）。
    allow_negative = bool(strategy_params.get("allow_short", False))
    try:
        return RiskConfig(
            max_total_leverage=max_total_leverage,
            max_weight_dict=max_weight_dict,
            allow_negative_weights=allow_negative,
        )
    except TypeError:
        # 兼容移植环境：旧版 RiskConfig 无 max_total_leverage/allow_negative_weights 参数
        return RiskConfig()
