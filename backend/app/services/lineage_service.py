"""
数据血缘追踪服务
- 管理 lineage_nodes 和 lineage_edges 两个MongoDB集合
- 提供节点/边的CRUD操作
- 支持图谱查询和影响分析
"""
from typing import Optional, List
from datetime import datetime
from loguru import logger
from pydantic import BaseModel, Field


# ============ 数据模型 ============

class LineageNode(BaseModel):
    """血缘节点"""
    node_id: str = Field(..., description="结构化ID: {type}:{domain}:{name}:{version}")
    node_type: str = Field(..., description="节点类型: SOURCE_API/SOURCE_FILE/STORAGE_MONGO/TRANSFORM_TOOL/CONSUMER_UI/CONSUMER_AGENT")
    domain: str = Field("", description="所属域")
    name: str = Field(..., description="节点名称（如集合名、API名）")
    display_name: str = Field("", description="中文显示名")
    metadata: dict = Field(default_factory=dict, description="附加元数据")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LineageEdge(BaseModel):
    """血缘边"""
    edge_id: str = Field("", description="自动生成: {source_id}--{edge_type}-->{target_id}")
    source_id: str = Field(..., description="来源节点ID")
    target_id: str = Field(..., description="目标节点ID")
    edge_type: str = Field(..., description="边类型: DATA_FLOW/TRANSFORM/REFERENCE/DERIVE")
    label: str = Field("", description="边标签")
    metadata: dict = Field(default_factory=dict, description="附加元数据（如导入批次、记录数等）")
    created_at: Optional[str] = None


