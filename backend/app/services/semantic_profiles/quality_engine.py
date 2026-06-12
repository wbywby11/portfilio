"""
数据质量评分引擎
- 四维度质量评估：完整性(completeness)、一致性(consistency)、时效性(timeliness)、准确性(accuracy)
- 加权综合评分
- 质量等级判定 (green/yellow/red)
- 语义覆盖率统计
- 血缘健康度检测
"""
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from loguru import logger
from pydantic import BaseModel, Field


class QualityScore(BaseModel):
    """单表质量评分"""
    table_name: str
    domain: str = ""
    # 四维度分项（0-100分）
    completeness_score: float = 0.0   # 完整性（字段非空率加权平均）
    consistency_score: float = 0.0    # 一致性（外键匹配率、类型一致性）
    timeliness_score: float = 0.0     # 时效性（数据新鲜度）
    accuracy_score: float = 0.0       # 准确性（值域合规率）
    # 综合分
    overall_score: float = 0.0        # 加权综合分
    quality_level: str = "unknown"    # green(>=80) / yellow(60-79) / red(<60)
    # 明细
    issues: List[str] = Field(default_factory=list)  # 具体问题描述
    computed_at: Optional[str] = None


class CoverageStats(BaseModel):
    """语义覆盖率统计"""
    total_tables: int = 0
    tables_with_profile: int = 0
    table_coverage_rate: float = 0.0   # 表级画像覆盖率
    total_fields: int = 0
    fields_with_profile: int = 0
    field_coverage_rate: float = 0.0   # 字段画像覆盖率
    domains_covered: List[str] = Field(default_factory=list)
    uncovered_tables: List[str] = Field(default_factory=list)


class HealthReport(BaseModel):
    """血缘健康度报告"""
    total_nodes: int = 0
    total_edges: int = 0
    orphan_nodes: List[str] = Field(default_factory=list)  # 孤儿节点（无边连接）
    broken_links: List[str] = Field(default_factory=list)  # 断链（引用不存在的节点）
    coverage_rate: float = 0.0         # 血缘覆盖率（有血缘记录的表/总表数）
    freshness_days: Optional[float] = None  # 最新血缘记录距今天数
    health_level: str = "unknown"      # green/yellow/red
    issues: List[str] = Field(default_factory=list)


