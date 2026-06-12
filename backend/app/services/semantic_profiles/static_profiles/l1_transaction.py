"""
交易域(Transaction Domain) - L1静态画像定义
覆盖：委托单/成交/结算/费用/回购/外汇 共 6 张表
"""
from ..models import DomainOverview, TableProfile


DOMAIN_OVERVIEW = DomainOverview(
    domain_code="transaction",
    domain_name="交易域",
    description=(
        "记录组合从委托下单、成交确认、清算结算、交易费用，到回购融资与外汇交易的"
        "完整交易链路，是组合调仓与资金运作的执行账本。下游为估值、风险与绩效核算"
        "提供原始交易事实数据。"
    ),
    table_count=6,
    tables=[
        "dwd_trn_order",
        "dwd_trn_trade_ast",
        "dwd_trn_settle",
        "dwd_trn_fee",
        "dwd_trn_repo",
        "dwd_trn_fx",
    ],
    core_scenarios=[
        "交易执行与成交分析",
        "结算异常与失败追踪",
        "交易费用归集与成本归因",
        "回购融资敞口与资金成本监控",
        "外汇交易与汇率敞口分析",
        "调仓行为与交易员绩效评估",
    ],
    key_entities=[
        "ORDER_ID", "TRADE_ID", "SETTLE_ID", "FEE_ID",
        "REPO_ID", "FX_DEAL_ID", "PORT_ID", "AST_CD", "CNTP_ID",
    ],
)


