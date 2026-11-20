# -*- coding: utf-8 -*-
"""策略档案采集器 —— 从 STRATEGY_MANIFEST 静态采集 18 条档案.

采集口径：
    - ``manifest_key`` = STRATEGY_MANIFEST 的键，``strategy_id`` 由本模块生成
      UUID4（不派生，见 :mod:`app.models.strategy_registry`）；
    - ``LEGACY_ALIASES`` 的 3 个旧 code **不生成独立文档**，写成目标策略的
      ``aliases`` —— 别名一旦独立成档就会在查询面多出 3 个「策略」，
      但它们并没有自己的类、没有自己的版本链；
    - standalone 6 条按 manifest 的 ``strategy_form`` 直接落档（不再用
      ``composition.allocator`` 反推：vol_scaled_budget 的 allocator 也指向自身）；
    - 静态反射 ``get_data_contract`` / ``get_extra_panels`` / ``get_panel_datasets``
      全部按**类**调用（三者都是 classmethod），不实例化策略类 ——
      ``published_snapshot.py`` 已记录「策略类不可无参实例化」的坑；
      任一反射失败记 ``None``，不中断整轮采集。

``pending_scope``：本期只覆盖 allocation 支柱的 18 条 manifest 条目，
selection / control 两类模板（由 builtin_templates 的独立派生循环生成）
不建档案，写进 pending_scope 明示缺口，避免被读成「系统里没有这些组件」。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from app.allocation.strategy_manifest import LEGACY_ALIASES, STRATEGY_MANIFEST
from app.services.strategy_registry_service import StrategyRegistryService

logger = logging.getLogger(__name__)

__all__ = ["collect_registry_entries", "sync_registry_from_manifest"]


def _aliases_for(manifest_key: str) -> List[str]:
    """反向别名表：目标 code → 指向它的旧 code 列表（排序保证幂等）."""
    return sorted(alias for alias, target in LEGACY_ALIASES.items() if target == manifest_key)


def _reflect_contract(cls: Any) -> Optional[Dict[str, Any]]:
    """静态反射 ``get_data_contract()``，返回可落库的纯量字典."""
    getter = getattr(cls, "get_data_contract", None)
    if not callable(getter):
        return None
    try:
        contract = getter()
    except Exception as exc:  # noqa: BLE001 —— 反射失败不中断采集
        logger.warning("[registry_collector] get_data_contract 失败 %s: %s", cls, exc)
        return None
    if contract is None:
        return None
    snapshot: Dict[str, Any] = {}
    for name in (
        "min_assets",
        "min_history_days",
        "require_continuous",
        "max_single_day_jump",
        "min_price",
        "calendar",
    ):
        if hasattr(contract, name):
            value = getattr(contract, name)
            # 只落库 JSON 可存的纯量，避免把 GroupSpec 之类结构塞进快照
            snapshot[name] = value if isinstance(value, (int, float, bool, str)) or value is None else str(value)
    groups = getattr(contract, "group_params", None)
    if isinstance(groups, dict):
        snapshot["group_params"] = sorted(groups.keys())
    expected = getattr(contract, "expected_asset_class", None)
    if isinstance(expected, dict):
        snapshot["expected_asset_class"] = {str(k): str(v) for k, v in expected.items()}
    checks = getattr(contract, "custom_checks", None)
    if checks is not None:
        snapshot["custom_checks"] = list(checks)
    panels = getattr(contract, "panels", None)
    if isinstance(panels, dict):
        snapshot["panels"] = {str(k): str(v) for k, v in panels.items()}
    datasets = getattr(contract, "datasets", None)
    if datasets is not None:
        snapshot["datasets"] = list(datasets)
    return snapshot


def _reflect_panels(cls: Any) -> Optional[Dict[str, str]]:
    """静态反射面板声明 ``{面板名: dataset}``."""
    out: Dict[str, str] = {}
    try:
        getter = getattr(cls, "get_extra_panels", None)
        names = list(getter() or []) if callable(getter) else []
        dgetter = getattr(cls, "get_panel_datasets", None)
        datasets = dict(dgetter() or {}) if callable(dgetter) else {}
        for name in names:
            out[str(name)] = str(datasets.get(name) or "")
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("[registry_collector] 面板声明反射失败 %s: %s", cls, exc)
        return None


def collect_registry_entries() -> List[Dict[str, Any]]:
    """静态生成全部档案记录（不落库，纯函数，便于单测）."""
    from app.allocation.strategy_manifest import resolve_class_safe

    rows: List[Dict[str, Any]] = []
    for manifest_key, entry in STRATEGY_MANIFEST.items():
        cls = resolve_class_safe(manifest_key)
        contract_snapshot = _reflect_contract(cls) if cls is not None else None
        panels_snapshot = _reflect_panels(cls) if cls is not None else None
        composition = dict(entry.composition or {})
        rows.append(
            {
                "manifest_key": manifest_key,
                "strategy_id": str(uuid.uuid4()),
                "payload": {
                    "name": entry.name,
                    "description": entry.description,
                    "class_path": entry.class_path,
                    "strategy_form": entry.strategy_form or "composite",
                    "pillar": "allocation",
                    "aliases": _aliases_for(manifest_key),
                    "component_set_declared": composition,
                    "pending_scope": ["selection", "control"],
                    "data_contract_snapshot": contract_snapshot,
                    "panel_datasets_snapshot": panels_snapshot,
                    "signal_family": composition.get("selector") or None,
                },
            }
        )
    return rows


async def sync_registry_from_manifest() -> Dict[str, Any]:
    """采集并 upsert 全部档案，返回计数.

    幂等：已存在的 ``manifest_key`` 只刷新采集字段，``strategy_id`` 与人工字段
    （``trial_count`` / ``owner`` / ``tags`` / ``lifecycle_stage``）不动，
    因此多次启动不会改变策略身份。
    """
    svc = StrategyRegistryService()
    rows = collect_registry_entries()
    ok = 0
    for row in rows:
        if await svc.upsert_entry(row["manifest_key"], row["strategy_id"], row["payload"]):
            ok += 1
    logger.info(
        "[registry_collector] 档案同步完成: manifest=%d 写入成功=%d standalone=%d",
        len(rows), ok,
        sum(1 for r in rows if r["payload"]["strategy_form"] == "standalone"),
    )
    return {"total": len(rows), "upserted": ok}
