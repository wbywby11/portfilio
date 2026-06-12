"""
行情域(Market Domain) - L1静态画像定义
覆盖：债券/股票/基金/指数/外汇/利率/大宗/衍生品/回购/ABS/可转债/曲线/基准/
波动率/流动性/信用利差/行业指数/宏观/日历/节假日/交易所/停牌/IPO/评级动作
共 25 张表
"""
from ..models import DomainOverview, TableProfile, FieldProfile


DOMAIN_OVERVIEW = DomainOverview(
    domain_code="market",
    domain_name="行情域",
    description=(
        "汇集多市场、多品种的行情时间序列数据：现货价格、收益率、汇率、商品、"
        "衍生品、宏观指标与市场基础设施信息（日历、停牌、IPO、评级动作等），"
        "是估值、绩效归因、风险计量与策略研究的统一数据源。"
    ),
    table_count=25,
    tables=[
        "dwd_mkt_bond", "dwd_mkt_equity", "dwd_mkt_fund", "dwd_mkt_index",
        "dwd_mkt_fx", "dwd_mkt_ir", "dwd_mkt_commodity", "dwd_mkt_derivative",
        "dwd_mkt_repo", "dwd_mkt_abs", "dwd_mkt_convertible",
        "dwd_mkt_curve_point", "dwd_mkt_curve_def", "dwd_mkt_benchmark",
        "dwd_mkt_vol_surface", "dwd_mkt_liquidity", "dwd_mkt_credit_spread",
        "dwd_mkt_sector_index", "dwd_mkt_macro", "dwd_mkt_calendar",
        "dwd_mkt_holiday", "dwd_mkt_exchange_info", "dwd_mkt_trading_halt",
        "dwd_mkt_ipo_calendar", "dwd_mkt_rating_action",
    ],
    core_scenarios=[
        "组合估值与净值计算",
        "收益率曲线/利差/波动率构造",
        "行情驱动的策略回测与因子研究",
        "宏观与政策事件影响分析",
        "交易日历/停牌/节假日合规校验",
        "评级动作驱动的信用研究",
        "IPO 申购与新股研究",
    ],
    key_entities=[
        "AST_CD", "INDEX_CD", "CURVE_ID", "CCY_PAIR",
        "BIZ_DT", "EXCHANGE_CD", "IPO_CD", "ISR_ID",
    ],
)


