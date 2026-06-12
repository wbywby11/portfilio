"""资产相关路由"""
import asyncio
from datetime import datetime
from typing import List, Optional
import io

from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from bson import ObjectId
from bson.errors import InvalidId

from pydantic import BaseModel, Field
from loguru import logger

from app.models.asset import AssetType, Asset
from app.schemas.asset import (
    AssetOption, AssetCreate, AssetUpdate, AssetOut, KlinePoint,
    PriceImportRequest, PriceImportResponse, PriceCoverageResponse,
    MultiAssetSingleImportRequest,
    MultiAssetRowPreviewStatsRequest,
)
from app.schemas.response import Response, PageData
from app.services.asset_service import AssetService


def _parse_excel_to_price_list(contents: bytes) -> List[dict]:
    """在线程中解析 Excel 为行情字典列表；须含日期列，且至少一列有效行情数值。"""
    import pandas as pd
    df = pd.read_excel(io.BytesIO(contents))
    df.columns = df.columns.astype(str).str.strip()
    column_mapping = {
        "日期": "date",
        "日期*": "date",
        "date": "date",
        "开盘价": "open",
        "开盘价*": "open",
        "open": "open",
        "最高价": "high",
        "最高价*": "high",
        "high": "high",
        "最低价": "low",
        "最低价*": "low",
        "low": "low",
        "收盘价": "close",
        "收盘价*": "close",
        "收盘": "close",
        "close": "close",
        "成交量": "volume",
        "volume": "volume",
        "成交额": "amount",
        "amount": "amount",
        "规模": "scale",
        "规模*": "scale",
        "基金规模": "scale",
        "scale": "scale",
    }
    df.rename(columns=column_mapping, inplace=True)
    df.columns = df.columns.str.lower()
    df.rename(columns=column_mapping, inplace=True)
    if "date" not in df.columns:
        raise ValueError("缺少必须列: date")
    value_cols = ("open", "high", "low", "close", "volume", "amount", "scale")
    present_value_cols = [c for c in value_cols if c in df.columns]
    if not present_value_cols:
        raise ValueError("缺少行情数值列：须至少包含开盘价、最高价、最低价、收盘价、成交量、成交额、规模之一")
    df.dropna(subset=["date"], inplace=True)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.to_dict("records")


router = APIRouter()


def validate_object_id(id_str: str) -> str:
    """验证ObjectId格式"""
    if not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=400,
            detail=f"无效的ID格式: {id_str}, 必须是24位十六进制字符串"
        )
    return id_str


def get_asset_service() -> AssetService:
    return AssetService()


@router.get("/options", response_model=Response[List[AssetOption]], summary="资产查询(下拉框)")
async def list_asset_options(
    asset_type: Optional[str] = Query(None, description="资产类型"),
    service: AssetService = Depends(get_asset_service),
):
    """提供给前台下拉框使用的资产列表(精简字段)"""
    # 空字符串视为None
    asset_type_enum = None
    if asset_type and asset_type.strip():
        try:
            asset_type_enum = AssetType(asset_type)
        except ValueError:
            pass  # 如果不是合法枚举值,忽略
    assets = await service.list_assets(asset_type=asset_type_enum, is_active=True, limit=500)
    data = [AssetOption(id=a.id or "", code=a.code, name=a.name) for a in assets]
    return Response.success(data=data)


@router.post("/", response_model=Response[str], summary="创建资产")
async def create_asset(asset_in: AssetCreate, service: AssetService = Depends(get_asset_service)):
    asset = Asset(**asset_in.dict())
    asset_id = await service.create_asset(asset)
    return Response.success(data=asset_id, message="资产创建成功")


