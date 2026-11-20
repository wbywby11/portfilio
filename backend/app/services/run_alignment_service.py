# -*- coding: utf-8 -*-
"""跨通道运行对齐（S13）：按 ``config_fingerprint`` 把回测与监控运行分组.

同一模型在「同一份发布配置指纹」下产生的回测与监控记录，才具备可比性：
回测回答「这段配置在历史上会怎样」，监控回答「这段配置实盘跑出来怎样」。
指纹相等即对齐；指纹缺失的存量记录单独归入 ``ungrouped``，不做推断。

只读服务：不写库、不改任何运行记录。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.strategy_run_service import StrategyRunService

__all__ = ["RunAlignmentService", "COVERAGE_NOTE"]

# 历史缺口声明：前端/调用方据此区分「没跑过」与「上线前没记录」
COVERAGE_NOTE = "自本功能上线起有记录；更早的历史运行未登记，缺口不代表未运行"


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class RunAlignmentService:
    """运行对齐读写（只读）"""

    @staticmethod
    def _brief(run: Any) -> Dict[str, Any]:
        return {
            "run_id": run.run_id,
            "run_kind": run.run_kind,
            "model_id": run.model_id,
            "strategy_id": run.strategy_id,
            "config_version_id": run.config_version_id,
            "config_fingerprint": run.config_fingerprint,
            "reproducibility_fingerprint": run.reproducibility_fingerprint,
            "engine_version": run.engine_version,
            "window": dict(run.window or {}),
            "metrics": dict(run.metrics or {}),
            "status": run.status,
            "created_at": _iso(run.created_at),
        }

    async def align_runs(self, model_id: str, limit: int = 200) -> Dict[str, Any]:
        """按配置指纹分组返回 ``{groups, ungrouped}``.

        Args:
            model_id: 策略模型 ID
            limit: 最多扫描的运行记录条数（按 created_at 倒序）

        Returns:
            ``{"model_id", "groups", "ungrouped", "coverage"}``；
            ``groups`` 每项含 ``config_fingerprint`` / ``backtest_runs`` /
            ``monitor_runs`` / ``aligned``（两种运行都有才为 True）。
        """
        model_id = str(model_id or "").strip()
        empty = {
            "model_id": model_id,
            "groups": [],
            "ungrouped": {"backtest_runs": [], "monitor_runs": []},
            "coverage": COVERAGE_NOTE,
        }
        if not model_id:
            return empty

        runs = await StrategyRunService().list_runs(model_id=model_id, limit=limit)

        groups: Dict[str, Dict[str, Any]] = {}
        ungrouped: Dict[str, List[Dict[str, Any]]] = {"backtest_runs": [], "monitor_runs": []}
        for run in runs:
            if run is None:
                continue
            if run.run_kind == "monitor":
                bucket_key = "monitor_runs"
            elif run.run_kind == "backtest":
                bucket_key = "backtest_runs"
            else:  # signal_replay 暂不参与对齐
                continue
            item = self._brief(run)
            fingerprint = run.config_fingerprint
            if not fingerprint:
                ungrouped[bucket_key].append(item)
                continue
            group = groups.setdefault(
                fingerprint,
                {
                    "config_fingerprint": fingerprint,
                    "backtest_runs": [],
                    "monitor_runs": [],
                },
            )
            group[bucket_key].append(item)

        ordered: List[Dict[str, Any]] = []
        for group in groups.values():
            group["aligned"] = bool(group["backtest_runs"]) and bool(group["monitor_runs"])
            latest = max(
                (r.get("created_at") or "" for r in group["backtest_runs"] + group["monitor_runs"]),
                default="",
            )
            group["latest_at"] = latest or None
            ordered.append(group)
        ordered.sort(key=lambda g: g.get("latest_at") or "", reverse=True)

        return {
            "model_id": model_id,
            "groups": ordered,
            "ungrouped": ungrouped,
            "coverage": COVERAGE_NOTE,
        }
