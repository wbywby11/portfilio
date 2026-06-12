from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class ProfileLevel(str, Enum):
    L1_TABLE = "l1_table"
    L2_INTRA_DOMAIN = "l2_intra_domain"
    L3_CROSS_DOMAIN = "l3_cross_domain"
    L4_RESONANCE = "l4_resonance"


class FieldProfile(BaseModel):
    """字段级语义画像（统一微观四层）"""
    field_name: str = Field(..., description="字段名")
    # -- L1 基础语义 --
    display_name: str = Field(..., description="中文名")
    data_type: str = Field(..., description="数据类型: string/number/date/enum/boolean")
    definition: str = Field("", description="业务定义")
    example_values: List[str] = Field(default_factory=list, description="示例值")
    unit: Optional[str] = Field(None, description="单位（如 %、元、BP、年）")
    enum_values: Optional[dict] = Field(None, description="枚举值映射")
    # -- L2 关联语义 --
    is_primary_key: bool = Field(False, description="是否主键")
    is_foreign_key: bool = Field(False, description="是否外键")
    references: Optional[str] = Field(None, description="外键引用 table.field")
    association_chains: List[str] = Field(default_factory=list, description="可穿透关联路径")
    # -- L3 特征语义 --
    sensitivity_level: str = Field("public", description="敏感等级: public/internal/confidential/secret")
    is_time_series: bool = Field(False, description="是否时序字段")
    is_computed: bool = Field(False, description="是否计算派生字段")
    tags: List[str] = Field(default_factory=list, description="特征标签: 主键/检索键/聚合键/排序键/维度/度量")
    # -- L4 质量语义（动态填充） --
    completeness: Optional[float] = Field(None, description="非空覆盖率 0-1")
    quality_level: Optional[str] = Field(None, description="质量等级: green/yellow/red")


class DomainOverview(BaseModel):
    """域级概览"""
    domain_code: str = Field(..., description="域代码，如 asset/product/market")
    domain_name: str = Field(..., description="域中文名称")
    description: str = Field(..., description="域功能描述")
    table_count: int = Field(..., description="包含表数量")
    tables: List[str] = Field(default_factory=list, description="表名列表")
    core_scenarios: List[str] = Field(default_factory=list, description="核心业务场景")
    key_entities: List[str] = Field(default_factory=list, description="核心实体/主键")


class TableProfile(BaseModel):
    """L1 单表画像"""
    table_name: str = Field(..., description="表名")
    domain: str = Field(..., description="所属域代码")
    display_name: str = Field("", description="表中文名")
    purpose: str = Field(..., description="表名/作用描述")
    distribution: str = Field(..., description="分布特征")
    trend: str = Field(..., description="趋势特征")
    anomaly: str = Field(..., description="异常与微观特征")
    scenarios: List[str] = Field(default_factory=list, description="适用场景")
    key_fields: List[str] = Field(default_factory=list, description="核心字段")
    primary_keys: List[str] = Field(default_factory=list, description="主键字段")
    foreign_keys: dict = Field(default_factory=dict, description="外键映射")
    # 动态部分
    record_count: Optional[int] = Field(None, description="实际记录数（动态）")
    field_coverage: Optional[dict] = Field(None, description="字段覆盖率（动态）")
    last_biz_date: Optional[str] = Field(None, description="最新业务日期（动态）")
    last_refreshed: Optional[str] = Field(None, description="画像刷新时间")
    field_profiles: List["FieldProfile"] = Field(default_factory=list, description="字段级画像列表")


class IntraDomainProfile(BaseModel):
    """L2 域内表间画像"""
    profile_id: str = Field(..., description="画像标识")
    domain: str = Field(..., description="所属域代码")
    domain_name: str = Field("", description="域中文名")
    tables_involved: List[str] = Field(default_factory=list, description="涉及表")
    structure: str = Field(..., description="域内结构特征")
    consistency: str = Field(..., description="域内一致性特征")
    distribution: str = Field(..., description="域内分布特征")
    anomaly: str = Field(..., description="域内异常特征")
    scenarios: List[str] = Field(default_factory=list, description="适用场景")
    join_keys: dict = Field(default_factory=dict, description="关联键映射")


class CrossDomainProfile(BaseModel):
    """L3 跨域表间画像"""
    profile_id: str = Field(..., description="画像标识")
    profile_name: str = Field(..., description="画像名称")
    domains_involved: List[str] = Field(default_factory=list, description="涉及域")
    tables_involved: List[str] = Field(default_factory=list, description="涉及表")
    join_path: str = Field(..., description="关联路径描述")
    structure: str = Field("", description="跨域结构特征")
    distribution: str = Field(..., description="跨域分布特征")
    trend: str = Field(..., description="跨域趋势特征")
    anomaly: str = Field(..., description="跨域异常特征")
    scenarios: List[str] = Field(default_factory=list, description="适用场景")


class ResonanceProfile(BaseModel):
    """L4 域间联动画像"""
    profile_id: str = Field(..., description="画像标识")
    scenario_name: str = Field(..., description="场景名称")
    domains_involved: List[str] = Field(default_factory=list, description="涉及域")
    structure: str = Field(..., description="跨域结构特征")
    resonance_chain: str = Field(..., description="共振/传染路径")
    extreme_features: str = Field(..., description="极端脱钩/异动特征")
    warning_indicators: List[str] = Field(default_factory=list, description="预警指标")
    scenarios: List[str] = Field(default_factory=list, description="适用场景")


class DynamicStats(BaseModel):
    """动态统计数据"""
    table_name: str
    record_count: int = 0
    field_coverage: dict = Field(default_factory=dict)
    numeric_stats: dict = Field(default_factory=dict)
    categorical_distribution: dict = Field(default_factory=dict)
    date_range: Optional[dict] = None
    recent_trend: Optional[dict] = None
    anomaly_ratio: Optional[float] = None
    computed_at: Optional[str] = None


class TableStatsProfile(BaseModel):
    """L5.1 单表统计画像 - 基于实时数据的四维度自然语言描述"""
    table_name: str
    domain: str
    physical_basis: str      # 物理基础: "X条记录，Y个字段，按日粒度覆盖Z时间段"
    distribution: str        # 截面分布: "AAA占比X%，城投和金融为主"
    trend: str               # 时序趋势: "近7日新增X条，整体呈Y趋势"
    anomaly: str             # 异常极值: "X个字段存在超3σ异常值"
    computed_at: str         # 生成时间 ISO格式
    raw_stats: Optional[dict] = None  # 原始DynamicStats引用


class DomainMacroProfile(BaseModel):
    """L5.2 数据域全局画像 - 域级宏观分布/趋势/预警"""
    domain_code: str
    domain_name: str
    boundary: str            # 域边界: "X张表，Y条记录，覆盖Z类实体"
    macro_distribution: str  # 宏观分布: "债券类占60%，存量集中于..."
    macro_trend: str         # 宏观趋势: "近期数据增量集中在..."
    system_warning: str      # 系统预警: "集中度偏高/覆盖率不足/数据滞后"
    computed_at: str
    tables_stats_summary: Optional[dict] = None


class CrossDomainResonance(BaseModel):
    """L5.3 跨域联动画像 - 域间因果共振分析"""
    scenario_id: str
    scenario_name: str
    domains_involved: List[str]
    scenario_definition: str   # 场景定义
    cross_structure: str       # 跨域结构
    resonance_trend: str       # 共振趋势
    extreme_decoupling: str    # 极端脱钩
    computed_at: str
