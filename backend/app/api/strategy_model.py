"""策略模型相关路由

策略模型作为配置管理工具，存储和管理策略配置。

注意：
- 策略模型不直接执行回测
- 要执行回测，请使用 POST /api/v1/backtests/run 接口
- 可以通过 GET /{model_id}/backtest-request 接口获取回测请求参数
"""
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from bson import ObjectId

from app.schemas.strategy_model import (
    StrategyModelCreate,
    StrategyModelUpdate,
    StrategyModelOut,
    WeightChangesOut,
    BacktestRecordOut,
    LivePublishRequest,
    LiveConfigUpdate,
    ManualRebalanceDecisionRequest,
    LiveChangeLogOut,
)
from app.schemas.param_version import ParamVersionOut
from app.schemas.response import Response
from app.services.strategy_model_service import StrategyModelService
from app.services.strategy_model_service import resolve_full_params
from app.services.live_publish_service import LivePublishService
from app.services.backtest_service import BacktestService
from app.services.param_version_service import ParamVersionService
from app.services.strategy_model_monitoring import (
    get_model_monitoring_core,
    get_weight_changes_core,
)
# 监控回测与权重变化编排已下沉 app/services/strategy_model_monitoring.py（P9 治理）
from app.models.strategy_model import (
    StrategyModel,
    ModelStatus,
)
from app.services.asset_service import AssetService
from app.services.market_service import MarketService


router = APIRouter()


def validate_object_id(id_str: str) -> str:
    """验证ObjectId格式"""
    if not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=400,
            detail=f"无效的ID格式: {id_str}, 必须是24位十六进制字符串"
        )
    return id_str


def validate_rebalance_frequency(frequency: str) -> str:
    """验证调仓频率格式"""
    import re
    
    # 检查是否为自定义格式（数字+单位）
    custom_pattern = r'^(\d+)([天周月季年])$'
    if re.match(custom_pattern, frequency):
        num = int(re.match(custom_pattern, frequency).group(1))
        if num <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"调仓频率中的数字必须大于0: {frequency}"
            )
        return frequency
    
    # 检查是否为标准频率
    valid_standard_freqs = ["日", "周", "月", "季", "年", "daily", "weekly", "monthly", "quarterly", "yearly"]
    if frequency in valid_standard_freqs:
        return frequency
    
    raise HTTPException(
        status_code=400,
        detail=f"无效的调仓频率: {frequency}，支持的格式包括: 日/周/月/季/年 或 自定义格式如 '1天', '2周', '3月' 等"
    )


def get_model_service() -> StrategyModelService:
    return StrategyModelService()


def get_live_publish_service() -> LivePublishService:
    return LivePublishService()


def get_backtest_service() -> BacktestService:
    return BacktestService()


def get_param_version_service() -> ParamVersionService:
    return ParamVersionService()


def get_asset_service() -> AssetService:
    return AssetService()


def get_market_service() -> MarketService:
    return MarketService()


def _live_effective_fields(
    model: StrategyModel,
    asset_names: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[str], Optional[List[str]], Optional[List[str]]]:
    """实盘展示字段计算已下沉 LivePublishService，API 层仅保留转发。"""
    return LivePublishService.live_effective_fields(model, asset_names)


