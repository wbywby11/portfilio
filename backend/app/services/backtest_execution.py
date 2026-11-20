"""单策略回测执行核心（自 app/api/backtests.py 平移，P8 治理）.

承接回测执行链路：配置构造、主观策略校验、资产校验、DataFeed 构建、
run_unified 调用、响应组装与异常翻译；
以及快照/交易序列化与风控配置推导（单策略与组合子策略共用）。
"""
from typing import Any, Callable, Dict, Optional
import asyncio
import logging
import traceback

import pandas as pd
from fastapi import HTTPException

from app.schemas.response import Response
from app.schemas.backtests import BacktestRequest, SnapshotOut, TradeOut, BacktestResultOut
from app.services.market_service import MarketService
from app.services.asset_service import AssetService
from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed, resolve_lookback_days
from app.allocation.services.registry import create_strategy_service_from_database
from app.analysis.formulas.drawdown import calculate_drawdown_series

from app.services.backtest_helpers import (
    sanitize_dict_for_json as _sanitize_dict_for_json,
    apply_snapshot_aggregation as _apply_snapshot_aggregation,
    rebalance_label_for_trade as _rebalance_label_for_trade,
)

logger = logging.getLogger(__name__)


async def _run_backtest_core(
    request: BacktestRequest,
    market_service: MarketService,
    asset_service: AssetService,
    digest_sink: Optional[Dict[str, Any]] = None,
    progress_cb: Optional[Callable[[int, int, Any], None]] = None,
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
    - ``progress_cb`` 为引擎逐日同步回调 ``(done, total, bar_time)``，为空时不上报
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
        _preset_warnings: list = []

        # 主观策略仅按预设日期调仓：期初权重（manual_weights）与预设调仓日相互独立，
        # 配置了期初权重时可无任何预设调仓日（全周期持有初始权重，不触发调仓）
        if strategy_type in ("manual_allocation", "manual_allocation_strategy"):
            config.rebalance_only_on_preset_dates = True
            sp = getattr(request, "strategy_params", None) or {}
            max_leverage = float(sp.get("max_leverage", 4))
            if max_leverage < 1:
                max_leverage = 4
            # 期初建仓：使用策略默认权重（或本次回测覆盖的 manual_weights）在首日建仓
            mw = sp.get("manual_weights")
            if isinstance(mw, str):
                # 兼容模型参数以 JSON 字符串存储的历史数据（同 ManualAllocationStrategy.allocate 口径）
                import json
                try:
                    mw = json.loads(mw.replace("'", '"')) if mw.strip() else {}
                except (TypeError, ValueError):
                    raise HTTPException(
                        status_code=400,
                        detail="策略参数 manual_weights 不是合法的权重字典（JSON 解析失败），请检查策略模型的权重初始化配置。",
                    )
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

        # 2. 验证资产代码是否存在
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
        # momentum_reversal (7+1) / min_history_days>=260 需至少 400 日历天预加载（确保 260 交易日 + 缓冲）
        effective_lookback = request.lookback_days
        sp = request.strategy_params or {}
        sel = sp.get("selection_info") or sp
        if (
            sel.get("selector_type") == "momentum_reversal"
            or int(sp.get("min_history_days") or 0) >= 260
        ):
            effective_lookback = max(effective_lookback, 400)
        # 长窗口策略（如 756 日协方差、250 日 AR 链）声明的是交易日，
        # 统一按 min_history_days 放大预加载天数，避免首段调仓拿到不足历史；
        # 传入 strategy_type 使模板声明的默认值对存量模型同样生效
        effective_lookback = resolve_lookback_days(
            sp, effective_lookback, strategy_type=strategy_type
        )
        data_feed = await DataFeed.from_market_service(
            market_service=market_service,
            config=config,
            lookback_days=effective_lookback,
            strategy_type=strategy_type,
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
        
        # 预设调仓日与回测区间取交集：区间外/非交易日的调仓日自动忽略，不阻断回测
        if config.manual_weight_adjustments:
            start_ymd = str(request.start_date).replace("-", "")[:8]
            end_ymd = str(request.end_date).replace("-", "")[:8]
            trading_days = set(pd.Series(data_feed.prices.index).dt.strftime("%Y%m%d").astype(str).tolist())
            effective_adjustments = {}
            ignored_preset = []
            for d, adj in config.manual_weight_adjustments.items():
                if d < start_ymd or d > end_ymd or d not in trading_days:
                    ignored_preset.append(d)
                else:
                    effective_adjustments[d] = adj
            if ignored_preset:
                ignored_msg = (
                    f"以下预设调仓日不在回测区间 [{start_ymd}, {end_ymd}] 内或非交易日，已自动忽略："
                    f"{', '.join(sorted(ignored_preset))}"
                )
                logger.warning("[回测] %s", ignored_msg)
                _preset_warnings.append(ignored_msg)
            config.manual_weight_adjustments = effective_adjustments or None
            # 期初建仓归一化开关跟随区间内最早的预设调仓日；无生效调仓日时不归一化
            config.initial_weights_auto_normalize = (
                effective_adjustments[min(effective_adjustments)].get("auto_normalize", False)
                if effective_adjustments else False
            )

        # 主观策略权重来源校验：期初权重与区间内预设调仓日至少需其一
        if strategy_type in ("manual_allocation", "manual_allocation_strategy"):
            _init_weight_sum = sum(
                float(v or 0) for v in (config.initial_weights or {}).values()
            )
            if _init_weight_sum <= 0 and not config.manual_weight_adjustments:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "主观配置策略未配置任何持仓权重：请在「权重初始化」中填写资产权重，"
                        "或设置至少一个回测区间内的调仓日。"
                    ),
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

        # 3.5 可复现性摘要（S10）：只算不落库，经 digest_sink 交给调用方随记录写入。
        # 用保真矩阵 strategy_prices（未 ffill / 未清洗）而非 prices：在清洗后的
        # 矩阵上取摘要，无法区分「原始数据」与「被前值填充过的数据」。
        # 区间取回测区间，不含 lookback（预热段不属于本次结果的一部分）。
        if digest_sink is not None:
            try:
                from app.services.strategy_fingerprint import data_digest_v2, pool_hash
                from app.services.strategy_version_service import resolve_contract_hash

                digest_sink["data_digest_v2"] = data_digest_v2(
                    getattr(data_feed, "strategy_prices", None),
                    start_date=request.start_date,
                    end_date=request.end_date,
                )
                digest_sink["asset_pool_hash"] = pool_hash(request.thscodes)
                digest_sink["contract_hash"] = resolve_contract_hash(strategy_type)
            except Exception as exc:  # noqa: BLE001 —— 摘要失败不得影响回测
                logger.warning("[fingerprint] 摘要计算失败（回测继续）: %s", exc)

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
        run_spec = RunSpec(
            config=config,
            data_feed=data_feed,
            allocator=strategy_impl,
            thscodes=request.thscodes,
            composition=composition,
            strategy_params=request.strategy_params,
            # 支持最大杠杆>1 时权重和大于1，不强制归一化为和1
            risk_config=_build_risk_config(request.strategy_params),
            progress_cb=progress_cb,
        )
        try:
            # 引擎是同步 CPU 密集计算（逐日撮合），必须放到工作线程：
            # 直接调用会冻结 asyncio 事件循环，期间进度轮询与其它 API 全部挂起，
            # 前端表现为进度条不动（与组合子策略回测同一口径）。
            result = await asyncio.to_thread(run_unified, run_spec)
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
            annual_return_365=performance.annual_return_365,
            volatility_365=performance.annual_volatility_365,
            sharpe_ratio_365=performance.sharpe_ratio_365,
            calmar_ratio_365=performance.calmar_ratio_365,
            win_rate=performance.win_rate,
            n_trades=performance.n_trades,
            total_commission=performance.total_commission,
            total_slippage=performance.total_slippage,
            turnover=performance.turnover,
            warnings=list(performance.warnings) + _preset_warnings,
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
    """从策略参数推导风控配置（保留别名，实现在子策略执行器）。

    单策略回测、组合子策略、组合监控三条通道共用一个实现，避免
    max_total_leverage / weight_caps / allow_short 的解析口径分叉。
    """
    from app.services.single_strategy_executor import build_risk_config

    return build_risk_config(strategy_params)
