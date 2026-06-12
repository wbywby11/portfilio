"""
L5 统计语义画像引擎
基于实时MongoDB数据生成自然语言统计描述
三层架构: L5.1单表 → L5.2域级 → L5.3跨域

LLM集成: 优先调用 DeepSeek (OpenAI 兼容接口) 生成业务洞察描述，
调用失败时 fallback 到本地模板拼接。
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Optional, List

from loguru import logger

from .models import (
    TableStatsProfile,
    DomainMacroProfile,
    CrossDomainResonance,
    DynamicStats,
)


class StatsProfileEngine:
    """L5 统计语义画像引擎

    职责：
    1. L5.1 基于DynamicStats生成单表四维度自然语言画像
    2. L5.2 聚合域内所有表统计，生成域全局画像
    3. L5.3 跨域联动分析，生成共振/脱钩画像
    """

    _instance: Optional["StatsProfileEngine"] = None

    # MongoDB集合名
    COLLECTION_TABLE_STATS = "semantic_stats_profiles"
    COLLECTION_DOMAIN_MACRO = "semantic_domain_macro"
    COLLECTION_CROSS_RESONANCE = "semantic_cross_resonance"

    # LLM 调用超时（秒）
    LLM_TIMEOUT_SECONDS = 30

    def __init__(self):
        self._llm_client = None

    @classmethod
    def get_instance(cls) -> "StatsProfileEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ─── LLM 调用基础设施 ─────────────────────────────────────

    def _get_llm_client(self):
        """延迟初始化 AsyncOpenAI 客户端，复用项目现有 .env 配置"""
        if self._llm_client is None:
            from openai import AsyncOpenAI
            api_key = os.getenv("LLM_API_KEY", "")
            base_url = os.getenv("LLM_BASE_URL", "")
            if not api_key or not base_url:
                logger.warning("[L5-LLM] 未配置 LLM_API_KEY/LLM_BASE_URL，将跳过LLM调用")
                return None
            self._llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        return self._llm_client

    async def _call_llm_for_profile(self, prompt: str) -> Optional[dict]:
        """调用LLM生成画像描述，返回解析后的 dict；失败返回 None。双保险：
        - 超时控制：30秒内未返回视为失败
        - 任何异常不向上报，以免影响整体画像生成
        """
        client = self._get_llm_client()
        if client is None:
            return None
        model = os.getenv("LLM_MODEL", "deepseek-chat")
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是金融数据语义分析专家，精通资产、交易、估值、风险、"
                                "市场等投研业务领域。请基于给定的统计数据，生成有业务洞察力的自然语言"
                                "描述，避免纯数字罗列，优先表达业务含义。输出必须为严格JSON格式。"
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=2000,
                ),
                timeout=self.LLM_TIMEOUT_SECONDS,
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                return None
            # 剖除 ```json ... ``` 或 ``` ... ``` 包裹
            if "```json" in content:
                content = content.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in content:
                parts = content.split("```")
                if len(parts) >= 3:
                    content = parts[1].strip()
            # 如仍不是JSON起始，尝试定位首个 {
            if not content.startswith("{"):
                lb = content.find("{")
                rb = content.rfind("}")
                if 0 <= lb < rb:
                    content = content[lb : rb + 1]
            result = json.loads(content)
            if isinstance(result, dict):
                return result
            return None
        except asyncio.TimeoutError:
            logger.warning("[L5-LLM] LLM调用超时({}s)，fallback到模板生成", self.LLM_TIMEOUT_SECONDS)
            return None
        except Exception as e:
            logger.warning("[L5-LLM] LLM画像生成失败: {}", e)
            return None

    # ─── L5.1 单表统计画像 ───────────────────────────────────────

    async def generate_table_stats_profile(self, table_name: str) -> TableStatsProfile:
        """生成/刷新L5.1单表统计画像（LLM优先，失败fallback模板）"""
        try:
            from .dynamic_profiler import DynamicProfiler
            from .profile_engine import ProfileEngine

            # 1. 获取动态统计
            profiler = DynamicProfiler.get_instance()
            stats = await profiler.compute_stats(table_name)

            # 2. 获取静态画像元信息
            engine = ProfileEngine.get_instance()
            table_profile = engine._table_profiles.get(table_name)
            domain = table_profile.domain if table_profile else "unknown"

            # 3. 默认使用模板生成作为fallback
            physical_basis = self._build_physical_basis(stats)
            distribution = self._build_distribution(stats)
            trend = self._build_trend(stats)
            anomaly = self._build_anomaly(stats)

            # 4. 尝试LLM生成业务语义描述
            llm_result = await self._call_llm_for_profile(
                self._build_l51_prompt(table_name, stats, table_profile)
            )
            if llm_result:
                physical_basis = llm_result.get("physical_basis") or physical_basis
                distribution = llm_result.get("distribution") or distribution
                trend = llm_result.get("trend") or trend
                anomaly = llm_result.get("anomaly") or anomaly
                logger.info("[L5.1] LLM生成成功 [{}]", table_name)
            else:
                logger.info("[L5.1] 使用模板生成 [{}]", table_name)

            now = datetime.now().isoformat()
            profile = TableStatsProfile(
                table_name=table_name,
                domain=domain,
                physical_basis=physical_basis,
                distribution=distribution,
                trend=trend,
                anomaly=anomaly,
                computed_at=now,
                raw_stats=stats.model_dump() if stats else None,
            )

            # 5. 存入MongoDB（upsert by table_name）
            await self._upsert_table_stats(profile)

            return profile

        except Exception as e:
            logger.exception("[L5.1] 单表统计画像生成异常 [{}]: {}", table_name, e)
            return TableStatsProfile(
                table_name=table_name,
                domain="unknown",
                physical_basis="数据不足，暂无法生成",
                distribution="数据不足，暂无法生成",
                trend="数据不足，暂无法生成",
                anomaly="数据不足，暂无法生成",
                computed_at=datetime.now().isoformat(),
            )

    async def get_table_stats_profile(self, table_name: str) -> Optional[TableStatsProfile]:
        """从MongoDB获取已缓存的L5.1"""
        try:
            db = self._get_db()
            if db is None:
                return None
            doc = await db[self.COLLECTION_TABLE_STATS].find_one({"table_name": table_name})
            if doc:
                doc.pop("_id", None)
                return TableStatsProfile(**doc)
            return None
        except Exception as e:
            logger.warning("[L5.1] 获取缓存失败 [{}]: {}", table_name, e)
            return None

    # ─── L5.2 域全局画像 ─────────────────────────────────────────

    async def generate_domain_macro(self, domain_code: str) -> DomainMacroProfile:
        """生成/刷新L5.2域全局画像"""
        try:
            from .profile_engine import ProfileEngine
            from .dynamic_profiler import DynamicProfiler

            engine = ProfileEngine.get_instance()
            profiler = DynamicProfiler.get_instance()

            # 1. 获取域概览
            overview = engine._domain_overviews.get(domain_code)
            if not overview:
                return DomainMacroProfile(
                    domain_code=domain_code,
                    domain_name="未知域",
                    boundary="数据不足，暂无法生成",
                    macro_distribution="数据不足，暂无法生成",
                    macro_trend="数据不足，暂无法生成",
                    system_warning="数据不足，暂无法生成",
                    computed_at=datetime.now().isoformat(),
                )

            tables = overview.tables
            domain_name = overview.domain_name

            # 2. 获取域内所有表的动态统计
            table_stats: dict = {}
            total_records = 0
            for t in tables:
                try:
                    s = await profiler.compute_stats(t)
                    if s:
                        table_stats[t] = s
                        total_records += s.record_count
                except Exception:
                    continue

            # 3. 默认使用模板生成作为fallback
            entity_types = len(tables)
            boundary = f"{len(tables)}张表，共{total_records}条记录，覆盖{entity_types}类数据"
            macro_distribution = self._build_macro_distribution(table_stats, total_records)
            macro_trend = self._build_macro_trend(table_stats)
            system_warning = self._build_system_warning(table_stats, total_records)

            # 4. 尝试LLM生成业务语义描述
            llm_result = await self._call_llm_for_profile(
                self._build_l52_prompt(domain_code, domain_name, overview, table_stats, total_records)
            )
            if llm_result:
                boundary = llm_result.get("boundary") or boundary
                macro_distribution = llm_result.get("macro_distribution") or macro_distribution
                macro_trend = llm_result.get("macro_trend") or macro_trend
                system_warning = llm_result.get("system_warning") or system_warning
                logger.info("[L5.2] LLM生成成功 [{}]", domain_code)
            else:
                logger.info("[L5.2] 使用模板生成 [{}]", domain_code)

            # 汇总信息（供前端同时展示原始指标）
            tables_summary = {
                t: {
                    "record_count": s.record_count,
                    "anomaly_ratio": s.anomaly_ratio,
                    "field_count": len(s.field_coverage) if s.field_coverage else 0,
                    "date_range": s.date_range,
                }
                for t, s in table_stats.items()
            }

            now = datetime.now().isoformat()
            profile = DomainMacroProfile(
                domain_code=domain_code,
                domain_name=domain_name,
                boundary=boundary,
                macro_distribution=macro_distribution,
                macro_trend=macro_trend,
                system_warning=system_warning,
                computed_at=now,
                tables_stats_summary=tables_summary,
            )

            # 4. 存入MongoDB
            await self._upsert_domain_macro(profile)

            return profile

        except Exception as e:
            logger.exception("[L5.2] 域全局画像生成异常 [{}]: {}", domain_code, e)
            return DomainMacroProfile(
                domain_code=domain_code,
                domain_name="未知域",
                boundary="数据不足，暂无法生成",
                macro_distribution="数据不足，暂无法生成",
                macro_trend="数据不足，暂无法生成",
                system_warning="数据不足，暂无法生成",
                computed_at=datetime.now().isoformat(),
            )

    async def get_domain_macro(self, domain_code: str) -> Optional[DomainMacroProfile]:
        """从MongoDB获取已缓存的L5.2"""
        try:
            db = self._get_db()
            if db is None:
                return None
            doc = await db[self.COLLECTION_DOMAIN_MACRO].find_one({"domain_code": domain_code})
            if doc:
                doc.pop("_id", None)
                return DomainMacroProfile(**doc)
            return None
        except Exception as e:
            logger.warning("[L5.2] 获取缓存失败 [{}]: {}", domain_code, e)
            return None

    # ─── L5.3 跨域联动画像 ───────────────────────────────────────

    async def generate_cross_resonance(self) -> List[CrossDomainResonance]:
        """生成/刷新所有L5.3跨域联动画像"""
        try:
            from .profile_engine import ProfileEngine

            engine = ProfileEngine.get_instance()

            # 1. 获取L3跨域画像和L4联动画像
            cross_domain_profiles = engine._cross_domain_profiles
            resonance_profiles = engine._resonance_profiles

            results: List[CrossDomainResonance] = []

            # 2. 对每个L4联动场景生成L5.3
            for profile_id, resonance in resonance_profiles.items():
                try:
                    # 获取涉及域的L5.2宏观画像
                    domain_macros = {}
                    for domain in resonance.domains_involved:
                        macro = await self.get_domain_macro(domain)
                        if macro:
                            domain_macros[domain] = macro

                    # 场景定义
                    scenario_definition = (
                        f"{resonance.scenario_name}，涉及域: "
                        f"{', '.join(resonance.domains_involved)}"
                    )
                    
                    # 默认使用模板生成作为fallback
                    cross_structure = self._build_cross_structure(
                        resonance, cross_domain_profiles
                    )
                    resonance_trend = self._build_resonance_trend(domain_macros)
                    extreme_decoupling = self._build_extreme_decoupling(domain_macros)
                    
                    # 尝试LLM生成业务语义描述
                    llm_result = await self._call_llm_for_profile(
                        self._build_l53_prompt(
                            resonance, domain_macros, cross_domain_profiles
                        )
                    )
                    if llm_result:
                        scenario_definition = llm_result.get("scenario_definition") or scenario_definition
                        cross_structure = llm_result.get("cross_structure") or cross_structure
                        resonance_trend = llm_result.get("resonance_trend") or resonance_trend
                        extreme_decoupling = llm_result.get("extreme_decoupling") or extreme_decoupling
                        logger.info("[L5.3] LLM生成成功 [{}]", profile_id)
                    else:
                        logger.info("[L5.3] 使用模板生成 [{}]", profile_id)

                    now = datetime.now().isoformat()
                    item = CrossDomainResonance(
                        scenario_id=profile_id,
                        scenario_name=resonance.scenario_name,
                        domains_involved=resonance.domains_involved,
                        scenario_definition=scenario_definition,
                        cross_structure=cross_structure,
                        resonance_trend=resonance_trend,
                        extreme_decoupling=extreme_decoupling,
                        computed_at=now,
                    )
                    results.append(item)
                except Exception as e:
                    logger.warning("[L5.3] 单场景生成异常 [{}]: {}", profile_id, e)
                    continue

            # 3. 存入MongoDB
            await self._upsert_cross_resonance(results)

            return results

        except Exception as e:
            logger.exception("[L5.3] 跨域联动画像生成异常: {}", e)
            return []

    async def get_cross_resonance_list(self) -> List[CrossDomainResonance]:
        """从MongoDB获取所有L5.3"""
        try:
            db = self._get_db()
            if db is None:
                return []
            cursor = db[self.COLLECTION_CROSS_RESONANCE].find({})
            results = []
            async for doc in cursor:
                doc.pop("_id", None)
                results.append(CrossDomainResonance(**doc))
            return results
        except Exception as e:
            logger.warning("[L5.3] 获取缓存列表失败: {}", e)
            return []

    async def get_cross_resonance(self, scenario_id: str) -> Optional[CrossDomainResonance]:
        """获取指定L5.3"""
        try:
            db = self._get_db()
            if db is None:
                return None
            doc = await db[self.COLLECTION_CROSS_RESONANCE].find_one(
                {"scenario_id": scenario_id}
            )
            if doc:
                doc.pop("_id", None)
                return CrossDomainResonance(**doc)
            return None
        except Exception as e:
            logger.warning("[L5.3] 获取缓存失败 [{}]: {}", scenario_id, e)
            return None

    # ─── 内部辅助方法 ─────────────────────────────────────────────

    @staticmethod
    def _get_db():
        """获取MongoDB数据库实例"""
        from app.config.database import Database
        return Database.get_database()

    # -- L5.1 描述构建 --

    def _build_physical_basis(self, stats: Optional[DynamicStats]) -> str:
        """构建物理基础描述"""
        if not stats or stats.record_count == 0:
            return "暂无数据记录"
        parts = [f"{stats.record_count}条记录"]
        if stats.field_coverage:
            parts.append(f"{len(stats.field_coverage)}个字段")
        if stats.date_range:
            dr_min = stats.date_range.get("min", "")
            dr_max = stats.date_range.get("max", "")
            if dr_min and dr_max:
                parts.append(f"按日粒度覆盖{dr_min}至{dr_max}")
        return "，".join(parts)

    def _build_distribution(self, stats: Optional[DynamicStats]) -> str:
        """构建截面分布描述"""
        if not stats or not stats.categorical_distribution:
            return "暂无分类分布数据"
        descriptions = []
        for field, dist in list(stats.categorical_distribution.items())[:3]:
            if not dist:
                continue
            total = sum(dist.values())
            top_items = sorted(dist.items(), key=lambda x: x[1], reverse=True)[:3]
            parts = []
            for name, count in top_items:
                pct = round(count / total * 100, 1) if total > 0 else 0
                parts.append(f"{name}占{pct}%")
            descriptions.append(f"{field}: {', '.join(parts)}")
        return "；".join(descriptions) if descriptions else "分类维度均匀分布"

    def _build_trend(self, stats: Optional[DynamicStats]) -> str:
        """构建时序趋势描述"""
        if not stats or not stats.recent_trend:
            return "暂无趋势数据"
        trend = stats.recent_trend
        values = list(trend.values())
        if not values:
            return "暂无趋势数据"
        total_recent = sum(values)
        avg_daily = round(total_recent / len(values), 1)
        # 判断趋势方向
        if len(values) >= 2:
            first_half = sum(values[:len(values) // 2])
            second_half = sum(values[len(values) // 2:])
            if second_half > first_half * 1.2:
                direction = "上升"
            elif second_half < first_half * 0.8:
                direction = "下降"
            else:
                direction = "平稳"
        else:
            direction = "平稳"
        return f"近{len(values)}日新增{total_recent}条，日均{avg_daily}条，整体呈{direction}趋势"

    def _build_anomaly(self, stats: Optional[DynamicStats]) -> str:
        """构建异常极值描述"""
        if not stats:
            return "暂无异常检测数据"
        if stats.anomaly_ratio is None or stats.anomaly_ratio == 0:
            return "未检测到显著异常值"
        # 估算异常字段数
        anomaly_fields = 0
        if stats.numeric_stats:
            anomaly_fields = max(1, int(len(stats.numeric_stats) * stats.anomaly_ratio))
        pct = round(stats.anomaly_ratio * 100, 2)
        return f"{anomaly_fields}个数值字段存在超3σ异常值，异常样本占比{pct}%"

    # -- L5.2 描述构建 --

    def _build_macro_distribution(self, table_stats: dict, total_records: int) -> str:
        """构建宏观分布描述"""
        if not table_stats or total_records == 0:
            return "域内暂无有效数据"
        # 按记录数排序，取前3
        sorted_tables = sorted(
            table_stats.items(), key=lambda x: x[1].record_count, reverse=True
        )[:3]
        parts = []
        for table_name, stats in sorted_tables:
            pct = round(stats.record_count / total_records * 100, 1) if total_records > 0 else 0
            parts.append(f"{table_name}占{pct}%({stats.record_count}条)")
        return "数据分布: " + ", ".join(parts)

    def _build_macro_trend(self, table_stats: dict) -> str:
        """构建宏观趋势描述"""
        if not table_stats:
            return "域内暂无趋势数据"
        growing = 0
        declining = 0
        stable = 0
        for _, stats in table_stats.items():
            if not stats.recent_trend:
                stable += 1
                continue
            values = list(stats.recent_trend.values())
            if len(values) >= 2:
                first_half = sum(values[:len(values) // 2])
                second_half = sum(values[len(values) // 2:])
                if second_half > first_half * 1.2:
                    growing += 1
                elif second_half < first_half * 0.8:
                    declining += 1
                else:
                    stable += 1
            else:
                stable += 1
        total = growing + declining + stable
        if growing > declining and growing > stable:
            return f"域整体呈增长态势（{growing}/{total}张表数据增长）"
        elif declining > growing and declining > stable:
            return f"域整体呈下降态势（{declining}/{total}张表数据减少）"
        else:
            return f"域整体保持稳定（{stable}/{total}张表数据平稳）"

    def _build_system_warning(self, table_stats: dict, total_records: int) -> str:
        """构建系统预警描述"""
        if not table_stats:
            return "无预警"
        warnings = []
        # 检测集中度: 单表占比>50%
        for table_name, stats in table_stats.items():
            if total_records > 0 and stats.record_count / total_records > 0.5:
                pct = round(stats.record_count / total_records * 100, 1)
                warnings.append(f"集中度偏高: {table_name}占{pct}%")
                break
        # 检测覆盖率: 平均覆盖率<60%
        coverages = []
        for _, stats in table_stats.items():
            if stats.field_coverage:
                avg_cov = sum(stats.field_coverage.values()) / len(stats.field_coverage)
                coverages.append(avg_cov)
        if coverages:
            avg_all = sum(coverages) / len(coverages)
            if avg_all < 0.6:
                warnings.append(f"字段覆盖率不足: 平均{round(avg_all * 100, 1)}%")
        # 检测时效性: 最新日期滞后>7天
        from datetime import timedelta
        now = datetime.now()
        for table_name, stats in table_stats.items():
            if stats.date_range and stats.date_range.get("max"):
                try:
                    max_date_str = stats.date_range["max"][:10]
                    max_date = datetime.strptime(max_date_str, "%Y-%m-%d")
                    if (now - max_date) > timedelta(days=7):
                        days_lag = (now - max_date).days
                        warnings.append(f"数据滞后: {table_name}最新数据距今{days_lag}天")
                        break
                except (ValueError, TypeError):
                    continue
        return "；".join(warnings) if warnings else "无预警"

    # -- L5.3 描述构建 --

    def _build_cross_structure(self, resonance, cross_domain_profiles: dict) -> str:
        """构建跨域结构描述"""
        # 从L3跨域画像中找到相关的join_path
        related_paths = []
        for _, cdp in cross_domain_profiles.items():
            # 检查是否有域重叠
            if set(cdp.domains_involved) & set(resonance.domains_involved):
                related_paths.append(cdp.join_path)
        if related_paths:
            return "关联路径: " + "; ".join(related_paths[:3])
        return f"涉及{len(resonance.domains_involved)}个域的联动结构"

    def _build_resonance_trend(self, domain_macros: dict) -> str:
        """构建共振趋势描述"""
        if not domain_macros:
            return "暂无足够域级数据进行共振分析"
        trends = {}
        for domain, macro in domain_macros.items():
            if "增长" in macro.macro_trend:
                trends[domain] = "增长"
            elif "下降" in macro.macro_trend:
                trends[domain] = "下降"
            else:
                trends[domain] = "稳定"
        # 判断是否同向
        unique_trends = set(trends.values())
        if len(unique_trends) == 1:
            direction = list(unique_trends)[0]
            return f"各域趋势同向({direction})，呈正向共振"
        elif "增长" in unique_trends and "下降" in unique_trends:
            growing = [d for d, t in trends.items() if t == "增长"]
            declining = [d for d, t in trends.items() if t == "下降"]
            return (
                f"域间趋势背离: {', '.join(growing)}增长 vs {', '.join(declining)}下降"
            )
        else:
            return "域间趋势基本一致，部分域波动"

    def _build_extreme_decoupling(self, domain_macros: dict) -> str:
        """构建极端脱钩描述"""
        if not domain_macros:
            return "暂无足够数据检测脱钩"
        # 检测严重背离：一升一降
        growing_domains = []
        declining_domains = []
        for domain, macro in domain_macros.items():
            if "增长" in macro.macro_trend:
                growing_domains.append(domain)
            elif "下降" in macro.macro_trend:
                declining_domains.append(domain)
        if growing_domains and declining_domains:
            return (
                f"检测到极端脱钩: {', '.join(growing_domains)}域数据增长，"
                f"而{', '.join(declining_domains)}域数据下降，存在背离风险"
            )
        return "未检测到极端脱钩现象"

    # -- LLM Prompt 构建 --

    def _build_l51_prompt(
        self,
        table_name: str,
        stats: Optional[DynamicStats],
        table_profile,
    ) -> str:
        """构建 L5.1 单表统计画像的 LLM Prompt"""
        domain_info = f"所属域: {table_profile.domain}" if table_profile else ""
        purpose_info = f"表作用: {table_profile.purpose}" if table_profile else ""
        display_name = (
            f"表中文名: {table_profile.display_name}"
            if (table_profile and table_profile.display_name)
            else ""
        )

        stats_payload = {
            "record_count": stats.record_count if stats else 0,
            "field_coverage": stats.field_coverage if stats else {},
            "numeric_stats": stats.numeric_stats if stats else {},
            "categorical_distribution": stats.categorical_distribution if stats else {},
            "date_range": stats.date_range if stats else None,
            "recent_trend": stats.recent_trend if stats else None,
            "anomaly_ratio": stats.anomaly_ratio if stats else None,
        }
        stats_json = json.dumps(stats_payload, ensure_ascii=False, indent=2, default=str)

        return f"""请为数据表 "{table_name}" 生成L5.1统计语义画像。

