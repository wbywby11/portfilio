# -*- coding: utf-8 -*-
"""
投资组合 API

支持三种来源的组合创建、查询、分析和权重管理。
"""
from typing import List, Optional
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel

from app.portfolio.schemas import (
    PortfolioCreate,
    PortfolioFromSingleModelCreate,
    PortfolioFromPortfolioModelCreate,
    PortfolioFromStrategiesCreate,
    WeightAdjustRequest,
    PortfolioOut,
    PortfolioDetailOut,
    SubStrategyOut,
    SubStrategyPerformanceOut,
    CorrelationAnalysisOut,
    RebalanceRecordOut,
    PositionIn,
)
from app.schemas.response import Response
from app.portfolio.portfolio_service import PortfolioService
from app.services.asset_service import AssetService
from app.portfolio.models import Portfolio, PortfolioSource, PortfolioStatus, Position, RebalanceRecord
from app.models.strategy_model import ModelStatus


router = APIRouter()


def get_portfolio_service() -> PortfolioService:
    return PortfolioService()


def get_asset_service() -> AssetService:
    return AssetService()


# ============================================================
# 创建端点
# ============================================================

@router.post("/", response_model=Response[str], summary="手工创建组合")
async def create_portfolio(
    portfolio_in: PortfolioCreate,
    service: PortfolioService = Depends(get_portfolio_service),
    asset_service: AssetService = Depends(get_asset_service),
):
    """
    手工创建模拟组合

    支持两种持仓配置方式：
    1. 按权重配置：提供 weight，系统根据资金和价格计算 shares
    2. 按份额配置：提供 shares，系统根据价格计算 weight
    """
    inception_date = portfolio_in.inception_date if portfolio_in.inception_date else datetime.now()

    # 处理持仓
    positions = []
    if portfolio_in.positions:
        import pandas as pd
        asset_codes = [p.asset_code for p in portfolio_in.positions]
        lookback_start = inception_date - pd.Timedelta(days=30)
        price_df = await asset_service.get_price_dataframe(
            asset_codes, lookback_start, datetime.now()
        )

        if price_df.empty:
            latest_dates = await asset_service.get_latest_price_dates(asset_codes)
            date_info_lines = []
            for code in asset_codes:
                latest = latest_dates.get(code)
                if latest:
                    date_info_lines.append(f"  - {code}: 最新数据日期 {latest}")
                else:
                    date_info_lines.append(f"  - {code}: 无价格数据")
            detail_msg = (
                f"无法获取资产价格数据，请检查：\n"
                f"1. 资产代码是否正确：{', '.join(asset_codes)}\n"
                f"2. 是否已导入这些资产的行情数据\n"
                f"3. 建仓日期：{inception_date.strftime('%Y-%m-%d')}\n\n"
                f"各资产最新数据日期：\n" + "\n".join(date_info_lines)
            )
            raise HTTPException(status_code=400, detail=detail_msg)

        latest_prices = price_df.iloc[-1].to_dict()
        total_market_value = 0.0
        temp_positions = []

        for p_in in portfolio_in.positions:
            price = latest_prices.get(p_in.asset_code)
            if price is None or price <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"资产 {p_in.asset_code} 的价格数据不可用"
                )
            position_dict = p_in.dict()
            position_dict['price'] = float(price)

            if p_in.weight is not None:
                market_value = portfolio_in.initial_capital * p_in.weight
                shares = market_value / price
                position_dict['shares'] = shares
                position_dict['market_value'] = market_value
            elif p_in.shares is not None:
                market_value = p_in.shares * price
                position_dict['market_value'] = market_value
                total_market_value += market_value

            temp_positions.append(position_dict)

        if total_market_value > 0:
            for pos_dict in temp_positions:
                if pos_dict.get('weight') is None:
                    pos_dict['weight'] = pos_dict['market_value'] / total_market_value

        positions = [Position(**pos_dict) for pos_dict in temp_positions]

    portfolio = Portfolio(
        name=portfolio_in.name,
        source=PortfolioSource.MANUAL,
        description=portfolio_in.description,
        initial_capital=portfolio_in.initial_capital,
        current_capital=portfolio_in.initial_capital,
        inception_date=inception_date,
        positions=positions,
        created_by=portfolio_in.created_by,
    )
    portfolio_id = await service.create_portfolio(portfolio)
    await service.ensure_portfolio_model(portfolio_id)
    return Response.success(data=portfolio_id, message="组合创建成功")