@router.post("/", response_model=Response[str], summary="创建策略模型")
async def create_model(
    model_in: StrategyModelCreate,
    service: StrategyModelService = Depends(get_model_service),
    asset_service: AssetService = Depends(get_asset_service)
):
    # 验证调仓频率格式
    validate_rebalance_frequency(model_in.rebalance_frequency)
    
    # 移除基准代码字段（因为它不再存在于模型中）
    model_data = model_in.dict()
    model_data.pop('benchmark_code', None)  # 移除基准代码字段
    
    model = StrategyModel(**model_data)
    model_id = await service.create_model(model)
    
    # 获取刚创建的模型以返回完整信息
    created_model = await service.get_model(model_id)
    
    # 获取资产名称映射
    asset_names = {}
    for asset_code in created_model.asset_codes:
        asset_info = await asset_service.get_asset_by_code(asset_code)
        if asset_info:
            asset_names[asset_code] = asset_info.name
    
    # 获取模板名称和参数标签
    from app.services.model_template_service import ModelTemplateService
    template_service = ModelTemplateService()
    template = await template_service.get_template_by_code(created_model.template_code)
    template_name = template.name if template else created_model.template_code
    parameter_labels = {p.name: p.label for p in template.parameters} if template else {}
    
    # 构造带名称信息的模型输出
    model_dict = created_model.dict()
    model_dict.pop('asset_names', None)
    model_dict.pop('template_name', None)
    model_dict.pop('parameter_labels', None)
    
    model_out = StrategyModelOut(
        **model_dict,
        asset_names=asset_names,
        template_name=template_name,
        parameter_labels=parameter_labels
    )
    
    return Response.success(data=model_id, message="策略模型创建成功")


@router.get("/", response_model=Response[List[StrategyModelOut]], summary="策略模型列表")
async def list_models(
    status: str | None = Query(None, description="模型状态(草稿/已发布/已归档)，空字符串表示不筛选"),
    template_code: str | None = Query(None, description="模板代码"),
    rebalance_frequency: str | None = Query(None, description="调仓频率(日/周/月/季/年 或 自定义格式如 '1天', '2周', '3月' 等)"),
    include_portfolio: bool = Query(False, description="是否包含组合模型（is_portfolio=True），默认排除"),
    service: StrategyModelService = Depends(get_model_service),
    asset_service: AssetService = Depends(get_asset_service)
):
    """查询策略模型列表，支持按状态和模板代码筛选（默认排除组合模型）"""
    # 将空字符串转换为 None（不筛选）
    status_filter = None if not status or status.strip() == "" else status
    template_filter = None if not template_code or template_code.strip() == "" else template_code
    frequency_filter = None if not rebalance_frequency or rebalance_frequency.strip() == "" else rebalance_frequency
    
    # 如果 status_filter 有值，验证是否为有效的枚举值
    if status_filter:
        try:
            status_enum = ModelStatus(status_filter)
        except ValueError:
            valid_statuses = [s.value for s in ModelStatus]
            raise HTTPException(
                status_code=400,
                detail=f"无效的状态值: {status_filter}，有效值为: {valid_statuses}"
            )
    else:
        status_enum = None
    
    # 验证调仓频率格式（如果提供了调仓频率）
    if frequency_filter:
        validate_rebalance_frequency(frequency_filter)
    
    models = await service.list_models(
        status=status_enum,
        template_code=template_filter,
        rebalance_frequency=frequency_filter,
        include_portfolio=include_portfolio,
    )
    
    # 获取所有唯一资产代码、模板代码
    all_asset_codes = set()
    all_template_codes = set()
    
    for model in models:
        all_asset_codes.update(model.asset_codes)
        all_template_codes.add(model.template_code)
    
    # 批量获取资产名称
    asset_names_map = {}
    for asset_code in all_asset_codes:
        asset_info = await asset_service.get_asset_by_code(asset_code)
        if asset_info:
            asset_names_map[asset_code] = asset_info.name
    
    # 批量获取模板名称和参数标签
    from app.services.model_template_service import ModelTemplateService
    template_service = ModelTemplateService()
    template_info_map = {}
    for template_code in all_template_codes:
        template = await template_service.get_template_by_code(template_code)
        if template:
            template_info_map[template_code] = {
                "name": template.name,
                "parameter_labels": {p.name: p.label for p in template.parameters}
            }
        else:
            template_info_map[template_code] = {
                "name": template_code,
                "parameter_labels": {}
            }
    
    # 构造带名称信息的模型输出
    data = []
    for model in models:
        model_dict = model.dict()
        model_dict.pop('asset_names', None)
        model_dict.pop('template_name', None)
        model_dict.pop('parameter_labels', None)
        
        # 获取当前模型的资产名称
        current_asset_names = {}
        for asset_code in model.asset_codes:
            if asset_code in asset_names_map:
                current_asset_names[asset_code] = asset_names_map[asset_code]
        
        template_info = template_info_map.get(model.template_code, {"name": model.template_code, "parameter_labels": {}})
        
        # 注意：model.dict()已经包含了选择器相关字段（如果StrategyModel模型中有定义）
        # 但为了确保完整性，也可以从数据库直接读取（如果需要）
        
        le_sum, le_assets, le_labels = _live_effective_fields(model, current_asset_names)
        # 结构化参数：三层解耦聚合
        rp = resolve_full_params(model)
        model_out = StrategyModelOut(
            **model_dict,
            asset_names=current_asset_names,
            template_name=template_info["name"],
            parameter_labels=template_info["parameter_labels"],
            live_effective_summary=le_sum,
            live_effective_assets=le_assets,
            live_effective_asset_labels=le_labels,
            resolved_params=rp,
        )
        data.append(model_out)
    
    return Response.success(data=data)


