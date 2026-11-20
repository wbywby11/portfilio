"""回测服务API - 基于新的 BacktestEngine"""
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio
import logging

logger = logging.getLogger(__name__)

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from bson import ObjectId
from app.schemas.strategy_model import BacktestRecordOut

from app.schemas.response import Response
from app.services.market_service import MarketService
from app.services.asset_service import AssetService
from app.services.published_snapshot import apply_published_snapshot
from app.services.strategy_model_service import StrategyModelService
from app.models.strategy_model import ModelStatus
from app.services.backtest_service import BacktestService
from app.backtesting.analytics import compute_paused_metrics

router = APIRouter()

#: 进度任务号：前端生成 uuid 并并行轮询 ``GET /monitor/tasks/{task_id}``；
#: 为空时不建进度文档，端点行为与接入前完全一致
_PROGRESS_KEY_QUERY = Query(
    None,
    description="进度任务号（前端生成的 uuid，同时作为轮询用的 task_id）；为空时不上报进度",
    max_length=64,
)


# ==================== 从 backtest_helpers 导入公共辅助函数 ====================
from app.services.backtest_helpers import (
    sanitize_dict_for_json as _sanitize_dict_for_json,
)

# ==================== 请求/响应模型与编排服务（P8 治理后位置） ====================
# schemas 平移至 app/schemas/backtests.py；单策略回测编排平移至
# app/services/backtest_orchestration.py。带 noqa: F401 的为再导出，兼容
# monitor/scripts/regression 既有的 from app.api.backtests import ... 导入面。
from app.schemas.backtests import (
    BacktestRequest,  # noqa: F401  (scripts/regen_snowball_record.py)
    BacktestResultOut,
    ComputeMetricsFromSnapshotsRequest,
    BacktestByModelRequest,  # noqa: F401  (tests/regression/chains.py)
    SensitivityRequest,
    ScenarioRequest,
    RobustnessRequest,
    PortfolioReportRequest,
    PortfolioBacktestRequest,  # noqa: F401  (monitor/chains)
    PortfolioBacktestResultOut,
    PortfolioByIdBacktestRequest,  # noqa: F401  (tests/regression/chains.py)
)
from app.services.backtest_orchestration import (
    _run_backtest_core,  # noqa: F401  (scripts/regen_snowball_record.py)
    run_backtest_by_model_core,
)
from app.services.backtest_progress import (
    KIND_PORTFOLIO,
    SINK_KEY,
    close_progress,
    open_progress,
)
from app.services.portfolio_backtest_helpers import (
    _maybe_apply_product_layer,
    _collect_cost_overrides,
    _build_quadrant_weight_components,
    _run_sub_strategy_backtests,
    _build_portfolio_equity_outputs,  # noqa: F401  (monitor 同源链路)
    _build_portfolio_backtest_result,
)


# ==================== 依赖注入 ====================

def get_market_service() -> MarketService:
    """获取行情服务实例"""
    return MarketService()


def get_asset_service() -> AssetService:
    """获取资产服务实例"""
    return AssetService()


def get_model_service() -> StrategyModelService:
    """获取模型服务实例"""
    return StrategyModelService()


def get_backtest_service() -> BacktestService:
    """获取回测记录服务实例"""
    return BacktestService()


def validate_object_id(id_str: str) -> str:
    """验证ObjectId格式"""
    if not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=400,
            detail=f"无效的ID格式: {id_str}, 必须是24位十六进制字符串"
        )
    return id_str


# ==================== API路由 ====================









@router.post("/compute-metrics-from-snapshots", response_model=Response[Dict[str, Any]], summary="基于快照切片计算绩效指标")
async def compute_metrics_from_snapshots(request: ComputeMetricsFromSnapshotsRequest = Body(...)):
    """
    根据已有快照按截止日期切片后计算绩效指标。
    用于基于已有快照数据计算截至某日的绩效指标，与最终净值曲线保持同一数据源。
    """
    cutoff = str(request.cutoff_date).replace("-", "")[:8]
    if not cutoff or len(cutoff) != 8:
        raise HTTPException(status_code=400, detail="cutoff_date 须为 YYYYMMDD 格式")
    sliced = []
    for s in request.snapshots:
        t = s.get("time")
        if t is None:
            continue
        try:
            ts = pd.Timestamp(t)
            ds = ts.strftime("%Y%m%d") if hasattr(ts, "strftime") else str(t).replace("-", "")[:8]
            if ds <= cutoff:
                sliced.append(s)
        except Exception:
            continue
    if not sliced:
        return Response.success(data={
            "total_return": 0.0,
            "annual_return": 0.0,
            "volatility": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "calmar_ratio": 0.0,
        }, message="无有效快照")
    metrics = compute_paused_metrics(sliced, None)
    return Response.success(data={
        "total_return": metrics.get("total_return") or 0.0,
        "annual_return": metrics.get("annual_return") or 0.0,
        "volatility": metrics.get("volatility") or 0.0,
        "max_drawdown": metrics.get("max_drawdown") or 0.0,
        "sharpe_ratio": metrics.get("sharpe_ratio") or 0.0,
        "calmar_ratio": metrics.get("calmar_ratio") or 0.0,
    }, message="ok")


