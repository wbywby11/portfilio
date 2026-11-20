"""策略库查询 API（S16）—— 只读视图：档案 / 版本 / 运行台账 / 血缘.

为什么独立成 router：
    ``app/api/strategy_model.py`` 已接近 1000 行上限（S18 行数守卫），
    本组端点只读、不做写操作，放在新文件里与实例级 CRUD 解耦。

统一口径：
    - 全部 GET，无写路径；
    - 每个响应带 ``coverage``：``strategy_registry`` / ``strategy_versions`` /
      ``strategy_runs`` / ``lineage_*`` 四类集合只从治理功能上线起写入，
      此前的配置、回测与发布动作没有回填，**空列表不代表策略不存在**；
    - 未知 ``strategy_id`` 不返回 404：返回 200 + 空列表，避免前端深链/
      分页停留在过期 id 上直接爆错。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config.collections import (
    COL_LINEAGE_EDGES,
    COL_LINEAGE_NODES,
    COL_STRATEGY_MODELS,
    COL_STRATEGY_REGISTRY,
    COL_STRATEGY_RUNS,
    COL_STRATEGY_VERSIONS,
)
from app.config.database import Database
from app.models.strategy_registry import LIFECYCLE_STAGES
from app.schemas.response import Response
from app.services.strategy_registry_service import StrategyRegistryService
from app.services.strategy_run_service import StrategyRunService
from app.services.strategy_version_service import StrategyVersionService

router = APIRouter()

# 覆盖面声明：随每个响应返回，把「集合只是上线后才开始写」这件事显式化
_COVERAGE: Dict[str, Any] = {
    "since": "策略库治理功能上线（S07 版本表 / S11 运行台账 / S15 血缘）起",
    "note": (
        "档案、版本、运行、血缘四类记录只包含上线后的写入；"
        "此前的配置与回测未回填，空列表不等于策略或运行不存在"
    ),
    "collections": [
        COL_STRATEGY_REGISTRY,
        COL_STRATEGY_VERSIONS,
        COL_STRATEGY_RUNS,
        COL_LINEAGE_NODES,
        COL_LINEAGE_EDGES,
    ],
}

_MODEL_PROJECTION = {
    "name": 1,
    "template_code": 1,
    "status": 1,
    "published_version": 1,
    "live_published_version": 1,
    "created_at": 1,
    "updated_at": 1,
}


def get_registry_service() -> StrategyRegistryService:
    return StrategyRegistryService()


def get_version_service() -> StrategyVersionService:
    return StrategyVersionService()


def get_run_service() -> StrategyRunService:
    return StrategyRunService()


def _db():
    return Database.get_database()


def _split_tags(tags: Optional[str]) -> List[str]:
    """标签筛选：逗号分隔，去空白去重；空串按不筛处理."""
    if not tags:
        return []
    seen: List[str] = []
    for raw in tags.split(","):
        tag = raw.strip()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


async def _models_for_entry(entry) -> List[Dict[str, Any]]:
    """策略本体 → 实例列表：按 ``template_code`` 命中 manifest_key 或历史别名."""
    codes = [entry.manifest_key] + [a for a in (entry.aliases or []) if a]
    cursor = _db()[COL_STRATEGY_MODELS].find(
        {"template_code": {"$in": codes}}, projection=_MODEL_PROJECTION
    ).sort("created_at", -1)
    rows: List[Dict[str, Any]] = []
    async for doc in cursor:
        rows.append(
            {
                "model_id": str(doc["_id"]),
                "name": doc.get("name"),
                "template_code": doc.get("template_code"),
                "status": doc.get("status"),
                "published_version": doc.get("published_version"),
                "live_published_version": doc.get("live_published_version"),
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
            }
        )
    return rows


async def _count(collection_name: str, query: Dict[str, Any]) -> int:
    return int(await _db()[collection_name].count_documents(query))


def _empty_detail(strategy_id: str) -> Dict[str, Any]:
    return {
        "item": None,
        "models": [],
        "counts": {"models": 0, "versions": 0, "runs": 0},
        "coverage": _COVERAGE,
        "strategy_id": strategy_id,
    }


@router.get("", response_model=Response[dict], summary="列出策略库档案")
async def list_strategies(
    pillar: Optional[str] = Query(None, description="支柱：allocation / selection / control"),
    family: Optional[str] = Query(None, description="策略族标识"),
    tags: Optional[str] = Query(None, description="标签筛选，逗号分隔，命中任一即返回"),
    lifecycle: Optional[str] = Query(
        None, description="研发成熟度：" + " / ".join(LIFECYCLE_STAGES)
    ),
    skip: int = Query(0, ge=0, description="跳过条数"),
    limit: int = Query(200, ge=1, le=500, description="单页条数"),
    service: StrategyRegistryService = Depends(get_registry_service),
):
    """按支柱 / 策略族 / 标签 / 研发成熟度筛选档案（默认按 manifest_key 升序）。"""
    if lifecycle and lifecycle not in LIFECYCLE_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"lifecycle 取值须为：{' / '.join(LIFECYCLE_STAGES)}",
        )
    entries = await service.list_entries(
        pillar=pillar,
        family_id=family,
        tags=_split_tags(tags),
        lifecycle_stage=lifecycle,
        skip=skip,
        limit=limit,
    )
    items = [e.model_dump() for e in entries]
    return Response.success(
        data={
            "items": items,
            "count": len(items),
            "total": await service.count(),
            "coverage": _COVERAGE,
        }
    )


@router.get("/{strategy_id}", response_model=Response[dict], summary="策略档案详情")
async def get_strategy(
    strategy_id: str,
    service: StrategyRegistryService = Depends(get_registry_service),
):
    """档案正文 + 该策略下的模型实例列表 + 三类记录条数."""
    entry = await service.get_by_strategy_id(strategy_id)
    if entry is None:
        return Response.success(data=_empty_detail(strategy_id))
    models = await _models_for_entry(entry)
    return Response.success(
        data={
            "strategy_id": strategy_id,
            "item": entry.model_dump(),
            "models": models,
            "counts": {
                "models": len(models),
                "versions": await _count(
                    COL_STRATEGY_VERSIONS, {"strategy_id": strategy_id}
                ),
                "runs": await _count(COL_STRATEGY_RUNS, {"strategy_id": strategy_id}),
            },
            "coverage": _COVERAGE,
        }
    )


@router.get("/{strategy_id}/versions", response_model=Response[dict], summary="策略配置版本列表")
async def list_strategy_versions(
    strategy_id: str,
    model_id: Optional[str] = Query(None, description="只看某个模型实例的版本"),
    include_body: bool = Query(False, description="是否返回 snapshot_body 正文（体积大）"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    service: StrategyRegistryService = Depends(get_registry_service),
    versions: StrategyVersionService = Depends(get_version_service),
):
    """按 strategy_id 列版本（倒序）；未知策略返回空列表."""
    entry = await service.get_by_strategy_id(strategy_id)
    if entry is None:
        return Response.success(
            data={"items": [], "count": 0, "strategy_id": strategy_id, "coverage": _COVERAGE}
        )
    rows = await versions.list_versions(
        model_id=model_id, strategy_id=strategy_id, skip=skip, limit=limit
    )
    items: List[Dict[str, Any]] = []
    for row in rows:
        data = row.model_dump()
        if not include_body:
            data.pop("snapshot_body", None)
        items.append(data)
    return Response.success(
        data={"items": items, "count": len(items), "strategy_id": strategy_id, "coverage": _COVERAGE}
    )


@router.get("/{strategy_id}/runs", response_model=Response[dict], summary="策略运行台账")
async def list_strategy_runs(
    strategy_id: str,
    model_id: Optional[str] = Query(None, description="只看某个模型实例的运行"),
    run_kind: Optional[str] = Query(None, description="backtest / monitor / signal_replay"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    service: StrategyRegistryService = Depends(get_registry_service),
    runs: StrategyRunService = Depends(get_run_service),
):
    """回测与监控运行摘要（8 项指标白名单，不含曲线）."""
    entry = await service.get_by_strategy_id(strategy_id)
    if entry is None:
        return Response.success(
            data={"items": [], "count": 0, "strategy_id": strategy_id, "coverage": _COVERAGE}
        )
    query: Dict[str, Any] = {"strategy_id": strategy_id}
    if model_id:
        query["model_id"] = model_id
    if run_kind:
        query["run_kind"] = run_kind
    rows = await runs.list_runs(
        strategy_id=strategy_id, model_id=model_id, run_kind=run_kind, skip=skip, limit=limit
    )
    return Response.success(
        data={
            "items": [r.model_dump() for r in rows],
            "count": len(rows),
            "total": await _count(COL_STRATEGY_RUNS, query),
            "strategy_id": strategy_id,
            "coverage": _COVERAGE,
        }
    )


@router.get("/{strategy_id}/lineage", response_model=Response[dict], summary="策略血缘（版本↔模型↔运行）")
async def get_strategy_lineage(
    strategy_id: str,
    version_id: Optional[str] = Query(
        None, description="按版本反查：上游是哪些模型、下游是哪些运行"
    ),
    run_kind: Optional[str] = Query(None, description="下游运行时按种类过滤"),
    limit: int = Query(200, ge=1, le=500),
    service: StrategyRegistryService = Depends(get_registry_service),
    versions: StrategyVersionService = Depends(get_version_service),
    runs: StrategyRunService = Depends(get_run_service),
):
    """双向血缘：

    - 正向：``strategy_model:{model_id}`` --uses_config--> ``config_version:{version_id}``
      （S15 在发布/实盘动作时写入的边，确定性 edge_id 幂等）；
    - 反向：给定 ``version_id``，返回使用该版本的模型（边）与产生它的运行（台账）。
    """
    entry = await service.get_by_strategy_id(strategy_id)
    if entry is None:
        return Response.success(
            data={
                "strategy_id": strategy_id,
                "nodes": [],
                "edges": [],
                "versions": [],
                "runs": [],
                "coverage": _COVERAGE,
            }
        )

    models = await _models_for_entry(entry)
    model_nodes = [f"strategy_model:{m['model_id']}" for m in models]
    edge_query: Dict[str, Any] = {}
    if version_id:
        edge_query["to_node"] = f"config_version:{version_id}"
    elif model_nodes:
        edge_query["from_node"] = {"$in": model_nodes}
    else:
        edge_query["from_node"] = {"$in": []}

    edges: List[Dict[str, Any]] = []
    if edge_query.get("from_node") != {"$in": []}:
        cursor = _db()[COL_LINEAGE_EDGES].find(edge_query, projection={
            "edge_id": 1, "from_node": 1, "to_node": 1, "relation": 1, "created_at": 1,
        }).limit(limit)
        async for doc in cursor:
            edges.append({k: v for k, v in doc.items() if k != "_id"})

    node_ids: List[str] = []
    for edge in edges:
        for key in ("from_node", "to_node"):
            value = edge.get(key)
            if value and value not in node_ids:
                node_ids.append(value)
    nodes: List[Dict[str, Any]] = []
    if node_ids:
        cursor = _db()[COL_LINEAGE_NODES].find(
            {"node_id": {"$in": node_ids}},
            projection={"node_id": 1, "node_type": 1, "ref_id": 1, "created_at": 1},
        )
        async for doc in cursor:
            nodes.append({k: v for k, v in doc.items() if k != "_id"})

    version_rows = await versions.list_versions(strategy_id=strategy_id, limit=limit)
    version_items = [
        {
            "version_id": row.version_id,
            "model_id": row.model_id,
            "version_no": row.version_no,
            "source_action": row.source_action,
            "config_fingerprint": row.config_fingerprint,
            "created_at": row.created_at,
        }
        for row in version_rows
    ]

    downstream = []
    if version_id:
        matched = [
            r for r in await runs.list_runs(
                strategy_id=strategy_id, run_kind=run_kind, limit=limit
            )
            if r.config_version_id == version_id
        ]
        downstream = [r.model_dump() for r in matched]

    return Response.success(
        data={
            "strategy_id": strategy_id,
            "models": models,
            "nodes": nodes,
            "edges": edges,
            "versions": version_items,
            "runs": downstream,
            "filter": {"version_id": version_id, "run_kind": run_kind},
            "coverage": _COVERAGE,
        }
    )
