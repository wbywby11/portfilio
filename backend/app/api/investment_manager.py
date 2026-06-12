"""投资经理相关路由"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId

from app.schemas.investment_manager import (
    InvestmentManagerCreate,
    InvestmentManagerUpdate,
    InvestmentManagerOut,
)
from app.schemas.response import Response
from app.services.investment_manager_service import InvestmentManagerService
from app.models.investment_manager import (
    InvestmentManager, ManagerLevel, ExpertiseDomain, RiskAppetite
)


router = APIRouter()


def validate_object_id(id_str: str) -> str:
    """验证ObjectId格式"""
    if not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=400,
            detail=f"无效的ID格式: {id_str}, 必须是24位十六进制字符串"
        )
    return id_str


def get_investment_manager_service() -> InvestmentManagerService:
    return InvestmentManagerService()


@router.post("/", response_model=Response[str], summary="创建投资经理")
async def create_manager(
    manager_in: InvestmentManagerCreate,
    service: InvestmentManagerService = Depends(get_investment_manager_service),
):
    """创建投资经理"""
    # 检查经理代码是否已存在
    existing = await service.get_manager_by_code(manager_in.manager_code)
    if existing:
        raise HTTPException(status_code=400, detail=f"经理代码已存在: {manager_in.manager_code}")

    manager = InvestmentManager(**manager_in.dict())
    manager_id = await service.create_manager(manager)
    return Response.success(data=manager_id, message="投资经理创建成功")


@router.get("/", response_model=Response[List[InvestmentManagerOut]], summary="投资经理列表")
async def list_managers(
    level: str | None = Query(None, description="职级过滤"),
    expertise: str | None = Query(None, description="专长领域过滤"),
    risk_appetite: str | None = Query(None, description="风险偏好过滤"),
    is_active: bool | None = Query(True, description="是否启用，None表示查询所有"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=500, description="返回记录数"),
    service: InvestmentManagerService = Depends(get_investment_manager_service),
):
    """查询投资经理列表，支持按职级、专长领域、风险偏好和启用状态筛选"""
    level_filter = None
    if level and level.strip():
        try:
            level_filter = ManagerLevel(level)
        except ValueError:
            valid = [v.value for v in ManagerLevel]
            raise HTTPException(status_code=400, detail=f"无效的职级: {level}，有效值为: {valid}")

    expertise_filter = None
    if expertise and expertise.strip():
        try:
            expertise_filter = ExpertiseDomain(expertise)
        except ValueError:
            valid = [v.value for v in ExpertiseDomain]
            raise HTTPException(status_code=400, detail=f"无效的专长领域: {expertise}，有效值为: {valid}")

    risk_filter = None
    if risk_appetite and risk_appetite.strip():
        try:
            risk_filter = RiskAppetite(risk_appetite)
        except ValueError:
            valid = [v.value for v in RiskAppetite]
            raise HTTPException(status_code=400, detail=f"无效的风险偏好: {risk_appetite}，有效值为: {valid}")

    managers = await service.list_managers(
        level=level_filter,
        expertise=expertise_filter,
        risk_appetite=risk_filter,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )
    data = [InvestmentManagerOut(**m.dict()) for m in managers]
    return Response.success(data=data)


@router.get("/{manager_id}", response_model=Response[InvestmentManagerOut], summary="获取单个投资经理")
async def get_manager(
    manager_id: str,
    service: InvestmentManagerService = Depends(get_investment_manager_service),
):
    """获取单个投资经理详情"""
    validate_object_id(manager_id)
    manager = await service.get_manager(manager_id)
    if not manager:
        raise HTTPException(status_code=404, detail=f"投资经理不存在: {manager_id}")
    return Response.success(data=InvestmentManagerOut(**manager.dict()))


@router.put("/{manager_id}", response_model=Response[bool], summary="更新投资经理")
async def update_manager(
    manager_id: str,
    manager_update: InvestmentManagerUpdate,
    service: InvestmentManagerService = Depends(get_investment_manager_service),
):
    """更新投资经理信息，仅更新提供的字段"""
    validate_object_id(manager_id)

    existing = await service.get_manager(manager_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"投资经理不存在: {manager_id}")

    update_data = manager_update.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有提供任何要更新的字段")

    success = await service.update_manager(manager_id, update_data)
    if not success:
        raise HTTPException(status_code=500, detail="投资经理更新失败")
    return Response.success(data=success, message="投资经理更新成功")


@router.delete("/{manager_id}", response_model=Response[bool], summary="删除投资经理")
async def delete_manager(
    manager_id: str,
    service: InvestmentManagerService = Depends(get_investment_manager_service),
):
    """删除投资经理（软删除）"""
    validate_object_id(manager_id)
    success = await service.delete_manager(manager_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"投资经理不存在: {manager_id}")
    return Response.success(data=success, message="投资经理删除成功")
