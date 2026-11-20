"""数据分析服务API - 提供资产指标、相关性、时间序列分析等接口"""
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas.response import Response
from app.services.market_service import MarketService
from app.services.asset_service import AssetService
from app.analysis.service import AnalysisService
from app.analysis.config import AnalysisConfig


router = APIRouter()


# ==================== Pydantic模型定义 ====================

class AnalysisRequest(BaseModel):
    """数据分析请求"""
    thscodes: List[str] = Field(..., description="资产代码列表")
    start_date: str = Field(..., description="开始日期（格式：YYYYMMDD）")
    end_date: str = Field(..., description="结束日期（格式：YYYYMMDD）")


class AssetMetricsOut(BaseModel):
    """资产指标输出"""
    thscode: str = Field(..., description="资产代码")
    name: str = Field(..., description="资产名称")
    annual_return: float = Field(..., description="年化收益率")
    annual_volatility: float = Field(..., description="年化波动率")
    sharpe_ratio: float = Field(..., description="夏普比率")
    max_drawdown: float = Field(..., description="最大回撤")
    calmar_ratio: float = Field(..., description="卡玛比率")
    total_return: float = Field(..., description="累计收益率")
    # 365 口径（自然日/年）：与 260 口径并列返回
    annual_return_365: Optional[float] = Field(None, description="年化收益率（365 自然日口径）")
    annual_volatility_365: Optional[float] = Field(None, description="年化波动率（365 自然日口径）")
    sharpe_ratio_365: Optional[float] = Field(None, description="夏普比率（365 自然日口径）")
    calmar_ratio_365: Optional[float] = Field(None, description="卡玛比率（365 自然日口径）")


class CorrelationMatrixOut(BaseModel):
    """相关性矩阵输出"""
    matrix: Dict[str, Dict[str, float]] = Field(..., description="相关性矩阵")
    asset_info: List[Dict[str, str]] = Field(..., description="资产信息列表（包含代码和名称）")
    method: str = Field(..., description="计算方法")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")


class TimeSeriesPoint(BaseModel):
    """时间序列数据点"""
    date: str = Field(..., description="日期（YYYY-MM-DD）")
    value: float = Field(..., description="值")


class TimeSeriesDataOut(BaseModel):
    """时间序列数据输出"""
    thscode: str = Field(..., description="资产代码")
    name: str = Field(..., description="资产名称")
    nav: List[TimeSeriesPoint] = Field(..., description="累计净值序列")
    drawdown: List[TimeSeriesPoint] = Field(..., description="回撤序列")
    returns: List[TimeSeriesPoint] = Field(..., description="收益率序列")


class DashboardDataOut(BaseModel):
    """看板数据输出"""
    asset_metrics: List[AssetMetricsOut] = Field(..., description="资产指标列表")
    correlation_matrix: CorrelationMatrixOut = Field(..., description="相关性矩阵")
    timeseries_data: List[TimeSeriesDataOut] = Field(..., description="时间序列数据列表")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")


# ==================== 依赖注入 ====================

def get_analysis_service() -> AnalysisService:
    """获取数据分析服务实例"""
    market_service = MarketService()
    config = AnalysisConfig()
    return AnalysisService(data_service=market_service, config=config)


async def get_asset_names(thscodes: List[str]) -> Dict[str, str]:
    """
    获取资产名称映射
    
    Args:
        thscodes: 资产代码列表
    
    Returns:
        {thscode: name} 字典
    """
    asset_service = AssetService()
    name_map = {}
    
    for thscode in thscodes:
        asset = await asset_service.get_asset_by_code(thscode)
        if asset:
            name_map[thscode] = asset.name
        else:
            name_map[thscode] = thscode  # 如果找不到，使用代码作为名称
    
    return name_map


# ==================== API路由 ====================

