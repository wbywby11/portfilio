# -*- coding: utf-8 -*-
"""
收益凭证估值模块 API 路由

提供产品管理、市场数据、波动率曲面、估值运行、风险分析和事件日志等 REST API 端点。
路由前缀: /api/v1/options (在 main.py 中注册时添加)
"""
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Body, UploadFile, File, Form
from loguru import logger

from app.schemas.response import Response
from app.config.collections import COL_ASSET_PRICES
from app.services.option_pricing_service import OptionPricingService
from app.schemas.option_product import (
    OptionProductCreate,
    OptionProductUpdate,
    OptionMarketDataImportRequest,
    OptionVolSurfaceImportRequest,
    OptionRunRequest,
    OptionRiskRunRequest,
)


router = APIRouter()


def get_service() -> OptionPricingService:
    return OptionPricingService()


# ============================================================
# 产品 CRUD
# ============================================================

@router.get("/products", response_model=Response[list], summary="获取产品列表")
async def list_products(
    type: Optional[str] = Query(None, description="产品类型筛选"),
    status: Optional[str] = Query(None, description="产品状态筛选"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
):
    """获取收益凭证产品列表"""
    service = get_service()
    try:
        products = await service.list_products(
            product_type=type, status=status, skip=skip, limit=limit
        )
        return Response.success(data=products, message="获取成功")
    except Exception as e:
        logger.error(f"获取产品列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取产品列表失败: {str(e)}")


@router.post("/products", response_model=Response[str], summary="创建产品")
async def create_product(data: OptionProductCreate = Body(...)):
    """创建收益凭证产品"""
    service = get_service()
    try:
        # 检查编号唯一性
        existing = await service.get_product_by_code(data.product_id)
        if existing:
            raise HTTPException(status_code=400, detail=f"产品编号已存在: {data.product_id}")

        doc = data.model_dump(by_alias=True)
        mongo_id = await service.create_product(doc)
        logger.info(f"创建产品: {data.product_id} -> {mongo_id}")
        return Response.success(data=mongo_id, message="创建成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建产品失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建产品失败: {str(e)}")


@router.get("/products/{product_id}", response_model=Response[dict], summary="获取产品详情")
async def get_product(product_id: str):
    """根据 MongoDB _id 获取产品详情"""
    service = get_service()
    try:
        product = await service.get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"产品不存在: {product_id}")
        return Response.success(data=product, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取产品失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取产品失败: {str(e)}")


@router.put("/products/{product_id}", response_model=Response[bool], summary="更新产品")
async def update_product(product_id: str, data: OptionProductUpdate = Body(...)):
    """更新收益凭证产品"""
    service = get_service()
    try:
        update_data = data.model_dump(exclude_none=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="无更新字段")
        success = await service.update_product(product_id, update_data)
        if not success:
            raise HTTPException(status_code=404, detail=f"产品不存在或无变更: {product_id}")
        logger.info(f"更新产品: {product_id}")
        return Response.success(data=True, message="更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新产品失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新产品失败: {str(e)}")


@router.delete("/products/{product_id}", response_model=Response[bool], summary="删除产品")
async def delete_product(product_id: str):
    """删除收益凭证产品"""
    service = get_service()
    try:
        success = await service.delete_product(product_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"产品不存在: {product_id}")
        logger.info(f"删除产品: {product_id}")
        return Response.success(data=True, message="删除成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除产品失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除产品失败: {str(e)}")


# ============================================================
# 市场数据
# ============================================================

@router.post("/market-data/import", response_model=Response[dict], summary="导入市场数据")
async def import_market_data(req: OptionMarketDataImportRequest = Body(...)):
    """批量导入/更新市场数据（按 date+underlying 去重）"""
    service = get_service()
    try:
        records = [item.model_dump() for item in req.records]
        result = await service.import_market_data(records)
        logger.info(f"导入市场数据: {result}")
        return Response.success(data=result, message="导入成功")
    except Exception as e:
        logger.error(f"导入市场数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入市场数据失败: {str(e)}")


@router.get("/market-data/{date}", response_model=Response[list], summary="获取市场数据")
async def get_market_data(date: str):
    """获取指定日期的市场数据"""
    service = get_service()
    try:
        data = await service.get_market_data(date)
        return Response.success(data=data, message="获取成功")
    except Exception as e:
        logger.error(f"获取市场数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取市场数据失败: {str(e)}")


@router.post("/market-data/sync-from-assets", response_model=Response[dict], summary="从资产库同步行情")
async def sync_market_data_from_assets(
    date: str = Body(..., description="日期 YYYY-MM-DD", embed=True)
):
    """从主系统 asset_prices 集合同步所有产品标的的收盘价到 option_market_data"""
    service = get_service()
    try:
        result = await service.sync_market_data_from_assets(date)
        logger.info(f"从资产库同步行情: {result}")
        return Response.success(data=result, message="同步成功")
    except Exception as e:
        logger.error(f"从资产库同步行情失败: {e}")
        raise HTTPException(status_code=500, detail=f"同步行情失败: {str(e)}")


# ============================================================
# 波动率曲面
# ============================================================

@router.post("/vol-surface/import", response_model=Response[str], summary="导入波动率曲面")
async def import_vol_surface(req: OptionVolSurfaceImportRequest = Body(...)):
    """导入/更新波动率曲面（按 underlying 去重）"""
    service = get_service()
    try:
        data = req.model_dump()
        result_id = await service.import_vol_surface(data)
        msg = "新建成功" if result_id else "更新成功"
        logger.info(f"导入波动率曲面: {req.underlying}")
        return Response.success(data=result_id, message=msg)
    except Exception as e:
        logger.error(f"导入波动率曲面失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入波动率曲面失败: {str(e)}")


@router.post("/vol-surface/import/excel", response_model=Response[str], summary="从Excel导入波动率曲面")
async def import_vol_surface_excel(
    file: UploadFile = File(..., description="Excel文件"),
    underlying: str = Form(..., description="标的资产代码"),
):
    """从Excel文件导入波动率曲面

    期望格式：
    - 第1行（表头）: 第1列为空或“Tenor\\Moneyness”，其余列为 Moneyness 网格值 (K/S)
    - 第1列: Tenor 网格值（年）
    - 交叉区域: 波动率值（小数或百分比）

    示例：
    | Tenor | 0.80 | 0.90 | 1.00 | 1.10 | 1.20 |
    |-------|------|------|------|------|------|
    | 0.083 | 0.22 | 0.21 | 0.20 | 0.21 | 0.22 |
    | 0.25  | 0.21 | 0.20 | 0.19 | 0.20 | 0.21 |
    """
    import io
    import pandas as pd
    service = get_service()
    try:
        content = await file.read()
        df = pd.read_excel(io.BytesIO(content))

        if df.empty:
            raise HTTPException(status_code=400, detail="Excel文件为空")

        # 提取 Moneyness 网格（表头，跳过第一列）
        moneyness_grid = []
        for col in df.columns[1:]:
            try:
                val = float(col)
                moneyness_grid.append(val)
            except (ValueError, TypeError):
                continue

        if not moneyness_grid:
            raise HTTPException(status_code=400, detail="无法从表头解析出 Moneyness 网格，请确保第2列起的列名为数字（如 0.80, 0.90, 1.00）")

        # 提取 Tenor 网格（第一列）和波动率矩阵
        tenor_grid = []
        vol_grid = []
        for _, row in df.iterrows():
            try:
                tenor = float(row.iloc[0])
            except (ValueError, TypeError):
                continue
            tenor_grid.append(tenor)
            row_vols = []
            for i, col in enumerate(df.columns[1:]):
                if i >= len(moneyness_grid):
                    break
                try:
                    v = float(row.iloc[i + 1])
                    # 自动检测百分比格式（> 1 的值视为百分比）
                    if v > 1:
                        v = v / 100.0
                    row_vols.append(v)
                except (ValueError, TypeError):
                    row_vols.append(0.20)  # 默认值
            # 补齐不足列
            while len(row_vols) < len(moneyness_grid):
                row_vols.append(row_vols[-1] if row_vols else 0.20)
            vol_grid.append(row_vols[:len(moneyness_grid)])

        if not tenor_grid or not vol_grid:
            raise HTTPException(status_code=400, detail="无法从数据区域解析出 Tenor 和波动率值")

        # 调用 service 保存
        data = {
            "underlying": underlying,
            "moneyness_grid": moneyness_grid,
            "tenor_grid": tenor_grid,
            "vol_grid": vol_grid,
        }
        result_id = await service.import_vol_surface(data)
        msg = "新建成功" if result_id else "更新成功"
        logger.info(f"从Excel导入波动率曲面: {underlying}, moneyness={len(moneyness_grid)}点, tenor={len(tenor_grid)}点")
        return Response.success(data=result_id, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"从Excel导入波动率曲面失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.get("/vol-surface", response_model=Response[list], summary="列出波动率曲面")
async def list_vol_surfaces():
    """列出所有波动率曲面"""
    service = get_service()
    try:
        surfaces = await service.list_vol_surfaces()
        return Response.success(data=surfaces, message="获取成功")
    except Exception as e:
        logger.error(f"获取波动率曲面列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取波动率曲面列表失败: {str(e)}")


@router.get("/vol-surface/{underlying}", response_model=Response[dict], summary="获取波动率曲面")
async def get_vol_surface(underlying: str):
    """获取指定标的的波动率曲面"""
    service = get_service()
    try:
        surface = await service.get_vol_surface(underlying)
        if not surface:
            raise HTTPException(status_code=404, detail=f"波动率曲面不存在: {underlying}")
        return Response.success(data=surface, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取波动率曲面失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取波动率曲面失败: {str(e)}")


# ============================================================
# 估值运行
# ============================================================

@router.post("/valuation/run", response_model=Response[dict], summary="运行估值")
async def run_valuation(req: OptionRunRequest = Body(...)):
    """运行收益凭证估值

    对指定日期和可选的产品列表运行估值，包括：
    - 产品加载与市场数据匹配
    - 生命周期检测（敲出/敲入/到期）
    - 逐产品定价（解析解 / 蒙特卡洛模拟）
    - 结果校验与存储
    """
    service = get_service()
    try:
        logger.info(f"开始估值运行: date={req.date}, products={req.product_ids}")
        result = await service.run_valuation(
            date_str=req.date,
            product_ids=req.product_ids,
            skip_lifecycle=req.skip_lifecycle,
        )
        if result.get("error"):
            return Response.error(message=result["error"], data=result)
        return Response.success(data=result, message="估值完成")
    except Exception as e:
        logger.error(f"估值运行失败: {e}")
        raise HTTPException(status_code=500, detail=f"估值运行失败: {str(e)}")


@router.get("/valuation/snapshot/{date}", response_model=Response[dict], summary="获取估值快照")
async def get_valuation_snapshot(date: str):
    """获取指定日期的估值快照"""
    service = get_service()
    try:
        snapshot = await service.get_valuation_snapshot(date)
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"估值快照不存在: {date}")
        return Response.success(data=snapshot, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取估值快照失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取估值快照失败: {str(e)}")


@router.get("/valuation/history", response_model=Response[list], summary="获取估值历史")
async def get_valuation_history(
    product_id: Optional[str] = Query(None, description="产品编号"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """获取估值历史记录"""
    service = get_service()
    try:
        history = await service.get_valuation_history(
            product_id=product_id,
            start_date=start_date,
            end_date=end_date,
            skip=skip,
            limit=limit,
        )
        return Response.success(data=history, message="获取成功")
    except Exception as e:
        logger.error(f"获取估值历史失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取估值历史失败: {str(e)}")


@router.get("/valuation/versions/{date}", response_model=Response[list], summary="获取估值版本列表")
async def get_valuation_versions(date: str):
    """获取指定日期的所有估值版本列表（按版本号降序）"""
    service = get_service()
    try:
        versions = await service.get_valuation_versions(date)
        return Response.success(data=versions, message="获取成功")
    except Exception as e:
        logger.error(f"获取估值版本失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取估值版本失败: {str(e)}")


@router.get("/valuation/version/{date}/{version}", response_model=Response[dict], summary="获取指定版本估值详情")
async def get_valuation_version_detail(date: str, version: int):
    """获取指定日期指定版本的完整估值详情（含产品明细）"""
    service = get_service()
    try:
        detail = await service.get_valuation_version_detail(date, version)
        if not detail:
            raise HTTPException(status_code=404, detail=f"估值版本不存在: {date} v{version}")
        return Response.success(data=detail, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取估值版本详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取估值版本详情失败: {str(e)}")


@router.post("/valuation/confirm/{date}/{version}", response_model=Response[bool], summary="确认估值版本为最终版")
async def confirm_valuation_version(
    date: str,
    version: int,
    confirmed_by: str = Body("", description="确认人", embed=True),
):
    """确认指定版本为最终版（同日其他版本的 is_final 设为 False）"""
    service = get_service()
    try:
        success = await service.confirm_valuation_version(date, version, confirmed_by)
        if not success:
            raise HTTPException(status_code=404, detail=f"估值版本不存在: {date} v{version}")
        logger.info(f"确认估值版本: {date} v{version} by {confirmed_by}")
        return Response.success(data=True, message="确认成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"确认估值版本失败: {e}")
        raise HTTPException(status_code=500, detail=f"确认估值版本失败: {str(e)}")


@router.get("/valuation/trend", response_model=Response[list], summary="获取产品估值趋势")
async def get_valuation_trend(
    product_id: str = Query(..., description="产品编号"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
):
    """获取指定产品在日期范围内的估值趋势序列（每日取最终版本）"""
    service = get_service()
    try:
        trend = await service.get_valuation_trend(
            product_id=product_id,
            start_date=start_date,
            end_date=end_date,
        )
        return Response.success(data=trend, message="获取成功")
    except Exception as e:
        logger.error(f"获取估值趋势失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取估值趋势失败: {str(e)}")


@router.post("/valuation/rerun/{date}", response_model=Response[dict], summary="重跑估值")
async def rerun_valuation(date: str, req: OptionRunRequest = Body(...)):
    """重跑指定日期的估值（创建新版本）"""
    service = get_service()
    try:
        logger.info(f"重跑估值: date={date}, products={req.product_ids}")
        result = await service.run_valuation(
            date_str=date,
            product_ids=req.product_ids,
            skip_lifecycle=req.skip_lifecycle,
        )
        if result.get("error"):
            return Response.error(message=result["error"], data=result)
        return Response.success(data=result, message="重跑完成")
    except Exception as e:
        logger.error(f"重跑估值失败: {e}")
        raise HTTPException(status_code=500, detail=f"重跑估值失败: {str(e)}")


# ============================================================
# 风险分析
# ============================================================

@router.post("/risk/analysis", response_model=Response[dict], summary="运行风险分析")
async def run_risk_analysis(req: OptionRiskRunRequest = Body(...)):
    """运行风险分析

    包括情景分析、压力测试和 P&L 归因。
    """
    service = get_service()
    try:
        logger.info(f"开始风险分析: date={req.date}")
        result = await service.run_risk_analysis(
            date_str=req.date,
            run_scenario=req.run_scenario,
            run_stress=req.run_stress,
            run_pnl=req.run_pnl,
        )
        if result.get("error"):
            return Response.error(message=result["error"], data=result)
        return Response.success(data=result, message="风险分析完成")
    except Exception as e:
        logger.error(f"风险分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"风险分析失败: {str(e)}")


@router.get("/risk/report/{date}", response_model=Response[dict], summary="获取风险报告")
async def get_risk_report(date: str):
    """获取指定日期的风险报告"""
    service = get_service()
    try:
        report = await service.get_risk_report(date)
        if not report:
            raise HTTPException(status_code=404, detail=f"风险报告不存在: {date}")
        return Response.success(data=report, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取风险报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取风险报告失败: {str(e)}")


# ============================================================
# 事件日志
# ============================================================

@router.get("/events", response_model=Response[list], summary="获取事件日志")
async def get_events(
    product_id: Optional[str] = Query(None, description="产品编号"),
    event_type: Optional[str] = Query(None, description="事件类型"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
):
    """获取生命周期事件日志"""
    service = get_service()
    try:
        events = await service.get_events(
            product_id=product_id,
            event_type=event_type,
            skip=skip,
            limit=limit,
        )
        return Response.success(data=events, message="获取成功")
    except Exception as e:
        logger.error(f"获取事件日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取事件日志失败: {str(e)}")


# ============================================================
# 估值数据管理
# ============================================================

@router.get("/valuation-data/assets", response_model=Response[list], summary="获取可用标的列表")
async def get_valuation_data_assets():
    """列出 asset_prices 中所有可用标的及其数据概况（数据条数、日期范围、最新收盘价）"""
    from app.config.database import Database
    db = Database.get_database()
    try:
        pipeline = [
            {"$group": {
                "_id": "$asset_code",
                "count": {"$sum": 1},
                "latest_date": {"$max": "$date"},
                "earliest_date": {"$min": "$date"},
                "latest_close": {"$last": "$close"},
            }},
            {"$sort": {"_id": 1}},
        ]
        results = []
        async for doc in db[COL_ASSET_PRICES].aggregate(pipeline):
            results.append({
                "asset_code": doc["_id"],
                "count": doc["count"],
                "earliest_date": doc["earliest_date"],
                "latest_date": doc["latest_date"],
                "latest_close": round(doc["latest_close"], 4) if doc.get("latest_close") else None,
            })
        return Response.success(data=results, message=f"共 {len(results)} 个可用标的")
    except Exception as e:
        logger.error(f"获取可用标的失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取可用标的失败: {str(e)}")


@router.get("/valuation-data/prices/{code}", response_model=Response[list], summary="获取标的行情序列")
async def get_valuation_data_prices(
    code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    limit: int = Query(100, ge=1, le=500, description="返回条数"),
):
    """获取指定标的的行情时间序列（按日期倒序）"""
    from app.config.database import Database
    db = Database.get_database()
    try:
        query = {"asset_code": code}
        if start_date:
            query["date"] = {"$gte": start_date}
        if end_date:
            if "date" in query:
                query["date"]["$lte"] = end_date
            else:
                query["date"] = {"$lte": end_date}

        cursor = db[COL_ASSET_PRICES].find(
            query, {"_id": 0}
        ).sort("date", -1).limit(limit)

        results = []
        async for doc in cursor:
            results.append({
                "date": doc.get("date"),
                "close": round(doc["close"], 4) if doc.get("close") else None,
                "open": round(doc["open"], 4) if doc.get("open") else None,
                "high": round(doc["high"], 4) if doc.get("high") else None,
                "low": round(doc["low"], 4) if doc.get("low") else None,
                "volume": doc.get("volume"),
                "amount": doc.get("amount"),
            })
        return Response.success(data=results, message=f"{code}: {len(results)} 条行情数据")
    except Exception as e:
        logger.error(f"获取行情数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取行情数据失败: {str(e)}")
