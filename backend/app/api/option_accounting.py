# -*- coding: utf-8 -*-
"""
会计辅助 API 路由

提供会计分录生成、查询、导出和科目配置等功能。
路由前缀: /api/v1/options/accounting (在 main.py 中注册时添加)
"""
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Body
from loguru import logger

from app.schemas.response import Response

router = APIRouter()


def _get_service():
    from app.services.option_pricing_service import OptionPricingService
    return OptionPricingService()


def _get_accounting_service():
    from app.services.option_accounting_service import OptionAccountingService
    return OptionAccountingService()


# ============================================================
# 会计分录生成
# ============================================================

@router.post("/generate", response_model=Response[dict], summary="生成会计分录")
async def generate_accounting_entries(
    date: str = Body(..., description="会计日期 YYYY-MM-DD", embed=True),
):
    """根据指定日期的估值结果自动生成会计分录（日终盯市 + 事件结算）"""
    service = _get_accounting_service()
    try:
        result = await service.generate_entries(date)
        if result.get("error"):
            return Response.error(message=result["error"], data=result)
        return Response.success(data=result, message="生成分录完成")
    except Exception as e:
        logger.error(f"生成会计分录失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成会计分录失败: {str(e)}")


# ============================================================
# 会计分录查询
# ============================================================

@router.get("/entries", response_model=Response[list], summary="查询会计分录")
async def get_accounting_entries(
    date: Optional[str] = Query(None, description="日期 YYYY-MM-DD"),
    product_id: Optional[str] = Query(None, description="产品编号"),
    entry_type: Optional[str] = Query(None, description="分录类型"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
):
    """查询会计分录记录"""
    service = _get_accounting_service()
    try:
        entries = await service.get_entries(
            date=date, product_id=product_id, entry_type=entry_type,
            skip=skip, limit=limit,
        )
        return Response.success(data=entries, message="获取成功")
    except Exception as e:
        logger.error(f"查询会计分录失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询会计分录失败: {str(e)}")


@router.get("/summary", response_model=Response[list], summary="按科目汇总")
async def get_accounting_summary(
    date: str = Query(..., description="日期 YYYY-MM-DD"),
):
    """按科目汇总指定日期的会计分录"""
    service = _get_accounting_service()
    try:
        entries = await service.get_entries(date=date)
        from app.options.accounting import AccountingGenerator
        summary = AccountingGenerator.summarize_by_account(entries)
        return Response.success(data=summary, message="汇总完成")
    except Exception as e:
        logger.error(f"汇总会计分录失败: {e}")
        raise HTTPException(status_code=500, detail=f"汇总会计分录失败: {str(e)}")


# ============================================================
# 导出
# ============================================================

@router.get("/export", summary="导出会计分录为 Excel")
async def export_accounting_entries(
    date: str = Query(..., description="日期 YYYY-MM-DD"),
):
    """导出指定日期的会计分录为 Excel 文件"""
    from fastapi.responses import StreamingResponse
    import io

    service = _get_accounting_service()
    try:
        entries = await service.get_entries(date=date)
        if not entries:
            raise HTTPException(status_code=404, detail=f"无会计分录数据: {date}")

        import pandas as pd
        df = pd.DataFrame(entries)
        # 移除 _id 字段
        df.pop("_id", None)
        # 重命名列为中文
        col_map = {
            "date": "日期", "product_id": "产品编号", "entry_type": "分录类型",
            "debit_account": "借方科目", "credit_account": "贷方科目",
            "amount": "金额", "description": "摘要", "valuation_version": "估值版本",
            "created_at": "生成时间",
        }
        df.rename(columns=col_map, inplace=True)

        output = io.BytesIO()
        df.to_excel(output, index=False, sheet_name="会计分录")
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=accounting_{date}.xlsx"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出会计分录失败: {e}")
        raise HTTPException(status_code=500, detail=f"导出会计分录失败: {str(e)}")


# ============================================================
# 科目配置
# ============================================================

@router.get("/config", response_model=Response[dict], summary="获取科目映射配置")
async def get_accounting_config():
    """获取当前科目映射配置"""
    service = _get_accounting_service()
    try:
        config = await service.get_config()
        return Response.success(data=config, message="获取成功")
    except Exception as e:
        logger.error(f"获取科目配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取科目配置失败: {str(e)}")


@router.put("/config", response_model=Response[bool], summary="更新科目映射配置")
async def update_accounting_config(
    account_map: dict = Body(..., description="科目映射 {key: 科目名称}"),
):
    """更新科目映射配置"""
    service = _get_accounting_service()
    try:
        success = await service.update_config(account_map)
        return Response.success(data=success, message="更新成功")
    except Exception as e:
        logger.error(f"更新科目配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新科目配置失败: {str(e)}")