@router.get("/{model_id}", response_model=Response[StrategyModelOut], summary="获取单个模型")
async def get_model(
    model_id: str, 
    service: StrategyModelService = Depends(get_model_service),
    asset_service: AssetService = Depends(get_asset_service)
):
    validate_object_id(model_id)
    model = await service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")
    
    # 获取资产名称映射
    asset_names = {}
    for asset_code in model.asset_codes:
        asset_info = await asset_service.get_asset_by_code(asset_code)
        if asset_info:
            asset_names[asset_code] = asset_info.name
    
    # 获取模板名称和参数标签
    from app.services.model_template_service import ModelTemplateService
    template_service = ModelTemplateService()
    template = await template_service.get_template_by_code(model.template_code)
    template_name = template.name if template else model.template_code
    parameter_labels = {p.name: p.label for p in template.parameters} if template else {}
    
    # 从数据库获取完整模型数据（包含选择器相关字段）
    from bson import ObjectId
    model_data = await service.collection.find_one({"_id": ObjectId(model_id)})
    
    # 构造带名称信息的模型输出
    model_dict = model.dict()
    model_dict.pop('asset_names', None)
    model_dict.pop('template_name', None)
    model_dict.pop('parameter_labels', None)
    
    # 添加选择器相关字段（如果存在）
    if model_data:
        if "enable_momentum_selection" in model_data:
            model_dict["enable_momentum_selection"] = model_data["enable_momentum_selection"]
        if "selector_type" in model_data:
            model_dict["selector_type"] = model_data["selector_type"]
        if "asset_selection_count" in model_data:
            model_dict["asset_selection_count"] = model_data["asset_selection_count"]
        if "min_history_days" in model_data:
            model_dict["min_history_days"] = model_data["min_history_days"]
        if "momentum_windows" in model_data:
            model_dict["momentum_windows"] = model_data["momentum_windows"]
        for _wk in (
            "mom_windows",
            "posi_windows",
            "smom_windows",
            "macd_windows",
            "macd_long_window",
            "reversal_windows",
            "sharp_windows",
        ):
            if _wk in model_data:
                model_dict[_wk] = model_data[_wk]
        if "tie_break_window" in model_data:
            model_dict["tie_break_window"] = model_data["tie_break_window"]
    
    le_sum, le_assets, le_labels = _live_effective_fields(model, asset_names)
    # 结构化参数：三层解耦聚合，前端可直接渲染
    rp = resolve_full_params(model)
    model_out = StrategyModelOut(
        **model_dict,
        asset_names=asset_names,
        template_name=template_name,
        parameter_labels=parameter_labels,
        live_effective_summary=le_sum,
        live_effective_assets=le_assets,
        live_effective_asset_labels=le_labels,
        resolved_params=rp,
    )
    
    return Response.success(data=model_out)


