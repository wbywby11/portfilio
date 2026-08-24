"""回测编排服务（自 app/api/backtests.py 平移，P8 治理）.

承接单策略回测编排：配置构造、资产校验、DataFeed 构建、
run_unified 调用、响应组装；模型快捷回测的参数组装、选择器覆盖、
回测记录持久化（含三级兜底）与异常翻译。

依赖方向：本模块只依赖 app.backtesting / app.services / app.schemas，
不 import app.api；组合回测路由（is_portfolio 分支）经 portfolio_runner
回调由路由层注入，避免 services → api 反向依赖。
"""
import traceback

import pandas as pd
from fastapi import HTTPException

from app.schemas.response import Response
from app.schemas.backtests import (
    BacktestRequest,
    BacktestByModelRequest,
    PortfolioBacktestRequest,
)

# 回测执行核心（配置构造/DataFeed/run_unified/响应组装）拆分至 backtest_execution
from app.services.backtest_execution import _run_backtest_core
from app.services.market_service import MarketService
from app.services.asset_service import AssetService
from app.services.strategy_model_service import StrategyModelService, build_backtest_params
from app.services.backtest_service import BacktestService
import copy as _copy
from app.models.strategy_model import (
    BacktestRecord,
    BacktestResult as ModelBacktestResult,
    EquityPoint,
    ReturnPoint,
    PositionRecord,
    AssetPosition,
    WeightChangePoint
)
from app.services.backtest_helpers import (
    is_manual_strategy as _is_manual_strategy,
    sanitize_dict_for_json as _sanitize_dict_for_json,
    apply_snapshot_aggregation as _apply_snapshot_aggregation,
    ensure_trades_rebalance_labels as _ensure_trades_rebalance_labels,
)