@router.get("/{record_id}", response_model=Response[BacktestRecordOut], summary="获取回测详情")
async def get_backtest_detail(
    record_id: str,
    backtest_service: BacktestService = Depends(get_backtest_service),
    asset_service: AssetService = Depends(get_asset_service)
):
    """
    根据记录ID获取数据库中的回测详情
    """
    validate_object_id(record_id)
    record = await backtest_service.get_backtest_record(record_id)
    
    if not record:
        raise HTTPException(status_code=404, detail=f"回测记录不存在: {record_id}")
        
    # 填充缺失的资产名称（兜底处理）
    if not record.result.asset_names:
        asset_names = {}
        # 从持仓记录中提取资产代码
        codes = set()
        for pos_rec in record.result.positions:
            for pos in pos_rec.positions:
                codes.add(pos.asset_code)
        
        for code in codes:
            info = await asset_service.get_asset_by_code(code)
            if info:
                asset_names[code] = info.name
        record.result.asset_names = asset_names
        
    # 确保每个持仓点都有资产名称
    for pos_rec in record.result.positions:
        for pos in pos_rec.positions:
            if not pos.asset_name:
                pos.asset_name = record.result.asset_names.get(pos.asset_code)

    _data = record.model_dump() if hasattr(record, "model_dump") else record
    return Response.success(data=_sanitize_dict_for_json(_data))




@router.post("/run-by-model/{model_id}", response_model=Response[BacktestResultOut], summary="根据策略模型快捷回测")
async def run_backtest_by_model(
    model_id: str,
    request: BacktestByModelRequest = Body(...),
    progress_key: Optional[str] = _PROGRESS_KEY_QUERY,
    market_service: MarketService = Depends(get_market_service),
    asset_service: AssetService = Depends(get_asset_service),
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
    # 编排主体已下沉 app.services.backtest_orchestration（P8 治理），
    # 组合回测路由（is_portfolio 分支）经 portfolio_runner 注入本文件端点；
    # progress_key 用闭包透传，组合分支的进度文档由组合端点自己建（kind 不同）
    async def _portfolio_runner(mid: str, req):
        return await run_portfolio_backtest_api(mid, req, progress_key=progress_key)

    sink: Dict[str, Any] = {}
    try:
        result = await run_backtest_by_model_core(
            model_id, request, market_service, asset_service,
            portfolio_runner=_portfolio_runner,
            progress_key=progress_key,
            progress_sink=sink,
        )
    except BaseException as exc:  # noqa: BLE001 —— 只为把失败写回进度文档，原样抛出
        await close_progress(sink, exc)
        raise
    await close_progress(sink)
    return result


# ==================== 多维分析 API ====================







@router.post("/sensitivity", response_model=Response[dict], summary="参数敏感度分析")
async def run_sensitivity_analysis(req: SensitivityRequest = Body(...)):
    """参数敏感度分析 — 单参数扫描。
    
    对指定参数在给定值列表中逐一扫描，每次跑一次完整回测，
    输出各参数值对应的绩效指标，供热力图展示。
    """
    from app.services.backtest_analysis_service import BacktestAnalysisService
    service = BacktestAnalysisService()
    try:
        result = await service.sensitivity_analysis(
            model_id=req.model_id,
            param_name=req.param_name,
            param_values=req.param_values,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_cash=req.initial_cash,
        )
        return Response.success(data=result, message="敏感度分析完成")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"敏感度分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"敏感度分析失败: {str(e)}")


@router.post("/scenario", response_model=Response[dict], summary="情景推演")
async def run_scenario_analysis(req: ScenarioRequest = Body(...)):
    """情景推演 — 修改价格矩阵后跑回测。
    
    用户定义各资产的冲击幅度（如“沪深300跌20%”），
    对比基线回测 vs 情景回测的绩效差异。
    """
    from app.services.backtest_analysis_service import BacktestAnalysisService
    service = BacktestAnalysisService()
    try:
        result = await service.scenario_analysis(
            model_id=req.model_id,
            scenario=req.scenario,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_cash=req.initial_cash,
        )
        return Response.success(data=result, message="情景推演完成")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"情景推演失败: {e}")
        raise HTTPException(status_code=500, detail=f"情景推演失败: {str(e)}")