@router.put("/{model_id}", response_model=Response[StrategyModelOut], summary="更新策略模型")
async def update_model(
    model_id: str,
    model_update: StrategyModelUpdate,
    source: str = Query("strategy", description="操作来源：strategy/live_monitoring"),
    operator: str | None = Query(None, description="操作人"),
    service: StrategyModelService = Depends(get_model_service),
    asset_service: AssetService = Depends(get_asset_service)
):
    """
    更新策略模型信息
    
    注意：
    - 仅更新提供的字段，未提供的字段保持不变
    - 不能修改 template_code（模板代码）
    - 已发布的模型也可以更新，但建议谨慎操作
    """
    validate_object_id(model_id)
    
    # 检查模型是否存在
    existing_model = await service.get_model(model_id)
    if not existing_model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")
    
    # 验证调仓频率格式（如果提供了调仓频率）
    update_data = model_update.dict(exclude_unset=True)
    update_data["_change_source"] = source
    update_data["_change_operator"] = operator
    if 'rebalance_frequency' in update_data:
        validate_rebalance_frequency(update_data['rebalance_frequency'])
    
    if not update_data:
        raise HTTPException(status_code=400, detail="没有提供任何要更新的字段")
    
    # 执行更新
    success = await service.update_model(model_id, update_data)
    if not success:
        raise HTTPException(status_code=500, detail="模型更新失败")
    
    # 返回更新后的模型
    updated_model = await service.get_model(model_id)
    
    # 获取资产名称映射
    asset_names = {}
    for asset_code in updated_model.asset_codes:
        asset_info = await asset_service.get_asset_by_code(asset_code)
        if asset_info:
            asset_names[asset_code] = asset_info.name
    
    # 获取模板名称和参数标签
    from app.services.model_template_service import ModelTemplateService
    template_service = ModelTemplateService()
    template = await template_service.get_template_by_code(updated_model.template_code)
    template_name = template.name if template else updated_model.template_code
    parameter_labels = {p.name: p.label for p in template.parameters} if template else {}
    
    # 构造带名称信息的模型输出
    model_dict = updated_model.dict()
    model_dict.pop('asset_names', None)
    model_dict.pop('template_name', None)
    model_dict.pop('parameter_labels', None)
    
    le_sum, le_assets, le_labels = _live_effective_fields(updated_model, asset_names)
    # 结构化参数：三层解耦聚合
    rp = resolve_full_params(updated_model)
    model_out = StrategyModelOut(
        **model_dict,
        asset_names=asset_names,
        template_name=template_name,
        parameter_labels=parameter_labels,
        live_effective_summary=le_sum,
        live_effective_assets=le_assets,
        live_effective_asset_labels=le_labels,
        resolved_params=rp,
    )
    
    return Response.success(data=model_out, message="策略模型更新成功")


@router.post("/{model_id}/publish", response_model=Response[bool], summary="发布模型")
async def publish_model(model_id: str, live_service: LivePublishService = Depends(get_live_publish_service)):
    validate_object_id(model_id)
    success = await live_service.publish_model(model_id)
    return Response.success(data=success, message="模型发布成功")


@router.post("/{model_id}/live-publish", response_model=Response[bool], summary="实盘发布策略模型（T+1 生效）")
async def live_publish_model(
    model_id: str,
    body: LivePublishRequest = Body(default=LivePublishRequest()),
    service: StrategyModelService = Depends(get_model_service),
    live_service: LivePublishService = Depends(get_live_publish_service),
):
    validate_object_id(model_id)
    # 自动检测组合模型，走组合发布逻辑
    model = await service.get_model(model_id)
    if model and model.is_portfolio:
        success = await live_service.live_publish_portfolio_model(
            model_id=model_id,
            source=body.source,
            operator=body.operator,
        )
        return Response.success(data=success, message="组合模型发布成功")
    success = await live_service.live_publish_model(
        model_id=model_id,
        source=body.source,
        operator=body.operator,
        rebalance_mode=body.rebalance_mode,
        volatility_threshold=body.volatility_threshold,
    )
    return Response.success(data=success, message="实盘发布成功（次交易日生效）")