@router.post("/from-model", response_model=Response[str], summary="从单策略模型创建组合")
async def create_portfolio_from_single_model(
    body: PortfolioFromSingleModelCreate,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """
    从单策略模型创建模拟组合（保持兼容）

    流程：
    1. 验证模型状态
    2. 从建仓日追溯到当前的所有持仓记录和业绩表现
    3. 创建并保存模拟组合
    """
    try:
        portfolio_id = await service.create_from_single_model(
            model_id=body.model_id,
            inception_date=body.inception_date,
            name=body.name,
            initial_capital=body.initial_capital,
        )
        await service.ensure_portfolio_model(portfolio_id)
        return Response.success(data=portfolio_id, message="模拟组合创建成功（已完成历史追溯）")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"组合创建失败: {str(e)}")


@router.post("/from-portfolio-model", response_model=Response[str], summary="从组合模型创建（多策略）")
async def create_portfolio_from_portfolio_model(
    body: PortfolioFromPortfolioModelCreate,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """
    从组合模型（is_portfolio=True，多策略复合）创建模拟组合。

    这是核心新能力：
    1. 解析组合模型的子策略列表
    2. 对每个子策略执行回测获取NAV序列
    3. 调用 composite_engine 复合为组合NAV
    4. 追溯生成权重变化记录
    """
    try:
        portfolio_id = await service.create_from_portfolio_model(
            portfolio_model_id=body.portfolio_model_id,
            inception_date=body.inception_date,
            name=body.name,
            initial_capital=body.initial_capital,
            weight_method=body.weight_method,
            sub_strategy_weights=[w.model_dump() for w in body.sub_strategy_weights] if body.sub_strategy_weights else None,
            vol_target=body.vol_target,
            vol_lookback_short=body.vol_lookback_short,
            vol_lookback_long=body.vol_lookback_long,
            vol_method=body.vol_method,
            vol_annualize_factor=body.vol_annualize_factor,
            vol_leverage_min=body.vol_leverage_min,
            vol_leverage_max=body.vol_leverage_max,
            rebalance_frequency=body.rebalance_frequency,
        )
        return Response.success(data=portfolio_id, message="多策略组合创建成功（已完成历史追溯）")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"组合创建失败: {str(e)}")