class QualityEngine:
    """数据质量评分引擎（单例）"""

    _instance: Optional["QualityEngine"] = None

    # 质量维度权重
    WEIGHTS = {
        "completeness": 0.35,
        "consistency": 0.25,
        "timeliness": 0.25,
        "accuracy": 0.15
    }

    @classmethod
    def get_instance(cls) -> "QualityEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def compute_table_quality(self, table_name: str) -> QualityScore:
        """计算单表质量评分"""
        from .dynamic_profiler import DynamicProfiler

        score = QualityScore(table_name=table_name, computed_at=datetime.now().isoformat())

        try:
            profiler = DynamicProfiler.get_instance()
            stats = await profiler.compute_stats(table_name)

            if not stats or stats.record_count == 0:
                score.quality_level = "red"
                score.issues.append("表无数据")
                return score

            # 推断域
            score.domain = self._infer_domain(table_name)

            # 1. 完整性评分 — 基于字段非空覆盖率
            if stats.field_coverage:
                avg_coverage = sum(stats.field_coverage.values()) / len(stats.field_coverage)
                score.completeness_score = avg_coverage * 100
                if avg_coverage < 0.7:
                    score.issues.append(f"字段平均非空率仅 {avg_coverage:.1%}")
            else:
                score.completeness_score = 50.0

            # 2. 一致性评分 — 基于分类字段的规范性
            score.consistency_score = self._assess_consistency(stats)

            # 3. 时效性评分 — 基于最新BIZ_DT距今天数
            score.timeliness_score = self._assess_timeliness(stats)

            # 4. 准确性评分 — 基于异常率
            if stats.anomaly_ratio is not None:
                score.accuracy_score = max(0, (1.0 - stats.anomaly_ratio * 10)) * 100
            else:
                score.accuracy_score = 75.0  # 无法计算时给默认分

            # 综合分
            score.overall_score = (
                score.completeness_score * self.WEIGHTS["completeness"] +
                score.consistency_score * self.WEIGHTS["consistency"] +
                score.timeliness_score * self.WEIGHTS["timeliness"] +
                score.accuracy_score * self.WEIGHTS["accuracy"]
            )

            # 等级判定
            if score.overall_score >= 80:
                score.quality_level = "green"
            elif score.overall_score >= 60:
                score.quality_level = "yellow"
            else:
                score.quality_level = "red"

        except Exception as e:
            logger.warning(f"质量评分计算失败 [{table_name}]: {e}")
            score.quality_level = "unknown"
            score.issues.append(f"计算异常: {str(e)}")

        return score

    def _assess_consistency(self, stats) -> float:
        """评估一致性"""
        if not stats.categorical_distribution:
            return 75.0
        # 如果分类字段值分布合理（无异常值），给高分
        total_categories = len(stats.categorical_distribution)
        if total_categories == 0:
            return 75.0
        # 简单启发式：有值的分类字段越多，一致性越好
        return min(100, 60 + total_categories * 5)

    def _assess_timeliness(self, stats) -> float:
        """评估时效性"""
        if not stats.date_range or "max" not in stats.date_range:
            return 50.0
        try:
            max_date_str = str(stats.date_range["max"])
            # 尝试解析日期（支持yyyyMMdd和ISO格式）
            if len(max_date_str) == 8 and max_date_str.isdigit():
                max_date = datetime.strptime(max_date_str, "%Y%m%d")
            else:
                max_date = datetime.fromisoformat(max_date_str[:10])

            days_old = (datetime.now() - max_date).days
            if days_old <= 1:
                return 100.0
            elif days_old <= 7:
                return 90.0
            elif days_old <= 30:
                return 70.0
            elif days_old <= 90:
                return 50.0
            else:
                return 30.0
        except Exception:
            return 50.0

    async def compute_coverage_stats(self) -> CoverageStats:
        """计算语义覆盖率"""
        from .profile_engine import ProfileEngine

        engine = ProfileEngine.get_instance()
        stats = CoverageStats()

        # 从DOMAIN_METADATA获取总表数
        try:
            from app.services.collection_registry import DOMAIN_METADATA
            all_known_tables: set = set()
            for domain_key, domain_data in DOMAIN_METADATA.items():
                tables_dict = domain_data.get("tables", {})
                for table_name in tables_dict:
                    all_known_tables.add(table_name)
            stats.total_tables = len(all_known_tables) if all_known_tables else 82
        except ImportError:
            all_known_tables = set()
            stats.total_tables = 82

        # 有画像的表
        profiled_tables = set(engine._table_profiles.keys())
        stats.tables_with_profile = len(profiled_tables)
        stats.table_coverage_rate = stats.tables_with_profile / max(stats.total_tables, 1)

        # 有字段画像的表
        total_fields = 0
        fields_with_profile = 0
        for table_name, profile in engine._table_profiles.items():
            field_count = len(profile.key_fields) if profile.key_fields else 5  # 估计
            total_fields += field_count
            fields_with_profile += len(profile.field_profiles)

        stats.total_fields = total_fields
        stats.fields_with_profile = fields_with_profile
        stats.field_coverage_rate = fields_with_profile / max(total_fields, 1)

        # 已覆盖的域
        stats.domains_covered = list(engine._domain_overviews.keys())

        # 未覆盖的表
        stats.uncovered_tables = list(all_known_tables - profiled_tables)[:20]  # 最多显示20个

        return stats

    async def compute_health_report(self) -> HealthReport:
        """计算血缘健康度"""
        report = HealthReport()

        try:
            from app.services.lineage_service import LineageService
            service = LineageService.get_instance()

            graph = await service.get_graph()
            nodes = graph.get("nodes", [])
            edges = graph.get("edges", [])

            report.total_nodes = len(nodes)
            report.total_edges = len(edges)

            if not nodes:
                report.health_level = "yellow"
                report.issues.append("暂无血缘数据")
                return report

            # 检测孤儿节点
            connected_nodes: set = set()
            for edge in edges:
                connected_nodes.add(edge.get("source_id", ""))
                connected_nodes.add(edge.get("target_id", ""))

            all_node_ids = {n.get("node_id", "") for n in nodes}
            orphans = all_node_ids - connected_nodes
            report.orphan_nodes = list(orphans)[:10]

            # 检测断链
            for edge in edges:
                src = edge.get("source_id", "")
                tgt = edge.get("target_id", "")
                if src and src not in all_node_ids:
                    report.broken_links.append(f"边引用不存在的源: {src}")
                if tgt and tgt not in all_node_ids:
                    report.broken_links.append(f"边引用不存在的目标: {tgt}")
            report.broken_links = report.broken_links[:10]

            # 覆盖率
            storage_nodes = [n for n in nodes if n.get("node_type") == "STORAGE_MONGO"]
            report.coverage_rate = len(storage_nodes) / 82.0  # 82张业务表

            # 新鲜度
            latest_time = None
            for edge in edges:
                ct = edge.get("created_at") or edge.get("metadata", {}).get("import_time")
                if ct and (latest_time is None or ct > latest_time):
                    latest_time = ct
            if latest_time:
                try:
                    lt = datetime.fromisoformat(latest_time[:19])
                    report.freshness_days = (datetime.now() - lt).total_seconds() / 86400
                except Exception:
                    pass

            # 健康等级
            issues_count = len(report.orphan_nodes) + len(report.broken_links)
            if issues_count == 0 and report.coverage_rate > 0.5:
                report.health_level = "green"
            elif issues_count < 5 and report.coverage_rate > 0.2:
                report.health_level = "yellow"
            else:
                report.health_level = "red"

            if report.orphan_nodes:
                report.issues.append(f"{len(report.orphan_nodes)}个孤儿节点")
            if report.broken_links:
                report.issues.append(f"{len(report.broken_links)}条断链")
            if report.coverage_rate < 0.3:
                report.issues.append(f"血缘覆盖率仅{report.coverage_rate:.0%}")

        except ImportError:
            report.health_level = "yellow"
            report.issues.append("LineageService未就绪")
        except Exception as e:
            logger.warning(f"健康度检测失败: {e}")
            report.health_level = "unknown"

        return report

    def _infer_domain(self, table_name: str) -> str:
        prefix_map = {
            "dwd_ast_": "asset", "dwd_isr_": "subject", "dwd_ptl_": "product",
            "dwd_val_": "valuation", "dwd_trn_": "transaction", "dwd_sale_": "seller",
            "dwd_cust_": "customer", "dwd_rsk_": "risk", "dwd_mkt_": "market"
        }
        for prefix, domain in prefix_map.items():
            if table_name.startswith(prefix):
                return domain
        return ""