TABLE_PROFILES = {
    "dwd_trn_order": TableProfile(
        table_name="dwd_trn_order",
        domain="transaction",
        display_name="交易委托单表",
        purpose=(
            "记录交易员或算法系统下达的全部委托指令，含目标价、目标量、成交进度与"
            "委托状态，是交易执行链路的入口事实表。"
        ),
        distribution=(
            "ORDER_STATUS 以 FILLED 为主（>80%），PARTIAL/CANCELLED/REJECTED 为长尾；"
            "ORDER_DIR 在 BUY/SELL 之间相对均衡；ORDER_SRC 集中在 MANUAL，少量 ALGO/API；"
            "按 PORT_ID/AST_CD 维度呈现明显的交易日内集中分布（开盘 9:30-10:00 与午后 13:30-14:00 两高峰）。"
        ),
        trend=(
            "工作日有委托、节假日为零；月末/季末调仓窗口委托量显著放大；"
            "在政策/事件驱动日（降准、评级下调、信用事件）出现单日突增。"
        ),
        anomaly=(
            "需关注：FILLED_QTY > ORDER_QTY 的越权成交；超长 PENDING（同日未结束）委托；"
            "频繁 CANCELLED 的「假单」行为；同一 PORT_ID 同 AST_CD 短时间内反向对敲委托；"
            "ORDER_PRC 与同期市场价偏离超过 1% 的异常报价。"
        ),
        scenarios=[
            "查询某组合某日全部委托及成交进度",
            "分析交易员/算法的撤单率与执行质量",
            "定位 PARTIAL/REJECTED 委托的根因",
            "识别异常报价或对敲嫌疑的委托",
            "统计某资产某日委托方向不平衡度",
            "复盘大额调仓的委托拆分策略",
        ],
        key_fields=[
            "ORDER_ID", "PORT_ID", "AST_CD", "ORDER_DT", "ORDER_TIME",
            "ORDER_DIR", "ORDER_PRC", "ORDER_QTY", "FILLED_QTY",
            "ORDER_STATUS", "ORDER_SRC", "TRADER",
        ],
        primary_keys=["ORDER_ID"],
        foreign_keys={
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
            "AST_CD": "dwd_ast_info.AST_CD",
        },
    ),

    "dwd_trn_trade_ast": TableProfile(
        table_name="dwd_trn_trade_ast",
        domain="transaction",
        display_name="资产成交记录表",
        purpose=(
            "记录组合在二级市场的全部成交流水，包含成交价、收益率、面额、结算金额、"
            "应计利息与对手方信息，是调仓损益与持仓变动的核心源头。"
        ),
        distribution=(
            "TRADE_TYPE 以 OUTRIGHT（现券买卖）为主，REPO/PLEDGE 为流动性管理工具；"
            "TRADE_DIR 多空相对均衡，但纯债组合通常 BUY 略多；"
            "FACE_AMT 集中在 5000 万-3 亿元区间；TRADE_YIELD 按资产类型呈簇状分布"
            "（利率债 1.9%-2.4%、AAA 信用 2.5%-3.0%、AA 及以下 3.5%+）。"
        ),
        trend=(
            "日均成交笔数随市场活跃度波动；季末配置盘集中放量；"
            "评级下调或信用事件后会出现持仓资产的避险性集中卖出。"
        ),
        anomaly=(
            "需关注：TRADE_PRC 偏离同日中债估值价 0.5% 以上；TRADE_YIELD 与曲线对应久期"
            "明显背离；SETTLE_AMT 计算与 FACE_AMT*TRADE_PRC 严重不符；"
            "同一 PORT_ID 当日对同一 AST_CD 的反向高频成交；"
            "STATUS 长期停留在非 SETTLED。"
        ),
        scenarios=[
            "复盘某只债券的买卖时点与盈亏",
            "估值对比：成交价 vs 中债/中证估值",
            "对手方集中度与最佳执行分析",
            "组合调仓换手率与久期变化分析",
            "信用事件后的减持行为追踪",
            "TWAP/VWAP 等执行算法的业绩归因",
        ],
        key_fields=[
            "TRADE_ID", "PORT_ID", "AST_CD", "TRADE_DT", "SETTLE_DT",
            "TRADE_DIR", "TRADE_TYPE", "TRADE_PRC", "TRADE_YIELD",
            "FACE_AMT", "SETTLE_AMT", "ACCRUED_INT",
            "CNTP_ID", "TRADER", "STATUS",
        ],
        primary_keys=["TRADE_ID"],
        foreign_keys={
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
            "AST_CD": "dwd_ast_info.AST_CD",
            "CNTP_ID": "dwd_cntp_info.CNTP_ID",
        },
    ),

    "dwd_trn_settle": TableProfile(
        table_name="dwd_trn_settle",
        domain="transaction",
        display_name="交易结算记录表",
        purpose=(
            "记录每笔成交的清算交收信息，含 DVP/FOP 结算方式、资金/券方向、"
            "资金账户与债券账户，是核对资金到账与券款对付的事实表。"
        ),
        distribution=(
            "SETTLE_TYPE 以 DVP（券款对付）为绝对主流，FOP（券款分离）多用于回购交收；"
            "STATUS 大多为 SETTLED，PENDING/FAILED 应是少数；"
            "SETTLE_DT 多数为 T+1（银行间）或 T+0/T+1（交易所）。"
        ),
        trend=(
            "结算量呈现 T+1 滞后于交易日的波形；月末/季末因大额调仓集中出现结算高峰；"
            "节假日前后会出现结算压缩或顺延。"
        ),
        anomaly=(
            "需关注：STATUS=FAILED 或长期 PENDING 的交收失败；SETTLE_AMT 与"
            "成交表 SETTLE_AMT 不一致；BOND_DIR 与 CASH_DIR 方向不互补；"
            "BOND_ACCT 或 CASH_ACCT 缺失；超过 T+3 仍未结算的极端滞后。"
        ),
        scenarios=[
            "查询某笔成交的实际交收状态",
            "定位结算失败/延迟的笔次并归因",
            "资金账户与债券账户的资金流轧差",
            "DVP 与 FOP 比例及风险敞口监控",
            "月末/节前结算量预测与人力安排",
            "组合实际可用资金的T+N 推算",
        ],
        key_fields=[
            "SETTLE_ID", "TRADE_ID", "PORT_ID", "SETTLE_DT", "SETTLE_TYPE",
            "SETTLE_AMT", "CASH_DIR", "BOND_DIR", "BOND_ACCT", "CASH_ACCT",
            "STATUS",
        ],
        primary_keys=["SETTLE_ID"],
        foreign_keys={
            "TRADE_ID": "dwd_trn_trade_ast.TRADE_ID",
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
        },
    ),

    "dwd_trn_fee": TableProfile(
        table_name="dwd_trn_fee",
        domain="transaction",
        display_name="交易费用表",
        purpose=(
            "归集每笔成交所产生的各类费用（券商佣金、托管费、印花税、过户费、"
            "结算费、清算所费等），是交易成本归因与费率合规的事实表。"
        ),
        distribution=(
            "FEE_TYPE 以 BROKER（佣金）笔数最多，CUSTODY（托管）按周期摊销；"
            "FEE_RATE 按市场约定呈簇状分布（银行间券商 0.005‰、交易所 ETF 申赎万分之五等）；"
            "FEE_AMT 与 SETTLE_AMT 强正相关，呈右偏长尾分布。"
        ),
        trend=(
            "随交易量同步波动；季度末大额调仓导致费用峰值；"
            "费率政策调整或券商谈判后会出现整体水平的台阶式变化。"
        ),
        anomaly=(
            "需关注：FEE_RATE 偏离同类业务标准 20% 以上；FEE_AMT 与 FEE_RATE*SETTLE_AMT"
            "严重不符；同一笔 TRADE_ID 出现重复 BROKER 费用；"
            "FEE_DT 早于 TRADE_DT 的时间倒挂；零佣金或异常高佣金的极端值。"
        ),
        scenarios=[
            "组合交易成本归因（按费用类型/对手方）",
            "券商佣金合规性与最佳执行评估",
            "季度费率谈判前的成本基线测算",
            "异常高费率的合规审计",
            "ETF/QFII 等特殊业务的费用核对",
            "组合管理费率与交易成本对比",
        ],
        key_fields=[
            "FEE_ID", "TRADE_ID", "PORT_ID", "FEE_TYPE",
            "FEE_AMT", "FEE_RATE", "FEE_DT",
        ],
        primary_keys=["FEE_ID"],
        foreign_keys={
            "TRADE_ID": "dwd_trn_trade_ast.TRADE_ID",
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
        },
    ),

    "dwd_trn_repo": TableProfile(
        table_name="dwd_trn_repo",
        domain="transaction",
        display_name="回购交易表",
        purpose=(
            "记录组合在银行间/交易所市场的回购融资与逆回购融出业务，含质押券、"
            "回购利率、起止日与对手方，是组合杠杆与短期资金管理的核心表。"
        ),
        distribution=(
            "REPO_TYPE 以 PLEDGE（质押式）为绝对主流，OUTRIGHT（买断式）较少；"
            "REPO_DIR 中纯债/混合组合以 LEND（融出）为主，杠杆型组合以 BORROW（融入）为主；"
            "期限集中于 1D/7D/14D，少量 1M+；REPO_RATE 围绕 DR007/R007 中枢波动。"
        ),
        trend=(
            "月末、季末、税期与春节前后融资需求显著走高，REPO_RATE 短时上行；"
            "央行 OMO/MLF 投放后利率回落；信用事件可能引发质押品折扣率骤升。"
        ),
        anomaly=(
            "需关注：REPO_RATE 短时偏离 DR007 50bp 以上；STATUS=ACTIVE 但 END_DT 已过的"
            "未到期清理异常；同一 COLLATERAL_CD 被重复质押的合规风险；"
            "BORROW 业务导致组合杠杆率超过监管/合同上限；对手方信用恶化时的展期风险。"
        ),
        scenarios=[
            "组合杠杆率监控与回购到期分布",
            "资金成本与 DR007/R007 比对分析",
            "质押品集中度与折扣率监控",
            "对手方授信使用率与集中度分析",
            "节假日资金缺口预测与应对",
            "套息交易盈利测算（持有票息 - 回购成本）",
        ],
        key_fields=[
            "REPO_ID", "PORT_ID", "REPO_TYPE", "REPO_DIR",
            "START_DT", "END_DT", "REPO_RATE", "REPO_AMT",
            "COLLATERAL_CD", "CNTP_ID", "STATUS",
        ],
        primary_keys=["REPO_ID"],
        foreign_keys={
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
            "COLLATERAL_CD": "dwd_ast_info.AST_CD",
            "CNTP_ID": "dwd_cntp_info.CNTP_ID",
        },
    ),

    "dwd_trn_fx": TableProfile(
        table_name="dwd_trn_fx",
        domain="transaction",
        display_name="外汇交易表",
        purpose=(
            "记录组合的即期、远期、掉期外汇交易，含买卖币对、汇率、本外币金额、"
            "起息日与到期日，是 QDII/跨境组合汇率敞口管理的事实表。"
        ),
        distribution=(
            "DEAL_TYPE 中 SPOT（即期）笔数最多、FORWARD/SWAP 用于对冲；"
            "CCY_PAIR 以 USD/CNY 为主，少量 EUR/CNY、HKD/CNY、JPY/CNY；"
            "DEAL_AMT 集中在百万-千万美元当量级，机构组合可达亿美元级。"
        ),
        trend=(
            "美联储议息周、地缘政治事件与中美利差变动驱动交易量起伏；"
            "财年末与跨年存在集中对冲需求；离岸/在岸价差扩大时套利交易增多。"
        ),
        anomaly=(
            "需关注：DEAL_RATE 偏离 CFETS 中间价超过 1%；FORWARD_PTS（远期点）"
            "与利率平价隐含价差严重背离；同一组合同日反向对敲外汇交易；"
            "STATUS 长期未交收（SETTLE_DT 已过）；本外币金额轧差不为零。"
        ),
        scenarios=[
            "QDII 组合外汇敞口与对冲比例",
            "汇率成本归因与最佳执行评估",
            "远期点与隐含利差套利分析",
            "跨币种结算与时差风险监控",
            "重大事件冲击下的汇率交易复盘",
            "汇兑损益与组合净值波动归因",
        ],
        key_fields=[
            "FX_DEAL_ID", "PORT_ID", "DEAL_DT", "DEAL_TYPE",
            "CCY_PAIR", "BUY_CCY", "SELL_CCY", "DEAL_RATE",
            "DEAL_AMT", "VALUE_DT", "MATURITY_DT", "CNTP_ID", "STATUS",
        ],
        primary_keys=["FX_DEAL_ID"],
        foreign_keys={
            "PORT_ID": "dwd_prd_port_info.PORT_ID",
            "CNTP_ID": "dwd_cntp_info.CNTP_ID",
        },
    ),
}