@router.post("/robustness", response_model=Response[dict], summary="鲁棒性检验")
async def run_robustness_check(req: RobustnessRequest = Body(...)):
    """时间窗口鲁棒性检验 — 滑动子区间回测。
    
    将回测区间切分为多个子区间，每个独立跑回测，
    展示绩效指标的稳定性（均值、标准差、箱线图数据）。
    """
    from app.services.backtest_analysis_service import BacktestAnalysisService
    service = BacktestAnalysisService()
    try:
        result = await service.robustness_check(
            model_id=req.model_id,
            n_windows=req.n_windows,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_cash=req.initial_cash,
        )
        return Response.success(data=result, message="鲁棒性检验完成")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"鲁棒性检验失败: {e}")
        raise HTTPException(status_code=500, detail=f"鲁棒性检验失败: {str(e)}")




@router.post("/portfolio-report", response_model=Response[dict], summary="组合评估报告")
async def generate_portfolio_report(
    req: PortfolioReportRequest = Body(...),
    market_service: MarketService = Depends(get_market_service),
):
    """生成组合评估报告（Phase 3: 组合评估能力补全）。
    
    对指定策略模型最近一次回测结果进行全面评估：
    - 基础绩效指标（年化收益/波动/夏普/回撤）
    - 子策略分解（GMSI2等多策略组合）
    - 相关性分析（子策略间分散化效果）
    - 基准对比指标（跟踪误差/信息比率/Beta-Alpha）
    """
    from app.backtesting.portfolio_analytics import compute_portfolio_report
    from app.services.strategy_model_service import StrategyModelService
    
    model_service = StrategyModelService()
    backtest_service = BacktestService(model_service)
    try:
        # 获取最近一次回测记录
        records = await backtest_service.list_backtest_records(req.model_id, skip=0, limit=1)
        if not records:
            raise HTTPException(status_code=400, detail=f"策略 {req.model_id} 尚没有回测记录")
        
        record = records[0]
        bt_result = record.result
        
        # 从回测结果构建净值序列
        if not bt_result.equity_curve:
            raise HTTPException(status_code=400, detail="回测结果中没有净值曲线")
        
        nav_data = []
        for pt in bt_result.equity_curve:
            try:
                d = pd.Timestamp(pt.date)
                uv = float(pt.unit_value or 1.0)
                if pd.notna(d) and uv > 0:
                    nav_data.append({"date": d, "unit_value": uv})
            except (ValueError, TypeError):
                continue
        
        if len(nav_data) < 10:
            raise HTTPException(status_code=400, detail="净值数据点不足")
        
        portfolio_nav = pd.DataFrame(nav_data).set_index("date")["unit_value"]
        
        # 基准净值（如果提供）
        benchmark_nav = None
        if req.benchmark_nav and req.benchmark_dates and len(req.benchmark_nav) == len(req.benchmark_dates):
            benchmark_nav = pd.Series(
                req.benchmark_nav,
                index=pd.to_datetime(req.benchmark_dates),
            )
        
        # 生成报告
        report = compute_portfolio_report(
            portfolio_nav=portfolio_nav,
            benchmark_nav=benchmark_nav,
        )
        
        # 附加回测元信息
        report["model_id"] = req.model_id
        report["model_name"] = (await model_service.get_model(req.model_id)).name if await model_service.get_model(req.model_id) else ""
        report["backtest_start"] = record.start_date.strftime("%Y-%m-%d") if hasattr(record.start_date, "strftime") else str(record.start_date)
        report["backtest_end"] = record.end_date.strftime("%Y-%m-%d") if hasattr(record.end_date, "strftime") else str(record.end_date)
        report["data_points"] = len(nav_data)
        
        return Response.success(data=report, message="组合评估报告生成完成")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"组合评估报告生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"组合评估报告生成失败: {str(e)}")


