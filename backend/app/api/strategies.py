"""策略服务API - 提供策略注册、参数Schema、权重计算等接口"""
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field

from app.schemas.response import Response
from app.services.market_service import MarketService
from app.strategies.services.registry import create_strategy_service_from_database
from app.strategies.services.strategy_service import StrategyService


router = APIRouter()


# ==================== Pydantic模型定义 ====================

class WeightCalculationRequest(BaseModel):
    """权重计算请求"""
    strategy_type: str = Field(..., description="策略类型（如 risk_parity, mean_variance）")
    thscodes: List[str] = Field(..., description="资产代码列表")
    start_date: str = Field(..., description="开始日期（格式：YYYYMMDD）")
    end_date: str = Field(..., description="结束日期（格式：YYYYMMDD）")
    params: Dict[str, Any] = Field(default_factory=dict, description="策略参数字典")


class WeightCalculationResponse(BaseModel):
    """权重计算响应"""
    thscodes: List[str] = Field(..., description="资产代码列表")
    weights: List[float] = Field(..., description="对应权重列表")
    timestamp: str = Field(..., description="计算时间戳")
    strategy_type: str = Field(..., description="策略类型")
    params_used: Dict[str, Any] = Field(..., description="实际使用的参数")


class StrategyTypeInfo(BaseModel):
    """策略类型信息"""
    type: str = Field(..., description="策略类型标识")
    display_name: str = Field(..., description="显示名称")
    description: str = Field(..., description="策略描述")


class ParamValidationRequest(BaseModel):
    """参数验证请求"""
    strategy_type: str = Field(..., description="策略类型")
    params: Dict[str, Any] = Field(..., description="待验证的参数")


class ParamValidationResponse(BaseModel):
    """参数验证响应"""
    valid: bool = Field(..., description="是否有效")
    errors: List[str] = Field(default_factory=list, description="错误信息列表")
    warnings: List[str] = Field(default_factory=list, description="警告信息列表")


# ==================== 依赖注入 ====================

_strategy_service_instance: StrategyService | None = None
_service_init_lock = False  # 锁，防止并发初始化


async def get_strategy_service() -> StrategyService:
    """获取策略服务实例（单例，从数据库加载）"""
    global _strategy_service_instance, _service_init_lock
    
    if _strategy_service_instance is None:
        if _service_init_lock:
            # 等待初始化完成
            import asyncio
            while _service_init_lock:
                await asyncio.sleep(0.01)
            return _strategy_service_instance
        
        _service_init_lock = True
        try:
            # 创建 MarketService
            market_service = MarketService()
            
            # 从数据库创建策略服务
            _strategy_service_instance = await create_strategy_service_from_database(
                market_service=market_service,
                config_file="data/strategy_configs.json"
            )
        finally:
            _service_init_lock = False
    
    return _strategy_service_instance


# ==================== API路由 ====================

@router.get("/types", response_model=Response[List[str]], summary="获取所有策略类型")
async def list_strategy_types(
    service: StrategyService = Depends(get_strategy_service)
):
    """
    获取所有已注册的策略类型列表
    
    返回策略类型标识列表，如：["risk_parity", "mean_variance", "risk_budget_target_vol"]
    """
    types = service.list_strategy_types()
    return Response.success(data=types)


@router.get("/types/{strategy_type}/schema", response_model=Response[Dict[str, Any]], summary="获取策略参数Schema")
async def get_strategy_schema(
    strategy_type: str,
    service: StrategyService = Depends(get_strategy_service)
):
    """
    获取指定策略的参数Schema定义
    
    Schema包含：
    - strategy_type: 策略类型
    - display_name: 显示名称
    - description: 策略描述
    - params: 参数列表（每个参数包含名称、类型、默认值、范围等）
    """
    try:
        schema = service.get_param_schema(strategy_type)
        return Response.success(data=schema)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/schemas", response_model=Response[Dict[str, Dict[str, Any]]], summary="获取所有策略参数Schema")
async def get_all_schemas(
    service: StrategyService = Depends(get_strategy_service)
):
    """
    获取所有已注册策略的参数Schema
    
    返回格式：{strategy_type: schema_dict}
    """
    schemas = service.get_all_param_schemas()
    return Response.success(data=schemas)


@router.post("/validate", response_model=Response[ParamValidationResponse], summary="验证策略参数")
async def validate_params(
    request: ParamValidationRequest = Body(...),
    service: StrategyService = Depends(get_strategy_service)
):
    """
    验证策略参数是否符合Schema定义
    
    返回验证结果，包括：
    - valid: 是否有效
    - errors: 错误信息列表
    - warnings: 警告信息列表
    """
    result = service.validate_params(request.strategy_type, request.params)
    response = ParamValidationResponse(**result)
    return Response.success(data=response)


@router.post("/compute-weights", response_model=Response[WeightCalculationResponse], summary="计算策略权重")
async def compute_weights(
    request: WeightCalculationRequest = Body(...),
    service: StrategyService = Depends(get_strategy_service)
):
    """
    计算策略权重（无状态接口）
    
    根据提供的策略类型、资产池、日期区间和参数，计算资产配置权重。
    
    注意：
    - start_date 和 end_date 格式为 YYYYMMDD（如 20230101）
    - params 中的参数必须符合策略的Schema定义
    - 返回的权重已归一化（和为1）
    """
    try:
        result = await service.compute_weights(
            strategy_type=request.strategy_type,
            thscodes=request.thscodes,
            start_date=request.start_date,
            end_date=request.end_date,
            params=request.params
        )
        
        response = WeightCalculationResponse(**result)
        return Response.success(data=response, message="权重计算成功")
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/info", response_model=Response[List[StrategyTypeInfo]], summary="获取策略类型信息列表")
async def get_strategy_info(
    service: StrategyService = Depends(get_strategy_service)
):
    """
    获取所有策略的基本信息（类型、名称、描述）
    
    用于前端展示策略列表、选择器等场景
    """
    schemas = service.get_all_param_schemas()
    
    info_list = []
    for strategy_type, schema in schemas.items():
        info = StrategyTypeInfo(
            type=strategy_type,
            display_name=schema.get("display_name", strategy_type),
            description=schema.get("description", "")
        )
        info_list.append(info)
    
    return Response.success(data=info_list)
