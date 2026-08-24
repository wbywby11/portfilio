"""汇率数据导入 API"""
import io
import re
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile

from app.models.fx_rate import FxManualRatesIn
from app.schemas.response import Response
from app.services.fx_service import FxService


def get_fx_service() -> FxService:
    return FxService()


router = APIRouter()


@router.post("/import", response_model=Response[dict], summary="导入汇率数据")
async def import_fx_rates(
    file: UploadFile = File(..., description="fx.xlsx 文件（第一列日期，后续列 EUR/USD/HKD/JPY/CNH）"),
    mode: str = Form(
        "replace",
        description="replace=清空后全量覆盖；incremental=仅填补无记录日期及已有记录中的空币种列，不覆盖已有数值",
    ),
    service: FxService = Depends(get_fx_service),
):
    """
    从 Excel 文件导入汇率数据。

    文件格式（与 portfilio-end/大类资产模型备份/fx.xlsx 一致）：
    - 第一列：日期（作为行索引）
    - 后续列：EUR、USD、HKD、JPY、CNH，单元格为该货币对人民币的汇率
    - 读取方式：pd.read_excel(path, index_col=0, parse_dates=True)

    导入模式 **mode**：
    - **replace**：删除库内全部汇率记录后写入文件中的全量数据
    - **incremental**：不删库；无该日则插入；已有该日则只写入库中为空的币种列，已有数值不覆盖
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="请上传 .xlsx 或 .xls 格式的 Excel 文件",
        )

    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents), index_col=0, parse_dates=True)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"文件解析失败: {str(e)}，请确保第一列为日期、格式符合 fx.xlsx 规范",
        )

    if df.empty:
        raise HTTPException(status_code=400, detail="文件为空或无法解析出有效数据")

    mode_norm = (mode or "replace").strip().lower()
    if mode_norm not in ("replace", "incremental"):
        raise HTTPException(
            status_code=400,
            detail="mode 须为 replace（全量覆盖）或 incremental（增量填补）",
        )

    # 标准化列名
    df.columns = df.columns.astype(str).str.strip().str.upper()
    valid_cols = [c for c in FxService.FX_COLUMNS if c in df.columns]
    if not valid_cols:
        raise HTTPException(
            status_code=400,
            detail=f"未找到有效货币列（需要 EUR/USD/HKD/CNH 中至少一列），当前列: {list(df.columns)}",
        )

    stats = await service.import_from_dataframe(df, mode=mode_norm)
    touched = stats["inserted"] + stats["updated"]
    dr = f"{df.index.min()} ~ {df.index.max()}"
    if mode_norm == "replace":
        msg = f"已全量覆盖，共写入 {stats['inserted']} 条"
    else:
        msg = (
            f"增量完成：新增 {stats['inserted']} 日、补充 {stats['updated']} 日缺失字段，"
            f"跳过已存在数值 {stats['skipped_cells']} 项"
        )
    return Response.success(
        data={
            "imported": touched,
            "inserted": stats["inserted"],
            "updated": stats["updated"],
            "skipped_cells": stats["skipped_cells"],
            "mode": mode_norm,
            "date_range": dr,
        },
        message=msg,
    )


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.post("/manual", response_model=Response[dict], summary="手动录入单日汇率")
async def upsert_fx_manual(
    body: FxManualRatesIn = Body(...),
    service: FxService = Depends(get_fx_service),
):
    """
    按日期写入或合并汇率：仅更新请求体中给出且大于 0 的币种，其余列保留库中原值；
    无该日时插入新文档。至少须填一个有效汇率。
    """
    d = (body.date or "").strip()
    if not _DATE_RE.match(d):
        raise HTTPException(status_code=400, detail="日期须为 YYYY-MM-DD")
    try:
        await service.upsert_manual_rates(
            d,
            {"EUR": body.EUR, "USD": body.USD, "HKD": body.HKD, "JPY": body.JPY, "CNH": body.CNH},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response.success(data={"date": d}, message="已保存该日汇率")


@router.get("/stats", response_model=Response[dict], summary="汇率数据统计")
async def get_fx_stats(
    service: FxService = Depends(get_fx_service),
):
    """获取汇率数据条数、日期范围及实际有数据的币种列"""
    cursor = service.collection.find({}).sort("date", 1)
    dates = []
    has_columns: set = set()
    async for doc in cursor:
        dates.append(doc.get("date"))
        for col in FxService.FX_COLUMNS:
            v = doc.get(col)
            if v is not None:
                has_columns.add(col)
    # 保持 FX_COLUMNS 声明顺序
    columns = [c for c in FxService.FX_COLUMNS if c in has_columns]
    if not dates:
        return Response.success(data={"count": 0, "start_date": None, "end_date": None, "columns": columns})
    return Response.success(
        data={
            "count": len(dates),
            "start_date": dates[0],
            "end_date": dates[-1],
            "columns": columns,
        }
    )


@router.get("/rates", response_model=Response[dict], summary="获取汇率时序数据")
async def get_fx_rates(
    start_date: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    service: FxService = Depends(get_fx_service),
):
    """获取汇率时序数据，用于前端图表展示。返回 columns 告知前端实际可用的币种列。"""
    df = await service.get_rates_dataframe(start_date=start_date, end_date=end_date)
    if df.empty:
        return Response.success(data={"rows": [], "columns": list(FxService.FX_COLUMNS)})
    # 检测哪些列实际有非空数据
    active_cols = [c for c in FxService.FX_COLUMNS if df[c].notna().any()]
    df = df.reset_index()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df.replace({np.nan: None})
    rows = df.to_dict(orient="records")
    return Response.success(data={"rows": rows, "columns": active_cols})
