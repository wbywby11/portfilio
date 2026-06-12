"""
风险域(Risk Domain) - L1静态画像定义
覆盖：舆情/信用/担保/限额使用/风险事件 共 5 张表
"""
from ..models import DomainOverview, TableProfile


DOMAIN_OVERVIEW = DomainOverview(
    domain_code="risk",
    domain_name="风险域",
    description=(
        "对组合层面的舆情/信用/担保/限额/事件五大类风险进行结构化记录，"
        "支撑风险预警、合规检查、信用观察名单、抵押品折扣管理与重大事件追溯，"
        "是组合风控与监管报送的事实基础。"
    ),
    table_count=5,
    tables=[
        "dwd_rsk_sentiment",
        "dwd_rsk_credit",
        "dwd_rsk_guarantee",
        "dwd_rsk_limit_usage",
        "dwd_rsk_event",
    ],
    core_scenarios=[
        "舆情风险监控与传染分析",
        "信用风险评级与观察名单管理",
        "担保品价值与折扣率监控",
        "限额使用率合规检查",
        "重大风险事件追溯与影响评估",
    ],
    key_entities=[
        "SENT_ID", "CREDIT_ID", "GUARANTEE_ID",
        "LIMIT_ID", "EVENT_ID", "ISR_ID", "AST_CD",
    ],
)


