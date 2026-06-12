"""
客户域(Customer Domain) - L1静态画像定义
覆盖：客户基础信息/做市持仓/交易账户/IPO 认购/赎回/分红/转换/风险评估/资金流水
共 9 张表
"""
from ..models import DomainOverview, TableProfile


DOMAIN_OVERVIEW = DomainOverview(
    domain_code="customer",
    domain_name="客户域",
    description=(
        "围绕零售与机构客户的全生命周期视图：基础档案、风险评估、交易账户、"
        "认购/赎回/分红/转换流水及资金账户余额，覆盖适当性合规、客户营销与"
        "AUM 留存分析等场景，是销售域与产品域之间的桥梁。"
    ),
    table_count=9,
    tables=[
        "dwd_cust_info",
        "dwd_cust_make_pstn_info",
        "dwd_cust_trade_acct",
        "dwd_cust_ipo",
        "dwd_cust_redeem",
        "dwd_cust_dividend",
        "dwd_cust_transfer",
        "dwd_cust_risk_assess",
        "dwd_cust_flow",
    ],
    core_scenarios=[
        "客户 360° 画像与持仓查询",
        "适当性匹配与合规检查",
        "认购/赎回行为分析与流失预警",
        "分红派发与红利再投资跟踪",
        "客户资金账户余额与流水审计",
        "做市/自营持仓敞口监控",
        "客户分层与精准营销",
    ],
    key_entities=[
        "CUSTOMER_ID", "ACCT_ID", "IPO_ID", "REDEEM_ID",
        "DIVIDEND_ID", "TRANSFER_ID", "ASSESS_ID", "FLOW_ID",
    ],
)


