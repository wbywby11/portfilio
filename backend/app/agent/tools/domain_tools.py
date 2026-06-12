"""
域级综合分析工具 - 支持9大业务域82张表的单表查询和跨表关联分析
"""
from typing import Any

from bson import ObjectId
from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.services.collection_registry import CollectionRegistry, DOMAIN_METADATA
from app.config.database import Database


class DomainQueryTool(BaseTool):
    """数据域综合查询工具"""

    name = "domain_query"
    description = """数据域综合查询工具。支持对9大业务域（资产、主体、产品、估值、交易、销售、客户、风险、行情）共82张数据表进行单表查询和跨表关联分析。

功能：
1. discover - 探索指定域下所有可查询的表及其描述、关联关系
2. query - 对单张表进行条件查询（支持过滤、排序、分页）
3. join - 跨表关联查询（基于外键关系自动关联两张表的数据）
4. analyze - 域级聚合分析（按维度分组统计，支持sum/avg/count/min/max）

适用场景：
- "帮我查询所有国债类资产的最新估值"
- "分析PORT001组合的持仓结构及对应资产的中债估值"
- "统计各销售人员管理的客户资产总规模"
- "查看工商银行(ISR000003)发行的所有债券及其最新评级"
- "对比5个组合的最新净值和风险指标"
"""

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["discover", "query", "join", "analyze"],
                "description": "操作类型：discover探索域表/query单表查询/join跨表关联/analyze聚合分析"
            },
            "domain": {
                "type": "string",
                "enum": ["asset", "subject", "product", "valuation", "transaction", "seller", "customer", "risk", "market"],
                "description": "业务域标识（discover时必填，其他操作可选）"
            },
            "collection": {
                "type": "string",
                "description": "目标表名（query/join/analyze时使用），如 dwd_ast_info"
            },
            "filters": {
                "type": "object",
                "description": "查询条件，格式为 {field: value} 或 {field: {op: value}}。支持的操作符：eq/ne/gt/gte/lt/lte/in/contains"
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "返回字段列表（投影），为空则返回全部字段"
            },
            "sort": {
                "type": "object",
                "description": "排序配置，格式为 {field: 1} 正序 或 {field: -1} 倒序"
            },
            "join_config": {
                "type": "object",
                "properties": {
                    "right_collection": {"type": "string", "description": "右表名称"},
                    "on": {"type": "string", "description": "关联字段名（两表共有）"},
                    "right_fields": {"type": "array", "items": {"type": "string"}, "description": "从右表取哪些字段"}
                },
                "description": "关联配置（join操作时使用）"
            },
            "group_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "分组字段（analyze操作时使用）"
            },
            "metrics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "agg": {"type": "string", "enum": ["sum", "avg", "count", "min", "max"]}
                    }
                },
                "description": "聚合指标，如 [{field:'AUM', agg:'sum'}, {field:'PORT_ID', agg:'count'}]"
            },
            "limit": {
                "type": "integer",
                "description": "返回记录数上限，默认50，最大500"
            },
            "skip": {
                "type": "integer",
                "description": "跳过记录数（分页用）"
            }
        },
        "required": ["action"]
    }

    category = "data"
    tags = ["domain", "cross-table", "join", "comprehensive", "data-dictionary"]

    # 操作符映射
    _OP_MAP = {
        "eq": "$eq", "ne": "$ne", "gt": "$gt", "gte": "$gte",
        "lt": "$lt", "lte": "$lte", "in": "$in",
    }

    async def execute(self, **kwargs) -> dict:
        action = kwargs.get("action")
        if action == "discover":
            result = await self._discover(kwargs)
            result["_lineage_meta"] = self._build_lineage_meta(
                operation="discover", tables=[], fields_accessed={}, result_count=0
            )
            return result
        elif action == "query":
            collection = kwargs.get("collection", "")
            result = await self._query(kwargs)
            fields = kwargs.get("fields") or []
            record_count = result.get("metadata", {}).get("record_count", 0) if result.get("success") else 0
            result["_lineage_meta"] = self._build_lineage_meta(
                operation="query",
                tables=[collection] if collection else [],
                fields_accessed={collection: fields} if collection and fields else {},
                result_count=record_count,
            )
            return result
        elif action == "join":
            result = await self._join(kwargs)
            # 构建 join 的 lineage
            collection = kwargs.get("collection", "")
            join_config = kwargs.get("join_config") or {}
            right_collection = join_config.get("right_collection", "")
            on_field = join_config.get("on", "")
            left_fields = kwargs.get("fields") or []
            right_fields = join_config.get("right_fields") or []
            tables = [t for t in [collection, right_collection] if t]
            fields_accessed = {}
            if collection and left_fields:
                fields_accessed[collection] = left_fields
            if right_collection and right_fields:
                fields_accessed[right_collection] = right_fields
            join_path = f"{collection}.{on_field} → {right_collection}.{on_field}" if collection and right_collection and on_field else ""
            record_count = result.get("metadata", {}).get("record_count", 0) if result.get("success") else 0
            meta = self._build_lineage_meta(
                operation="join", tables=tables, fields_accessed=fields_accessed, result_count=record_count
            )
            meta["join_path"] = join_path
            result["_lineage_meta"] = meta
            return result
        elif action == "analyze":
            collection = kwargs.get("collection", "")
            result = await self._analyze(kwargs)
            # 聚合字段
            agg_fields: list[str] = list(kwargs.get("group_by") or [])
            for m in (kwargs.get("metrics") or []):
                if isinstance(m, dict) and m.get("field"):
                    agg_fields.append(m["field"])
            record_count = result.get("metadata", {}).get("record_count", 0) if result.get("success") else 0
            result["_lineage_meta"] = self._build_lineage_meta(
                operation="analyze",
                tables=[collection] if collection else [],
                fields_accessed={collection: agg_fields} if collection and agg_fields else {},
                result_count=record_count,
            )
            return result
        else:
            result = ToolResult.error(f"不支持的操作类型: {action}，可选: discover/query/join/analyze")
            result["_lineage_meta"] = self._build_lineage_meta(
                operation=action or "", tables=[], fields_accessed={}, result_count=0
            )
            return result

    # ── discover ─────────────────────────────────────────────────────────────

    async def _discover(self, kwargs: dict) -> dict:
        """探索指定域下所有可查询的表及其描述、关联关系。"""
        domain = kwargs.get("domain")

        if not domain:
            # 返回所有域的概要
            overview = []
            for domain_key, domain_info in DOMAIN_METADATA.items():
                overview.append({
                    "domain": domain_key,
                    "display_name": domain_info["display_name"],
                    "description": domain_info["description"],
                    "table_count": len(domain_info["tables"]),
                })
            return ToolResult.success(
                data={"domains": overview},
                summary=f"系统共有 {len(overview)} 个业务域，{sum(d['table_count'] for d in overview)} 张数据表",
                record_count=len(overview),
                data_shape="list",
            )

        # 指定域
        domain_info = DOMAIN_METADATA.get(domain)
        if not domain_info:
            available = list(DOMAIN_METADATA.keys())
            return ToolResult.error(
                f"未知的业务域: {domain}，可用域: {', '.join(available)}"
            )

        tables = []
        for table_name, table_meta in domain_info["tables"].items():
            tables.append({
                "collection": table_name,
                "display_name": table_meta["display_name"],
                "description": table_meta["description"],
                "primary_keys": table_meta.get("primary_keys", []),
                "foreign_keys": table_meta.get("foreign_keys", {}),
                "key_fields": table_meta.get("key_fields", []),
                "typical_queries": table_meta.get("typical_queries", []),
            })

        return ToolResult.success(
            data={
                "domain": domain,
                "display_name": domain_info["display_name"],
                "description": domain_info["description"],
                "tables": tables,
            },
            summary=f"{domain_info['display_name']}共有 {len(tables)} 张数据表",
            record_count=len(tables),
            data_shape="list",
        )

    # ── query ────────────────────────────────────────────────────────────────

    async def _query(self, kwargs: dict) -> dict:
        """对单张表进行条件查询。"""
        collection = kwargs.get("collection")
        if not collection:
            return ToolResult.error("query 操作需要指定 collection 参数")

        # 验证 collection 存在
        if not self._validate_collection_exists(collection):
            return ToolResult.error(
                f"集合 '{collection}' 不在已知业务表中。请使用 discover 查看可用表。"
            )

        try:
            db = Database.get_database()
            col = db[collection]

            # 构建查询条件
            mongo_filter = self._build_filter(kwargs.get("filters"))

            # 构建投影
            fields = kwargs.get("fields")
            projection: dict | None = None
            if fields:
                projection = {f: 1 for f in fields}

            # 构建排序
            sort_spec = kwargs.get("sort")
            sort_list: list[tuple[str, int]] | None = None
            if sort_spec and isinstance(sort_spec, dict):
                sort_list = [(k, int(v)) for k, v in sort_spec.items()]

            # 限制与分页
            limit = min(max(1, int(kwargs.get("limit", 50))), 500)
            skip = max(0, int(kwargs.get("skip", 0)))

            # 执行查询
            total: int = await col.count_documents(mongo_filter)
            cursor = col.find(mongo_filter, projection).skip(skip).limit(limit)
            if sort_list:
                cursor = cursor.sort(sort_list)

            docs: list[dict] = []
            async for doc in cursor:
                docs.append(self._serialize_doc(doc))

            has_more = (skip + limit) < total

            summary = f"查询 '{collection}'：返回 {len(docs)} 条（共 {total} 条）"
            if has_more:
                summary += "，还有更多数据"

            return ToolResult.success(
                data={
                    "records": docs,
                    "total": total,
                    "page_info": {
                        "limit": limit,
                        "skip": skip,
                        "has_more": has_more,
                    },
                },
                summary=summary,
                record_count=len(docs),
                data_shape="table",
            )
        except Exception as e:
            logger.error("[DomainQuery] query 失败: {}", e)
            return ToolResult.error(f"查询失败: {e}")

    # ── join ─────────────────────────────────────────────────────────────────

    async def _join(self, kwargs: dict) -> dict:
        """跨表关联查询 - 应用层 lookup。"""
        collection = kwargs.get("collection")
        join_config = kwargs.get("join_config")

        if not collection:
            return ToolResult.error("join 操作需要指定 collection（左表）参数")
        if not join_config or not isinstance(join_config, dict):
            return ToolResult.error("join 操作需要指定 join_config 参数")

        right_collection = join_config.get("right_collection")
        on_field = join_config.get("on")
        right_fields = join_config.get("right_fields")

        if not right_collection or not on_field:
            return ToolResult.error("join_config 需要包含 right_collection 和 on 字段")

        # 验证两张表都存在
        if not self._validate_collection_exists(collection):
            return ToolResult.error(f"左表 '{collection}' 不在已知业务表中")
        if not self._validate_collection_exists(right_collection):
            return ToolResult.error(f"右表 '{right_collection}' 不在已知业务表中")

        try:
            db = Database.get_database()

            # 1) 查询左表（带 filters/limit）
            mongo_filter = self._build_filter(kwargs.get("filters"))
            limit = min(max(1, int(kwargs.get("limit", 50))), 500)
            skip = max(0, int(kwargs.get("skip", 0)))

            # 左表投影：保留全部字段
            left_fields = kwargs.get("fields")
            left_projection: dict | None = None
            if left_fields:
                left_projection = {f: 1 for f in left_fields}
                # 确保关联字段在投影中
                left_projection[on_field] = 1

            sort_spec = kwargs.get("sort")
            sort_list: list[tuple[str, int]] | None = None
            if sort_spec and isinstance(sort_spec, dict):
                sort_list = [(k, int(v)) for k, v in sort_spec.items()]

            left_col = db[collection]
            cursor = left_col.find(mongo_filter, left_projection).skip(skip).limit(limit)
            if sort_list:
                cursor = cursor.sort(sort_list)

            left_docs: list[dict] = []
            async for doc in cursor:
                left_docs.append(self._serialize_doc(doc))

            if not left_docs:
                return ToolResult.success(
                    data={"records": [], "total": 0},
                    summary="左表查询无结果，无法执行关联",
                    record_count=0,
                    data_shape="table",
                )

            # 2) 收集关联键值，批量查右表
            join_values = list({
                doc[on_field] for doc in left_docs
                if on_field in doc and doc[on_field] is not None
            })

            if not join_values:
                return ToolResult.success(
                    data={"records": left_docs, "total": len(left_docs)},
                    summary=f"左表 {len(left_docs)} 条，关联字段 '{on_field}' 无有效值",
                    record_count=len(left_docs),
                    data_shape="table",
                )

            right_col = db[right_collection]
            right_filter = {on_field: {"$in": join_values}}
            right_projection: dict | None = None
            if right_fields:
                right_projection = {f: 1 for f in right_fields}
                right_projection[on_field] = 1

            right_docs: list[dict] = []
            async for doc in right_col.find(right_filter, right_projection).limit(len(join_values) * 10):
                right_docs.append(self._serialize_doc(doc))

            # 3) 构建右表索引 (一对多：每个 key 对应多条)
            right_map: dict[str, list[dict]] = {}
            for rdoc in right_docs:
                key_val = str(rdoc.get(on_field, ""))
                right_map.setdefault(key_val, []).append(rdoc)

            # 4) 合并
            merged: list[dict] = []
            for ldoc in left_docs:
                key_val = str(ldoc.get(on_field, ""))
                matched_rights = right_map.get(key_val, [])
                if matched_rights:
                    for rdoc in matched_rights:
                        combined = {**ldoc}
                        for k, v in rdoc.items():
                            if k != on_field and k != "_id":
                                combined[f"{right_collection}.{k}"] = v
                        merged.append(combined)
                else:
                    merged.append(ldoc)

            # 截断
            if len(merged) > 500:
                merged = merged[:500]
                has_more = True
            else:
                has_more = False

            summary = (
                f"关联查询: {collection} ⟶ {right_collection} (on={on_field})，"
                f"左表 {len(left_docs)} 条，右表命中 {len(right_docs)} 条，合并 {len(merged)} 条"
            )
            if has_more:
                summary += "（已截断至500条）"

            return ToolResult.success(
                data={
                    "records": merged,
                    "total": len(merged),
                    "join_info": {
                        "left": collection,
                        "right": right_collection,
                        "on": on_field,
                        "left_count": len(left_docs),
                        "right_matched": len(right_docs),
                    },
                    "has_more": has_more,
                },
                summary=summary,
                record_count=len(merged),
                data_shape="table",
            )
        except Exception as e:
            logger.error("[DomainQuery] join 失败: {}", e)
            return ToolResult.error(f"关联查询失败: {e}")

    # ── analyze ──────────────────────────────────────────────────────────────

    async def _analyze(self, kwargs: dict) -> dict:
        """域级聚合分析 - 使用 MongoDB aggregation pipeline。"""
        collection = kwargs.get("collection")
        if not collection:
            return ToolResult.error("analyze 操作需要指定 collection 参数")

        if not self._validate_collection_exists(collection):
            return ToolResult.error(
                f"集合 '{collection}' 不在已知业务表中。请使用 discover 查看可用表。"
            )

        group_by: list[str] | None = kwargs.get("group_by")
        metrics: list[dict] | None = kwargs.get("metrics")

        if not metrics:
            return ToolResult.error("analyze 操作需要指定 metrics 参数（聚合指标）")

        try:
            db = Database.get_database()
            col = db[collection]

            pipeline: list[dict] = []

            # $match
            mongo_filter = self._build_filter(kwargs.get("filters"))
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

            agg_map = {
                "sum": "$sum", "avg": "$avg", "min": "$min",
                "max": "$max",
            }
            sort_field: str | None = None

            for m in metrics:
                field = m.get("field", "_id")
                agg_op = m.get("agg", "sum")
                alias = m.get("alias", f"{agg_op}_{field}")

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
            limit = min(max(1, int(kwargs.get("limit", 100))), 500)
            pipeline.append({"$limit": limit})

            # 执行
            docs: list[dict] = []
            async for doc in col.aggregate(pipeline):
                # 展平 _id
                group_id = doc.pop("_id", None)
                if isinstance(group_id, dict):
                    doc.update(group_id)
                elif group_id is not None:
                    if group_by and len(group_by) == 1:
                        doc[group_by[0]] = self._serialize_value(group_id)
                    else:
                        doc["group"] = self._serialize_value(group_id)
                docs.append(self._serialize_doc_flat(doc))

            summary = f"聚合分析 '{collection}'：{len(docs)} 个分组"
            if group_by:
                summary += f"（按 {', '.join(group_by)} 分组）"

            return ToolResult.success(
                data={"groups": docs, "group_count": len(docs)},
                summary=summary,
                record_count=len(docs),
                data_shape="aggregate",
            )
        except Exception as e:
            logger.error("[DomainQuery] analyze 失败: {}", e)
            return ToolResult.error(f"聚合分析失败: {e}")

    # ── 内部辅助方法 ──────────────────────────────────────────────────────────

    # ── 血缘溯源元数据 ──────────────────────────────────────────────────────────

    def _build_lineage_meta(self, operation: str, tables: list[str], fields_accessed: dict, result_count: int) -> dict:
        """构造血缘溯源元数据"""
        domains = []
        for t in tables:
            d = self._infer_domain(t)
            if d and d not in domains:
                domains.append(d)

        return {
            "tables_used": tables,
            "domains_involved": domains,
            "fields_accessed": fields_accessed,
            "join_path": "",
            "records_returned": result_count,
            "query_operation": operation,
        }

    @staticmethod
    def _infer_domain(collection: str) -> str:
        """从集合名推断所属域"""
        prefix_map = {
            "dwd_ast_": "asset",
            "dwd_isr_": "subject",
            "dwd_ptl_": "product",
            "dwd_val_": "valuation",
            "dwd_trn_": "transaction",
            "dwd_sale_": "seller",
            "dwd_cust_": "customer",
            "dwd_rsk_": "risk",
            "dwd_mkt_": "market",
            "tag_ptl_": "product",
            # data_hub 域表（接口中心）
            "subject_risk_": "data_hub",
            "zysc_ptl_": "data_hub",
        }
        # 精确匹配优先（处理 data_hub 域的完整表名）
        exact_map = {
            "subject_risk_records": "data_hub",
            "subject_risk_import_batches": "data_hub",
            "zysc_ptl_info_records": "data_hub",
            "zysc_ptl_info_import_batches": "data_hub",
            "zysc_ptl_holder_records": "data_hub",
            "zysc_ptl_holder_import_batches": "data_hub",
        }
        if collection in exact_map:
            return exact_map[collection]
        for prefix, domain in prefix_map.items():
            if collection.startswith(prefix):
                return domain
        return ""

    @staticmethod
    def _validate_collection_exists(collection: str) -> bool:
        """验证集合是否在 DOMAIN_METADATA 中注册。"""
        for domain_info in DOMAIN_METADATA.values():
            if collection in domain_info["tables"]:
                return True
        return False

    def _build_filter(self, filters: Any) -> dict:
        """将简化的 filters 对象转换为 MongoDB 查询条件。

        支持两种格式：
        - 简单值: {field: value} → 精确匹配
        - 操作符: {field: {op: value}} → 对应 MongoDB 操作
        """
        if not filters or not isinstance(filters, dict):
            return {}

        mongo_filter: dict[str, Any] = {}

        for field, condition in filters.items():
            if field.startswith("$"):
                # 安全检查：拒绝危险字段
                logger.warning("[DomainQuery] 拒绝危险字段: {}", field)
                continue

            if isinstance(condition, dict):
                # 操作符格式: {op: value}
                for op, value in condition.items():
                    if op == "contains":
                        mongo_filter[field] = {"$regex": str(value), "$options": "i"}
                    elif op in self._OP_MAP:
                        mongo_op = self._OP_MAP[op]
                        if field in mongo_filter and isinstance(mongo_filter[field], dict):
                            mongo_filter[field][mongo_op] = value
                        else:
                            mongo_filter[field] = {mongo_op: value}
                    elif op == "eq":
                        mongo_filter[field] = value
                    else:
                        logger.warning("[DomainQuery] 不支持的操作符: {}", op)
            else:
                # 简单精确匹配
                mongo_filter[field] = condition

        return mongo_filter

    @staticmethod
    def _serialize_doc(doc: dict) -> dict:
        """序列化 MongoDB 文档，处理 ObjectId 和特殊类型。"""
        result = {}
        for k, v in doc.items():
            if k == "_id":
                result["_id"] = str(v) if isinstance(v, ObjectId) else v
            else:
                result[k] = DomainQueryTool._serialize_value(v)
        return result

    @staticmethod
    def _serialize_doc_flat(doc: dict) -> dict:
        """序列化已展平的聚合文档。"""
        result = {}
        for k, v in doc.items():
            result[k] = DomainQueryTool._serialize_value(v)
        return result

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        """递归序列化值。"""
        if isinstance(value, ObjectId):
            return str(value)
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, list):
            return [DomainQueryTool._serialize_value(v) for v in value]
        if isinstance(value, dict):
            return {k: DomainQueryTool._serialize_value(v) for k, v in value.items()}
        return value
