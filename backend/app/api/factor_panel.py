"""因子截面数据路由"""
import asyncio
from typing import Any, Dict

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from loguru import logger

from app.schemas.response import Response
from app.services.factor_panel_service import FactorPanelService
from app.services.factor_panel_templates import build_factor_panel_template

router = APIRouter()

_SHEET_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def get_factor_panel_service() -> FactorPanelService:
    return FactorPanelService()


def _notice_suffix(result: Dict[str, Any]) -> str:
    """把定性说明与告警拼成提示后缀（导入与预演共用，避免两处口径漂移）。

    快照期定性放在告警之前：它不是错误，但直接决定策略走打分选样还是
    全截面等权，必须让用户在提示里第一眼看到。
    """
    suffix = ""
    snapshot = result.get("snapshot_periods") or []
    if snapshot:
        suffix += (
            f"；{len(snapshot)} 期整期无因子，按成分快照期写入"
            f"（{snapshot[0]} ~ {snapshot[-1]}，策略全截面入选等权）"
        )
    skipped = result.get("skipped_reasons") or {}
    empty = skipped.get("factor_empty") or 0
    if empty:
        suffix += (
            f"；{empty} 行因子全空未写库（同期内其他行有因子，判为漏填；"
            "整期都不填因子列才按成分快照写入）"
        )
    warnings = result.get("warnings") or {}
    unknown = warnings.get("code_not_in_assets") or 0
    if unknown:
        suffix += f"；{unknown} 只代码不在资产主数据中，回测时取不到行情"
    unmapped = warnings.get("unmapped_columns") or []
    if unmapped:
        suffix += f"；忽略无法识别的列 {len(unmapped)} 个"
    non_numeric = warnings.get("non_numeric_cells") or {}
    if non_numeric:
        detail = "、".join(f"{c} {n} 行" for c, n in sorted(non_numeric.items()))
        suffix += f"；数值因子列出现文本已置空：{detail}"
    return suffix


def _build_message(result: Dict[str, Any]) -> str:
    """把导入统计拼成含关键数据的提示文本（不写「操作成功」这类空话）。"""
    message = (
        f"数据集 {result.get('dataset')} 导入完成：新增 {result['inserted_count']} 行，"
        f"更新 {result['updated_count']} 行，跳过 {result['skipped_count']} 行，"
        f"错误 {result['error_count']} 行，共 {len(result['periods'])} 期"
    )
    return message + _notice_suffix(result)


def _build_preview_message(result: Dict[str, Any]) -> str:
    """预演结果的提示文本：识别到几期、几行、几个因子键、多少告警。"""
    message = (
        f"数据集 {result.get('dataset')} 预演完成：识别到 {len(result['periods'])} 期，"
        f"共 {result['total_rows']} 行，因子键 {len(result.get('factor_keys') or [])} 个，"
        f"错误 {result['error_count']} 行"
    )
    return message + _notice_suffix(result)


@router.post("/import", response_model=Response[dict], summary="导入因子截面数据")
async def import_factor_panel(
    file: UploadFile = File(..., description="因子截面 Excel 文件，一个文件可含任意期数"),
    dataset: str = Form(
        ...,
        description=(
            "目标数据集标识，必填；取值见 GET /factor-panel/datasets。"
            "factor_panel 集合被多个数据集共用，整个文件写入同一个数据集"
        ),
    ),
    mode: str = Form(
        "upsert",
        description=(
            "upsert=按(数据集,日期,代码)逐行覆盖，重复导入结果一致；"
            "replace=仅覆盖本数据集中文件出现的那几期，其他期与其他数据集不动；"
            "incremental=只写库内还没有的(数据集,日期,代码)"
        ),
    ),
    as_of_date: str = Form(
        "",
        description=(
            "决策日（信号日）YYYY-MM-DD：T 日收盘用该截面算权重、收益自 T+1 起。"
            "文件无日期列时作为整期决策日（半年一次，由用户指定）；"
            "若源数据是持仓生效日 startdate，请先换算为生效日前一交易日"
        ),
    ),
    dry_run: bool = Form(
        False,
        description="true=只解析预演（识别到的期/行数/因子键/告警），不写库",
    ),
    service: FactorPanelService = Depends(get_factor_panel_service),
):
    """从 Excel 导入因子截面数据（一期一股一行，按「日期」列自动分期）。"""
    # 先留痕再校验：上传失败往往发生在 handler 入口（扩展名、解析），不记的话无从排查
    logger.info(
        "[FactorPanel-API] import 请求: file={!r} dataset={!r} mode={!r} "
        "as_of_date={!r} dry_run={}",
        file.filename, dataset, mode, as_of_date, dry_run,
    )
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        logger.warning("[FactorPanel-API] 拒绝上传：文件名不合法 {!r}", file.filename)
        raise HTTPException(
            status_code=400, detail="请上传 .xlsx 或 .xls 格式的 Excel 文件"
        )

    content = await file.read()
    logger.info("[FactorPanel-API] 已读取 {!r} {} 字节", file.filename, len(content))
    try:
        result = await service.import_from_excel(
            content, dataset=dataset, mode=mode, filename=file.filename,
            as_of_date=as_of_date, dry_run=dry_run,
        )
    except ValueError as exc:
        logger.warning("[FactorPanel-API] 导入被拒绝：{}", exc)
        raise HTTPException(status_code=400, detail=str(exc))

    message = _build_preview_message(result) if dry_run else _build_message(result)
    return Response.success(data=result, message=message)


