"""
画像合并器 - 将静态模板画像与动态统计合并为结构化文本
"""
from typing import Optional
from .models import (
    TableProfile, IntraDomainProfile, CrossDomainProfile,
    ResonanceProfile, DomainOverview, DynamicStats
)


class ProfileMerger:
    """将画像模型转换为LLM可读的结构化文本"""
    
    @staticmethod
    def format_overview(overviews: list[DomainOverview]) -> str:
        """格式化全域概览为文本"""
        lines = ["【ZY主题数据域全景概览】\n"]
        lines.append(f"共 {len(overviews)} 个业务域，覆盖资产管理全生命周期。\n")
        
        for ov in overviews:
            lines.append(f"■ {ov.domain_name}（{ov.domain_code}）— {ov.table_count}张表")
            lines.append(f"  功能：{ov.description}")
            lines.append(f"  核心场景：{'、'.join(ov.core_scenarios[:5])}")
            lines.append(f"  关键实体：{'、'.join(ov.key_entities)}")
            lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_table_profile(profile: TableProfile) -> str:
        """格式化L1单表画像为文本"""
        lines = [f"【L1单表画像 - {profile.display_name}（{profile.table_name}）】\n"]
        
        lines.append(f"【表名/作用】{profile.purpose}\n")
        lines.append(f"【分布特征】{profile.distribution}\n")
        lines.append(f"【趋势特征】{profile.trend}\n")
        lines.append(f"【异常与微观特征】{profile.anomaly}\n")
        lines.append(f"【核心字段】{', '.join(profile.key_fields)}")
        lines.append(f"【主键】{', '.join(profile.primary_keys)}")
        
        if profile.foreign_keys:
            fk_str = '、'.join(f"{k} → {v}" for k, v in profile.foreign_keys.items())
            lines.append(f"【外键关联】{fk_str}")
        
        if profile.record_count is not None:
            lines.append(f"\n【动态统计】当前记录数：{profile.record_count:,}")
        if profile.last_biz_date:
            lines.append(f"  最新业务日期：{profile.last_biz_date}")
        
        lines.append(f"\n【适用场景】适合Agent在{'、'.join(profile.scenarios)}时查询此表。")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_intra_domain_profile(profile: IntraDomainProfile) -> str:
        """格式化L2域内画像为文本"""
        lines = [f"【L2域内画像 - {profile.domain_name}（{profile.domain}域）】\n"]
        
        lines.append(f"【涉及表】{'、'.join(profile.tables_involved)}\n")
        lines.append(f"【域内结构特征】{profile.structure}\n")
        lines.append(f"【域内一致性特征】{profile.consistency}\n")
        lines.append(f"【域内分布特征】{profile.distribution}\n")
        lines.append(f"【域内异常特征】{profile.anomaly}\n")
        
        if profile.join_keys:
            jk_str = '、'.join(f"{k}: {v}" for k, v in profile.join_keys.items())
            lines.append(f"【关联键】{jk_str}\n")
        
        lines.append(f"【适用场景】适合Agent在{'、'.join(profile.scenarios)}时进行域内联合查询。")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_cross_domain_profile(profile: CrossDomainProfile) -> str:
        """格式化L3跨域画像为文本"""
        lines = [f"【L3跨域画像 - {profile.profile_name}】\n"]
        
        lines.append(f"【涉及域】{'、'.join(profile.domains_involved)}")
        lines.append(f"【涉及表】{'、'.join(profile.tables_involved)}")
        lines.append(f"【关联路径】{profile.join_path}\n")
        lines.append(f"【跨域结构特征】{profile.structure}\n")
        lines.append(f"【跨域分布特征】{profile.distribution}\n")
        lines.append(f"【跨域趋势特征】{profile.trend}\n")
        lines.append(f"【跨域异常特征】{profile.anomaly}\n")
        lines.append(f"【适用场景】适合Agent在{'、'.join(profile.scenarios)}时进行跨域穿透分析。")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_resonance_profile(profile: ResonanceProfile) -> str:
        """格式化L4联动画像为文本"""
        lines = [f"【L4域间联动画像 - {profile.scenario_name}】\n"]
        
        lines.append(f"【涉及域】{'、'.join(profile.domains_involved)}\n")
        lines.append(f"【跨域结构特征】{profile.structure}\n")
        lines.append(f"【共振/传染路径】{profile.resonance_chain}\n")
        lines.append(f"【极端脱钩/异动特征】{profile.extreme_features}\n")
        
        if profile.warning_indicators:
            lines.append("【跨域预警指标】")
            for ind in profile.warning_indicators:
                lines.append(f"  - {ind}")
            lines.append("")
        
        lines.append(f"【适用场景】适合Agent在{'、'.join(profile.scenarios)}时进行全局联动分析。")
        
        return "\n".join(lines)