@router.post("/dashboard", response_model=Response[DashboardDataOut], summary="生成完整看板数据")
async def generate_dashboard(
    request: AnalysisRequest,
    correlation_method: str = Query("pearson", description="相关性计算方法（pearson/spearman/kendall）"),
    service: AnalysisService = Depends(get_analysis_service)
):
    """
    生成完整的数据分析看板
    
    一次性返回：
    - 资产指标（年化收益、波动率、夏普比率、最大回撤等）
    - 相关性矩阵（资产间相关性）
    - 时间序列数据（净值曲线、回撤曲线、收益率）
    
    适用于前端看板展示、数据总览等场景。
    """
    try:
        # 调用分析服务
        dashboard = await service.generate_dashboard(
            thscodes=request.thscodes,
            start_date=request.start_date,
            end_date=request.end_date,
            correlation_method=correlation_method
        )
        
        # 获取资产名称
        asset_names = await get_asset_names(request.thscodes)
        
        # 转换为输出格式
        asset_metrics_out = [
            AssetMetricsOut(
                thscode=thscode,
                name=asset_names.get(thscode, thscode),
                annual_return=metrics.annualized_return,
                annual_volatility=metrics.annualized_volatility,
                sharpe_ratio=metrics.sharpe_ratio,
                max_drawdown=metrics.max_drawdown,
                calmar_ratio=metrics.calmar_ratio,
                total_return=metrics.cumulative_return,
                annual_return_365=metrics.annualized_return_365,
                annual_volatility_365=metrics.annualized_volatility_365,
                sharpe_ratio_365=metrics.sharpe_ratio_365,
                calmar_ratio_365=metrics.calmar_ratio_365,
            )
            for thscode, metrics in dashboard.asset_metrics.items()
        ]
        
        # 转换相关性矩阵
        correlation_matrix_out = CorrelationMatrixOut(
            matrix={
                row: {col: float(dashboard.correlation_matrix.matrix.loc[row, col]) 
                      for col in dashboard.correlation_matrix.matrix.columns}
                for row in dashboard.correlation_matrix.matrix.index
            },
            asset_info=[
                {"thscode": thscode, "name": asset_names.get(thscode, thscode)}
                for thscode in dashboard.correlation_matrix.matrix.index
            ],
            method=dashboard.correlation_matrix.method,
            start_date=dashboard.correlation_matrix.start_date,
            end_date=dashboard.correlation_matrix.end_date
        )
        
        # 转换时间序列数据
        timeseries_data_out = []
        for thscode, ts_data in dashboard.timeseries_data.items():
            timeseries_data_out.append(TimeSeriesDataOut(
                thscode=thscode,
                name=asset_names.get(thscode, thscode),
                nav=[
                    TimeSeriesPoint(date=str(idx.date()), value=float(val))
                    for idx, val in ts_data.nav.items()
                ],
                drawdown=[
                    TimeSeriesPoint(date=str(idx.date()), value=float(val))
                    for idx, val in ts_data.drawdown.items()
                ],
                returns=[
                    TimeSeriesPoint(date=str(idx.date()), value=float(val))
                    for idx, val in ts_data.returns.items()
                ]
            ))
        
        result = DashboardDataOut(
            asset_metrics=asset_metrics_out,
            correlation_matrix=correlation_matrix_out,
            timeseries_data=timeseries_data_out,
            start_date=dashboard.start_date,
            end_date=dashboard.end_date
        )
        
        return Response.success(data=result, message="看板数据生成成功")
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据分析失败: {str(e)}")


