"""策略模型相关路由

策略模型作为配置管理工具，存储和管理策略配置。

注意：
- 策略模型不直接执行回测
- 要执行回测，请使用 POST /api/v1/backtests/run 接口
- 可以通过 GET /{model_id}/backtest-request 接口获取回测请求参数
"""
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from app.monitor.monitor_runtime import (
    config_baseline_eligible_strategy_dict,
    live_effective_display_bundle,
    live_effective_asset_display_labels,
    live_effective_structured_params,
    normalize_strategy_asset_codes,
)

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from bson import ObjectId

from app.schemas.strategy_model import (
    StrategyModelCreate,
    StrategyModelUpdate,
    StrategyModelOut,
    WeightChangesOut,
    AssetWeight,
    BacktestRecordOut,
    LivePublishRequest,
    LiveConfigUpdate,
    ManualRebalanceDecisionRequest,
    LiveChangeLogOut,
)
from app.schemas.response import Response
from app.services.strategy_model_service import StrategyModelService
from app.models.strategy_model import (
    StrategyModel,
    ModelStatus,
    EquityPoint,
    ReturnPoint,
    WeightChangePoint,
    BacktestResult as ModelBacktestResult,
    BacktestRecord,
    AssetPosition,
    PositionRecord,
    TodayNav,
    TodayPlannedRebalance,
)
from app.services.asset_service import AssetService
from app.services.market_service import MarketService
from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.engine import BacktestEngine
from app.backtesting.risk import RiskManager, RiskConfig
from app.backtesting.execution import ExecutionEngine
from app.backtesting.strategy_api import StrategiesWrapper
from app.backtesting.analytics import PerformanceAnalyzer
from app.strategies.services.registry import create_strategy_service_from_database


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


def get_asset_service() -> AssetService:
    return AssetService()


def get_market_service() -> MarketService:
    return MarketService()


def _live_effective_fields(
    model: StrategyModel,
    asset_names: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[str], Optional[List[str]], Optional[List[str]]]:
    """实盘摘要文案 + 监控资产标识列表 + 同序展示名称列表（仅已实盘发布快照，不含未发布草稿）。"""
    codes_list = normalize_strategy_asset_codes(getattr(model, "asset_codes", None))
    summary, assets = live_effective_display_bundle(
        model.live_publish_enabled,
        model.live_snapshot or {},
        model.live_volatility_threshold,
        current_parameters=model.parameters,
        current_asset_codes=codes_list,
        asset_names=asset_names,
        published_only=True,
    )
    labels = live_effective_asset_display_labels(assets, asset_names)
    return summary, assets, labels


