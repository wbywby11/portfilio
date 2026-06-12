"""
单请求内行情导入进度（内存），供前端轮询 GET /assets/prices/import/progress 展示。
多 worker 部署时需改为 Redis 等共享存储。
"""
import asyncio
import time
from typing import Any, Dict, Optional

_lock = asyncio.Lock()
_store: Dict[str, Dict[str, Any]] = {}
_TTL_SEC = 3600
# 完成后保留一段时间，便于前端在导入请求返回前最后一次轮询到 done
_DONE_CLEAR_DELAY_SEC = 30.0


async def _schedule_clear_after_done(progress_id: str) -> None:
    await asyncio.sleep(_DONE_CLEAR_DELAY_SEC)
    async with _lock:
        _store.pop(progress_id, None)


def metric_to_cn(metric: Optional[str]) -> str:
    m = (metric or "").strip().lower()
    mp = {
        "close": "收盘价",
        "open": "开盘价",
        "high": "最高价",
        "low": "最低价",
        "volume": "成交量",
        "amount": "成交额",
        "scale": "规模",
    }
    return mp.get(m, "行情")


def _prune_stale() -> None:
    now = time.time()
    dead = [k for k, v in _store.items() if now - float(v.get("updated_at") or 0) > _TTL_SEC]
    for k in dead:
        _store.pop(k, None)


async def touch_progress(
    progress_id: Optional[str],
    *,
    asset_code: str,
    asset_name: str = "",
    import_metric: Optional[str] = None,
    phase: str = "",
    prepare_done: int = 0,
    file_line_total: int = 0,
    write_done: int = 0,
    write_total: int = 0,
    message: str = "",
) -> None:
    if not progress_id:
        return
    payload: Dict[str, Any] = {
        "progress_id": progress_id,
        "asset_code": asset_code,
        "asset_name": (asset_name or "").strip() or asset_code,
        "metric_key": (import_metric or "").strip().lower() or None,
        "metric_label": metric_to_cn(import_metric),
        "phase": phase,
        "prepare_done": int(max(0, prepare_done)),
        "file_line_total": int(max(0, file_line_total)),
        "write_done": int(max(0, write_done)),
        "write_total": int(max(0, write_total)),
        "message": message or "",
        "updated_at": time.time(),
    }
    async with _lock:
        _prune_stale()
        _store[progress_id] = payload
    if phase == "done":
        asyncio.create_task(_schedule_clear_after_done(progress_id))


async def get_snapshot(progress_id: str) -> Optional[Dict[str, Any]]:
    if not progress_id:
        return None
    async with _lock:
        v = _store.get(progress_id)
        return dict(v) if v else None


async def clear_progress(progress_id: Optional[str]) -> None:
    if not progress_id:
        return
    async with _lock:
        _store.pop(progress_id, None)
