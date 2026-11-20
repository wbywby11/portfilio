"""宏观与估值序列导入 API（macro_series 集合）

与 fx 的差别：macro_series 一个集合装多条序列（指数 PE/PB/股息率、债券收益率、
信用/汇率等），所以导入、查询、统计都带 code 维度。
"""
import io
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

import pandas as pd

from app.schemas.field_mappings import MACRO_SERIES_META_SHEET, MACRO_SERIES_TYPES
from app.schemas.response import Response
from app.services.macro_series_service import MacroSeriesService

router = APIRouter()

_SHEET_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def get_macro_series_service() -> MacroSeriesService:
    return MacroSeriesService()


def _read_sheets(contents: bytes) -> dict:
    """读出全部工作表（模板带「序列说明」sheet，不能只读第一张）。"""
    return pd.read_excel(io.BytesIO(contents), sheet_name=None)


@router.post("/import", response_model=Response[dict], summary="导入宏观与估值序列")
async def import_macro_series(
    file: UploadFile = File(
        ...,
        description="Excel：第一列为日期，后续每列列名为序列代码；可带「序列说明」工作表",
    ),
    mode: str = Form(
        "replace",
        description=(
            "replace=按序列覆盖（只清空文件中出现的序列，其他序列不动）；"
            "incremental=只补库内缺失的 (序列, 日期)，已有取值不覆盖"
        ),
    ),
    service: MacroSeriesService = Depends(get_macro_series_service),
):
    """
    导入宏观与估值序列。

    数据表两种形态都接受（自动识别）：

    - **宽表**（官方模板）：第一列日期，后续每列列名为序列代码（如 `H00922_PE`、`CBA_10Y`）
    - **长表**：列含 `序列代码` / `数值` / `日期`（及可选 `序列类型` / `单位` / `来源`）

    可选「序列说明」工作表给每条序列标注 `series_type`（受控词表见
    `field_mappings.MACRO_SERIES_TYPES`）、单位、来源；缺该表时统一按 `other`
    归档并在返回的 warnings 里列出未登记序列，不从代码名猜类型。

    序列代码统一去空白转大写存储（`h00922_pe` 与 `H00922_PE` 视为同一序列）。
    取值不限制正负：PB、信用利差、ERP 分量允许为负。
    """
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 或 .xls 格式的 Excel 文件")

    try:
        sheets = _read_sheets(await file.read())
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"文件解析失败: {e}。请确认为 Excel 格式，且第一列是日期、后续列名是序列代码",
        )

    if not sheets:
        raise HTTPException(status_code=400, detail="文件没有任何工作表")

    meta_df = sheets.get(MACRO_SERIES_META_SHEET)
    data_sheets = [(n, d) for n, d in sheets.items() if n != MACRO_SERIES_META_SHEET]
    if not data_sheets:
        raise HTTPException(
            status_code=400,
            detail=f"只找到「{MACRO_SERIES_META_SHEET}」工作表，缺少数据表",
        )
    # 取第一张数据表（按工作簿顺序）；多张数据表请拆成多次导入，避免混入同一批
    sheet_name, df = data_sheets[0]
    if df is None or df.empty:
        raise HTTPException(status_code=400, detail=f"工作表「{sheet_name}」为空")

    mode_norm = (mode or "replace").strip().lower()
    if mode_norm not in ("replace", "incremental"):
        raise HTTPException(
            status_code=400,
            detail="mode 须为 replace（按序列覆盖）或 incremental（增量填补）",
        )

    try:
        stats = await service.import_dataframes(df, mode=mode_norm, meta_df=meta_df)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if mode_norm == "replace":
        msg = (
            f"已覆盖 {len(stats['codes'])} 条序列，写入 {stats['inserted']} 条"
            f"（{stats['date_range']}）"
        )
    else:
        msg = (
            f"增量完成：新增 {stats['inserted']} 条、补充 {stats['updated']} 条，"
            f"跳过已存在 {stats['skipped_existing']} 条（{stats['date_range']}）"
        )
    skipped = stats["skipped_cells"]
    bad_date = skipped.get("bad_date") or 0
    bad_value = skipped.get("bad_value") or 0
    if bad_date:
        msg += f"；跳过日期无法解析的行 {bad_date} 个"
    if bad_value:
        msg += f"；跳过非数字单元格 {bad_value} 个（如 N/A、—）"
    if stats["duplicates"]:
        msg += f"；文件内重复 (序列, 日期) {stats['duplicates']} 条，按后出现者为准"
    if stats["warnings"]:
        msg += "；" + "；".join(stats["warnings"])

    return Response.success(
        data={
            "mode": stats["mode"],
            "format": stats["format"],
            "inserted": stats["inserted"],
            "updated": stats["updated"],
            "skipped_existing": stats["skipped_existing"],
            "skipped_cells": skipped,
            "duplicates": stats["duplicates"],
            "codes": stats["codes"],
            "date_range": stats["date_range"],
            "meta_applied": stats["meta_applied"],
            "warnings": stats["warnings"],
        },
        message=msg,
    )


@router.get("/stats", response_model=Response[dict], summary="宏观序列数据统计")
async def get_macro_stats(
    service: MacroSeriesService = Depends(get_macro_series_service),
):
    """集合级统计：总条数、序列数、日期范围、按序列类型的分组统计。"""
    return Response.success(data=await service.stats())


@router.get("/series", response_model=Response[dict], summary="列出全部宏观序列")
async def list_macro_series(
    series_type: Optional[str] = Query(
        None, description="按序列类型过滤，取值见 MACRO_SERIES_TYPES"
    ),
    service: MacroSeriesService = Depends(get_macro_series_service),
):
    """列出库内序列：代码、类型、单位、来源、条数、起止日期。"""
    try:
        rows = await service.list_series(series_type=series_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response.success(
        data={"items": rows, "types": MACRO_SERIES_TYPES, "count": len(rows)}
    )


@router.get("/data", response_model=Response[dict], summary="获取单条序列时序")
async def get_macro_series_data(
    code: str = Query(..., description="序列代码，如 H00922_PE"),
    start_date: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    service: MacroSeriesService = Depends(get_macro_series_service),
):
    """取单条序列的逐日取值，用于前端折线图。"""
    series = await service.get_series(code, start_date=start_date, end_date=end_date)
    rows = [
        {"date": idx.strftime("%Y-%m-%d"), "value": float(val)}
        for idx, val in series.items()
    ]
    return Response.success(
        data={"code": series.name, "rows": rows, "count": len(rows)}
    )


@router.get("/template/download", summary="下载宏观序列导入模板")
async def download_macro_series_template():
    """下载模板：数据 sheet（宽表示例）+ 序列说明 sheet（series_type / 单位 / 来源）。"""
    output, filename = MacroSeriesService.build_template()
    return StreamingResponse(
        output,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        media_type=_SHEET_MEDIA_TYPE,
    )
