# -*- coding: utf-8 -*-
"""
监控模块 API 路由

提供日常组合监控、主观调仓和日报查询等功能的 REST API 端点。
路由前缀: /api/v1/monitor (在 main.py 中注册时添加)

读写分界（批次化改造后不得越界）：
- **所有 GET 端点**只注入 :class:`MonitorQueryService`（纯读表），统一接受可选
  ``batch_id``，不传则读最新 ``completed`` 批次；缓存/快照缺失直接 404，
  绝对不在请求里重建绩效缓存或触发推演（缓存只在跑批写入侧重建）。
- **所有触发端点**（/init /run /run-range）异步提交后台任务，立即返回
  ``{task_id, batch_id, status: "pending"}``，进度走 ``GET /tasks/{task_id}`` 轮询。
- 边界由 ``tests/test_monitor_readonly_endpoints.py`` 的 AST 断言守住。
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from loguru import logger

from app.api.monitor_deps import (
    BATCH_ID_DESC,
    assert_daily_monitor_eligible_gate,
    get_monitor_query_service,
    get_monitor_service,
    missing,
    validate_date_format,
    validate_weights,
)
from app.schemas.response import Response
from app.services.monitor_query_service import MonitorQueryService
from app.services.monitor_task_service import (
    TASK_KIND_INIT,
    TASK_KIND_RANGE,
    TASK_KIND_RUN,
)
from app.models.monitor import SubjectiveOverrideCreate, OperationRemarkUpdate


router = APIRouter()


# ============================================================
# 状态查询
# ============================================================

@router.get("/state", response_model=Response[dict], summary="获取当前监控状态")
async def get_monitor_state(
    monitor_id: str = Query("default", description="监控实例 ID"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """获取指定批次的监控状态（纯读表）

    返回完整的组合监控状态文档，包括：
    - 净值、持仓、目标权重
    - 费用统计、波动率重置次数
    - 净值历史、事件日志等
    - ``batch_id``：本文档所属的运行批次
    """
    try:
        state = await query.get_state(monitor_id, batch_id)
        if not state:
            raise missing(f"监控状态不存在: {monitor_id}，请先运行初始化")

        logger.info(
            f"获取监控状态: monitor_id={monitor_id}, "
            f"batch_id={state.get('batch_id')}, date={state.get('date')}"
        )
        return Response.success(data=state, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取监控状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取监控状态失败: {str(e)}")


@router.get("/nav-history", response_model=Response[list], summary="获取净值历史")
async def get_nav_history(
    monitor_id: str = Query("default", description="监控实例 ID"),
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """获取净值历史数据（纯读表）

    支持日期范围筛选，返回格式：[{"date": "YYYY-MM-DD", "nav": 1.23}, ...]
    """
    try:
        if start:
            validate_date_format(start, "开始日期")
        if end:
            validate_date_format(end, "结束日期")

        history = await query.get_nav_history(monitor_id, start, end, batch_id)
        if history is None:
            raise missing(f"监控状态不存在: {monitor_id}，请先运行初始化")
        logger.info(
            f"获取净值历史: monitor_id={monitor_id}, batch_id={batch_id or 'latest'}, "
            f"count={len(history)}"
        )
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
    limit: int = Query(50, ge=1, le=500, description="返回条数限制"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """获取事件日志（纯读表）

    事件类型包括：
    - init: 初始化
    - monthly_rebalance: 月度调仓
    - vol_reset_trigger: 波动率重置触发
    - vol_reset_execute: 波动率重置执行
    - subjective_rebalance: 主观调仓
    """
    try:
        events = await query.get_events(monitor_id, type, limit, batch_id)
        if events is None:
            raise missing(f"监控状态不存在: {monitor_id}，请先运行初始化")
        logger.info(
            f"获取事件日志: monitor_id={monitor_id}, type={type}, count={len(events)}"
        )
        return Response.success(data=events, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取事件日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取事件日志失败: {str(e)}")


@router.get("/positions", response_model=Response[dict], summary="获取当前持仓明细")
async def get_monitor_positions(
    monitor_id: str = Query("default", description="监控实例 ID"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """获取当前持仓明细（纯读表：读该批次的绩效缓存快照）

    返回各资产的：
    - name: 资产名称
    - code: 资产代码
    - asset_class: 资产类别（权益/固定收益/大宗商品）
    - current_weight: 当前权重%（基于市值）
    - daily_change: 当日涨跌%（底层资产价格变动）
    - currency: 计价货币
    """
    try:
        positions = await query.get_positions(monitor_id, batch_id)
        if positions is None:
            raise missing(f"绩效缓存不存在: {monitor_id}，请先运行初始化")
        logger.info(f"获取持仓明细: monitor_id={monitor_id}, batch_id={batch_id or 'latest'}")
        return Response.success(data=positions, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取持仓明细失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取持仓明细失败: {str(e)}")


@router.get("/daily-attribution", response_model=Response[dict], summary="获取当日损益归因")
async def get_daily_attribution(
    monitor_id: str = Query("default", description="监控实例 ID"),
    date: Optional[str] = Query(None, description="目标日期 YYYY-MM-DD，默认最新"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """获取各底层资产对组合当日损益的贡献（纯读表）

    返回：
    - date: 日期
    - attributions: 各资产归因明细 [{name, code, asset_class, weight, daily_change, contribution, currency}, ...]
    - total_pnl: 组合当日总损益
    - prev_nav: 前一日净值
    - current_nav: 当日净值
    """
    try:
        if date:
            validate_date_format(date, "目标日期")

        data = await query.get_daily_attribution(monitor_id, date, batch_id)
        if data is None:
            raise missing(f"绩效缓存不存在: {monitor_id}，请先运行初始化")
        logger.info(f"获取损益归因: monitor_id={monitor_id}, date={data.get('date')}")
        return Response.success(data=data, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取损益归因失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取损益归因失败: {str(e)}")


@router.get("/performance", response_model=Response[dict], summary="获取绩效指标")
async def get_monitor_performance(
    monitor_id: str = Query("default", description="监控实例 ID"),
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD，默认全区间"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD，默认最新"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """获取绩效指标（纯读表：指标由该批次缓存净值序列投影得到）

    返回：
    - 累计收益率、年化收益率
    - 年化波动率、最大回撤
    - 夏普比率、卡玛比率、调仓周期胜率
    - 交易费用、复制费用统计
    """
    try:
        if start:
            validate_date_format(start, "开始日期")
        if end:
            validate_date_format(end, "结束日期")

        performance = await query.get_performance(monitor_id, start, end, batch_id)
        if not performance:
            raise missing(f"绩效缓存不存在: {monitor_id}，请先运行初始化")
        logger.info(
            f"获取绩效指标: monitor_id={monitor_id}, "
            f"batch_id={performance.get('batch_id')}"
        )
        return Response.success(data=performance, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取绩效指标失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取绩效指标失败: {str(e)}")


@router.get(
    "/performance-panel",
    response_model=Response[dict],
    summary="获取绩效页统一数据（预计算缓存，按区间读取）",
)
async def get_performance_panel_api(
    monitor_id: str = Query("default", description="监控实例 ID（实盘策略即策略模型 ID）"),
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD，默认全区间"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD，默认最新"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """绩效页所有卡片共用一份数据（同一周期）。

    **只读不重建**：缓存由跑批结束时写入，本端点只做区间投影；
    缓存缺失（新批次还没跑完 / 存量实例未重跑）直接 404。

    返回：
    - batch_id: 本次读取的批次号
    - range: 实际采用的区间（含全区间边界与是否被夹取）
    - nav_history / nav_history_model: 区间内双轨净值序列（含日收益/累计收益/回撤/调仓标记）
    - metrics: 区间绩效指标（年化 260、几何夏普，与全系统同口径）
    - positions: 区间末最近持仓快照与类别分布
    - attribution: 区间收益归因（NAV 链接多期归因，人民币口径）
    - asset_analysis: 区间内底层资产相关性矩阵与年化指标
    """
    try:
        if start:
            validate_date_format(start, "开始日期")
        if end:
            validate_date_format(end, "结束日期")

        data = await query.get_panel(monitor_id, start, end, batch_id)
        if data is None:
            raise missing(f"绩效缓存不存在: {monitor_id}，请先运行初始化")
        logger.info(
            f"获取绩效页数据: monitor_id={monitor_id}, batch_id={data['batch_id']}, "
            f"range={data['range']['start']}~{data['range']['end']}, "
            f"nav={len(data['nav_history'])}"
        )
        return Response.success(data=data, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取绩效页数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取绩效页数据失败: {str(e)}")


@router.get("/performance-dual", response_model=Response[dict], summary="获取双轨绩效对比")
async def get_dual_performance(
    monitor_id: str = Query("default", description="监控实例 ID"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """双轨绩效对比（纯读表）：
    - model: 模型口径（纯系统信号自动执行，不含主观调整）
    - actual: 实际口径（纳入主观调整后的真实净值）
    另附双轨净值序列与主观分歧事件（分歧事件跨批次，属于实例历史事实）。
    """
    try:
        result = await query.get_dual_performance(monitor_id, batch_id)
        if not result:
            raise missing(f"绩效缓存不存在: {monitor_id}，请先运行初始化")
        return Response.success(data=result, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取双轨绩效失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取双轨绩效失败: {str(e)}")


@router.get("/operations", response_model=Response[dict], summary="获取操作指令（策略维度分组）")
async def list_monitor_operations(
    monitor_id: str = Query("default", description="监控实例 ID"),
    status: Optional[str] = Query(None, description="状态筛选: pending/executed/superseded/cancelled"),
    strategy_key: Optional[str] = Query(None, description="策略维度键（子策略 model_id 或 portfolio）"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """按策略维度分组返回操作指令（含目标权重明细与状态）。
    待执行指令置顶（预展示窗口：信号日 → 执行日）。
    默认只看展示批次；尚未跑过的实例返回空分组而不是 404。

    groups 内每条指令除权重明细外，组合层另带 ``strategy_breakdown`` /
    ``prev_strategy_breakdown``（子策略 → 策略内资产权重）；顶层 ``asset_meta``
    给出指令涉及的资产名称与各自最近收盘价，不含任何绝对金额——
    规模由前端按用户输入现算。
    """
    if status and status not in ('pending', 'executed', 'superseded', 'cancelled'):
        raise HTTPException(
            status_code=400,
            detail=f"无效的状态值: {status}，有效值为: pending/executed/superseded/cancelled"
        )
    try:
        result = await query.get_operations_grouped(
            monitor_id, status=status, strategy_key=strategy_key, batch_id=batch_id
        )
        return Response.success(data=result, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取操作指令失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取操作指令失败: {str(e)}")


@router.patch(
    "/operations/{operation_id}/remark",
    response_model=Response[dict],
    summary="补充说明操作指令",
)
async def update_operation_remark(
    operation_id: str,
    data: OperationRemarkUpdate = Body(..., description="补充说明请求"),
):
    """为已执行指令追加/更新补充说明（空字符串表示清除）。

    remark 存独立集合 monitor_operation_remarks，按业务键挂靠，
    组合通道全量重建 ops 后不会丢失。
    """
    service = get_monitor_service()
    try:
        result = await service.update_operation_remark(operation_id, data.remark)
        logger.info(
            f"更新操作指令补充说明: operation_id={operation_id}, "
            f"remark_len={len(result.get('remark') or '')}"
        )
        return Response.success(data=result, message="补充说明已保存")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"更新操作指令补充说明失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新补充说明失败: {str(e)}")


@router.get("/positions-overlap", response_model=Response[dict], summary="多监控实例持仓重叠")
async def get_positions_overlap(
    monitor_ids: Optional[str] = Query(
        None,
        description="逗号分隔的监控实例 ID；不传则取全部已登记且未归档实例",
    ),
    top: int = Query(10, ge=1, le=50, description="返回重叠资产条目数"),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """持仓重叠（纯读表）：同一资产在多个监控实例中的权重合计。

    权重口径 = positions_cny / nav，资产代码经 canonical_price_code 归一化；
    每个实例各取自己最新 completed 批次的状态文档，按合计权重降序返回 Top N。
    """
    try:
        ids = [s.strip() for s in monitor_ids.split(",") if s.strip()] if monitor_ids else None
        data = await query.get_positions_overlap(ids, top=top)
        logger.info(
            f"获取持仓重叠: monitor_count={data['monitor_count']}, "
            f"asset_count={data['asset_count']}, ids={ids or 'all'}"
        )
        return Response.success(data=data, message="获取成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"获取持仓重叠失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取持仓重叠失败: {str(e)}")


@router.get("/signals", response_model=Response[dict], summary="获取信号状态")
async def get_monitor_signals(
    monitor_id: str = Query("default", description="监控实例 ID"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """获取信号状态（纯读表：读跑批收尾时物化到状态文档的快照）

    返回：
    - 下次月度调仓日期
    - 波动率重置阈值
    - 待执行调仓信息（如有）
    - snapshot_at: 快照生成时间（= 本批次跑批收尾时刻）

    存量批次没有快照（未重跑过）时返回 404，不在请求里回源行情库重算。
    """
    try:
        signals = await query.get_signals(monitor_id, batch_id)
        if not signals:
            raise missing(
                f"信号快照不存在: {monitor_id}，该批次尚未物化信号数据，请重新运行一次"
            )
        logger.info(f"获取信号状态: monitor_id={monitor_id}, batch_id={batch_id or 'latest'}")
        return Response.success(data=signals, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取信号状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取信号状态失败: {str(e)}")


# ============================================================
# 风险预警记录
# ============================================================

@router.get("/risk-alerts", response_model=Response[dict], summary="获取风险预警记录")
async def list_monitor_risk_alerts(
    monitor_id: Optional[str] = Query(None, description="监控实例 ID；不传则跨实例查询"),
    severity: Optional[str] = Query(None, description="级别过滤: red/yellow/green/info"),
    signal_type: Optional[str] = Query(None, description="类型过滤: vol_compare/corr_reversal/stale_skip"),
    monitor_kind: Optional[str] = Query(None, description="来源过滤: strategy/portfolio"),
    start_date: Optional[str] = Query(None, description="信号日起 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="信号日止 YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=500, description="返回条数"),
    offset: int = Query(0, ge=0, description="跳过条数"),
    batch_id: Optional[str] = Query(None, description="运行批次号；不传表示跨批次（历史台账）"),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """风险预警记录（策略与组合共用一份数据，monitor_kind 区分来源）。

    预警是历史台账，默认跨批次返回全部记录；传 ``batch_id`` 可只看某次跑批产出的预警。
    排序：red → yellow → green → info，同级按信号日倒序。
    返回 items / total / counts / limit / offset，供前端分级展示与分页。
    """
    from app.services.monitor_risk_alert_service import (
        SIGNAL_TYPE_VALUES,
        SEVERITY_VALUES,
    )

    if severity and severity not in SEVERITY_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的级别: {severity}，有效值为: {'/'.join(SEVERITY_VALUES)}",
        )
    if signal_type and signal_type not in SIGNAL_TYPE_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的类型: {signal_type}，有效值为: {'/'.join(SIGNAL_TYPE_VALUES)}",
        )
    if monitor_kind and monitor_kind not in ("strategy", "portfolio"):
        raise HTTPException(
            status_code=400,
            detail=f"无效的来源: {monitor_kind}，有效值为: strategy/portfolio",
        )
    if start_date:
        validate_date_format(start_date, "开始日期")
    if end_date:
        validate_date_format(end_date, "结束日期")

    try:
        data = await query.search_risk_alerts(
            monitor_id=monitor_id,
            severity=severity,
            signal_type=signal_type,
            monitor_kind=monitor_kind,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
            batch_id=batch_id,
        )
        logger.info(
            f"获取风险预警: monitor_id={monitor_id or 'all'}, severity={severity}, "
            f"signal_type={signal_type}, total={data['total']}, counts={data['counts']}"
        )
        return Response.success(data=data, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取风险预警失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取风险预警失败: {str(e)}")


# ============================================================
# 运行控制（全部异步：预建批次 → 后台任务 → 立即返回句柄）
# ============================================================

async def _submit_run_task(
    monitor_id: str, kind: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    """提交一次异步跑批，返回 ``{task_id, batch_id, status, kind, monitor_id, params}``.

    批次在提交时就建好（``status=pending``），因此前端拿到 ``batch_id`` 后
    可以直接开始轮询；真正置 ``running`` 由 ``MonitorService._begin_run_batch``
    接管已有批次时完成，两侧不会重复建批次。
    """
    from app.services.monitor_task_service import submit

    await assert_daily_monitor_eligible_gate()
    try:
        return await submit(monitor_id, kind, params)
    except ValueError as exc:
        # 同一实例已有活跃任务 / 任务类型非法 → 409，与改造前的语义一致
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/run", response_model=Response[dict], summary="触发监控运行（后台任务）")
async def run_monitor(
    monitor_id: str = Query("default", description="监控实例 ID"),
    target_date: Optional[str] = Query(None, description="目标日期 YYYY-MM-DD，默认最新"),
    manual_preset_step: bool = Query(
        False,
        description="主观配置策略时：在每档预设调仓日当日推演完成后暂停并落库，便于查看绩效后再续跑",
    ),
):
    """触发监控运行到指定日期（异步）

    从上次状态续接到目标日期（默认数据最新日期）。
    立即返回 ``{task_id, batch_id, status: "pending"}``，进度走
    ``GET /monitor/tasks/{task_id}`` 轮询；任务完成后展示端点自动切到新批次。
    """
    try:
        if target_date:
            validate_date_format(target_date, "目标日期")

        handle = await _submit_run_task(monitor_id, TASK_KIND_RUN, {
            "target_date": target_date,
            "manual_preset_step": bool(manual_preset_step),
        })
        logger.info(
            f"日常监控任务已提交: monitor_id={monitor_id}, target_date={target_date}, "
            f"task_id={handle['task_id']}, batch_id={handle['batch_id']}"
        )
        return Response.success(
            data=handle, message="运行任务已提交，请通过任务进度接口查询"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"监控运行提交失败: {e}")
        raise HTTPException(status_code=500, detail=f"监控运行提交失败: {str(e)}")


@router.post("/init", response_model=Response[dict], summary="初始化监控（后台任务）")
async def init_monitor(
    monitor_id: str = Query("default", description="监控实例 ID"),
    start_date: Optional[str] = Query(None, description="启动日期 YYYY-MM-DD，默认为配置中的基日"),
    manual_preset_step: bool = Query(
        False,
        description="主观配置策略时：在每档预设调仓日当日完成后暂停，与回测步进一致，便于查看区间绩效",
    ),
    async_mode: bool = Query(
        True,
        description="true=提交后台任务并立即返回 task_id；false=同步执行（脚本/调试兼容）",
    ),
):
    """初始化监控（从指定日期开始）

    默认异步：立即返回 ``{task_id, batch_id, status: "pending"}``，任务在服务进程内
    执行，进度写入 monitor_tasks，可通过 GET /monitor/tasks/{task_id} 或
    GET /monitor/tasks/active 轮询。

    ``async_mode=false`` 仅供脚本/调试同步调用，此时批次由 MonitorService 自建。
    """
    try:
        if start_date:
            validate_date_format(start_date, "启动日期")

        if async_mode:
            handle = await _submit_run_task(monitor_id, TASK_KIND_INIT, {
                "start_date": start_date,
                "manual_preset_step": bool(manual_preset_step),
            })
            logger.info(
                f"初始化任务已提交: task_id={handle['task_id']}, monitor_id={monitor_id}, "
                f"start_date={start_date}, batch_id={handle['batch_id']}"
            )
            return Response.success(
                data=handle, message="初始化任务已提交，请通过任务进度接口查询"
            )

        await assert_daily_monitor_eligible_gate()
        logger.warning(
            f"开始初始化监控（同步模式）: monitor_id={monitor_id}, start_date={start_date}"
        )
        service = get_monitor_service()
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
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"初始化监控失败: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"初始化监控失败: {str(e)}")


@router.get("/tasks/active", response_model=Response[dict], summary="查询监控实例的活跃任务")
async def get_active_monitor_task(
    monitor_id: str = Query("default", description="监控实例 ID"),
):
    """返回该实例当前进行中的任务；无任务时 data 为 null（页面刷新后恢复进度用）."""
    from app.services.monitor_task_service import get_active_task

    task = await get_active_task(monitor_id)
    return Response.success(
        data=task, message="获取成功" if task else "无进行中的任务"
    )


@router.get("/tasks/{task_id}", response_model=Response[dict], summary="查询监控任务进度")
async def get_monitor_task(task_id: str):
    """查询后台任务状态与进度（前端轮询接口）."""
    from app.services.monitor_task_service import get_task

    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return Response.success(data=task, message="获取成功")


@router.post("/run-range", response_model=Response[dict], summary="按日期范围运行（后台任务）")
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
    
    从指定开始日期到结束日期运行监控流程，适用于特定日期范围的补算或验证。
    立即返回 ``{task_id, batch_id, status: "pending"}``，进度走
    ``GET /monitor/tasks/{task_id}`` 轮询；任务完成后展示端点自动切到新批次。
    """
    try:
        validate_date_format(from_date, "开始日期")
        validate_date_format(to_date, "结束日期")
        
        if from_date > to_date:
            raise HTTPException(
                status_code=400,
                detail=f"开始日期不能晚于结束日期: {from_date} > {to_date}"
            )
        
        handle = await _submit_run_task(monitor_id, TASK_KIND_RANGE, {
            "from_date": from_date,
            "to_date": to_date,
            "manual_preset_step": bool(manual_preset_step),
        })
        logger.info(
            f"范围运行任务已提交: monitor_id={monitor_id}, {from_date} ~ {to_date}, "
            f"task_id={handle['task_id']}, batch_id={handle['batch_id']}"
        )
        return Response.success(
            data=handle, message="补算任务已提交，请通过任务进度接口查询"
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"范围运行提交失败: {e}")
        raise HTTPException(status_code=500, detail=f"范围运行提交失败: {str(e)}")


