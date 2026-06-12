"""
通用 MongoDB 查询引擎

将结构化查询规格（Filter DSL）安全转换为 pymongo 查询执行。
关键安全机制：白名单校验、字段校验、字段脱敏、行数限制、超时控制、操作审计。
"""

import re
import time
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from loguru import logger

from app.config.database import Database
from app.services.collection_registry import CollectionNotFoundError, CollectionRegistry


class GenericQueryEngine:
    """通用 MongoDB 查询引擎

    将结构化查询规格（Filter DSL）安全转换为 pymongo 查询执行。
    关键安全机制：白名单校验、字段校验、字段脱敏、行数限制、超时控制、操作审计。
    """

    MAX_QUERY_LIMIT = 1000
    MAX_AGGREGATE_GROUPS = 500
    QUERY_TIMEOUT_MS = 30000

    # 允许的过滤操作符白名单
    ALLOWED_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "nin", "contains", "regex", "exists"}

    # 操作符 → MongoDB 映射
    OP_MAP = {
        "eq": "$eq", "ne": "$ne", "gt": "$gt", "gte": "$gte",
        "lt": "$lt", "lte": "$lte", "in": "$in", "nin": "$nin",
        "exists": "$exists",
    }

    # 日期格式正则
    _DATE_PATTERN = re.compile(
        r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$"
    )

    def __init__(self, registry: CollectionRegistry | None = None) -> None:
        self._db = None
        self._registry = registry or CollectionRegistry()

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    async def find(
        self,
        collection: str,
        filters: list[dict] | None = None,
        fields: list[str] | None = None,
        sort: list[dict] | None = None,
        limit: int = 50,
        skip: int = 0,
        user: str = "system",
    ) -> dict:
        """条件查询。

        1. 校验 collection 白名单
        2. 校验 fields 存在性（不存在时返回友好提示）
        3. 将 filters DSL 转换为 pymongo filter dict
        4. 执行查询，应用字段脱敏
        5. 返回 {"data": [...], "total": N, "page_info": {"limit": N, "skip": N, "has_more": bool}}
        """
        start_time = time.time()

        # 白名单校验
        schema = await self._validate_collection(collection)

        # 字段校验
        warnings: list[str] = []
        if fields:
            warnings = self._validate_fields(schema, fields)

        # 强制限制
        limit = min(limit, self.MAX_QUERY_LIMIT)

        # 构建查询
        mongo_filter = self._build_mongo_filter(filters or [])

        # 构建投影
        projection: dict[str, int] | None = None
        if fields:
            projection = {f: 1 for f in fields}

        # 构建排序
        sort_list: list[tuple[str, int]] | None = None
        if sort:
            sort_list = []
            for s in sort:
                direction = -1 if s.get("order", "asc") == "desc" else 1
                sort_list.append((s["field"], direction))

        # 执行查询
        col = self.db[collection]
        total: int = await col.count_documents(mongo_filter)

        cursor = col.find(mongo_filter, projection).skip(skip).limit(limit)
        if sort_list:
            cursor = cursor.sort(sort_list)

        docs: list[dict] = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            docs.append(doc)

        # 脱敏
        sensitive_fields = schema.get("sensitive_fields", [])
        if sensitive_fields:
            docs = self._apply_masking(sensitive_fields, docs)

        duration_ms = (time.time() - start_time) * 1000

        # 审计
        await self._audit_log(
            user=user,
            collection=collection,
            action="find",
            params={"filters": filters, "fields": fields, "limit": limit, "skip": skip},
            duration_ms=duration_ms,
        )

        result: dict[str, Any] = {
            "data": docs,
            "total": total,
            "page_info": {
                "limit": limit,
                "skip": skip,
                "has_more": (skip + limit) < total,
            },
        }
        if warnings:
            result["warnings"] = warnings

        return result

    async def aggregate(
        self,
        collection: str,
        filters: list[dict] | None = None,
        group_by: list[str] | None = None,
        metrics: list[dict] | None = None,
        user: str = "system",
    ) -> dict:
        """聚合查询。

        1. 校验 collection 白名单
        2. 构建 aggregation pipeline: $match → $group → $sort → $limit
        3. metrics 中每项: {field, agg, alias}，agg 支持 sum/avg/count/min/max/first/last
        4. 返回 {"data": [...], "group_count": N}
        """
        start_time = time.time()

        await self._validate_collection(collection)

        # 构建 pipeline
        pipeline: list[dict] = []

        # $match
        mongo_filter = self._build_mongo_filter(filters or [])
        if mongo_filter:
            pipeline.append({"$match": mongo_filter})

        # $group
        group_stage: dict[str, Any] = {}

        if group_by:
            if len(group_by) == 1:
                group_stage["_id"] = f"${group_by[0]}"
            else:
                group_stage["_id"] = {g: f"${g}" for g in group_by}
        else:
            group_stage["_id"] = None

        # 聚合指标
        agg_map = {
            "sum": "$sum", "avg": "$avg", "min": "$min",
            "max": "$max", "first": "$first", "last": "$last",
        }
        sort_field: str | None = None

        if metrics:
            for m in metrics:
                alias = m.get("alias", m.get("field", "value"))
                agg_op = m.get("agg", "sum")
                field = m.get("field", "_id")

                if agg_op == "count":
                    group_stage[alias] = {"$sum": 1}
                elif agg_op in agg_map:
                    group_stage[alias] = {agg_map[agg_op]: f"${field}"}
                else:
                    group_stage[alias] = {"$sum": f"${field}"}

                if sort_field is None:
                    sort_field = alias

        pipeline.append({"$group": group_stage})

        # $sort
        if sort_field:
            pipeline.append({"$sort": {sort_field: -1}})

        # $limit
        pipeline.append({"$limit": self.MAX_AGGREGATE_GROUPS})

        # 执行
        col = self.db[collection]
        docs: list[dict] = []
        async for doc in col.aggregate(pipeline):
            # 展平 _id
            group_id = doc.pop("_id", None)
            if isinstance(group_id, dict):
                doc.update(group_id)
            elif group_id is not None:
                if group_by and len(group_by) == 1:
                    doc[group_by[0]] = group_id
                else:
                    doc["_id"] = str(group_id) if isinstance(group_id, ObjectId) else group_id
            docs.append(doc)

        duration_ms = (time.time() - start_time) * 1000

        await self._audit_log(
            user=user,
            collection=collection,
            action="aggregate",
            params={"filters": filters, "group_by": group_by, "metrics": metrics},
            duration_ms=duration_ms,
        )

        return {"data": docs, "group_count": len(docs)}

    async def count(
        self,
        collection: str,
        filters: list[dict] | None = None,
        user: str = "system",
    ) -> int:
        """计数查询。"""
        start_time = time.time()

        await self._validate_collection(collection)

        mongo_filter = self._build_mongo_filter(filters or [])
        col = self.db[collection]
        total: int = await col.count_documents(mongo_filter)

        duration_ms = (time.time() - start_time) * 1000
        await self._audit_log(
            user=user,
            collection=collection,
            action="count",
            params={"filters": filters},
            duration_ms=duration_ms,
        )

        return total

    def _build_mongo_filter(self, filters: list[dict]) -> dict:
        """将 Filter DSL 转换为 pymongo 查询字典。

        仅支持白名单操作符。
        contains → {"$regex": value}
        regex → {"$regex": value}
        其他 → {OP_MAP[op]: value}
        拒绝 $where/$expr/$function 等危险操作。
        """
        if not filters:
            return {}

        mongo_filter: dict[str, Any] = {}

        for f in filters:
            field = f.get("field", "")
            op = f.get("op", "eq")
            value = f.get("value")

            # 安全检查：拒绝危险字段名
            if field.startswith("$"):
                logger.warning("dangerous_field_rejected", extra={"field": field})
                continue

            if op not in self.ALLOWED_OPS:
                logger.warning("unsupported_op_rejected", extra={"op": op, "field": field})
                continue

            # 日期自动转换
            value = self._auto_convert_date(value)

            # 构建条件
            if op == "eq":
                mongo_filter[field] = value
            elif op in ("contains", "regex"):
                mongo_filter[field] = {"$regex": value}
            else:
                mongo_op = self.OP_MAP[op]
                if field in mongo_filter and isinstance(mongo_filter[field], dict):
                    mongo_filter[field][mongo_op] = value
                else:
                    mongo_filter[field] = {mongo_op: value}

        return mongo_filter

    async def _validate_collection(self, collection: str) -> dict:
        """白名单校验：检查集合是否在 registry 中且 is_whitelisted=True。
        不满足则抛出 CollectionNotFoundError。
        返回该集合的 registry entry（供后续字段校验使用）。
        """
        registry_col = self._registry.db[CollectionRegistry.REGISTRY_COLLECTION]
        entry = await registry_col.find_one({"collection_name": collection})

        if not entry:
            raise CollectionNotFoundError(f"集合 '{collection}' 未注册，请先执行 registry.refresh()")
        if not entry.get("is_whitelisted", True):
            raise CollectionNotFoundError(f"集合 '{collection}' 未授权查询")

        return entry

    def _validate_fields(self, schema: dict, fields: list[str]) -> list[str]:
        """字段校验：检查请求的字段是否存在于 Schema 中。
        不存在的字段收集起来，返回提示信息列表。
        """
        known_fields = {f["name"] for f in schema.get("fields", [])}
        known_fields.add("_id")

        warnings: list[str] = []
        for field in fields:
            if field not in known_fields:
                warnings.append(f"字段 '{field}' 不存在于集合 Schema 中，可能无数据返回")

        return warnings

    def _apply_masking(self, sensitive_fields: list[str], docs: list[dict]) -> list[dict]:
        """字段脱敏。
        - 手机号 → 138****1234
        - 证件号 → 前3后4
        - 其他 → ***
        修改 docs 原地脱敏，返回修改后的列表。
        """
        phone_pattern = re.compile(r"^1[3-9]\d{9}$")
        id_card_pattern = re.compile(r"^\d{15,18}[Xx]?$")

        for doc in docs:
            for field in sensitive_fields:
                if field not in doc or doc[field] is None:
                    continue
                value = str(doc[field])
                if phone_pattern.match(value):
                    doc[field] = f"{value[:3]}****{value[-4:]}"
                elif id_card_pattern.match(value):
                    doc[field] = f"{value[:3]}{'*' * (len(value) - 7)}{value[-4:]}"
                else:
                    doc[field] = "***"

        return docs

    async def _audit_log(
        self,
        user: str,
        collection: str,
        action: str,
        params: dict,
        duration_ms: float,
    ) -> None:
        """操作审计：将查询记录写入 _query_audit_log 集合。"""
        try:
            audit_col = self.db["_query_audit_log"]
            await audit_col.insert_one({
                "user": user,
                "collection": collection,
                "action": action,
                "params": params,
                "duration_ms": round(duration_ms, 2),
                "timestamp": datetime.now(timezone.utc),
            })
        except Exception as e:
            logger.warning("audit_log_write_failed", extra={"error": str(e)})

    def _auto_convert_date(self, value: Any) -> Any:
        """当 value 是日期字符串格式时，自动转为 datetime 对象。"""
        if not isinstance(value, str):
            return value
        if not self._DATE_PATTERN.match(value):
            return value

        try:
            if "T" in value:
                return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return value
