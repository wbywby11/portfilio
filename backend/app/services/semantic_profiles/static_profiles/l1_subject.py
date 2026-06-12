"""
主体域(Subject Domain) - L1 单表画像定义
覆盖 dwd_isr_* 共 3 张表，主键以 ISR_ID（机构）/CNTP_ID（交易对手）为锚点。
画像内容依据 mongo-seed/02_subject_domain.js 的 Schema 与业务语义编写。
"""
from ..models import DomainOverview, TableProfile

# ====================== 域概览 ======================
DOMAIN_OVERVIEW = DomainOverview(
    domain_code="subject",
    domain_name="主体域",
    description=(
        "聚焦债券发行人和交易对手两类金融主体，沉淀机构基础信息、财务报表、"
        "信用资质、授信额度、主协议签署等关键属性，是信用风险计量、"
        "对手方限额管理与合规白名单维护的主体侧底座。"
    ),
    table_count=3,
    tables=[
        "dwd_isr_institution",
        "dwd_isr_institution_finance",
        "dwd_isr_trd_cntp",
    ],
    core_scenarios=[
        "发行人主体识别与穿透分析",
        "机构财务健康度评估（杠杆/盈利/资产质量）",
        "主体信用评级与负面舆情联动",
        "交易对手授信占用与白名单管理",
        "行业景气度与发行人集群分析",
    ],
    key_entities=["ISR_ID", "CNTP_ID", "INDUSTRY_CD", "RPT_DT", "RPT_TYPE"],
)


