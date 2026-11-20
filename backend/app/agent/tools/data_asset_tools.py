"""
数据资产域读工具 — query_assets + check_data_quality

- query_assets(action=list/coverage)：资产盘点（实时扫库，新集合自动可见）
- check_data_quality(scope, checks)：数据质检（缺失/重复/陈旧度）

复用链路：ApiDataAssetService（实时扫描 + 人工标注合并）。
"""
from datetime import datetime, timezone

from loguru import logger

from app.agent.tools._helpers import bar_chart, fmt_date
from app.agent.tools.base import BaseTool

# 内部集合前缀（盘点清单中过滤，降低噪音；与 query_dataset 黑名单一致）
_INTERNAL_PREFIXES = ("_", "agent_", "system.")

# 质检默认范围
_DEFAULT_SCOPE = "asset_prices,fx_rates"

# 代码字段候选（重复检测用，按优先级）
_CODE_FIELD_CANDIDATES = ["thscode", "asset_code", "code", "symbol", "instrument", "pair", "fx_pair"]

# 陈旧度阈值（天）
_STALE_THRESHOLD_DAYS = 3


class QueryAssetsTool(BaseTool):
    """数据资产盘点工具（实时扫库，新增集合自动可见）"""

    name = "query_assets"
    description = (
        "盘点数据库中的【数据集合】元数据（数据工程视角，实时扫描全部集合，"
        "新增集合自动可见）。两种模式：\n"
        "1) action=list：数据集合清单——每个集合的记录数/存储大小/字段列表/日期范围/"
        "人工标注（描述/标签）。用于了解系统有哪些数据集、字段结构与数据新鲜度，"
        "或在集合名不确定时先确认其存在\n"
        "2) action=coverage：数据覆盖概览——指定集合（collections，逗号分隔，"
        "默认行情类）的日期范围与数据陈旧度\n"
        "注意：本工具盘点的是'数据集合'而非'可投资资产'。"
        "为策略/组合挑选底层资产时不要使用本工具，"
        "应通过 query_dataset 查询资产主数据集合（集合名见知识库）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "coverage"],
                "description": "查询模式",
            },
            "collections": {
                "type": "string",
                "description": "coverage 模式的目标集合，逗号分隔（默认 asset_prices,fx_rates）",
            },
            "keyword": {
                "type": "string",
                "description": "list 模式按名称/描述/标签过滤（可选）",
            },
        },
        "required": ["action"],
    }

    max_result_chars = 10000
    tool_timeout = 120.0

    async def execute(
        self,
        action: str = "list",
        collections: str = "",
        keyword: str = "",
        **kwargs,
    ) -> dict:
        from app.services.api_data_asset_service import ApiDataAssetService

        service = ApiDataAssetService()
        if action == "list":
            return await self._list(service, keyword)
        if action == "coverage":
            return await self._coverage(service, collections)
        return {"success": False, "error": f"未知 action: {action}（可选 list/coverage）"}

    async def _list(self, service, keyword: str) -> dict:
        result = await service.list_assets(keyword=keyword or None, page=1, page_size=200)
        records = []
        for item in result["items"]:
            name = item["collection_name"]
            if any(name.startswith(p) for p in _INTERNAL_PREFIXES):
                continue
            date_range = item.get("date_range") or {}
            records.append({
                "collection_name": name,
                "description": item.get("description") or "",
                "tags": item.get("tags") or [],
                "record_count": item.get("record_count", 0),
                "field_count": item.get("field_count", 0),
                "date_field": item.get("date_field"),
                "date_min": date_range.get("min", "")[:10],
                "date_max": date_range.get("max", "")[:10],
                "status": item.get("status", "active"),
            })

        return {
            "success": True,
            "count": len(records),
            "data": {"records": records},
            "metadata": {"record_count": len(records)},
            "summary": (
                f"共 {len(records)} 个业务数据集合，总记录数 {result['total_records']}。"
                if records else "未找到数据集合。"
            ),
            "hint": "查询数据集请用 query_dataset（先 metadata/preview 再 query）",
        }

    async def _coverage(self, service, collections: str) -> dict:
        names = [c.strip() for c in (collections or _DEFAULT_SCOPE).split(",") if c.strip()]
        records = []
        today = datetime.now(timezone.utc).date()
        for name in names:
            asset = await service.get_asset(name)
            if not asset:
                records.append({"collection_name": name, "error": "集合不存在"})
                continue
            date_range = asset.get("date_range") or {}
            stale_days = None
            if date_range.get("max"):
                try:
                    latest = datetime.strptime(str(date_range["max"])[:10], "%Y-%m-%d").date()
                    stale_days = (today - latest).days
                except ValueError:
                    pass
            records.append({
                "collection_name": name,
                "record_count": asset.get("record_count", 0),
                "date_field": asset.get("date_field"),
                "date_min": str(date_range.get("min", ""))[:10],
                "date_max": str(date_range.get("max", ""))[:10],
                "days_since_latest": stale_days,
                "is_stale": (stale_days is not None and stale_days > _STALE_THRESHOLD_DAYS),
            })

        return {
            "success": True,
            "count": len(records),
            "data": {"records": records},
            "metadata": {"record_count": len(records)},
            "summary": f"已盘点 {len(records)} 个集合的数据覆盖情况（days_since_latest 为距最新数据天数）。",
        }


