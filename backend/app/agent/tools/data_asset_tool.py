"""
数据资产管理工具

让 AI Agent 通过对话管理 API 数据资产表、维护本地表、执行取数入库。
支持操作：list, detail, create, update, sync, refresh, query_data, import_data。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.config.database import Database
from app.models.api_data_asset import ApiDataAssetCreate, ApiDataAssetUpdate
from app.services.api_data_asset_service import ApiDataAssetService

# 模块级单例
_service = ApiDataAssetService()


def _serialize_doc(doc: Any) -> Any:
    """递归序列化 MongoDB 文档，将 ObjectId -> str, datetime -> isoformat"""
    if isinstance(doc, dict):
        return {k: _serialize_doc(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [_serialize_doc(item) for item in doc]
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc


class DataAssetTool(BaseTool):
    """数据资产管理工具"""

    name = "manage_data_assets"
    description = (
        "管理API数据资产表：查询、创建、更新、同步、取数入库等操作。"
        "用于维护系统已接入的数据源元信息和触发数据同步。"
    )
    category = "data"
    tags = ["数据资产", "数据管理", "同步", "导入"]

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list", "detail", "create", "update",
                    "sync", "refresh", "query_data", "import_data",
                ],
                "description": "操作类型",
            },
            "asset_id": {
                "type": "string",
                "description": "数据资产ID（detail/update/sync/refresh/query_data/import_data 操作必填）",
            },
            "filters": {
                "type": "object",
                "description": "list操作的筛选条件：asset_type, status, tags, keyword",
                "properties": {
                    "asset_type": {"type": "string"},
                    "status": {"type": "string"},
                    "tags": {"type": "string"},
                    "keyword": {"type": "string"},
                },
            },
            "data": {
                "type": "object",
                "description": "create/update操作的数据payload",
            },
            "query": {
                "type": "object",
                "description": "query_data操作的查询条件",
                "properties": {
                    "filter": {"type": "object", "description": "MongoDB过滤条件"},
                    "limit": {"type": "integer", "description": "返回记录数限制，默认10"},
                    "sort": {"type": "object", "description": "排序条件"},
                },
            },
            "records": {
                "type": "array",
                "description": "import_data操作的记录列表",
                "items": {"type": "object"},
            },
        },
        "required": ["action"],
    }

    # ─── 需要 asset_id 的操作 ─────────────────────────────────────────────────
    _ACTIONS_REQUIRE_ASSET_ID = {"detail", "update", "sync", "refresh", "query_data", "import_data"}

    async def execute(self, **kwargs: Any) -> dict:
        """执行数据资产管理操作"""
        action: str = kwargs.get("action", "")
        if not action:
            return ToolResult.error("缺少必要参数: action")

        # 需要 asset_id 的操作做统一校验
        asset_id: str = kwargs.get("asset_id", "")
        if action in self._ACTIONS_REQUIRE_ASSET_ID and not asset_id:
            return ToolResult.error(f"操作 '{action}' 需要提供 asset_id 参数")

        try:
            if action == "list":
                result = await self._handle_list(kwargs)
            elif action == "detail":
                result = await self._handle_detail(asset_id)
            elif action == "create":
                result = await self._handle_create(kwargs)
            elif action == "update":
                result = await self._handle_update(asset_id, kwargs)
            elif action == "sync":
                result = await self._handle_sync(asset_id)
            elif action == "refresh":
                result = await self._handle_refresh(asset_id)
            elif action == "query_data":
                result = await self._handle_query_data(asset_id, kwargs)
            elif action == "import_data":
                result = await self._handle_import_data(asset_id, kwargs)
            else:
                return ToolResult.error(
                    f"不支持的操作: {action}，可选: list/detail/create/update/sync/refresh/query_data/import_data"
                )
        except Exception as e:
            logger.exception("[DataAssetTool] 操作失败 action={}: {}", action, e)
            return ToolResult.error(f"操作失败: {e}")

        # 统一附加血缘
        if not (isinstance(result, dict) and result.get("success")):
            return result
        if "_lineage_meta" in result:
            return result
        return self.attach_lineage(
            result,
            tables=["data_assets"],
            domains=["meta"],
            fields={"data_assets": ["asset_id", "name", "type", "status"]},
            records_returned=result.get("metadata", {}).get("record_count", 0),
            query_operation=f"manage_data_assets:{action}",
            asset_id=asset_id or None,
        )

    # ─── list ─────────────────────────────────────────────────────────────────

    async def _handle_list(self, kwargs: dict) -> dict:
        """查询数据资产列表"""
        filters = kwargs.get("filters") or {}
        result = await _service.list_assets(filters=filters)
        items = _serialize_doc(result.get("items", []))
        total = result.get("total", 0)

        return ToolResult.success(
            data={"items": items, "total": total, "page": result.get("page", 1)},
            summary=f"查询到 {total} 条数据资产记录，当前返回 {len(items)} 条",
            record_count=len(items),
            data_shape="table",
        )

    # ─── detail ───────────────────────────────────────────────────────────────

    async def _handle_detail(self, asset_id: str) -> dict:
        """获取单个资产详情"""
        doc = await _service.get_asset(asset_id)
        if not doc:
            return ToolResult.error(f"资产不存在: {asset_id}")

        return ToolResult.success(
            data=_serialize_doc(doc),
            summary=f"资产 '{doc.get('name', asset_id)}' 详情",
            record_count=1,
            data_shape="detail",
        )

    # ─── create ───────────────────────────────────────────────────────────────

    async def _handle_create(self, kwargs: dict) -> dict:
        """创建新数据资产"""
        data = kwargs.get("data")
        if not data or not isinstance(data, dict):
            return ToolResult.error("create 操作需要提供 data 参数（包含 name, asset_type, target_collection 等字段）")

        # 校验必填字段
        required_fields = ["name", "asset_type", "target_collection"]
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            return ToolResult.error(f"create 缺少必填字段: {', '.join(missing)}")

        try:
            create_model = ApiDataAssetCreate(**data)
        except Exception as e:
            return ToolResult.error(f"参数校验失败: {e}")

        doc = await _service.create_asset(create_model)
        return ToolResult.success(
            data=_serialize_doc(doc),
            summary=f"成功创建数据资产 '{doc.get('name')}' (ID: {doc.get('asset_id')})",
            record_count=1,
            data_shape="detail",
        )

    # ─── update ───────────────────────────────────────────────────────────────

    async def _handle_update(self, asset_id: str, kwargs: dict) -> dict:
        """更新数据资产"""
        data = kwargs.get("data")
        if not data or not isinstance(data, dict):
            return ToolResult.error("update 操作需要提供 data 参数（包含要更新的字段）")

        try:
            update_model = ApiDataAssetUpdate(**data)
        except Exception as e:
            return ToolResult.error(f"参数校验失败: {e}")

        doc = await _service.update_asset(asset_id, update_model)
        if doc is None:
            return ToolResult.error(f"资产不存在: {asset_id}")

        return ToolResult.success(
            data=_serialize_doc(doc),
            summary=f"成功更新数据资产 '{doc.get('name')}' (ID: {asset_id})",
            record_count=1,
            data_shape="detail",
        )

    # ─── sync ─────────────────────────────────────────────────────────────────

    async def _handle_sync(self, asset_id: str) -> dict:
        """触发数据同步"""
        result = await _service.sync_asset(asset_id)

        if result.get("status") == "error":
            return ToolResult.error(result.get("message", "同步失败"))

        sync_status = result.get("status", "unknown")
        sync_count = result.get("sync_count", 0)
        summary = f"同步完成，状态: {sync_status}，同步记录数: {sync_count}"

        return ToolResult.success(
            data=_serialize_doc(result),
            summary=summary,
            record_count=sync_count,
            data_shape="detail",
        )

    # ─── refresh ──────────────────────────────────────────────────────────────

    async def _handle_refresh(self, asset_id: str) -> dict:
        """刷新资产统计信息"""
        result = await _service.refresh_stats(asset_id)

        if result.get("status") == "error":
            return ToolResult.error(result.get("message", "刷新失败"))

        total = result.get("total_records", 0)
        date_start = result.get("date_range_start", "N/A")
        date_end = result.get("date_range_end", "N/A")
        summary = f"统计刷新完成：总记录数 {total}，日期范围 {date_start} ~ {date_end}"

        return ToolResult.success(
            data=result,
            summary=summary,
            record_count=1,
            data_shape="detail",
        )

    # ─── query_data ───────────────────────────────────────────────────────────

    async def _handle_query_data(self, asset_id: str, kwargs: dict) -> dict:
        """查询资产对应集合的数据"""
        # 获取资产信息确定目标集合
        asset = await _service.get_asset(asset_id)
        if not asset:
            return ToolResult.error(f"资产不存在: {asset_id}")

        target_collection = asset.get("target_collection")
        if not target_collection:
            return ToolResult.error(f"资产 '{asset.get('name')}' 未配置 target_collection")

        query_params = kwargs.get("query") or {}
        mongo_filter = query_params.get("filter") or {}
        limit = query_params.get("limit", 10)
        sort_spec = query_params.get("sort") or {}

        try:
            limit = int(limit)
        except (ValueError, TypeError):
            limit = 10
        # 限制最大返回量，防止内存溢出
        limit = min(limit, 500)

        db = Database.get_database()
        col = db[target_collection]

        # 构建排序
        sort_list = None
        if sort_spec and isinstance(sort_spec, dict):
            from pymongo import ASCENDING, DESCENDING
            sort_list = [
                (k, DESCENDING if v == -1 or str(v).lower() == "desc" else ASCENDING)
                for k, v in sort_spec.items()
            ]

        cursor = col.find(mongo_filter).limit(limit)
        if sort_list:
            cursor = cursor.sort(sort_list)

        records = [_serialize_doc(doc) async for doc in cursor]

        return ToolResult.success(
            data={"records": records, "collection": target_collection, "count": len(records)},
            summary=f"从集合 '{target_collection}' 查询到 {len(records)} 条记录",
            record_count=len(records),
            data_shape="table",
        )

    # ─── import_data ──────────────────────────────────────────────────────────

    async def _handle_import_data(self, asset_id: str, kwargs: dict) -> dict:
        """批量导入数据到资产对应集合"""
        # 获取资产信息
        asset = await _service.get_asset(asset_id)
        if not asset:
            return ToolResult.error(f"资产不存在: {asset_id}")

        # 验证资产状态
        if asset.get("status") != "active":
            return ToolResult.error(
                f"资产 '{asset.get('name')}' 状态为 '{asset.get('status')}'，仅 active 状态的资产允许导入数据"
            )

        target_collection = asset.get("target_collection")
        if not target_collection:
            return ToolResult.error(f"资产 '{asset.get('name')}' 未配置 target_collection")

        records = kwargs.get("records")
        if not records or not isinstance(records, list):
            return ToolResult.error("import_data 操作需要提供 records 参数（非空数组）")

        # 过滤无效记录
        valid_records = [r for r in records if isinstance(r, dict) and r]
        if not valid_records:
            return ToolResult.error("records 中没有有效的记录（需要非空的 dict 对象）")

        db = Database.get_database()
        col = db[target_collection]
        primary_key = asset.get("primary_key") or []
        now = datetime.utcnow()
        imported_at = now.isoformat()

        inserted = 0
        upserted = 0

        for record in valid_records:
            record["_imported_at"] = imported_at
            if primary_key and all(record.get(k) for k in primary_key):
                filter_doc = {k: record[k] for k in primary_key}
                result = await col.update_one(filter_doc, {"$set": record}, upsert=True)
                if result.upserted_id:
                    inserted += 1
                else:
                    upserted += 1
            else:
                await col.insert_one(record)
                inserted += 1

        # 更新资产的同步统计
        total_records = await col.count_documents({})
        await _service._coll().update_one(
            {"asset_id": asset_id},
            {"$set": {
                "last_sync_at": now.isoformat(),
                "last_sync_status": "success",
                "last_sync_count": len(valid_records),
                "total_records": total_records,
                "updated_at": now.isoformat(),
            }},
        )

        summary = f"导入完成：新增 {inserted} 条，更新 {upserted} 条，集合 '{target_collection}' 总计 {total_records} 条"
        logger.info("[DataAssetTool] import_data asset_id={} inserted={} upserted={}", asset_id, inserted, upserted)

        return ToolResult.success(
            data={
                "inserted": inserted,
                "upserted": upserted,
                "total_records": total_records,
                "collection": target_collection,
            },
            summary=summary,
            record_count=inserted + upserted,
            data_shape="detail",
        )


