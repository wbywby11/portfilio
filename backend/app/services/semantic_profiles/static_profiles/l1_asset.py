"""
资产域(Asset Domain) - L1 单表画像定义
覆盖 dwd_ast_* 共 12 张表，主键以 AST_CD（证券代码）为锚点。
画像内容依据 mongo-seed/01_asset_domain.js 的 Schema 与业务语义编写。
"""
from ..models import DomainOverview, TableProfile, FieldProfile

# ====================== 域概览 ======================
DOMAIN_OVERVIEW = DomainOverview(
    domain_code="asset",
    domain_name="资产域",
    description=(
        "以证券代码 AST_CD 为锚点，沉淀全量金融资产的元数据、估值、收益率、"
        "现金流、质押、评级、担保、条款、持有人、交易流水及生命周期事件，"
        "是组合管理、风险监控、合规审查、归因分析的资产侧底座。"
    ),
    table_count=14,
    tables=[
        "dwd_ast_info",
        "dwd_ast_info_ch",
        "dwd_ast_info_zg",
        "dwd_ast_yield_info",
        "dwd_ast_cf_plan",
        "dwd_ast_pledge",
        "dwd_ast_flow_trade",
        "dwd_ast_rating",
        "dwd_ast_guarantor",
        "dwd_ast_clause",
        "dwd_ast_holder",
        "dwd_ast_event",
        "assets",
        "asset_prices",
    ],
    core_scenarios=[
        "资产准入与白名单筛查",
        "中债/中证双源估值对比与定价异常识别",
        "现金流到期预警与利息计提核对",
        "质押率与回购融资能力评估",
        "信用评级迁移与下调预警",
        "含权债行权窗口管理（PUT/CALL/利率调整）",
        "持有人结构集中度分析",
        "资产生命周期事件追踪（付息/违约/回售/绿色披露）",
    ],
    key_entities=["AST_CD", "AST_TYPE", "ISR_ID", "BIZ_DT", "TRADE_ID", "code", "asset_code"],
)


