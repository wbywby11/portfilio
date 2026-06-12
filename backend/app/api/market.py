"""
行情同步 API（SSE 流式接口）

供前端「同步行情」使用，避免长时间请求超时。
本模块提供占位实现：返回 SSE 流并提示使用「批量导入行情」补充数据；
若后续接入外部数据源，可在此扩展真实同步逻辑。
"""
from __future__ import annotations

import json
import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.services.asset_service import AssetService

router = APIRouter()


def _sse_message(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _sync_today_stream_gen() -> AsyncGenerator[str, None]:
    """生成同步当日行情 SSE 流（占位实现）。"""
    yield _sse_message({"phase": "init", "phase_label": "正在检查…", "percent": 0})
    await asyncio.sleep(0.2)
    yield _sse_message({
        "phase": "check",
        "phase_label": "检查资产与数据源…",
        "percent": 10,
        "log": "当前环境未配置外部行情数据源。"
    })
    await asyncio.sleep(0.2)
    yield _sse_message({
        "phase": "skip",
        "phase_label": "完成",
        "percent": 100,
        "log": "请使用「批量导入行情」或 Excel 导入补充行情数据。"
    })
    yield _sse_message({
        "done": True,
        "result": {
            "skipped": True,
            "message": "当日行情同步在本环境中为占位实现，请使用「批量导入行情」或 Excel 导入补充数据。"
        },
        "error": None
    })


@router.post("/sync-today/stream", summary="同步当日行情（SSE 流）")
async def sync_today_stream(
    service: AssetService = Depends(lambda: AssetService()),
):
    """
    以 SSE 流式返回同步进度，供前端「同步行情」展示。
    当前为占位实现：无外部数据源时立即返回提示，建议使用「批量导入行情」上传 Excel。
    """
    return StreamingResponse(
        _sync_today_stream_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