@router.post("/from-strategies", response_model=Response[str], summary="从多个已发布策略组合创建")
async def create_portfolio_from_strategies(
    body: PortfolioFromStrategiesCreate,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """
    从用户选择的多个已发布策略直接组合创建模拟组合（仅建记录，不执行回测）。

    用户可多选策略并设置权重：
    1. 用户从已发布策略列表中选择多个策略
    2. 设置每个策略的权重（或使用等权/风险平价/最小方差自动计算）
    """
    try:
        portfolio_id = await service.create_from_strategies(
            strategy_ids=body.strategy_ids,
            name=body.name,
            initial_capital=body.initial_capital,
            weight_method=body.weight_method,
            weight_model_params=body.weight_model_params,
            sub_strategy_weights=[w.model_dump() for w in body.sub_strategy_weights] if body.sub_strategy_weights else None,
            vol_target=body.vol_target,
            vol_lookback_short=body.vol_lookback_short,
            vol_lookback_long=body.vol_lookback_long,
            vol_method=body.vol_method,
            vol_annualize_factor=body.vol_annualize_factor,
            vol_leverage_min=body.vol_leverage_min,
            vol_leverage_max=body.vol_leverage_max,
        )
        await service.ensure_portfolio_model(portfolio_id)
        return Response.success(data=portfolio_id, message="组合创建成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"组合创建失败: {str(e)}")


# ============================================================
# 查询端点
# ============================================================

def _portfolio_live_status(p: Portfolio, live_status_map: dict) -> bool:
    """组合实盘状态：以直接关联的组合模型为准（与前端发布/取消操作目标一致）。

    仅当组合无直接关联模型时，才回退到子策略模型状态。
    子策略独立实盘（从策略库页面发布）不应影响组合自身的发布/取消操作，
    否则会出现「实盘发布按钮常禁用、取消实盘点击无效」的状态不一致。
    """
    direct = p.portfolio_model_id or p.model_id
    if direct:
        return bool((live_status_map.get(str(direct)) or {}).get("live_publish_enabled"))
    for s in (p.sub_strategies or []):
        if s.model_id and (live_status_map.get(str(s.model_id)) or {}).get("live_publish_enabled"):
            return True
    return False


def _portfolio_model_meta(p: Portfolio, live_status_map: dict) -> dict:
    """取组合自身关联模型的发布元信息（无直接模型时回退第一个已实盘子策略）。"""
    direct = p.portfolio_model_id or p.model_id
    if direct:
        return live_status_map.get(str(direct)) or {}
    for s in (p.sub_strategies or []):
        meta = live_status_map.get(str(s.model_id)) if s.model_id else None
        if meta and meta.get("live_publish_enabled"):
            return meta
    return {}

@router.get("/", response_model=Response[List[PortfolioOut]], summary="组合列表")
async def list_portfolios(service: PortfolioService = Depends(get_portfolio_service)):
    """获取所有模拟组合列表"""
    portfolios = await service.list_portfolios()

    # 懒同步：存量组合自动补建组合模型（确保每个组合都有模型ID）
    for p in portfolios:
        if not p.portfolio_model_id and p.status != PortfolioStatus.ARCHIVED:
            try:
                new_mid = await service.ensure_portfolio_model(str(p.id))
                if new_mid:
                    p.portfolio_model_id = new_mid
            except Exception:
                pass  # 补建失败不影响列表展示

    # 批量查询关联模型（含子策略模型）的实盘发布状态
    linked_ids = set()
    for p in portfolios:
        direct = p.portfolio_model_id or p.model_id
        if direct:
            linked_ids.add(str(direct))
        for s in (p.sub_strategies or []):
            if s.model_id:
                linked_ids.add(str(s.model_id))
    live_status_map = {}
    if linked_ids:
        from app.config.database import Database
        db = Database.get_database()
        valid_ids = [ObjectId(mid) for mid in linked_ids if ObjectId.is_valid(mid)]
        cursor = db.strategy_models.find(
            {"_id": {"$in": valid_ids}},
            {
                "live_publish_enabled": 1,
                "status": 1,
                "published_version": 1,
                "live_published_version": 1,
            },
        )
        async for doc in cursor:
            live_status_map[str(doc["_id"])] = {
                "live_publish_enabled": bool(doc.get("live_publish_enabled", False)),
                "status": doc.get("status"),
                "published_version": doc.get("published_version"),
                "live_published_version": doc.get("live_published_version"),
            }

    data = []
    for p in portfolios:
        # 构造子策略输出
        sub_strats = [
            SubStrategyOut(
                model_id=s.model_id,
                name=s.name,
                weight=s.weight,
                template_code=s.template_code,
                latest_nav=s.latest_nav,
                latest_return=s.latest_return,
            )
            for s in p.sub_strategies
        ] if p.sub_strategies else []

        # 扁平化绩效
        total_return = None
        annual_return = None
        annual_volatility = None
        annual_return_365 = None
        annual_volatility_365 = None
        max_drawdown = None
        sharpe_ratio = None
        sharpe_ratio_365 = None
        latest_unit_value = None
        if p.performance:
            total_return = p.performance.total_return
            annual_return = p.performance.annual_return
            annual_volatility = getattr(p.performance, 'annual_volatility', None)
            annual_return_365 = getattr(p.performance, 'annual_return_365', None)
            annual_volatility_365 = getattr(p.performance, 'annual_volatility_365', None)
            max_drawdown = p.performance.max_drawdown
            sharpe_ratio = p.performance.sharpe_ratio
            sharpe_ratio_365 = getattr(p.performance, 'sharpe_ratio_365', None)
            latest_unit_value = p.performance.latest_unit_value
        else:
            # 回退到 latest_backtest_summary（回测后写入）
            _bs = getattr(p, 'latest_backtest_summary', None)
            if _bs:
                total_return = _bs.get('total_return')
                annual_return = _bs.get('annual_return')
                annual_volatility = _bs.get('annual_vol')
                annual_return_365 = _bs.get('annual_return_365')
                annual_volatility_365 = _bs.get('annual_vol_365')
                max_drawdown = _bs.get('max_drawdown')
                sharpe_ratio = _bs.get('sharpe')
                sharpe_ratio_365 = _bs.get('sharpe_365')

        data.append(PortfolioOut(
            id=str(p.id),
            name=p.name,
            source=p.source,
            description=p.description,
            status=p.status,
            model_id=p.model_id,
            portfolio_model_id=p.portfolio_model_id,
            sub_strategies=sub_strats,
            rebalance_frequency=p.rebalance_frequency,
            weight_method=p.weight_method,
            vol_target=p.vol_target,
            vol_lookback_short=p.vol_lookback_short,
            vol_lookback_long=p.vol_lookback_long,
            vol_method=getattr(p, 'vol_method', None),
            vol_annualize_factor=getattr(p, 'vol_annualize_factor', None),
            vol_leverage_min=getattr(p, 'vol_leverage_min', None),
            vol_leverage_max=getattr(p, 'vol_leverage_max', None),
            initial_capital=p.initial_capital,
            current_capital=p.current_capital,
            total_return=total_return,
            annual_return=annual_return,
            annual_volatility=annual_volatility,
            annual_return_365=annual_return_365,
            annual_volatility_365=annual_volatility_365,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            sharpe_ratio_365=sharpe_ratio_365,
            latest_unit_value=latest_unit_value,
            latest_backtest_summary=getattr(p, 'latest_backtest_summary', None),
            live_publish_enabled=_portfolio_live_status(p, live_status_map),
            portfolio_model_status=_portfolio_model_meta(p, live_status_map).get("status"),
            published_version=_portfolio_model_meta(p, live_status_map).get("published_version"),
            live_published_version=_portfolio_model_meta(p, live_status_map).get("live_published_version"),
            inception_date=p.inception_date,
            created_at=p.created_at,
            updated_at=p.updated_at,
        ))

    return Response.success(data=data)


@router.get("/{portfolio_id}", response_model=Response[PortfolioOut], summary="获取单个组合")
async def get_portfolio(
    portfolio_id: str,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """获取单个组合基础信息"""
    portfolio = await service.get_portfolio(portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"组合不存在: {portfolio_id}")

    # 确保组合拥有模型ID（懒同步）
    if not portfolio.portfolio_model_id and portfolio.status != PortfolioStatus.ARCHIVED:
        try:
            new_mid = await service.ensure_portfolio_model(portfolio_id)
            if new_mid:
                portfolio.portfolio_model_id = new_mid
        except Exception:
            pass

    # 查询关联模型实盘/发布状态
    _live_enabled = False
    _model_status = None
    _published_version = None
    _live_published_version = None
    _pmid = portfolio.portfolio_model_id or portfolio.model_id
    if _pmid and ObjectId.is_valid(str(_pmid)):
        from app.config.database import Database as _Db
        _doc = await _Db.get_database().strategy_models.find_one(
            {"_id": ObjectId(str(_pmid))},
            {
                "live_publish_enabled": 1,
                "status": 1,
                "published_version": 1,
                "live_published_version": 1,
            },
        )
        if _doc:
            _live_enabled = bool(_doc.get("live_publish_enabled", False))
            _model_status = _doc.get("status")
            _published_version = _doc.get("published_version")
            _live_published_version = _doc.get("live_published_version")

    sub_strats = [
        SubStrategyOut(
            model_id=s.model_id,
            name=s.name,
            weight=s.weight,
            template_code=s.template_code,
            latest_nav=s.latest_nav,
            latest_return=s.latest_return,
        )
        for s in portfolio.sub_strategies
    ] if portfolio.sub_strategies else []

    total_return = None
    annual_return = None
    annual_volatility = None
    annual_return_365 = None
    annual_volatility_365 = None
    sharpe_ratio_365 = None
    max_drawdown = None
    sharpe_ratio = None
    latest_unit_value = None
    if portfolio.performance:
        total_return = portfolio.performance.total_return
        annual_return = portfolio.performance.annual_return
        annual_volatility = getattr(portfolio.performance, 'annual_volatility', None)
        annual_return_365 = getattr(portfolio.performance, 'annual_return_365', None)
        annual_volatility_365 = getattr(portfolio.performance, 'annual_volatility_365', None)
        sharpe_ratio_365 = getattr(portfolio.performance, 'sharpe_ratio_365', None)
        max_drawdown = portfolio.performance.max_drawdown
        sharpe_ratio = portfolio.performance.sharpe_ratio
        latest_unit_value = portfolio.performance.latest_unit_value
    else:
        _bs = getattr(portfolio, 'latest_backtest_summary', None)
        if _bs:
            total_return = _bs.get('total_return')
            annual_return = _bs.get('annual_return')
            annual_volatility = _bs.get('annual_vol')
            annual_return_365 = _bs.get('annual_return_365')
            annual_volatility_365 = _bs.get('annual_vol_365')
            sharpe_ratio_365 = _bs.get('sharpe_365')
            max_drawdown = _bs.get('max_drawdown')
            sharpe_ratio = _bs.get('sharpe')

    out = PortfolioOut(
        id=str(portfolio.id),
        name=portfolio.name,
        source=portfolio.source,
        description=portfolio.description,
        status=portfolio.status,
        model_id=portfolio.model_id,
        portfolio_model_id=portfolio.portfolio_model_id,
        sub_strategies=sub_strats,
        rebalance_frequency=portfolio.rebalance_frequency,
        weight_method=portfolio.weight_method,
        weight_model_params=portfolio.weight_model_params or {},
        vol_target=portfolio.vol_target,
        vol_lookback_short=portfolio.vol_lookback_short,
        vol_lookback_long=portfolio.vol_lookback_long,
        vol_method=getattr(portfolio, 'vol_method', None),
        vol_annualize_factor=getattr(portfolio, 'vol_annualize_factor', None),
        vol_leverage_min=getattr(portfolio, 'vol_leverage_min', None),
        vol_leverage_max=getattr(portfolio, 'vol_leverage_max', None),
        initial_capital=portfolio.initial_capital,
        current_capital=portfolio.current_capital,
        total_return=total_return,
        annual_return=annual_return,
        annual_volatility=annual_volatility,
        annual_return_365=annual_return_365,
        annual_volatility_365=annual_volatility_365,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        sharpe_ratio_365=sharpe_ratio_365,
        latest_unit_value=latest_unit_value,
        latest_backtest_summary=getattr(portfolio, 'latest_backtest_summary', None),
        live_publish_enabled=_live_enabled,
        portfolio_model_status=_model_status,
        published_version=_published_version,
        live_published_version=_live_published_version,
        inception_date=portfolio.inception_date,
        created_at=portfolio.created_at,
        updated_at=portfolio.updated_at,
    )
    return Response.success(data=out)


@router.get("/{portfolio_id}/details", response_model=Response[PortfolioDetailOut], summary="组合详情")
async def get_portfolio_details(
    portfolio_id: str,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """
    获取组合详情页所需的所有数据：
    - 基础信息、核心业绩指标、净值曲线
    - 子策略绩效分解（仅 PORTFOLIO_MODEL）
    - 相关性分析（仅 PORTFOLIO_MODEL）
    - 当前持仓占比
    """
    portfolio = await service.get_portfolio(portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"组合不存在: {portfolio_id}")

    # 计算最新业绩
    performance = await service.compute_performance(portfolio_id)

    # 子策略输出
    sub_strats = [
        SubStrategyOut(
            model_id=s.model_id,
            name=s.name,
            weight=s.weight,
            template_code=s.template_code,
            latest_nav=s.latest_nav,
            latest_return=s.latest_return,
        )
        for s in portfolio.sub_strategies
    ] if portfolio.sub_strategies else []

    # 当前持仓
    from app.schemas.strategy_model import AssetPositionOut
    current_holdings = [
        AssetPositionOut(
            asset_code=p.asset_code,
            asset_name=p.asset_name,
            weight=p.weight,
            market_value=p.market_value,
            price=p.price,
        )
        for p in portfolio.positions
    ]

    # 子策略绩效分解和相关性分析（仅 PORTFOLIO_MODEL）
    sub_perf_list = []
    correlation = None
    if portfolio.source == PortfolioSource.PORTFOLIO_MODEL and portfolio.portfolio_model_id:
        sub_perf_list, correlation = await _compute_sub_strategy_analysis(
            service, portfolio
        )

    from app.schemas.strategy_model import BacktestResultOut
    metrics_out = None
    if performance:
        metrics_out = BacktestResultOut(**performance.dict())

    detail = PortfolioDetailOut(
        id=str(portfolio.id),
        name=portfolio.name,
        source=portfolio.source,
        description=portfolio.description,
        status=portfolio.status,
        model_id=portfolio.model_id,
        portfolio_model_id=portfolio.portfolio_model_id,
        sub_strategies=sub_strats,
        inception_date=portfolio.inception_date,
        initial_capital=portfolio.initial_capital,
        current_capital=portfolio.current_capital,
        metrics=metrics_out,
        sub_strategy_performance=sub_perf_list,
        correlation_analysis=correlation,
        current_holdings=current_holdings,
    )
    return Response.success(data=detail)


@router.get("/{portfolio_id}/analysis", response_model=Response, summary="组合分析")
async def get_portfolio_analysis(
    portfolio_id: str,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """返回组合当前的业绩指标及净值曲线"""
    portfolio = await service.get_portfolio(portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"组合不存在: {portfolio_id}")

    performance = await service.compute_performance(portfolio_id)
    from app.schemas.strategy_model import BacktestResultOut
    if performance:
        result = BacktestResultOut(**performance.dict())
        # 附加回撤序列
        drawdown_series = await service.compute_drawdown_series(portfolio_id)
        data = result.model_dump()
        data["drawdown_series"] = drawdown_series
        return Response.success(data=data)
    return Response.success(data=None, message="暂无绩效数据")


# ============================================================
# 权重管理端点
# ============================================================

@router.patch("/{portfolio_id}/weights", response_model=Response[bool], summary="手动调整子策略权重")
async def adjust_weights(
    portfolio_id: str,
    body: WeightAdjustRequest,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """
    手动调整组合内子策略的配置权重。

    仅适用于 PORTFOLIO_MODEL 类型的组合。
    调整后不会自动重新计算绩效（用户可手动触发分析接口）。
    """
    try:
        new_weights = [{"model_id": s.model_id, "weight": s.weight} for s in body.sub_strategies]
        success = await service.update_sub_strategy_weights(
            portfolio_id=portfolio_id,
            new_weights=new_weights,
            reason=body.reason,
        )
        return Response.success(data=success, message="子策略权重调整成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{portfolio_id}/note", response_model=Response[bool], summary="更新分析笔记")
async def update_portfolio_note(
    portfolio_id: str,
    body: dict,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """更新组合分析笔记"""
    note = body.get("note", "")
    success = await service.update_portfolio(portfolio_id, {"note": note})
    return Response.success(data=success, message="笔记更新成功")


class PortfolioEditIn(BaseModel):
    """编辑组合请求体"""
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    weight_method: Optional[str] = None
    weight_model_params: Optional[dict] = None
    rebalance_frequency: Optional[str] = None
    vol_target: Optional[float] = None
    vol_lookback_short: Optional[int] = None
    vol_lookback_long: Optional[int] = None
    vol_method: Optional[str] = None
    vol_annualize_factor: Optional[int] = None
    vol_leverage_min: Optional[float] = None
    vol_leverage_max: Optional[float] = None
    sub_strategies: Optional[list] = None  # [{"model_id": "...", "weight": 0.5, "name": "..."}]


@router.patch("/{portfolio_id}", response_model=Response[bool], summary="编辑组合")
async def edit_portfolio(
    portfolio_id: str,
    body: PortfolioEditIn,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """编辑组合（名称、描述、状态、子策略权重、权重方法、波动率参数等）"""
    if not ObjectId.is_valid(portfolio_id):
        raise HTTPException(status_code=400, detail=f"无效的组合ID格式: {portfolio_id}")
    portfolio = await service.get_portfolio(portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"组合不存在: {portfolio_id}")

    linked_model_id = getattr(portfolio, "portfolio_model_id", None) or getattr(portfolio, "model_id", None)
    linked_model = None
    if linked_model_id and ObjectId.is_valid(str(linked_model_id)):
        linked_model = await service.strategy_model_service.get_model(str(linked_model_id))
    if linked_model and linked_model.live_publish_enabled:
        raise HTTPException(
            status_code=409,
            detail="组合已实盘，配置已冻结；请先取消实盘后再编辑",
        )

    update_data: dict = {}

    # 基础字段
    if body.name is not None:
        update_data["name"] = body.name.strip()
    if body.description is not None:
        update_data["description"] = body.description
    if body.status is not None:
        update_data["status"] = body.status
    if body.weight_method is not None:
        update_data["weight_method"] = body.weight_method
    if body.weight_model_params is not None:
        update_data["weight_model_params"] = body.weight_model_params
        # 产品层配置同步到关联的策略模型：日常监控从 strategy_models 读取
        # weight_model_params，若不同步会导致监控与组合回测的产品层口径不一致。
        if "product_layer" in body.weight_model_params:
            linked_model_id = getattr(portfolio, "portfolio_model_id", None) or getattr(portfolio, "model_id", None)
            if linked_model_id and ObjectId.is_valid(str(linked_model_id)):
                try:
                    from app.config.database import Database as _DB
                    await _DB.get_database()["strategy_models"].update_one(
                        {"_id": ObjectId(str(linked_model_id))},
                        {"$set": {"weight_model_params.product_layer": body.weight_model_params["product_layer"]}},
                    )
                except Exception as sync_err:
                    logger.warning(f"[product_layer] 同步策略模型失败（不影响保存）: {sync_err}")
    if body.rebalance_frequency is not None:
        update_data["rebalance_frequency"] = body.rebalance_frequency
    if body.vol_target is not None:
        update_data["vol_target"] = body.vol_target
    if body.vol_lookback_short is not None:
        update_data["vol_lookback_short"] = body.vol_lookback_short
    if body.vol_lookback_long is not None:
        update_data["vol_lookback_long"] = body.vol_lookback_long
    if body.vol_method is not None:
        update_data["vol_method"] = body.vol_method
    if body.vol_annualize_factor is not None:
        update_data["vol_annualize_factor"] = body.vol_annualize_factor
    if body.vol_leverage_min is not None:
        update_data["vol_leverage_min"] = body.vol_leverage_min
    if body.vol_leverage_max is not None:
        update_data["vol_leverage_max"] = body.vol_leverage_max

    # 子策略权重
    if body.sub_strategies is not None:
        from app.portfolio.models import SubStrategyAllocation
        new_subs = []
        for s in body.sub_strategies:
            # 保留原有的 name / template_code
            existing = next((x for x in portfolio.sub_strategies if x.model_id == s.get("model_id")), None)
            new_subs.append(SubStrategyAllocation(
                model_id=s["model_id"],
                name=s.get("name") or (existing.name if existing else ""),
                weight=float(s["weight"]),
                template_code=s.get("template_code") or (existing.template_code if existing else None),
                latest_nav=existing.latest_nav if existing else None,
                latest_return=existing.latest_return if existing else None,
            ))
        update_data["sub_strategies"] = [s.dict() for s in new_subs]

    if not update_data:
        return Response.success(data=True, message="无变更")

    success = await service.update_portfolio(portfolio_id, update_data)

    # 草稿态：把组合配置同步到组合模型，保证发布时冻结的是最新配置
    if success and linked_model:
        model_update: dict = {}
        if "name" in update_data:
            model_update["name"] = update_data["name"]
        if "rebalance_frequency" in update_data:
            model_update["rebalance_frequency"] = update_data["rebalance_frequency"]
        if "weight_model_params" in update_data:
            model_update["weight_model_params"] = update_data["weight_model_params"]
        if body.weight_method is not None:
            model_update["weight_model_type"] = (
                "quadrant" if body.weight_method == "quadrant" else None
            )
        if "sub_strategies" in update_data:
            model_update["sub_strategies"] = update_data["sub_strategies"]
            all_codes: set = set()
            for sub in update_data["sub_strategies"]:
                sub_model = await service.strategy_model_service.get_model(
                    str(sub.get("model_id") or "")
                )
                if sub_model:
                    all_codes.update(sub_model.asset_codes or [])
            model_update["asset_codes"] = sorted(all_codes)
        if model_update:
            model_update["updated_at"] = datetime.now()
            await service.strategy_model_service.collection.update_one(
                {"_id": ObjectId(str(linked_model_id))}, {"$set": model_update}
            )
            # 已发布组合：编辑会改变发布快照内容，立即刷新快照，
            # 保证下次实盘发布使用最新配置（组合管理不暴露发布动作）
            frozen_fields = {
                "sub_strategies",
                "rebalance_frequency",
                "weight_model_params",
                "weight_model_type",
            }
            if linked_model.status == ModelStatus.PUBLISHED and frozen_fields & set(model_update):
                from app.services.live_publish_service import LivePublishService
                try:
                    await LivePublishService(service.strategy_model_service).republish_model(
                        str(linked_model_id), source="portfolio_edit"
                    )
                except ValueError as refresh_err:
                    logger.warning(
                        "[组合编辑] 刷新发布快照失败 model=%s: %s", linked_model_id, refresh_err
                    )
                    return Response.success(
                        data=success, message="组合已保存，但发布快照刷新失败，请稍后重试"
                    )

    return Response.success(data=success, message="组合信息已更新")


@router.get("/{portfolio_id}/rebalance-records", response_model=Response[List[RebalanceRecordOut]], summary="调仓记录")
async def list_rebalance_records(
    portfolio_id: str,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """获取组合的调仓/权重变化历史记录"""
    records = await service.list_rebalance_records(portfolio_id)
    data = [
        RebalanceRecordOut(
            id=str(r.id) if r.id else None,
            rebalance_date=r.rebalance_date,
            action=r.action,
            reason=r.reason,
            positions_before=[
                PositionIn(
                    asset_code=p.asset_code,
                    asset_name=p.asset_name,
                    weight=p.weight,
                    shares=p.shares,
                )
                for p in r.positions_before
            ] if r.positions_before else [],
            positions_after=[
                PositionIn(
                    asset_code=p.asset_code,
                    asset_name=p.asset_name,
                    weight=p.weight,
                    shares=p.shares,
                )
                for p in r.positions_after
            ] if r.positions_after else [],
            weights_before=r.weights_before,
            weights_after=r.weights_after,
        )
        for r in records
    ]
    return Response.success(data=data)


# ============================================================
# 回测历史
# ============================================================

@router.get("/{portfolio_id}/backtests", response_model=Response[List[dict]], summary="获取组合回测记录")
async def list_portfolio_backtests(
    portfolio_id: str,
    skip: int = 0,
    limit: int = 50,
):
    """查询组合的回测历史记录（复用 backtests 集合，model_id=portfolio_id）。

    列表只返回指标摘要：净值曲线/收益曲线/持仓/权重变化等明细体量大，
    由详情接口 GET /api/v1/backtests/{record_id} 按需加载。
    """
    if not ObjectId.is_valid(portfolio_id):
        raise HTTPException(status_code=400, detail=f"无效的ID格式: {portfolio_id}")
    from app.services.backtest_service import BacktestService
    svc = BacktestService()
    records = await svc.list_backtest_records(model_id=portfolio_id, skip=skip, limit=limit)
    heavy_fields = ("equity_curve", "return_curve", "positions", "weight_changes")
    out = []
    for r in records:
        result_dict = r.result.dict() if hasattr(r.result, 'dict') else {}
        for field in heavy_fields:
            result_dict.pop(field, None)
        out.append({
            "id": str(r.id) if r.id else None,
            "model_id": r.model_id,
            "start_date": r.start_date.strftime("%Y-%m-%d") if hasattr(r.start_date, "strftime") else str(r.start_date),
            "end_date": r.end_date.strftime("%Y-%m-%d") if hasattr(r.end_date, "strftime") else str(r.end_date),
            "initial_capital": getattr(r, "initial_capital", 0) or 0,
            "result": result_dict,
            "remark": getattr(r, "remark", None),
            "created_at": r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at),
        })
    return Response.success(data=out)


# ============================================================
# 删除端点
# ============================================================

@router.delete("/{portfolio_id}", response_model=Response[bool], summary="删除组合")
async def delete_portfolio(
    portfolio_id: str,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """删除模拟组合及其所有相关的调仓记录"""
    if not ObjectId.is_valid(portfolio_id):
        raise HTTPException(status_code=400, detail=f"无效的组合ID格式: {portfolio_id}")

    success = await service.delete_portfolio(portfolio_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"组合不存在或删除失败: {portfolio_id}")

    return Response.success(data=True, message="组合及相关记录已删除")


# ============================================================
# 辅助函数
# ============================================================

async def _compute_sub_strategy_analysis(
    service: PortfolioService,
    portfolio: Portfolio,
) -> tuple:
    """
    计算子策略绩效分解和相关性分析。
    返回 (sub_strategy_performance_list, correlation_analysis)

    绩效指标统一走 `app.analysis.performance`，与回测口径一致。
    """
    from app.analysis.performance import compute_performance

    sub_perf_list = []
    correlation = None

    try:
        # 使用 service 层的公共函数执行子策略回测，消除与 portfolio_service 的重复逻辑
        result = await service._run_all_sub_strategies(portfolio)
        if result is None:
            return sub_perf_list, correlation

        portfolio_model, sub_pairs, sub_nav_series, sub_weights = result

        # 计算子策略绩效
        for sub_model, weight in sub_pairs:
            key = sub_model.id or sub_model.name
            if key not in sub_nav_series:
                continue
            nav = sub_nav_series[key]
            actual_weight = sub_weights.get(key, weight)

            # 绩效指标由统一内核计算，避免此处再实现一套年化/回撤口径
            metrics = compute_performance(nav)
            # 贡献：静态权重近似（此处无逐日权重历史，仅用于组合概览排序）
            contribution = float(metrics.total_return * actual_weight)

            # 净值曲线（采样）
            equity_curve = []
            step = max(1, len(nav) // 200)
            for i in range(0, len(nav), step):
                equity_curve.append({
                    "date": nav.index[i].strftime("%Y-%m-%d"),
                    "nav": round(float(nav.iloc[i]), 4),
                })

            sub_perf_list.append(SubStrategyPerformanceOut(
                model_id=sub_model.id or "",
                name=sub_model.name,
                weight=actual_weight,
                annual_return=round(metrics.annual_return, 6),
                annual_vol=round(metrics.annual_volatility, 6),
                sharpe=round(metrics.sharpe_ratio, 4),
                max_drawdown=round(metrics.max_drawdown, 6),
                annual_return_365=round(metrics.annual_return_365, 6),
                annual_vol_365=round(metrics.annual_volatility_365, 6),
                sharpe_365=round(metrics.sharpe_ratio_365, 4),
                contribution=round(contribution, 6),
                contribution_pct=None,
                equity_curve=equity_curve,
            ))

        # 贡献占比
        total_contribution = sum(abs(sp.contribution or 0) for sp in sub_perf_list)
        if total_contribution > 0:
            for sp in sub_perf_list:
                sp.contribution_pct = round((sp.contribution or 0) / total_contribution, 4)

        # 相关性分析（复用 portfolio_analytics 模块）
        if len(sub_nav_series) >= 2:
            from app.backtesting.portfolio_analytics import compute_correlation_drag
            corr_result = compute_correlation_drag(sub_nav_series, sub_weights)

            if corr_result.correlation_matrix is not None:
                corr_dict = {}
                for col in corr_result.correlation_matrix.columns:
                    corr_dict[col] = {
                        row: round(float(corr_result.correlation_matrix.loc[row, col]), 4)
                        for row in corr_result.correlation_matrix.index
                    }

                correlation = CorrelationAnalysisOut(
                    avg_correlation=round(float(corr_result.avg_correlation), 4),
                    diversification_ratio=round(float(corr_result.diversification_ratio), 4),
                    correlation_drag=round(float(corr_result.correlation_drag), 6),
                    correlation_matrix=corr_dict,
                )

    except Exception as e:
        logger.warning(f"[子策略分析] 计算失败: {e}")

    return sub_perf_list, correlation
