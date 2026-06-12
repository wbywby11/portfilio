"""理财产品相关路由"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from bson import ObjectId

from app.models.financial_product import FinancialProduct, ProductType, RiskLevel, ProductStatus
from app.schemas.financial_product import (
    FinancialProductCreate, FinancialProductUpdate, FinancialProductOut,
)
from app.schemas.response import Response
from app.services.financial_product_service import FinancialProductService


router = APIRouter()


def validate_object_id(id_str: str) -> str:
    """验证ObjectId格式"""
    if not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=400,
            detail=f"无效的ID格式: {id_str}, 必须是24位十六进制字符串"
        )
    return id_str


def get_financial_product_service() -> FinancialProductService:
    return FinancialProductService()


@router.post("", response_model=Response[FinancialProductOut], summary="创建理财产品")
async def create_product(
    product_in: FinancialProductCreate,
    service: FinancialProductService = Depends(get_financial_product_service),
):
    """创建理财产品"""
    try:
        # 检查产品代码是否已存在
        existing = await service.get_product_by_code(product_in.product_code)
        if existing:
            return Response.error(message=f"产品代码已存在: {product_in.product_code}", code=400)

        product = FinancialProduct(**product_in.dict())
        product_id = await service.create_product(product)
        created = await service.get_product(product_id)
        out = FinancialProductOut(**created.dict(by_alias=True))
        return Response.success(data=out, message="创建成功")
    except Exception as e:
        return Response.error(message=f"创建理财产品失败: {str(e)}")


@router.get("", response_model=Response[List[FinancialProductOut]], summary="理财产品列表")
async def list_products(
    product_type: Optional[str] = Query(None, description="产品类型"),
    risk_level: Optional[str] = Query(None, description="风险等级"),
    status: Optional[str] = Query(None, description="产品状态"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=500, description="返回记录数"),
    service: FinancialProductService = Depends(get_financial_product_service),
):
    """查询理财产品列表，支持按产品类型、风险等级、状态过滤"""
    try:
        # 转换枚举参数
        product_type_enum = None
        if product_type and product_type.strip():
            try:
                product_type_enum = ProductType(product_type)
            except ValueError:
                pass

        risk_level_enum = None
        if risk_level and risk_level.strip():
            try:
                risk_level_enum = RiskLevel(risk_level)
            except ValueError:
                pass

        status_enum = None
        if status and status.strip():
            try:
                status_enum = ProductStatus(status)
            except ValueError:
                pass

        products = await service.list_products(
            product_type=product_type_enum,
            risk_level=risk_level_enum,
            status=status_enum,
            skip=skip,
            limit=limit,
        )
        data = [FinancialProductOut(**p.dict(by_alias=True)) for p in products]
        return Response.success(data=data)
    except Exception as e:
        return Response.error(message=f"查询理财产品列表失败: {str(e)}")


@router.get("/{product_id}", response_model=Response[FinancialProductOut], summary="获取单个理财产品")
async def get_product(
    product_id: str,
    service: FinancialProductService = Depends(get_financial_product_service),
):
    """根据ID获取单个理财产品"""
    try:
        validate_object_id(product_id)
        product = await service.get_product(product_id)
        if not product:
            return Response.error(message="理财产品不存在", code=404)
        out = FinancialProductOut(**product.dict(by_alias=True))
        return Response.success(data=out)
    except HTTPException:
        raise
    except Exception as e:
        return Response.error(message=f"获取理财产品失败: {str(e)}")


@router.put("/{product_id}", response_model=Response[FinancialProductOut], summary="更新理财产品")
async def update_product(
    product_id: str,
    product_in: FinancialProductUpdate,
    service: FinancialProductService = Depends(get_financial_product_service),
):
    """更新理财产品"""
    try:
        validate_object_id(product_id)
        existing = await service.get_product(product_id)
        if not existing:
            return Response.error(message="理财产品不存在", code=404)

        update_data = product_in.dict(exclude_unset=True)
        if not update_data:
            return Response.error(message="未提供任何更新字段", code=400)

        await service.update_product(product_id, update_data)
        updated = await service.get_product(product_id)
        out = FinancialProductOut(**updated.dict(by_alias=True))
        return Response.success(data=out, message="更新成功")
    except HTTPException:
        raise
    except Exception as e:
        return Response.error(message=f"更新理财产品失败: {str(e)}")


@router.delete("/{product_id}", response_model=Response, summary="删除理财产品")
async def delete_product(
    product_id: str,
    service: FinancialProductService = Depends(get_financial_product_service),
):
    """软删除理财产品（is_active=False）"""
    try:
        validate_object_id(product_id)
        existing = await service.get_product(product_id)
        if not existing:
            return Response.error(message="理财产品不存在", code=404)

        success = await service.delete_product(product_id)
        if success:
            return Response.success(message="删除成功")
        return Response.error(message="删除失败")
    except HTTPException:
        raise
    except Exception as e:
        return Response.error(message=f"删除理财产品失败: {str(e)}")
