# -*- coding: utf-8 -*-
"""
监控模块 API 路由

提供日常组合监控、主观调仓和日报查询等功能的 REST API 端点。
路由前缀: /api/v1/monitor (在 main.py 中注册时添加)
"""
import re
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from loguru import logger

from app.schemas.response import Response
from app.services.monitor_service import MonitorService
from app.services.strategy_model_service import StrategyModelService
from app.services.monitored_strategy_service import MonitoredStrategyService
from app.models.monitor import SubjectiveOverrideCreate


router = APIRouter()


def get_monitor_service() -> MonitorService:
    """获取监控服务实例"""
    return MonitorService()


async def assert_daily_monitor_eligible_gate() -> None:
    """日常监控准入检查：研究员策略始终可用，不再强制要求实盘发布策略。"""
    # 研究员策略始终可用，无需门禁
    pass


def validate_date_format(date_str: str, field_name: str = "日期") -> str:
    """验证日期格式 YYYY-MM-DD"""
    if not date_str:
        return date_str
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    if not re.match(pattern, date_str):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name}格式无效: {date_str}，应为 YYYY-MM-DD"
        )
    # 验证日期有效性
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name}无效: {date_str}，不是有效的日期"
        )
    return date_str


def validate_weights(weights: dict) -> dict:
    """校验权重字典的合法性"""
    if not weights:
        raise HTTPException(status_code=400, detail="权重不能为空")
    
    for asset, w in weights.items():
        if not isinstance(w, (int, float)):
            raise HTTPException(
                status_code=400,
                detail=f"资产 {asset} 的权重必须是数字，当前值: {w}"
            )
        if w < 0:
            raise HTTPException(
                status_code=400,
                detail=f"资产 {asset} 的权重不能为负数: {w}"
            )
    
    return weights


# ============================================================
# 状态查询
# ============================================================