# ====================== L1 单表画像 ======================
TABLE_PROFILES: dict[str, TableProfile] = {
    # 1. 资产基础信息
    "dwd_ast_info": TableProfile(
        table_name="dwd_ast_info",
        domain="asset",
        display_name="资产基础信息表",
        purpose=(
            "全量金融资产主数据宽表，统一登记债券（国债/政策金融债/中票/企业债）、"
            "股票、ETF、ABS 等品种的代码、名称、类型、发行人、上市/到期日、票面利率、"
            "发行规模、交易市场、债券期限等核心元属性，是资产识别的唯一锚点。"
        ),
        distribution=(
            "资产类型以 BOND 为主体（覆盖 CGB/POLICY/MTN/ENTERPRISE 子类），"
            "其次为 STOCK（A_SHARE）、FUND（ETF）、ABS。市场分布上以银行间为主、"
            "上交所/深交所次之；币种集中于 CNY；BOND_TERM 集中在 3/5/10/30 年。"
        ),
        trend=(
            "资产入库随发行节奏增长，季末与年初冲量明显；超长期特别国债、绿色债、"
            "ABS 等创新品种占比逐步提升；股票与 ETF 存量稳定、变更主要为名称/状态。"
        ),
        anomaly=(
            "应关注：1) MATURITY_DT 早于 BIZ_DT 的已到期资产是否仍被引用；"
            "2) AST_TYPE 与 AST_SUB_TYPE 不匹配（如 STOCK 出现 MTN）；"
            "3) BOND 类资产 COUPON_RATE/ISSUE_AMT 缺失；4) ISR_ID 在主体表中无对应记录。"
        ),
        scenarios=[
            "资产准入筛查与白名单维护",
            "按 AST_TYPE/AST_SUB_TYPE 做品类分布统计",
            "按 ISR_ID 反查发行人全量存量证券",
            "到期分布与剩余期限结构分析",
            "跨市场资产编码映射",
        ],
        key_fields=[
            "AST_CD", "AST_NM", "AST_TYPE", "AST_SUB_TYPE", "ISR_ID",
            "LIST_DT", "MATURITY_DT", "COUPON_RATE", "ISSUE_AMT", "MARKET", "BOND_TERM", "CCY",
        ],
        primary_keys=["AST_CD"],
        foreign_keys={"ISR_ID": "dwd_isr_institution.ISR_ID"},
        field_profiles=[
            FieldProfile(
                field_name="AST_CD",
                display_name="证券代码",
                data_type="string",
                definition="金融资产的唯一标识编码，含市场后缀",
                example_values=["019601.IB", "600036.SH", "127080.SZ"],
                is_primary_key=True,
                association_chains=[
                    "AST_CD → dwd_ptl_holding.AST_CD → dwd_ptl_info.PORT_ID",
                    "AST_CD → dwd_mkt_bond.AST_CD",
                    "AST_CD → dwd_ast_rating.AST_CD",
                ],
                tags=["主键", "检索键"],
            ),
            FieldProfile(
                field_name="AST_NM",
                display_name="证券名称",
                data_type="string",
                definition="资产的官方中文简称",
                example_values=["21国开01", "招商银行", "沪深300ETF"],
                tags=["检索键", "维度"],
            ),
            FieldProfile(
                field_name="AST_TYPE",
                display_name="资产大类",
                data_type="enum",
                definition="资产一级分类，区分债券、股票、基金、ABS等品种",
                example_values=["BOND", "STOCK", "FUND", "ABS"],
                enum_values={"BOND": "债券", "STOCK": "股票", "FUND": "基金", "ABS": "资产支持证券"},
                tags=["维度", "检索键"],
            ),
            FieldProfile(
                field_name="AST_SUB_TYPE",
                display_name="资产子类",
                data_type="enum",
                definition="资产二级分类，细化品种属性",
                example_values=["CGB", "POLICY", "MTN", "ENTERPRISE", "A_SHARE", "ETF"],
                enum_values={"CGB": "国债", "POLICY": "政策性金融债", "MTN": "中期票据", "ENTERPRISE": "企业债", "A_SHARE": "A股", "ETF": "ETF基金"},
                tags=["维度"],
            ),
            FieldProfile(
                field_name="ISR_ID",
                display_name="发行人ID",
                data_type="string",
                definition="关联发行人/主体的唯一标识",
                example_values=["ISR_001", "ISR_CDB", "ISR_MOF"],
                is_foreign_key=True,
                references="dwd_isr_institution.ISR_ID",
                association_chains=[
                    "ISR_ID → dwd_isr_institution.ISR_ID → dwd_isr_institution.ISR_NM",
                ],
                tags=["外键", "维度"],
            ),
            FieldProfile(
                field_name="MATURITY_DT",
                display_name="到期日",
                data_type="date",
                definition="债券本金到期兑付日期",
                example_values=["2025-03-15", "2031-11-20"],
                is_time_series=True,
                tags=["排序键", "维度"],
            ),
            FieldProfile(
                field_name="COUPON_RATE",
                display_name="票面利率",
                data_type="number",
                definition="债券的名义年化票息率",
                example_values=["2.85", "3.50", "4.20"],
                unit="%",
                tags=["度量"],
            ),
            FieldProfile(
                field_name="MARKET",
                display_name="上市市场",
                data_type="enum",
                definition="资产上市或托管的交易市场",
                example_values=["IB", "SH", "SZ"],
                enum_values={"IB": "银行间", "SH": "上交所", "SZ": "深交所"},
                tags=["维度", "检索键"],
            ),
            FieldProfile(
                field_name="RATING",
                display_name="信用评级",
                data_type="enum",
                definition="债项信用评级（最新）",
                example_values=["AAA", "AA+", "AA"],
                enum_values={"AAA": "最高级", "AA+": "高级", "AA": "中高级", "AA-": "中级"},
                tags=["维度"],
            ),
            FieldProfile(
                field_name="ISSUE_DT",
                display_name="发行日期",
                data_type="date",
                definition="证券首次发行的日期",
                example_values=["2021-01-15", "2023-06-20"],
                is_time_series=True,
                tags=["排序键"],
            ),
            FieldProfile(
                field_name="PAR_VALUE",
                display_name="面值",
                data_type="number",
                definition="债券每张面值，通常为100元",
                example_values=["100"],
                unit="元",
                tags=["度量"],
            ),
            FieldProfile(
                field_name="CCY",
                display_name="币种",
                data_type="enum",
                definition="证券计价币种",
                example_values=["CNY", "USD", "HKD"],
                enum_values={"CNY": "人民币", "USD": "美元", "HKD": "港元"},
                tags=["维度"],
            ),
            FieldProfile(
                field_name="ISSUE_AMT",
                display_name="发行规模",
                data_type="number",
                definition="证券发行总额",
                example_values=["5000000000", "20000000000"],
                unit="元",
                tags=["度量"],
            ),
            FieldProfile(
                field_name="BOND_TERM",
                display_name="债券期限",
                data_type="number",
                definition="债券发行时约定的存续年限",
                example_values=["3", "5", "10", "30"],
                unit="年",
                tags=["维度", "检索键"],
            ),
            FieldProfile(
                field_name="LIST_DT",
                display_name="上市日期",
                data_type="date",
                definition="证券在交易市场上市的日期",
                example_values=["2021-01-18", "2023-06-22"],
                is_time_series=True,
                tags=["排序键"],
            ),
        ],
    ),

    # 2. 中债估值
    "dwd_ast_info_ch": TableProfile(
        table_name="dwd_ast_info_ch",
        domain="asset",
        display_name="中债估值表",
        purpose=(
            "由中债估值中心（CH）提供的债券类资产逐日估值快照，"
            "记录净价、全价、收益率、修正久期、凸性等关键定价指标，"
            "是估值入账和市值核算的权威外部数据源之一。"
        ),
        distribution=(
            "全量 12 条覆盖所有 AST_CD（含股票/ETF 时 VAL_YIELD/DURATION 为空）；"
            "VAL_NET_PRC 集中在 98~103 区间；信用债收益率（如万科 MTN）显著高于利率债。"
        ),
        trend=(
            "BIZ_DT 维度日频更新；估值随利率曲线波动，节假日不更新；"
            "信用事件发生时净价快速下行、收益率上行。"
        ),
        anomaly=(
            "应关注：1) VAL_NET_PRC 单日跳变超过 ±2%；2) DURATION 与债券剩余期限严重背离；"
            "3) 同一资产中债 vs 中证估值偏差超过 30bp（口径冲突）；4) BIZ_DT 缺失或空值。"
        ),
        scenarios=[
            "组合每日 MTM 估值入账",
            "债券估值收益率曲线监控",
            "中债 vs 中证双源价差监控",
            "久期/凸性敞口核算",
        ],
        key_fields=["AST_CD", "BIZ_DT", "VAL_NET_PRC", "VAL_FULL_PRC", "VAL_YIELD", "DURATION", "CONVEXITY", "VAL_SRC"],
        primary_keys=["AST_CD", "BIZ_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    # 3. 中证估值
    "dwd_ast_info_zg": TableProfile(
        table_name="dwd_ast_info_zg",
        domain="asset",
        display_name="中证估值表",
        purpose=(
            "由中证指数公司（ZG）提供的债券/ABS 类资产逐日估值快照，"
            "与中债估值并列作为第二估值源，用于估值校验、争议解决和审计验证。"
        ),
        distribution=(
            "覆盖 8 条记录，仅含债券与 ABS（不含权益/ETF）；"
            "估值数值与中债接近但存在轻微差异（通常 < 5bp）；评级机构标记为‘中证指数’。"
        ),
        trend=(
            "日频更新；价差波动通常稳定，对市场流动性紧张和信用事件敏感；"
            "新发行债券入池滞后中债 1~2 日。"
        ),
        anomaly=(
            "应关注：1) 与 dwd_ast_info_ch 的同日价差 > 0.30 元；2) 收益率反向偏离；"
            "3) 部分债券中证未提供估值（缺失需 fallback 到中债）。"
        ),
        scenarios=[
            "双估值源价差监控与异常告警",
            "估值争议复核与第三方校验",
            "审计取数与定价合理性检查",
        ],
        key_fields=["AST_CD", "BIZ_DT", "VAL_NET_PRC", "VAL_FULL_PRC", "VAL_YIELD", "DURATION", "CONVEXITY", "VAL_SRC"],
        primary_keys=["AST_CD", "BIZ_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    # 4. 收益率信息
    "dwd_ast_yield_info": TableProfile(
        table_name="dwd_ast_yield_info",
        domain="asset",
        display_name="资产收益率信息表",
        purpose=(
            "存储每只资产的到期收益率（YTM）、信用利差（SPREAD）、基准利率，"
            "以及日/周/月/年初至今多周期收益率，是个券收益归因和风险定价的核心源表。"
        ),
        distribution=(
            "BOND/ABS 类有完整 YTM 与 SPREAD（信用债 SPREAD 显著高，如万科 MTN ≈ 215bp），"
            "权益类 YTM/SPREAD 为空但 DAILY_RTN 非空；DAILY_RTN 量级集中在 ±50bp。"
        ),
        trend=(
            "日频更新；信用利差随主体评级变化、行业景气度而周期性波动；"
            "利率债收益率与基准利率高度同步，信用债额外承担利差中枢移动。"
        ),
        anomaly=(
            "应关注：1) SPREAD 单日跳升超过 50bp（暗示主体信用恶化）；"
            "2) DAILY_RTN 异常值（> 5% 多为公司行动事件）；"
            "3) YTM 与中债估值收益率口径不一致；4) 已到期资产仍刷新 YTM。"
        ),
        scenarios=[
            "信用利差监控与下沉/上沉策略",
            "组合收益归因（票息/资本利得分解）",
            "个券与基准的相对强弱排序",
            "异常波动告警与跌停/涨停识别",
        ],
        key_fields=["AST_CD", "BIZ_DT", "YTM", "SPREAD", "BASE_RATE", "DAILY_RTN", "WEEK_RTN", "MONTH_RTN", "YTD_RTN", "SETTLE_PRC"],
        primary_keys=["AST_CD", "BIZ_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    # 5. 现金流计划
    "dwd_ast_cf_plan": TableProfile(
        table_name="dwd_ast_cf_plan",
        domain="asset",
        display_name="资产现金流计划表",
        purpose=(
            "登记每只债券类资产的未来现金流计划，包括付息（COUPON）、到期还本付息"
            "（COUPON_PRINCIPAL）、过手摊还（ABS）等事件的日期与金额，"
            "支撑利息预提、到期资金安排和久期/凸性精确测算。"
        ),
        distribution=(
            "CF_TYPE 以 COUPON 为主、COUPON_PRINCIPAL 集中在到期日；"
            "现金流密度因付息频率不同而异（年付息 1 次 / 半年付息 2 次 / ABS 季度过手）；"
            "金额量级跨度大（千万到百亿）。"
        ),
        trend=(
            "现金流分布呈现年内季末/季中峰值（与公开发行付息日聚集相关）；"
            "随发行规模扩张，年度现金流体量逐年抬升。"
        ),
        anomaly=(
            "应关注：1) CF_DT 在过去但未生成已实现事件（dwd_ast_event 缺失）；"
            "2) COUPON_PRINCIPAL 金额与 ISSUE_AMT*(1+COUPON_RATE) 不一致；"
            "3) 重复登记同日同类型现金流；4) ABS 过手金额偏离资产池规模。"
        ),
        scenarios=[
            "未来 30/60/90 天到期付息现金流预测",
            "组合现金缺口与流动性管理",
            "久期/凸性精确计算（基于现金流贴现）",
            "ABS 摊还节奏与资产池逾期联动监控",
        ],
        key_fields=["AST_CD", "CF_DT", "CF_TYPE", "CF_AMT", "CCY", "NOTE"],
        primary_keys=["AST_CD", "CF_DT", "CF_TYPE"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    # 6. 质押状态
    "dwd_ast_pledge": TableProfile(
        table_name="dwd_ast_pledge",
        domain="asset",
        display_name="资产质押状态表",
        purpose=(
            "登记每只债券资产是否纳入回购质押券池及对应的质押率（PLEDGE_RATIO）、"
            "质押登记机构和合格性标记，是评估资产融资能力和回购杠杆策略的核心字段。"
        ),
        distribution=(
            "PLEDGE_FLAG 以 Y 为主（利率债标准券 ≥0.90，信用债 0.65~0.80），"
            "信用资质恶化资产 PLEDGE_FLAG=N；登记机构集中于中央国债登记结算公司、"
            "上海清算所、中国证券登记结算公司。"
        ),
        trend=(
            "质押率随交易所/中证登政策调整、主体评级变化而被动调整；"
            "信用风险事件后，相关债券常被剔除标准券池或质押率下调。"
        ),
        anomaly=(
            "应关注：1) PLEDGE_FLAG=Y 但 PLEDGE_RATIO 为 0；2) 标准券（STD）"
            "突然降级为 NON；3) 质押机构与市场不匹配（深交所债登记到中央结算）。"
        ),
        scenarios=[
            "回购质押融资能力评估",
            "标准券池变动与杠杆策略调整",
            "高质押率底仓优化与现金管理",
            "信用事件后质押权动态监控",
        ],
        key_fields=["AST_CD", "BIZ_DT", "PLEDGE_FLAG", "PLEDGE_RATIO", "PLEDGE_INST", "PLEDGE_STD", "PLEDGE_NOTE"],
        primary_keys=["AST_CD", "BIZ_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    # 7. 交易流水
    "dwd_ast_flow_trade": TableProfile(
        table_name="dwd_ast_flow_trade",
        domain="asset",
        display_name="资产交易流水表",
        purpose=(
            "明细级登记每笔证券交易（买入/卖出）的成交日期、价格、数量、金额、"
            "交易对手、归属组合及结算日，是资金流、持仓变动与对手方限额监控的源头表。"
        ),
        distribution=(
            "TRADE_DIR 以 BUY 为主（建仓阶段），SELL 多发生于 SELL 调仓与回售；"
            "交易主要集中在银行间市场，交易对手以中信、中金、国君、兴业银行为主；"
            "成交金额量级覆盖百万到亿元。"
        ),
        trend=(
            "交易频率呈月度规律：月初新增建仓多、月末调仓与现金管理活跃；"
            "重大事件（评级下调/监管口径变化）可触发集中卖出脉冲。"
        ),
        anomaly=(
            "应关注：1) TRADE_PRC 偏离当日中债估值 > 50bp；"
            "2) 同一组合同日反向交易（疑似账户错配）；"
            "3) SETTLE_DT 早于 TRADE_DT 或跨度异常；4) 对手方使用额度（USED_LIMIT）逼近上限。"
        ),
        scenarios=[
            "成交价异常（异于估值）核查",
            "对手方授信使用与集中度监控",
            "组合调仓节奏与换手率分析",
            "T+0/T+1/T+2 结算合规检查",
        ],
        key_fields=["TRADE_ID", "AST_CD", "TRADE_DT", "TRADE_DIR", "TRADE_AMT", "TRADE_PRC", "TRADE_QTY", "CNTP_ID", "PORT_ID", "SETTLE_DT"],
        primary_keys=["TRADE_ID"],
        foreign_keys={
            "AST_CD": "dwd_ast_info.AST_CD",
            "CNTP_ID": "dwd_isr_trd_cntp.CNTP_ID",
            "PORT_ID": "dwd_ptl_info.PORT_ID",
        },
    ),

    # 8. 信用评级
    "dwd_ast_rating": TableProfile(
        table_name="dwd_ast_rating",
        domain="asset",
        display_name="资产信用评级表",
        purpose=(
            "记录每只债券由不同评级机构出具的债项评级（BOND_RATING）、主体评级"
            "（ISR_RATING）、展望（OUTLOOK）以及评级类型（初评/跟踪/下调），"
            "是信用风险计量与组合内评级分布管控的核心数据。"
        ),
        distribution=(
            "评级集中于 AAA（利率债与高等级信用债），AA+/AA 多见于地产/民企信用债；"
            "评级机构以中诚信国际、联合资信、大公国际、东方金诚四家为主；"
            "OUTLOOK 大多稳定，少量负面对应主体下迁。"
        ),
        trend=(
            "评级跟踪通常每 6~12 个月发布一次；下调与负面展望集中在年报披露后；"
            "信用债行业景气度恶化时下调密度上升。"
        ),
        anomaly=(
            "应关注：1) RATING_TYPE='下调' 或 OUTLOOK 由稳定转负面；"
            "2) 同一资产多家机构评级分歧 > 2 档；3) BOND_RATING 与 ISR_RATING 倒挂；"
            "4) RATING_DT 长期未更新（超过 18 个月）。"
        ),
        scenarios=[
            "组合评级分布与信用集中度",
            "评级下迁预警与持仓风险敞口",
            "评级机构差异化对比",
            "信用利差合理性验证",
        ],
        key_fields=["AST_CD", "RATING_AGENCY", "RATING_DT", "BOND_RATING", "ISR_RATING", "OUTLOOK", "RATING_TYPE"],
        primary_keys=["AST_CD", "RATING_AGENCY", "RATING_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    # 9. 担保信息
    "dwd_ast_guarantor": TableProfile(
        table_name="dwd_ast_guarantor",
        domain="asset",
        display_name="资产担保信息表",
        purpose=(
            "登记债券的担保人、担保类型（连带责任/差额支付/隐性政府支持等）、"
            "担保金额、覆盖比例及生效/到期日，用于评估增信措施的有效性与回收率假设。"
        ),
        distribution=(
            "GUAR_TYPE 集中在‘母公司全额担保’、‘差额支付’、‘原始权益人差额补足’、"
            "‘隐性政府支持’等；GUAR_RATIO 多为 1.00（全额覆盖）；ABS 类常见多层担保。"
        ),
        trend=(
            "担保安排通常在发行时一次性确定；存续期内担保人评级变化将间接影响债项评级；"
            "差额补足触发后会出现新增的临时担保记录。"
        ),
        anomaly=(
            "应关注：1) EXP_DT 早于债券 MATURITY_DT（担保覆盖不足）；"
            "2) GUAR_RATIO < 1.00 但条款描述为‘全额担保’；"
            "3) 担保人本身评级被下调，导致增信失效。"
        ),
        scenarios=[
            "增信结构有效性评估",
            "ABS 信用增级层级核对",
            "担保人评级联动风险传导",
            "回收率假设与减值测算",
        ],
        key_fields=["AST_CD", "GUAR_NM", "GUAR_TYPE", "GUAR_AMT", "GUAR_RATIO", "EFF_DT", "EXP_DT"],
        primary_keys=["AST_CD", "GUAR_NM"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    # 10. 债券条款
    "dwd_ast_clause": TableProfile(
        table_name="dwd_ast_clause",
        domain="asset",
        display_name="债券条款表",
        purpose=(
            "登记债券特殊条款（PUT 回售/CALL 赎回/RATE_ADJ 利率调整/CROSS_DEF 交叉违约/"
            "GREEN_BIND 绿色用途等）的触发条件、生效日、行权价与说明，"
            "支撑含权债定价、行权决策与合规专项管理。"
        ),
        distribution=(
            "CLAUSE_TYPE 以 NONE（普通固息）和 CALL/PUT 为主，少量为 RATE_ADJ/CROSS_DEF/"
            "GREEN_BIND；EXE_PRC 通常等于 100；EFF_DT 多落在债券存续中后期。"
        ),
        trend=(
            "含权债占比随银行二级资本债、永续债、地产信用债扩容而上升；"
            "市场利率下行期 CALL 行权概率提升，信用恶化期 PUT 行权概率提升。"
        ),
        anomaly=(
            "应关注：1) CLAUSE_TYPE 与 NOTE 描述不一致；2) EFF_DT 已过但条款状态未更新；"
            "3) RATE_ADJ 与 CALL 联动条款缺失对端记录；"
            "4) GREEN_BIND 资产未披露资金用途（对应事件缺失）。"
        ),
        scenarios=[
            "含权债行权窗口排期",
            "利率调整 + 赎回联动定价",
            "交叉违约触发条件监控",
            "绿色债资金用途合规检查",
        ],
        key_fields=["AST_CD", "CLAUSE_TYPE", "CLAUSE_NM", "TRIGGER", "EFF_DT", "EXE_PRC", "NOTE"],
        primary_keys=["AST_CD", "CLAUSE_TYPE", "EFF_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    # 11. 持有人信息
    "dwd_ast_holder": TableProfile(
        table_name="dwd_ast_holder",
        domain="asset",
        display_name="资产持有人信息表",
        purpose=(
            "登记债券前 N 大持有人的机构类型、持有面值、持仓比例与排名，"
            "用于评估资产的流动性结构、潜在抛售压力和大户行为分析。"
        ),
        distribution=(
            "HOLDER_TYPE 以 BANK、INSURANCE、AMC、SSF、PORTFOLIO 为主；"
            "前 1 大持有人占比通常在 10%~17%，前 3 大合计 30%~50%；"
            "利率债持有人结构稳定，信用债持仓更分散。"
        ),
        trend=(
            "持有人排名按季度披露（部分按月）；银行自营在利率债中长期占主导，"
            "保险和社保增持长久期国债节奏季节性明显，资管产品在信用债端波动较大。"
        ),
        anomaly=(
            "应关注：1) 单一持有人占比 > 30%（流动性集中风险）；"
            "2) 排名前 3 持有人短期内大幅减持；"
            "3) HOLD_RATIO 求和 > 1.0（数据冲突）；4) HOLDER_TYPE 与机构名称不匹配。"
        ),
        scenarios=[
            "资产流动性与抛售压力评估",
            "大户持仓变动与价格博弈",
            "组合内资产间持有人重叠分析",
            "禁止互持/关联交易合规检查",
        ],
        key_fields=["AST_CD", "HOLDER_NM", "HOLDER_TYPE", "HOLD_FACE_AMT", "HOLD_RATIO", "RANK", "BIZ_DT"],
        primary_keys=["AST_CD", "HOLDER_NM", "BIZ_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    # 12. 资产事件
    "dwd_ast_event": TableProfile(
        table_name="dwd_ast_event",
        domain="asset",
        display_name="资产生命周期事件表",
        purpose=(
            "记录每只资产关键生命周期事件（发行、付息、到期、回售、赎回、评级变动、"
            "资产池报告、绿色披露、违约等）的发生日期、描述及业务影响（IMPACT），"
            "是事件驱动策略与风险预警的事件源表。"
        ),
        distribution=(
            "EVENT_TYPE 以 COUPON、ISSUE 等中性事件为多，RATING_CHG/PUT_DCLR/DEFAULT 等"
            "负面事件占比低但影响重大；IMPACT 分布大致 NEUTRAL 50% / POSITIVE 30% / NEGATIVE 20%。"
        ),
        trend=(
            "事件密度与债券存续阶段相关：发行初期 ISSUE/RATING 集中，存续中期为定期付息，"
            "存续末期回售/赎回/到期密集；信用风险周期会引发短时间内 RATING_CHG/DEFAULT 集群。"
        ),
        anomaly=(
            "应关注：1) IMPACT='NEGATIVE' 事件触发后短期内净价大幅下跌；"
            "2) 与 dwd_ast_cf_plan 中 COUPON 计划日不一致；"
            "3) 同一资产同日多类型事件叠加（连锁反应）；"
            "4) DEFAULT 事件后续未补充处置/重组事件。"
        ),
        scenarios=[
            "事件驱动策略信号提取",
            "评级下调影响半径量化",
            "回售/赎回行权窗口管理",
            "ABS 资产池逾期率监控",
            "绿色债资金投向披露追踪",
        ],
        key_fields=["AST_CD", "EVENT_TYPE", "EVENT_DT", "EVENT_DESC", "IMPACT"],
        primary_keys=["AST_CD", "EVENT_DT", "EVENT_TYPE"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    # 13. 资产列表主数据 (assets 集合)
    "assets": TableProfile(
        table_name="assets",
        domain="asset",
        display_name="资产列表主数据表",
        purpose=(
            "组合管理系统的资产主数据集合，以 code 为唯一标识，登记每只资产的代码、名称、"
            "资产类型(asset_type)及创建时间。作为 asset_prices K线行情和产品持仓的父表，"
            "是投资组合管理、回测、风控等业务的资产侧基础。"
        ),
        distribution=(
            "资产类型以指数类(ETF)为主体，其次为债券类、股票类；"
            "代码格式包含市场后缀（如 510300.SH、159915.SZ、SPX）；"
            "数据规模约数十到数百条，随新资产引入而增长。"
        ),
        trend=(
            "随策略扩展和新资产引入而稳定增长；存量资产的 name/asset_type 属性较少变动。"
        ),
        anomaly=(
            "应关注：1) code 与 asset_prices.asset_code 的孤儿引用（行情存在但资产列表缺失）；"
            "2) 同名资产重复 code；3) asset_type 与实际行情类型不匹配。"
        ),
        scenarios=[
            "资产列表查询与筛选",
            "资产代码与名称映射",
            "K线行情和产品持仓的父级关联",
            "回测策略的资产池管理",
        ],
        key_fields=["code", "name", "asset_type", "created_at"],
        primary_keys=["code"],
        foreign_keys={},
        field_profiles=[
            FieldProfile(
                field_name="code",
                display_name="资产代码",
                data_type="string",
                definition="资产的唯一标识编码，可含市场后缀",
                example_values=["510300.SH", "159915.SZ", "SPX", "GLD"],
                is_primary_key=True,
                association_chains=[
                    "code → asset_prices.asset_code",
                    "code → dwd_ptl_ast_hld.AST_CD",
                ],
                tags=["主键", "检索键"],
            ),
            FieldProfile(
                field_name="name",
                display_name="资产名称",
                data_type="string",
                definition="资产的中文/英文简称",
                example_values=["沪深300ETF", "创业板ETF", "标普500"],
                tags=["检索键", "维度"],
            ),
            FieldProfile(
                field_name="asset_type",
                display_name="资产类型",
                data_type="enum",
                definition="资产类型分类",
                example_values=["指数类", "债券类", "股票类"],
                enum_values={"指数类": "指数/ETF类资产", "债券类": "债券类资产", "股票类": "股票类资产"},
                tags=["维度", "检索键"],
            ),
        ],
    ),

    # 14. 资产日频K线行情 (asset_prices 集合)
    "asset_prices": TableProfile(
        table_name="asset_prices",
        domain="asset",
        display_name="资产日频K线行情表",
        purpose=(
            "存储资产日频 OHLC 行情数据，包含开高低收、成交量、成交额、规模等字段，"
            "通过 asset_code 关联 assets 主表。是投资组合净值计算、回测收益归因、"
            "风险监控、K线可视化和策略评估的核心行情数据源。"
        ),
        distribution=(
            "每只资产按日频记录，数据量随资产数和存续期增长；"
            "close 字段为净值/价格核心指标；volume/amount 在 ETF 类资产较大，"
            "指数类可能为空；scale 记录基金规模。"
        ),
        trend=(
            "日频更新，节假日可能有仅含收盘价的记录（自然日全量）；"
            "行情随市场波动，重大事件日价格跳变明显。"
        ),
        anomaly=(
            "应关注：1) asset_code 在 assets 主表中不存在（孤儿行情）；"
            "2) close 为 0 或 null 的异常记录；"
            "3) 同一 asset_code 同日多条记录；"
            "4) open/high/low/close 逻辑矛盾（如 low > high）。"
        ),
        scenarios=[
            "资产K线走势可视化",
            "投资组合净值与收益计算",
            "回测策略收益归因",
            "多资产相关性分析",
            "异常行情检测与告警",
        ],
        key_fields=["asset_code", "date", "open", "high", "low", "close", "volume", "amount", "scale"],
        primary_keys=["asset_code", "date"],
        foreign_keys={"asset_code": "assets.code"},
        field_profiles=[
            FieldProfile(
                field_name="asset_code",
                display_name="资产代码",
                data_type="string",
                definition="关联 assets 主表的资产代码",
                example_values=["510300.SH", "159915.SZ", "SPX"],
                is_foreign_key=True,
                references="assets.code",
                association_chains=[
                    "asset_code → assets.code → assets.name",
                ],
                tags=["外键", "检索键"],
            ),
            FieldProfile(
                field_name="date",
                display_name="日期",
                data_type="date",
                definition="行情日期",
                example_values=["2025-01-15", "2026-06-01"],
                is_time_series=True,
                tags=["排序键", "维度"],
            ),
            FieldProfile(
                field_name="close",
                display_name="收盘价",
                data_type="number",
                definition="当日收盘价格/净值",
                example_values=["3.85", "1.234", "5200.5"],
                tags=["度量"],
            ),
            FieldProfile(
                field_name="open",
                display_name="开盘价",
                data_type="number",
                definition="当日开盘价格",
                example_values=["3.82", "1.230"],
                tags=["度量"],
            ),
            FieldProfile(
                field_name="high",
                display_name="最高价",
                data_type="number",
                definition="当日最高价格",
                example_values=["3.90", "1.240"],
                tags=["度量"],
            ),
            FieldProfile(
                field_name="low",
                display_name="最低价",
                data_type="number",
                definition="当日最低价格",
                example_values=["3.78", "1.220"],
                tags=["度量"],
            ),
            FieldProfile(
                field_name="volume",
                display_name="成交量",
                data_type="number",
                definition="当日成交量",
                example_values=["1000000", "50000"],
                tags=["度量"],
            ),
            FieldProfile(
                field_name="amount",
                display_name="成交额",
                data_type="number",
                definition="当日成交金额",
                example_values=["3850000", "62000"],
                unit="元",
                tags=["度量"],
            ),
            FieldProfile(
                field_name="scale",
                display_name="规模",
                data_type="number",
                definition="基金/ETF规模",
                example_values=["1000000000"],
                tags=["度量"],
            ),
        ],
    ),
}
