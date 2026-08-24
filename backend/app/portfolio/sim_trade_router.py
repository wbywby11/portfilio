# -*- coding: utf-8 -*-
"""
模拟交易 API 路由

路由前缀: /api/v1/sim-trade
"""
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Body
from loguru import logger

from app.schemas.response import Response
from app.portfolio.schemas import SimAdvanceRequest, BatchAdvanceRequest
from app.portfolio.sim_trade_service import SimTradeService


router = APIRouter()


def get_service() -> SimTradeService:
    return SimTradeService()


# ============================================================
# 推进
# ============================================================

@router.post("/{portfolio_id}/advance", response_model=Response[dict], summary="推进模拟交易")
async def advance_sim_trade(
    portfolio_id: str,
    req: SimAdvanceRequest = Body(default=SimAdvanceRequest()),
):
    """将模拟组合从当前状态逐日推进到目标日期"""
    service = get_service()
    try:
        target = None
        if req.target_date:
            target = datetime.strptime(req.target_date, "%Y-%m-%d").date()
        result = await service.advance_portfolio(portfolio_id, target)
        return Response.success(data=result, message=result.get("message", "推进完成"))
    except Exception as e:
        logger.error(f"推进模拟交易失败: {e}")
        raise HTTPException(status_code=500, detail=f"推进失败: {str(e)}")


@router.post("/batch-advance", response_model=Response[list], summary="批量推进")
async def batch_advance(req: BatchAdvanceRequest = Body(default=BatchAdvanceRequest())):
    """批量推进所有活跃模拟组合"""
    service = get_service()
    try:
        target = None
        if req.target_date:
            target = datetime.strptime(req.target_date, "%Y-%m-%d").date()
        results = await service.batch_advance(target, req.portfolio_ids)
        return Response.success(data=results, message=f"批量推进完成，共 {len(results)} 个组合")
    except Exception as e:
        logger.error(f"批量推进失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量推进失败: {str(e)}")


# ============================================================
# 查询
# ============================================================

@router.get("/{portfolio_id}/trades", response_model=Response[dict], summary="查询成交记录")
async def get_trades(
    portfolio_id: str,
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
):
    """查询模拟成交记录（分页 + 日期筛选）"""
    service = get_service()
    try:
        result = await service.get_trades(portfolio_id, start_date, end_date, skip, limit)
        return Response.success(data=result)
    except Exception as e:
        logger.error(f"查询成交记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/{portfolio_id}/snapshots", response_model=Response[dict], summary="查询逐日快照")
async def get_snapshots(
    portfolio_id: str,
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
):
    """查询模拟组合逐日快照"""
    service = get_service()
    try:
        result = await service.get_snapshots(portfolio_id, start_date, end_date, skip, limit)
        return Response.success(data=result)
    except Exception as e:
        logger.error(f"查询快照失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


# ============================================================
# 报告
# ============================================================

@router.get("/{portfolio_id}/tracking", response_model=Response[dict], summary="跟踪误差报告")
async def get_tracking_report(portfolio_id: str):
    """获取模拟组合与回测基准的跟踪误差分析"""
    service = get_service()
    try:
        result = await service.get_tracking_report(portfolio_id)
        return Response.success(data=result, message="跟踪误差报告")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"跟踪误差报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"报告生成失败: {str(e)}")


@router.get("/{portfolio_id}/attribution", response_model=Response[dict], summary="绩效归因报告")
async def get_attribution_report(portfolio_id: str):
    """获取 Brinson 绩效归因报告"""
    service = get_service()
    try:
        result = await service.get_attribution_report(portfolio_id)
        return Response.success(data=result, message="绩效归因报告")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"绩效归因报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"报告生成失败: {str(e)}")