@router.post("/{model_id}/live-unpublish", response_model=Response[bool], summary="取消实盘发布")
async def live_unpublish_model(
    model_id: str,
    source: str = Query("strategy", description="操作来源"),
    operator: str | None = Query(None, description="操作人"),
    live_service: LivePublishService = Depends(get_live_publish_service),
):
    validate_object_id(model_id)
    success = await live_service.live_unpublish_model(model_id=model_id, source=source, operator=operator)
    return Response.success(data=success, message="已取消实盘发布")


@router.get("/{model_id}/live-config", response_model=Response[dict], summary="获取实盘配置（含策略参数建议值）")
async def get_live_config(
    model_id: str,
    service: StrategyModelService = Depends(get_model_service),
    live_service: LivePublishService = Depends(get_live_publish_service),
):
    """返回当前实盘配置及从策略 parameters 提取的建议波动率阈值"""
    validate_object_id(model_id)
    model = await service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")
    suggested = live_service._extract_volatility_from_params(model)
    data = {
        "live_volatility_threshold": model.live_volatility_threshold,
        "live_rebalance_mode": str(model.live_rebalance_mode) if model.live_rebalance_mode else "auto",
        "suggested_volatility_threshold": suggested,
    }
    return Response.success(data=data)


@router.patch("/{model_id}/live-config", response_model=Response[bool], summary="更新实盘配置")
async def update_live_config(
    model_id: str,
    body: LiveConfigUpdate,
    live_service: LivePublishService = Depends(get_live_publish_service),
):
    validate_object_id(model_id)
    success = await live_service.update_live_config(
        model_id=model_id,
        source=body.source,
        operator=body.operator,
        rebalance_mode=body.rebalance_mode,
        volatility_threshold=body.volatility_threshold,
    )
    return Response.success(data=success, message="实盘配置更新成功")


@router.get("/live/published", response_model=Response[List[StrategyModelOut]], summary="获取实盘发布策略列表")
async def list_live_published_models(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    live_service: LivePublishService = Depends(get_live_publish_service),
    asset_service: AssetService = Depends(get_asset_service),
):
    models = await live_service.list_live_models(skip=skip, limit=limit)
    data = []
    for model in models:
        asset_names = {}
        for asset_code in model.asset_codes:
            asset_info = await asset_service.get_asset_by_code(asset_code)
            if asset_info:
                asset_names[asset_code] = asset_info.name
        model_dict = model.dict()
        model_dict.pop("asset_names", None)
        model_dict.pop("template_name", None)
        model_dict.pop("parameter_labels", None)
        le_sum, le_assets, le_labels = _live_effective_fields(model, asset_names)
        model_out = StrategyModelOut(
            **model_dict,
            asset_names=asset_names,
            template_name=model.template_code,
            parameter_labels={},
            live_effective_summary=le_sum,
            live_effective_assets=le_assets,
            live_effective_asset_labels=le_labels,
        )
        data.append(model_out)
    return Response.success(data=data)