@router.post("/asset-metrics", response_model=Response[List[AssetMetricsOut]], summary="获取资产指标")
async def get_asset_metrics(
    request: AnalysisRequest,
    service: AnalysisService = Depends(get_analysis_service)
):
    """
    获取资产统计指标
    
    返回每个资产的：
    - 年化收益率
    - 年化波动率
    - 夏普比率
    - 最大回撤
    - 卡玛比率
    - 累计收益率
    """
    try:
        metrics_dict = await service.get_asset_metrics(
            thscodes=request.thscodes,
            start_date=request.start_date,
            end_date=request.end_date
        )
        
        # 获取资产名称
        asset_names = await get_asset_names(request.thscodes)
        
        result = [
            AssetMetricsOut(
                thscode=thscode,
                name=asset_names.get(thscode, thscode),
                annual_return=metrics.annualized_return,
                annual_volatility=metrics.annualized_volatility,
                sharpe_ratio=metrics.sharpe_ratio,
                max_drawdown=metrics.max_drawdown,
                calmar_ratio=metrics.calmar_ratio,
                total_return=metrics.cumulative_return,
                annual_return_365=metrics.annualized_return_365,
                annual_volatility_365=metrics.annualized_volatility_365,
                sharpe_ratio_365=metrics.sharpe_ratio_365,
                calmar_ratio_365=metrics.calmar_ratio_365,
            )
            for thscode, metrics in metrics_dict.items()
        ]
        
        return Response.success(data=result, message="资产指标计算成功")
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"资产指标计算失败: {str(e)}")


@router.post("/correlation-matrix", response_model=Response[CorrelationMatrixOut], summary="获取相关性矩阵")
async def get_correlation_matrix(
    request: AnalysisRequest,
    method: str = Query("pearson", description="相关性计算方法（pearson/spearman/kendall）"),
    service: AnalysisService = Depends(get_analysis_service)
):
    """
    获取资产相关性矩阵
    
    支持的相关性计算方法：
    - pearson: 皮尔逊相关系数（线性相关）
    - spearman: 斯皮尔曼等级相关系数（单调相关）
    - kendall: 肯德尔等级相关系数
    """
    try:
        correlation = await service.get_correlation_matrix(
            thscodes=request.thscodes,
            start_date=request.start_date,
            end_date=request.end_date,
            method=method
        )
        
        # 获取资产名称
        asset_names = await get_asset_names(request.thscodes)
        
        result = CorrelationMatrixOut(
            matrix={
                row: {col: float(correlation.matrix.loc[row, col]) 
                      for col in correlation.matrix.columns}
                for row in correlation.matrix.index
            },
            asset_info=[
                {"thscode": thscode, "name": asset_names.get(thscode, thscode)}
                for thscode in correlation.matrix.index
            ],
            method=correlation.method,
            start_date=correlation.start_date,
            end_date=correlation.end_date
        )
        
        return Response.success(data=result, message="相关性矩阵计算成功")
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"相关性矩阵计算失败: {str(e)}")


@router.post("/timeseries", response_model=Response[List[TimeSeriesDataOut]], summary="获取时间序列数据")
async def get_timeseries_data(
    request: AnalysisRequest,
    service: AnalysisService = Depends(get_analysis_service)
):
    """
    获取时间序列数据
    
    返回每个资产的：
    - 累计净值序列（归一化，初始值=1）
    - 回撤序列（负值）
    - 收益率序列
    """
    try:
        timeseries_dict = await service.get_timeseries_data(
            thscodes=request.thscodes,
            start_date=request.start_date,
            end_date=request.end_date
        )
        
        # 获取资产名称
        asset_names = await get_asset_names(request.thscodes)
        
        result = []
        for thscode, ts_data in timeseries_dict.items():
            result.append(TimeSeriesDataOut(
                thscode=thscode,
                name=asset_names.get(thscode, thscode),
                nav=[
                    TimeSeriesPoint(date=str(idx.date()), value=float(val))
                    for idx, val in ts_data.nav.items()
                ],
                drawdown=[
                    TimeSeriesPoint(date=str(idx.date()), value=float(val))
                    for idx, val in ts_data.drawdown.items()
                ],
                returns=[
                    TimeSeriesPoint(date=str(idx.date()), value=float(val))
                    for idx, val in ts_data.returns.items()
                ]
            ))
        
        return Response.success(data=result, message="时间序列数据获取成功")
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"时间序列数据获取失败: {str(e)}")
