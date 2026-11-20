"""监控操作指令服务

管理 monitor_operations 集合：策略维度的操作指令（月度调仓/波动率重置/主观调仓）。

生命周期：
- 信号日写 pending（目标仓位/操作建议预展示）
- 执行日落地转 executed（回填执行前权重）
- 主观比例优化时原指令转 superseded，主观指令携带 linked_operation_id

批次维度（``batch_id``）约定：
- **写入侧**：``batch_id`` 为空一律归一到 ``LEGACY_BATCH_ID``，指令永远有所属批次，
  不产生「无主」文档；业务幂等键因此从 ``{monitor_id, strategy_key, op_type,
  signal_date, source}`` 扩展为再叠加 ``batch_id``，重跑新批次不会覆盖旧批次的指令。
- **读取侧**：``batch_id=None`` 表示**不过滤**（跨批次，兼容既有调用方与历史查询），
  传入具体批次号（含 ``"legacy"``）才做过滤。展示端点必须先经
  ``monitor_batch_service.resolve_batch_id`` 解析出批次号再传入。
- **备注（remarks）刻意不分批次**：用户为某个信号日写的说明应跨重跑保留，
  因此备注业务键不含 ``batch_id``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from loguru import logger

from app.config.collections import COL_MONITOR_OPERATIONS, COL_MONITOR_OPERATION_REMARKS
from app.config.database import Database
from app.models.monitor import (
    LEGACY_BATCH_ID,
    MonitorOperation,
    OperationStatus,
    OperationType,
)


# 补充说明的挂靠业务键字段：组合通道全量重建后 _id 会变，但业务键稳定。
# 不含 batch_id：备注跨批次保留，重跑不丢用户手写的说明。
_REMARK_KEY_FIELDS = ("monitor_id", "strategy_key", "op_type", "signal_date", "source")


def _write_batch_id(batch_id: Optional[str]) -> str:
    """写入侧批次号归一：空值落 ``legacy``，保证指令永远有所属批次。"""
    text = str(batch_id or "").strip()
    return text or LEGACY_BATCH_ID


def _remark_key(doc: Dict[str, Any]) -> tuple:
    """指令业务键（元组形式，用于备注集合与 ops 的匹配）。"""
    return (
        str(doc.get("monitor_id") or ""),
        str(doc.get("strategy_key") or ""),
        str(doc.get("op_type") or ""),
        str(doc.get("signal_date") or "")[:10],
        str(doc.get("source") or "auto"),
    )


class MonitorOperationService:
    """监控操作指令 CRUD 服务"""

    def __init__(self):
        self.db = Database.get_database()
        self.collection = self.db[COL_MONITOR_OPERATIONS]
        self.remarks_collection = self.db[COL_MONITOR_OPERATION_REMARKS]
        self._indexes_ready = False
        self._remark_indexes_ready = False

    async def ensure_indexes(self) -> None:
        """创建查询所需索引（幂等，仅首次调用生效）。"""
        if self._indexes_ready:
            return
        await self.collection.create_index([("monitor_id", 1), ("status", 1)])
        await self.collection.create_index([("monitor_id", 1), ("signal_date", -1)])
        await self.collection.create_index([("monitor_id", 1), ("strategy_key", 1)])
        await self.collection.create_index(
            [("monitor_id", 1), ("batch_id", 1), ("signal_date", -1)]
        )
        self._indexes_ready = True

    async def ensure_remark_indexes(self) -> None:
        """创建备注集合唯一索引（业务键维度，幂等）。"""
        if self._remark_indexes_ready:
            return
        await self.remarks_collection.create_index(
            [(f, 1) for f in _REMARK_KEY_FIELDS], unique=True
        )
        self._remark_indexes_ready = True

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    async def upsert_auto_operation(
        self,
        monitor_id: str,
        strategy_key: str,
        op_type: str,
        signal_date: str,
        execute_date: str,
        target_weights: Dict[str, float],
        strategy_name: str = "",
        suggestion: Optional[Dict[str, Any]] = None,
        batch_id: Optional[str] = None,
    ) -> str:
        """写入/更新系统信号指令（幂等：同批次+监控实例+策略+类型+信号日视为同一指令）。

        重复推演（run/init 重跑）时仅刷新目标权重与执行日，不产生重复记录。

        Args:
            monitor_id: 监控实例 ID
            strategy_key: 策略维度键
            op_type: monthly_rebalance / vol_reset
            signal_date: 信号生成日期 YYYY-MM-DD
            execute_date: 执行日期 YYYY-MM-DD
            target_weights: 目标权重（小数形式）
            strategy_name: 策略展示名
            suggestion: 操作建议明细（波动率重置的波动/阈值/杠杆等）
            batch_id: 所属运行批次；空值归一为 ``legacy``

        Returns:
            指令 ID（str）
        """
        await self.ensure_indexes()
        filter_doc = {
            "monitor_id": monitor_id,
            "batch_id": _write_batch_id(batch_id),
            "strategy_key": strategy_key,
            "op_type": op_type,
            "signal_date": signal_date,
            "source": "auto",
        }
        set_doc = {
            "execute_date": execute_date,
            "target_weights": _clean_weights(target_weights),
            "strategy_name": strategy_name,
            "suggestion": suggestion or {},
            "updated_at": datetime.now(),
        }
        result = await self.collection.update_one(
            filter_doc,
            {"$set": set_doc, "$setOnInsert": {
                "status": OperationStatus.PENDING.value,
                "prev_weights": {},
                "linked_operation_id": None,
                "override_ref": None,
                "created_at": datetime.now(),
            }},
            upsert=True,
        )
        if result.upserted_id:
            return str(result.upserted_id)
        existing = await self.collection.find_one(filter_doc, {"_id": 1})
        return str(existing["_id"]) if existing else ""

    async def bulk_upsert_executed_operations(
        self,
        monitor_id: str,
        ops: List[Dict[str, Any]],
        batch_id: Optional[str] = None,
    ) -> int:
        """批量 upsert 已执行指令（组合管线全量重建场景）。

        ops 每项：{strategy_key, strategy_name, op_type, signal_date,
        execute_date, target_weights, prev_weights}；组合层指令可额外携带
        strategy_weights/prev_strategy_weights/strategy_breakdown/prev_strategy_breakdown
        （两级拆解及上一调仓日同级快照）。
        业务键 = batch_id + monitor_id + strategy_key + op_type + signal_date + source:auto，
        状态一律写 executed（管线全量重跑时指令均已落地）。

        Returns:
            写入/更新的指令数
        """
        if not ops:
            return 0
        await self.ensure_indexes()
        from pymongo import UpdateOne

        now = datetime.now()
        batch = _write_batch_id(batch_id)
        mongo_ops = []
        for op in ops:
            filter_doc = {
                "monitor_id": monitor_id,
                "batch_id": batch,
                "strategy_key": str(op.get("strategy_key") or "portfolio"),
                "op_type": op["op_type"],
                "signal_date": op["signal_date"],
                "source": "auto",
            }
            set_doc = {
                "execute_date": op["execute_date"],
                "target_weights": _clean_weights(op.get("target_weights") or {}),
                "prev_weights": _clean_weights(op.get("prev_weights") or {}),
                "strategy_weights": _clean_weights(op.get("strategy_weights") or {}),
                "prev_strategy_weights": _clean_weights(op.get("prev_strategy_weights") or {}),
                "strategy_breakdown": _clean_breakdown(op.get("strategy_breakdown") or []),
                "prev_strategy_breakdown": _clean_breakdown(
                    op.get("prev_strategy_breakdown") or []
                ),
                "strategy_name": op.get("strategy_name", ""),
                "status": OperationStatus.EXECUTED.value,
                "updated_at": now,
            }
            mongo_ops.append(UpdateOne(
                filter_doc,
                {"$set": set_doc, "$setOnInsert": {
                    "suggestion": {},
                    "linked_operation_id": None,
                    "override_ref": None,
                    "created_at": now,
                }},
                upsert=True,
            ))
        total = 0
        for i in range(0, len(mongo_ops), 1000):
            result = await self.collection.bulk_write(
                mongo_ops[i:i + 1000], ordered=False
            )
            total += result.upserted_count + result.modified_count
        return total

    async def create_subjective_operation(
        self,
        monitor_id: str,
        execute_date: str,
        weights: Dict[str, float],
        override_ref: str,
        strategy_key: Optional[str] = None,
        strategy_name: str = "",
        linked_operation_id: Optional[str] = None,
        description: Optional[str] = None,
        record_executed: bool = False,
        batch_id: Optional[str] = None,
    ) -> str:
        """创建主观调仓指令记录（额外调仓或比例优化）。

        Args:
            monitor_id: 监控实例 ID
            execute_date: 执行日期 YYYY-MM-DD
            weights: 主观目标权重（小数形式）
            override_ref: 关联的 subjective_overrides.override_id
            strategy_key: 策略维度键（默认等于 monitor_id）
            strategy_name: 策略展示名
            linked_operation_id: 挂接的原待执行指令 ID（比例优化模式）
            description: 描述备注
            record_executed: 补录模式，直接写 executed；净值由调用方提交重算任务
            batch_id: 所属运行批次；空值归一为 ``legacy``

        Returns:
            指令 ID（str）
        """
        await self.ensure_indexes()
        op = MonitorOperation(
            monitor_id=monitor_id,
            batch_id=_write_batch_id(batch_id),
            strategy_key=strategy_key or monitor_id,
            strategy_name=strategy_name,
            op_type=OperationType.SUBJECTIVE.value,
            signal_date=execute_date,
            execute_date=execute_date,
            status=(
                OperationStatus.EXECUTED.value if record_executed
                else OperationStatus.PENDING.value
            ),
            target_weights=_clean_weights(weights),
            source="subjective",
            linked_operation_id=linked_operation_id,
            override_ref=override_ref,
            suggestion={"description": description} if description else {},
        )
        result = await self.collection.insert_one(op.to_dict())
        return str(result.inserted_id)

    async def delete_subjective_operation(self, override_ref: str) -> int:
        """按 ``override_ref`` 删除主观指令记录（补录回滚用，返回删除数）。"""
        if not override_ref:
            return 0
        result = await self.collection.delete_many({
            "override_ref": str(override_ref),
            "source": "subjective",
        })
        return int(getattr(result, "deleted_count", 0) or 0)

    async def copy_subjective_for_batch(
        self,
        monitor_id: str,
        source_batch_id: str,
        target_batch_id: str,
        ref_map: Dict[str, str],
    ) -> int:
        """把父批次 ``pending`` 的主观指令记录复制到新批次（方案 A 的操作面板侧）。

        ``subjective_overrides`` 继承时会重新发号，操作指令的 ``override_ref``
        必须跟着换成新号；否则新批次里 :meth:`mark_override_executed` 找不到
        对应文档，主观调仓执行后不会出现在操作面板上。

        只复制 ``pending`` 的主观指令：``executed``/``superseded``/``cancelled``
        随源批次封存，与新批次的自动指令重建（``_seed_monthly_operations``）无关。
        幂等：目标批次已存在同 ``override_ref`` 的文档时跳过。

        Args:
            ref_map: ``{源 override_id: 新 override_id}``

        Returns:
            复制条数
        """
        if not ref_map:
            return 0
        source_batch = _write_batch_id(source_batch_id)
        target_batch = _write_batch_id(target_batch_id)
        if source_batch == target_batch:
            return 0
        await self.ensure_indexes()

        cursor = self.collection.find({
            "monitor_id": monitor_id,
            "batch_id": source_batch,
            "op_type": OperationType.SUBJECTIVE.value,
            "status": OperationStatus.PENDING.value,
            "override_ref": {"$in": list(ref_map.keys())},
        })
        source_docs = [doc async for doc in cursor]
        if not source_docs:
            return 0

        new_refs = [ref_map[str(d.get("override_ref"))] for d in source_docs
                    if str(d.get("override_ref")) in ref_map]
        existed = await self.collection.find({
            "monitor_id": monitor_id,
            "batch_id": target_batch,
            "override_ref": {"$in": new_refs},
        }, projection={"override_ref": 1}).to_list(length=None)
        existed_refs = {str(d.get("override_ref")) for d in existed}

        copied = 0
        for doc in source_docs:
            new_ref = ref_map.get(str(doc.get("override_ref")))
            if not new_ref or new_ref in existed_refs:
                continue
            payload = {k: v for k, v in doc.items() if k != "_id"}
            payload["batch_id"] = target_batch
            payload["override_ref"] = new_ref
            # 挂接的原指令属于源批次，新批次的自动指令会重建，保留旧 ID 会指向不存在的文档
            payload["linked_operation_id"] = None
            payload["created_at"] = datetime.now()
            payload["updated_at"] = datetime.now()
            await self.collection.insert_one(payload)
            existed_refs.add(new_ref)
            copied += 1

        if copied:
            logger.info(
                f"[监控批次] 继承 pending 主观操作指令 {copied} 条: "
                f"monitor={monitor_id}, {source_batch} → {target_batch}"
            )
        return copied

    # ------------------------------------------------------------------
    # 状态流转
    # ------------------------------------------------------------------

    async def mark_executed(
        self,
        monitor_id: str,
        strategy_key: str,
        op_type: str,
        execute_date: str,
        prev_weights: Optional[Dict[str, float]] = None,
        batch_id: Optional[str] = None,
    ) -> bool:
        """执行日落地：将该指令由 pending 转 executed 并回填执行前权重。

        按业务键匹配（信号指令）；未找到时静默返回（历史补算场景）。
        ``batch_id`` 为空时不限批次（兼容存量指令）。
        """
        filter_doc = {
            "monitor_id": monitor_id,
            "strategy_key": strategy_key,
            "op_type": op_type,
            "execute_date": execute_date,
            "source": "auto",
            "status": OperationStatus.PENDING.value,
        }
        if batch_id:
            filter_doc["batch_id"] = str(batch_id)
        result = await self.collection.update_one(
            filter_doc,
            {"$set": {
                "status": OperationStatus.EXECUTED.value,
                "prev_weights": _clean_weights(prev_weights or {}),
                "updated_at": datetime.now(),
            }},
        )
        return result.modified_count > 0

    async def mark_override_executed(
        self, override_ref: str, batch_id: Optional[str] = None
    ) -> None:
        """主观指令执行后，将对应操作指令转 executed。

        ``override_ref`` 已全局唯一（继承时会重新发号），批次过滤只是双保险。
        """
        filter_doc: Dict[str, Any] = {
            "override_ref": override_ref,
            "status": OperationStatus.PENDING.value,
        }
        if batch_id:
            filter_doc["batch_id"] = str(batch_id)
        await self.collection.update_one(
            filter_doc,
            {"$set": {
                "status": OperationStatus.EXECUTED.value,
                "updated_at": datetime.now(),
            }},
        )

    async def supersede(self, operation_id: str, reason: Optional[str] = None) -> bool:
        """比例优化：将原待执行指令标记为 superseded。仅 pending 状态可替代。

        Args:
            operation_id: 被替代的指令 ID
            reason: 替代原因，非空时写入独立备注集合
        """
        if not ObjectId.is_valid(operation_id):
            raise ValueError(f"无效的指令 ID 格式: {operation_id}")
        result = await self.collection.update_one(
            {"_id": ObjectId(operation_id), "status": OperationStatus.PENDING.value},
            {"$set": {
                "status": OperationStatus.SUPERSEDED.value,
                "updated_at": datetime.now(),
            }},
        )
        if result.modified_count > 0 and (reason or "").strip():
            try:
                await self.set_remark(operation_id, reason)
            except Exception as e:
                logger.warning(f"写入替代原因失败（不影响状态流转）: {e}")
        return result.modified_count > 0

    async def unsupersede(self, operation_id: str) -> bool:
        """主观指令取消时恢复原指令为 pending。仅 superseded 状态可恢复。"""
        if not ObjectId.is_valid(operation_id):
            return False
        result = await self.collection.update_one(
            {"_id": ObjectId(operation_id), "status": OperationStatus.SUPERSEDED.value},
            {"$set": {
                "status": OperationStatus.PENDING.value,
                "updated_at": datetime.now(),
            }},
        )
        return result.modified_count > 0

    async def mark_cancelled_by_key(
        self, monitor_id: str, strategy_key: str, op_type: str, signal_date: str,
        reason: Optional[str] = None, batch_id: Optional[str] = None,
    ) -> None:
        """信号失效/冲突跳过时，取消对应待执行指令（幂等）。

        Args:
            reason: 跳过原因，非空时写入独立备注集合（如月度优先覆盖）
            batch_id: 限定批次；为空时不限（兼容存量指令）
        """
        filter_doc = {
            "monitor_id": monitor_id,
            "strategy_key": strategy_key,
            "op_type": op_type,
            "signal_date": signal_date,
            "source": "auto",
            "status": OperationStatus.PENDING.value,
        }
        if batch_id:
            filter_doc["batch_id"] = str(batch_id)
        result = await self.collection.update_one(
            filter_doc,
            {"$set": {
                "status": OperationStatus.CANCELLED.value,
                "updated_at": datetime.now(),
            }},
        )
        if result.modified_count > 0 and (reason or "").strip():
            doc = await self.collection.find_one(
                {k: v for k, v in filter_doc.items() if k != "status"},
                {"_id": 1},
            )
            if doc:
                try:
                    await self.set_remark(str(doc["_id"]), reason)
                except Exception as e:
                    logger.warning(f"写入取消原因失败（不影响状态流转）: {e}")

    # ------------------------------------------------------------------
    # 补充说明（独立集合，按业务键挂靠）
    # ------------------------------------------------------------------

    async def set_remark(self, operation_id: str, remark: Optional[str]) -> str:
        """写入/清除指令补充说明。

        权威数据存于 monitor_operation_remarks，以业务键挂靠，
        组合通道全量重建 ops（_id 变）后备注仍可回填。

        Returns:
            归一化后的备注文本（空串表示已清除）
        """
        if not ObjectId.is_valid(operation_id):
            raise ValueError(f"无效的指令 ID 格式: {operation_id}")
        doc = await self.collection.find_one({'_id': ObjectId(operation_id)})
        if not doc:
            raise ValueError(f"操作指令不存在: {operation_id}")
        await self.ensure_remark_indexes()
        key = dict(zip(_REMARK_KEY_FIELDS, _remark_key(doc)))
        text = (remark or "").strip()
        now = datetime.now()
        if text:
            await self.remarks_collection.update_one(
                key,
                {"$set": {"remark": text, "updated_at": now},
                 "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        else:
            await self.remarks_collection.delete_one(key)
        return text

    async def _attach_remarks(self, docs: List[Dict[str, Any]]) -> None:
        """按业务键批量回填 remark 字段（缺失时为 None）。"""
        if not docs:
            return
        await self.ensure_remark_indexes()
        keys = [dict(zip(_REMARK_KEY_FIELDS, _remark_key(d))) for d in docs]
        remark_map: Dict[tuple, str] = {}
        cursor = self.remarks_collection.find({"$or": keys})
        async for row in cursor:
            remark_map[_remark_key(row)] = row.get("remark")
        for d in docs:
            d["remark"] = remark_map.get(_remark_key(d))

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def get(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 获取指令文档（_id 已序列化为 str）。"""
        if not ObjectId.is_valid(operation_id):
            return None
        doc = await self.collection.find_one({"_id": ObjectId(operation_id)})
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        out = _json_safe(doc)
        await self._attach_remarks([out])
        return out

    async def list_by_monitor(
        self,
        monitor_id: str,
        status: Optional[str] = None,
        strategy_key: Optional[str] = None,
        limit: int = 200,
        batch_id: Optional[str] = None,
        include_subjective_history: bool = False,
    ) -> List[Dict[str, Any]]:
        """按监控实例查询指令列表（信号日倒序），可按状态/策略维度/批次过滤。

        ``batch_id=None`` 表示跨批次（历史查询/存量兼容）。
        ``include_subjective_history=True``：额外带上其他批次已执行的主观指令。
        补录后重算会换批次，已执行的主观调整挂在旧批次，不跨批次读就会从
        面板消失；只带 ``executed``，避免把父批次遗留的 pending 副本重复展示。
        """
        await self.ensure_indexes()
        query: Dict[str, Any] = {"monitor_id": monitor_id}
        if status:
            query["status"] = status
        if strategy_key:
            query["strategy_key"] = strategy_key
        if batch_id:
            if include_subjective_history:
                query["$or"] = [
                    {"batch_id": str(batch_id)},
                    {"source": "subjective", "status": OperationStatus.EXECUTED.value},
                ]
            else:
                query["batch_id"] = str(batch_id)
        cursor = (
            self.collection.find(query)
            .sort([("signal_date", -1), ("created_at", -1)])
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        out = [_json_safe(d) for d in docs]
        await self._attach_remarks(out)
        return out

    async def find_pending(
        self,
        monitor_id: str,
        strategy_key: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """查询某监控实例的待执行指令（执行日升序）。"""
        await self.ensure_indexes()
        query: Dict[str, Any] = {
            "monitor_id": monitor_id,
            "status": OperationStatus.PENDING.value,
        }
        if strategy_key:
            query["strategy_key"] = strategy_key
        if batch_id:
            query["batch_id"] = str(batch_id)
        cursor = self.collection.find(query).sort("execute_date", 1)
        docs = await cursor.to_list(length=100)
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        return [_json_safe(d) for d in docs]

    async def delete_by_monitor(
        self,
        monitor_id: str,
        source: Optional[str] = "auto",
        batch_id: Optional[str] = None,
    ) -> int:
        """删除某监控实例的指令（默认仅自动指令，保留主观指令；返回删除数）。

        **必须传 ``batch_id``**：不传会跳批次全删，把旧批次已封存的指令一并抹除。
        调用方（初始化重建 / 组合全量重建）一律限定在当前批次内。
        """
        query: Dict[str, Any] = {"monitor_id": monitor_id}
        if source:
            query["source"] = source
        if batch_id:
            query["batch_id"] = str(batch_id)
        result = await self.collection.delete_many(query)
        return result.deleted_count


def _clean_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """权重字典清洗：键转 str、值转 float，过滤非法值。"""
    out: Dict[str, float] = {}
    for k, v in (weights or {}).items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _clean_breakdown(breakdown: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """组合层穿透拆解清洗：权重/策略内资产权重数值化，过滤非法条目。"""
    out: List[Dict[str, Any]] = []
    for item in breakdown or []:
        if not isinstance(item, dict):
            continue
        try:
            weight = float(item.get("weight") or 0)
        except (TypeError, ValueError):
            continue
        out.append({
            "strategy_key": str(item.get("strategy_key") or ""),
            "strategy_name": str(item.get("strategy_name") or ""),
            "weight": weight,
            "asset_weights": _clean_weights(item.get("asset_weights") or {}),
        })
    return out


def _json_safe(doc: Dict[str, Any]) -> Dict[str, Any]:
    """文档序列化兜底：datetime 转 ISO 字符串，避免 JSON 序列化报错。"""
    out: Dict[str, Any] = {}
    for k, v in doc.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
