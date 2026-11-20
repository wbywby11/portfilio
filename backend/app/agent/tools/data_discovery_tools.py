"""
M8 数据自适应核心 — query_dataset

元数据驱动的通用数据集查询：任何集合（含新接入的数据）无需改代码即可被 agent 发现与查询。

强制"先认识后使用"：agent 必须先 metadata/preview 确认字段含义，再做 query。

安全边界：
- 只读；内部集合黑名单（_ 前缀 / agent_ / system.）不可查
- 仅等值 + 日期范围过滤（禁止任意聚合管道）
- 单次返回上限 200 行；字段投影必须是已采样字段
"""
from datetime import datetime

from app.agent.tools._helpers import bson_safe
from app.agent.tools.base import BaseTool

# 内部集合黑名单规则（前缀匹配）
_BLACKLIST_PREFIXES = ("_", "agent_", "system.")

MAX_QUERY_ROWS = 200
MAX_PREVIEW_ROWS = 10


def _is_blocked(collection_name: str) -> bool:
    return any(collection_name.startswith(p) for p in _BLACKLIST_PREFIXES)


class QueryDatasetTool(BaseTool):
    """通用数据集查询工具（自适应，新集合零代码接入）"""

    name = "query_dataset"
    description = (
        "查询任意数据集（自适应：新增集合无需任何代码改动即可查询）。"
        "【使用纪律】必须先 action=metadata 了解字段与含义、action=preview 查看样本，"
        "确认字段名后才能 action=query，禁止假设未验证的字段名。\n"
        "action 说明：\n"
        "1) metadata：返回集合描述/标签/字段列表/日期字段与范围/记录数\n"
        "2) preview：采样前 10 条原始记录\n"
        "3) query：等值过滤（filters）+ 日期范围（date_from/date_to）查询，上限 200 行"
    )
    parameters = {
        "type": "object",
        "properties": {
            "dataset": {
                "type": "string",
                "description": "数据集（集合）名称；集合名不确定时先用 query_assets 确认",
            },
            "action": {
                "type": "string",
                "enum": ["metadata", "preview", "query"],
                "description": "操作类型（先 metadata/preview 后 query）",
            },
            "filters": {
                "type": "object",
                "description": "query 模式等值过滤条件 {字段名: 值}，字段名必须来自 metadata 的字段列表",
            },
            "date_from": {
                "type": "string",
                "description": "query 模式日期范围起（YYYY-MM-DD，作用于集合的日期字段）",
            },
            "date_to": {
                "type": "string",
                "description": "query 模式日期范围止（YYYY-MM-DD）",
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "query 模式返回字段投影（可选，必须是 metadata 中已确认的字段）",
            },
            "limit": {
                "type": "integer",
                "description": "query 模式返回行数上限（默认 50，最大 200）",
            },
        },
        "required": ["dataset", "action"],
    }

    max_result_chars = 12000
    tool_timeout = 90.0

    async def execute(
        self,
        dataset: str = "",
        action: str = "metadata",
        filters: dict | None = None,
        date_from: str = "",
        date_to: str = "",
        fields: list | None = None,
        limit: int = 50,
        **kwargs,
    ) -> dict:
        from app.services.api_data_asset_service import ApiDataAssetService

        if not dataset:
            return {"success": False, "error": "缺少 dataset 参数"}
        if _is_blocked(dataset):
            return {"success": False, "error": f"数据集 {dataset} 为内部集合，不可查询"}

        service = ApiDataAssetService()

        if action == "metadata":
            asset = await service.get_asset(dataset)
            if not asset:
                return {"success": False, "error": f"数据集不存在: {dataset}，请先用 query_assets 查看资产清单"}
            return {
                "success": True,
                "dataset": dataset,
                "metadata": asset,
                "hint": "请继续 action=preview 查看样本，确认字段含义后再 action=query",
            }

        if action == "preview":
            preview = await service.preview_collection(dataset, limit=MAX_PREVIEW_ROWS)
            if preview["total"] == 0 and not preview["records"]:
                return {"success": False, "error": f"数据集不存在或为空: {dataset}"}
            return {
                "success": True,
                "dataset": dataset,
                "total_records": preview["total"],
                "records": preview["records"],
                "hint": "确认字段后可 action=query 进行条件查询",
            }

        if action == "query":
            return await self._query(service, dataset, filters or {}, date_from, date_to, fields or [], limit)

        return {"success": False, "error": f"未知 action: {action}（可选 metadata/preview/query）"}

    # ------------------------------------------------------------------

    async def _query(
        self,
        service,
        dataset: str,
        filters: dict,
        date_from: str,
        date_to: str,
        fields: list,
        limit: int,
    ) -> dict:
        from app.config.database import Database

        asset = await service.get_asset(dataset)
        if not asset:
            return {"success": False, "error": f"数据集不存在: {dataset}"}

        known_fields = set(asset.get("fields") or [])
        if not known_fields:
            return {"success": False, "error": f"数据集 {dataset} 为空集合，无字段可查询"}

        # 等值过滤：字段必须在已采样字段中（防止凭空字段与任意查询）
        mongo_filter: dict = {}
        rejected_fields = []
        for key, value in filters.items():
            if key in known_fields:
                mongo_filter[key] = value
            else:
                rejected_fields.append(key)
        if rejected_fields:
            return {
                "success": False,
                "error": f"字段不存在于 {dataset}: {rejected_fields}。已知字段: {sorted(known_fields)}",
            }

        # 日期范围：作用于探测到的日期字段，按存储类型自适应（datetime / 字符串）
        date_field = asset.get("date_field")
        if date_from or date_to:
            if not date_field:
                return {"success": False, "error": f"数据集 {dataset} 未探测到日期字段，不支持日期范围过滤"}
            lo = self._parse_date(date_from, end_of_day=False) if date_from else None
            hi = self._parse_date(date_to, end_of_day=True) if date_to else None
            if date_from and not lo:
                return {"success": False, "error": f"date_from 格式无效: {date_from}（需 YYYY-MM-DD）"}
            if date_to and not hi:
                return {"success": False, "error": f"date_to 格式无效: {date_to}（需 YYYY-MM-DD）"}

            stored_as_datetime = await self._date_stored_as_datetime(service.db[dataset], date_field)
            range_cond: dict = {}
            if lo:
                range_cond["$gte"] = lo if stored_as_datetime else date_from
            if hi:
                range_cond["$lte"] = hi if stored_as_datetime else date_to
            mongo_filter[date_field] = range_cond

        # 字段投影（仅允许已采样字段）
        projection = {"_id": 0}
        invalid_projection = [f for f in fields if f not in known_fields]
        if invalid_projection:
            return {"success": False, "error": f"投影字段不存在: {invalid_projection}"}
        for f in fields:
            projection[f] = 1

        limit = max(1, min(int(limit or 50), MAX_QUERY_ROWS))
        coll = service.db[dataset]
        total = await coll.count_documents(mongo_filter)
        cursor = coll.find(mongo_filter, projection).limit(limit)
        rows = [doc async for doc in cursor]

        return {
            "success": True,
            "dataset": dataset,
            "count": len(rows),
            "total_matched": total,
            "truncated": total > len(rows),
            "data": {"records": bson_safe(rows)},
            "metadata": {"record_count": len(rows)},
            "summary": (
                f"数据集 {dataset} 命中 {total} 条，返回 {len(rows)} 条"
                + ("（已截断）" if total > len(rows) else "")
            ),
        }

    @staticmethod
    def _parse_date(text: str, end_of_day: bool):
        try:
            dt = datetime.strptime(text.strip(), "%Y-%m-%d")
        except (ValueError, AttributeError):
            return None
        if end_of_day:
            return dt.replace(hour=23, minute=59, second=59)
        return dt

    @staticmethod
    async def _date_stored_as_datetime(coll, date_field: str) -> bool:
        """采样一条记录判断日期字段存储类型（datetime vs 字符串）"""
        sample = await coll.find_one({date_field: {"$exists": True, "$ne": None}}, {date_field: 1})
        return isinstance((sample or {}).get(date_field), datetime)