{display_name}
{domain_info}
{purpose_info}

实时统计数据:
{stats_json}

请输出JSON，包含以下四个字段：
{{
  "physical_basis": "物理基础描述(数据规模、字段覆盖、时间跨度、数据粒度，体现业务含义)",
  "distribution": "截面分布描述(主要分类维度的分布特征，体现业务结构)",
  "trend": "时序趋势描述(数据增长方向、波动特征、关键拐点)",
  "anomaly": "异常极值描述(异常检测发现、潜在风险点、需关注事项)"
}}

要求：
- 每个字段100-300字符
- 使用金融业务术语而非纯统计数据罗列
- 如果某维度数据不足则描述为"当前数据量不足以支撑该维度分析"
- 输出严格JSON，不包含任何额外说明文本
"""

    def _build_l52_prompt(
        self,
        domain_code: str,
        domain_name: str,
        overview,
        table_stats: dict,
        total_records: int,
    ) -> str:
        """构建 L5.2 域全局画像的 LLM Prompt"""
        scenarios = (
            ", ".join(overview.core_scenarios)
            if overview and overview.core_scenarios
            else ""
        )
        description = overview.description if overview else ""

        # 构建表级汇总
        tables_payload = {}
        for t, s in table_stats.items():
            tables_payload[t] = {
                "record_count": s.record_count,
                "field_count": len(s.field_coverage) if s.field_coverage else 0,
                "date_range": s.date_range,
                "anomaly_ratio": s.anomaly_ratio,
                "recent_trend": s.recent_trend,
                "top_categorical": {
                    field: dict(sorted(dist.items(), key=lambda x: x[1], reverse=True)[:5])
                    for field, dist in (s.categorical_distribution or {}).items()
                },
            }
        tables_json = json.dumps(tables_payload, ensure_ascii=False, indent=2, default=str)

        return f"""请为数据域 "{domain_name}"({domain_code}) 生成L5.2全局画像。

