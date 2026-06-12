"""交易日历 API 路由"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Path, Query, UploadFile

from app.schemas.response import Response
from app.services.trade_calendar_service import TradeCalendarService


def get_trade_calendar_service() -> TradeCalendarService:
    return TradeCalendarService()


router = APIRouter()


@router.post("/import", response_model=Response[dict], summary="导入交易日历")
async def import_trade_calendar(
    file: UploadFile = File(..., description="交易日历 Excel 文件"),
    mode: str = Form(
        "incremental",
        description="replace=清空后全量导入；incremental=仅新增不存在的日期",
    ),
    service: TradeCalendarService = Depends(get_trade_calendar_service),
):
    """从 Excel 文件导入交易日历"""
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="请上传 .xlsx 或 .xls 格式的 Excel 文件",
        )

    content = await file.read()
    try:
        result = await service.import_from_excel(content, mode=mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    msg_mode = "全量覆盖" if result["mode"] == "replace" else "增量导入"
    message = (
        f"{msg_mode}完成：新增 {result['inserted_count']} 条，"
        f"跳过 {result['skipped_count']} 条，文件共 {result['total_in_file']} 条"
    )
    return Response.success(data=result, message=message)


@router.post("/manual", response_model=Response[dict], summary="手动添加交易日期")
async def add_trade_dates(
    data: Dict[str, Any] = Body(
        ...,
        example={"dates": ["2026-01-05", "2026-01-06"]},
        description="支持 {date: 'YYYY-MM-DD'} 或 {dates: ['YYYY-MM-DD', ...]}",
    ),
    service: TradeCalendarService = Depends(get_trade_calendar_service),
):
    """手动添加交易日期（支持单个或批量）"""
    if data is None or not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")

    dates: List[str] = []
    if "dates" in data and isinstance(data["dates"], list):
        dates = [str(x) for x in data["dates"] if x is not None]
    elif "date" in data and data["date"] is not None:
        dates = [str(data["date"])]

    if not dates:
        raise HTTPException(
            status_code=400,
            detail="请提供 date 或 dates 字段（YYYY-MM-DD 格式）",
        )

    try:
        result = await service.add_dates(dates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return Response.success(
        data=result,
        message=f"已添加 {result['inserted_count']} 条，跳过 {result['skipped_count']} 条",
    )


@router.delete("/{date}", response_model=Response[dict], summary="删除交易日期")
async def delete_trade_date(
    date: str = Path(..., description="待删除的交易日期 YYYY-MM-DD"),
    service: TradeCalendarService = Depends(get_trade_calendar_service),
):
    """删除指定交易日期"""
    try:
        result = await service.delete_date(date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if result["deleted_count"] == 0:
        return Response.success(data=result, message=f"未找到日期 {date}")
    return Response.success(data=result, message=f"已删除 {date}")


@router.get("/stats", response_model=Response[dict], summary="交易日历统计")
async def get_stats(
    service: TradeCalendarService = Depends(get_trade_calendar_service),
):
    """获取交易日历统计信息（总数、起止日期、本年数量、最近更新）"""
    stats = await service.get_stats()
    return Response.success(data=stats)


@router.get("/dates", response_model=Response[dict], summary="获取交易日期列表")
async def get_dates(
    year: Optional[int] = Query(None, description="按年份过滤（可选）"),
    service: TradeCalendarService = Depends(get_trade_calendar_service),
):
    """获取交易日期列表，可按年份过滤"""
    dates = await service.get_dates_by_year(year=year)
    return Response.success(data={"dates": dates, "count": len(dates)})