@router.get("/state", response_model=Response[dict], summary="获取当前监控状态")
async def get_monitor_state(monitor_id: str = Query("default", description="监控实例 ID")):
    """
    获取当前监控状态
    
    返回完整的组合监控状态数据，包括：
    - 净值、持仓、目标权重
    - 费用统计、波动率重置次数
    - 净值历史、事件日志等
    """
    service = get_monitor_service()
    try:
        state = await service.get_state(monitor_id)
        if not state:
            raise HTTPException(
                status_code=404,
                detail=f"监控状态不存在: {monitor_id}，请先运行初始化"
            )
        
        logger.info(f"获取监控状态: monitor_id={monitor_id}, date={state.date}")
        return Response.success(
            data=state.model_dump(by_alias=True, exclude_none=False),
            message="获取成功"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取监控状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取监控状态失败: {str(e)}")


@router.get("/nav-history", response_model=Response[list], summary="获取净值历史")
async def get_nav_history(
    monitor_id: str = Query("default", description="监控实例 ID"),
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD")
):
    """
    获取净值历史数据
    
    支持日期范围筛选，返回格式：[{"date": "YYYY-MM-DD", "nav": 1.23}, ...]
    """
    service = get_monitor_service()
    try:
        if start:
            validate_date_format(start, "开始日期")
        if end:
            validate_date_format(end, "结束日期")
        
        history = await service.get_nav_history(monitor_id, start, end)
        logger.info(f"获取净值历史: monitor_id={monitor_id}, count={len(history)}")
        return Response.success(data=history, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取净值历史失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取净值历史失败: {str(e)}")


@router.get("/events", response_model=Response[list], summary="获取事件日志")
async def get_monitor_events(
    monitor_id: str = Query("default", description="监控实例 ID"),
    type: Optional[str] = Query(None, description="事件类型筛选（如 monthly_rebalance, vol_reset_trigger 等）"),
    limit: int = Query(50, ge=1, le=500, description="返回条数限制")
):
    """
    获取事件日志
    
    事件类型包括：
    - init: 初始化
    - monthly_rebalance: 月度调仓
    - vol_reset_trigger: 波动率重置触发
    - vol_reset_execute: 波动率重置执行
    - subjective_rebalance: 主观调仓
    """
    service = get_monitor_service()
    try:
        events = await service.get_events(monitor_id, type, limit)
        logger.info(f"获取事件日志: monitor_id={monitor_id}, type={type}, count={len(events)}")
        return Response.success(data=events, message="获取成功")
    except Exception as e:
        logger.error(f"获取事件日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取事件日志失败: {str(e)}")


@router.get("/positions", response_model=Response[dict], summary="获取当前持仓明细")
async def get_monitor_positions(monitor_id: str = Query("default", description="监控实例 ID")):
    """
    获取当前持仓明细
    
    返回各资产的：
    - name: 资产名称
    - code: 资产代码
    - asset_class: 资产类别（权益/固定收益/大宗商品）
    - current_weight: 当前权重%（基于市值）
    - daily_change: 当日涨跌%（底层资产价格变动）
    - currency: 计价货币
    """
    service = get_monitor_service()
    try:
        positions = await service.get_positions(monitor_id)
        logger.info(f"获取持仓明细: monitor_id={monitor_id}")
        return Response.success(data=positions, message="获取成功")
    except Exception as e:
        logger.error(f"获取持仓明细失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取持仓明细失败: {str(e)}")


@router.get("/daily-attribution", response_model=Response[dict], summary="获取当日损益归因")
async def get_daily_attribution(
    monitor_id: str = Query("default", description="监控实例 ID"),
    date: Optional[str] = Query(None, description="目标日期 YYYY-MM-DD，默认最新")
):
    """
    获取各底层资产对组合当日损益的贡献
    
    返回：
    - date: 日期
    - attributions: 各资产归因明细 [{name, code, asset_class, weight, daily_change, contribution, currency}, ...]
    - total_pnl: 组合当日总损益
    - prev_nav: 前一日净值
    - current_nav: 当日净值
    """
    service = get_monitor_service()
    try:
        if date:
            validate_date_format(date, "目标日期")
        
        data = await service.get_daily_attribution(monitor_id, date)
        logger.info(f"获取损益归因: monitor_id={monitor_id}, date={data.get('date')}")
        return Response.success(data=data, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取损益归因失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取损益归因失败: {str(e)}")


@router.get("/performance", response_model=Response[dict], summary="获取绩效指标")
async def get_monitor_performance(monitor_id: str = Query("default", description="监控实例 ID")):
    """
    获取绩效指标
    
    返回：
    - 累计收益率、年化收益率
    - 年化波动率、最大回撤
    - 夏普比率、卡玛比率
    - 交易费用、复制费用统计
    """
    service = get_monitor_service()
    try:
        performance = await service.get_performance(monitor_id)
        if not performance:
            raise HTTPException(
                status_code=404,
                detail=f"监控状态不存在: {monitor_id}"
            )
        logger.info(f"获取绩效指标: monitor_id={monitor_id}")
        return Response.success(data=performance, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取绩效指标失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取绩效指标失败: {str(e)}")


@router.get("/signals", response_model=Response[dict], summary="获取信号状态")
async def get_monitor_signals(monitor_id: str = Query("default", description="监控实例 ID")):
    """
    获取信号状态
    
    返回：
    - 下次月度调仓日期
    - 波动率重置阈值
    - 待执行调仓信息（如有）
    """
    service = get_monitor_service()
    try:
        signals = await service.get_signal_status(monitor_id)
        if not signals:
            raise HTTPException(
                status_code=404,
                detail=f"监控状态不存在: {monitor_id}"
            )
        logger.info(f"获取信号状态: monitor_id={monitor_id}")
        return Response.success(data=signals, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取信号状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取信号状态失败: {str(e)}")


# ============================================================
# 运行控制
# ============================================================

@router.post("/run", response_model=Response[dict], summary="触发监控运行")
async def run_monitor(
    monitor_id: str = Query("default", description="监控实例 ID"),
    target_date: Optional[str] = Query(None, description="目标日期 YYYY-MM-DD，默认最新"),
    manual_preset_step: bool = Query(
        False,
        description="主观配置策略时：在每档预设调仓日当日推演完成后暂停并落库，便于查看绩效后再续跑",
    ),
):
    """
    触发监控运行到指定日期
    
    从上次状态续接到目标日期（默认数据最新日期）。
    注意：可能是耗时操作。
    """
    service = get_monitor_service()
    try:
        await assert_daily_monitor_eligible_gate()
        if target_date:
            validate_date_format(target_date, "目标日期")
        
        logger.info(f"开始日常监控运行: monitor_id={monitor_id}, target_date={target_date}")
        result = await service.run_daily(
            monitor_id, target_date, manual_preset_step=manual_preset_step
        )
        logger.info(f"日常监控运行完成: {result}")
        msg = result.get("message") if result.get("paused") else "运行完成"
        return Response.success(data=result, message=msg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"监控运行失败: {e}")
        raise HTTPException(status_code=500, detail=f"监控运行失败: {str(e)}")


@router.post("/init", response_model=Response[dict], summary="初始化监控")
async def init_monitor(
    monitor_id: str = Query("default", description="监控实例 ID"),
    start_date: Optional[str] = Query(None, description="启动日期 YYYY-MM-DD，默认为配置中的基日"),
    manual_preset_step: bool = Query(
        False,
        description="主观配置策略时：在每档预设调仓日当日完成后暂停，与回测步进一致，便于查看区间绩效",
    ),
):
    """
    初始化监控（从指定日期开始）
    
    从指定启动日期（默认 2014-02-10 基日）开始，逐日推演到数据最新日期。
    警告：这是非常耗时的操作（可能需要数分钟），仅在首次部署或重置时使用。
    """
    service = get_monitor_service()
    try:
        await assert_daily_monitor_eligible_gate()
        # 验证日期格式
        if start_date:
            validate_date_format(start_date, "启动日期")
        
        logger.warning(f"开始初始化监控（耗时操作）: monitor_id={monitor_id}, start_date={start_date}")
        result = await service.run_init(
            monitor_id, start_date=start_date, manual_preset_step=manual_preset_step
        )
        logger.info(f"初始化监控完成: {result}")
        msg = (
            result.get("message")
            if result.get("paused")
            else "初始化完成"
        )
        return Response.success(data=result, message=msg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"初始化监控失败: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"初始化监控失败: {str(e)}")


@router.post("/run-range", response_model=Response[dict], summary="按日期范围运行")
async def run_monitor_range(
    monitor_id: str = Query("default", description="监控实例 ID"),
    from_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    to_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    manual_preset_step: bool = Query(
        False,
        description="主观配置策略时：在每档预设调仓日当日完成后暂停",
    ),
):
    """
    按日期范围运行
    
    从指定开始日期到结束日期运行监控流程。
    适用于特定日期范围的补算或验证。
    """
    service = get_monitor_service()
    try:
        await assert_daily_monitor_eligible_gate()
        validate_date_format(from_date, "开始日期")
        validate_date_format(to_date, "结束日期")
        
        if from_date > to_date:
            raise HTTPException(
                status_code=400,
                detail=f"开始日期不能晚于结束日期: {from_date} > {to_date}"
            )
        
        logger.info(f"开始范围运行: monitor_id={monitor_id}, {from_date} ~ {to_date}")
        result = await service.run_range(
            monitor_id, from_date, to_date, manual_preset_step=manual_preset_step
        )
        logger.info(f"范围运行完成: {result}")
        msg = result.get("message") if result.get("paused") else "运行完成"
        return Response.success(data=result, message=msg)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"范围运行失败: {e}")
        raise HTTPException(status_code=500, detail=f"范围运行失败: {str(e)}")


# ============================================================
# 日报
# ============================================================

@router.get("/reports/{date}", response_model=Response[dict], summary="获取指定日期日报")
async def get_monitor_report(
    date: str,
    monitor_id: str = Query("default", description="监控实例 ID")
):
    """
    获取指定日期的日报数据
    
    返回当日的净值、收益率、持仓、信号状态等快照数据。
    """
    service = get_monitor_service()
    try:
        validate_date_format(date, "日期")
        
        report = await service.get_daily_report(monitor_id, date)
        if not report:
            raise HTTPException(
                status_code=404,
                detail=f"日报不存在: {monitor_id}/{date}"
            )
        logger.info(f"获取日报: monitor_id={monitor_id}, date={date}")
        return Response.success(data=report, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日报失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日报失败: {str(e)}")


@router.get("/reports", response_model=Response[list], summary="日报列表")
async def get_monitor_report_list(
    monitor_id: str = Query("default", description="监控实例 ID"),
    skip: int = Query(0, ge=0, description="跳过条数"),
    limit: int = Query(30, ge=1, le=100, description="返回条数限制")
):
    """
    获取日报列表
    
    支持分页，按日期倒序返回。
    """
    service = get_monitor_service()
    try:
        reports = await service.get_report_list(monitor_id, skip, limit)
        logger.info(f"获取日报列表: monitor_id={monitor_id}, count={len(reports)}")
        return Response.success(data=reports, message="获取成功")
    except Exception as e:
        logger.error(f"获取日报列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日报列表失败: {str(e)}")


# ============================================================
# 主观调仓
# ============================================================

@router.get("/subjective", response_model=Response[list], summary="列出主观调仓指令")
async def list_subjective_overrides(
    monitor_id: str = Query("default", description="监控实例 ID"),
    status: Optional[str] = Query(None, description="状态筛选: pending/executed/cancelled")
):
    """
    列出主观调仓指令
    
    可按状态筛选：
    - pending: 待执行
    - executed: 已执行
    - cancelled: 已取消
    """
    service = get_monitor_service()
    try:
        # 验证状态值
        if status and status not in ['pending', 'executed', 'cancelled']:
            raise HTTPException(
                status_code=400,
                detail=f"无效的状态值: {status}，有效值为: pending/executed/cancelled"
            )
        
        overrides = await service.list_subjective_overrides(monitor_id, status)
        logger.info(f"获取主观调仓列表: monitor_id={monitor_id}, status={status}, count={len(overrides)}")
        return Response.success(data=overrides, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取主观调仓列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取主观调仓列表失败: {str(e)}")


@router.post("/subjective", response_model=Response[str], summary="新增主观调仓指令")
async def add_subjective_override(
    data: SubjectiveOverrideCreate = Body(..., description="主观调仓请求")
):
    """
    新增主观调仓指令
    
    请求体：
    - monitor_id: 监控实例 ID
    - weights: 目标权重 {资产名: 权重}
    - execute_date: 执行日期 YYYY-MM-DD
    - description: 调仓描述（可选）
    
    返回新创建的 override_id。
    """
    service = get_monitor_service()
    try:
        # 验证日期格式
        validate_date_format(data.execute_date, "执行日期")
        
        # 验证权重
        validate_weights(data.weights)
        
        override_id = await service.add_subjective_override(
            monitor_id=data.monitor_id,
            weights=data.weights,
            execute_date=data.execute_date,
            description=data.description
        )
        
        logger.info(f"创建主观调仓指令: override_id={override_id}, execute_date={data.execute_date}")
        return Response.success(data=override_id, message="主观调仓指令创建成功")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建主观调仓指令失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建主观调仓指令失败: {str(e)}")


@router.put("/subjective/{override_id}/cancel", response_model=Response[bool], summary="取消主观调仓指令")
async def cancel_subjective_override(override_id: str):
    """
    取消主观调仓指令
    
    仅 pending 状态的指令可以取消。
    """
    service = get_monitor_service()
    try:
        success = await service.cancel_subjective_override(override_id)
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"主观调仓指令不存在或状态非 pending: {override_id}"
            )
        
        logger.info(f"取消主观调仓指令: override_id={override_id}")
        return Response.success(data=True, message="主观调仓指令已取消")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消主观调仓指令失败: {e}")
        raise HTTPException(status_code=500, detail=f"取消主观调仓指令失败: {str(e)}")


# ============================================================
# 监测策略管理（monitored_strategies）
# ============================================================

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

    new_doc = {
        "display_name": model.name,
        "source_type": source_type,
        "source_ref": model_id,
        "description": f"实盘发布{'组合' if model.is_portfolio else '策略'}（{model.template_code}）",
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