域描述: {description}
核心场景: {scenarios}
表数量: {len(table_stats)}
总记录数: {total_records}

域内各表统计汇总:
{tables_json}

请输出JSON，包含以下四个字段：
{{
  "boundary": "域边界描述(覆盖的实体类型、业务范围、数据规模)",
  "macro_distribution": "宏观分布描述(表间数据量占比、主要业务集中点、结构性特征)",
  "macro_trend": "宏观趋势描述(域整体增长动能、重点表变化、业务信号)",
  "system_warning": "系统预警描述(集中度/覆盖率/时效性等问题，无问题请明确说明)"
}}

要求：
- 每个字段100-300字符
- 使用金融业务术语，关联业务场景与数据特征
- 输出严格JSON，不包含任何额外说明文本
"""

    def _build_l53_prompt(
        self,
        resonance,
        domain_macros: dict,
        cross_domain_profiles: dict,
    ) -> str:
        """构建 L5.3 跨域联动画像的 LLM Prompt"""
        # 收集涉及域的 L5.2 画像摘要
        macros_payload = {}
        for d, m in domain_macros.items():
            macros_payload[d] = {
                "domain_name": m.domain_name,
                "boundary": m.boundary,
                "macro_trend": m.macro_trend,
                "system_warning": m.system_warning,
            }

        # 收集 L3 关联路径
        join_paths = []
        for _, cdp in cross_domain_profiles.items():
            if set(cdp.domains_involved) & set(resonance.domains_involved):
                join_paths.append({
                    "name": cdp.profile_name,
                    "path": cdp.join_path,
                })

        macros_json = json.dumps(macros_payload, ensure_ascii=False, indent=2, default=str)
        join_paths_json = json.dumps(join_paths, ensure_ascii=False, indent=2, default=str)

        return f"""请为跨域联动场景 "{resonance.scenario_name}" 生成L5.3画像。