# ==================== 投资组合回测 ====================







# 四象限权重模型组件组装位于组合层共享构建块（app/portfolio/quadrant_components.py），
# 经 app.services.portfolio_backtest_helpers 统一引用，回测 API 与组合服务
# （绩效/回撤链路）同一组装口径，避免参数断点。


















@router.post("/run-portfolio/{model_id}", response_model=Response[PortfolioBacktestResultOut], summary="投资组合回测")
async def run_portfolio_backtest_api(
    model_id: str,
    request: PortfolioBacktestRequest = Body(...),
    progress_key: Optional[str] = _PROGRESS_KEY_QUERY,
):
    """
    投资组合回测

    将多个独立策略按配置权重在 NAV 层复合，形成投资组合。
    每个子策略独立回测，然后按权重加权合成。

    进度阶段：每个子策略一段 + 组合合成一段（仅 ``progress_key`` 非空时上报）。
    """
    sink: Dict[str, Any] = {}
    try:
        validate_object_id(model_id)
        model_service = get_model_service()
        portfolio_model = await model_service.get_model(model_id)

        if not portfolio_model:
            raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")

        if not portfolio_model.is_portfolio:
            raise HTTPException(status_code=400, detail=f"模型 {model_id} 不是投资组合类型")

        # 已发布组合：成员/权重/权重模型参数统一读发布冻结快照
        if portfolio_model.status == ModelStatus.PUBLISHED and portfolio_model.published_snapshot:
            portfolio_model = apply_published_snapshot(
                portfolio_model, portfolio_model.published_snapshot
            )
        membership = model_service.portfolio_membership(portfolio_model)
        if not membership:
            raise HTTPException(status_code=400, detail="投资组合未配置子策略")

        sub_pairs = await model_service.resolve_sub_strategies(
            portfolio_model, sub_strategies=membership
        )
        if not sub_pairs:
            raise HTTPException(status_code=400, detail="无法解析子策略，请检查配置")

        from app.portfolio.composite_runner import run_composite_unified as composite_run

        # 标准化子策略清单后走共享回测循环
        sub_entries = []
        for sub_model, weight in sub_pairs:
            sub_info = next(
                (s for s in membership if s.get("model_id") == sub_model.id), {}
            )
            sub_entries.append({
                "model": sub_model,
                "weight": weight,
                "name": sub_info.get("name", sub_model.name),
                "fetch_id": sub_model.id or sub_model.name,
                # 子策略独立回测起点（可选，对齐原型子策略自身起点）
                "sub_start": sub_info.get("backtest_start"),
            })

        # 旁路进度：子策略逐个回测各算一段，组合合成再算一段
        _total_steps = len(sub_entries) + 1
        progress = await open_progress(
            progress_key,
            kind=KIND_PORTFOLIO,
            subject_id=model_id,
            subject_name=portfolio_model.name,
            total_steps=_total_steps,
            params={
                "start_date": request.start_date,
                "end_date": request.end_date,
                "sub_strategies": [e["name"] for e in sub_entries],
            },
        )
        sink[SINK_KEY] = progress
        await progress.start(
            f"组合回测启动：{len(sub_entries)} 个子策略待回测"
            f"（{request.start_date} ~ {request.end_date}）"
        )

        async def _on_sub_done(done: int, total: int, message: str) -> None:
            """子策略完成回调：映射为阶段步进（未开进度时内部自动 no-op）."""
            await progress.step(message, index=done)

        (
            sub_nav_series, sub_weights, sub_results_out,
            all_trades, sub_snapshots_by_key,
        ) = await _run_sub_strategy_backtests(
            sub_entries, request.start_date, request.end_date,
            request.initial_nav, model_service,
            cost_overrides=_collect_cost_overrides(request),
            progress_cb=_on_sub_done,
            engine_progress=progress.day_bridge,
        )

        if not sub_nav_series:
            raise HTTPException(status_code=400, detail="所有子策略回测失败，无法构建投资组合")

        # ---- 组合权重模型与事件驱动信号组装（组装层：读配置 → 实例化 → 组装）----
        weight_model = None
        rebalance_signal = None
        composite_exec_schedule = None
        composite_weight_drift = True
        wm_type = getattr(portfolio_model, "weight_model_type", None)
        wm_params = getattr(portfolio_model, "weight_model_params", {}) or {}
        if wm_type == "quadrant":
            weight_model, rebalance_signal, composite_exec_schedule, composite_weight_drift = (
                await _build_quadrant_weight_components(
                    wm_params,
                    request.start_date,
                    request.end_date,
                )
            )

        portfolio_result = await asyncio.to_thread(
            composite_run,
            sub_nav_series=sub_nav_series,
            sub_weights=sub_weights,
            initial_nav=request.initial_nav,
            rebalance_freq=request.rebalance_freq or "monthly",
            mother_vol_target=request.mother_vol_target,
            mother_leverage_min=request.mother_leverage_min,
            mother_leverage_max=request.mother_leverage_max,
            weight_model=weight_model,
            rebalance_signal=rebalance_signal,
            execution_schedule=composite_exec_schedule,
            weight_drift=composite_weight_drift,
            # 母层成本与子策略同一组请求参数，否则母基金层成交只计入零成本
            commission_rate=float(request.commission_rate or 0.0),
            slippage=float(request.slippage or 0.0),
            # 合成引擎同样是逐日撮合，接同一套逐日进度（未开进度时为 None）
            progress_cb=progress.day_bridge(_total_steps, "组合合成"),
        )

        # ---- 产品层（可选）：策略组合 + 短债 + 现金的目标波动率配置 ----
        portfolio_result, product_layer_out = await _maybe_apply_product_layer(
            portfolio_result, wm_params, request.initial_nav,
        )

        result_out = await _build_portfolio_backtest_result(
            portfolio_result, sub_nav_series, sub_weights, sub_results_out,
            all_trades, sub_snapshots_by_key,
            record_model_id=model_id,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_nav=request.initial_nav,
            model_service=model_service,
            product_layer_out=product_layer_out,
        )

        # NOTE: 路径 A 是纯回测端点，model_id 是 strategy_model ID（非 portfolio ID），
        # 不应写入 portfolios 集合（之前用 model_id 查询 portfolios 会导致静默失败或错误覆盖）。
        # 回测记录已通过 save_backtest_record 保存。

        await close_progress(sink)
        return Response.success(
            data=result_out,
            message="投资组合回测完成",
        )

    except HTTPException as he:
        await close_progress(sink, he)
        raise
    except Exception as e:
        await close_progress(sink, e)
        logger.error(f"投资组合回测失败: {e}")
        raise HTTPException(status_code=500, detail=f"投资组合回测失败: {str(e)}")






