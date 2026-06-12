"""业绩基准相关路由"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId

from app.schemas.benchmark import (
    PerformanceBenchmarkCreate,
    PerformanceBenchmarkUpdate,
    PerformanceBenchmarkOut
)
from app.schemas.response import Response
from app.services.benchmark_service import BenchmarkService
from app.models.benchmark import PerformanceBenchmark, BenchmarkType


router = APIRouter()


def validate_object_id(id_str: str) -> str:
    """验证ObjectId格式"""
    if not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=400,
            detail=f"无效的ID格式: {id_str}, 必须是24位十六进制字符串"
        )
    return id_str


def get_benchmark_service() -> BenchmarkService:
    return BenchmarkService()


@router.get("/", response_model=Response[List[PerformanceBenchmarkOut]], summary="业绩基准列表")
async def list_benchmarks(
    benchmark_type: str | None = Query(None, description="基准类型(单一基准/复合基准/绝对基准)，空字符串表示不筛选"),
    is_active: bool | None = Query(True, description="是否启用，None表示查询所有"),
    service: BenchmarkService = Depends(get_benchmark_service),
):
    """查询业绩基准列表，支持按类型和启用状态筛选"""
    # 将空字符串转换为 None（不筛选）
    type_filter = None
    if benchmark_type and benchmark_type.strip():
        try:
            type_filter = BenchmarkType(benchmark_type)
        except ValueError:
            valid_types = [t.value for t in BenchmarkType]
            raise HTTPException(
                status_code=400,
                detail=f"无效的基准类型: {benchmark_type}，有效值为: {valid_types}"
            )
    
    benchmarks = await service.list_benchmarks(
        benchmark_type=type_filter,
        is_active=is_active
    )
    data = [PerformanceBenchmarkOut(**b.dict()) for b in benchmarks]
    return Response.success(data=data)


@router.post("/", response_model=Response[str], summary="创建业绩基准")
async def create_benchmark(
    benchmark_in: PerformanceBenchmarkCreate,
    service: BenchmarkService = Depends(get_benchmark_service),
):
    """创建业绩基准"""
    # 验证复合基准的权重总和和绝对基准的固定收益率
    if benchmark_in.benchmark_type == BenchmarkType.COMPOSITE and benchmark_in.components:
        total_weight = sum(comp.weight for comp in benchmark_in.components)
        if abs(total_weight - 1.0) > 0.001:  # 允许微小误差
            raise HTTPException(
                status_code=400,
                detail=f"复合基准权重总和必须为1，当前总和为: {total_weight:.4f}"
            )
    elif benchmark_in.benchmark_type == BenchmarkType.ABSOLUTE:
        if benchmark_in.fixed_return is None:
            raise HTTPException(
                status_code=400,
                detail="绝对基准必须提供固定收益率"
            )
    
    benchmark = PerformanceBenchmark(**benchmark_in.dict())
    benchmark_id = await service.create_benchmark(benchmark)
    return Response.success(data=benchmark_id, message="业绩基准创建成功")


@router.get("/{benchmark_id}", response_model=Response[PerformanceBenchmarkOut], summary="获取单个业绩基准")
async def get_benchmark(
    benchmark_id: str,
    service: BenchmarkService = Depends(get_benchmark_service)
):
    """获取单个业绩基准详情"""
    validate_object_id(benchmark_id)
    benchmark = await service.get_benchmark(benchmark_id)
    if not benchmark:
        raise HTTPException(status_code=404, detail=f"业绩基准不存在: {benchmark_id}")
    return Response.success(data=PerformanceBenchmarkOut(**benchmark.dict()))


@router.put("/{benchmark_id}", response_model=Response[bool], summary="更新业绩基准")
async def update_benchmark(
    benchmark_id: str,
    benchmark_update: PerformanceBenchmarkUpdate,
    service: BenchmarkService = Depends(get_benchmark_service)
):
    """
    更新业绩基准信息
    
    注意：
    - 仅更新提供的字段，未提供的字段保持不变
    - 对于复合基准，权重总和必须为1
    - 对于绝对基准，必须提供固定收益率
    """
    validate_object_id(benchmark_id)
    
    # 检查基准是否存在
    existing_benchmark = await service.get_benchmark(benchmark_id)
    if not existing_benchmark:
        raise HTTPException(status_code=404, detail=f"业绩基准不存在: {benchmark_id}")
    
    # 验证复合基准的权重总和和绝对基准的固定收益率
    update_data = benchmark_update.dict(exclude_unset=True)
    
    # 获取实际的基准类型（优先使用更新数据中的类型，否则使用现有类型）
    actual_type_str = update_data.get('benchmark_type', str(existing_benchmark.benchmark_type))
    
    # 尝试将字符串转换为枚举
    try:
        if actual_type_str in [t.value for t in BenchmarkType]:
            # 如果是中文描述，需要映射回枚举
            for t in BenchmarkType:
                if t.value == actual_type_str:
                    actual_type = t
                    break
        else:
            actual_type = BenchmarkType(actual_type_str)
    except ValueError:
        actual_type = existing_benchmark.benchmark_type  # 如果无法转换，使用现有类型
    
    if actual_type == BenchmarkType.COMPOSITE and 'components' in update_data:
        # 检查组件是字典格式还是对象格式
        if update_data['components'] and isinstance(update_data['components'][0], dict):
            # 如果是字典格式，转换为BenchmarkComponent对象
            from app.models.benchmark import BenchmarkComponent
            components = [BenchmarkComponent(**comp) for comp in update_data['components']]
            total_weight = sum(comp.weight for comp in components)
        else:
            # 如果已经是对象格式
            total_weight = sum(comp.weight for comp in update_data['components'])
        if abs(total_weight - 1.0) > 0.001:
            raise HTTPException(
                status_code=400,
                detail=f"复合基准权重总和必须为1，当前总和为: {total_weight:.4f}"
            )
    elif actual_type == BenchmarkType.ABSOLUTE and 'fixed_return' in update_data:
        if update_data['fixed_return'] is None:
            raise HTTPException(
                status_code=400,
                detail="绝对基准必须提供固定收益率"
            )
    
    if not update_data:
        raise HTTPException(status_code=400, detail="没有提供任何要更新的字段")
    
    success = await service.update_benchmark(benchmark_id, update_data)
    if not success:
        raise HTTPException(status_code=500, detail="业绩基准更新失败")
    
    return Response.success(data=success, message="业绩基准更新成功")


@router.delete("/{benchmark_id}", response_model=Response[bool], summary="删除业绩基准")
async def delete_benchmark(
    benchmark_id: str,
    service: BenchmarkService = Depends(get_benchmark_service)
):
    """
    删除业绩基准（软删除）
    
    注意：此操作不可逆，请谨慎使用
    """
    validate_object_id(benchmark_id)
    success = await service.delete_benchmark(benchmark_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"业绩基准不存在: {benchmark_id}")
    return Response.success(data=success, message="业绩基准删除成功")


@router.get("/by-code/{code}", response_model=Response[PerformanceBenchmarkOut], summary="根据代码获取业绩基准")
async def get_benchmark_by_code(
    code: str,
    service: BenchmarkService = Depends(get_benchmark_service)
):
    """根据代码获取业绩基准"""
    benchmark = await service.get_benchmark_by_code(code)
    if not benchmark:
        raise HTTPException(status_code=404, detail=f"业绩基准不存在: {code}")
    return Response.success(data=PerformanceBenchmarkOut(**benchmark.dict()))