@router.get("/", response_model=Response[PageData[AssetOut]], summary="资产列表")
async def list_assets(
    asset_type: Optional[str] = Query(None, description="资产类型"),
    is_active: bool = Query(True, description="是否启用"),
    code: Optional[str] = Query(None, description="资产代码（模糊匹配）"),
    name: Optional[str] = Query(None, description="资产名称（模糊匹配）"),
    skip: int = 0,
    limit: int = 100,
    service: AssetService = Depends(get_asset_service),
):
    # 空字符串视为None
    asset_type_enum = None
    if asset_type and asset_type.strip():
        try:
            asset_type_enum = AssetType(asset_type)
        except ValueError:
            pass  # 如果不是合法枚举值,忽略
    assets = await service.list_assets(
        asset_type=asset_type_enum, is_active=is_active,
        skip=skip, limit=limit,
        code=code, name=name,
    )
    total = await service.count_assets(
        asset_type=asset_type_enum, is_active=is_active,
        code=code, name=name,
    )
    page_size = limit or 20
    page = (skip // page_size) + 1 if page_size else 1
    pages = (total + page_size - 1) // page_size if page_size else 1
    data = [AssetOut(**a.dict()) for a in assets]
    return Response.success(data=PageData(
        items=data, total=total, page=page, page_size=page_size, pages=pages,
    ))


@router.get("/template/download", summary="下载资产导入模板")
async def download_asset_template():
    """下载用于批量导入资产的 Excel 模板"""
    import pandas as pd
    
    # 定义模板列
    columns = [
        "资产代码*", "资产名称*", "资产类型*", "交易所", "资产描述", 
        "展期天数(k)", "持仓量阈值(th)", "观察窗口起点(p)", "观察窗口终点(q)",
        "替代标的代码", "切换日期(YYYYMMDD)"
    ]
    
    # 示例数据
    example_data = [
        ["IF2503", "沪深300期货2503", "指数", "CFFEX", "股指期货示例", 5, 0.3, 10, 3, "", ""],
        ["SH000300", "沪深300指数", "指数", "SSE", "指数示例", "", "", "", "", "", ""]
    ]
    
    df = pd.DataFrame(example_data, columns=columns)
    
    # 写入内存
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='资产导入模板')
        
        # 还可以增加一个说明 Sheet
        instructions = [
            ["字段名称", "是否必填", "说明"],
            ["资产代码", "是", "唯一标识，如 SH000300"],
            ["资产名称", "是", "显示名称"],
            ["资产类型", "是", "可选值：股票、债券、商品、货币、基金、指数、数字货币"],
            ["交易所", "否", "交易所代码"],
            ["资产描述", "否", "备注信息"],
            ["展期天数(k)", "否", "仅期货类资产需要"],
            ["持仓量阈值(th)", "否", "仅期货类资产需要"],
            ["观察窗口起点(p)", "否", "仅期货类资产需要"],
            ["观察窗口终点(q)", "否", "仅期货类资产需要"],
            ["替代标的代码", "否", "现货/ETF上市前替代标的"],
            ["切换日期(YYYYMMDD)", "否", "替代标的切换日期"]
        ]
        pd.DataFrame(instructions[1:], columns=instructions[0]).to_excel(writer, index=False, sheet_name='填写说明')
    
    output.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="asset_import_template.xlsx"'
    }
    return StreamingResponse(output, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@router.post("/import/excel", response_model=Response[dict], summary="批量从Excel导入资产")
async def import_assets_from_excel(
    file: UploadFile = File(..., description="资产导入Excel文件"),
    service: AssetService = Depends(get_asset_service)
):
    """从 Excel 批量导入或更新资产信息"""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 或 .xls 文件")
    
    try:
        import pandas as pd
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        # 列名映射
        mapping = {
            "资产代码*": "code",
            "资产代码": "code",
            "资产名称*": "name",
            "资产名称": "name",
            "资产类型*": "asset_type",
            "资产类型": "asset_type",
            "交易所": "exchange",
            "资产描述": "description",
            "展期天数(k)": "rollover_days",
            "持仓量阈值(th)": "rollover_threshold",
            "观察窗口起点(p)": "rollover_window_p",
            "观察窗口终点(q)": "rollover_window_q",
            "替代标的代码": "substitute_code",
            "切换日期(YYYYMMDD)": "switch_date"
        }
        
        # 过滤并重命名列
        df.rename(columns=mapping, inplace=True)
        
        # 只要我们映射中存在的列
        valid_cols = [c for c in df.columns if c in mapping.values()]
        df = df[valid_cols]
        
        # 必填项检查
        required = ["code", "name", "asset_type"]
        missing = [r for r in required if r not in df.columns]
        if missing:
            raise HTTPException(status_code=400, detail=f"模板错误，缺少必填列: {missing}")
            
        # 清理空行
        df.dropna(subset=required, inplace=True)
        
        # 转换数据
        assets_data = df.to_dict('records')
        
        # 调用 service 导入
        result = await service.import_assets_from_excel_data(assets_data)
        
        return Response.success(
            data=result, 
            message=f"导入完成：新增{result['inserted_count']}个，更新{result['updated_count']}个"
        )
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.get("/{asset_code}/kline", response_model=Response[List[KlinePoint]], summary="资产行情K线")
async def get_asset_kline(
    asset_code: str,
    start_date: Optional[str] = Query(None, description="开始日期（格式：YYYY-MM-DD）"),
    end_date: Optional[str] = Query(None, description="结束日期（格式：YYYY-MM-DD）"),
    all_calendar_days: bool = Query(
        False,
        description="为 True 时返回区间内全部自然日行情，不按交易日历裁剪；默认 False",
    ),
    service: AssetService = Depends(get_asset_service),
):
    """
    返回指定资产在时间区间内的K线数据,用于前台画K线图

    **交易日历：** 若系统已配置 Mongo ``trade_dates`` 或 ``data/trade_dates.xlsx``，且未传
    ``all_calendar_days=true``，则仅返回落在交易日历内的行。需要表格展示含假期的完整序列时传
    ``all_calendar_days=true``。

    **请求示例：**
    ```
    GET /api/v1/assets/SH000016/kline?start_date=2025-01-01&end_date=2026-01-19
    ```

    **参数说明：**
    - `start_date`: 开始日期，格式 YYYY-MM-DD，可选
    - `end_date`: 结束日期，格式 YYYY-MM-DD，可选
    """
    # 解析日期字符串为 datetime 对象
    start_dt = None
    end_dt = None
    
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=400, detail=f"开始日期格式错误，请使用 YYYY-MM-DD 格式")
    
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=400, detail=f"结束日期格式错误，请使用 YYYY-MM-DD 格式")
    
    prices = await service.get_asset_prices(asset_code, start_dt, end_dt)
    if not all_calendar_days:
        td_set = await service.load_trade_calendar_date_set()
        if td_set:

            def _dkey(d: str) -> str:
                s = (d or "").strip().replace("/", "-")
                return s[:10] if len(s) >= 10 else s

            prices = [p for p in prices if _dkey(str(p.date)) in td_set]

    data = [
        KlinePoint(
            date=p.date,
            open=p.open,
            high=p.high,
            low=p.low,
            close=p.close,
            volume=p.volume,
            amount=p.amount,
            scale=p.scale,
        )
        for p in prices
    ]
    return Response.success(data=data)