@router.get(
    "/defaults/risk_budget_target_vol_hybrid_momentum",
    response_model=Response[dict],
    summary="获取 risk_budget_target_vol 混合动量策略默认参数",
)
async def get_hybrid_momentum_rbtv_defaults(
    asset_codes: str | None = Query(
        None,
        description="资产代码列表，逗号分隔，用于预填 max_weight_dict；不传则 max_weight_dict 为空",
    ),
):
    """
    依据浙银理财-申万指数编制规则 B.1 关键参数精确值，返回 risk_budget_target_vol 混合动量策略的默认参数。
    新建策略时，前端可调用此接口预填表单。
    """
    from app.config.hybrid_momentum_rbtv_defaults import get_hybrid_momentum_rbtv_defaults as _get_defaults

    codes = [c.strip() for c in asset_codes.split(",") if c.strip()] if asset_codes else None
    defaults = _get_defaults(asset_codes=codes)
    return Response.success(data=defaults, message="默认参数获取成功")


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
    
    # risk_budget_target_vol + 混合动量：按 B.1 编制规则初始化默认参数（仅填充未提供的键）
    params = model_data.get("parameters") or {}
    if (
        model_data.get("template_code") == "risk_budget_target_vol"
        and (
            model_data.get("enable_momentum_selection") is True
            or params.get("enable_momentum_selection") is True
            or params.get("selector_type") in ("momentum_reversal", "hybrid")
        )
    ):
        from app.config.hybrid_momentum_rbtv_defaults import get_hybrid_momentum_rbtv_defaults
        defaults = get_hybrid_momentum_rbtv_defaults(asset_codes=model_data.get("asset_codes"))
        for k, v in defaults.items():
            if k not in params or params[k] is None:
                params[k] = v
        model_data["parameters"] = params
    
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
    service: StrategyModelService = Depends(get_model_service),
    asset_service: AssetService = Depends(get_asset_service)
):
    """查询策略模型列表，支持按状态和模板代码筛选"""
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
    
    models = await service.list_models(status=status_enum, template_code=template_filter, rebalance_frequency=frequency_filter)
    
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
        model_out = StrategyModelOut(
            **model_dict,
            asset_names=current_asset_names,
            template_name=template_info["name"],
            parameter_labels=template_info["parameter_labels"],
            live_effective_summary=le_sum,
            live_effective_assets=le_assets,
            live_effective_asset_labels=le_labels,
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
        ):
            if _wk in model_data:
                model_dict[_wk] = model_data[_wk]
        if "tie_break_window" in model_data:
            model_dict["tie_break_window"] = model_data["tie_break_window"]
    
    le_sum, le_assets, le_labels = _live_effective_fields(model, asset_names)
    model_out = StrategyModelOut(
        **model_dict,
        asset_names=asset_names,
        template_name=template_name,
        parameter_labels=parameter_labels,
        live_effective_summary=le_sum,
        live_effective_assets=le_assets,
        live_effective_asset_labels=le_labels,
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
    model_out = StrategyModelOut(
        **model_dict,
        asset_names=asset_names,
        template_name=template_name,
        parameter_labels=parameter_labels,
        live_effective_summary=le_sum,
        live_effective_assets=le_assets,
        live_effective_asset_labels=le_labels,
    )
    
    return Response.success(data=model_out, message="策略模型更新成功")


@router.post("/{model_id}/publish", response_model=Response[bool], summary="发布模型")
async def publish_model(model_id: str, service: StrategyModelService = Depends(get_model_service)):
    validate_object_id(model_id)
    success = await service.publish_model(model_id)
    return Response.success(data=success, message="模型发布成功")


@router.post("/{model_id}/live-publish", response_model=Response[bool], summary="实盘发布策略模型（T+1 生效）")
async def live_publish_model(
    model_id: str,
    body: LivePublishRequest = Body(default=LivePublishRequest()),
    service: StrategyModelService = Depends(get_model_service),
):
    validate_object_id(model_id)
    success = await service.live_publish_model(
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
    service: StrategyModelService = Depends(get_model_service),
):
    validate_object_id(model_id)
    success = await service.live_unpublish_model(model_id=model_id, source=source, operator=operator)
    return Response.success(data=success, message="已取消实盘发布")


@router.get("/{model_id}/live-config", response_model=Response[dict], summary="获取实盘配置（含策略参数建议值）")
async def get_live_config(
    model_id: str,
    service: StrategyModelService = Depends(get_model_service),
):
    """返回当前实盘配置及从策略 parameters 提取的建议波动率阈值"""
    validate_object_id(model_id)
    model = await service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")
    suggested = service._extract_volatility_from_params(model)
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
    service: StrategyModelService = Depends(get_model_service),
):
    validate_object_id(model_id)
    success = await service.update_live_config(
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
    service: StrategyModelService = Depends(get_model_service),
    asset_service: AssetService = Depends(get_asset_service),
):
    models = await service.list_live_models(skip=skip, limit=limit)
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
    service: StrategyModelService = Depends(get_model_service),
    asset_service: AssetService = Depends(get_asset_service),
):
    models = await service.list_live_eligible_monitor_models(skip=skip, limit=limit)
    strategies: List[Dict[str, Any]] = []
    for model in models:
        asset_names: Dict[str, str] = {}
        for asset_code in model.asset_codes:
            asset_info = await asset_service.get_asset_by_code(asset_code)
            if asset_info:
                asset_names[asset_code] = asset_info.name
        le_sum, le_assets, le_labels = _live_effective_fields(model, asset_names)
        codes_list = normalize_strategy_asset_codes(getattr(model, "asset_codes", None))
        le_params = live_effective_structured_params(
            model.live_publish_enabled,
            model.live_snapshot or {},
            model.live_volatility_threshold,
            current_parameters=model.parameters,
            current_asset_codes=codes_list,
            model_for_selection=model,
            published_only=True,
        )
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

    from app.monitor import config as monitor_config

    baseline_asset_names: Dict[str, str] = {}
    for nm in monitor_config.ASSET_LIST:
        code = monitor_config.ASSET_NAME_TO_CODE.get(nm)
        if not code:
            continue
        asset_info = await asset_service.get_asset_by_code(code)
        baseline_asset_names[code] = asset_info.name if asset_info else code
    strategies.append(config_baseline_eligible_strategy_dict(baseline_asset_names))

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
    service: StrategyModelService = Depends(get_model_service),
):
    validate_object_id(model_id)
    rows = await service.list_live_change_logs(model_id=model_id, skip=skip, limit=limit)
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
    service: StrategyModelService = Depends(get_model_service),
):
    validate_object_id(model_id)
    if body.decision not in {"confirm", "skip"}:
        raise HTTPException(status_code=400, detail="decision 仅支持 confirm 或 skip")
    ok = await service.confirm_manual_rebalance(
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
    service: StrategyModelService = Depends(get_model_service)
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
    request_data = service.to_backtest_request(
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
    records = await service.list_backtest_records(model_id=model_id, skip=skip, limit=limit)
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
    service: StrategyModelService = Depends(get_model_service),
):
    """更新指定回测记录的备注信息"""
    validate_object_id(model_id)
    validate_object_id(record_id)
    remark = body.get("remark")
    print(f"[BacktestRecord] PATCH 更新备注 model_id={model_id} record_id={record_id} remark_len={len(remark) if remark else 0}")
    updated = await service.update_backtest_record_remark(record_id=record_id, model_id=model_id, remark=remark)
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

    # 1. 获取并校验模型
    model = await service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")

    if model.status != ModelStatus.PUBLISHED and not model.live_publish_enabled:
        raise HTTPException(status_code=400, detail="仅支持对已发布或已实盘发布的策略进行监控")

    # 2. 确定建仓日与结束日；实盘监控时使用 live_snapshot 配置
    from datetime import datetime

    if use_live_snapshot and model.live_publish_enabled and model.live_snapshot:
        snap = model.live_snapshot
        asset_codes = snap.get("asset_codes") or model.asset_codes
        parameters = snap.get("parameters") or model.parameters
        rebalance_frequency = snap.get("rebalance_frequency") or model.rebalance_frequency
        if model.live_effective_date:
            start_dt = model.live_effective_date
        else:
            start_dt = model.inception_date or model.published_at or model.created_at
    else:
        asset_codes = model.asset_codes
        parameters = model.parameters
        rebalance_frequency = model.rebalance_frequency
        if model.inception_date:
            start_dt = model.inception_date
        elif model.published_at:
            start_dt = model.published_at
        else:
            start_dt = model.created_at

    start_date_str = start_dt.strftime("%Y%m%d")
    end_dt = datetime.now()
    end_date_str = end_dt.strftime("%Y%m%d")

    # 3. 构造回测配置（尽量复用现有回测逻辑）
    config = BacktestConfig(
        name=f"monitoring_{model_id}",
        thscodes=asset_codes,
        start_date=start_date_str,
        end_date=end_date_str,
        rebalance_freq=rebalance_frequency,
        initial_cash=10_000_000.0,
    )

    # 4. 创建数据源
    data_feed = await DataFeed.from_market_service(
        market_service=market_service,
        config=config,
        lookback_days=500,
    )
    if data_feed.prices.empty:
        raise HTTPException(status_code=400, detail="无法获取历史行情数据，请检查资产代码和日期范围")

    # 5. 创建策略实例（从数据库模板加载）
    strategy_service = await create_strategy_service_from_database(market_service=market_service)
    try:
        strategy_cls = strategy_service.get_strategy_class(model.template_code)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"策略类型不存在: {model.template_code}")

    strategy_impl = strategy_cls()
    strategy = StrategiesWrapper(strategy_impl=strategy_impl, params=parameters)

    # 6. 创建风控和执行引擎
    risk_manager = RiskManager(config=RiskConfig())
    execution_engine = ExecutionEngine(config=config)

    # 7. 运行回测引擎（监控视角）
    engine = BacktestEngine(
        config=config,
        data_feed=data_feed,
        strategy=strategy,
        risk_manager=risk_manager,
        execution_engine=execution_engine,
    )

    result = engine.run()

    # 8. 计算绩效指标
    analyzer = PerformanceAnalyzer(risk_free_rate=0.03)
    performance = analyzer.from_results(result.snapshots, result.trades)

    # 9. 构造 BacktestResult 模型（用于输出）
    snapshots = result.snapshots
    if not snapshots:
        raise HTTPException(status_code=400, detail="监控期间无有效交易日")

    initial_val = snapshots[0].total_value or config.initial_cash

    # 计算回撤序列
    from app.analysis.formulas.drawdown import calculate_drawdown_series
    total_values_series = pd.Series([s.total_value for s in snapshots])
    drawdown_series = calculate_drawdown_series(total_values_series) if not total_values_series.empty else pd.Series()

    # 净值曲线
    equity_curve = [
        EquityPoint(
            date=s.time,
            value=s.total_value,
            unit_value=s.total_value / initial_val if initial_val != 0 else 1.0,
            cumulative_return=(s.total_value / initial_val - 1) if initial_val != 0 else 0.0,
            portfolio_volatility=getattr(s, "portfolio_volatility", None),
            drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0
        )
        for i, s in enumerate(snapshots)
    ]

    # 收益率曲线（简化：累计收益）
    return_curve = [
        ReturnPoint(
            date=s.time,
            daily_return=0.0,
            cumulative_return=(s.total_value / initial_val - 1) if initial_val != 0 else 0.0,
        )
        for s in snapshots
    ]

    # 持仓记录：只保留调仓日
    positions_record = [
        PositionRecord(
            date=s.time,
            portfolio_value=s.total_value,
            cash=s.cash,
            rebalance_reason=getattr(s, "rebalance_reason", None),
            positions=[
                AssetPosition(
                    asset_code=code,
                    asset_name=None,  # 监控场景下名称可选，如需可通过 asset_service 补全
                    weight=weight,
                    market_value=s.total_value * weight,
                )
                for code, weight in s.weights.items()
            ],
        )
        for s in snapshots
        if s.is_rebalance_day
    ]

    # 权重变化记录
    weight_changes = [
        WeightChangePoint(
            date=s.time.strftime("%Y-%m-%d"),
            weights=s.weights,
        )
        for s in snapshots
        if s.is_rebalance_day
    ]

    # 资产名称映射
    asset_names = {}
    for code in asset_codes:
        info = await asset_service.get_asset_by_code(code)
        if info:
            asset_names[code] = info.name

    # 当日净值、权重、计划调仓
    last_snap = snapshots[-1]
    date_str = last_snap.time.strftime("%Y-%m-%d")
    today_nav = TodayNav(
        date=date_str,
        unit_value=last_snap.total_value / initial_val if initial_val != 0 else 1.0,
        total_value=last_snap.total_value,
    )
    today_weights = dict(last_snap.weights) if last_snap.weights else {}
    today_planned_rebalance = None
    if last_snap.is_rebalance_day and len(snapshots) >= 2:
        prev_snap = snapshots[-2]
        prev_weights = prev_snap.weights or {}
        target_weights = last_snap.weights or {}
        all_codes = set(prev_weights.keys()) | set(target_weights.keys())
        weight_deltas = {c: target_weights.get(c, 0) - prev_weights.get(c, 0) for c in all_codes}
        today_planned_rebalance = TodayPlannedRebalance(
            date=date_str,
            is_rebalance_day=True,
            current_weights=dict(prev_weights),
            target_weights=dict(target_weights),
            weight_deltas={c: d for c, d in weight_deltas.items() if abs(d) > 1e-8},
        )

    model_result = ModelBacktestResult(
        total_return=performance.total_return,
        annual_return=performance.annual_return,
        annual_volatility=performance.annual_volatility,
        sharpe_ratio=performance.sharpe_ratio,
        max_drawdown=performance.max_drawdown,
        calmar_ratio=performance.calmar_ratio,
        equity_curve=equity_curve,
        return_curve=return_curve,
        positions=positions_record,
        weight_changes=weight_changes,
        asset_names=asset_names,
        today_nav=today_nav,
        today_weights=today_weights,
        today_planned_rebalance=today_planned_rebalance,
    )

    monitor_record = BacktestRecord(
        model_id=model_id,
        start_date=start_dt,
        end_date=end_dt,
        initial_capital=config.initial_cash,
        result=model_result,
    )

    # 构造输出模型（不落库，id 使用占位）
    monitor_out = BacktestRecordOut(
        id="monitoring",
        model_id=model_id,
        start_date=start_dt,
        end_date=end_dt,
        initial_capital=config.initial_cash,
        result=model_result,
        created_at=end_dt,
    )

    return Response.success(data=monitor_out, message="策略监控数据生成成功")


