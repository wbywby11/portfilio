"""模拟组合相关路由"""
from typing import List
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from app.schemas.portfolio import PortfolioCreate, PortfolioOut, RebalanceCreate, PositionIn, PortfolioDetailOut
from app.schemas.response import Response
from app.services.portfolio_service import PortfolioService
from app.services.asset_service import AssetService
from app.models.portfolio import Portfolio, RebalanceRecord, Position


router = APIRouter()


def get_portfolio_service() -> PortfolioService:
    return PortfolioService()


def get_asset_service() -> AssetService:
    return AssetService()


@router.post("/", response_model=Response[str], summary="创建模拟组合")
async def create_portfolio(
    portfolio_in: PortfolioCreate,
    service: PortfolioService = Depends(get_portfolio_service),
    asset_service: AssetService = Depends(get_asset_service),
):
    """
    创建模拟组合
    
    支持两种持仓配置方式：
    1. 按权重配置：提供 weight，系统根据资金和价格计算 shares
    2. 按份额配置：提供 shares，系统根据价格计算 weight
    
    建仓日期：
    - 不提供 inception_date：使用当前日期建仓
    - 提供历史日期：从该日期开始计算业绩
    """
    # 如果没有提供建仓日期，使用当前日期
    inception_date = portfolio_in.inception_date if portfolio_in.inception_date else datetime.now()
    
    # 处理持仓：需要获取价格数据来计算缺失的 weight 或 shares
    positions = []
    if portfolio_in.positions:
        # 收集所有资产代码
        asset_codes = [p.asset_code for p in portfolio_in.positions]
        
        # 获取价格数据：往前扩展30天以确保能取到最近交易日的数据（避免当天数据未入库时报错）
        import pandas as pd
        lookback_start = inception_date - pd.Timedelta(days=30)
        price_df = await asset_service.get_price_dataframe(
            asset_codes,
            lookback_start,
            datetime.now()
        )
        
        if price_df.empty:
            # 查询每个资产的最新数据日期，帮助用户了解数据情况
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
                f"各资产最新数据日期：\n" + "\n".join(date_info_lines) + "\n\n"
                f"建议：\n"
                f"- 如果最新数据日期早于建仓日期，请调整建仓日期至最新数据日期或更早\n"
                f"- 如果显示「无价格数据」，请先导入该资产的行情数据"
            )
            raise HTTPException(status_code=400, detail=detail_msg)
        
        # 获取最新价格
        latest_prices = price_df.iloc[-1].to_dict()
        
        # 计算总市值（如果是按份额配置）
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
            
            # 如果提供了权重，计算份额
            if p_in.weight is not None:
                market_value = portfolio_in.initial_capital * p_in.weight
                shares = market_value / price
                position_dict['shares'] = shares
                position_dict['market_value'] = market_value
            # 如果提供了份额，计算市值（暂时，稍后计算权重）
            elif p_in.shares is not None:
                market_value = p_in.shares * price
                position_dict['market_value'] = market_value
                total_market_value += market_value
            
            temp_positions.append(position_dict)
        
        # 如果是按份额配置，计算权重
        if total_market_value > 0:
            for pos_dict in temp_positions:
                if pos_dict.get('weight') is None:
                    pos_dict['weight'] = pos_dict['market_value'] / total_market_value
        
        # 创建 Position 对象
        positions = [Position(**pos_dict) for pos_dict in temp_positions]
    
    portfolio = Portfolio(
        name=portfolio_in.name,
        portfolio_type=portfolio_in.portfolio_type,
        description=portfolio_in.description,
        model_id=portfolio_in.model_id,
        rebalance_frequency=portfolio_in.rebalance_frequency,
        initial_capital=portfolio_in.initial_capital,
        current_capital=portfolio_in.initial_capital,
        inception_date=inception_date,
        positions=positions,
        created_by=portfolio_in.created_by,
    )
    portfolio_id = await service.create_portfolio(portfolio)
    return Response.success(data=portfolio_id, message="组合创建成功")


@router.post("/from-model", response_model=Response[str], summary="策略模型转模拟组合")
async def create_portfolio_from_model(
    model_id: str,
    inception_date: datetime,
    name: str,
    initial_capital: float = 10_000_000.0,
    service: PortfolioService = Depends(get_portfolio_service),
):
    """
    根据已发布的策略模型创建模拟组合
    
    流程：
    1. 验证模型状态
    2. 设置起始日期（建仓日）
    3. 调用回测引擎，从建仓日追溯到当前的所有持仓记录和业绩表现
    4. 创建并保存模拟组合
    """
    try:
        portfolio_id = await service.create_from_model(
            model_id=model_id,
            inception_date=inception_date,
            name=name,
            initial_capital=initial_capital
        )
        return Response.success(data=portfolio_id, message="模拟组合创建成功（已完成历史追溯）")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"组合创建失败: {str(e)}")


@router.post("/maintenance/daily-batch", response_model=Response[bool], summary="每日批量维护（定时任务调用）")
async def run_daily_maintenance(service: PortfolioService = Depends(get_portfolio_service)):
    """
    批量执行模拟组合的每日维护任务：
    - 检查并触发关联模型的调仓
    - 更新所有组合的最新业绩表现
    """
    await service.run_daily_batch_maintenance()
    return Response.success(data=True, message="批量维护任务执行成功")