async def run_backtest_by_model_core(
    model_id: str,
    request: BacktestByModelRequest,
    market_service: MarketService,
    asset_service: AssetService,
    portfolio_runner=None,
):
    """
    根据策略模型快捷回测
    
    自动从策略模型中获取：
    - 策略类型（template_code）
    - 策略参数（parameters）
    - 资产池（asset_codes）
    - 调仓频率（rebalance_frequency）
    
    只需指定：
    - 回测日期区间
    - 初始资金（可选）
    
    适用场景：
    - 模型开发后快速验证
    - 模型参数调优
    - 不同时间区间比较
    
    示例：
    ```
    POST /api/v1/backtests/run-by-model/6789abc123def456
    {
        "start_date": "20230101",
        "end_date": "20231231",
        "initial_cash": 5000000
    }
    ```
    """
    try:
        # 1. 获取策略模型
        model_service = StrategyModelService()
        backtest_service = BacktestService(model_service)
        model = await model_service.get_model(model_id)
        
        if not model:
            raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")

        # 投资组合：路由到组合回测端点
        if model.is_portfolio:
            portfolio_req = PortfolioBacktestRequest(
                start_date=request.start_date,
                end_date=request.end_date,
                initial_nav=getattr(request, 'initial_nav', 1000.0),
                rebalance_freq=request.rebalance_freq,
            )
            if portfolio_runner is None:
                raise HTTPException(status_code=500, detail="组合回测路由未注入（portfolio_runner）")
            return await portfolio_runner(model_id, portfolio_req)

        # 2. 从模型生成回测请求（支持参数覆盖）
        overrides = {
            "initial_cash": request.initial_cash,
            "lookback_days": request.lookback_days
        }
        if request.rebalance_freq:
            overrides["rebalance_freq"] = request.rebalance_freq
        if request.commission_rate is not None:
            overrides["commission_rate"] = request.commission_rate
        if request.slippage is not None:
            overrides["slippage"] = request.slippage
        
        request_data = backtest_service.to_backtest_request(
            model=model,
            start_date=request.start_date,
            end_date=request.end_date,
            **overrides
        )
        
        # 检查模型是否启用了资产选择（从数据库直接获取，因为可能不在StrategyModel模型中）
        from bson import ObjectId
        model_data = await model_service.collection.find_one({"_id": ObjectId(model_id)})
        
        model_asset_count = len(model.asset_codes)
        model_asset_set = set(model.asset_codes)
        
        # ========== 统一参数组装（build_backtest_params 合并 allocator + selector + controller） ==========
        # 收集请求级选择器覆盖
        _bt_overrides = {}
        for _k in ("n_momentum", "n_reversal", "reversal_windows", "momentum_windows",
                    "macd_windows", "sharp_windows", "tie_break_window", "min_history_days",
                    "asset_selection_count", "selector_type", "enable_momentum_selection"):
            _v = getattr(request, _k, None)
            if _v is not None:
                _bt_overrides[_k] = _v
        if request.enable_vol_reset is not None:
            _bt_overrides["enable_vol_reset"] = request.enable_vol_reset
        if request.vol_reset_threshold is not None:
            _bt_overrides["vol_reset_threshold"] = float(request.vol_reset_threshold)

        # 调用统一组装函数
        unified_params = build_backtest_params(
            model=model, overrides=_bt_overrides, model_data=model_data,
        )
        request_data["strategy_params"] = unified_params

        # ========== 请求级特殊处理：手动资产选择 ==========
        raw_selector_for_manual = (
            request.selector_type or (model_data and model_data.get("selector_type")) or "sharpe"
        )
        is_hybrid = raw_selector_for_manual in ("reversal", "momentum_reversal", "hybrid")

        if request.selected_asset_codes is not None and len(request.selected_asset_codes) > 0:
            selected_codes = request.selected_asset_codes
            n_selected = len(selected_codes)

            invalid_codes = [c for c in selected_codes if c not in model_asset_set]
            if invalid_codes:
                raise HTTPException(
                    status_code=400,
                    detail=f"以下资产不在模型资产池中：{', '.join(invalid_codes)}。模型资产池：{', '.join(model.asset_codes)}"
                )

            if is_hybrid:
                # 混合动量：手动选择作为候选池，强制 momentum_reversal
                request_data["thscodes"] = selected_codes
                unified_params["enable_momentum_selection"] = True
                unified_params["selector_type"] = "momentum_reversal"
                n_mom = int(_bt_overrides.get("n_momentum") or (model_data and model_data.get("n_momentum")) or 7)
                n_rev = int(_bt_overrides.get("n_reversal") or (model_data and model_data.get("n_reversal")) or 1)
                unified_params["n_momentum"] = n_mom
                unified_params["n_reversal"] = n_rev
                unified_params["asset_selection_count"] = n_mom + n_rev
            else:
                if request.asset_selection_count is not None:
                    expected = int(request.asset_selection_count)
                    if n_selected != expected:
                        raise HTTPException(
                            status_code=400,
                            detail=f"选择资产数量（{expected}）与实际勾选的资产数量（{n_selected}）不一致，请检查。"
                        )
                request_data["thscodes"] = selected_codes
                unified_params["enable_momentum_selection"] = False
                unified_params["asset_selection_count"] = n_selected
        else:
            # ========== 未手动选择资产时的选择器逻辑 ==========
            use_frontend_count = request.asset_selection_count is not None

            if use_frontend_count:
                n_assets = int(request.asset_selection_count)
                if n_assets < 1:
                    raise HTTPException(status_code=400, detail="选择资产数量必须大于 0")
                if n_assets > model_asset_count:
                    raise HTTPException(
                        status_code=400,
                        detail=f"选择资产数量（{n_assets}）不能大于模型资产池数量（{model_asset_count}）。请调整前端「选择资产数量」或模型资产配置。"
                    )

            enable_selection = bool(
                request.enable_momentum_selection is True
                or use_frontend_count
                or (request.selector_type is not None or request.min_history_days is not None
                    or request.momentum_windows is not None or request.tie_break_window is not None)
                or (model_data and model_data.get("enable_momentum_selection", False))
            )

            if enable_selection:
                unified_params["enable_momentum_selection"] = True
                raw_selector_type = (
                    request.selector_type
                    or (model_data and model_data.get("selector_type")) or "sharpe"
                )
                if raw_selector_type in ("reversal", "momentum_reversal", "hybrid"):
                    unified_params["selector_type"] = "momentum_reversal"
                    n_momentum = int(
                        request.n_momentum if request.n_momentum is not None
                        else ((model_data and model_data.get("n_momentum")) or 7)
                    )
                    n_reversal = int(
                        request.n_reversal if request.n_reversal is not None
                        else ((model_data and model_data.get("n_reversal")) or 1)
                    )
                    unified_params["n_momentum"] = n_momentum
                    unified_params["n_reversal"] = n_reversal
                    n_from_request = int(request.asset_selection_count) if request.asset_selection_count is not None else None
                    n_from_model = model_data.get("asset_selection_count") if model_data else None
                    if n_from_request is not None:
                        n_selected = n_from_request
                    elif n_from_model is not None:
                        n_selected = int(n_from_model)
                    else:
                        n_selected = min(n_momentum + n_reversal, model_asset_count)
                    unified_params["asset_selection_count"] = n_selected
                else:
                    unified_params["selector_type"] = raw_selector_type
                    n_from_request = int(request.asset_selection_count) if request.asset_selection_count is not None else None
                    n_from_model = model_data.get("asset_selection_count") if model_data else None
                    if n_from_request is not None:
                        n_selected = n_from_request
                    elif n_from_model is not None:
                        n_selected = int(n_from_model)
                    else:
                        template_code = getattr(model, "template_code", None) or (model_data.get("template_code") if model_data else None)
                        n_selected = min(8, model_asset_count) if template_code in ("vol_scaled_budget", "risk_budget_target_vol") else model_asset_count
                    unified_params["asset_selection_count"] = n_selected
                if raw_selector_type == "sharpe" and "sharp_windows" not in unified_params:
                    unified_params["sharp_windows"] = (
                        request.sharp_windows or request.momentum_windows
                        or (model_data and model_data.get("sharp_windows"))
                        or (model_data and model_data.get("momentum_windows"))
                        or "22,65,260"
                    )
                if raw_selector_type not in ("reversal", "momentum_reversal", "hybrid") and model_data and model_data.get("n_assets_for_allocation") is not None:
                    unified_params["n_assets_for_allocation"] = int(model_data["n_assets_for_allocation"])

        # ========== 请求级特殊处理：手动权重 / 杠杆 ==========
        strategy_type_unified = request_data.get("strategy_type") or ""

        # 交互式权重调整（仅 manual_allocation 策略）
        if request.manual_weight_adjustments is not None and len(request.manual_weight_adjustments) > 0:
            request_data["manual_weight_adjustments"] = request.manual_weight_adjustments
        elif _is_manual_strategy(strategy_type_unified):
            _sp_mwa = unified_params.get("manual_weight_adjustments")
            if _sp_mwa:
                if isinstance(_sp_mwa, str):
                    import json as _json
                    try:
                        _sp_mwa = _json.loads(_sp_mwa) if _sp_mwa.strip() else []
                    except Exception:
                        _sp_mwa = []
                if isinstance(_sp_mwa, list) and len(_sp_mwa) > 0:
                    request_data["manual_weight_adjustments"] = _sp_mwa

        # 默认权重覆盖
        if request.manual_weights is not None and len(request.manual_weights) > 0:
            unified_params["manual_weights"] = dict(request.manual_weights)

        # 杠杆倍数限制
        if getattr(request, "max_leverage", None) is not None:
            try:
                lev = float(request.max_leverage)
                if lev >= 1:
                    unified_params["max_leverage"] = lev
            except (TypeError, ValueError):
                pass

        # ========== 参数快照：在所有注入完成后、构造 BacktestRequest 前捕获 ==========
        _param_snapshot = _copy.deepcopy(unified_params)

        # 4. 构造 BacktestRequest
        backtest_request = BacktestRequest(**request_data)
        
        # 5. 执行回测
        try:
            result = await _run_backtest_core(backtest_request, market_service, asset_service)
        except HTTPException as he:
            # 原样重新抛出，保证客户端收到正确的 4xx 状态码（如 400 无法获取行情数据）
            raise he
        except Exception as e:
            # 包装 _run_backtest_core 的错误，提供更多上下文
            error_type = type(e).__name__
            error_msg = str(e)
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=(
                    f"回测引擎执行失败 ({error_type}): {error_msg}\n\n"
                    f"策略模型: {model.name} ({model.template_code})\n"
                    f"资产池: {', '.join(model.asset_codes)}\n"
                    f"日期范围: {request.start_date} 至 {request.end_date}\n\n"
                    f"请检查策略参数配置和资产数据。"
                )
            )
        
        # 5. 保存回测记录
        if result.code == 200 and result.data:
            try:
                backtest_data = result.data
                # run_backtest 返回的 data 为 dict（model_dump），需兼容
                snapshots = backtest_data.get("snapshots", []) if isinstance(backtest_data, dict) else getattr(backtest_data, "snapshots", [])

                def _get(obj, key, default=None):
                    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

                if snapshots:
                    initial_val = _get(snapshots[0], "total_value") or request.initial_cash
                    asset_names_map = _get(backtest_data, "asset_names") or {}

                    # 转换净值曲线
                    equity_curve = [
                        EquityPoint(
                            date=_get(s, "time"),
                            value=_get(s, "total_value"),
                            unit_value=(_get(s, "total_value") or 0) / initial_val if initial_val != 0 else 1.0,
                            cumulative_return=((_get(s, "total_value") or 0) / initial_val - 1) if initial_val != 0 else 0.0,
                            portfolio_volatility=_get(s, "portfolio_volatility"),
                            drawdown=_get(s, "drawdown"),
                            rebalance_type=_get(s, "rebalance_type")
                        )
                        for s in snapshots
                    ]

                    # 转换收益率曲线
                    return_curve = [
                        ReturnPoint(
                            date=_get(s, "time"),
                            daily_return=0.0,
                            cumulative_return=((_get(s, "total_value") or 0) / initial_val - 1) if initial_val != 0 else 0.0
                        )
                        for s in snapshots
                    ]

                    # 转换持仓记录 (只记录调仓日)
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
                                    market_value=(_get(s, "total_value") or 0) * weight
                                )
                                for code, weight in (_get(s, "weights") or {}).items()
                            ]
                        )
                        for s in snapshots if _get(s, "is_rebalance_day")
                    ]

                    # 权重变化记录
                    weight_changes = [
                        WeightChangePoint(
                            date=(_get(s, "time").strftime('%Y-%m-%d') if hasattr(_get(s, "time"), "strftime") else str(_get(s, "time"))[:10]),
                            weights=_get(s, "weights") or {}
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
                        selected_asset_count=_get(backtest_data, "selected_asset_count")
                    )
                    
                    # 转换日期格式
                    start_dt = pd.to_datetime(request.start_date)
                    end_dt = pd.to_datetime(request.end_date)
                    
                    backtest_record = BacktestRecord(
                        model_id=model_id,
                        start_date=start_dt,
                        end_date=end_dt,
                        initial_capital=request.initial_cash,
                        result=model_result,
                        remark=getattr(request, "remark", None) or None
                    )
                    
                    record_id = await backtest_service.save_backtest_record(
                        backtest_record,
                        param_snapshot=_param_snapshot,
                    )
                    # 在响应中返回 record_id 与 remark，便于前端在回测结果区展示分析与记录笔记
                    result_data = result.data.model_dump() if hasattr(result.data, "model_dump") else (result.data if isinstance(result.data, dict) else {})
                    if isinstance(result_data, dict):
                        _ensure_trades_rebalance_labels(result_data)
                        result_data["record_id"] = str(record_id)
                        result_data["remark"] = getattr(request, "remark", None) or ""
                        result_data = _sanitize_dict_for_json(result_data)
                        _apply_snapshot_aggregation(result_data)
                        print(f"[BacktestRecord] 回测记录已保存 model_id={model_id} record_id={record_id} 响应payload_keys={list(result_data.keys())[:15]}")
                        return Response.success(data=result_data, message="回测完成")
                else:
                    # 无 snapshots 时也保存一条最小记录，保证前端始终有 record_id 可编辑备注
                    start_dt = pd.to_datetime(request.start_date)
                    end_dt = pd.to_datetime(request.end_date)
                    _bd = result.data
                    model_result = ModelBacktestResult(
                        total_return=_get(_bd, "total_return", 0.0) or 0.0,
                        annual_return=_get(_bd, "annual_return", 0.0) or 0.0,
                        annual_volatility=_get(_bd, "volatility", 0.0) or 0.0,
                        sharpe_ratio=_get(_bd, "sharpe_ratio", 0.0) or 0.0,
                        max_drawdown=_get(_bd, "max_drawdown", 0.0) or 0.0,
                        calmar_ratio=_get(_bd, "calmar_ratio", None),
                        win_rate=_get(_bd, "win_rate"),
                        equity_curve=[],
                        return_curve=[],
                        positions=[],
                        weight_changes=[],
                        asset_names=_get(_bd, "asset_names"),
                        selected_asset_count=_get(_bd, "selected_asset_count"),
                    )
                    backtest_record = BacktestRecord(
                        model_id=model_id,
                        start_date=start_dt,
                        end_date=end_dt,
                        initial_capital=request.initial_cash,
                        result=model_result,
                        remark=getattr(request, "remark", None) or None,
                    )
                    record_id = await backtest_service.save_backtest_record(
                        backtest_record,
                        param_snapshot=_param_snapshot,
                    )
                    result_data = result.data.model_dump() if hasattr(result.data, "model_dump") else (result.data if isinstance(result.data, dict) else {})
                    if isinstance(result_data, dict):
                        _ensure_trades_rebalance_labels(result_data)
                        result_data["record_id"] = str(record_id)
                        result_data["remark"] = getattr(request, "remark", None) or ""
                        result_data = _sanitize_dict_for_json(result_data)
                        _apply_snapshot_aggregation(result_data)
                        print(f"[BacktestRecord] 无snapshots时已保存最小记录 model_id={model_id} record_id={record_id}")
                        return Response.success(data=result_data, message="回测完成")
            except Exception as e:
                # 保存失败时尝试保存一条最小记录，保证前端有关联的 record_id 可编辑备注
                print(f"保存回测记录失败: {str(e)}")
                _out = result.data.model_dump() if hasattr(result.data, "model_dump") else (result.data if isinstance(result.data, dict) else {})
                if isinstance(_out, dict):
                    _ensure_trades_rebalance_labels(_out)
                    _record_id = None
                    try:
                        start_dt = pd.to_datetime(request.start_date)
                        end_dt = pd.to_datetime(request.end_date)
                        _bd = result.data
                        _g = lambda o, k, d=None: o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)
                        minimal_result = ModelBacktestResult(
                            total_return=_g(_bd, "total_return", 0.0) or 0.0,
                            annual_return=_g(_bd, "annual_return", 0.0) or 0.0,
                            annual_volatility=_g(_bd, "volatility", 0.0) or 0.0,
                            sharpe_ratio=_g(_bd, "sharpe_ratio", 0.0) or 0.0,
                            max_drawdown=_g(_bd, "max_drawdown", 0.0) or 0.0,
                            calmar_ratio=_g(_bd, "calmar_ratio", None),
                            win_rate=_g(_bd, "win_rate"),
                            equity_curve=[],
                            return_curve=[],
                            positions=[],
                            weight_changes=[],
                            asset_names=_g(_bd, "asset_names"),
                            selected_asset_count=_g(_bd, "selected_asset_count"),
                        )
                        minimal_record = BacktestRecord(
                            model_id=model_id,
                            start_date=start_dt,
                            end_date=end_dt,
                            initial_capital=request.initial_cash,
                            result=minimal_result,
                            remark=getattr(request, "remark", None) or None,
                        )
                        _record_id = await backtest_service.save_backtest_record(
                            minimal_record,
                            param_snapshot=_param_snapshot,
                        )
                        _record_id = str(_record_id) if _record_id else None
                    except Exception as e2:
                        print(f"保存最小回测记录也失败: {str(e2)}")
                    _out["record_id"] = _record_id
                    _out["remark"] = getattr(request, "remark", None) or ""
                    _out = _sanitize_dict_for_json(_out)
                    _apply_snapshot_aggregation(_out)
                    print(f"[BacktestRecord] 保存失败后尝试最小记录 model_id={model_id} record_id={_record_id}")
                    return Response.success(data=_out, message="回测完成")
        # 无 snapshot 或 result 结构不同时，统一返回带 record_id 的 payload，避免前端“未关联回测记录”
        if result and getattr(result, "data", None) is not None:
            result_data = result.data.model_dump() if hasattr(result.data, "model_dump") else (result.data if isinstance(result.data, dict) else {})
            if isinstance(result_data, dict):
                _ensure_trades_rebalance_labels(result_data)
                result_data["record_id"] = None
                result_data["remark"] = getattr(request, "remark", None) or ""
                result_data = _sanitize_dict_for_json(result_data)
                _apply_snapshot_aggregation(result_data)
                print(f"[BacktestRecord] 无snapshot/result分支返回 record_id=None")
                return Response.success(data=result_data, message="回测完成")
        return result
        
    except HTTPException as he:
        raise he
    except ValueError as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"参数错误: {str(e)}")
    except KeyError as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=400, 
            detail=f"策略配置错误: 缺少必需的参数或字段 - {str(e)}"
        )
    except AttributeError as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"策略执行错误: {str(e)}。可能是策略参数配置不正确或策略类实现有问题。"
        )
    except Exception as e:
        traceback.print_exc()
        error_type = type(e).__name__
        error_msg = str(e)
        
        # 提供更详细的错误信息
        detail_msg = (
            f"回测执行失败 ({error_type}): {error_msg}\n\n"
            f"可能的原因：\n"
            f"1. 策略参数配置错误\n"
            f"2. 策略算法实现问题\n"
            f"3. 数据格式不匹配\n"
            f"4. 内存不足或计算超时\n\n"
            f"请检查：\n"
            f"- 策略模型的参数配置是否正确\n"
            f"- 资产代码和日期范围是否有效\n"
            f"- 后端日志中的详细错误堆栈"
        )
        
        raise HTTPException(status_code=500, detail=detail_msg)