class LineageService:
    """血缘追踪服务（单例）"""

    _instance: Optional["LineageService"] = None

    NODES_COLLECTION = "lineage_nodes"
    EDGES_COLLECTION = "lineage_edges"

    @classmethod
    def get_instance(cls) -> "LineageService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_db(self):
        from app.config.database import Database
        return Database.db

    async def ensure_indexes(self):
        """确保索引存在"""
        db = self._get_db()
        if db is None:
            return
        try:
            await db[self.NODES_COLLECTION].create_index("node_id", unique=True)
            await db[self.NODES_COLLECTION].create_index("node_type")
            await db[self.NODES_COLLECTION].create_index("domain")
            await db[self.EDGES_COLLECTION].create_index("edge_id", unique=True)
            await db[self.EDGES_COLLECTION].create_index("source_id")
            await db[self.EDGES_COLLECTION].create_index("target_id")
        except Exception as e:
            logger.warning(f"创建血缘索引失败: {e}")

    async def upsert_node(self, node: LineageNode) -> bool:
        """创建或更新节点"""
        db = self._get_db()
        if db is None:
            return False
        try:
            now = datetime.now().isoformat()
            doc = node.model_dump()
            doc["updated_at"] = now
            await db[self.NODES_COLLECTION].update_one(
                {"node_id": node.node_id},
                {"$set": doc, "$setOnInsert": {"created_at": now}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.warning(f"血缘节点更新失败: {e}")
            return False

    async def upsert_edge(self, edge: LineageEdge) -> bool:
        """创建或更新边"""
        db = self._get_db()
        if db is None:
            return False
        try:
            now = datetime.now().isoformat()
            if not edge.edge_id:
                edge.edge_id = f"{edge.source_id}--{edge.edge_type}-->{edge.target_id}"
            doc = edge.model_dump()
            doc["created_at"] = now
            await db[self.EDGES_COLLECTION].update_one(
                {"edge_id": edge.edge_id},
                {"$set": doc, "$setOnInsert": {"created_at": now}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.warning(f"血缘边更新失败: {e}")
            return False

    async def record_import_lineage(self, source_type: str, source_name: str,
                                     target_collection: str, domain: str,
                                     record_count: int = 0, batch_id: str = ""):
        """记录一次数据导入的血缘（便捷方法）"""
        # 创建来源节点
        source_node = LineageNode(
            node_id=f"{source_type}:{domain}:{source_name}:1.0",
            node_type=source_type,
            domain=domain,
            name=source_name,
            display_name=source_name,
            metadata={"batch_id": batch_id}
        )
        await self.upsert_node(source_node)

        # 创建存储节点
        storage_node = LineageNode(
            node_id=f"STORAGE_MONGO:{domain}:{target_collection}:1.0",
            node_type="STORAGE_MONGO",
            domain=domain,
            name=target_collection,
            display_name=target_collection,
            metadata={"record_count": record_count}
        )
        await self.upsert_node(storage_node)

        # 创建数据流边
        edge = LineageEdge(
            source_id=source_node.node_id,
            target_id=storage_node.node_id,
            edge_type="DATA_FLOW",
            label=f"导入 {record_count} 条",
            metadata={
                "batch_id": batch_id,
                "record_count": record_count,
                "import_time": datetime.now().isoformat()
            }
        )
        await self.upsert_edge(edge)

        logger.info(f"血缘记录: {source_name} → {target_collection} ({record_count}条)")

    async def get_graph(self, domain: Optional[str] = None,
                        root_id: Optional[str] = None,
                        depth: int = 3) -> dict:
        """获取血缘图谱"""
        db = self._get_db()
        if db is None:
            return {"nodes": [], "edges": []}

        try:
            # 查询节点
            node_filter = {}
            if domain:
                node_filter["domain"] = domain

            nodes = []
            async for doc in db[self.NODES_COLLECTION].find(node_filter, {"_id": 0}):
                nodes.append(doc)

            # 查询边
            edge_filter = {}
            if domain:
                node_ids = [n["node_id"] for n in nodes]
                edge_filter = {"$or": [
                    {"source_id": {"$in": node_ids}},
                    {"target_id": {"$in": node_ids}}
                ]}

            edges = []
            async for doc in db[self.EDGES_COLLECTION].find(edge_filter, {"_id": 0}):
                edges.append(doc)

            return {"nodes": nodes, "edges": edges}
        except Exception as e:
            logger.warning(f"获取血缘图谱失败: {e}")
            return {"nodes": [], "edges": []}

    async def get_impact_analysis(self, node_id: str, direction: str = "downstream") -> dict:
        """影响分析：查找指定节点的上游或下游"""
        db = self._get_db()
        if db is None:
            return {"impacted_nodes": [], "paths": []}

        try:
            visited = set()
            impacted = []
            paths = []

            await self._traverse(db, node_id, direction, visited, impacted, paths, depth=3)

            return {"root": node_id, "direction": direction, "impacted_nodes": impacted, "paths": paths}
        except Exception as e:
            logger.warning(f"影响分析失败: {e}")
            return {"impacted_nodes": [], "paths": []}

    async def _traverse(self, db, node_id: str, direction: str,
                        visited: set, impacted: list, paths: list, depth: int):
        """递归遍历图谱"""
        if depth <= 0 or node_id in visited:
            return
        visited.add(node_id)

        if direction == "downstream":
            filter_key = "source_id"
            next_key = "target_id"
        else:
            filter_key = "target_id"
            next_key = "source_id"

        async for edge in db[self.EDGES_COLLECTION].find({filter_key: node_id}, {"_id": 0}):
            next_id = edge[next_key]
            if next_id not in visited:
                impacted.append(next_id)
                paths.append(f"{node_id} → {next_id}" if direction == "downstream" else f"{next_id} → {node_id}")
                await self._traverse(db, next_id, direction, visited, impacted, paths, depth - 1)

    async def get_stats(self) -> dict:
        """获取血缘统计"""
        db = self._get_db()
        if db is None:
            return {"total_nodes": 0, "total_edges": 0}
        try:
            total_nodes = await db[self.NODES_COLLECTION].count_documents({})
            total_edges = await db[self.EDGES_COLLECTION].count_documents({})

            # 按类型统计节点
            pipeline = [{"$group": {"_id": "$node_type", "count": {"$sum": 1}}}]
            type_dist = {}
            async for doc in db[self.NODES_COLLECTION].aggregate(pipeline):
                type_dist[doc["_id"]] = doc["count"]

            return {
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "node_type_distribution": type_dist
            }
        except Exception:
            return {"total_nodes": 0, "total_edges": 0}