@router.get(
    "/prices/coverage-gaps",
    response_model=Response[PriceCoverageResponse],
    summary="区间内行情缺失的交易日（用于补数提示）",
)
async def get_price_coverage_gaps(
    asset_code: str = Query(..., description="资产代码"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    service: AssetService = Depends(get_asset_service),
):
    """
    将 ``data/trade_dates.xlsx`` 中的交易日（若不存在则用工作日近似）与 Mongo ``asset_prices`` 已有日期对比，
    返回区间内缺失的交易日列表，便于前端提示补录。
    """
    asset = await service.get_asset_by_code(asset_code)
    if not asset:
        raise HTTPException(status_code=404, detail=f"资产不存在: {asset_code}")
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d")
        ed = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式须为 YYYY-MM-DD")
    if sd > ed:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    raw = await service.get_price_coverage_gaps(asset_code, sd, ed)
    return Response.success(data=PriceCoverageResponse(**raw))


class _PriceDateBatchRequest(BaseModel):
    """批量删除行情请求体。"""
    dates: List[str] = Field(..., min_items=1, description="要删除的日期列表，YYYY-MM-DD")


@router.delete(
    "/{asset_code}/prices/{date}",
    response_model=Response[dict],
    summary="删除资产某日行情数据",
)
async def delete_asset_price_by_date(
    asset_code: str,
    date: str,
    service: AssetService = Depends(get_asset_service),
):
    """删除指定资产、指定日期的单条 K 线/行情记录。"""
    asset = await service.get_asset_by_code(asset_code)
    if not asset:
        raise HTTPException(status_code=404, detail=f"资产不存在: {asset_code}")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式须为 YYYY-MM-DD")
    deleted = await service.delete_asset_price_by_date(asset_code, date)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"未找到 {asset_code} 在 {date} 的行情记录",
        )
    return Response.success(
        data={"asset_code": asset_code, "date": date, "deleted": 1},
        message="行情删除成功",
    )


@router.delete(
    "/{asset_code}/prices",
    response_model=Response[dict],
    summary="批量删除资产行情数据",
)
async def delete_asset_prices_batch(
    asset_code: str,
    request: _PriceDateBatchRequest,
    service: AssetService = Depends(get_asset_service),
):
    """按 ``dates`` 列表批量删除资产行情记录，返回实际删除条数。"""
    asset = await service.get_asset_by_code(asset_code)
    if not asset:
        raise HTTPException(status_code=404, detail=f"资产不存在: {asset_code}")
    bad: List[str] = []
    cleaned: List[str] = []
    for raw in request.dates:
        s = (raw or "").strip()
        try:
            datetime.strptime(s.replace("/", "-")[:10], "%Y-%m-%d")
            cleaned.append(s.replace("/", "-")[:10])
        except ValueError:
            bad.append(raw)
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"以下日期格式不合法（需 YYYY-MM-DD）: {bad}",
        )
    deleted = await service.delete_asset_prices_by_dates(asset_code, cleaned)
    return Response.success(
        data={
            "asset_code": asset_code,
            "requested": len(cleaned),
            "deleted": deleted,
        },
        message=f"已删除 {deleted} 条行情记录",
    )


