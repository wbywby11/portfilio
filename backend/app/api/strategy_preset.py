"""策略原型预设路由

三个只读/无状态端点，与策略模型的增删改查分开：

- ``GET  /presets``                       预设摘要列表（明细走 resolve）
- ``POST /presets/validate``              任意一组配置的实时门禁
- ``POST /presets/{preset_code}/resolve`` 预设声明 → 展开后的配置 + 问题清单

**注册顺序**：本 router 必须挂在与 ``strategy_model_router`` 相同的前缀下，
且**先于**后者注册。``strategy_model_router`` 有 ``GET /{model_id}``，
若后注册，``GET /presets`` 会被当成 ``model_id="presets"`` 抢先匹配。
"""
from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from app.allocation.builtin_presets import list_preset_summaries
from app.schemas.response import Response
from app.services.strategy_preset_service import (
    resolve_preset as resolve_preset_definition,
)
from app.services.strategy_preset_service import (
    validate_config as validate_strategy_config_payload,
)

router = APIRouter()


@router.get("/presets", response_model=Response[List[dict]], summary="策略原型预设列表")
async def list_strategy_presets(
    template_code: Optional[str] = Query(None, description="模板代码，留空返回全部"),
):
    """返回内置预设摘要（code / 名称 / 版本标签 / 内容 hash）. 明细走 resolve."""
    return Response.success(data=list_preset_summaries(template_code))


@router.post("/presets/validate", response_model=Response[dict], summary="校验一组策略配置")
async def validate_strategy_config(payload: dict = Body(...)):
    """实时门禁：任意一组配置给出三级问题清单，不要求已保存.

    入参 ``{template_code, asset_codes, parameters, min_history_days,
    rebalance_frequency}``。详情页与回测页据此决定「运行回测」是否可用，
    与 resolve 共用同一套校验链，只是跳过预设加载。

    模板不可用（未注册 / 类加载失败）时返回 200 + ``template_not_found``
    阻断结论，不走 404：前端拿不到问题清单时会清空门禁并放行，
    反而让不可用的模型看起来「可以回测」。
    """
    template_code = str(payload.get("template_code") or "").strip()
    if not template_code:
        raise HTTPException(status_code=400, detail="template_code 不能为空")
    try:
        result = await validate_strategy_config_payload(
            template_code=template_code,
            asset_codes=payload.get("asset_codes") or [],
            parameters=payload.get("parameters") or {},
            min_history_days=payload.get("min_history_days"),
            rebalance_frequency=payload.get("rebalance_frequency"),
            name=str(payload.get("name") or ""),
        )
    except KeyError as exc:
        # 仅覆盖资产展开等异常路径（模板不可用已在 service 层转为阻断结论）
        raise HTTPException(status_code=404, detail=str(exc))
    return Response.success(data=result.to_dict())


@router.post(
    "/presets/{preset_code}/resolve",
    response_model=Response[dict],
    summary="展开预设（资产池 + 参数 + 校验结论）",
)
async def resolve_strategy_preset(preset_code: str):
    """把预设声明展开成可直接应用的配置，并返回三级问题清单.

    ``applicable=False``（存在 blocking_error）时前端禁用「应用」；
    ``backtest_ready=False`` 时禁用「运行回测」。
    """
    try:
        result = await resolve_preset_definition(preset_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response.success(data=result.to_dict())