TABLE_PROFILES = {
    "dwd_mkt_bond": TableProfile(
        table_name="dwd_mkt_bond",
        domain="market",
        display_name="债券行情表",
        purpose=(
            "存储银行间与交易所债券的逐日 OHLC、收益率、久期、成交量等行情序列，"
            "是债券估值、净价/全价比对与久期管理的核心行情源。"
        ),
        distribution=(
            "AST_CD 涵盖国债、政金债、信用债、ABS、地方债等品种；YTM 按品种呈簇状"
            "（利率债 1.5%-2.5%、AAA 信用 2.5%-3.0%、AA 及以下 3.5%+）；"
            "DURATION 在 0.5 至 30 年区间，长端品种成交活跃度更低。"
        ),
        trend=(
            "工作日有数据、节假日缺失；新券上市后 1-3 个月最活跃；"
            "降准/降息/MLF 操作日全市场 YTM 同步移动；季末/年末交易量收缩。"
        ),
        anomaly=(
            "需关注：CLOSE_PRC 与中债/中证估值偏离 > 0.5%；YTM 跳点（无对应券种事件）；"
            "VOL=0 但 CLOSE_PRC 有变化的「幽灵成交」；DURATION 突变 > 1 年；"
            "节假日出现行情记录。"
        ),
        scenarios=[
            "债券估值与持仓盯市",
            "新券上市的市场反应分析",
            "久期/收益率走廊监控",
            "做市报价点差合理性",
            "成交量/换手率与流动性评估",
            "ABS/可转债等特殊券种的价格发现",
        ],
        key_fields=[
            "AST_CD", "BIZ_DT", "OPEN_PRC", "HIGH_PRC", "LOW_PRC", "CLOSE_PRC",
            "VOL", "AMT", "YTM", "CHG_BP", "DURATION",
        ],
        primary_keys=["AST_CD", "BIZ_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
        field_profiles=[
            FieldProfile(
                field_name="AST_CD",
                display_name="证券代码",
                data_type="string",
                definition="债券的唯一标识编码，关联资产域主表",
                example_values=["019601.IB", "200215.IB", "127080.SZ"],
                is_primary_key=True,
                is_foreign_key=True,
                references="dwd_ast_info.AST_CD",
                association_chains=[
                    "AST_CD → dwd_ast_info.AST_CD → dwd_ast_info.AST_NM",
                    "AST_CD → dwd_ast_info_ch.AST_CD",
                ],
                tags=["主键", "外键", "检索键"],
            ),
            FieldProfile(
                field_name="BIZ_DT",
                display_name="业务日期",
                data_type="date",
                definition="行情数据对应的交易日",
                example_values=["2026-01-06", "2026-05-20"],
                is_primary_key=True,
                is_time_series=True,
                tags=["主键", "排序键", "时序"],
            ),
            FieldProfile(
                field_name="OPEN_PRC",
                display_name="开盘价",
                data_type="number",
                definition="债券当日开盘净价",
                example_values=["100.25", "99.80"],
                unit="元",
                tags=["度量"],
            ),
            FieldProfile(
                field_name="HIGH_PRC",
                display_name="最高价",
                data_type="number",
                definition="债券当日最高成交净价",
                example_values=["100.50", "100.10"],
                unit="元",
                tags=["度量"],
            ),
            FieldProfile(
                field_name="LOW_PRC",
                display_name="最低价",
                data_type="number",
                definition="债券当日最低成交净价",
                example_values=["99.70", "99.50"],
                unit="元",
                tags=["度量"],
            ),
            FieldProfile(
                field_name="CLOSE_PRC",
                display_name="收盘价",
                data_type="number",
                definition="债券当日收盘净价，用于估值与盯市",
                example_values=["100.35", "99.90"],
                unit="元",
                tags=["度量", "检索键"],
            ),
            FieldProfile(
                field_name="VOL",
                display_name="成交量",
                data_type="number",
                definition="债券当日成交的总面值金额",
                example_values=["500000000", "2000000000"],
                unit="元",
                tags=["度量"],
            ),
            FieldProfile(
                field_name="AMT",
                display_name="成交额",
                data_type="number",
                definition="债券当日成交的总全价金额",
                example_values=["510000000", "2050000000"],
                unit="元",
                tags=["度量"],
            ),
            FieldProfile(
                field_name="YTM",
                display_name="到期收益率",
                data_type="number",
                definition="债券按当日收盘价计算的年化到期收益率",
                example_values=["2.35", "3.10", "4.50"],
                unit="%",
                tags=["度量", "检索键"],
            ),
            FieldProfile(
                field_name="DURATION",
                display_name="修正久期",
                data_type="number",
                definition="债券修正久期，反映利率敏感度",
                example_values=["2.35", "5.80", "12.50"],
                unit="年",
                tags=["度量"],
            ),
            FieldProfile(
                field_name="CHG_BP",
                display_name="收益率变动",
                data_type="number",
                definition="当日到期收益率较前一交易日的变动幅度",
                example_values=["-2.5", "1.0", "5.3"],
                unit="BP",
                is_computed=True,
                tags=["度量"],
            ),
        ],
    ),

    "dwd_mkt_equity": TableProfile(
        table_name="dwd_mkt_equity",
        domain="market",
        display_name="股票行情表",
        purpose=(
            "存储 A 股/港股/美股个股的日频 OHLC、成交量金额、PE/PB 等行情指标，"
            "支撑权益持仓估值、因子构造与策略回测。"
        ),
        distribution=(
            "AST_CD 数千至数万只；CLOSE_PRC 跨度大（几元到几千元）；"
            "PE_TTM 中位数 15-25 倍，部分行业可达 50+；TURNOVER 集中 0.5%-3%。"
        ),
        trend=(
            "单日 OHLC 围绕指数中枢波动；分红除权后价格阶跃下跌；"
            "重大政策、业绩披露日附近放量；节假日缺失。"
        ),
        anomaly=(
            "需关注：CLOSE_PRC 单日 ±10%（涨跌停）频次异常；停牌期仍有行情；"
            "ST/退市股数据延续异常；除权日未做复权调整；PE_TTM 为负或极端大值。"
        ),
        scenarios=[
            "股票持仓估值与浮动盈亏",
            "股息/除权调整的复权计算",
            "PE/PB 估值百分位分析",
            "因子（动量/价值/成长）回测",
            "停牌期持仓的特别估值",
            "板块联动与轮动研究",
        ],
        key_fields=[
            "AST_CD", "BIZ_DT", "OPEN_PRC", "HIGH_PRC", "LOW_PRC", "CLOSE_PRC",
            "VOL", "AMT", "PE_TTM", "PB_LF",
        ],
        primary_keys=["AST_CD", "BIZ_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    "dwd_mkt_fund": TableProfile(
        table_name="dwd_mkt_fund",
        domain="market",
        display_name="基金行情表",
        purpose=(
            "存储公募基金/ETF/LOF 的日频净值（NAV/累计净值）、二级市场价格、"
            "申赎数据与折溢价率，是 FoF/MoM/资产配置的输入数据。"
        ),
        distribution=(
            "NAV 集中在 0.8-3.0 区间；ETF 折溢价率围绕 0 波动 ±0.5%；"
            "AMT/VOL 在头部 ETF 集中度高；LOF 折价率长期为负是常态。"
        ),
        trend=(
            "NAV 工作日每日更新一次；行情型 ETF 二级价格分钟级波动；"
            "分红除权日 NAV 阶跃下降；节假日缺失。"
        ),
        anomaly=(
            "需关注：NAV 与申赎成本明显不一致；DISCOUNT_RATE 异常拉大（>1%）；"
            "ETF 二级 CLOSE_PRC 偏离 IOPV >0.5%；累计净值与单位净值差额突变。"
        ),
        scenarios=[
            "FOF 组合估值",
            "ETF 套利机会监控（折溢价）",
            "基金申赎流量分析",
            "基金绩效归因与持有期收益",
            "分红再投影响测算",
            "同类基金对比与排名",
        ],
        key_fields=[
            "AST_CD", "BIZ_DT", "NAV", "ACC_NAV",
            "CLOSE_PRC", "DISCOUNT_RATE", "VOL", "AMT",
        ],
        primary_keys=["AST_CD", "BIZ_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    "dwd_mkt_index": TableProfile(
        table_name="dwd_mkt_index",
        domain="market",
        display_name="指数行情表",
        purpose=(
            "存储宽基与策略指数的日频点位、成交额、涨跌幅等行情，"
            "用于业绩基准、跟踪误差计算与市场状态判断。"
        ),
        distribution=(
            "INDEX_CD 涵盖宽基（沪深300/中证500/创业板指）、债指、行业指数等；"
            "CHG_PCT 集中在 -2%~+2%，尾部 -8%~+8% 极端行情；"
            "AMT 与市场情绪强相关。"
        ),
        trend=(
            "工作日连续，节假日缺失；政策窗口、财报季、宏观数据发布日"
            "波动率显著放大；季末调仓在固定期出现高换手。"
        ),
        anomaly=(
            "需关注：CLOSE_VAL 偏离前一日 ±5% 仍无对应事件；指数编制方法变更"
            "导致的台阶；VOL/AMT 与 CHG_PCT 严重背离；"
            "节假日异常出现行情。"
        ),
        scenarios=[
            "组合相对基准的跟踪误差/超额收益",
            "市场状态监控（牛熊/震荡/极端）",
            "因子收益归因",
            "指数增强策略回测",
            "宏观与指数联动分析",
            "全市场情绪量化",
        ],
        key_fields=[
            "INDEX_CD", "BIZ_DT", "OPEN_VAL", "HIGH_VAL", "LOW_VAL", "CLOSE_VAL",
            "VOL", "AMT", "CHG_PCT",
        ],
        primary_keys=["INDEX_CD", "BIZ_DT"],
        foreign_keys={},
    ),

    "dwd_mkt_fx": TableProfile(
        table_name="dwd_mkt_fx",
        domain="market",
        display_name="外汇行情表",
        purpose=(
            "存储主要货币对的中间价、买入价、卖出价与远期点，"
            "是 QDII/跨境组合估值与汇率敞口管理的基础。"
        ),
        distribution=(
            "CCY_PAIR 以 USD/CNY 数据最全，EUR/CNY、HKD/CNY、JPY/CNY 次之；"
            "BID/ASK 价差稳定（USD/CNY 通常 5-10pip）；SOURCE 来源 CFETS/Reuters 等。"
        ),
        trend=(
            "美联储议息、地缘事件、贸易数据公布日波动放大；"
            "节前节后离岸/在岸价差扩大；季末年末汇兑结算需求集中。"
        ),
        anomaly=(
            "需关注：MID 偏离前日 ±1% 但无事件支撑；BID > ASK 报错；"
            "SOURCE 缺失；同一币对多源价差 > 0.3%。"
        ),
        scenarios=[
            "QDII 组合估值与汇兑损益",
            "汇率敞口与远期对冲设计",
            "中美利差套利分析",
            "重大事件的汇率冲击复盘",
            "多源汇率比对与套利识别",
            "结售汇时点选择",
        ],
        key_fields=[
            "CCY_PAIR", "BIZ_DT", "MID", "BID", "ASK",
            "FORWARD_PTS", "SOURCE",
        ],
        primary_keys=["CCY_PAIR", "BIZ_DT"],
        foreign_keys={},
    ),

    "dwd_mkt_ir": TableProfile(
        table_name="dwd_mkt_ir",
        domain="market",
        display_name="利率行情表",
        purpose=(
            "汇集 SHIBOR、LPR、MLF、DR、R 等关键利率指标的日频数值与变动，"
            "是货币市场分析、定价基准与浮息债估值的核心源。"
        ),
        distribution=(
            "INDICATOR 涵盖 SHIBOR(ON/1W/1M/3M)、LPR(1Y/5Y)、MLF、DR007 等；"
            "TENOR 多样；RATE 集中在 1.5%-3.5%；CHG_BP 大多在 ±5bp 内。"
        ),
        trend=(
            "MLF/LPR 月度报价；SHIBOR 每日 9:30 公布；"
            "降准/降息会导致整体下移；月末/季末/税期短端利率上行。"
        ),
        anomaly=(
            "需关注：CHG_BP > 30bp 的极端跳动；SHIBOR 期限结构倒挂；"
            "LPR 报价空缺；同一利率多源差异。"
        ),
        scenarios=[
            "浮息债定价基准取值",
            "货币市场利率走廊监控",
            "降准/降息政策效果跟踪",
            "短端流动性预测",
            "LPR 调整对房贷/信贷影响",
            "回购套息策略可行性",
        ],
        key_fields=[
            "INDICATOR", "TENOR", "BIZ_DT", "RATE", "CHG_BP", "SOURCE",
        ],
        primary_keys=["INDICATOR", "TENOR", "BIZ_DT"],
        foreign_keys={},
    ),

    "dwd_mkt_commodity": TableProfile(
        table_name="dwd_mkt_commodity",
        domain="market",
        display_name="大宗商品行情表",
        purpose=(
            "存储黄金、原油、铜、铁矿、农产品等大宗商品的日频价格与涨跌幅，"
            "辅助宏观研究、通胀传导与资源类资产研究。"
        ),
        distribution=(
            "COMMODITY 涵盖贵金属/能源/有色/黑色/农产品；UNIT 多样；"
            "CHG_PCT 大多在 ±3%，地缘事件可达 ±10%。"
        ),
        trend=(
            "OPEC 会议、地缘冲突、库存数据发布日波动放大；"
            "美元强弱反向影响商品价格；季节性影响（取暖油冬季、农产品种植期）。"
        ),
        anomaly=(
            "需关注：单日 ±10% 极端波动；UNIT 切换未对齐；"
            "COMMODITY 名称不规范（中英文混用）；节假日异常有数据。"
        ),
        scenarios=[
            "通胀压力跟踪（CPI/PPI 前瞻）",
            "资源股/期货持仓研究",
            "美元-商品相关性",
            "地缘事件风险溢价测算",
            "黄金避险属性观察",
            "宏观-商品-行业的联动分析",
        ],
        key_fields=[
            "COMMODITY", "BIZ_DT", "UNIT", "CLOSE_PRC", "CHG_PCT",
        ],
        primary_keys=["COMMODITY", "BIZ_DT"],
        foreign_keys={},
    ),

    "dwd_mkt_derivative": TableProfile(
        table_name="dwd_mkt_derivative",
        domain="market",
        display_name="衍生品行情表",
        purpose=(
            "存储期货、期权、IRS、CDS 等衍生品的逐日行情：合约价、隐含波动率、"
            "Greeks、未平仓量等，支撑套保设计与衍生品估值。"
        ),
        distribution=(
            "DERIV_TYPE 涵盖 FUTURE/OPTION/IRS/CDS/SWAPTION；UNDERLYING 关联现货；"
            "IV 集中在 15%-25%，尾部 40%+ 出现在极端事件期。"
        ),
        trend=(
            "近月合约最活跃，远月合约持仓有限；季月合约切换有滚动；"
            "事件前隐含波动率上行（IV 锥）。"
        ),
        anomaly=(
            "需关注：IV 突破历史 99 分位；OPEN_INTEREST 异常下降（强平）；"
            "Greeks 数值异常（Delta>1）；合约到期日错配。"
        ),
        scenarios=[
            "套保比率与对冲效果评估",
            "波动率交易策略",
            "Greeks 暴露与净额管理",
            "CDS 利差与信用风险",
            "事件驱动的衍生品定价",
            "期货持仓 Open Interest 跟踪",
        ],
        key_fields=[
            "CONTRACT_CD", "BIZ_DT", "DERIV_TYPE", "UNDERLYING",
            "STRIKE", "EXPIRY", "CLOSE_PRC", "IV",
            "DELTA", "GAMMA", "VEGA", "THETA", "OPEN_INTEREST",
        ],
        primary_keys=["CONTRACT_CD", "BIZ_DT"],
        foreign_keys={"UNDERLYING": "dwd_ast_info.AST_CD"},
    ),

    "dwd_mkt_repo": TableProfile(
        table_name="dwd_mkt_repo",
        domain="market",
        display_name="回购利率行情表",
        purpose=(
            "存储银行间与交易所主要回购品种（DR001/DR007/R001/R007/GC001 等）"
            "的成交利率、加权均值、量价信息，是货币市场流动性监控的核心。"
        ),
        distribution=(
            "RATE_CD 涵盖 DR/R/GC 系列；RATE 集中 1.5%-2.5%；"
            "VOL 在 DR/R 系列日均万亿级，月末/税期跳升明显。"
        ),
        trend=(
            "月末/季末/年末 R007 显著上行；央行 OMO 投放可压低利率；"
            "节假日前后流动性紧张；春节前后波动最大。"
        ),
        anomaly=(
            "需关注：RATE 单日 > 50bp 跳跃；HIGH-LOW > 100bp 的剧烈波动；"
            "VOL 暴跌（流动性枯竭）；RATE 与 SHIBOR 同期限差距过大。"
        ),
        scenarios=[
            "组合回购成本测算",
            "流动性紧张预警",
            "OMO 政策效果跟踪",
            "套息策略可行性分析",
            "跨市场利差套利",
            "负 carry 风险评估",
        ],
        key_fields=[
            "RATE_CD", "BIZ_DT", "RATE_VAL", "HIGH", "LOW", "VOL",
        ],
        primary_keys=["RATE_CD", "BIZ_DT"],
        foreign_keys={},
    ),

    "dwd_mkt_abs": TableProfile(
        table_name="dwd_mkt_abs",
        domain="market",
        display_name="ABS 行情表",
        purpose=(
            "存储资产支持证券（ABS/MBS/CLO）的二级市场价格、收益率、"
            "资产池表现（违约率、提前还款率）与覆盖倍数，是 ABS 估值与"
            "信用监控的事实表。"
        ),
        distribution=(
            "ABS_CD 按发起机构分类；DEFAULT_RATE 通常 < 1%（优先级）；"
            "PREPAY_RATE 因房贷/消费贷品类不同，0.05-0.20；"
            "COVERAGE_RATIO 一般 ≥ 1.2。"
        ),
        trend=(
            "房贷 ABS 受利率与房价影响明显；消费 ABS 与失业率相关；"
            "评级下调或资产池恶化时价格快速回调。"
        ),
        anomaly=(
            "需关注：DEFAULT_RATE 季度环比上升 50%+；COVERAGE_RATIO < 1.0；"
            "RATING 急降；POOL_BAL 异常下降（提前清偿）；STATUS=ATTENTION/DEFAULT。"
        ),
        scenarios=[
            "ABS 投资估值与浮亏判断",
            "底层资产池表现追踪",
            "提前还款风险评估",
            "次级档信用风险监控",
            "覆盖率压力测试",
            "ABS 流动性折价分析",
        ],
        key_fields=[
            "ABS_CD", "BIZ_DT", "CLOSE_PRC", "YIELD",
            "POOL_BAL", "DEFAULT_RATE", "PREPAY_RATE",
            "COVERAGE_RATIO", "RATING", "STATUS",
        ],
        primary_keys=["ABS_CD", "BIZ_DT"],
        foreign_keys={"ABS_CD": "dwd_ast_info.AST_CD"},
    ),

    "dwd_mkt_convertible": TableProfile(
        table_name="dwd_mkt_convertible",
        domain="market",
        display_name="可转债行情表",
        purpose=(
            "存储可转债行情：转股价、转股价值、纯债价值、转股溢价率、"
            "纯债溢价率、剩余期限等，支撑可转债定价与套利策略。"
        ),
        distribution=(
            "CONV_PREMIUM 在 0%-50% 不等，越接近转股价值越低；"
            "PURE_BOND_PREMIUM 反映债底支撑；CLOSE_PRC 集中 80-150 元区间。"
        ),
        trend=(
            "正股大涨时转股价值上升、溢价率下降；下修转股价时价格阶跃；"
            "强赎条款触发后批量赎回引发价格回归。"
        ),
        anomaly=(
            "需关注：CONV_PREMIUM 为负的套利机会；CLOSE_PRC > 130 仍未触发强赎；"
            "下修日数据未对齐；剩余期限计算错误。"
        ),
        scenarios=[
            "可转债估值与持仓盯市",
            "转股套利识别",
            "下修与强赎条款监控",
            "可转债 vs 正股相对价值",
            "纯债溢价率作为信用指标",
            "可转债基金的持仓研究",
        ],
        key_fields=[
            "AST_CD", "BIZ_DT", "CLOSE_PRC", "CONV_PRC",
            "CONV_VAL", "PURE_BOND_VAL", "CONV_PREMIUM",
            "PURE_BOND_PREMIUM", "REMAINING_YR",
        ],
        primary_keys=["AST_CD", "BIZ_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    "dwd_mkt_curve_point": TableProfile(
        table_name="dwd_mkt_curve_point",
        domain="market",
        display_name="收益率曲线点表",
        purpose=(
            "存储各类收益率曲线在标准期限点（3M/6M/1Y/.../30Y）的收益率值，"
            "是债券估值、利差计算、久期套利的最底层数据。"
        ),
        distribution=(
            "CURVE_ID 涵盖 CGB/CDB/AAA_MTN/SHIBOR 等；"
            "TENOR 按 3M/6M/1Y/2Y/3Y/5Y/7Y/10Y/15Y/20Y/30Y 等标准点；"
            "YIELD 从短到长递增（牛市/熊市可倒挂）。"
        ),
        trend=(
            "曲线整体平移随政策利率变化；短端受流动性影响敏感、"
            "长端受通胀与基本面预期影响；陡/平峭化体现经济周期阶段。"
        ),
        anomaly=(
            "需关注：相邻期限点收益率倒挂（除非真实倒挂）；"
            "曲线日间跳跃 > 20bp 但无对应事件；TENOR 标准化错误。"
        ),
        scenarios=[
            "债券估值（按曲线插值）",
            "信用利差测算",
            "曲线形态分析（牛平/熊陡）",
            "久期/凸性管理",
            "曲线交易策略（蝴蝶/陡峭）",
            "利率衍生品定价",
        ],
        key_fields=[
            "CURVE_ID", "BIZ_DT", "TENOR", "YIELD", "CHG_BP",
        ],
        primary_keys=["CURVE_ID", "BIZ_DT", "TENOR"],
        foreign_keys={"CURVE_ID": "dwd_mkt_curve_def.CURVE_ID"},
    ),

    "dwd_mkt_curve_def": TableProfile(
        table_name="dwd_mkt_curve_def",
        domain="market",
        display_name="收益率曲线定义表",
        purpose=(
            "维护收益率曲线的元数据：曲线代码、名称、币种、编制机构、计息基准、"
            "使用场景、生效起止日，是 dwd_mkt_curve_point 的主数据。"
        ),
        distribution=(
            "CURVE_ID 数十条；CCY 多为 CNY，少量 USD；ISSUER 涵盖中债、中证、外汇交易中心等；"
            "DAY_COUNT 多为 ACT/365 或 ACT/ACT。"
        ),
        trend=(
            "主数据变化频率低；新发布或编制方法切换时新增/失效；"
            "曲线弃用通常会平滑切换至新曲线。"
        ),
        anomaly=(
            "需关注：CURVE_ID 重复；VALID_TO 早于 VALID_FROM；DAY_COUNT 缺失；"
            "在 dwd_mkt_curve_point 有数据但 def 表缺失的孤立曲线。"
        ),
        scenarios=[
            "曲线选取与币种过滤",
            "自有曲线与官方曲线的对照",
            "曲线生命周期管理",
            "计息基准的统一处理",
            "曲线变更影响评估",
            "曲线主数据治理",
        ],
        key_fields=[
            "CURVE_ID", "CURVE_NM", "CCY", "ISSUER",
            "DAY_COUNT", "USE_SCENARIO", "VALID_FROM", "VALID_TO", "STATUS",
        ],
        primary_keys=["CURVE_ID"],
        foreign_keys={},
    ),

    "dwd_mkt_benchmark": TableProfile(
        table_name="dwd_mkt_benchmark",
        domain="market",
        display_name="基准利率表",
        purpose=(
            "存储用于浮息债定价、衍生品基准、组合业绩比较的基准利率序列："
            "LPR、MLF、SOFR、TONA、SHIBOR_3M 等，是定价与基准管理的核心源。"
        ),
        distribution=(
            "BENCHMARK_CD 涵盖境内外多种基准；TENOR 多样；"
            "VAL 集中在主流利率区间；MAJOR_CCY 以 CNY/USD 为主。"
        ),
        trend=(
            "LPR 月度报价、SOFR 每日发布、SHIBOR 每日 9:30 公布；"
            "基准切换（LIBOR→SOFR）期间出现新旧并行。"
        ),
        anomaly=(
            "需关注：基准已废止仍在使用；同一日多源差异 > 1bp；VAL 缺失；"
            "TENOR 标记错误。"
        ),
        scenarios=[
            "浮息债定价",
            "基准切换影响评估（IBOR Reform）",
            "组合业绩基准选择",
            "跨币种基准比对",
            "挂钩衍生品估值",
            "基准合规性核查",
        ],
        key_fields=[
            "BENCHMARK_CD", "BIZ_DT", "TENOR", "VAL", "CCY", "SOURCE",
        ],
        primary_keys=["BENCHMARK_CD", "BIZ_DT", "TENOR"],
        foreign_keys={},
    ),

    "dwd_mkt_vol_surface": TableProfile(
        table_name="dwd_mkt_vol_surface",
        domain="market",
        display_name="波动率曲面表",
        purpose=(
            "存储期权隐含波动率在不同执行价/到期日的二维曲面：UNDERLYING/EXPIRY/STRIKE"
            "对应的 IV 与 Delta，是期权定价、波动率交易与风险管理的输入。"
        ),
        distribution=(
            "UNDERLYING 集中在主流 ETF/股指/外汇；STRIKE 围绕 ATM 上下展开；"
            "IV 通常 15%-30%，深度虚值/实值出现尖峰；Delta 在 0.05-0.95 间。"
        ),
        trend=(
            "事件前 ATM IV 上行（IV 锥）；事件后回落；"
            "长期看 Skew/Smile 形态稳定，但极端事件会改变形态。"
        ),
        anomaly=(
            "需关注：IV 在某 STRIKE 跳点；曲面无套利违反（蝶式负值）；"
            "DELTA 与 STRIKE 关系反转；EXPIRY 顺序错乱。"
        ),
        scenarios=[
            "期权定价与希腊字母计算",
            "波动率套利策略（Skew Trade）",
            "事件驱动的 IV 变化研究",
            "风险敞口与对冲组合构建",
            "曲面平滑与无套利校准",
            "隐含波动率指数构造",
        ],
        key_fields=[
            "UNDERLYING", "BIZ_DT", "EXPIRY", "STRIKE",
            "CALL_IV", "PUT_IV", "DELTA",
        ],
        primary_keys=["UNDERLYING", "BIZ_DT", "EXPIRY", "STRIKE"],
        foreign_keys={"UNDERLYING": "dwd_ast_info.AST_CD"},
    ),

    "dwd_mkt_liquidity": TableProfile(
        table_name="dwd_mkt_liquidity",
        domain="market",
        display_name="流动性指标表",
        purpose=(
            "汇集 R007/DR007/SHIBOR 利差、回购成交量、北向资金、ETF 申赎、"
            "融资融券余额等流动性度量指标，是市场流动性状态的综合视图。"
        ),
        distribution=(
            "INDICATOR 涵盖资金面/股市流动性/北向流入等多维度；"
            "VAL 单位差异大（点位/亿元/%），需以指标分别理解。"
        ),
        trend=(
            "月末/季末/税期/春节前流动性紧张；"
            "重大事件期间北向流出；融资余额随牛熊周期波动。"
        ),
        anomaly=(
            "需关注：单一指标偏离 30 日均值 ±2 倍标准差；"
            "多个流动性指标同向极端值（系统性紧张）；指标缺失或单位错误。"
        ),
        scenarios=[
            "流动性预警与应急预案",
            "组合现金管理决策",
            "市场情绪与资金面联动",
            "北向资金跟随策略",
            "融资融券风险监控",
            "宏观流动性传导研究",
        ],
        key_fields=[
            "INDICATOR", "BIZ_DT", "VAL", "CHG", "UNIT", "MARKET",
        ],
        primary_keys=["INDICATOR", "BIZ_DT"],
        foreign_keys={},
    ),

    "dwd_mkt_credit_spread": TableProfile(
        table_name="dwd_mkt_credit_spread",
        domain="market",
        display_name="信用利差表",
        purpose=(
            "存储不同评级、期限的信用利差（相对国债/国开基准），"
            "是信用研究、相对价值分析与信用 ETF 估值的关键。"
        ),
        distribution=(
            "RATING 涵盖 AAA/AA+/AA/AA-/A+ 等；TENOR 1Y/3Y/5Y 为主；"
            "SPREAD 按评级递增（AAA 30-50bp、AA 80-150bp、AA- 130bp+）。"
        ),
        trend=(
            "经济下行/信用事件期间利差走阔；流动性宽松期间利差压缩；"
            "行业风险（地产/城投）会带动相关评级利差异常。"
        ),
        anomaly=(
            "需关注：单日利差跳跃 > 20bp 无对应事件；不同评级利差倒挂；"
            "BENCHMARK 不一致；TENOR 期限点缺失。"
        ),
        scenarios=[
            "信用债估值与利差比较",
            "评级间相对价值分析",
            "信用周期判断（紧/松）",
            "信用 ETF 申赎决策",
            "信用风险溢价研究",
            "信用-利率因子分解",
        ],
        key_fields=[
            "RATING", "TENOR", "BIZ_DT", "SPREAD", "CHG_BP", "BENCHMARK",
        ],
        primary_keys=["RATING", "TENOR", "BIZ_DT"],
        foreign_keys={},
    ),

    "dwd_mkt_sector_index": TableProfile(
        table_name="dwd_mkt_sector_index",
        domain="market",
        display_name="行业指数表",
        purpose=(
            "存储中信/申万/Wind 等行业分类下的行业指数日频行情，"
            "用于行业轮动、风格归因与板块联动研究。"
        ),
        distribution=(
            "SECTOR_CD 涵盖 28-30 个一级行业；INDEX_FAMILY 中信/申万/Wind 三大体系；"
            "CHG_PCT 大多 ±3%，板块行情期可达 ±8%。"
        ),
        trend=(
            "政策窗口、财报季、基本面拐点附近板块轮动加快；"
            "成长/价值风格周期切换；行业指数编制方法改版有阶跃。"
        ),
        anomaly=(
            "需关注：成分股调整未平滑；不同体系同名行业差异 > 2%；"
            "CHG_PCT 超 ±10% 需核查；节假日异常有数据。"
        ),
        scenarios=[
            "行业轮动策略与时点判断",
            "风格归因（行业贡献）",
            "行业 ETF 投资决策",
            "上下游产业链联动",
            "板块比较与领涨/领跌识别",
            "行业 Beta/Alpha 分解",
        ],
        key_fields=[
            "SECTOR_CD", "BIZ_DT", "INDEX_FAMILY", "CLOSE_VAL",
            "CHG_PCT", "VOL", "AMT",
        ],
        primary_keys=["SECTOR_CD", "INDEX_FAMILY", "BIZ_DT"],
        foreign_keys={},
    ),

    "dwd_mkt_macro": TableProfile(
        table_name="dwd_mkt_macro",
        domain="market",
        display_name="宏观经济指标表",
        purpose=(
            "存储 GDP、CPI、PPI、PMI、M2、社融、进出口等宏观经济与货币金融指标，"
            "是宏观策略、利率走势研判与大类资产配置的输入数据。"
        ),
        distribution=(
            "INDICATOR 数十种；RPT_PERIOD 月度/季度为主，少量年度；"
            "VALUE 单位多样（%/亿元/点）；SOURCE 多为国家统计局/央行/海关总署。"
        ),
        trend=(
            "按既定披露窗口更新（CPI 月中、PMI 月初、GDP 季初）；"
            "经济周期阶段决定指标走向；政策调整后传导至经济数据有 1-2 季度滞后。"
        ),
        anomaly=(
            "需关注：YoY/MoM 与 VALUE 计算不一致；RPT_DT 早于 RPT_PERIOD；"
            "修订值未追溯；SOURCE 缺失或非官方源；指标定义变更未标记。"
        ),
        scenarios=[
            "宏观策略与大类资产配置",
            "利率走廊判断",
            "通胀压力与货币政策预期",
            "信用扩张周期识别",
            "出口/外需驱动行业研究",
            "经济衰退/复苏拐点识别",
        ],
        key_fields=[
            "INDICATOR", "RPT_DT", "RPT_PERIOD", "VALUE",
            "UNIT", "YOY", "MOM", "SOURCE",
        ],
        primary_keys=["INDICATOR", "RPT_DT"],
        foreign_keys={},
    ),

    "dwd_mkt_calendar": TableProfile(
        table_name="dwd_mkt_calendar",
        domain="market",
        display_name="交易日历表",
        purpose=(
            "维护各市场（银行间/上交所/深交所/港交所等）的交易日 vs 非交易日标识，"
            "是回测、清算、估值与日期推算的基础日历表。"
        ),
        distribution=(
            "CAL_DT 连续覆盖未来与历史；MARKET 多市场并行；"
            "IS_TRADE 通常 Y/N；WEEK_DAY 0-6；节假日批量出现连续 N。"
        ),
        trend=(
            "每年初批量更新次年日历；春节前后/十一长假/元旦集中非交易日；"
            "调休补班需特别处理。"
        ),
        anomaly=(
            "需关注：MARKET 不同但日期共用导致的口径混淆；"
            "WEEK_DAY 计算错误；调休日未标记；同日重复行。"
        ),
        scenarios=[
            "回测日期对齐",
            "T+N 推算与结算日确定",
            "日频估值跳点处理",
            "节假日前的资金安排",
            "跨市场日期匹配",
            "交易日历变更通知",
        ],
        key_fields=[
            "CAL_DT", "MARKET", "IS_TRADE", "WEEK_DAY", "WEEK_DAY_NM",
        ],
        primary_keys=["CAL_DT", "MARKET"],
        foreign_keys={},
    ),

    "dwd_mkt_holiday": TableProfile(
        table_name="dwd_mkt_holiday",
        domain="market",
        display_name="节假日表",
        purpose=(
            "明细记录公历/法定节假日及调休安排：节日名称、起止日期、调休补班日，"
            "是日历表的补充语义信息源。"
        ),
        distribution=(
            "HOLIDAY_NM 涵盖元旦/春节/清明/劳动/端午/中秋/国庆等；"
            "COUNTRY/MARKET 区分境内外；DURATION_DAYS 春节/十一最长。"
        ),
        trend=(
            "年度初一次性发布次年节假日；调休安排官方公布后固定不变；"
            "特殊年份（疫情/重大活动）会有临时调整。"
        ),
        anomaly=(
            "需关注：HOLIDAY_DT 跨年错误；调休补班日缺失；"
            "COUNTRY/MARKET 不一致；连续日期断裂。"
        ),
        scenarios=[
            "节假日前后流动性预测",
            "清算/结算日推算",
            "跨市场（A 股 vs 港股）休市差异处理",
            "节日效应（季节性收益）研究",
            "运营人力排班",
            "调休补班的特别处理",
        ],
        key_fields=[
            "HOLIDAY_DT", "HOLIDAY_NM", "COUNTRY", "MARKET",
            "START_DT", "END_DT", "DURATION_DAYS", "IS_MAKEUP",
        ],
        primary_keys=["HOLIDAY_DT", "MARKET"],
        foreign_keys={},
    ),

    "dwd_mkt_exchange_info": TableProfile(
        table_name="dwd_mkt_exchange_info",
        domain="market",
        display_name="交易所信息表",
        purpose=(
            "维护交易所的基础信息：代码、全称、所在国家/地区、交易时段、"
            "币种、监管机构与状态，是跨市场业务的主数据。"
        ),
        distribution=(
            "EXCHANGE_CD 涵盖 SSE/SZSE/CFETS/SHFE/HKEX/NYSE/NASDAQ 等；"
            "COUNTRY 多元；TRADE_SESSION 时区差异大。"
        ),
        trend=(
            "主数据变化稀少；新交易所设立或并购时新增；"
            "交易时段调整偶发（夏令/冬令时切换）。"
        ),
        anomaly=(
            "需关注：EXCHANGE_CD 重复或别名混用；TRADE_SESSION 无效格式；"
            "STATUS=CLOSED 但仍有数据；时区缺失。"
        ),
        scenarios=[
            "跨市场资产路由",
            "交易时段合规校验",
            "夏令/冬令时切换处理",
            "币种与清算行匹配",
            "监管报送的交易所代码映射",
            "全球资产配置主数据",
        ],
        key_fields=[
            "EXCHANGE_CD", "EXCHANGE_NM", "COUNTRY", "REGION",
            "TRADE_SESSION", "CCY", "REGULATOR", "TIMEZONE", "STATUS",
        ],
        primary_keys=["EXCHANGE_CD"],
        foreign_keys={},
    ),

    "dwd_mkt_trading_halt": TableProfile(
        table_name="dwd_mkt_trading_halt",
        domain="market",
        display_name="停牌信息表",
        purpose=(
            "记录股票/基金/债券的停牌事件：停牌日期、复牌日期、停牌原因、停牌类型，"
            "是估值切换、组合流动性管理与风险预警的事实表。"
        ),
        distribution=(
            "HALT_REASON 中重大资产重组、年报披露、信息核查等占大头；"
            "HALT_TYPE 涵盖临停/停牌核查/长期停牌；"
            "绝大多数停牌时间 1 个交易日内，少数延伸至月级。"
        ),
        trend=(
            "年报披露季临停集中；监管严查期非定期停牌增多；"
            "重大并购公告前后是停牌高峰。"
        ),
        anomaly=(
            "需关注：长期停牌（>30 个交易日）需采用特别估值方法；"
            "RESUME_DT 早于 HALT_DT；同一标的频繁停复牌；"
            "HALT_REASON 缺失或描述含糊。"
        ),
        scenarios=[
            "停牌股估值切换（如指数收益法）",
            "组合流动性影响测算",
            "重大事项前的内幕交易识别",
            "复牌后的价格冲击分析",
            "长期停牌资产的特别处理",
            "信息披露合规核查",
        ],
        key_fields=[
            "AST_CD", "HALT_DT", "RESUME_DT", "HALT_TYPE",
            "HALT_REASON", "EXCHANGE_CD", "STATUS",
        ],
        primary_keys=["AST_CD", "HALT_DT"],
        foreign_keys={"AST_CD": "dwd_ast_info.AST_CD"},
    ),

    "dwd_mkt_ipo_calendar": TableProfile(
        table_name="dwd_mkt_ipo_calendar",
        domain="market",
        display_name="新股 IPO 日历表",
        purpose=(
            "记录 IPO 与债券一级发行的关键日期：申购日、缴款日、上市日、发行价、"
            "中签率与发行规模，是新股研究、打新策略与一级承销研究的核心。"
        ),
        distribution=(
            "IPO_TYPE 中股票主板/创业板/科创板/北交所，债券国债/政金债/信用债等；"
            "中签率股票通常 0.01%-0.5%，债券国债中标倍数 2-4 倍；"
            "发行规模差异巨大（小盘股几亿到大盘股几百亿）。"
        ),
        trend=(
            "按月度发行节奏；季末/年末发行集中；"
            "市场低迷时 IPO 暂停（A 股历史多次）；高景气期发行加速。"
        ),
        anomaly=(
            "需关注：LISTING_DT 早于 ISSUE_DT 的逻辑错误；"
            "中签率 > 100% 或为负；ISSUE_PRC 与询价区间偏离；"
            "BID_MULTIPLE 异常低（<1，发行失败）。"
        ),
        scenarios=[
            "打新策略与中签预测",
            "新股上市首日表现研究",
            "一级承销机构表现",
            "发行节奏与市场容量评估",
            "询价合理性分析",
            "债券一级招标利差",
        ],
        key_fields=[
            "IPO_CD", "IPO_NM", "IPO_TYPE", "ISR_NM",
            "SUBSCRIBE_DT", "PAYMENT_DT", "LISTING_DT",
            "ISSUE_PRC", "ISSUE_AMT", "WIN_RATE", "BID_MULTIPLE", "STATUS",
        ],
        primary_keys=["IPO_CD"],
        foreign_keys={},
    ),

    "dwd_mkt_rating_action": TableProfile(
        table_name="dwd_mkt_rating_action",
        domain="market",
        display_name="评级动作表",
        purpose=(
            "记录评级机构对发行人/债项的评级动作：上调、下调、展望调整、列入观察，"
            "是信用研究、组合信用风险监控与持仓预警的事实表。"
        ),
        distribution=(
            "AGENCY 涵盖中诚信/联合资信/大公/东方金诚/穆迪/惠誉/标普；"
            "CHANGE_TYPE 中 OUTLOOK_CHG 最频繁，UPGRADE/DOWNGRADE 集中在年报后；"
            "信用周期下行阶段 DOWNGRADE 占比上升。"
        ),
        trend=(
            "年报披露后 1-2 月评级动作密集；"
            "行业出清期（地产/城投）DOWNGRADE 集中；"
            "经济复苏期 UPGRADE 增多。"
        ),
        anomaly=(
            "需关注：跨级跳调（AA→BBB）的极端动作；不同机构对同一主体评级偏离 > 2 档；"
            "REASON 描述空白；CHANGE_DT 与官方公告日不一致；"
            "IMPACT_ASSETS/IMPACT_PORTS 关联缺失。"
        ),
        scenarios=[
            "持仓发行人评级变动监控",
            "评级动作驱动的预警与减持",
            "行业评级周期判断",
            "机构评级一致性检查",
            "评级展望与正式调整的领先关系",
            "信用研究素材积累",
        ],
        key_fields=[
            "ACTION_ID", "ISR_ID", "ISR_NM", "AGENCY",
            "PREV_RATING", "NEW_RATING", "CHANGE_TYPE",
            "CHANGE_DT", "REASON", "IMPACT_ASSETS", "IMPACT_PORTS",
        ],
        primary_keys=["ACTION_ID"],
        foreign_keys={
            "ISR_ID": "dwd_ast_isr_info.ISR_ID",
        },
    ),
}