@router.get("/", response_model=Response[List[PortfolioOut]], summary="模拟组合列表")
async def list_portfolios(service: PortfolioService = Depends(get_portfolio_service)):
    portfolios = await service.list_portfolios()
    
    data = []
    for p in portfolios:
        p_dict = p.dict()
        # 扁平化业绩指标
        if p.performance:
            p_dict.update({
                "total_return": p.performance.total_return,
                "annual_return": p.performance.annual_return,
                "max_drawdown": p.performance.max_drawdown,
                "sharpe_ratio": p.performance.sharpe_ratio,
                "latest_unit_value": p.performance.latest_unit_value
            })
        data.append(PortfolioOut(**p_dict))
        
    return Response.success(data=data)


@router.get("/{portfolio_id}", response_model=Response[PortfolioOut], summary="获取单个组合")
async def get_portfolio(portfolio_id: str, service: PortfolioService = Depends(get_portfolio_service)):
    portfolio = await service.get_portfolio(portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"组合不存在: {portfolio_id}")
    
    p_dict = portfolio.dict()
    if portfolio.performance:
        p_dict.update({
            "total_return": portfolio.performance.total_return,
            "annual_return": portfolio.performance.annual_return,
            "max_drawdown": portfolio.performance.max_drawdown,
            "sharpe_ratio": portfolio.performance.sharpe_ratio,
            "latest_unit_value": portfolio.performance.latest_unit_value
        })
        
    return Response.success(data=PortfolioOut(**p_dict))


@router.post("/{portfolio_id}/rebalance", response_model=Response[str], summary="记录调仓")
async def add_rebalance_record(
    portfolio_id: str,
    record_in: RebalanceCreate,
    service: PortfolioService = Depends(get_portfolio_service),
):
    record = RebalanceRecord(
        portfolio_id=portfolio_id,
        rebalance_date=record_in.rebalance_date,
        action=record_in.action,
        positions_before=[Position(**p.dict()) for p in record_in.positions_before],
        positions_after=[Position(**p.dict()) for p in record_in.positions_after],
        reason=record_in.reason,
    )
    record_id = await service.add_rebalance_record(record)
    return Response.success(data=record_id, message="调仓记录成功")


@router.get("/{portfolio_id}/rebalance-records", response_model=Response[List[RebalanceCreate]], summary="调仓记录列表")
async def list_rebalance_records(portfolio_id: str, service: PortfolioService = Depends(get_portfolio_service)):
    records = await service.list_rebalance_records(portfolio_id)
    # 这里为了前端复用,使用与创建时相同的模型结构进行返回
    data = [
        RebalanceCreate(
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
            ],
            positions_after=[
                PositionIn(
                    asset_code=p.asset_code,
                    asset_name=p.asset_name,
                    weight=p.weight,
                    shares=p.shares,
                )
                for p in r.positions_after
            ],
        )
        for r in records
    ]
    return Response.success(data=data)


@router.get("/{portfolio_id}/details", response_model=Response[PortfolioDetailOut], summary="获取组合详情")
async def get_portfolio_details(portfolio_id: str, service: PortfolioService = Depends(get_portfolio_service)):
    """
    获取组合详情页所需的所有数据，包括：
    - 基础信息
    - 核心业绩指标
    - 净值曲线
    - 当前持仓占比
    """
    portfolio = await service.get_portfolio(portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"组合不存在: {portfolio_id}")
    
    # 实时计算最新业绩表现
    performance = await service.compute_performance(portfolio_id)
    
    # 构造当前持仓输出
    from app.schemas.strategy_model import AssetPositionOut
    current_holdings = [
        AssetPositionOut(
            asset_code=p.asset_code,
            asset_name=p.asset_name,
            weight=p.weight,
            market_value=p.market_value,
            price=p.price
        )
        for p in portfolio.positions
    ]
    
    detail = PortfolioDetailOut(
        id=str(portfolio.id),
        name=portfolio.name,
        portfolio_type=portfolio.portfolio_type,
        description=portfolio.description,
        inception_date=portfolio.inception_date,
        initial_capital=portfolio.initial_capital,
        current_capital=portfolio.current_capital,
        metrics=performance,
        current_holdings=current_holdings
    )
    
    return Response.success(data=detail)


from app.schemas.strategy_model import BacktestResultOut

@router.get("/{portfolio_id}/analysis", response_model=Response[BacktestResultOut], summary="组合分析")
async def get_portfolio_analysis(portfolio_id: str, service: PortfolioService = Depends(get_portfolio_service)):
    """返回组合当前的业绩指标及净值曲线，数据结构与回测结果完全一致"""
    performance = await service.compute_performance(portfolio_id)
    return Response.success(data=performance)


@router.delete("/{portfolio_id}", response_model=Response[bool], summary="删除模拟组合")
async def delete_portfolio(
    portfolio_id: str,
    service: PortfolioService = Depends(get_portfolio_service)
):
    """删除模拟组合及其所有相关的调仓记录"""
    # 验证 ID 格式
    if not ObjectId.is_valid(portfolio_id):
        raise HTTPException(status_code=400, detail=f"无效的组合ID格式: {portfolio_id}")
        
    success = await service.delete_portfolio(portfolio_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"组合不存在或删除失败: {portfolio_id}")
        
    return Response.success(data=True, message="组合及相关记录已删除")