# ====================== L1 单表画像 ======================
TABLE_PROFILES: dict[str, TableProfile] = {
    # 1. 机构（发行人）信息
    "dwd_isr_institution": TableProfile(
        table_name="dwd_isr_institution",
        domain="subject",
        display_name="机构（发行人）信息表",
        purpose=(
            "登记所有债券发行人/股票上市主体的全称、简称、机构类型、统一社会信用代码、"
            "行业分类、注册地、注册资本、上市状态、成立日期与最新主体评级，"
            "是发行人识别、行业归口与信用资质的主数据表。"
        ),
        distribution=(
            "ISR_TYPE 覆盖 GOV / POLICY_BANK / BANK / CORP / STATE_CORP / INSURANCE 六类，"
            "其中政策银行与商业银行评级集中于 AAA，民营企业评级在 AA+ 一档；"
            "注册地以北京/广东为主；上市状态（LIST_FLAG）半数以上为 Y。"
        ),
        trend=(
            "存量主体信息变更频率低（年度/不定期），主要变更字段为 LATEST_RATING、"
            "REG_CAP、LIST_FLAG；新主体随债券新发或股票上市增量入库。"
        ),
        anomaly=(
            "应关注：1) ISR_TYPE 与 INDUSTRY_CD 不匹配（如 BANK 但行业非 J6611/J6612）；"
            "2) CREDIT_CD 校验位错误或重复；3) LATEST_RATING 长期未更新（> 24 个月）；"
            "4) LIST_FLAG=Y 但找不到对应股票 AST_CD。"
        ),
        scenarios=[
            "发行人主体准入与白名单维护",
            "组合主体集中度（按 ISR_ID 聚合持仓）",
            "行业归口与板块敞口分析",
            "主体评级下迁穿透到债项影响范围",
            "上市/非上市主体披露能力对比",
        ],
        key_fields=[
            "ISR_ID", "ISR_NM", "ISR_SHORT_NM", "ISR_TYPE", "CREDIT_CD",
            "INDUSTRY_CD", "INDUSTRY_NM", "REG_PROV", "REG_CAP", "LIST_FLAG",
            "EST_DT", "LATEST_RATING", "RATING_AGENCY", "RATING_DT",
        ],
        primary_keys=["ISR_ID"],
        foreign_keys={},
    ),

    # 2. 机构财务报表
    "dwd_isr_institution_finance": TableProfile(
        table_name="dwd_isr_institution_finance",
        domain="subject",
        display_name="机构财务报表",
        purpose=(
            "存储发行人定期披露的财务三表关键聚合指标（总资产、总负债、净资产、"
            "营业收入、净利润、资产负债率、ROE、ROA），"
            "支撑信用资质评估、财务恶化预警与同业比较。"
        ),
        distribution=(
            "RPT_TYPE 覆盖 ANNUAL/SEMI/Q1/Q3，每个机构每期 1 条；"
            "银行/保险类资产负债率普遍在 0.90~0.94，地产类 0.75 左右；"
            "ROE 商业银行约 10%~15%、政策银行 5%~11%、地产/民企波动大可能为负；"
            "财政部仅有 REVENUE/NET_PROFIT 字段（公共预算口径）。"
        ),
        trend=(
            "年报集中在次年 3-4 月披露，半年报集中在 8-9 月；"
            "净利润同比变化反映行业景气度，房地产、民营企业近年呈现明显下滑趋势。"
        ),
        anomaly=(
            "应关注：1) NET_PROFIT 由正转负（盈利能力恶化）；"
            "2) ASSET_LIAB_RATIO 单期跳升 > 5pct；3) TOTAL_LIAB > TOTAL_ASSET（资不抵债）；"
            "4) RPT_DT 缺失/错位；5) 半年化 ROE 与年化口径混淆。"
        ),
        scenarios=[
            "发行人财务健康度评估",
            "杠杆率/偿债能力同业对比",
            "盈利波动与信用利差联动",
            "财务造假/数据异常筛查",
            "重点行业（地产/城投）景气度跟踪",
        ],
        key_fields=[
            "ISR_ID", "RPT_DT", "RPT_TYPE",
            "TOTAL_ASSET", "TOTAL_LIAB", "NET_ASSET",
            "REVENUE", "NET_PROFIT", "ASSET_LIAB_RATIO", "ROE", "ROA",
        ],
        primary_keys=["ISR_ID", "RPT_DT", "RPT_TYPE"],
        foreign_keys={"ISR_ID": "dwd_isr_institution.ISR_ID"},
    ),

    # 3. 交易对手
    "dwd_isr_trd_cntp": TableProfile(
        table_name="dwd_isr_trd_cntp",
        domain="subject",
        display_name="交易对手信息表",
        purpose=(
            "登记交易对手机构（券商、银行金市部、做市商、协会等）的基本信息、"
            "授信额度（CREDIT_LIMIT/USED_LIMIT）、主协议（NAFMII 等）、"
            "结算账户、白名单状态与可交易市场，"
            "支撑对手方授信管理、清算路由与合规审查。"
        ),
        distribution=(
            "CNTP_TYPE 以 SECURITIES、BANK、OTHER 为主；STATUS 大多为 ACTIVE；"
            "CREDIT_LIMIT 量级在 40~60 亿；USED_LIMIT 占用率在 20%~30%；"
            "MARKET 多覆盖 IB+SH+SZ；评级集中在 AAA，少量 NR；WHITELIST 多为 Y。"
        ),
        trend=(
            "对手方信息变更频率较低；额度调整、协议续签为主；"
            "新增对手方多伴随业务扩张（新增市场、新增产品线）。"
        ),
        anomaly=(
            "应关注：1) USED_LIMIT > CREDIT_LIMIT（额度透支）；"
            "2) WHITELIST=N 但仍有交易流水；3) STATUS 非 ACTIVE 但近期有交易；"
            "4) MASTER_AGREEMENT 缺失或过期；5) SETT_BANK/SETT_ACCT 为空但需结算的市场。"
        ),
        scenarios=[
            "对手方授信占用监控与额度告警",
            "白名单/黑名单合规检查",
            "主协议有效性核查（NAFMII 续签）",
            "交易路由与结算账户管理",
            "对手方集中度与系统重要性分析",
        ],
        key_fields=[
            "CNTP_ID", "CNTP_NM", "CNTP_SHORT_NM", "CNTP_TYPE", "STATUS",
            "CREDIT_LIMIT", "USED_LIMIT", "MASTER_AGREEMENT", "AGREEMENT_DT",
            "MARKET", "RATING", "WHITELIST", "SETT_BANK", "SETT_ACCT",
        ],
        primary_keys=["CNTP_ID"],
        foreign_keys={"LINKED_ISR_ID": "dwd_isr_institution.ISR_ID"},
    ),
}
