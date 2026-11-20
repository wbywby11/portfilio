# -*- coding: utf-8 -*-
"""策略运行台账服务（``strategy_runs``）—— append-only 摘要写入与读取.

写入约束（R3，与 ``strategy_versions`` 同口径）：
    - 只在主写成功之后调用（回测记录已插入 / 监控状态已落库）；
    - 调用方用整块 try/except 包裹，本服务失败只 warn 并返回 None，不向上抛；
    - 幂等：同一 ``(run_kind, backtest_record_id)`` 重复写入返回已存在的 run_id，
      保证「一次回测 ⇒ 恰好一条 backtest 运行记录」。

刻意不存净值/持仓/交易明细：台账只回答「谁、用哪版配置、在哪个窗口、跑了什么
结果、能不能复现」，曲线细节一律回 ``backtest_records`` 取（B4-1）。
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config.collections import COL_STRATEGY_RUNS
from app.config.database import Database
from app.models.strategy_run import METRIC_KEYS, RUN_KINDS, RUN_STATUSES, StrategyRun

logger = logging.getLogger(__name__)

__all__ = ["StrategyRunService", "build_run_metrics", "normalize_metrics"]


def _num(value: Any) -> Optional[float]:
    """数值化；None / 非数值 / NaN / inf 一律视为缺失."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def _date_str(value: Any) -> Optional[str]:
    """窗口端点统一成 ``YYYY-MM-DD`` 字符串（datetime / str / None 均可）."""
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return text[:10] if text else None


def normalize_metrics(metrics: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """按白名单裁剪指标：只保留 8 个键，缺失项不写键，NaN/inf 丢弃."""
    if not metrics:
        return {}
    out: Dict[str, Optional[float]] = {}
    for key in METRIC_KEYS:
        if key not in metrics:
            continue
        num = _num(metrics.get(key))
        if num is not None:
            out[key] = num
    return out


def build_run_metrics(result: Any) -> Dict[str, Optional[float]]:
    """从 ``BacktestResult``（对象或 dict）抽出 8 项白名单指标.

    字段改名只在这一个函数里发生（``annual_volatility`` → ``annual_vol``，
    ``sharpe_ratio`` → ``sharpe``），监控（S13）可复用同一口径。
    """
    if result is None:
        return {}
    get = result.get if isinstance(result, dict) else (lambda k, d=None: getattr(result, k, d))
    raw = {
        "total_return": get("total_return"),
        "annual_return": get("annual_return"),
        "annual_vol": get("annual_volatility"),
        "sharpe": get("sharpe_ratio"),
        "max_drawdown": get("max_drawdown"),
        "calmar": get("calmar_ratio"),
        "win_rate": get("win_rate"),
        "latest_unit_value": get("latest_unit_value"),
    }
    return normalize_metrics(raw)


class StrategyRunService:
    """运行台账读写（写入只有 append 一条路径）"""

    @property
    def collection(self):
        return Database.get_database()[COL_STRATEGY_RUNS]

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    async def append_run(
        self,
        *,
        run_kind: str,
        model_id: str,
        strategy_id: Optional[str] = None,
        config_version_id: Optional[str] = None,
        backtest_record_id: Optional[str] = None,
        pool_hash_value: Optional[str] = None,
        contract_hash_value: Optional[str] = None,
        data_digest: Optional[str] = None,
        config_fingerprint: Optional[str] = None,
        reproducibility_fingerprint: Optional[str] = None,
        engine_version: Optional[str] = None,
        window_start: Any = None,
        window_end: Any = None,
        metrics: Optional[Dict[str, Any]] = None,
        status: str = "success",
    ) -> Optional[str]:
        """追加一条运行摘要，返回 run_id；同回测记录已存在时返回原 run_id."""
        model_id = str(model_id or "").strip()
        if not model_id:
            return None
        kind = run_kind if run_kind in RUN_KINDS else "backtest"
        record_ref = str(backtest_record_id) if backtest_record_id else None

        if record_ref:
            existing = await self.collection.find_one(
                {"run_kind": kind, "backtest_record_id": record_ref},
                projection={"run_id": 1},
            )
            if existing:
                return existing.get("run_id")

        doc: Dict[str, Any] = {
            "run_id": str(uuid.uuid4()),
            "run_kind": kind,
            "strategy_id": strategy_id,
            "model_id": model_id,
            "config_version_id": config_version_id,
            "backtest_record_id": record_ref,
            "pool_hash": pool_hash_value,
            "contract_hash": contract_hash_value,
            "data_digest": data_digest,
            "config_fingerprint": config_fingerprint,
            "reproducibility_fingerprint": reproducibility_fingerprint,
            "engine_version": engine_version,
            "window": {"start": _date_str(window_start), "end": _date_str(window_end)},
            "metrics": normalize_metrics(metrics),
            "status": status if status in RUN_STATUSES else "success",
            "created_at": datetime.now(),
            "schema_version": 1,
        }
        # 可选键为空时不写：读取侧统一 .get()，避免存量文档出现大量 null
        payload = {k: v for k, v in doc.items() if v is not None}
        try:
            await self.collection.insert_one(payload)
            return payload["run_id"]
        except Exception as exc:  # noqa: BLE001 —— 由调用方决定是否记录，本层不抛
            logger.warning(
                "[strategy_runs] 运行记录写入失败 model_id=%s kind=%s: %s",
                model_id, kind, exc,
            )
            return None

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    async def list_runs(
        self,
        strategy_id: Optional[str] = None,
        model_id: Optional[str] = None,
        run_kind: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[StrategyRun]:
        """按策略 / 模型 / 种类列运行记录（策略库查询 API 用）."""
        query: Dict[str, Any] = {}
        if strategy_id:
            query["strategy_id"] = strategy_id
        if model_id:
            query["model_id"] = model_id
        if run_kind:
            query["run_kind"] = run_kind
        if not query:
            return []
        cursor = (
            self.collection.find(query)
            .sort("created_at", -1)
            .skip(max(0, int(skip)))
            .limit(max(1, int(limit)))
        )
        return [self._to_model(doc) async for doc in cursor if doc]  # type: ignore[list-item]

    async def count(self, model_id: Optional[str] = None, run_kind: Optional[str] = None) -> int:
        query: Dict[str, Any] = {}
        if model_id:
            query["model_id"] = model_id
        if run_kind:
            query["run_kind"] = run_kind
        return int(await self.collection.count_documents(query))

    @staticmethod
    def _to_model(doc: Optional[Dict[str, Any]]) -> Optional[StrategyRun]:
        if not doc:
            return None
        data = {k: v for k, v in doc.items() if k != "_id"}
        try:
            return StrategyRun(**data)
        except Exception as exc:  # noqa: BLE001 —— 单条坏文档不拖垮列表
            logger.warning("[strategy_runs] 文档解析失败 run_id=%s: %s", doc.get("run_id"), exc)
            return None