TABLE_PROFILES = {
    "dwd_cust_info": TableProfile(
        table_name="dwd_cust_info",
        domain="customer",
        display_name="客户基础信息表",
        purpose=(
            "维护零售个人客户与机构客户的主档：客户类型、证件、风险等级、"
            "绑定销售、当前持仓与认购日期等，是客户域所有事实表的主键源头。"
        ),
        distribution=(
            "CUSTOMER_TYPE 一般 INDIVIDUAL 笔数多、INSTITUTION 持仓金额大；"
            "RISK_LVL 集中于 C2-C4，机构客户多为 C3/C5；CHANNEL 中 DIRECT/BANK/BROKER"
            "三足鼎立；HOLD_AMT 服从右偏长尾分布，机构 TOP 客户贡献 80% AUM。"
        ),
        trend=(
            "客户数缓慢增长；月初/季初新客集中；HOLD_SHARE/HOLD_AMT 随净值实时变动；"
            "STATUS 切换至 INACTIVE 多发生在赎回完成或风险评估到期之后。"
        ),
        anomaly=(
            "需关注：CUSTOMER_TYPE 与 ID_TYPE 不匹配（个人却用 CREDIT_CODE）；"
            "RISK_LVL 高于产品风险等级的反向匹配；HOLD_AMT 远大于 KYC 净资产；"
            "SELLER_ID 已离职但客户仍绑定；缺失 SUBSCRIBE_DT 但有持仓的孤儿数据。"
        ),
        scenarios=[
            "客户基础档案查询",
            "AUM TOP N 客户分析",
            "销售-客户绑定关系核查",
            "适当性匹配前的风险等级提取",
            "客户类型/渠道/区域分布",
            "睡眠客户激活分析",
        ],
        key_fields=[
            "CUSTOMER_ID", "CUSTOMER_NM", "CUSTOMER_TYPE", "ID_TYPE",
            "RISK_LVL", "SELLER_ID", "PORT_ID",
            "HOLD_SHARE", "HOLD_AMT", "SUBSCRIBE_DT", "STATUS", "CHANNEL",
        ],
        primary_keys=["CUSTOMER_ID"],
        foreign_keys={
            "SELLER_ID": "dwd_sale_psn_info.SELLER_ID",
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
        },
    ),

    "dwd_cust_make_pstn_info": TableProfile(
        table_name="dwd_cust_make_pstn_info",
        domain="customer",
        display_name="做市/自营持仓信息表",
        purpose=(
            "记录公司做市业务及自营账户的持仓快照，含做市券种、双边报价义务量、"
            "成本与浮动盈亏，是做市义务履行与自营敞口监控的事实表。"
        ),
        distribution=(
            "MAKE_TYPE 中 BOND_MARKET_MAKING 占比最大，少量 ETF/股票做市；"
            "AST_CD 集中在国债、政金债、AAA 信用债等做市义务券；"
            "POSITION 既有正向（持有）也有负向（做空）；FLOAT_PNL 围绕零附近双侧波动。"
        ),
        trend=(
            "持仓量在做市期间日内频繁变化，T 日末轧差留隔夜量；"
            "新入做市券种上市初期持仓快速放大，做市义务到期后逐步降低。"
        ),
        anomaly=(
            "需关注：POSITION 突破做市净敞口上限；FLOAT_PNL 单券单日浮亏超过预警线；"
            "已退出做市名单但仍存在大额持仓；同一券种被重复登记不同账户。"
        ),
        scenarios=[
            "做市义务券种持仓与双边报价覆盖率",
            "自营账户敞口与浮动盈亏监控",
            "做市业务损益归因",
            "做市券种成本/久期分析",
            "退市/赎回前的做市头寸清理",
            "监管报送做市规模口径核对",
        ],
        key_fields=[
            "PSTN_ID", "ACCT_ID", "AST_CD", "MAKE_TYPE",
            "POSITION", "COST_PRC", "MKT_PRC", "FLOAT_PNL",
            "BIZ_DT", "STATUS",
        ],
        primary_keys=["PSTN_ID"],
        foreign_keys={
            "AST_CD": "dwd_ast_info.AST_CD",
            "ACCT_ID": "dwd_cust_trade_acct.ACCT_ID",
        },
    ),

    "dwd_cust_trade_acct": TableProfile(
        table_name="dwd_cust_trade_acct",
        domain="customer",
        display_name="客户交易账户表",
        purpose=(
            "维护客户在交易系统中开立的资金账户/证券账户：账户类型、"
            "开户日期、币种、托管行、绑定渠道与状态，是认购/赎回与资金流水的"
            "落地账户主数据。"
        ),
        distribution=(
            "ACCT_TYPE 中 CASH（资金账户）笔数最多，SECURITY/MARGIN 较少；"
            "CCY 以 CNY 为主，少量 USD/HKD；BANK_NM 在工商/招商/中信/建设等头部银行集中；"
            "STATUS 绝大多数 ACTIVE，少量 FROZEN/CLOSED。"
        ),
        trend=(
            "新开户随客户增长曲线同步；销户在赎回完成后批量发生；"
            "FROZEN 状态可能因司法冻结、KYC 失效或反洗钱核查触发。"
        ),
        anomaly=(
            "需关注：同一 CUSTOMER_ID 持有过多 CASH 账户（潜在洗钱风险）；"
            "STATUS=ACTIVE 但长时间无流水的休眠账户；"
            "OPEN_DT 早于客户 SUBSCRIBE_DT 的逻辑倒挂；"
            "BANK_NM 缺失或与渠道不符。"
        ),
        scenarios=[
            "客户多账户合并视图",
            "账户冻结/解冻处理与影响范围",
            "反洗钱（AML）账户排查",
            "渠道-账户-客户三表对账",
            "外币账户敞口分析",
            "休眠账户清理与销户管理",
        ],
        key_fields=[
            "ACCT_ID", "CUSTOMER_ID", "ACCT_TYPE", "CCY",
            "OPEN_DT", "BANK_NM", "BANK_ACCT", "CHANNEL", "STATUS",
        ],
        primary_keys=["ACCT_ID"],
        foreign_keys={
            "CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID",
        },
    ),

    "dwd_cust_ipo": TableProfile(
        table_name="dwd_cust_ipo",
        domain="customer",
        display_name="客户认购/IPO 记录表",
        purpose=(
            "记录客户对新发产品/IPO 的认购申请、确认份额、认购金额与认购费率，"
            "是新产品发行募集与客户首笔购买行为的事实表。"
        ),
        distribution=(
            "SUB_AMT 个人客户多在 1-50 万区间，机构客户在 1000 万-1 亿元区间；"
            "FEE_RATE 按认购金额分档（小额 1.5%、大额 0.6%）；"
            "STATUS 以 CONFIRMED 为主，少量 PARTIAL/REJECTED（受募集上限或风险不匹配影响）。"
        ),
        trend=(
            "在新产品发行窗口集中爆发，募集期外为零；"
            "首发当日量最大，后续递减；季末/年末新发因冲量而走高。"
        ),
        anomaly=(
            "需关注：SUB_AMT 超过客户 KYC 净资产的合规风险；"
            "认购费 = SUB_AMT * FEE_RATE 计算偏差；"
            "STATUS=CONFIRMED 但 CONFIRM_DT 缺失；"
            "REJECTED 集中爆发提示渠道或风控规则异常。"
        ),
        scenarios=[
            "新产品发行募集进度与达成率",
            "客户首次认购转化分析",
            "认购费收入与费率合规审计",
            "渠道发行能力对比",
            "适当性失败的客户原因归类",
            "大额认购客户清单与服务跟踪",
        ],
        key_fields=[
            "IPO_ID", "CUSTOMER_ID", "PORT_ID", "SUB_DT",
            "SUB_AMT", "SUB_SHARE", "NAV", "FEE", "FEE_RATE",
            "CHANNEL", "STATUS", "CONFIRM_DT",
        ],
        primary_keys=["IPO_ID"],
        foreign_keys={
            "CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID",
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
        },
    ),

    "dwd_cust_redeem": TableProfile(
        table_name="dwd_cust_redeem",
        domain="customer",
        display_name="客户赎回记录表",
        purpose=(
            "记录客户的赎回申请、确认份额、赎回金额、赎回费及到账状态，"
            "支撑流动性管理、巨额赎回应对与客户流失预警。"
        ),
        distribution=(
            "REDEEM_TYPE 中 CASH（现金赎回）为主；FEE_RATE 与持有期成反比"
            "（持有 < 7 天可能 1.5%、7-365 天 0.5%、>365 天 0%）；"
            "STATUS 以 CONFIRMED/SETTLED 为主，少量 PENDING（T+N 在途）。"
        ),
        trend=(
            "月末/季末/年末出现赎回高峰；负面市场行情或同类产品比价失利时集中赎回；"
            "新发产品锁定期到期后会出现一轮赎回潮。"
        ),
        anomaly=(
            "需关注：单日赎回 > 组合规模 10% 的巨额赎回触发；"
            "REDEEM_AMT 超过客户当前持仓的越权赎回；"
            "STATUS 长时间停留在 PENDING 的到账延迟；"
            "FEE_RATE 与持有期不一致；TO_ACCT 与客户主账户不符。"
        ),
        scenarios=[
            "巨额赎回压力测试与应对",
            "客户流失预警与挽留",
            "赎回费收入分析",
            "T+N 到账时效合规检查",
            "持有期分布与赎回行为关联",
            "市场下跌时的赎回弹性测算",
        ],
        key_fields=[
            "REDEEM_ID", "CUSTOMER_ID", "PORT_ID", "REDEEM_DT",
            "REDEEM_AMT", "REDEEM_SHARE", "NAV", "FEE", "FEE_RATE",
            "TO_ACCT", "STATUS", "ARRIVAL_DT",
        ],
        primary_keys=["REDEEM_ID"],
        foreign_keys={
            "CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID",
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
        },
    ),

    "dwd_cust_dividend": TableProfile(
        table_name="dwd_cust_dividend",
        domain="customer",
        display_name="客户分红派发表",
        purpose=(
            "记录组合现金分红/红利再投对客户的派发明细：每份分红、客户份额、"
            "派发金额、再投份额、派发方式与到账状态，是客户收益体验的事实表。"
        ),
        distribution=(
            "DIV_TYPE 在 CASH（现金）/REINVEST（再投）两类间分布，机构客户 CASH 偏多、"
            "零售客户 REINVEST 偏多；DIV_PER_SHARE 通常 0.001-0.05/份；"
            "PER_CUSTOMER_AMT 与 HOLD_SHARE 强线性相关。"
        ),
        trend=(
            "随产品分红周期出现：货币基金日结、债基月度/季度、混合基金年度；"
            "权益市场上涨年度分红更频繁；REINVEST 比例随渠道默认设置变动。"
        ),
        anomaly=(
            "需关注：DIV_AMT != HOLD_SHARE * DIV_PER_SHARE；"
            "再投 NAV 与权益登记日 NAV 不符；"
            "STATUS 长期 PENDING 的派发延迟；"
            "客户已赎回但仍发放分红的逻辑错误。"
        ),
        scenarios=[
            "组合分红派发明细与一致性核对",
            "现金分红 vs 红利再投转化率",
            "派发延迟监控与客户投诉关联",
            "分红对组合规模的影响测算",
            "权益登记日的客户份额冻结管理",
            "客户实际收益归因（含分红）",
        ],
        key_fields=[
            "DIVIDEND_ID", "CUSTOMER_ID", "PORT_ID", "RECORD_DT",
            "EX_DT", "PAY_DT", "DIV_PER_SHARE",
            "HOLD_SHARE", "DIV_AMT", "DIV_TYPE",
            "REINVEST_SHARE", "REINVEST_NAV", "STATUS",
        ],
        primary_keys=["DIVIDEND_ID"],
        foreign_keys={
            "CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID",
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
        },
    ),

    "dwd_cust_transfer": TableProfile(
        table_name="dwd_cust_transfer",
        domain="customer",
        display_name="客户转换/转户记录表",
        purpose=(
            "记录客户在同一管理人旗下产品间的份额转换（基金转换）以及"
            "跨渠道/跨托管的转户申请，是 AUM 留存与渠道流转的事实表。"
        ),
        distribution=(
            "TRANSFER_TYPE 中 FUND_CONVERT（产品转换）笔数最多，"
            "CHANNEL_TRANSFER（转渠道）/CUSTODY_TRANSFER（转托管）较少；"
            "FROM_PORT 与 TO_PORT 多在同公司不同风险等级产品间切换。"
        ),
        trend=(
            "市场风险偏好切换时（牛转熊/熊转牛）转换量放大；"
            "新产品发行期间老客户的「老转新」集中出现；"
            "渠道营销活动期间转渠道笔数上升。"
        ),
        anomaly=(
            "需关注：FROM_SHARE != TO_SHARE * NAV 转换的份额折算异常；"
            "STATUS 长期 PROCESSING 的卡单；FROM_PORT 与 TO_PORT 风险等级跨级（合规风险）；"
            "同一客户短时间多次反复转换的异常套利行为。"
        ),
        scenarios=[
            "AUM 在产品矩阵内的迁移分析",
            "客户风险偏好切换识别",
            "转换费收入与减免政策评估",
            "转渠道/转托管的渠道竞争分析",
            "异常套利转换排查",
            "营销活动对转换行为的影响",
        ],
        key_fields=[
            "TRANSFER_ID", "CUSTOMER_ID", "TRANSFER_DT", "TRANSFER_TYPE",
            "FROM_PORT", "TO_PORT", "FROM_SHARE", "TO_SHARE",
            "FROM_NAV", "TO_NAV", "FEE", "STATUS",
        ],
        primary_keys=["TRANSFER_ID"],
        foreign_keys={
            "CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID",
            "FROM_PORT": "dwd_prd_port_info.PORT_ID",
            "TO_PORT": "dwd_prd_port_info.PORT_ID",
        },
    ),

    "dwd_cust_risk_assess": TableProfile(
        table_name="dwd_cust_risk_assess",
        domain="customer",
        display_name="客户风险评估表",
        purpose=(
            "记录客户每次风险测评的结果：风险等级、得分、投资经验、收入水平、"
            "亏损承受能力与投资目标，是适当性匹配的核心依据，按测评日为时间序列。"
        ),
        distribution=(
            "RISK_LVL 集中在 C2/C3，C5 多为机构客户；SCORE 分布与 RISK_LVL 强对应；"
            "INVEST_GOAL 中 STABLE/BALANCED 占主流；VALID_TO 一般为评估日 +1 年。"
        ),
        trend=(
            "新客户首次开户时强制评估；老客户每年到期续评；"
            "市场剧烈波动后会触发主动重评；监管检查前出现批量补评。"
        ),
        anomaly=(
            "需关注：VALID_TO 已过期但客户仍持有高风险产品的合规风险；"
            "SCORE 与 RISK_LVL 映射不符；同一客户短期内 RISK_LVL 大幅跳级；"
            "INCOME_LVL 与 KYC 不一致；机构客户使用个人评估问卷。"
        ),
        scenarios=[
            "适当性匹配检查（客户 vs 产品风险等级）",
            "评估到期续评提醒",
            "市场剧烈波动后的客户风险偏好变化",
            "评估问卷有效性与作弊识别",
            "机构客户专项问卷适用性",
            "投资经验与亏损承受度的相关性分析",
        ],
        key_fields=[
            "ASSESS_ID", "CUSTOMER_ID", "ASSESS_DT", "RISK_LVL", "SCORE",
            "INVEST_EXP", "INCOME_LVL", "LOSS_TOLERANCE",
            "INVEST_GOAL", "VALID_TO",
        ],
        primary_keys=["ASSESS_ID"],
        foreign_keys={
            "CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID",
        },
    ),

    "dwd_cust_flow": TableProfile(
        table_name="dwd_cust_flow",
        domain="customer",
        display_name="客户资金流水表",
        purpose=(
            "记录客户资金账户的逐笔流水：入金、出金、扣费、利息、分红到账等，"
            "是客户对账、反洗钱与现金管理的最细粒度事实表。"
        ),
        distribution=(
            "FLOW_TYPE 中 SUBSCRIBE/REDEEM/DIVIDEND/FEE/INTEREST/REFUND 多类并存；"
            "FLOW_DIR 入金/出金大致均衡；金额服从右偏长尾分布；"
            "BAL_AFTER 单调连续，体现账户结余演变。"
        ),
        trend=(
            "工作日流水密集，节假日为零（除自动计息）；"
            "月末/季末分红与到期赎回引发流水高峰；新发产品募集期入金集中。"
        ),
        anomaly=(
            "需关注：BAL_AFTER 与上一笔 BAL_AFTER ± FLOW_AMT 不一致的对账失败；"
            "短时间内同一对手账户多笔大额进出（潜在洗钱）；"
            "FLOW_AMT 异常巨大（超过客户净资产）；"
            "FLOW_DT 与系统流水号顺序倒挂；FLOW_TYPE 缺失或非法值。"
        ),
        scenarios=[
            "客户对账与差异定位",
            "反洗钱流水筛查（AML）",
            "现金管理（cash sweep）方案设计",
            "分红/利息到账验证",
            "扣费明细与费用核对",
            "客户资金活跃度与休眠识别",
        ],
        key_fields=[
            "FLOW_ID", "CUSTOMER_ID", "ACCT_ID", "FLOW_DT", "FLOW_TIME",
            "FLOW_TYPE", "FLOW_DIR", "FLOW_AMT", "BAL_AFTER",
            "REF_BIZ_ID", "REMARK",
        ],
        primary_keys=["FLOW_ID"],
        foreign_keys={
            "CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID",
            "ACCT_ID": "dwd_cust_trade_acct.ACCT_ID",
        },
    ),
}
