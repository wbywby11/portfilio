"""
语义画像 REST API

前缀：/api/v1/semantic
提供ZY数据域语义画像的查询、搜索和图谱可视化能力。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.schemas.response import Response

router = APIRouter()


def _get_engine():
    from app.services.semantic_profiles.profile_engine import ProfileEngine
    return ProfileEngine.get_instance()


def _get_dynamic_profiler():
    from app.services.semantic_profiles.dynamic_profiler import DynamicProfiler
    return DynamicProfiler.get_instance()


@router.get("/overview", summary="获取9域概览+动态统计")
async def get_overview():
    """获取9域概览 + 动态统计"""
    try:
        engine = _get_engine()
        overviews = await engine.get_overview()
        domains = [ov.model_dump() for ov in overviews]
        total_tables = sum(ov.table_count for ov in overviews)
        return Response.success(data={"domains": domains, "total_tables": total_tables})
    except Exception as e:
        logger.exception("[semantic] overview 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/table/{table_name}", summary="获取单表画像（含字段画像）")
async def get_table_profile(table_name: str, include_dynamic: bool = True):
    """获取L1单表画像（含字段画像）"""
    try:
        engine = _get_engine()
        profile = await engine.get_table_profile(table_name, include_dynamic)
        if not profile:
            raise HTTPException(status_code=404, detail=f"表 '{table_name}' 不存在")
        return Response.success(data=profile.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[semantic] table profile 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/domain/{domain_code}", summary="获取域内画像")
async def get_domain_profile(domain_code: str):
    """获取L2域内画像"""
    try:
        engine = _get_engine()
        profile = await engine.get_domain_profile(domain_code)
        if not profile:
            raise HTTPException(status_code=404, detail=f"域 '{domain_code}' 不存在")
        return Response.success(data=profile.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[semantic] domain profile 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph", summary="获取图谱数据（节点+边），用于前端可视化")
async def get_lineage_graph(domain: Optional[str] = None):
    """获取图谱数据（节点+边），用于前端ECharts可视化"""
    try:
        data = await _build_graph(domain)
        return Response.success(data=data)
    except Exception as e:
        logger.exception("[semantic] graph 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", summary="按关键词搜索画像")
async def search_profiles(q: str = Query(..., min_length=1, description="搜索关键词")):
    """按关键词搜索所有层级画像"""
    try:
        engine = _get_engine()
        results = await engine.search_profiles(q)
        return Response.success(data=results)
    except Exception as e:
        logger.exception("[semantic] search 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/table-data/{table_name}", summary="查询表数据（小窗预览用）")
async def get_table_data(
    table_name: str,
    limit: int = Query(20, ge=1, le=100, description="返回记录数上限"),
):
    """获取表的前N条数据用于预览小窗"""
    try:
        from app.config.database import Database
        from bson import ObjectId
        from datetime import datetime as _dt

        db = Database.get_database()
        if db is None:
            return Response.success(data={"records": [], "total": 0, "table_name": table_name})

        collection = db[table_name]
        total = await collection.count_documents({})
        cursor = collection.find({}, {"_id": 0}).limit(limit)
        raw_records = await cursor.to_list(length=limit)

        # 序列化特殊类型
        def _serialize(doc):
            result = {}
            for k, v in doc.items():
                if isinstance(v, ObjectId):
                    result[k] = str(v)
                elif isinstance(v, _dt):
                    result[k] = v.isoformat()
                elif isinstance(v, dict):
                    result[k] = _serialize(v)
                elif isinstance(v, list):
                    result[k] = [
                        _serialize(i) if isinstance(i, dict) else
                        (str(i) if isinstance(i, ObjectId) else
                         (i.isoformat() if isinstance(i, _dt) else i))
                        for i in v
                    ]
                else:
                    result[k] = v
            return result

        records = [_serialize(doc) for doc in raw_records]
        return Response.success(data={"records": records, "total": total, "table_name": table_name})
    except Exception as e:
        logger.exception("[semantic] table-data 异常: {}", e)
        return Response.success(data={"records": [], "total": 0, "table_name": table_name})


@router.get("/dynamic/{table_name}", summary="获取动态统计")
async def get_dynamic_stats(table_name: str):
    """获取指定表的动态统计数据"""
    try:
        profiler = _get_dynamic_profiler()
        stats = await profiler.compute_stats(table_name)
        if not stats:
            return Response.success(data={
                "table_name": table_name,
                "record_count": 0,
                "field_coverage": {},
                "numeric_stats": {},
                "categorical_distribution": {},
                "date_range": None,
                "recent_trend": None,
                "anomaly_ratio": None,
                "computed_at": None,
            })
        return Response.success(data=stats.model_dump())
    except Exception as e:
        logger.exception("[semantic] dynamic stats 异常: {}", e)
        # MongoDB未连接时返回空统计而非报错
        return Response.success(data={
            "table_name": table_name,
            "record_count": 0,
            "field_coverage": {},
            "numeric_stats": {},
            "categorical_distribution": {},
            "date_range": None,
            "recent_trend": None,
            "anomaly_ratio": None,
            "computed_at": None,
        })


@router.get("/cross-domain", summary="列出所有L3跨域画像")
async def list_cross_domain_profiles():
    """列出所有L3跨域画像"""
    try:
        engine = _get_engine()
        profiles = list(engine._cross_domain_profiles.values())
        return Response.success(data=[p.model_dump() for p in profiles])
    except Exception as e:
        logger.exception("[semantic] cross-domain list 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cross-domain/{profile_id}", summary="获取指定L3跨域画像")
async def get_cross_domain_profile(profile_id: str):
    """获取指定L3跨域画像"""
    try:
        engine = _get_engine()
        profile = await engine.get_cross_domain_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"跨域画像 '{profile_id}' 不存在")
        return Response.success(data=profile.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[semantic] cross-domain profile 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resonance", summary="列出所有L4联动画像")
async def list_resonance_profiles():
    """列出所有L4联动画像"""
    try:
        engine = _get_engine()
        profiles = list(engine._resonance_profiles.values())
        return Response.success(data=[p.model_dump() for p in profiles])
    except Exception as e:
        logger.exception("[semantic] resonance list 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resonance/{profile_id}", summary="获取指定L4联动画像")
async def get_resonance_profile(profile_id: str):
    """获取指定L4联动画像"""
    try:
        engine = _get_engine()
        profile = await engine.get_resonance_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail=f"联动画像 '{profile_id}' 不存在")
        return Response.success(data=profile.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[semantic] resonance profile 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── 内部辅助 ───────────────────────────────────────────────

async def _build_graph(domain_filter: Optional[str] = None) -> dict:
    """构建图谱数据：从所有 TableProfile 的 foreign_keys 提取节点和边

    边的语义增强：包含字段中文名、关联表中文名、关系描述，
    供前端在 tooltip 和边上展示可读的关联解释。
    """
    engine = _get_engine()

    nodes = []
    edges = []

    # 构建表名 → 显示名 / 字段名 → 中文名 / 字段名 → 定义的快查表
    table_display: dict[str, str] = {}      # table_name → display_name
    field_display: dict[str, dict[str, str]] = {}  # table_name → {field: display_name}
    field_defs: dict[str, dict[str, str]] = {}     # table_name → {field: definition}
    for tn, prof in engine._table_profiles.items():
        table_display[tn] = prof.display_name or tn
        fmap = {}
        dmap = {}
        for fp in (prof.field_profiles or []):
            if fp.field_name and fp.display_name:
                fmap[fp.field_name] = fp.display_name
            if fp.field_name and fp.definition:
                dmap[fp.field_name] = fp.definition
        field_display[tn] = fmap
        field_defs[tn] = dmap

    def _field_zh(tbl: str, fld: str) -> str:
        """获取字段的中文显示名，回退为字段名本身"""
        return field_display.get(tbl, {}).get(fld, fld)

    def _field_def(tbl: str, fld: str) -> str:
        """获取字段的业务定义，回退为空串"""
        return field_defs.get(tbl, {}).get(fld, "")

    # 从所有表画像构建节点
    for table_name, profile in engine._table_profiles.items():
        if domain_filter and profile.domain != domain_filter:
            continue
        nodes.append({
            "id": table_name,
            "name": profile.display_name,
            "domain": profile.domain,
            "category": profile.domain,  # ECharts graph 的分类
        })

        # 从 foreign_keys 构建语义增强边
        for fk_field, ref in profile.foreign_keys.items():
            target_table = ref.split(".")[0] if "." in ref else ref
            target_field = ref.split(".")[1] if "." in ref else fk_field

            # 中文名解析
            src_zh = table_display.get(table_name, table_name)
            tgt_zh = table_display.get(target_table, target_table)
            fk_zh = _field_zh(table_name, fk_field)
            tgt_fk_zh = _field_zh(target_table, target_field)

            # 语义关系描述：用中文拼接关联解释
            if fk_zh != fk_field and tgt_fk_zh != target_field:
                relation_desc = f"通过「{fk_zh}」({fk_field}) 关联 {tgt_zh} 的「{tgt_fk_zh}」({target_field})"
            elif fk_zh != fk_field:
                relation_desc = f"通过「{fk_zh}」({fk_field}) 关联 {tgt_zh}"
            else:
                relation_desc = f"通过 {fk_field} 关联 {tgt_zh}"

            # 字段含义定义
            fk_def = _field_def(table_name, fk_field)
            tgt_fk_def = _field_def(target_table, target_field)

            edges.append({
                "source": table_name,
                "target": target_table,
                "label": fk_field,
                "type": "foreign_key",
                # 语义增强字段
                "source_field": fk_field,
                "target_field": target_field,
                "field_display": fk_zh,
                "target_field_display": tgt_fk_zh,
                "field_definition": fk_def,
                "target_field_definition": tgt_fk_def,
                "source_display": src_zh,
                "target_display": tgt_zh,
                "relation_desc": relation_desc,
            })

    # 域信息
    domains = []
    for code, overview in engine._domain_overviews.items():
        if domain_filter and code != domain_filter:
            continue
        domains.append({
            "code": code,
            "name": overview.domain_name,
            "description": overview.description,
            "table_count": overview.table_count,
        })

    return {"nodes": nodes, "edges": edges, "domains": domains}


# ============ 质量与监控API ============

@router.get("/quality/{table_name}", summary="获取单表质量评分")
async def get_table_quality(table_name: str):
    """获取单表质量评分（四维度加权）"""
    try:
        from app.services.semantic_profiles.quality_engine import QualityEngine
        engine = QualityEngine.get_instance()
        score = await engine.compute_table_quality(table_name)
        return Response.success(data=score.model_dump())
    except Exception as e:
        logger.exception("[semantic] quality 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quality-batch", summary="批量获取质量评分")
async def get_batch_quality(domain: Optional[str] = None, limit: int = Query(20, le=50)):
    """批量获取质量评分（按域筛选）"""
    try:
        from app.services.semantic_profiles.quality_engine import QualityEngine
        from app.services.semantic_profiles.profile_engine import ProfileEngine

        qe = QualityEngine.get_instance()
        pe = ProfileEngine.get_instance()

        tables = []
        for name, profile in pe._table_profiles.items():
            if domain and profile.domain != domain:
                continue
            tables.append(name)
            if len(tables) >= limit:
                break

        results = []
        for table in tables:
            score = await qe.compute_table_quality(table)
            results.append(score.model_dump())

        return Response.success(data={"total": len(results), "scores": results})
    except Exception as e:
        logger.exception("[semantic] quality-batch 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/coverage", summary="获取语义覆盖率统计")
async def get_coverage_stats():
    """获取语义覆盖率统计（表级+字段级）"""
    try:
        from app.services.semantic_profiles.quality_engine import QualityEngine
        engine = QualityEngine.get_instance()
        stats = await engine.compute_coverage_stats()
        return Response.success(data=stats.model_dump())
    except Exception as e:
        logger.exception("[semantic] coverage 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", summary="获取血缘健康度报告")
async def get_health_report():
    """获取血缘健康度报告（孤儿节点/断链/覆盖率）"""
    try:
        from app.services.semantic_profiles.quality_engine import QualityEngine
        engine = QualityEngine.get_instance()
        report = await engine.compute_health_report()
        return Response.success(data=report.model_dump())
    except Exception as e:
        logger.exception("[semantic] health 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============ 血缘图谱API ============

@router.get("/lineage/graph", summary="获取持久化血缘图谱")
async def get_persisted_lineage_graph(domain: Optional[str] = None):
    """获取持久化血缘图谱（节点+边）"""
    try:
        from app.services.lineage_service import LineageService
        service = LineageService.get_instance()
        result = await service.get_graph(domain=domain)
        return Response.success(data=result)
    except Exception as e:
        logger.exception("[semantic] lineage graph 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lineage/impact", summary="影响分析")
async def get_lineage_impact(node_id: str = Query(..., description="节点ID"), direction: str = Query("downstream", description="方向: upstream/downstream")):
    """影响分析：查找指定节点的上游或下游影响范围"""
    try:
        from app.services.lineage_service import LineageService
        service = LineageService.get_instance()
        result = await service.get_impact_analysis(node_id, direction)
        return Response.success(data=result)
    except Exception as e:
        logger.exception("[semantic] lineage impact 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lineage/stats", summary="血缘统计")
async def get_lineage_stats():
    """获取血缘统计信息（节点/边数量、类型分布）"""
    try:
        from app.services.lineage_service import LineageService
        service = LineageService.get_instance()
        result = await service.get_stats()
        return Response.success(data=result)
    except Exception as e:
        logger.exception("[semantic] lineage stats 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============ L5 统计语义画像 API ============

def _get_stats_engine():
    from app.services.semantic_profiles.stats_profile_engine import StatsProfileEngine
    return StatsProfileEngine.get_instance()


@router.get("/stats-profile/{table_name}", summary="获取L5.1单表统计画像（已缓存）")
async def get_stats_profile(table_name: str):
    """获取L5.1单表统计画像（已缓存）。无缓存时返回 data=null，由前端触发生成。"""
    try:
        engine = _get_stats_engine()
        profile = await engine.get_table_stats_profile(table_name)
        if not profile:
            return Response.success(data=None, message="画像尚未生成，请点击生成按钮")
        return Response.success(data=profile.model_dump())
    except Exception as e:
        logger.exception("[semantic] stats-profile get 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stats-profile/{table_name}/generate", summary="生成/刷新L5.1单表统计画像")
async def generate_stats_profile(table_name: str):
    """生成/刷新L5.1单表统计画像"""
    try:
        engine = _get_stats_engine()
        profile = await engine.generate_table_stats_profile(table_name)
        return Response.success(data=profile.model_dump())
    except Exception as e:
        logger.exception("[semantic] stats-profile generate 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/domain-macro/{domain_code}", summary="获取L5.2域全局画像（已缓存）")
async def get_domain_macro(domain_code: str):
    """获取L5.2域全局画像（已缓存）。无缓存时返回 data=null，由前端触发生成。"""
    try:
        engine = _get_stats_engine()
        profile = await engine.get_domain_macro(domain_code)
        if not profile:
            return Response.success(data=None, message="画像尚未生成，请点击生成按钮")
        return Response.success(data=profile.model_dump())
    except Exception as e:
        logger.exception("[semantic] domain-macro get 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domain-macro/{domain_code}/generate", summary="生成/刷新L5.2域全局画像")
async def generate_domain_macro(domain_code: str):
    """生成/刷新L5.2域全局画像"""
    try:
        engine = _get_stats_engine()
        profile = await engine.generate_domain_macro(domain_code)
        return Response.success(data=profile.model_dump())
    except Exception as e:
        logger.exception("[semantic] domain-macro generate 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cross-resonance", summary="获取L5.3跨域联动画像列表")
async def get_cross_resonance_list():
    """获取L5.3跨域联动画像列表"""
    try:
        engine = _get_stats_engine()
        profiles = await engine.get_cross_resonance_list()
        return Response.success(data=[p.model_dump() for p in profiles])
    except Exception as e:
        logger.exception("[semantic] cross-resonance list 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cross-resonance/{scenario_id}", summary="获取指定L5.3跨域联动画像")
async def get_cross_resonance_detail(scenario_id: str):
    """获取指定L5.3跨域联动画像。无缓存时返回 data=null，由前端触发生成。"""
    try:
        engine = _get_stats_engine()
        profile = await engine.get_cross_resonance(scenario_id)
        if not profile:
            return Response.success(data=None, message="画像尚未生成，请点击生成按钮")
        return Response.success(data=profile.model_dump())
    except Exception as e:
        logger.exception("[semantic] cross-resonance detail 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cross-resonance/generate", summary="生成/刷新所有L5.3跨域联动画像")
async def generate_cross_resonance():
    """生成/刷新所有L5.3跨域联动画像"""
    try:
        engine = _get_stats_engine()
        profiles = await engine.generate_cross_resonance()
        return Response.success(data=[p.model_dump() for p in profiles])
    except Exception as e:
        logger.exception("[semantic] cross-resonance generate 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/domain/{domain_code}/full", summary="获取域完整画像")
async def get_domain_full(domain_code: str):
    """获取域完整画像（概览+L2+动态统计+L5.2）"""
    try:
        engine = _get_engine()
        profiler = _get_dynamic_profiler()
        stats_engine = _get_stats_engine()

        # 域概览
        overview = engine._domain_overviews.get(domain_code)
        if not overview:
            raise HTTPException(status_code=404, detail=f"域 '{domain_code}' 不存在")

        # L2画像
        l2_profile = engine._intra_domain_profiles.get(domain_code)

        # 动态统计汇总
        total_records = 0
        coverages = []
        latest_date = None
        for table_name in overview.tables:
            try:
                stats = await profiler.compute_stats(table_name)
                if stats:
                    total_records += stats.record_count
                    if stats.field_coverage:
                        avg_cov = sum(stats.field_coverage.values()) / len(stats.field_coverage)
                        coverages.append(avg_cov)
                    if stats.date_range and stats.date_range.get("max"):
                        dr_max = stats.date_range["max"]
                        if latest_date is None or dr_max > latest_date:
                            latest_date = dr_max
            except Exception:
                continue

        dynamic_summary = {
            "total_records": total_records,
            "avg_coverage": round(sum(coverages) / len(coverages), 3) if coverages else 0.0,
            "latest_date": latest_date,
        }

        # L5.2宏观画像
        l5_macro = await stats_engine.get_domain_macro(domain_code)

        return Response.success(data={
            "overview": overview.model_dump(),
            "l2_profile": l2_profile.model_dump() if l2_profile else None,
            "dynamic_summary": dynamic_summary,
            "l5_macro": l5_macro.model_dump() if l5_macro else None,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[semantic] domain full 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))
