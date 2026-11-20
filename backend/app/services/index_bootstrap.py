# -*- coding: utf-8 -*-
"""索引启动引导 —— 按 ``index_specs`` 补齐缺失索引.

设计要点：
    - **先比对再建**：``list_indexes()`` 已存在的键形态直接跳过，二次启动
      ``createIndexes`` 调用数为 0；
    - **失败只 warn**：沿用 ``main.py`` 既有引导惯例（模板初始化 / 数据资产扫描 /
      知识库索引均不阻断启动），索引缺失是性能问题而非功能故障；
    - **进程内 ``_ready`` 位**：lifespan 只有一次，但测试与脚本会重复调用，
      置位后直接返回，避免重复往返；
    - **同键不同唯一性只告警**：存量库若已有同键非唯一索引，强建唯一索引会
      因选项冲突失败，且重复文档会让唯一索引永远建不起来 —— 记录告警交由人工处置，
      不静默改语义。

批次化存量兼容（不写独立迁移脚本，全部在启动引导里完成）：
    - **先补数据再建索引**：``index_specs.LEGACY_BATCH_BACKFILL`` 里的集合，
      把 ``batch_id`` 缺失/为 null 的存量文档统一补 ``"legacy"``，否则新的
      ``{monitor_id, batch_id}`` 唯一索引会把存量文档归为 null 并拒绝第二条；
    - **一次性标记位**：补齐成功后在 ``_collection_registry`` 写一条标记文档，
      下次启动直接跳过，不对大集合做重复全表扫描；部分失败不写标记，下次重试
      （``update_many`` 的过滤条件本身幂等）；
    - **建完新索引再删旧索引**：``LEGACY_INDEX_DROPS`` 按「键签名 + 唯一性」双重
      匹配后删除，避免旧唯一索引残留导致新批次文档被拒。

使用方式::

    from app.services.index_bootstrap import ensure_all_indexes
    result = await ensure_all_indexes()          # 启动引导
    result = await ensure_all_indexes(only_missing=False)  # 强制幂等重建（脚本）
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config.collections import COL_COLLECTION_REGISTRY
from app.config.database import Database
from app.config.index_specs import (
    LEGACY_BATCH_BACKFILL,
    LEGACY_BATCH_ID,
    LEGACY_INDEX_DROPS,
    IndexSpec,
    specs_by_collection,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_all_indexes",
    "reset_ready",
    "backfill_legacy_batch_ids",
    "drop_legacy_indexes",
]

# 进程内引导完成位：同进程只比对一次
_READY = False

# 存量 batch_id 补齐的一次性标记文档 ID（落在 _collection_registry，持久化跨重启）
_BACKFILL_MARKER_ID = "index_bootstrap:legacy_batch_backfill:v1"


def reset_ready() -> None:
    """复位引导位（仅测试/脚本使用）."""
    global _READY
    _READY = False


def _key_signature(keys: Any) -> tuple:
    """把 ``list_indexes()`` 的 SON 键描述归一为可比较元组."""
    if isinstance(keys, list):  # pymongo 3.13+ 返回 list of (key, direction)
        return tuple((str(k), int(d)) for k, d in keys)
    return tuple((str(k), int(d)) for k, d in dict(keys).items())


async def _ensure_collection(
    db: Any, collection: str, specs: List[IndexSpec], only_missing: bool
) -> Dict[str, Any]:
    """补齐单集合索引，返回 ``{created, skipped, warned}`` 计数."""
    stat = {"created": 0, "skipped": 0, "warned": 0}
    coll = db[collection]
    try:
        existing = await coll.list_indexes().to_list(length=None)
    except Exception as exc:  # 集合不存在时 list_indexes 返回空，真异常只 warn
        logger.warning("[index_bootstrap] %s 读取索引清单失败: %s", collection, exc)
        stat["warned"] += 1
        return stat

    by_keys: Dict[tuple, Dict[str, Any]] = {}
    for idx in existing or []:
        try:
            by_keys[_key_signature(idx.get("key"))] = dict(idx)
        except Exception:  # 异常索引描述不参与比对
            continue

    for spec in specs:
        got = by_keys.get(spec.keys)
        if got is not None:
            if bool(got.get("unique", False)) != bool(spec.unique):
                logger.warning(
                    "[index_bootstrap] %s 已存在同键索引 %s 但 unique=%s，与声明 %s 不一致，跳过",
                    collection, got.get("name"), got.get("unique", False), spec.unique,
                )
                stat["warned"] += 1
            else:
                stat["skipped"] += 1
            continue
        kwargs: Dict[str, Any] = {
            "name": spec.index_name,
            "unique": bool(spec.unique),
            "background": True,
        }
        if spec.partial_filter is not None:
            kwargs["partialFilterExpression"] = spec.partial_filter
        try:
            await coll.create_index(list(spec.keys), **kwargs)
            stat["created"] += 1
        except Exception as exc:
            logger.warning(
                "[index_bootstrap] 建索引失败 %s.%s: %s", collection, spec.index_name, exc
            )
            stat["warned"] += 1
    return stat


async def backfill_legacy_batch_ids(db: Any, force: bool = False) -> Dict[str, Any]:
    """把批次化涉及集合的存量文档补上 ``batch_id="legacy"``.

    幂等且轻量：
        - 过滤条件用 ``{"batch_id": None}``，Mongo 语义下同时命中「字段缺失」与
          「字段为 null」，已补过的文档不会被重复写；
        - ``_collection_registry`` 里的标记文档存在时直接返回，不做全表扫描；
        - 只有全部集合都补齐成功才写标记，否则下次启动重试。

    Args:
        db: motor 数据库句柄。
        force: True 时忽略标记位强制重跑（仅核对用，本身幂等）。

    Returns:
        ``{"skipped": bool, "modified": n, "collections": n, "failed": [...]}``。
    """
    stat: Dict[str, Any] = {"skipped": False, "modified": 0, "collections": 0, "failed": []}
    registry = db[COL_COLLECTION_REGISTRY]

    if not force:
        try:
            marker = await registry.find_one({"_id": _BACKFILL_MARKER_ID})
        except Exception as exc:  # 标记读不到宁可重跑一次（幂等），不能因此跳过
            logger.warning("[index_bootstrap] 读取 batch_id 补齐标记失败，改为重跑: %s", exc)
            marker = None
        if marker:
            stat["skipped"] = True
            return stat

    for collection in LEGACY_BATCH_BACKFILL:
        coll = db[collection]
        try:
            res = await coll.update_many(
                {"batch_id": None}, {"$set": {"batch_id": LEGACY_BATCH_ID}}
            )
            stat["collections"] += 1
            stat["modified"] += int(getattr(res, "modified_count", 0) or 0)
        except Exception as exc:
            logger.warning(
                "[index_bootstrap] %s 补齐 batch_id 失败（下次启动重试）: %s", collection, exc
            )
            stat["failed"].append(collection)

    if stat["failed"]:
        return stat

    try:
        await registry.update_one(
            {"_id": _BACKFILL_MARKER_ID},
            {
                "$set": {
                    "purpose": "monitor batch_id legacy backfill",
                    "batch_id_value": LEGACY_BATCH_ID,
                    "collections": list(LEGACY_BATCH_BACKFILL),
                    "modified": stat["modified"],
                    "applied_at": datetime.now(),
                }
            },
            upsert=True,
        )
    except Exception as exc:  # 标记写失败不影响本次结果，下次启动重跑（幂等）
        logger.warning("[index_bootstrap] 写入 batch_id 补齐标记失败: %s", exc)

    if stat["modified"]:
        logger.info(
            "[index_bootstrap] 存量 batch_id 补齐完成: 集合=%s 改写文档=%s",
            stat["collections"], stat["modified"],
        )
    return stat


async def drop_legacy_indexes(db: Any) -> Dict[str, Any]:
    """删除 :data:`LEGACY_INDEX_DROPS` 声明的旧索引.

    必须在新索引建完之后调用。删除前比对「键签名 + 唯一性」，对不上就不动：
    旧索引名可能是 pymongo 默认生成的，也可能被人工改过，按名字删有误删风险。

    Returns:
        ``{"dropped": [...], "skipped": n, "failed": [...]}``。
    """
    stat: Dict[str, Any] = {"dropped": [], "skipped": 0, "failed": []}
    for drop in LEGACY_INDEX_DROPS:
        coll = db[drop.collection]
        try:
            existing = await coll.list_indexes().to_list(length=None)
        except Exception as exc:
            logger.warning("[index_bootstrap] %s 读取索引清单失败: %s", drop.collection, exc)
            stat["failed"].append(drop.collection)
            continue

        target: Optional[str] = None
        for idx in existing or []:
            try:
                if _key_signature(idx.get("key")) != drop.keys:
                    continue
                if bool(idx.get("unique", False)) != bool(drop.unique):
                    continue
                target = str(idx.get("name"))
                break
            except Exception:
                continue

        if target is None:
            stat["skipped"] += 1
            continue

        try:
            await coll.drop_index(target)
            stat["dropped"].append(f"{drop.collection}.{target}")
            logger.info(
                "[index_bootstrap] 删除废弃索引 %s.%s：%s",
                drop.collection, target, drop.reason,
            )
        except Exception as exc:
            logger.warning(
                "[index_bootstrap] 删除废弃索引失败 %s.%s: %s", drop.collection, target, exc
            )
            stat["failed"].append(f"{drop.collection}.{target}")
    return stat


async def ensure_all_indexes(only_missing: bool = True) -> Dict[str, Any]:
    """按声明表补齐全部索引.

    执行顺序固定：补存量 ``batch_id`` → 建缺失索引 → 删废弃索引。

    Args:
        only_missing: True（默认）仅建缺失项；False 时对已存在同键索引也执行
            ``create_index``（Mongo 幂等，仅用于脚本核对选项一致性）。

    Returns:
        ``{"collections": n, "created": n, "skipped": n, "warned": n,
        "backfilled": n, "dropped": [...]}``；
        数据库未连接或整体失败时返回空结果并记 warning，不抛错。
    """
    global _READY
    if _READY and only_missing:
        return {
            "collections": 0, "created": 0, "skipped": 0, "warned": 0,
            "backfilled": 0, "dropped": [], "cached": True,
        }

    db = Database.get_database()
    if db is None:
        logger.warning("[index_bootstrap] 数据库未连接，跳过索引引导")
        return {
            "collections": 0, "created": 0, "skipped": 0, "warned": 0,
            "backfilled": 0, "dropped": [],
        }

    # Step 1：存量文档补 batch_id（必须先于唯一索引创建）
    try:
        backfill = await backfill_legacy_batch_ids(db, force=not only_missing)
    except Exception as exc:
        logger.warning("[index_bootstrap] 存量 batch_id 补齐异常（不阻断启动）: %s", exc)
        backfill = {"modified": 0, "failed": ["<unexpected>"]}

    total = {
        "collections": 0, "created": 0, "skipped": 0, "warned": 0,
        "backfilled": int(backfill.get("modified", 0) or 0), "dropped": [],
    }
    for collection, specs in specs_by_collection().items():
        total["collections"] += 1
        stat = await _ensure_collection(db, collection, specs, only_missing)
        for key in ("created", "skipped", "warned"):
            total[key] += stat[key]

    # Step 3：删废弃索引（必须晚于新索引创建，否则中间态无唯一约束）
    if not backfill.get("failed"):
        try:
            dropped = await drop_legacy_indexes(db)
            total["dropped"] = dropped.get("dropped", [])
            total["warned"] += len(dropped.get("failed", []))
        except Exception as exc:
            logger.warning("[index_bootstrap] 删除废弃索引异常（不阻断启动）: %s", exc)
    else:
        logger.warning(
            "[index_bootstrap] 存量 batch_id 未全部补齐（%s），本次不删废弃索引",
            ",".join(backfill.get("failed", [])),
        )

    if only_missing:
        _READY = True
    logger.info(
        "[index_bootstrap] 索引引导完成: 集合=%s 新建=%s 已存在=%s 告警=%s 补批次号=%s 删旧索引=%s",
        total["collections"], total["created"], total["skipped"], total["warned"],
        total["backfilled"], len(total["dropped"]),
    )
    return total


async def index_report() -> Dict[str, List[Optional[str]]]:
    """返回声明与实际索引清单的差集（脚本核对用，不建索引）."""
    db = Database.get_database()
    report: Dict[str, List[Optional[str]]] = {}
    if db is None:
        return report
    for collection, specs in specs_by_collection().items():
        try:
            existing = await db[collection].list_indexes().to_list(length=None)
        except Exception:
            existing = []
        have = {_key_signature(idx.get("key")) for idx in existing or []}
        report[collection] = [s.index_name for s in specs if s.keys not in have]
    return report