场景ID: {resonance.profile_id}
涉及域: {', '.join(resonance.domains_involved)}
共振链路: {resonance.resonance_chain}
极端特征: {resonance.extreme_features}
预警指标: {', '.join(resonance.warning_indicators) if resonance.warning_indicators else '无'}

所涉域的L5.2宏观画像:
{macros_json}

L3跨域关联路径:
{join_paths_json}

请输出JSON，包含以下四个字段：
{{
  "scenario_definition": "场景定义(业务含义、跨域联动逻辑、应用价值)",
  "cross_structure": "跨域结构(域间关联路径、关键联接点、传导机制)",
  "resonance_trend": "共振趋势(各域趋势同向/背离、联动强度、周期特征)",
  "extreme_decoupling": "极端脱钩(检测到的背离现象、风险实例、预警信号)"
}}

要求：
- 每个字段100-300字符
- 表达跨域业务逻辑与响应机制
- 输出严格JSON，不包含任何额外说明文本
"""

    # ─── MongoDB持久化 ────────────────────────────────────────────

    async def _upsert_table_stats(self, profile: TableStatsProfile) -> None:
        """L5.1持久化（upsert by table_name）"""
        try:
            db = self._get_db()
            if db is None:
                return
            await db[self.COLLECTION_TABLE_STATS].update_one(
                {"table_name": profile.table_name},
                {"$set": profile.model_dump()},
                upsert=True,
            )
        except Exception as e:
            logger.warning("[L5.1] 持久化失败 [{}]: {}", profile.table_name, e)

    async def _upsert_domain_macro(self, profile: DomainMacroProfile) -> None:
        """L5.2持久化（upsert by domain_code）"""
        try:
            db = self._get_db()
            if db is None:
                return
            await db[self.COLLECTION_DOMAIN_MACRO].update_one(
                {"domain_code": profile.domain_code},
                {"$set": profile.model_dump()},
                upsert=True,
            )
        except Exception as e:
            logger.warning("[L5.2] 持久化失败 [{}]: {}", profile.domain_code, e)

    async def _upsert_cross_resonance(self, profiles: List[CrossDomainResonance]) -> None:
        """L5.3持久化（清空后重建）"""
        try:
            db = self._get_db()
            if db is None:
                return
            coll = db[self.COLLECTION_CROSS_RESONANCE]
            # 清空旧数据后批量插入
            await coll.delete_many({})
            if profiles:
                await coll.insert_many([p.model_dump() for p in profiles])
        except Exception as e:
            logger.warning("[L5.3] 持久化失败: {}", e)