@router.get(
    "/live/eligible-for-monitor",
    response_model=Response[dict],
    summary="获取日常监控准入的实盘策略（混合动量或主观配置）",
)
async def list_live_eligible_monitor_models(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    live_service: LivePublishService = Depends(get_live_publish_service),
    asset_service: AssetService = Depends(get_asset_service),
):
    models = await live_service.list_live_eligible_monitor_models(skip=skip, limit=limit)
    strategies: List[Dict[str, Any]] = []
    for model in models:
        asset_names: Dict[str, str] = {}
        for asset_code in model.asset_codes:
            asset_info = await asset_service.get_asset_by_code(asset_code)
            if asset_info:
                asset_names[asset_code] = asset_info.name
        le_sum, le_assets, le_labels = _live_effective_fields(model, asset_names)
        le_params = LivePublishService.live_effective_params(model)
        strategies.append(
            {
                "id": model.id,
                "name": model.name,
                "template_code": model.template_code,
                "selector_type": model.selector_type,
                "live_version": model.live_version,
                "live_effective_date": model.live_effective_date,
                "live_effective_summary": le_sum,
                "live_effective_assets": le_assets,
                "asset_names": asset_names,
                "live_effective_asset_labels": le_labels,
                "live_effective_params": le_params,
                "is_config_baseline": False,
            }
        )

    strategies.append(await live_service.build_config_baseline_strategy(asset_service))

    display_name = "、".join([m["name"] for m in strategies]) if strategies else ""
    return Response.success(
        data={
            "has_eligible_strategy": len(strategies) > 0,
            "strategies": strategies,
            "display_name": display_name,
        }
    )


@router.get("/{model_id}/live-change-logs", response_model=Response[List[LiveChangeLogOut]], summary="获取实盘变更日志")
async def list_live_change_logs(
    model_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    live_service: LivePublishService = Depends(get_live_publish_service),
):
    validate_object_id(model_id)
    rows = await live_service.list_live_change_logs(model_id=model_id, skip=skip, limit=limit)
    data = [
        LiveChangeLogOut(
            id=row["_id"],
            model_id=row["model_id"],
            action=row.get("action", ""),
            source=row.get("source", ""),
            operator=row.get("operator"),
            live_version=row.get("live_version"),
            before=row.get("before", {}),
            after=row.get("after", {}),
            change_summary=row.get("change_summary"),
            created_at=row.get("created_at"),
            monitor_scoped_changes=row.get("monitor_scoped_changes"),
        )
        for row in rows
    ]
    return Response.success(data=data)


@router.post("/{model_id}/manual-rebalance", response_model=Response[bool], summary="手动确认本次调仓")
async def confirm_manual_rebalance(
    model_id: str,
    body: ManualRebalanceDecisionRequest,
    live_service: LivePublishService = Depends(get_live_publish_service),
):
    validate_object_id(model_id)
    if body.decision not in {"confirm", "skip"}:
        raise HTTPException(status_code=400, detail="decision 仅支持 confirm 或 skip")
    ok = await live_service.confirm_manual_rebalance(
        model_id=model_id,
        decision=body.decision,
        operator=body.operator,
        comment=body.comment,
    )
    return Response.success(data=ok, message="手动调仓操作已记录")


@router.get("/{model_id}/live-monitoring", response_model=Response[BacktestRecordOut], summary="实盘监控（实盘版本）")
async def get_model_live_monitoring(
    model_id: str,
    service: StrategyModelService = Depends(get_model_service),
    market_service: MarketService = Depends(get_market_service),
    asset_service: AssetService = Depends(get_asset_service),
):
    return await get_model_monitoring(
        model_id=model_id,
        service=service,
        market_service=market_service,
        asset_service=asset_service,
        use_live_snapshot=True,
    )


@router.get("/{model_id}/backtest-request", response_model=Response[dict], summary="生成回测请求参数")
async def get_backtest_request(
    model_id: str,
    start_date: str = Query(..., description="回测开始日期（格式：YYYYMMDD）"),
    end_date: str = Query(..., description="回测结束日期（格式：YYYYMMDD）"),
    initial_cash: float = Query(10_000_000.0, description="初始资金"),
    service: StrategyModelService = Depends(get_model_service),
    backtest_service: BacktestService = Depends(get_backtest_service)
):
    """
    从策略模型生成回测请求参数
    
    这个接口将策略模型的配置转换为回测 API 需要的请求参数。
    
    使用流程：
    1. 调用本接口获取回测请求参数
    2. 将返回的数据作为请求体调用 POST /api/v1/backtests/run
    
    示例：
    ```javascript
    // 1. 获取回测请求参数
    const response = await fetch(
        `/api/v1/strategy-models/${modelId}/backtest-request?start_date=20230101&end_date=20231231`
    );
    const { data: requestData } = await response.json();
    
    // 2. 执行回测
    const backtestResponse = await fetch('/api/v1/backtests/run', {
        method: 'POST',
        body: JSON.stringify(requestData)
    });
    ```
    """
    validate_object_id(model_id)
    
    model = await service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")
    
    # 生成回测请求参数
    request_data = backtest_service.to_backtest_request(
        model=model,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash
    )
    
    return Response.success(data=request_data, message="回测请求参数生成成功")