TABLE_PROFILES = {
    "dwd_rsk_sentiment": TableProfile(
        table_name="dwd_rsk_sentiment",
        domain="risk",
        display_name="舆情风险表",
        purpose=(
            "汇集涉及组合持仓发行人/标的的舆情信号：新闻、公告、社交媒体提及、"
            "情感得分与影响等级，是负面信号传染前的最早预警源。"
        ),
        distribution=(
            "SENT_LVL 多为 NORMAL/POSITIVE，NEGATIVE/CRITICAL 占比 5-15%；"
            "SOURCE 中财经新闻、监管公告、社交平台三类来源；"
            "SENT_SCORE 取值 -1.0 ~ +1.0，分布近似双峰（中性为零，强烈情绪集中两端）。"
        ),
        trend=(
            "工作日舆情量明显高于周末；财报披露期、政策窗口、地缘事件期"
            "舆情量与负面情绪指数同步飙升；评级下调或违约前 1-2 周通常出现"
            "舆情先行。"
        ),
        anomaly=(
            "需关注：单一发行人 24h 内 NEGATIVE 信号 ≥ 5 条；SENT_SCORE 急剧下滑；"
            "信源高度集中（疑似谣言）；CRITICAL 信号与持仓敞口的交叉曝光；"
            "已封堵的虚假信源仍持续上报。"
        ),
        scenarios=[
            "舆情驱动的信用风险先行预警",
            "持仓发行人负面新闻聚类",
            "重大政策事件后的市场情绪量化",
            "舆情-评级-违约的传导链路追溯",
            "公告披露合规与时效核查",
            "组合持仓暴露在负面舆情下的敞口",
        ],
        key_fields=[
            "SENT_ID", "BIZ_DT", "RELATED_AST", "RELATED_ISR",
            "SENT_TYPE", "SENT_LVL", "SENT_SCORE",
            "SOURCE", "TITLE", "CONTENT", "PUBLISH_TIME",
        ],
        primary_keys=["SENT_ID"],
        foreign_keys={
            "RELATED_AST": "dwd_ast_info.AST_CD",
            "RELATED_ISR": "dwd_ast_isr_info.ISR_ID",
        },
    ),

    "dwd_rsk_credit": TableProfile(
        table_name="dwd_rsk_credit",
        domain="risk",
        display_name="信用风险表",
        purpose=(
            "记录组合持仓发行人与债项的信用评级、评级变动、违约概率（PD）、"
            "回收率（LGD）与观察名单状态，是信用风险计量与观察的事实表。"
        ),
        distribution=(
            "RATING 中 AAA/AA+ 占比最大，AA-/A+ 是关注重点；"
            "WATCH_LVL 大多 NORMAL，少量 NORMAL_WATCH/SPECIAL_ATTENTION/CRITICAL；"
            "PD 服从对数正态分布，AAA 通常 <0.5%，AA- 通常 1%-3%。"
        ),
        trend=(
            "评级中枢按行业景气度演变（地产/城投在压力期下移）；"
            "WATCHLIST 数量在信用事件高发期显著上升；"
            "外部评级机构调整一般集中在年报披露后 1-2 个月。"
        ),
        anomaly=(
            "需关注：单月评级跨级下调（AAA→AA）的极端情况；"
            "内部评级与外部评级偏差 > 2 档；"
            "WATCH_LVL=CRITICAL 但持仓未减持的合规风险；"
            "PD/LGD 突变（>50%）但无对应事件支撑。"
        ),
        scenarios=[
            "组合信用评级分布与下沉度",
            "评级变动的损益与敞口影响",
            "信用观察名单维护与跟进",
            "内外部评级偏离监控",
            "信用风险加权资产计量",
            "持仓发行人违约概率压力测试",
        ],
        key_fields=[
            "CREDIT_ID", "BIZ_DT", "ISR_ID", "AST_CD",
            "AGENCY", "RATING", "PREV_RATING", "RATING_CHG",
            "WATCH_LVL", "PD", "LGD", "VALID_FROM", "VALID_TO",
        ],
        primary_keys=["CREDIT_ID"],
        foreign_keys={
            "ISR_ID": "dwd_ast_isr_info.ISR_ID",
            "AST_CD": "dwd_ast_info.AST_CD",
        },
    ),

    "dwd_rsk_guarantee": TableProfile(
        table_name="dwd_rsk_guarantee",
        domain="risk",
        display_name="担保/抵押品风险表",
        purpose=(
            "记录组合相关业务（回购、衍生品、融资融券）的担保品/抵押品明细："
            "标的、市值、折扣率、覆盖率与释放/补足要求，是抵押品管理与"
            "保证金通知（margin call）的事实表。"
        ),
        distribution=(
            "COLLATERAL_TYPE 中国债/政金债 HAIRCUT 通常 0-3%、AAA 信用 5-10%、"
            "权益与可转债 20-40%；COVERAGE_RATIO 应 ≥ 1.05；"
            "STATUS 大多 NORMAL，少量 SHORTAGE/PENDING_TOPUP/RELEASED。"
        ),
        trend=(
            "市场暴跌时 MV 缩水触发 COVERAGE_RATIO 不足；"
            "评级下调会导致 HAIRCUT 上调；"
            "回购到期日批量出现担保品释放。"
        ),
        anomaly=(
            "需关注：COVERAGE_RATIO < 1.0 的不足额担保；"
            "HAIRCUT 偏离市场基准 > 5pct；STATUS=SHORTAGE 长时间未补足；"
            "同一抵押品被重复登记给多笔业务（重押风险）；"
            "MV 与最新行情严重不符。"
        ),
        scenarios=[
            "保证金通知（Margin Call）触发与跟踪",
            "抵押品集中度与多元化分析",
            "市场下跌情景下的覆盖率压力测试",
            "重押/超额担保识别",
            "释放/补足时效合规监控",
            "对手方信用风险敞口净化",
        ],
        key_fields=[
            "GUARANTEE_ID", "BIZ_DT", "BIZ_TYPE", "BIZ_REF_ID",
            "COLLATERAL_CD", "COLLATERAL_TYPE",
            "FACE_AMT", "MV", "HAIRCUT", "EFFECTIVE_VAL",
            "EXPOSURE", "COVERAGE_RATIO", "CNTP_ID", "STATUS",
        ],
        primary_keys=["GUARANTEE_ID"],
        foreign_keys={
            "COLLATERAL_CD": "dwd_ast_info.AST_CD",
            "CNTP_ID": "dwd_cntp_info.CNTP_ID",
        },
    ),

    "dwd_rsk_limit_usage": TableProfile(
        table_name="dwd_rsk_limit_usage",
        domain="risk",
        display_name="限额使用情况表",
        purpose=(
            "记录组合各类风险限额的使用率快照：单一债券/发行人集中度、"
            "杠杆率、久期、低评级占比、行业/区域集中度等，"
            "是合规检查与超限处置的事实表。"
        ),
        distribution=(
            "USAGE_RATIO 大多 < 80%（NORMAL），10%-15% 在 80%-100%（WARNING），"
            "<5% 突破 100%（BREACH）；LIMIT_TYPE 涵盖 CONCENTRATION/LEVERAGE/"
            "DURATION/RATING/LIQUIDITY 等多类。"
        ),
        trend=(
            "市场波动剧烈时 BREACH 数量显著上升；调仓窗口前后限额使用率波动加大；"
            "合同变更后限额阈值阶跃式调整。"
        ),
        anomaly=(
            "需关注：STATUS=BREACH 持续 > 3 个交易日仍未恢复；"
            "USAGE_RATIO > 1 的实质性超限；"
            "同一组合同类限额多次反复跨阈值（频繁触发）；"
            "BREACH_REASON 缺失或描述含糊。"
        ),
        scenarios=[
            "组合合规检查与监管报送",
            "投资指引动态调整建议",
            "限额预警/突破工单流转",
            "调仓前的限额预演（pre-trade compliance）",
            "信用事件后的被动超限影响评估",
            "投后管理报告生成",
        ],
        key_fields=[
            "LIMIT_ID", "PORT_ID", "CHECK_DT", "RULE_ID", "RULE_NM",
            "LIMIT_TYPE", "THRESHOLD", "CURRENT_VAL", "USAGE_RATIO",
            "STATUS", "BREACH_REASON",
        ],
        primary_keys=["LIMIT_ID"],
        foreign_keys={
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
        },
    ),

    "dwd_rsk_event": TableProfile(
        table_name="dwd_rsk_event",
        domain="risk",
        display_name="风险事件表",
        purpose=(
            "记录对组合产生重大影响的风险事件：违约、停牌、退市、评级急降、"
            "重大舆情、监管处罚、市场异动等，含事件类型、影响等级、"
            "处置结论与关联标的，是风险复盘的核心事实表。"
        ),
        distribution=(
            "EVENT_TYPE 中信用事件、监管事件、市场事件占大头；"
            "IMPACT_LVL 集中在 LOW/MEDIUM，HIGH/CRITICAL 较少但影响大；"
            "STATUS 在 OPEN/PROCESSING/RESOLVED/CLOSED 之间流转。"
        ),
        trend=(
            "信用周期下行阶段事件密度上升；季报/年报披露期间集中爆发；"
            "重大事件常引发同业相关持仓的连锁反应（行业传染）。"
        ),
        anomaly=(
            "需关注：STATUS=OPEN 长时间未跟进的事件；"
            "IMPACT_LVL=CRITICAL 但 RESOLUTION 缺失；"
            "同一发行人短时间多事件叠加（深度危机征兆）；"
            "RELATED_PORTS 缺失但实际持仓存在的关联缺漏。"
        ),
        scenarios=[
            "重大事件追溯与组合影响评估",
            "信用违约的回收与减损跟踪",
            "监管处罚事件的合规整改",
            "停牌/退市事件的估值切换",
            "事件后的同业持仓敞口排查",
            "年度风险事件复盘报告",
        ],
        key_fields=[
            "EVENT_ID", "EVENT_DT", "EVENT_TYPE", "EVENT_NM",
            "IMPACT_LVL", "RELATED_AST", "RELATED_ISR", "RELATED_PORTS",
            "DESC", "RESOLUTION", "STATUS", "CLOSE_DT",
        ],
        primary_keys=["EVENT_ID"],
        foreign_keys={
            "RELATED_AST": "dwd_ast_info.AST_CD",
            "RELATED_ISR": "dwd_ast_isr_info.ISR_ID",
        },
    ),
}