# （_extract_nav_series 已提取至 backtest_helpers）


# ============================================================
# 组合回测（根据 Portfolio ID）
# ============================================================



@router.post("/run-portfolio-by-id/{portfolio_id}", response_model=Response[PortfolioBacktestResultOut], summary="根据组合ID执行回测")
async def run_portfolio_backtest_by_id(
    portfolio_id: str,
    request: PortfolioByIdBacktestRequest = Body(...),
    progress_key: Optional[str] = _PROGRESS_KEY_QUERY,
):
    """
    根据组合ID（portfolios集合）执行组合回测。

    从portfolios集合中获取组合配置（子策略列表和权重），然后执行组合回测。

    进度阶段：每个子策略一段 + 组合合成一段（仅 ``progress_key`` 非空时上报）。
    """
    sink: Dict[str, Any] = {}
    try:
        validate_object_id(portfolio_id)
        
        # 获取组合服务
        from app.portfolio.portfolio_service import PortfolioService
        portfolio_service = PortfolioService()
        
        # 获取组合
        portfolio = await portfolio_service.get_portfolio(portfolio_id)
        if not portfolio:
            raise HTTPException(status_code=404, detail=f"组合不存在: {portfolio_id}")

        # 获取策略模型服务
        model_service = get_model_service()

        # 已发布组合：成员/权重/权重模型参数读组合模型发布快照
        from app.models.strategy_model import ModelStatus

        linked_model = None
        published_config = None
        if getattr(portfolio, "portfolio_model_id", None):
            linked_model = await model_service.get_model(str(portfolio.portfolio_model_id))
        if linked_model and linked_model.status == ModelStatus.PUBLISHED:
            if not linked_model.published_snapshot:
                raise HTTPException(status_code=400, detail="组合缺少发布快照，请重新发布后再回测")
            published_config = apply_published_snapshot(
                linked_model, linked_model.published_snapshot
            )
            membership = model_service.portfolio_membership(published_config)
            sub_pairs = await model_service.resolve_sub_strategies(
                published_config, sub_strategies=membership
            )
        else:
            # 草稿组合：成员/权重读组合文档；子策略仍只读各自发布快照
            membership = [s.dict() for s in portfolio.sub_strategies]
            sub_pairs = []
            for sub_alloc in portfolio.sub_strategies:
                sub_model = await model_service.get_model(sub_alloc.model_id)
                if not sub_model:
                    logger.warning(f"子策略模型不存在: {sub_alloc.model_id}")
                    continue
                if sub_model.status != ModelStatus.PUBLISHED or not sub_model.published_snapshot:
                    raise HTTPException(
                        status_code=400,
                        detail=f"子策略「{sub_model.name}」未发布或缺少发布快照，请重新发布后再运行组合",
                    )
                sub_pairs.append((
                    apply_published_snapshot(sub_model, sub_model.published_snapshot),
                    sub_alloc.weight,
                ))

        if not sub_pairs:
            raise HTTPException(status_code=400, detail="组合未配置可用的子策略")

        from app.portfolio.composite_runner import run_composite_unified as composite_run

        # 标准化子策略清单后走共享回测循环
        sub_entries = []
        for sub_model, weight in sub_pairs:
            sub_info = next(
                (s for s in membership if s.get("model_id") == sub_model.id), {}
            )
            sub_entries.append({
                "model": sub_model,
                "weight": weight,
                "name": sub_info.get("name") or sub_model.name,
                "fetch_id": sub_model.id or sub_model.name,
                "sub_start": sub_info.get("backtest_start"),
            })

        # 旁路进度：子策略逐个回测各算一段，组合合成再算一段
        _total_steps = len(sub_entries) + 1
        progress = await open_progress(
            progress_key,
            kind=KIND_PORTFOLIO,
            subject_id=portfolio_id,
            subject_name=getattr(portfolio, "name", "") or "",
            total_steps=_total_steps,
            params={
                "start_date": request.start_date,
                "end_date": request.end_date,
                "sub_strategies": [e["name"] for e in sub_entries],
            },
        )
        sink[SINK_KEY] = progress
        await progress.start(
            f"组合回测启动：{len(sub_entries)} 个子策略待回测"
            f"（{request.start_date} ~ {request.end_date}）"
        )

        async def _on_sub_done(done: int, total: int, message: str) -> None:
            """子策略完成回调：映射为阶段步进（未开进度时内部自动 no-op）."""
            await progress.step(message, index=done)

        (
            sub_nav_series, sub_weights, sub_results_out,
            all_trades, sub_snapshots_by_key,
        ) = await _run_sub_strategy_backtests(
            sub_entries, request.start_date, request.end_date,
            request.initial_nav, model_service,
            cost_overrides=_collect_cost_overrides(request),
            progress_cb=_on_sub_done,
            engine_progress=progress.day_bridge,
        )

        if not sub_nav_series:
            raise HTTPException(status_code=400, detail="所有子策略回测失败，无法执行组合回测")

        # ---- 组合权重模型与事件驱动信号组装（组装层）----
        weight_model = None
        rebalance_signal = None
        composite_exec_schedule = None
        composite_weight_drift = True
        wm_params = (
            published_config.weight_model_params
            if published_config is not None
            else portfolio.weight_model_params
        ) or {}
        wm_type = (
            published_config.weight_model_type
            if published_config is not None
            else portfolio.weight_method
        )
        rebalance_freq = (
            published_config.rebalance_frequency
            if published_config is not None and published_config.rebalance_frequency
            else request.rebalance_freq
        )
        if wm_type == "quadrant":
            weight_model, rebalance_signal, composite_exec_schedule, composite_weight_drift = (
                await _build_quadrant_weight_components(
                    wm_params,
                    request.start_date,
                    request.end_date,
                )
            )

        # 执行组合回测：请求未显式指定时回退到组合文档的波动率配置
        portfolio_result = await asyncio.to_thread(
            composite_run,
            sub_nav_series=sub_nav_series,
            sub_weights=sub_weights,
            initial_nav=request.initial_nav,
            rebalance_freq=rebalance_freq,
            mother_vol_target=(
                request.mother_vol_target
                if request.mother_vol_target is not None
                else portfolio.vol_target
            ),
            mother_vol_short=portfolio.vol_lookback_short or 20,
            mother_vol_long=portfolio.vol_lookback_long or 60,
            mother_vol_method=portfolio.vol_method or "rolling",
            mother_annualize_factor=portfolio.vol_annualize_factor,
            mother_leverage_min=(
                request.mother_leverage_min
                if request.mother_leverage_min is not None
                else portfolio.vol_leverage_min
            ),
            mother_leverage_max=(
                request.mother_leverage_max
                if request.mother_leverage_max is not None
                else portfolio.vol_leverage_max
            ),
            weight_model=weight_model,
            rebalance_signal=rebalance_signal,
            execution_schedule=composite_exec_schedule,
            weight_drift=composite_weight_drift,
            # 母层成本与子策略同一组请求参数，否则母基金层成交只计入零成本
            commission_rate=float(request.commission_rate or 0.0),
            slippage=float(request.slippage or 0.0),
            # 合成引擎同样是逐日撮合，接同一套逐日进度（未开进度时为 None）
            progress_cb=progress.day_bridge(_total_steps, "组合合成"),
        )

        # ---- 产品层（可选）：策略组合 + 短债 + 现金的目标波动率配置 ----
        portfolio_result, product_layer_out = await _maybe_apply_product_layer(
            portfolio_result, wm_params, request.initial_nav,
        )

        result_out = await _build_portfolio_backtest_result(
            portfolio_result, sub_nav_series, sub_weights, sub_results_out,
            all_trades, sub_snapshots_by_key,
            record_model_id=portfolio_id,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_nav=request.initial_nav,
            model_service=model_service,
            product_layer_out=product_layer_out,
        )
        perf = portfolio_result.performance
        backtest_record_id = result_out.backtest_record_id

        # 同步更新组合文档的 performance + latest_backtest_summary（独立于回测记录保存）
        try:
            from bson import ObjectId as _Oid
            from app.config.database import Database
            db = Database.get_database()
            summary = {
                "annual_return": float(perf.annual_return) if perf.annual_return else 0.0,
                "annual_vol": float(perf.annual_volatility) if perf.annual_volatility else 0.0,
                "sharpe": float(perf.sharpe_ratio) if perf.sharpe_ratio else 0.0,
                "max_drawdown": float(perf.max_drawdown) if perf.max_drawdown else 0.0,
                "annual_return_365": float(getattr(perf, "annual_return_365", 0.0) or 0.0),
                "annual_vol_365": float(getattr(perf, "annual_volatility_365", 0.0) or 0.0),
                "sharpe_365": float(getattr(perf, "sharpe_ratio_365", 0.0) or 0.0),
                "total_return": float(perf.total_return) if perf.total_return else 0.0,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "backtest_date": datetime.now().isoformat(),
                "record_id": backtest_record_id,
            }
            import math as _math
            for k, v in list(summary.items()):
                if isinstance(v, float) and (_math.isnan(v) or _math.isinf(v)):
                    summary[k] = None
            await db.portfolios.update_one(
                {"_id": _Oid(portfolio_id)},
                {"$set": {
                    "latest_backtest_summary": summary,
                    "performance": {
                        "total_return": summary["total_return"],
                        "annual_return": summary["annual_return"],
                        "annual_volatility": summary["annual_vol"],
                        "sharpe_ratio": summary["sharpe"],
                        "max_drawdown": summary["max_drawdown"],
                        "annual_return_365": summary["annual_return_365"],
                        "annual_volatility_365": summary["annual_vol_365"],
                        "sharpe_ratio_365": summary["sharpe_365"],
                        "latest_unit_value": round(float(portfolio_result.portfolio_nav.iloc[-1]), 4) if len(portfolio_result.portfolio_nav) > 0 else 1.0,
                    },
                    "updated_at": datetime.now(),
                }}
            )
            logger.info(f"[by-id] 组合回测摘要已写入 portfolios: {portfolio_id}")
        except Exception as update_err:
            logger.warning(f"[by-id] 更新组合回测摘要失败（不影响返回）: {update_err}")

        await close_progress(sink)
        return Response.success(
            data=result_out,
            message="组合回测完成",
        )

    except HTTPException as he:
        await close_progress(sink, he)
        raise
    except Exception as e:
        await close_progress(sink, e)
        logger.error(f"组合回测失败: {e}")
        raise HTTPException(status_code=500, detail=f"组合回测失败: {str(e)}")



