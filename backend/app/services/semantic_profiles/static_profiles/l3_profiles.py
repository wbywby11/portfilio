"""
L3 跨域表间画像定义

汇总 5 条核心跨域穿透链路，覆盖产品/资产/主体/交易/估值/行情/客户/风险等多域的协同视图。
每条链路给出实际的外键穿透路径（join_path）、跨域分布、趋势、异常与典型业务场景。
"""
from ..models import CrossDomainProfile


CROSS_DOMAIN_PROFILES = {
    # ============================================================
    # 1. 产品持仓穿透主体财务视图 — PTL × AST × ISR
    # ============================================================
    "ptl_ast_isr": CrossDomainProfile(
        profile_id="ptl_ast_isr",
        profile_name="产品持仓穿透主体财务视图",
        domains_involved=["product", "asset", "subject"],
        tables_involved=[
            "dwd_ptl_info", "dwd_ptl_ast_hld",
            "dwd_ast_info", "dwd_ast_fiveclass",
            "dwd_isr_institution", "dwd_isr_institution_finance",
        ],
        join_path=(
            "dwd_ptl_info(PORT_ID) "
            "→ dwd_ptl_ast_hld(PORT_ID, AST_CD, BIZ_DT) "
            "→ dwd_ast_info(AST_CD, ISR_ID) "
            "→ dwd_ast_fiveclass(AST_CD) [LEFT JOIN] "
            "→ dwd_isr_institution(ISR_ID) "
            "→ dwd_isr_institution_finance(ISR_ID, RPT_DT)"
        ),
        structure=(
            "产品 1:N 持仓资产 N:1 发行人 1:N 财报。形成『产品 → 资产 → 发行人 → 财务』四级穿透树。"
            "可按 PORT_ID 聚合到发行人维度（先 AST 再 ISR），从而生成产品的发行人敞口与"
            "对应发行人的资产质量画像。"
        ),
        distribution=(
            "5 个产品向 8 个发行人形成 20~30 条非零持仓敞口。债券型产品（PORT002/PORT004）发行人集中度更高，"
            "财政部 + 政策性银行合计敞口可达 60%；混合型产品（PORT003）则在产业债（万科、新能源）有 10%~15% 敞口。"
            "财报覆盖 4 个标准报告期，机构净资产规模差异大但同行业内 ROE/资产负债率分布稳定。"
        ),
        trend=(
            "随着 BIZ_DT 推进，组合敞口缓慢迁移：①利率上行期国债敞口收缩、信用债下沉；"
            "②被穿透发行人财报季度更新带来的资产质量变化逐期反馈；"
            "③临近季末机构主体大概率发布预告，形成『预告 → 财报 → 评级 → 敞口调整』的领先关系。"
        ),
        anomaly=(
            "重点排查：①持仓资产对应 ISR_ID 在主体域不存在（孤儿外键）；"
            "②发行人最近一期财报缺失或滞后 > 90 天；"
            "③单一发行人敞口占组合净值 > 10% 触发集中度违规；"
            "④五级分类降级到关注/不良但敞口未压缩；"
            "⑤发行人资产负债率单期上升 > 5pct 但持仓未减持；"
            "⑥发行人净利润转负而其债券估值未下调。"
        ),
        scenarios=[
            "组合季度排雷与发行人财务穿透",
            "信用下沉策略安全性评估",
            "集中度违规识别（双十规则、发行人敞口）",
            "财报披露期事件驱动调仓",
            "ESG/行业敞口视图与重定向",
            "持仓资产五级分类与发行人健康度对照",
        ],
    ),

    # ============================================================
    # 2. 交易流水穿透行情视图 — TRN × AST × MKT
    # ============================================================
    "trn_ast_mkt": CrossDomainProfile(
        profile_id="trn_ast_mkt",
        profile_name="交易流水穿透行情对照视图",
        domains_involved=["transaction", "asset", "market"],
        tables_involved=[
            "dwd_trn_order", "dwd_trn_trade_ast",
            "dwd_ast_info",
            "dwd_mkt_bond", "dwd_mkt_bond_market",
            "dwd_mkt_stock", "dwd_mkt_index_quote",
            "dwd_mkt_curve_quote",
        ],
        join_path=(
            "dwd_trn_order(ORDER_ID) "
            "→ dwd_trn_trade_ast(ORDER_ID, TRADE_ID, AST_CD, TRADE_DT) "
            "→ dwd_ast_info(AST_CD, AST_TYPE) "
            "→ dwd_mkt_bond / dwd_mkt_stock / dwd_mkt_fund(AST_CD, BIZ_DT=TRADE_DT) "
            "→ dwd_mkt_curve_quote(CURVE_ID, TENOR, BIZ_DT) [估值参考]"
        ),
        structure=(
            "成交记录 1:1 对应行情快照（按 AST_CD + BIZ_DT），通过资产类型分流到债券/股票/基金行情表。"
            "曲线行情表用于债券交易的估值参考（同期限 CGB/CDB 收益率）。"
            "形成『订单 → 成交 → 资产 → 市场 → 曲线』五级穿透。"
        ),
        distribution=(
            "成交价格分布以行情中价为中心，债券±5BP、股票±0.3% 为典型偏离区间；"
            "成交量在月末/季末上行（再平衡触发）；"
            "债券交易约 70% 在银行间，股票/ETF 约 30% 在交易所；"
            "对手方集中度 CR3 ≈ 70%。"
        ),
        trend=(
            "结合曲线快照可观察『交易加权成交收益率 vs 当日中债估值 YTM 的滚动偏离序列』，"
            "其趋势揭示市场流动性与估值偏离方向。曲线陡平变化通常领先交易行为 2~5 个交易日，"
            "在曲线陡峭化阶段长端债券成交活跃度上升。"
        ),
        anomaly=(
            "重点排查：①成交价偏离当日 VWAP > 50BP（债券）或 > 1%（股票）；"
            "②无对应行情快照的『盲区交易』（行情未发布或资产停牌）；"
            "③成交日为非交易日（calendar 校验失败）；"
            "④同一资产同日反向交易超过持仓 30%（疑似对敲）；"
            "⑤成交后行情连续 3 日异常波动 > 3σ 的可能内幕信号。"
        ),
        scenarios=[
            "成交质量评估（VWAP/TWAP/Implementation Shortfall）",
            "异常交易行为识别与合规审计",
            "停牌/未上市资产的盲区交易告警",
            "成交收益率 vs 估值收益率偏离监控",
            "市场流动性与成交活跃度联动分析",
            "曲线陡平与交易策略归因",
        ],
    ),

    # ============================================================
    # 3. 客户持仓穿透产品估值视图 — CUS × PTL × VAL
    # ============================================================
    "cus_ptl_val": CrossDomainProfile(
        profile_id="cus_ptl_val",
        profile_name="客户持仓穿透产品估值视图",
        domains_involved=["customer", "product", "valuation"],
        tables_involved=[
            "dwd_cust_info", "dwd_cust_make_pstn_info",
            "dwd_cust_trans_apply_info_ta", "dwd_cust_trans_cfm_info",
            "dwd_ptl_info", "dwd_ptl_holder_summary",
            "dwd_val_summary", "dwd_val_notice",
        ],
        join_path=(
            "dwd_cust_info(CUSTOMER_ID) "
            "→ dwd_cust_make_pstn_info(CUSTOMER_ID, PORT_ID, BIZ_DT) "
            "→ dwd_ptl_info(PORT_ID) "
            "→ dwd_val_summary(PORT_ID, BIZ_DT) "
            "→ dwd_val_notice(PORT_ID, BIZ_DT) "
            "→ dwd_ptl_holder_summary(PORT_ID, BIZ_DT) [验证份额]"
        ),
        structure=(
            "客户 1:N 持仓产品 N:1 估值快照。客户视角的市值 = 持仓份额 × 产品 NAV。"
            "通过申请 _ta + 确认 _cfm 形成份额变动闭环，最终在 holder_summary 与客户持仓表对账。"
        ),
        distribution=(
            "7 名客户合计持仓覆盖 5 个产品，机构客户单产品持仓金额占其总持仓 60%~80%；"
            "零售客户更多分散持有 2~3 个产品。NAV 日变动幅度 < 0.5% 为常态，"
            "客户单日市值波动主要由 NAV 变化驱动而非份额变动。"
        ),
        trend=(
            "申购集中在产品发行期与净值低位（逢低买入）；"
            "赎回集中在月末/季末（资金回流）与净值新高后（获利了结）；"
            "客户持有期分布呈现『机构长持 + 零售短炒』的双峰特征。"
        ),
        anomaly=(
            "重点排查：①客户持仓份额与申请-确认-分红计算结果不一致（差异 > 0.01 份）；"
            "②产品适当性管理违规（高风险产品被低风险等级客户持有）；"
            "③单客户单日赎回 > 客户持仓 30% 的大额异动；"
            "④NAV 异常下跌 > 3σ 但客户未触发预警通知；"
            "⑤估值发布滞后（_notice.PUBLISH_TIME 晚于 BIZ_DT 的 T+1 18:00）；"
            "⑥客户大额申购后 3 日内即赎回的疑似洗钱模式。"
        ),
        scenarios=[
            "客户市值实时穿透与盈亏计算",
            "适当性管理与风险等级匹配审计",
            "客户级流动性预测（赎回压力测试）",
            "净值披露合规时效监控",
            "VIP 客户行为画像与挽留策略",
            "反洗钱可疑交易识别",
        ],
    ),

    # ============================================================
    # 4. 风险敞口穿透资产产品视图 — RSK × ISR × AST × PTL
    # ============================================================
    "rsk_isr_ast_ptl": CrossDomainProfile(
        profile_id="rsk_isr_ast_ptl",
        profile_name="风险敞口穿透资产产品视图",
        domains_involved=["risk", "subject", "asset", "product"],
        tables_involved=[
            "dwd_rsk_credit", "dwd_rsk_credit_position",
            "dwd_rsk_sentiment", "dwd_crdt_agme_info",
            "dwd_isr_institution",
            "dwd_ast_info",
            "dwd_ptl_ast_hld",
        ],
        join_path=(
            "dwd_rsk_credit(ISR_ID, RATING_DT) "
            "→ dwd_isr_institution(ISR_ID) "
            "→ dwd_ast_info(ISR_ID, AST_CD) "
            "→ dwd_ptl_ast_hld(AST_CD, PORT_ID, BIZ_DT) "
            "→ dwd_rsk_credit_position(PORT_ID, ISR_ID) [回写敞口] "
            "→ dwd_rsk_sentiment(ISR_ID, EVENT_DT) [LEFT JOIN] "
            "→ dwd_crdt_agme_info(GUARANTOR_ISR_ID/DEBTOR_ISR_ID) [担保链]"
        ),
        structure=(
            "风险因子 → 主体 → 资产 → 产品的反向穿透链路，叠加担保链与舆情事件，"
            "形成立体的『风险源-传导路径-持仓后果』图。一笔评级下调可同时关联多产品多笔持仓，"
            "通过 _credit_position 实现敞口口径统一。"
        ),
        distribution=(
            "8 个发行人的内部信用评级集中在 AAA-AA 级，敞口上 60%+ 集中在政策性银行与国有大行；"
            "舆情事件按行业分布，地产与新能源行业负面事件占比较高；"
            "担保链平均深度 2 层，互保结构以同业为主。"
        ),
        trend=(
            "评级下调 → 行情利差走阔 → 估值下调 → 敞口被动减少的传导链条通常在 1~5 个交易日内完成；"
            "舆情负面事件至评级下调存在 5~30 天领先期；"
            "担保人评级先于债务人下调时常成为风险传染前哨指标。"
        ),
        anomaly=(
            "重点排查：①评级下调或负面舆情后持仓未及时减持；"
            "②单一发行人敞口（含担保穿透）> 组合净值 10%；"
            "③担保链中担保人自身评级 < 债务人（担保增信失效）；"
            "④互保循环导致风险净敞口被低估；"
            "⑤舆情情感分单日 < -0.7 但内部评级未触发复评；"
            "⑥同一发行人在不同产品评级口径不一致。"
        ),
        scenarios=[
            "信用风险传导链路重建",
            "舆情驱动的早期减持决策",
            "担保穿透后的真实敞口测算",
            "信用集中度合规与压力测试",
            "评级迁徙归因分析",
            "风险事件多产品影响评估",
        ],
    ),

    # ============================================================
    # 5. 估值验证穿透行情视图 — VAL × AST × MKT
    # ============================================================
    "val_ast_mkt": CrossDomainProfile(
        profile_id="val_ast_mkt",
        profile_name="估值验证穿透行情视图",
        domains_involved=["valuation", "asset", "market"],
        tables_involved=[
            "dwd_val_summary", "dwd_val_detail",
            "dwd_ast_info", "dwd_ast_info_zg", "dwd_ast_info_ch",
            "dwd_mkt_bond", "dwd_mkt_bond_market",
            "dwd_mkt_stock", "dwd_mkt_fund",
            "dwd_mkt_curve_quote", "dwd_mkt_exrate",
        ],
        join_path=(
            "dwd_val_summary(PORT_ID, BIZ_DT) "
            "→ dwd_val_detail(PORT_ID, AST_CD, BIZ_DT) "
            "→ dwd_ast_info(AST_CD, AST_TYPE, CCY) "
            "→ dwd_ast_info_zg / dwd_ast_info_ch(AST_CD, BIZ_DT) "
            "→ dwd_mkt_bond / dwd_mkt_stock / dwd_mkt_fund(AST_CD, BIZ_DT) "
            "→ dwd_mkt_curve_quote(CURVE_ID, TENOR, BIZ_DT) "
            "→ dwd_mkt_exrate(CCY_PAIR, BIZ_DT) [外币持仓]"
        ),
        structure=(
            "估值明细按资产逐笔与市场行情比对，形成『内部估值 vs 第三方估值（中债/中证）vs 市场行情』的三角验证。"
            "外币资产需加入汇率折算回本币口径。曲线行情提供利率敏感性归因。"
        ),
        distribution=(
            "债券估值占组合 60%~80%（按摊余/公允双口径），股票/基金按公允价值；"
            "中债与中证估值多数情况下偏离 < 10BP，但在评级临近调整或低流动性资产上偏离扩大；"
            "外币敞口主要在 USD/HKD（小比例 QDII 配置）。"
        ),
        trend=(
            "估值偏离序列通常呈均值回复，但在市场剧烈波动期（信用事件、央行政策转向）"
            "可能出现 2~5 个交易日的趋势性偏离；曲线变化驱动债券估值的久期敏感性可被实时归因。"
        ),
        anomaly=(
            "重点排查：①val_detail 的 PRICE 偏离行情收盘价 > 1%（股票）或 > 50BP（债券）；"
            "②中债 vs 中证估值偏离 > 30BP 的双源不一致；"
            "③外币资产折算汇率与 _exrate 不符；"
            "④估值缺失对应行情快照（行情拉取失败但估值仍生成）；"
            "⑤摊余成本法下的偏离度 > 0.5% 触发影子定价告警；"
            "⑥曲线整体平移 10BP 但债券估值未跟随调整。"
        ),
        scenarios=[
            "估值合理性自动核验",
            "公允价值偏离影子定价预警",
            "利率/曲线归因（收益率分解）",
            "外币持仓汇率敞口测算",
            "估值差异溯源与责任落地",
            "净值发布前异常拦截",
        ],
    ),
    # ============================================================
    # 6. 数据接入 × 风险 × 主体 — 舆情主体穿透视图
    # ============================================================
    "datahub_risk_subject": CrossDomainProfile(
        profile_id="datahub_risk_subject",
        profile_name="舆情主体穿透视图",
        domains_involved=["data_hub", "risk", "subject", "product"],
        tables_involved=[
            "subject_risk_records",
            "dwd_rsk_sentiment",
            "dwd_isr_institution",
            "dwd_ptl_ast_hld",
            "dwd_ptl_info",
        ],
        join_path=(
            "subject_risk_records(subject_name) "
            "→ dwd_isr_institution(ISR_NM) [模糊匹配] "
            "→ dwd_rsk_sentiment(TARGET_CD=ISR_ID) "
            "→ dwd_ptl_ast_hld(AST_CD, PORT_ID) "
            "→ dwd_ptl_info(PORT_ID)"
        ),
        structure=(
            "从外部舆情信号（subject_risk_records）穿透到主体域（dwd_isr_institution）的“”主体名称“”匹配，"
            "再关联风险域舆情表（dwd_rsk_sentiment）形成双源舆情融合，"
            "最终穿透到产品域持仓表查看受影响产品的敞口。"
            "形成『舆情信号 → 主体识别 → 舆情融合 → 持仓敞口』四级预警链。"
        ),
        distribution=(
            "外部舆情信号（data_hub）与内部舆情（dwd_rsk_sentiment）的交集通常为 30-50%，"
            "外部独佔部分多为司法、征信等监管源信息；"
            "高风险主体关联的持仓产品通常占产品总数的 10-20%。"
        ),
        trend=(
            "外部舆情信号通常领先内部舆情 1-3 个工作日；"
            "当同一主体在双源舆情中同时出现时，风险升级概率显著增加；"
            "季末/年末财报披露期与舆情高峰重合。"
        ),
        anomaly=(
            "重点排查：①高风险主体仍被产品持仓且敞口未压缩；"
            "②外部舆情高但内部舆情未触发（内部监测延迟）；"
            "③主体名称模糊匹配导致误关联（同名不同实体）；"
            "④否决类/黑名单客户仍有新增风险信号。"
        ),
        scenarios=[
            "高风险主体的产品持仓敞口排查",
            "双源舆情融合分析与风险升级预警",
            "否决类客户的风险事件持续监控",
            "舆情信号到持仓影响的快速溯源",
        ],
    ),
    # ============================================================
    # 7. 数据接入 × 产品 — 外部产品数据与内部产品域桥接视图
    # ============================================================
    "datahub_product_bridge": CrossDomainProfile(
        profile_id="datahub_product_bridge",
        profile_name="外部产品数据与内部产品域桥接视图",
        domains_involved=["data_hub", "product"],
        tables_involved=[
            "zysc_ptl_info_records",
            "zysc_ptl_holder_records",
            "dwd_ptl_info",
            "dwd_ptl_holder_summary",
            "dwd_ptl_ast_hld",
        ],
        join_path=(
            "zysc_ptl_info_records(产品代码) "
            "→ dwd_ptl_info(PORT_ID) [产品代码映射] "
            "→ dwd_ptl_ast_hld(PORT_ID, AST_CD) "
            "\nzysc_ptl_holder_records(产品代码) "
            "→ dwd_ptl_holder_summary(PORT_ID, BIZ_DT) [持有人数据融合]"
        ),
        structure=(
            "外部数据接入域的产品信息表（zysc_ptl_info_records）与内部产品域（dwd_ptl_info）"
            "通过产品代码形成桥接，补充外部视角的基准、策略、开放频率等字段；"
            "外部持有人表（zysc_ptl_holder_records）与内部持有人汇总表（dwd_ptl_holder_summary）"
            "形成双源持有人结构对比。"
        ),
        distribution=(
            "外部产品表覆盖的产品代码通常比内部产品域更广（含全市场产品）；"
            "持有人数据的外部源和内部源在机构/个人比例上差异通常 < 5%，"
            "但部分定制产品可能存在差异（外部含穿透后口径）。"
        ),
        trend=(
            "外部产品数据按周/月更新，内部产品域按日更新；"
            "持有人结构双源数据在季报披露期对齐度最高。"
        ),
        anomaly=(
            "重点排查：①外部产品表存在但内部产品域不存在的产品（新增未同步）；"
            "②双源持有人数据机构占比差异 > 10%（数据口径不一致）；"
            "③外部产品到期日已过但内部状态仍为“存续”（状态未同步）；"
            "④外部基准上下限倒挂或合约基准为null。"
        ),
        scenarios=[
            "内外部产品数据完整性对比",
            "双源持有人结构差异分析",
            "外部产品全市场视角 vs 内部持仓视角",
            "新发产品同步状态监控",
        ],
    ),
}
