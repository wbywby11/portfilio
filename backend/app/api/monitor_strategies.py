# -*- coding: utf-8 -*-
"""监测策略台账 API —— monitored_strategies 的增删改查与可添加来源列表。

从 ``app/api/monitor.py`` 拆出，只为满足「api 单文件 ≤ 1000 行」的架构守卫
（见 tests/test_architecture_guard.py），路由前缀与拆分前完全一致：由
``monitor.py`` 通过 ``include_router`` 挂回同一棵路由树。

本模块只管「哪些策略被纳入监测」的台账本身，不读任何跑批产物，
因此既不注入 :class:`MonitorService` 也不注入 :class:`MonitorQueryService`。
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from loguru import logger

from app.schemas.response import Response
from app.services.monitored_strategy_service import MonitoredStrategyService

router = APIRouter()


def get_monitored_strategy_service() -> MonitoredStrategyService:
    return MonitoredStrategyService()


@router.get("/strategies", response_model=Response[list], summary="列出监测策略")
async def list_monitored_strategies(
    status: Optional[str] = Query(None, description="状态过滤: active/paused/archived"),
    source_type: Optional[str] = Query(None, description="来源过滤: researcher/system_strategy/portfolio"),
    service: MonitoredStrategyService = Depends(get_monitored_strategy_service),
):
    """列出所有监测策略（默认排除已归档）。"""
    items = await service.list(status=status, source_type=source_type)
    # 序列化 ObjectId
    for item in items:
        if "_id" in item:
            item["_id"] = str(item["_id"])
    return Response.success(data=items)


@router.post("/strategies", response_model=Response[str], summary="新增监测策略")
async def create_monitored_strategy(
    data: dict = Body(...),
    service: MonitoredStrategyService = Depends(get_monitored_strategy_service),
):
    """新增监测策略（手动添加系统策略/组合）。"""
    try:
        new_id = await service.create(data)
        return Response.success(data=new_id, message=f"监测策略创建成功")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建失败: {str(e)}")


@router.post("/strategies/from-researcher", response_model=Response[str], summary="从研究员策略创建")
async def create_from_researcher(
    code: str = Body(..., embed=True, description="研究员策略码，如 hybrid_12"),
    service: MonitoredStrategyService = Depends(get_monitored_strategy_service),
):
    """从研究员策略代码创建监测策略条目（幂等）。"""
    from pymongo.errors import DuplicateKeyError
    try:
        new_id = await service.create_from_researcher(code)
        return Response.success(data=new_id, message=f"研究员策略 {code} 已注册")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DuplicateKeyError:
        # 并发安全：已存在，重新查找返回
        existing = await service.get_by_source_ref("researcher", code)
        if existing:
            return Response.success(data=str(existing["_id"]), message="已存在")
        raise HTTPException(status_code=500, detail="注册异常")
    except Exception as e:
        logger.error(f"注册研究员策略失败: {code}, error={e}")
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")


@router.put("/strategies/{strategy_id}", response_model=Response[bool], summary="更新监测策略")
async def update_monitored_strategy(
    strategy_id: str,
    data: dict = Body(...),
    service: MonitoredStrategyService = Depends(get_monitored_strategy_service),
):
    """更新监测策略（改名/状态/描述）。"""
    success = await service.update(strategy_id, data)
    if not success:
        raise HTTPException(status_code=404, detail="监测策略不存在或无有效更新")
    return Response.success(data=True, message="更新成功")


@router.delete("/strategies/{strategy_id}", response_model=Response[bool], summary="归档监测策略")
async def archive_monitored_strategy(
    strategy_id: str,
    service: MonitoredStrategyService = Depends(get_monitored_strategy_service),
):
    """归档监测策略（软删除）。"""
    success = await service.update_status(strategy_id, "archived")
    if not success:
        raise HTTPException(status_code=404, detail="监测策略不存在")
    return Response.success(data=True, message="监测策略已归档")


@router.get("/researcher-strategies", response_model=Response[list], summary="列出可用研究员策略")
async def list_researcher_strategies():
    """列出所有可注册的研究员策略（尚未加入监测列表的）。"""
    from app.monitor.researcher_strategies import list_researcher_strategies as _list
    return Response.success(data=_list())


@router.get("/addable-strategies", response_model=Response[dict], summary="列出可添加的监控策略")
async def list_addable_strategies(
    service: MonitoredStrategyService = Depends(get_monitored_strategy_service),
):
    """列出所有可添加到监控的策略：研究员策略 + 已实盘发布的策略/组合。"""
    from app.monitor.researcher_strategies import list_researcher_strategies as _list
    from app.services.strategy_model_service import StrategyModelService

    # 研究员策略
    researcher = _list()

    # 已实盘发布的策略/组合
    svc = StrategyModelService()
    cursor = svc.collection.find(
        {"live_publish_enabled": True},
        {"name": 1, "is_portfolio": 1, "template_code": 1, "asset_codes": 1},
    )
    live_published = []
    async for doc in cursor:
        model_id = str(doc["_id"])
        is_portfolio = doc.get("is_portfolio", False)
        source_type = "portfolio" if is_portfolio else "system_strategy"
        live_published.append({
            "model_id": model_id,
            "name": doc.get("name", f"策略{model_id[:8]}"),
            "source_type": source_type,
            "template_code": doc.get("template_code", ""),
            "asset_count": len(doc.get("asset_codes", [])),
        })

    return Response.success(data={
        "researcher": researcher,
        "live_published": live_published,
    })


@router.post("/strategies/from-live", response_model=Response[str], summary="从实盘发布策略创建监控条目")
async def create_from_live_published(
    data: dict = Body(..., description="含 model_id 和 source_type"),
    service: MonitoredStrategyService = Depends(get_monitored_strategy_service),
):
    """从已实盘发布的策略/组合创建监控条目（幂等）。"""
    model_id = data.get("model_id", "")
    source_type = data.get("source_type", "system_strategy")
    if not model_id:
        raise HTTPException(status_code=400, detail="缺少 model_id")

    existing = await service.get_by_source_ref(source_type, model_id)
    if existing:
        # 若已归档则重新激活
        if existing.get("status") == "archived":
            await service.update_status(str(existing["_id"]), "active")
        return Response.success(data=str(existing["_id"]), message="已存在")

    from app.services.strategy_model_service import StrategyModelService
    svc = StrategyModelService()
    model = await svc.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")

    # 描述优先取模型自身描述：监控列表要能看出策略讲什么，只放模板代码
    # （如「实盘发布组合（portfolio）」）没有信息量；模型未填描述时才回退。
    _desc = (getattr(model, "description", "") or "").strip()
    if not _desc:
        _desc = f"实盘发布{'组合' if model.is_portfolio else '策略'}（{model.template_code}）"
    new_doc = {
        "display_name": model.name,
        "source_type": source_type,
        "source_ref": model_id,
        "description": _desc,
        "asset_codes": model.asset_codes,
        "status": "active",
    }
    from pymongo.errors import DuplicateKeyError
    try:
        new_id = await service.create(new_doc)
    except DuplicateKeyError:
        existing = await service.get_by_source_ref(source_type, model_id)
        if existing:
            if existing.get("status") == "archived":
                await service.update_status(str(existing["_id"]), "active")
            return Response.success(data=str(existing["_id"]), message="已存在")
        raise HTTPException(status_code=500, detail="创建异常")
    return Response.success(data=new_id, message=f"{model.name} 已添加到监控")