@router.get("/{asset_id}", response_model=Response[AssetOut], summary="获取资产详情")
async def get_asset(
    asset_id: str,
    service: AssetService = Depends(get_asset_service),
):
    """根据ID获取单个资产详情"""
    validate_object_id(asset_id)
    asset = await service.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    return Response.success(data=AssetOut(**asset.dict()))


@router.put("/{asset_id}", response_model=Response[AssetOut], summary="更新资产")
async def update_asset(
    asset_id: str,
    asset_in: AssetUpdate,
    service: AssetService = Depends(get_asset_service),
):
    """更新资产信息"""
    validate_object_id(asset_id)
    
    # 先检查资产是否存在
    existing_asset = await service.get_asset(asset_id)
    if not existing_asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    
    # 只更新提供的字段
    update_data = asset_in.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="未提供任何更新字段")
    
    success = await service.update_asset(asset_id, update_data)
    if not success:
        raise HTTPException(status_code=500, detail="更新失败")
    
    # 返回更新后的资产
    updated_asset = await service.get_asset(asset_id)
    return Response.success(data=AssetOut(**updated_asset.dict()), message="资产更新成功")


@router.delete("/{asset_id}", response_model=Response[dict], summary="删除资产")
async def delete_asset(
    asset_id: str,
    service: AssetService = Depends(get_asset_service),
):
    """删除资产(软删除,将is_active设置为False)"""
    validate_object_id(asset_id)
    
    # 检查资产是否存在
    existing_asset = await service.get_asset(asset_id)
    if not existing_asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    
    success = await service.delete_asset(asset_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")
    
    return Response.success(data={"asset_id": asset_id}, message="资产删除成功")


@router.get(
    "/prices/import/progress",
    response_model=Response[Optional[dict]],
    summary="行情导入进度（轮询）",
)
async def get_price_import_progress(
    progress_id: str = Query(..., min_length=1, description="与单资产导入请求中的 progress_id 一致"),
):
    """
    返回内存中的导入进度（单 worker 有效）。无记录或已清理时 data 为 null。
    """
    try:
        from app.services.price_import_progress import get_snapshot
    except ModuleNotFoundError:
        return Response.success(
            data=None,
            message="未部署 app.services.price_import_progress，进度轮询不可用（K 线等业务不受影响）",
        )
    snap = await get_snapshot(progress_id.strip())
    pid = progress_id.strip()
    if snap:
        wd = int(snap.get("write_done") or 0)
        wt = int(snap.get("write_total") or 0)
        lines = int(snap.get("file_line_total") or 0)
        prep = int(snap.get("prepare_done") or 0)
        phase = str(snap.get("phase") or "")
        metric = snap.get("metric_label") or snap.get("metric_key") or ""
        code = snap.get("asset_code") or ""
        name = (snap.get("asset_name") or "").strip()
        summary = snap.get("message") or ""
        ac = f"{code} {name}".strip() or code or "(未知资产)"
        summary_str = str(summary) if summary is not None else ""
        short_msg = summary_str[:160] + ("…" if len(summary_str) > 160 else "")
        logger.info(
            "[行情导入-progress] progress_id={} phase={} asset={} metric={} "
            "file_lines={} prepare_done={} write_done/write_total={}/{} msg={}",
            pid,
            phase,
            ac,
            metric,
            lines,
            prep,
            wd,
            wt,
            short_msg,
        )
    else:
        logger.info(
            "[行情导入-progress] progress_id={} snapshot=None（无进行中任务或进度已过期）",
            pid,
        )
    return Response.success(data=snap, message="ok" if snap else "无进度或已结束")


@router.post("/prices/import", response_model=Response[PriceImportResponse], summary="导入资产行情数据")
async def import_price_data(
    request: PriceImportRequest,
    service: AssetService = Depends(get_asset_service)
):
    """
    导入资产行情数据（JSON格式）
    
    服务端已做批量写入优化（每批约 1000 条），避免因逐条写入导致请求超时、数据导入不全。
    
    **请求示例：**
    ```json
    {
        "asset_code": "SH000016",
        "replace_existing": false,
        "prices": [
            {
                "date": "2024-01-01",
                "open": 3000.5,
                "high": 3050.8,
                "low": 2995.2,
                "close": 3020.6,
                "volume": 125000000,
                "amount": 15000000000
            },
            {
                "date": "20240102",
                "open": 3020.6,
                "high": 3080.0,
                "low": 3015.0,
                "close": 3075.5,
                "volume": 130000000
            }
        ]
    }
    ```
    
    **日期格式支持：**
    - YYYY-MM-DD（如 2024-01-01）
    - YYYYMMDD（如 20240101）
    
    **更新逻辑：**
    - `replace_existing=false` 且 `only_missing_dates=false`：按交易日 upsert（库中已有该日则更新，否则插入）
    - `replace_existing=false` 且 `only_missing_dates=true`：仅新增（库中已有该日则跳过该行，否则插入）
    - `replace_existing=true`：先删除该资产全部历史行情，再插入本次请求中的数据（忽略 only_missing_dates）

    **交易日历：** 若 Mongo ``trade_dates`` 或 ``data/trade_dates.xlsx`` 有数据，则请求中行日期不在交易日历内的记录会被跳过（不计入错误），便于收盘价含假期时仅向真实交易日写入 OHLC/规模/成交额等。
    """
    # 验证资产是否存在
    asset = await service.get_asset_by_code(request.asset_code)
    if not asset:
        raise HTTPException(status_code=404, detail=f"资产不存在: {request.asset_code}")
    
    def _dump_point(p):
        return p.model_dump(exclude_none=True) if hasattr(p, "model_dump") else p.dict(exclude_none=True)

    price_data_list = [_dump_point(p) for p in request.prices]
    
    # 导入数据
    result = await service.import_price_data(
        asset_code=request.asset_code,
        price_data_list=price_data_list,
        replace_existing=request.replace_existing,
        only_missing_dates=request.only_missing_dates,
    )
    
    # 返回结果
    response_data = PriceImportResponse(
        asset_code=request.asset_code,
        **result
    )
    
    msg = (
        f"导入完成：新增{result['inserted_count']}条，更新{result['updated_count']}条，"
        f"跳过{result.get('skipped_count', 0)}条，错误{result['error_count']}条"
    )
    if result.get("skipped_non_trade_days"):
        msg += f"（其中{result['skipped_non_trade_days']}条非交易日历内日期已跳过）"
    return Response.success(data=response_data, message=msg)


@router.get("/prices/template/download", summary="下载单资产行情批量导入模板")
async def download_price_template(
    kind: str = Query(
        "full",
        description="full=全列示例；open/high/low/close/volume/amount/scale=仅日期+该列（与按日合并导入配套）",
    ),
):
    """下载单列资产、纵向日期行的行情 Excel 模板（与「批量导入行情」配套）。"""
    import pandas as pd

    kind = (kind or "full").strip().lower()
    allowed = {"full", "open", "high", "low", "close", "volume", "amount", "scale"}
    if kind not in allowed:
        kind = "full"

    label_cn = {
        "open": "开盘价*",
        "high": "最高价*",
        "low": "最低价*",
        "close": "收盘价*",
        "volume": "成交量*",
        "amount": "成交额*",
        "scale": "规模*",
    }
    sample_val = {
        "open": 3000.50,
        "high": 3050.80,
        "low": 2995.20,
        "close": 3020.60,
        "volume": 125000000,
        "amount": 15000000000.00,
        "scale": 1.25e11,
    }

    if kind == "full":
        columns = [
            "日期*",
            "开盘价",
            "最高价",
            "最低价",
            "收盘价*",
            "成交量",
            "成交额",
            "规模",
        ]
        example_data = [
            ["2025-01-01", 3000.50, 3050.80, 2995.20, 3020.60, 125000000, 15000000000.00, 1.2e11],
            ["2025-01-02", "", "", "", 3075.50, 130000000, 16000000000.00, ""],
        ]
        instructions = [
            ["字段名称", "是否必填", "说明"],
            ["日期*", "是", "格式：YYYY-MM-DD 或 YYYYMMDD"],
            ["开盘价", "否", "数值"],
            ["最高价", "否", "数值"],
            ["最低价", "否", "数值"],
            ["收盘价*", "新交易日建议填", "按日合并时可只更新部分列；无该日时须能推断收盘价"],
            ["成交量", "否", "整数或数值"],
            ["成交额", "否", "数值"],
            ["规模", "否", "如 AUM、份额规模等"],
        ]
        fname = "price_import_template_single_asset_full.xlsx"
    else:
        col2 = label_cn[kind]
        columns = ["日期*", col2]
        example_data = [
            ["2025-01-01", sample_val[kind]],
            ["2025-01-02", sample_val[kind]],
        ]
        instructions = [
            ["字段名称", "是否必填", "说明"],
            ["日期*", "是", "格式：YYYY-MM-DD 或 YYYYMMDD"],
            [col2.replace("*", ""), "是", "与资产库 → 资产行情 → 批量导入行情 配合；按日合并只更新本列"],
        ]
        fname = f"price_import_template_single_asset_{kind}.xlsx"

    df = pd.DataFrame(example_data, columns=columns)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="行情导入模板")
        pd.DataFrame(instructions[1:], columns=instructions[0]).to_excel(
            writer, index=False, sheet_name="说明"
        )
    output.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{fname}"'}
    return StreamingResponse(
        output,
        headers=headers,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/prices/template/download/multi-asset", summary="下载多资产宽表行情导入模板")
async def download_multi_asset_price_template(
    metric: str = Query(
        "close",
        description="宽表列数值含义：close/open/high/low/amount/volume/scale，与导入时 metric 一致",
    ),
):
    """
    大类资产底层数据格式：第 4 行（Excel 行号）为资产名称、第 5 行为资产代码、第 6 行起为日期与数值列。
    与「多资产Excel导入」解析规则一致；导入时在界面选择相同 metric。
    """
    import pandas as pd

    metric = (metric or "close").strip().lower()
    if metric not in ("close", "open", "high", "low", "amount", "volume", "scale"):
        metric = "close"
    metric_label = {
        "close": "收盘价",
        "open": "开盘价",
        "high": "最高价",
        "low": "最低价",
        "amount": "成交额",
        "volume": "成交量",
        "scale": "规模",
    }[metric]

    n_rows = 12
    n_cols = 5
    grid = [[None] * n_cols for _ in range(n_rows)]
    grid[3][0] = "Date"
    grid[3][1] = "沪深300"
    grid[3][2] = "中证500"
    grid[3][3] = "示例债券指数"
    grid[3][4] = "示例货币利率"
    grid[4][0] = "Date"
    grid[4][1] = "000300.SH"
    grid[4][2] = "000905.SH"
    grid[4][3] = "CBA00101.CS"
    grid[4][4] = "DR007.IB"
    sample_dates = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"]
    for i, d in enumerate(sample_dates):
        r = 5 + i
        if r >= n_rows:
            break
        grid[r][0] = d
        grid[r][1] = 3500.12 + i
        grid[r][2] = 5200.45 + i
        grid[r][3] = 100.2 + i * 0.01
        grid[r][4] = 1.85 + i * 0.001

    df = pd.DataFrame(grid)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, header=False, sheet_name="Sheet1")
        instructions = [
            ["说明", "内容"],
            [
                "布局A（Wind类）",
                f"第 4 行：各列资产中文名称；第 5 行：资产代码；第 6 行起：A 列为日期，其余列为「{metric_label}」",
            ],
            [
                "布局B（基金/证券）",
                "第 1 行 A 列为「基金代码」等、B 列起为各资产代码；第 2 行 A 列为「基金名称」、B 列起为名称；"
                "第 3 行起 A 列为日期，其余列为行情数值（与图3收盘价表一致）",
            ],
            ["metric", f"导入时请选择 metric={metric}，与下载模板一致"],
            ["日期", "支持 YYYY-MM-DD；可增加行延续历史"],
            ["多 Sheet", "可在多个工作表中放置资产列，解析时会合并（同代码只保留首次出现）"],
            ["导入入口", "资产库 → 资产行情 →「多资产Excel导入」"],
        ]
        pd.DataFrame(instructions[1:], columns=instructions[0]).to_excel(
            writer, index=False, sheet_name="填写说明"
        )
    output.seek(0)
    headers = {
        "Content-Disposition": f'attachment; filename="price_import_template_multi_asset_{metric}.xlsx"'
    }
    return StreamingResponse(
        output,
        headers=headers,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/prices/import/multi-asset/preview", response_model=Response[dict], summary="多资产导入预览")
async def preview_multi_asset_import(
    file: UploadFile = File(..., description="大类资产底层数据 Excel 文件"),
    metric: str = Query(
        "close",
        description="宽表列映射: close/open/high/low/amount/volume/scale",
    ),
    service: AssetService = Depends(get_asset_service),
):
    """
    解析多资产 Excel（如 大类资产底层数据-含插件.xlsx），返回资产列表及冲突信息。
    用于导入前预览：代码一致名称不一致、已有行情等。
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 或 .xls 文件")
    contents = await file.read()
    try:
        result = await service.preview_multi_asset_import(contents, metric)
        return Response.success(data=result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {str(e)}")


@router.post("/prices/import/multi-asset/analyze", response_model=Response[dict], summary="多资产导入分析（含行情）")
async def analyze_multi_asset_import(
    file: UploadFile = File(..., description="大类资产底层数据 Excel 文件"),
    metric: str = Query(
        "close",
        description="宽表列映射: close/open/high/low/amount/volume/scale",
    ),
    service: AssetService = Depends(get_asset_service),
):
    """
    解析多资产 Excel，返回每条资产的匹配类型、系统侧信息及完整 prices，供前端预览后逐条导入。
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 或 .xls 文件")
    contents = await file.read()
    try:
        result = await service.analyze_multi_asset_import(contents, metric)
        return Response.success(data=result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {str(e)}")


@router.post(
    "/prices/import/multi-asset/row-preview-stats",
    response_model=Response[dict],
    summary="多资产单行导入影响预览（切换目标代码后刷新）",
)
async def multi_asset_row_preview_stats(
    body: MultiAssetRowPreviewStatsRequest,
    service: AssetService = Depends(get_asset_service),
):
    """按目标资产代码与文件中的 prices 计算库内区间、合并导入与全量覆盖两套统计。"""
    try:
        price_dicts = [
            p.model_dump(exclude_none=True) if hasattr(p, "model_dump") else p.dict(exclude_none=True)
            for p in body.prices
        ]
        stats = await service.compute_price_import_preview_stats(
            body.target_code.strip(), price_dicts
        )
        return Response.success(data=stats)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/prices/import/multi-asset/parse", response_model=Response[dict], summary="多资产Excel解析（含行情）")
async def parse_multi_asset_excel(
    file: UploadFile = File(..., description="大类资产底层数据 Excel 文件"),
    metric: str = Query(
        "close",
        description="宽表列映射: close/open/high/low/amount/volume/scale",
    ),
    service: AssetService = Depends(get_asset_service),
):
    """
    解析多资产 Excel，返回完整资产列表（含行情数据），供前端逐条导入并展示进度。
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 或 .xls 文件")
    contents = await file.read()
    try:
        loop = asyncio.get_event_loop()
        m = metric
        assets = await loop.run_in_executor(
            None,
            lambda: service._parse_multi_asset_excel(contents, m),
        )
        return Response.success(data={"assets": assets})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {str(e)}")


@router.post("/prices/import/multi-asset/single", response_model=Response[dict], summary="单资产导入（多资产逐条用）")
async def import_single_asset_from_multi(
    request: MultiAssetSingleImportRequest,
    service: AssetService = Depends(get_asset_service)
):
    """导入单个资产及行情，用于多资产导入时的逐条调用与进度展示。"""
    try:
        price_dicts = [
            p.model_dump(exclude_none=True) if hasattr(p, "model_dump") else p.dict(exclude_none=True)
            for p in request.prices
        ]
        result = await service.import_single_asset_from_multi(
            code=request.code,
            name=request.name,
            prices=price_dicts,
            overwrite_name=request.overwrite_name,
            replace_existing=request.replace_existing,
            only_missing_dates=request.only_missing_dates,
            import_as_code=request.import_as_code,
            create_new_asset=request.create_new_asset,
            new_asset_code=request.new_asset_code,
            progress_id=request.progress_id,
            import_metric=request.import_metric,
        )
        return Response.success(data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.post("/prices/import/multi-asset", response_model=Response[dict], summary="多资产批量导入")
async def import_multi_asset(
    overwrite_name: bool = Query(False, description="代码一致名称不一致时是否覆盖名称"),
    replace_existing: bool = Query(
        False,
        description="false：按日期 upsert；true：先删该资产全部行情再写入文件中的行",
    ),
    only_missing_dates: bool = Query(
        False,
        description="true 且 replace_existing=false：仅插入库中尚不存在的交易日",
    ),
    metric: str = Query(
        "close",
        description="宽表列映射: close/open/high/low/amount/volume/scale",
    ),
    file: UploadFile = File(..., description="大类资产底层数据 Excel 文件"),
    service: AssetService = Depends(get_asset_service),
):
    """
    从多资产 Excel 批量导入资产及行情。
    逐个资产根据代码导入；若资产不存在则自动创建。
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 或 .xls 文件")
    contents = await file.read()
    try:
        result = await service.import_multi_asset_from_excel(
            contents=contents,
            overwrite_name=overwrite_name,
            replace_existing=replace_existing,
            only_missing_dates=only_missing_dates,
            metric=metric,
        )
        return Response.success(
            data=result,
            message=f"导入完成：新增资产{result['assets_created']}个，更新{result['assets_updated']}个，行情{result['prices_imported']}条"
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.post("/prices/import/excel", response_model=Response[PriceImportResponse], summary="Excel文件导入行情")
async def import_price_data_from_excel(
    asset_code: str = Query(..., description="资产代码"),
    replace_existing: bool = Query(
        False,
        description="false：按日期 upsert；true：先删该资产全部行情再写入",
    ),
    only_missing_dates: bool = Query(
        False,
        description="true 且 replace_existing=false：仅插入库中尚不存在的交易日，已有日期跳过",
    ),
    only_date: Optional[str] = Query(
        None,
        description="若指定 YYYY-MM-DD，仅导入 Excel 中该日期的行（适合补单日）",
    ),
    file: UploadFile = File(..., description="Excel文件（.xlsx或.xls）"),
    service: AssetService = Depends(get_asset_service)
):
    """
    从 Excel 文件导入资产行情数据
    
    **Excel 文件格式要求：**
    
    必须包含 `date`/`日期` 列，并至少包含以下之一（列名不区分大小写）：
    `开盘价`、`最高价`、`最低价`、`收盘价`/`收盘`、`成交量`、`成交额`、`规模`/`scale`。
    按日合并：新插入的交易日须在本行提供大于 0 的收盘价；若仅导入规模/成交额等补充字段，对应日期须在库中已有有效收盘价。
    `only_missing_dates=true` 且非全量覆盖：仅插入库中尚不存在的交易日，已有日期跳过。
    全量覆盖：每一行均须提供大于 0 的收盘价。
    
    **示例：**
    
    | 日期       | 开盘价  | 最高价  | 最低价  | 收盘价  | 成交量      |
    |------------|--------|--------|--------|--------|-------------|
    | 2024-01-01 | 3000.5 | 3050.8 | 2995.2 | 3020.6 | 125000000   |
    | 2024-01-02 | 3020.6 | 3080.0 | 3015.0 | 3075.5 | 130000000   |
    
    **注意事项：**
    1. 第一行必须是表头
    2. 日期格式支持 YYYY-MM-DD 或 YYYYMMDD
    3. 成交量和成交额可以留空
    4. 支持 .xlsx 和 .xls 格式

    **交易日历：** 若已配置 Mongo ``trade_dates`` 或 ``data/trade_dates.xlsx``，则 Excel 中行日期不在交易日历内的记录会被跳过（响应字段 ``skipped_non_trade_days``）。
    """
    try:
        print(
            f"[行情导入] 开始 asset_code={asset_code}, replace_existing={replace_existing}, "
            f"only_missing_dates={only_missing_dates}, filename={getattr(file, 'filename', None)}"
        )
        # 验证资产是否存在
        asset = await service.get_asset_by_code(asset_code)
        if not asset:
            print(f"[行情导入] 资产不存在: {asset_code}")
            raise HTTPException(status_code=404, detail=f"资产不存在: {asset_code}")
        
        # 验证文件类型
        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(status_code=400, detail="只支持 .xlsx 或 .xls 文件")
        
        # 读取文件内容
        contents = await file.read()
        print(f"[行情导入] 文件大小: {len(contents)} 字节")
        
        # 在线程池中解析 Excel，避免阻塞事件循环导致请求超时
        loop = asyncio.get_event_loop()
        try:
            price_data_list = await loop.run_in_executor(
                None,
                _parse_excel_to_price_list,
                contents,
            )
        except Exception as parse_err:
            print(f"[行情导入] Excel 解析失败: {parse_err}")
            raise HTTPException(status_code=400, detail=f"Excel 解析失败: {str(parse_err)}")
        
        if not price_data_list:
            print(f"[行情导入] 无有效数据行")
            return Response.success(
                data=PriceImportResponse(
                    asset_code=asset_code,
                    total_count=0,
                    inserted_count=0,
                    updated_count=0,
                    skipped_count=0,
                    skipped_non_trade_days=0,
                    error_count=0,
                    errors=[],
                ),
                message="无有效数据行，导入跳过",
            )
        
        print(f"[行情导入] 解析行数: {len(price_data_list)}")
        if price_data_list:
            print(f"[行情导入] 首行示例: date={price_data_list[0].get('date')}, close={price_data_list[0].get('close')}")

        if only_date:
            od = only_date.strip()[:10]
            try:
                datetime.strptime(od, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="only_date 须为 YYYY-MM-DD")
            before_n = len(price_data_list)
            price_data_list = [
                r for r in price_data_list
                if str(r.get("date", ""))[:10] == od
            ]
            print(f"[行情导入] only_date={od} 过滤后 {len(price_data_list)} 行（原 {before_n} 行）")
        
        # 导入数据（服务端已做分批写入与保活，减少超时导致的不全）
        result = await service.import_price_data(
            asset_code=asset_code,
            price_data_list=price_data_list,
            replace_existing=replace_existing,
            only_missing_dates=only_missing_dates,
        )
        print(f"[行情导入] 完成 total={result['total_count']} inserted={result['inserted_count']} updated={result['updated_count']} error={result['error_count']}")
        if result.get('errors'):
            for err in result['errors'][:5]:
                print(f"[行情导入] 错误: {err}")
            if len(result['errors']) > 5:
                print(f"[行情导入] ... 共 {len(result['errors'])} 条错误")
        
        # 返回结果
        response_data = PriceImportResponse(
            asset_code=asset_code,
            **result
        )
        
        msg = (
            f"导入完成：新增{result['inserted_count']}条，更新{result['updated_count']}条，"
            f"跳过{result.get('skipped_count', 0)}条，错误{result['error_count']}条"
        )
        if result.get("skipped_non_trade_days"):
            msg += f"（其中{result['skipped_non_trade_days']}条非交易日历内日期已跳过）"
        return Response.success(data=response_data, message=msg)
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        import traceback
        print(f"[行情导入] 异常: {type(e).__name__}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")