# 运行批次端点（GET /batches、GET /batches/compare、GET /batches/{batch_id}、
# GET /batches/{batch_id}/nav-history、DELETE /batches/{batch_id}）已拆至
# app/api/monitor_batches.py，由本文件末尾的 include_router 挂回同一棵路由树。


# ============================================================
# 日报
# ============================================================

@router.get("/reports/{date}", response_model=Response[dict], summary="获取指定日期日报")
async def get_monitor_report(
    date: str,
    monitor_id: str = Query("default", description="监控实例 ID"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """
    获取指定日期的日报数据
    
    返回当日的净值、收益率、持仓、信号状态等快照数据。
    """
    try:
        validate_date_format(date, "日期")
        
        report = await query.get_daily_report(monitor_id, date, batch_id)
        if not report:
            raise missing(f"日报不存在: {monitor_id}/{date}")
        logger.info(
            f"获取日报: monitor_id={monitor_id}, date={date}, "
            f"batch_id={report.get('batch_id')}"
        )
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
    limit: int = Query(30, ge=1, le=100, description="返回条数限制"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """
    获取日报列表
    
    支持分页，按日期倒序返回。
    """
    try:
        reports = await query.get_report_list(monitor_id, skip, limit, batch_id)
        if reports is None:
            raise missing(f"监控实例尚未产出日报: {monitor_id}，请先运行初始化")
        logger.info(
            f"获取日报列表: monitor_id={monitor_id}, "
            f"batch_id={batch_id or 'latest'}, count={len(reports)}"
        )
        return Response.success(data=reports, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日报列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日报列表失败: {str(e)}")


# ============================================================
# 主观调仓
# ============================================================

@router.get("/subjective", response_model=Response[list], summary="列出主观调仓指令")
async def list_subjective_overrides(
    monitor_id: str = Query("default", description="监控实例 ID"),
    status: Optional[str] = Query(None, description="状态筛选: pending/executed/cancelled"),
    batch_id: Optional[str] = Query(None, description=BATCH_ID_DESC),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """
    列出主观调仓指令
    
    可按状态筛选：
    - pending: 待执行
    - executed: 已执行
    - cancelled: 已取消

    展示口径：不传 ``batch_id`` 时返回「当前批次 + 跨批次已执行」——
    补录后重算会换批次，已执行的历史调整挂在旧批次，必须跨批次带上；
    显式传 ``batch_id`` 则严格按该批次展示（历史回溯）。
    """
    try:
        # 验证状态值
        if status and status not in ['pending', 'executed', 'cancelled']:
            raise HTTPException(
                status_code=400,
                detail=f"无效的状态值: {status}，有效值为: pending/executed/cancelled"
            )
        
        overrides = await query.list_subjective_overrides(monitor_id, status, batch_id)
        if overrides is None:
            raise missing(f"监控状态不存在: {monitor_id}，请先运行初始化")
        logger.info(
            f"获取主观调仓列表: monitor_id={monitor_id}, status={status}, "
            f"batch_id={batch_id or 'latest'}, count={len(overrides)}"
        )
        return Response.success(data=overrides, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取主观调仓列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取主观调仓列表失败: {str(e)}")


@router.post("/subjective", response_model=Response[dict], summary="新增主观调仓指令")
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
    - linked_operation_id: 挂接的待执行指令 ID（可选，调仓日比例优化模式）
    - record_executed: 补录模式（可选）。提交后按执行日重算净值
    
    返回 ``{override_id, task}``；``task`` 仅在补录模式返回，供前端轮询重算进度。
    """
    service = get_monitor_service()
    override_id: Optional[str] = None
    try:
        # 验证日期格式
        validate_date_format(data.execute_date, "执行日期")
        
        # 验证权重
        validate_weights(data.weights)
        
        override_id = await service.add_subjective_override(
            monitor_id=data.monitor_id,
            weights=data.weights,
            execute_date=data.execute_date,
            description=data.description,
            linked_operation_id=data.linked_operation_id,
            record_executed=data.record_executed,
        )
        
        payload: Dict[str, Any] = {"override_id": override_id}
        if data.record_executed:
            # 补录必须立即重算：否则净值不包含这笔调仓，与「补录」的语义相背。
            # 提交失败（同实例已有任务 → 409）时回滚刚写入的指令，不留半状态。
            payload["task"] = await _submit_run_task(
                data.monitor_id, TASK_KIND_RUN,
                {"monitor_id": data.monitor_id, "replay": True},
            )
        
        logger.info(
            f"创建主观调仓指令: override_id={override_id}, "
            f"execute_date={data.execute_date}, record_executed={data.record_executed}"
        )
        message = "已补录，正在重算净值" if data.record_executed else "主观调仓指令创建成功"
        return Response.success(data=payload, message=message)
    except HTTPException:
        if override_id:
            await service.rollback_subjective_override(override_id)
        raise
    except ValueError as e:
        if override_id:
            await service.rollback_subjective_override(override_id)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        if override_id:
            await service.rollback_subjective_override(override_id)
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
# 子路由挂载（拆文件后对外路径与拆分前完全一致）
# ============================================================
# GET/DELETE /batches*                       → app/api/monitor_batches.py
# /strategies* /researcher-strategies /addable-strategies
#                                              → app/api/monitor_strategies.py
# 共享依赖（服务注入 / 校验 / 统一 404）  → app/api/monitor_deps.py
from app.api.monitor_batches import router as batches_router  # noqa: E402
from app.api.monitor_strategies import router as strategies_router  # noqa: E402

router.include_router(batches_router)
router.include_router(strategies_router)