@router.delete("/{model_id}", response_model=Response[bool], summary="删除策略模型")
async def delete_model(model_id: str, service: StrategyModelService = Depends(get_model_service)):
    """
    删除策略模型及其所有关联的回测记录
    
    注意：此操作不可逆，请谨慎使用
    """
    validate_object_id(model_id)
    success = await service.delete_model(model_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")
    return Response.success(data=True, message="策略模型删除成功")


@router.get("/{model_id}/backtests", response_model=Response[List[BacktestRecordOut]], summary="获取模型回测记录列表")
async def get_model_backtests(
    model_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    service: StrategyModelService = Depends(get_model_service),
    backtest_service: BacktestService = Depends(get_backtest_service),
    asset_service: AssetService = Depends(get_asset_service)
):
    """
    获取指定策略模型的所有历史回测记录列表
    
    支持分页：
    - skip: 跳过条数
    - limit: 返回条数（默认10，最大100）
    """
    validate_object_id(model_id)
    
    # 检查模型是否存在
    model = await service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")
    
    # 查询回测记录（按 created_at 倒序，第一条为最新）
    records = await backtest_service.list_backtest_records(model_id=model_id, skip=skip, limit=limit)
    if records:
        print(f"[BacktestRecord] GET 回测记录列表 model_id={model_id} count={len(records)} first_id={getattr(records[0], 'id', getattr(records[0], '_id', None))}")
    
    # 获取资产名称映射（用于填充可能缺失名称的旧记录）
    all_asset_codes = set()
    for record in records:
        if not record.result.asset_names:
            for pos_rec in record.result.positions:
                for pos in pos_rec.positions:
                    all_asset_codes.add(pos.asset_code)
    
    asset_names_map = {}
    if all_asset_codes:
        for code in all_asset_codes:
            info = await asset_service.get_asset_by_code(code)
            if info:
                asset_names_map[code] = info.name
                
    # 填充缺失的名称
    for record in records:
        if not record.result.asset_names:
            record.result.asset_names = {
                code: asset_names_map[code] 
                for code in asset_names_map 
                if any(p.asset_code == code for pr in record.result.positions for p in pr.positions)
            }
        
        # 同时也确保 positions 中的 asset_name 有值
        for pos_rec in record.result.positions:
            for pos in pos_rec.positions:
                if not pos.asset_name:
                    pos.asset_name = record.result.asset_names.get(pos.asset_code) or asset_names_map.get(pos.asset_code)
    
    return Response.success(data=records, message="查询回测记录成功")


@router.patch("/{model_id}/backtests/{record_id}", response_model=Response[bool], summary="更新回测记录备注")
async def update_backtest_record_remark(
    model_id: str,
    record_id: str,
    body: dict = Body(..., embed=False),
    backtest_service: BacktestService = Depends(get_backtest_service),
):
    """更新指定回测记录的备注信息"""
    validate_object_id(model_id)
    validate_object_id(record_id)
    remark = body.get("remark")
    print(f"[BacktestRecord] PATCH 更新备注 model_id={model_id} record_id={record_id} remark_len={len(remark) if remark else 0}")
    updated = await backtest_service.update_backtest_record_remark(record_id=record_id, model_id=model_id, remark=remark)
    if not updated:
        print(f"[BacktestRecord] PATCH 更新备注失败 404 record_id={record_id}")
        raise HTTPException(status_code=404, detail="回测记录不存在或不属于该模型")
    print(f"[BacktestRecord] PATCH 更新备注成功 record_id={record_id}")
    return Response.success(data=True, message="备注已更新")


@router.get("/{model_id}/monitoring", response_model=Response[BacktestRecordOut], summary="策略监控（从建仓日至今）")
async def get_model_monitoring(
    model_id: str,
    service: StrategyModelService = Depends(get_model_service),
    market_service: MarketService = Depends(get_market_service),
    asset_service: AssetService = Depends(get_asset_service),
    use_live_snapshot: bool = False,
):
    """获取已发布策略从建仓日到当前的表现监控信息.

    指标包括：组合净值曲线、累计收益率、年化波动率、最大回撤、夏普比率、资产权重、持仓调整记录等。
    内部复用回测引擎和绩效分析逻辑，仅不落库。
    use_live_snapshot: 实盘监控时使用 live_snapshot 配置，不触发实盘发布。
    """
    validate_object_id(model_id)
    return await get_model_monitoring_core(model_id, service, market_service, asset_service, use_live_snapshot)


@router.get("/{model_id}/weight-changes", response_model=Response[List[WeightChangesOut]], summary="获取权重变化")
async def get_weight_changes(
    model_id: str,
    backtest_service: BacktestService = Depends(get_backtest_service),
    asset_service: AssetService = Depends(get_asset_service)
):
    """
    获取模型的权重变化曲线数据
    
    返回数据说明：
    - date: 日期 (YYYY-MM-DD格式)
    - weights: 各资产权重列表
      - asset_code: 资产代码 (如 AAPL, GOOGL)
      - weight: 权重值 (0-1之间的浮点数，表示该资产在组合中的占比)
    
    示例返回：
    [
      {
        "date": "2023-01-01",
        "weights": [
          {
            "asset_code": "AAPL",
            "weight": 0.3
          },
          {
            "asset_code": "GOOGL",
            "weight": 0.4
          },
          {
            "asset_code": "MSFT",
            "weight": 0.3
          }
        ]
      },
      {
        "date": "2023-02-01",
        "weights": [
          {
            "asset_code": "AAPL",
            "weight": 0.25
          },
          {
            "asset_code": "GOOGL",
            "weight": 0.45
          },
          {
            "asset_code": "MSFT",
            "weight": 0.3
          }
        ]
      }
    ]
    """
    validate_object_id(model_id)
    return await get_weight_changes_core(model_id, backtest_service, asset_service)


@router.get(
    "/{model_id}/param-versions",
    response_model=Response[List[ParamVersionOut]],
    summary="获取策略参数版本列表",
)
async def list_param_versions(
    model_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    service: StrategyModelService = Depends(get_model_service),
    pv_service: ParamVersionService = Depends(get_param_version_service),
):
    """获取策略的参数版本快照列表（按版本号倒序，最新版本在前）"""
    validate_object_id(model_id)
    model = await service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")
    rows = await pv_service.list_param_versions(model_id, skip=skip, limit=limit)
    data = [ParamVersionOut(**row) for row in rows]
    return Response.success(data=data)


@router.get(
    "/{model_id}/param-versions/{version_id}",
    response_model=Response[ParamVersionOut],
    summary="获取单个参数版本详情",
)
async def get_param_version(
    model_id: str,
    version_id: str,
    pv_service: ParamVersionService = Depends(get_param_version_service),
):
    """获取某个参数版本的完整快照"""
    validate_object_id(model_id)
    validate_object_id(version_id)
    doc = await pv_service.get_param_version(version_id)
    if not doc or doc.get("model_id") != model_id:
        raise HTTPException(status_code=404, detail="参数版本不存在或不属于该模型")
    return Response.success(data=ParamVersionOut(**doc))