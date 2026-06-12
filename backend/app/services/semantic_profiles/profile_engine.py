"""
语义画像引擎 - 协调静态画像模板与动态计算
"""
from typing import Optional, List
from .models import (
    ProfileLevel, DomainOverview, TableProfile,
    IntraDomainProfile, CrossDomainProfile, ResonanceProfile
)


class ProfileEngine:
    """
    语义画像引擎主类
    
    职责：
    1. 管理和检索静态画像（基于Schema和业务规则）
    2. 调用动态计算引擎获取实时统计
    3. 合并静态+动态输出完整画像
    4. 支持按关键词搜索相关画像
    """
    
    _instance: Optional["ProfileEngine"] = None
    
    def __init__(self):
        self._static_profiles_loaded = False
        self._domain_overviews: dict[str, DomainOverview] = {}
        self._table_profiles: dict[str, TableProfile] = {}
        self._intra_domain_profiles: dict[str, IntraDomainProfile] = {}
        self._cross_domain_profiles: dict[str, CrossDomainProfile] = {}
        self._resonance_profiles: dict[str, ResonanceProfile] = {}
    
    @classmethod
    def get_instance(cls) -> "ProfileEngine":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load_static_profiles()
        return cls._instance
    
    def _load_static_profiles(self):
        """加载所有静态画像定义"""
        if self._static_profiles_loaded:
            return
        from .static_profiles import (
            get_all_domain_overviews,
            get_all_table_profiles,
            get_all_intra_domain_profiles,
            get_all_cross_domain_profiles,
            get_all_resonance_profiles
        )
        self._domain_overviews = get_all_domain_overviews()
        self._table_profiles = get_all_table_profiles()
        self._intra_domain_profiles = get_all_intra_domain_profiles()
        self._cross_domain_profiles = get_all_cross_domain_profiles()
        self._resonance_profiles = get_all_resonance_profiles()
        self._static_profiles_loaded = True
    
    async def get_overview(self) -> List[DomainOverview]:
        """获取全域概览"""
        return list(self._domain_overviews.values())
    
    async def get_table_profile(self, table_name: str, include_dynamic: bool = True) -> Optional[TableProfile]:
        """获取L1单表画像"""
        profile = self._table_profiles.get(table_name)
        if profile and include_dynamic:
            profile = await self._enrich_with_dynamic(profile)
        return profile
    
    async def get_domain_profile(self, domain: str) -> Optional[IntraDomainProfile]:
        """获取L2域内画像"""
        return self._intra_domain_profiles.get(domain)
    
    async def get_cross_domain_profile(self, profile_id: str) -> Optional[CrossDomainProfile]:
        """获取L3跨域画像"""
        return self._cross_domain_profiles.get(profile_id)
    
    async def get_resonance_profile(self, profile_id: str) -> Optional[ResonanceProfile]:
        """获取L4联动画像"""
        return self._resonance_profiles.get(profile_id)
    
    async def search_profiles(self, query: str) -> dict:
        """按关键词搜索所有层级的相关画像"""
        results = {
            "l1_tables": [],
            "l2_domains": [],
            "l3_cross_domain": [],
            "l4_resonance": []
        }
        query_lower = query.lower()
        
        # 搜索L1
        for name, profile in self._table_profiles.items():
            if self._match_profile(query_lower, profile):
                results["l1_tables"].append(name)
        
        # 搜索L2
        for name, profile in self._intra_domain_profiles.items():
            if self._match_intra_domain(query_lower, profile):
                results["l2_domains"].append(name)
        
        # 搜索L3
        for name, profile in self._cross_domain_profiles.items():
            if self._match_cross_domain(query_lower, profile):
                results["l3_cross_domain"].append(name)
        
        # 搜索L4
        for name, profile in self._resonance_profiles.items():
            if self._match_resonance(query_lower, profile):
                results["l4_resonance"].append(name)
        
        return results
    
    def _match_profile(self, query: str, profile: TableProfile) -> bool:
        """检查L1画像是否匹配搜索词"""
        searchable = f"{profile.table_name} {profile.display_name} {profile.purpose} {' '.join(profile.scenarios)}".lower()
        return any(kw in searchable for kw in query.split())
    
    def _match_intra_domain(self, query: str, profile: IntraDomainProfile) -> bool:
        searchable = f"{profile.domain} {profile.domain_name} {profile.structure} {' '.join(profile.scenarios)}".lower()
        return any(kw in searchable for kw in query.split())
    
    def _match_cross_domain(self, query: str, profile: CrossDomainProfile) -> bool:
        searchable = f"{profile.profile_name} {profile.join_path} {' '.join(profile.scenarios)}".lower()
        return any(kw in searchable for kw in query.split())
    
    def _match_resonance(self, query: str, profile: ResonanceProfile) -> bool:
        searchable = f"{profile.scenario_name} {profile.resonance_chain} {' '.join(profile.scenarios)}".lower()
        return any(kw in searchable for kw in query.split())
    
    async def _enrich_with_dynamic(self, profile: TableProfile) -> TableProfile:
        """用动态统计数据丰富静态画像"""
        try:
            from .dynamic_profiler import DynamicProfiler
            dynamic = await DynamicProfiler.get_instance().compute_stats(profile.table_name)
            if dynamic:
                profile = profile.model_copy(update={
                    "record_count": dynamic.record_count,
                    "field_coverage": dynamic.field_coverage,
                    "last_biz_date": dynamic.date_range.get("max") if dynamic.date_range else None,
                    "last_refreshed": dynamic.computed_at
                })
        except Exception:
            pass  # 动态数据不可用时优雅降级
        return profile