class CheckDataQualityTool(BaseTool):
    """数据质量检查工具 — 缺失/重复/陈旧度"""

    name = "check_data_quality"
    description = (
        "检查数据质量。支持三类检查（checks 参数选择，默认全部）：\n"
        "- staleness：数据陈旧度（最新数据距今天数）\n"
        "- duplicates：重复记录（代码+日期维度）\n"
        "- missing：缺失概览（按日期统计记录数，显著偏少的日期视为可疑缺失）\n"
        "scope 为目标集合（逗号分隔，默认 asset_prices,fx_rates）。"
        "涉及数据覆盖/质量的断言必须先经本工具验证。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": "目标集合，逗号分隔（默认 asset_prices,fx_rates）",
            },
            "checks": {
                "type": "array",
                "items": {"type": "string", "enum": ["staleness", "duplicates", "missing"]},
                "description": "要执行的检查项（默认全部）",
            },
        },
        "required": [],
    }

    max_result_chars = 10000
    tool_timeout = 120.0

    async def execute(
        self,
        scope: str = "",
        checks: list | None = None,
        **kwargs,
    ) -> dict:
        from app.services.api_data_asset_service import ApiDataAssetService

        service = ApiDataAssetService()
        names = [c.strip() for c in (scope or _DEFAULT_SCOPE).split(",") if c.strip()]
        check_set = set(checks or ["staleness", "duplicates", "missing"])

        records = []
        charts = []
        today = datetime.now(timezone.utc).date()

        for name in names:
            asset = await service.get_asset(name)
            if not asset:
                records.append({"collection_name": name, "error": "集合不存在"})
                continue

            report: dict = {"collection_name": name, "record_count": asset.get("record_count", 0)}
            date_field = asset.get("date_field")
            date_range = asset.get("date_range") or {}

            # 陈旧度
            if "staleness" in check_set:
                stale_days = None
                if date_range.get("max"):
                    try:
                        latest = datetime.strptime(str(date_range["max"])[:10], "%Y-%m-%d").date()
                        stale_days = (today - latest).days
                    except ValueError:
                        pass
                report["staleness"] = {
                    "latest_date": str(date_range.get("max", ""))[:10],
                    "days_since_latest": stale_days,
                    "is_stale": stale_days is not None and stale_days > _STALE_THRESHOLD_DAYS,
                }

            # 重复与缺失需要日期字段
            if date_field:
                if "duplicates" in check_set:
                    report["duplicates"] = await self._check_duplicates(service.db[name], asset)
                if "missing" in check_set:
                    missing, chart = await self._check_missing(service.db[name], name, date_field)
                    report["missing"] = missing
                    if chart:
                        charts.append(chart)
            else:
                if "duplicates" in check_set:
                    report["duplicates"] = {"skipped": "未探测到日期字段"}
                if "missing" in check_set:
                    report["missing"] = {"skipped": "未探测到日期字段"}

            records.append(report)

        return {
            "success": True,
            "count": len(records),
            "data": {"records": records},
            "charts": charts,
            "metadata": {"record_count": len(records)},
            "summary": f"已完成 {len(records)} 个集合的质量检查（{', '.join(sorted(check_set))}）。",
        }

    # ------------------------------------------------------------------

    @staticmethod
    async def _check_duplicates(coll, asset: dict) -> dict:
        """代码+日期维度重复检测（聚合管道，最多列 20 组）"""
        fields = set(asset.get("fields") or [])
        date_field = asset.get("date_field")
        code_field = next((c for c in _CODE_FIELD_CANDIDATES if c in fields), None)
        if not code_field or not date_field:
            return {"skipped": f"无法确定代码字段（候选 {_CODE_FIELD_CANDIDATES}）"}

        pipeline = [
            {"$group": {"_id": {"code": f"${code_field}", "date": f"${date_field}"}, "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": 21},
        ]
        try:
            groups = await coll.aggregate(pipeline).to_list(length=21)
        except Exception as e:
            logger.warning("quality_dup_check_failed", extra={"error": str(e)})
            return {"error": str(e)}

        truncated = len(groups) > 20
        groups = groups[:20]
        return {
            "duplicate_group_count": len(groups) + (1 if truncated else 0),
            "truncated": truncated,
            "top_duplicates": [
                {"code": g["_id"].get("code"), "date": fmt_date(g["_id"].get("date")), "count": g["n"]}
                for g in groups
            ],
        }

    @staticmethod
    async def _check_missing(coll, name: str, date_field: str) -> tuple[dict, dict | None]:
        """按日期统计记录数，显著偏少（<80% 峰值）的日期视为可疑缺失"""
        pipeline = [
            {"$match": {date_field: {"$exists": True, "$ne": None}}},
            {"$group": {"_id": f"${date_field}", "n": {"$sum": 1}}},
            {"$sort": {"_id": -1}},
            {"$limit": 500},
        ]
        try:
            rows = await coll.aggregate(pipeline).to_list(length=500)
        except Exception as e:
            logger.warning("quality_missing_check_failed", extra={"error": str(e)})
            return {"error": str(e)}, None

        if not rows:
            return {"suspicious_date_count": 0}, None

        peak = max(r["n"] for r in rows)
        threshold = peak * 0.8
        suspicious = [r for r in rows if r["n"] < threshold]

        # 图表：最近 30 个可疑日期的缺口量
        chart = None
        if suspicious:
            recent = suspicious[:30][::-1]
            chart = bar_chart(
                f"{name} 数据缺口（近 {len(recent)} 个可疑日期）",
                [fmt_date(r["_id"]) for r in recent],
                [{"name": "缺口记录数", "data": [peak - r["n"] for r in recent]}],
            )

        return {
            "checked_days": len(rows),
            "peak_records_per_day": peak,
            "suspicious_date_count": len(suspicious),
            "recent_suspicious": [
                {"date": fmt_date(r["_id"]), "records": r["n"], "gap": peak - r["n"]}
                for r in suspicious[:10]
            ],
        }, chart