@router.get("/{model_id}/weight-changes", response_model=Response[List[WeightChangesOut]], summary="获取权重变化")
async def get_weight_changes(
    model_id: str,
    service: StrategyModelService = Depends(get_model_service),
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
    
    # 获取最新的回测记录
    records = await service.list_backtest_records(model_id=model_id, skip=0, limit=1)
    
    if not records:
        raise HTTPException(status_code=404, detail="未找到回测记录")
    
    latest_record = records[0]
    # 由于BacktestResultOut中的weight_changes是WeightChangePoint格式，我们需要转换为WeightChangesOut格式
    weight_changes_raw = latest_record.result.weight_changes
    
    # 获取资产名称映射，以便填充权重变化中的名称
    asset_names_map = getattr(latest_record.result, 'asset_names', {})
    if not asset_names_map:
        # 如果记录里没有，尝试从资产服务获取（兜底）
        all_codes = set()
        for item in weight_changes_raw:
            if hasattr(item, 'weights'):
                all_codes.update(item.weights.keys())
            elif isinstance(item, dict):
                all_codes.update(item.get('weights', {}).keys())
        
        asset_names_map = {}
        for code in all_codes:
            info = await asset_service.get_asset_by_code(code)
            if info:
                asset_names_map[code] = info.name
    
    # 转换数据格式：从WeightChangePoint对象转换为WeightChangesOut对象
    weight_changes_formatted = []
    for item in weight_changes_raw:
        # 处理兼容性：item 可能是 WeightChangePoint 对象
        if hasattr(item, 'date') and hasattr(item, 'weights'):
            # WeightChangePoint 对象
            date = item.date
            weights_dict = item.weights
        elif isinstance(item, dict):
            # 字典格式（兼容旧数据）
            date = item.get('date', '')
            weights_dict = item.get('weights', {})
        else:
            # 其他格式，跳过
            continue
        
        weights_list = [
            AssetWeight(
                asset_code=code, 
                asset_name=asset_names_map.get(code),
                weight=weight
            )
            for code, weight in weights_dict.items()
        ]
        weight_changes_formatted.append(WeightChangesOut(date=date, weights=weights_list))
    
    return Response.success(data=weight_changes_formatted)