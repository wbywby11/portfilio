"""Excel 行情导入编排（自 app/api/asset.py 平移，P9 治理）.

承接 Excel 行情导入的核心编排：线程池解析、only_date 过滤、
分批写入与响应组装。路由层保留文件读取、资产/类型校验与异常兜底。
"""
import asyncio
import io
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException

from app.schemas.response import Response
from app.schemas.asset import PriceImportResponse


def _wide_table_hint(contents: bytes) -> str:
    """缺少数值列时探测文件是否为多资产宽表，命中则给出改道提示。"""
    try:
        import pandas as pd
        from app.services.excel_layout import ExcelLayoutMixin
        df0 = pd.read_excel(io.BytesIO(contents), header=None, nrows=8)
        mixin = ExcelLayoutMixin()
        if (
            mixin._try_date_corner_cn_name_wind_code_rows_0_1(df0)
            or mixin._try_fund_or_security_two_row_header_layout(df0)
        ):
            return "；检测到该文件为多资产宽表（首行资产名称+次行代码），请改用行情页「多资产宽表导入」"
    except Exception:
        pass
    return ""


def _parse_excel_to_price_list(contents: bytes) -> List[dict]:
    """在线程中解析 Excel 为行情字典列表；须含日期列，且至少一列有效行情数值。"""
    import pandas as pd
    from app.schemas.field_mappings import PRICE_COLUMN_MAPPING
    df = pd.read_excel(io.BytesIO(contents))
    df.columns = df.columns.astype(str).str.strip()
    df.rename(columns=PRICE_COLUMN_MAPPING, inplace=True)
    df.columns = df.columns.str.lower()
    df.rename(columns=PRICE_COLUMN_MAPPING, inplace=True)
    if "date" not in df.columns:
        raise ValueError("缺少必须列: date")
    value_cols = ("open", "high", "low", "close", "volume", "amount", "scale")
    present_value_cols = [c for c in value_cols if c in df.columns]
    if not present_value_cols:
        raise ValueError(
            "缺少行情数值列：须至少包含开盘价、最高价、最低价、收盘价、成交量、成交额、规模之一"
            + _wide_table_hint(contents)
        )
    df.dropna(subset=["date"], inplace=True)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.to_dict("records")


async def import_price_data_from_excel_core(
    asset_code: str,
    contents: bytes,
    replace_existing: bool,
    only_missing_dates: bool,
    only_date: Optional[str],
    service,
):
    """Excel 行情导入核心编排（解析 -> only_date 过滤 -> 分批写入 -> 响应组装）."""
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
    
