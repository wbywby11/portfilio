"""
销售域(Seller Domain) - L1静态画像定义
覆盖：销售人员信息 共 1 张表
"""
from ..models import DomainOverview, TableProfile


DOMAIN_OVERVIEW = DomainOverview(
    domain_code="seller",
    domain_name="销售域",
    description=(
        "维护销售人员的基础档案、岗位职级、所属部门、客户绑定数量、AUM 与销售业绩，"
        "支撑销售业绩排名、绩效核算与客户经理关系链路追踪。"
    ),
    table_count=1,
    tables=["dwd_sale_psn_info"],
    core_scenarios=[
        "销售业绩排名与绩效核算",
        "客户经理离职/调岗的客户交接管理",
        "区域/部门 AUM 分布分析",
        "销售层级（资深/总监/初级）能力建设",
        "客户-销售绑定关系追溯",
    ],
    key_entities=["SELLER_ID", "DEPT", "REGION"],
)


TABLE_PROFILES = {
    "dwd_sale_psn_info": TableProfile(
        table_name="dwd_sale_psn_info",
        domain="seller",
        display_name="销售人员信息表",
        purpose=(
            "维护销售人员的基础档案与业绩聚合视图，含部门、职级、入职日期、"
            "绑定客户数、托管规模 AUM、年初至今销售额、所在区域与状态，"
            "是销售-客户关系链路与销售业绩分析的主数据。"
        ),
        distribution=(
            "RANK 呈金字塔分布：JUNIOR > SENIOR > DIRECTOR；"
            "DEPT 集中在机构销售一/二部与零售销售部；REGION 在华东/华北/华南三大区域分布；"
            "AUM_TOTAL 与 RANK 强正相关（DIRECTOR 通常 50亿+，SENIOR 在 20-50 亿，JUNIOR <10 亿）；"
            "STATUS 大多为 ACTIVE，少量 LEAVE/RESIGNED。"
        ),
        trend=(
            "总人数变化平缓，每月新进/离职在个位数；CUSTOMER_CNT 与 AUM_TOTAL 月初更新；"
            "YTD_SALES 在年初为零并随月份递增；季末/年中考核前出现冲量。"
        ),
        anomaly=(
            "需关注：AUM_TOTAL 单月骤降 30% 以上（可能离职带走客户）；"
            "STATUS=ACTIVE 但 CUSTOMER_CNT=0 的空档销售；"
            "PHONE/EMAIL 缺失或重复；ENTRY_DT 为未来日期或异常早；"
            "RANK 与 AUM/年限严重不匹配。"
        ),
        scenarios=[
            "销售人员业绩排行榜（按 AUM/YTD_SALES）",
            "销售离职后客户交接影响评估",
            "区域/部门 AUM 与人均产能对比",
            "销售层级晋升与培养路径分析",
            "客户绑定的销售联系信息查询",
            "新入职销售的产能爬坡曲线",
        ],
        key_fields=[
            "SELLER_ID", "SELLER_NM", "DEPT", "TITLE",
            "PHONE", "EMAIL", "ENTRY_DT",
            "CUSTOMER_CNT", "AUM_TOTAL", "YTD_SALES",
            "RANK", "STATUS", "REGION",
        ],
        primary_keys=["SELLER_ID"],
        foreign_keys={},
    ),
}