@router.get("/datasets", response_model=Response[list], summary="因子截面数据集清单")
async def list_factor_panel_datasets(
    service: FactorPanelService = Depends(get_factor_panel_service),
):
    """可导入的数据集清单（含各自行数/期数/起止期日），供前端下拉选择。

    已登记但库内无数据的数据集也会列出（row_count=0）；库内存在但未登记的
    标 registered=false，不隐藏。
    """
    try:
        rows = await service.get_datasets()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response.success(data=rows)


@router.get("/overview", response_model=Response[dict], summary="因子截面数据总览")
async def get_factor_panel_overview(
    dataset: str = Query(
        "", description="按数据集筛选；留空返回全部数据集的合计与各数据集分解"
    ),
    service: FactorPanelService = Depends(get_factor_panel_service),
):
    """已导入的总览、期清单与因子键清单（面板显示「已有 N 期，最新期日」）。"""
    try:
        stats, periods, factor_names = await asyncio.gather(
            service.get_stats(dataset or None),
            service.get_periods(dataset or None),
            service.get_factor_names(dataset or None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response.success(
        data={"stats": stats, "periods": periods, "factor_names": factor_names}
    )


@router.get(
    "/period/{dataset}/{as_of_date}",
    response_model=Response[dict],
    summary="读取某数据集某一期因子截面",
)
async def get_factor_panel_period(
    dataset: str = Path(..., description="数据集标识，见 GET /factor-panel/datasets"),
    as_of_date: str = Path(..., description="期日 YYYY-MM-DD 或 YYYYMMDD"),
    service: FactorPanelService = Depends(get_factor_panel_service),
):
    """读取指定期日的全部截面行（按代码升序），用于导入后人工核对。

    dataset 走路径而非可选参数：不指定会把同一期日下不同数据集的行混在一起返回。
    """
    try:
        rows = await service.get_period(dataset, as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"数据集 {dataset} 的期日 {as_of_date} 没有数据",
        )
    return Response.success(
        data={
            "dataset": dataset,
            "as_of_date": rows[0]["as_of_date"],
            "row_count": len(rows),
            "rows": rows,
        }
    )


@router.delete(
    "/period/{dataset}/{as_of_date}",
    response_model=Response[dict],
    summary="删除某数据集某一期因子截面",
)
async def delete_factor_panel_period(
    dataset: str = Path(..., description="数据集标识，见 GET /factor-panel/datasets"),
    as_of_date: str = Path(..., description="期日 YYYY-MM-DD 或 YYYYMMDD"),
    service: FactorPanelService = Depends(get_factor_panel_service),
):
    """整期删除（导错重来）；只删本数据集的该期，其他期与其他数据集不受影响。"""
    try:
        result = await service.delete_period(dataset, as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if result["deleted_count"] == 0:
        return Response.success(
            data=result,
            message=(
                f"数据集 {result['dataset']} 未找到期日 {result['as_of_date']}，"
                "没有删除任何数据"
            ),
        )
    return Response.success(
        data=result,
        message=(
            f"已删除数据集 {result['dataset']} 期日 {result['as_of_date']} "
            f"共 {result['deleted_count']} 行"
        ),
    )


@router.get("/template/download", summary="下载因子截面导入模板")
async def download_factor_panel_template(
    dataset: str = Query(
        ..., description="数据集标识；模板按数据集出，因子列与说明各不相同"
    ),
):
    """下载指定数据集的因子截面 Excel 模板（数据 sheet + 填写说明 sheet）。"""
    try:
        output, filename = build_factor_panel_template(dataset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(output, headers=headers, media_type=_SHEET_MEDIA_TYPE)
