"""
产品域(Product Domain) - L1 单表画像定义
覆盖 dwd_ptl_* 共 12 张表，主键以 PORT_ID（产品/组合 ID）为锚点。
画像内容依据 mongo-seed/03_product_domain.js 的 Schema 与业务语义编写。
"""
from ..models import DomainOverview, TableProfile, FieldProfile

# ====================== 域概览 ======================
DOMAIN_OVERVIEW = DomainOverview(
    domain_code="product",
    domain_name="产品域",
    description=(
        "以组合 ID（PORT_ID）为锚点，覆盖资管产品/基金的基础信息、持仓、"
        "净值历史、收益率、风险指标、基准、费率、投资者结构、投资限制、"
        "交易汇总、业绩归因、合规检查 12 个维度，是组合管理与监督的核心域。"
    ),
    table_count=12,
    tables=[
        "dwd_ptl_info",
        "dwd_ptl_holding",
        "dwd_ptl_nav_hist",
        "dwd_ptl_return",
        "dwd_ptl_risk_indicator",
        "dwd_ptl_benchmark",
        "dwd_ptl_fee",
        "dwd_ptl_investor",
        "dwd_ptl_limit",
        "dwd_ptl_transaction_summary",
        "dwd_ptl_attribution",
        "dwd_ptl_compliance",
    ],
    core_scenarios=[
        "组合净值与收益率监控",
        "持仓结构与集中度分析",
        "风险指标（波动率/回撤/夏普/跟踪误差）评估",
        "投资限制与合规检查",
        "业绩归因（择时/选券/交易）",
        "投资者结构（机构/个人/前十大）跟踪",
        "费率合规与计提核算",
    ],
    key_entities=["PORT_ID", "AST_CD", "BIZ_DT", "BENCHMARK"],
)


# ====================== L1 单表画像 ======================
TABLE_PROFILES: dict[str, TableProfile] = {
    # 1. 产品基础信息
    "dwd_ptl_info": TableProfile(
        table_name="dwd_ptl_info",
        domain="product",
        display_name="产品基础信息表",
        purpose=(
            "登记每个资管产品/基金的标识（PORT_ID/PORT_NM）、产品类型、风险等级、"
            "成立日期、币种、业绩比较基准、最新份额净值/累计净值、AUM、总份额、"
            "管理人、托管行、状态及投资范围（INV_SCOPE），是产品主数据表。"
        ),
        distribution=(
            "PORT_TYPE 覆盖 MMF/BOND/MIXED/INDEX/FOF 等类别；RISK_LVL 分布于 R1~R4；"
            "AUM 量级跨度大（亿到百亿）；MMF 类 SHR_NAV 恒为 1.0000；"
            "管理人/托管行集中在头部银行（如工行、招行）。"
        ),
        trend=(
            "新增产品节奏与监管批文/市场行情相关；AUM 随申赎波动；"
            "净值随持仓估值日频变化；产品类型分布近年向被动指数与 FOF 倾斜。"
        ),
        anomaly=(
            "应关注：1) AUM 与 SHR_NAV * TOTAL_SHARE 偏差 > 1%（核算异常）；"
            "2) RISK_LVL 与 PORT_TYPE 不匹配（如 MMF 为 R4）；"
            "3) STATUS 非 ACTIVE 但仍有持仓和申赎；4) MGR_INST/CUSTODY_BANK 与主体表不一致。"
        ),
        scenarios=[
            "产品列表与基础信息查询",
            "组合按类型/风险等级聚合统计",
            "AUM 排名与同类对比",
            "管理人/托管行业务集中度",
            "新发与清盘产品全生命周期管理",
        ],
        key_fields=[
            "PORT_ID", "PORT_NM", "PORT_TYPE", "RISK_LVL", "ESTAB_DT", "CCY",
            "BENCHMARK", "SHR_NAV", "ACC_NAV", "AUM", "TOTAL_SHARE",
            "MGR_INST", "CUSTODY_BANK", "STATUS", "INV_SCOPE",
        ],
        primary_keys=["PORT_ID"],
        foreign_keys={
            "MGR_INST": "dwd_isr_institution.ISR_ID",
            "CUSTODY_BANK": "dwd_isr_institution.ISR_ID",
        },
        field_profiles=[
            FieldProfile(
                field_name="PORT_ID",
                display_name="产品/组合ID",
                data_type="string",
                definition="资管产品或投资组合的唯一标识",
                example_values=["PORT_001", "PORT_MMF_01", "PORT_BOND_03"],
                is_primary_key=True,
                association_chains=[
                    "PORT_ID → dwd_ptl_holding.PORT_ID → dwd_ast_info.AST_CD",
                    "PORT_ID → dwd_ptl_nav_hist.PORT_ID",
                    "PORT_ID → dwd_ptl_risk_indicator.PORT_ID",
                ],
                tags=["主键", "检索键"],
            ),
            FieldProfile(
                field_name="PORT_NM",
                display_name="产品名称",
                data_type="string",
                definition="资管产品的官方中文名称",
                example_values=["稳健增长1号", "现金宝货币A", "债券精选增强"],
                tags=["检索键", "维度"],
            ),
            FieldProfile(
                field_name="PORT_TYPE",
                display_name="产品类型",
                data_type="enum",
                definition="产品的投资类型分类",
                example_values=["MMF", "BOND", "MIXED", "INDEX", "FOF"],
                enum_values={"MMF": "货币市场基金", "BOND": "债券型", "MIXED": "混合型", "INDEX": "指数型", "FOF": "FOF"},
                tags=["维度", "检索键"],
            ),
            FieldProfile(
                field_name="AUM",
                display_name="资产管理规模",
                data_type="number",
                definition="产品当前管理的总资产规模",
                example_values=["1500000000", "50000000000"],
                unit="元",
                tags=["度量", "排序键"],
            ),
            FieldProfile(
                field_name="BENCHMARK",
                display_name="业绩比较基准",
                data_type="string",
                definition="产品的业绩比较基准描述",
                example_values=["中债综合财富指数", "七天通知存款利率*90%+沪深300*10%"],
                tags=["维度"],
            ),
            FieldProfile(
                field_name="STATUS",
                display_name="产品状态",
                data_type="enum",
                definition="产品当前运作状态",
                example_values=["ACTIVE", "CLOSED", "LIQUIDATING"],
                enum_values={"ACTIVE": "正常运作", "CLOSED": "已终止", "LIQUIDATING": "清算中"},
                tags=["维度"],
            ),
            FieldProfile(
                field_name="MGR_INST",
                display_name="管理人",
                data_type="string",
                definition="产品管理机构的标识ID",
                example_values=["ISR_ICBC_AM", "ISR_CMB_WM"],
                is_foreign_key=True,
                references="dwd_isr_institution.ISR_ID",
                tags=["外键", "维度"],
            ),
            FieldProfile(
                field_name="ESTAB_DT",
                display_name="成立日期",
                data_type="date",
                definition="产品成立并开始运作的日期",
                example_values=["2020-05-15", "2022-11-01"],
                is_time_series=True,
                tags=["排序键"],
            ),
            FieldProfile(
                field_name="RISK_LVL",
                display_name="风险等级",
                data_type="enum",
                definition="产品风险等级分类",
                example_values=["R1", "R2", "R3", "R4"],
                enum_values={"R1": "低风险", "R2": "中低风险", "R3": "中风险", "R4": "中高风险", "R5": "高风险"},
                tags=["维度"],
            ),
            FieldProfile(
                field_name="SHR_NAV",
                display_name="份额净值",
                data_type="number",
                definition="产品最新单位份额净值",
                example_values=["1.0000", "1.0523", "0.9876"],
                unit="元",
                tags=["度量"],
            ),
        ],
    ),

    # 2. 持仓明细
    "dwd_ptl_holding": TableProfile(
        table_name="dwd_ptl_holding",
        domain="product",
        display_name="组合持仓明细表",
        purpose=(
            "记录每个组合每日持有的资产明细（持仓量/市值/成本/比例/应计利息/浮盈亏），"
            "是组合估值、风险计量、归因分析、合规检查的最底层事实表。"
        ),
        distribution=(
            "每个组合通常持有 5~50 只资产；HOLD_RATIO 头部资产集中度 10%~30%；"
            "BOND 组合持仓全部为债券，MIXED 组合中债券占比 60%~80%、股票/ETF 20%~40%；"
            "INDEX 类组合 ETF/成份股权重高度集中。"
        ),
        trend=(
            "BIZ_DT 日频快照；持仓结构随调仓与申赎渐变，"
            "月末/季末因合规/披露需要常出现集中调仓窗口。"
        ),
        anomaly=(
            "应关注：1) HOLD_RATIO 之和偏离 1.0；2) HOLD_MV 与 dwd_val_asset_detail.MKT_VAL 不一致；"
            "3) FLOAT_PL 异常（如成本为 0 导致比例失真）；"
            "4) 持仓资产 AST_CD 在 dwd_ast_info 中缺失；5) MMF 出现非货币市场资产。"
        ),
        scenarios=[
            "组合持仓结构展示",
            "单一资产/单一发行人集中度合规",
            "组合行业/久期/信用分布映射",
            "持仓变动与调仓节奏分析",
            "组合间持仓重叠度（FOF/相关性）",
        ],
        key_fields=[
            "PORT_ID", "AST_CD", "AST_NM", "BIZ_DT",
            "HOLD_AMT", "HOLD_MV", "HOLD_COST", "HOLD_RATIO",
            "ACCRUED_INT", "FLOAT_PL",
        ],
        primary_keys=["PORT_ID", "AST_CD", "BIZ_DT"],
        foreign_keys={
            "PORT_ID": "dwd_ptl_info.PORT_ID",
            "AST_CD": "dwd_ast_info.AST_CD",
        },
    ),

    # 3. 净值历史
    "dwd_ptl_nav_hist": TableProfile(
        table_name="dwd_ptl_nav_hist",
        domain="product",
        display_name="组合净值历史表",
        purpose=(
            "存储每个组合的逐日份额净值（SHR_NAV）、累计净值（ACC_NAV）、"
            "日收益率（DAILY_RET）及净值确认状态（NAV_STATUS），"
            "是产品净值发布、客户对账与历史业绩计算的核心源表。"
        ),
        distribution=(
            "MMF 组合 SHR_NAV 恒为 1.0000、累计净值递增；"
            "其他组合 SHR_NAV 在 0.95~1.20 区间；DAILY_RET 量级 ±2bp ~ ±150bp；"
            "NAV_STATUS 大多为 CONFIRMED，少量 PUBLISHED/PENDING。"
        ),
        trend=(
            "工作日日频更新；股票型/混合型组合受市场波动较大，"
            "纯债型与货币型平稳；分红日累计净值与单位净值产生跳跃。"
        ),
        anomaly=(
            "应关注：1) DAILY_RET 与 ACC_NAV 变动率不一致；2) MMF SHR_NAV 偏离 1.0000；"
            "3) NAV_STATUS 长期为 PENDING；4) 缺失工作日数据；"
            "5) 净值跳变 > 10%（疑似分红/折算需复核）。"
        ),
        scenarios=[
            "客户净值披露与对账",
            "区间收益率与最大回撤计算",
            "净值与基准走势叠加",
            "净值精度与确认状态合规检查",
            "分红/折算事件溯源",
        ],
        key_fields=["PORT_ID", "BIZ_DT", "SHR_NAV", "ACC_NAV", "DAILY_RET", "NAV_STATUS"],
        primary_keys=["PORT_ID", "BIZ_DT"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 4. 收益率
    "dwd_ptl_return": TableProfile(
        table_name="dwd_ptl_return",
        domain="product",
        display_name="组合收益率表",
        purpose=(
            "提供每个组合的日/周/月/年初至今多周期收益率（DAILY_RET/WEEKLY_RET/MTD_RET/YTD_RET）"
            "及基准收益率、超额收益（EXCESS_RET），"
            "支撑业绩展示、超额能力评估与组合对比。"
        ),
        distribution=(
            "BOND 组合 DAILY_RET 集中于 ±10bp；MIXED/INDEX 组合 ±100bp 量级；"
            "MMF 组合 DAILY_RET 极小（< 5bp）；EXCESS_RET 通常为 DAILY_RET 的 10%~20%。"
        ),
        trend=(
            "日频统计；YTD_RET 随时间推移单调累积（叠加正负贡献），"
            "MTD_RET 在月末归零重置；股市/债市行情切换时超额方向反转。"
        ),
        anomaly=(
            "应关注：1) DAILY_RET 与 dwd_ptl_nav_hist 不一致；"
            "2) EXCESS_RET 与 (DAILY_RET - BENCH_DAILY_RET) 偏差大；"
            "3) YTD_RET 跳变（疑似口径切换）；4) 业绩归因合计与总收益不闭环。"
        ),
        scenarios=[
            "组合业绩多周期展示",
            "超额收益（Alpha）能力评估",
            "组合排名与同类比较",
            "收益归因数据校验",
            "客户业绩报告生成",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT",
            "DAILY_RET", "WEEKLY_RET", "MTD_RET", "YTD_RET",
            "BENCH_DAILY_RET", "EXCESS_RET",
        ],
        primary_keys=["PORT_ID", "BIZ_DT"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 5. 风险指标
    "dwd_ptl_risk_indicator": TableProfile(
        table_name="dwd_ptl_risk_indicator",
        domain="product",
        display_name="组合风险指标表",
        purpose=(
            "存储每个组合的滚动波动率（VOL）、最大回撤（MAX_DRAWDOWN）、夏普比率"
            "（SHARPE）、跟踪误差（TRACKING_ERROR）、信息比率（INFO_RATIO）、"
            "Beta、VaR(95%)、卡玛比率等风险/风险调整后绩效指标。"
        ),
        distribution=(
            "MMF 组合 VOL/MAX_DRAWDOWN 极小、SHARPE 较高（> 3）；"
            "BOND 组合 VOL ~2%、回撤温和；MIXED/INDEX 组合 VOL > 15%、回撤可达 -18%；"
            "Beta 取值随股票仓位线性增加。"
        ),
        trend=(
            "通常基于 1Y 回望期，每日滚动重算；"
            "市场剧烈波动期 VOL/回撤 短期内显著抬升、SHARPE 下降。"
        ),
        anomaly=(
            "应关注：1) MAX_DRAWDOWN 持续刷新极值；2) TRACKING_ERROR 突破 LIMIT_VALUE；"
            "3) Beta 与组合类型严重不符（如 MMF Beta > 0.05）；"
            "4) SHARPE 异常（无风险利率口径错误）；5) OBS_PERIOD 缺失或不一致。"
        ),
        scenarios=[
            "组合风险预算与限额监控",
            "风险调整后绩效评估",
            "市场压力期风险敞口扫描",
            "跟踪误差合规检查（被动产品）",
            "VaR/CVaR 与监管报送",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "VOL", "MAX_DRAWDOWN", "SHARPE",
            "TRACKING_ERROR", "INFO_RATIO", "BETA", "VAR_95", "CALMAR",
            "RISK_FREE_RATE", "OBS_PERIOD",
        ],
        primary_keys=["PORT_ID", "BIZ_DT"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 6. 基准信息
    "dwd_ptl_benchmark": TableProfile(
        table_name="dwd_ptl_benchmark",
        domain="product",
        display_name="组合基准信息表",
        purpose=(
            "登记每个组合的业绩比较基准定义（BENCHMARK_NM）、组成成分（COMPONENTS："
            "代码/名称/权重）以及基准的日/年初至今/1 年收益率，"
            "支撑超额收益计算、归因分析与基准合规审查。"
        ),
        distribution=(
            "BOND 类基准多采用‘中债综合财富指数’、MMF 多采用‘七天通知存款利率’、"
            "INDEX 类基准为‘沪深300*95% + 现金*5%’；"
            "COMPONENTS 权重合计为 1.0。"
        ),
        trend=(
            "基准定义通常稳定，每年/每季度评估一次是否需要调整；"
            "成分权重变更需经董事会/合规审议。"
        ),
        anomaly=(
            "应关注：1) COMPONENTS WGT 合计 ≠ 1.0；2) BENCHMARK_NM 与持仓特征严重不符；"
            "3) BENCH_DAILY_RET 与底层指数收益率不一致；"
            "4) BENCH_1Y_RET 缺失或冻结时间过长。"
        ),
        scenarios=[
            "超额收益与跟踪误差计算",
            "基准合理性审查（与组合定位匹配）",
            "组合相对市场表现展示",
            "归因分析的基准侧锚定",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "BENCHMARK_NM", "COMPONENTS",
            "BENCH_DAILY_RET", "BENCH_YTD_RET", "BENCH_1Y_RET",
        ],
        primary_keys=["PORT_ID", "BIZ_DT"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 7. 费率信息
    "dwd_ptl_fee": TableProfile(
        table_name="dwd_ptl_fee",
        domain="product",
        display_name="组合费率信息表",
        purpose=(
            "登记每个组合的管理费、托管费、申购费、赎回费、销售服务费、业绩报酬"
            "（PERF_FEE_RATE/PERF_FEE_BENCHMARK）等费率结构与生效日，"
            "用于费用计提核对、客户费率信息披露与产品成本对比。"
        ),
        distribution=(
            "MGT_FEE_RATE 集中在 0.30%~1.50%（MMF 最低、MIXED 最高）；"
            "CUSTODY_FEE_RATE 0.08%~0.25%；纯债与 MMF 通常无业绩报酬；"
            "MIXED/INDEX 增强类产品 PERF_FEE_RATE 多为 10%~20%。"
        ),
        trend=(
            "费率变更触发主要是产品合同修订；近年监管引导整体管理费率呈下行趋势；"
            "新发被动产品费率普遍较老产品低。"
        ),
        anomaly=(
            "应关注：1) FEE_CURRENCY 与产品 CCY 不一致；"
            "2) 业绩报酬基准描述与计算方式不匹配；3) EFF_DT 早于产品 ESTAB_DT；"
            "4) 管理费/托管费总和明显偏离同业中枢。"
        ),
        scenarios=[
            "费率合规披露与客户告知",
            "费用计提核算（与估值费用明细对账）",
            "同类产品费率竞争力分析",
            "业绩报酬触发条件管理",
        ],
        key_fields=[
            "PORT_ID", "EFF_DT",
            "MGT_FEE_RATE", "CUSTODY_FEE_RATE", "SUB_FEE_RATE", "RDM_FEE_RATE",
            "SALES_FEE_RATE", "PERF_FEE_RATE", "PERF_FEE_BENCHMARK", "FEE_CURRENCY",
        ],
        primary_keys=["PORT_ID", "EFF_DT"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 8. 投资者结构
    "dwd_ptl_investor": TableProfile(
        table_name="dwd_ptl_investor",
        domain="product",
        display_name="组合投资者结构表",
        purpose=(
            "按投资者类型（INSTITUTION/INDIVIDUAL）分组统计持有人数（HOLDER_CNT）、"
            "持有份额、持有金额、占比及前十大集中度（TOP10_RATIO），"
            "用于产品销售结构分析、流动性风险与大额赎回压力评估。"
        ),
        distribution=(
            "BOND/MMF 类机构占比偏高（60%~80%），MIXED 类个人占比更高；"
            "TOP10_RATIO 跨度大（30%~70%）；机构持有人数远少于个人，但单位持仓金额高。"
        ),
        trend=(
            "通常按月或按季度披露；机构占比受银行理财、保险委外节奏影响；"
            "明星基金或新发热销产品的个人占比阶段性走高。"
        ),
        anomaly=(
            "应关注：1) HOLD_RATIO 机构 + 个人合计 ≠ 1.0；"
            "2) TOP10_RATIO > 0.50 触发集中度风险；3) 持有人数 0 但有持仓金额；"
            "4) 机构占比突然剧降（疑似机构集中赎回）。"
        ),
        scenarios=[
            "客户结构稳定性评估",
            "大额赎回流动性风险预警",
            "机构客户集中度监管报送",
            "营销策略调整与产品定位",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "INVESTOR_TYPE",
            "HOLDER_CNT", "HOLD_SHARE", "HOLD_AMT", "HOLD_RATIO", "TOP10_RATIO",
        ],
        primary_keys=["PORT_ID", "BIZ_DT", "INVESTOR_TYPE"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 9. 投资限制
    "dwd_ptl_limit": TableProfile(
        table_name="dwd_ptl_limit",
        domain="product",
        display_name="组合投资限制表",
        purpose=(
            "登记每个组合的投资约束规则（单券上限、权益占比、债券下限、久期/期限、"
            "信用债占比、跟踪误差等）的描述、限值（LIMIT_VALUE）、当前值"
            "（CURRENT_VALUE）与状态（NORMAL/WARNING/BREACH），"
            "是事前/事中合规监控的规则与状态表。"
        ),
        distribution=(
            "STATUS 多为 NORMAL，少量 WARNING/BREACH；"
            "限制类型按产品类型差异化：MMF 重点 AVG_MATURITY/MAX_MATURITY，"
            "BOND 重点 BOND_FLOOR/CREDIT_BOND/DURATION，INDEX 重点 INDEX_TRACK/TRACK_ERR_CAP。"
        ),
        trend=(
            "限制规则一般稳定；CURRENT_VALUE 日频/周频更新；"
            "市场剧烈波动后 BREACH 数量短期内可能增加。"
        ),
        anomaly=(
            "应关注：1) STATUS=BREACH 持续多日（合规处置滞后）；"
            "2) CURRENT_VALUE 缺失但 STATUS=NORMAL（监控失效）；"
            "3) 同一限制类型出现多条历史记录（CHECK_DT 重叠）；"
            "4) LIMIT_VALUE 与产品合同披露不符。"
        ),
        scenarios=[
            "事前/事中合规校验",
            "BREACH 资产识别与处置跟踪",
            "限额预留与新增交易决策",
            "合规规则全量审查与版本管理",
        ],
        key_fields=[
            "PORT_ID", "LIMIT_TYPE", "LIMIT_DESC",
            "LIMIT_VALUE", "CURRENT_VALUE", "STATUS", "CHECK_DT",
        ],
        primary_keys=["PORT_ID", "LIMIT_TYPE", "CHECK_DT"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 10. 交易汇总
    "dwd_ptl_transaction_summary": TableProfile(
        table_name="dwd_ptl_transaction_summary",
        domain="product",
        display_name="组合交易汇总表",
        purpose=(
            "对每日的买入/卖出笔数、金额、净额、换手金额、换手率与总费用进行汇总，"
            "用于交易行为分析、换手率监控与冲击成本评估。"
        ),
        distribution=(
            "MMF 类换手率最高（T+0 频繁申赎与回购）；BOND 组合中等；"
            "MIXED/INDEX 类换手率较低；NET_AMT 正负反映净申购/净赎回压力。"
        ),
        trend=(
            "工作日日频；月末/季末换手放量；"
            "市场恐慌期 SELL_AMT 显著放大，平静期净额接近零。"
        ),
        anomaly=(
            "应关注：1) BUY_CNT/SELL_CNT 与流水表条数不一致；"
            "2) TURNOVER_RATIO 单日跳变 > 50%；3) TOTAL_FEE 与费率结构不匹配；"
            "4) NET_AMT 持续大额负值（赎回压力累积）。"
        ),
        scenarios=[
            "交易活跃度与换手率监控",
            "交易冲击成本估算",
            "异常交易模式识别（刷量/拉抬）",
            "净申赎与现金管理协同",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT",
            "BUY_CNT", "BUY_AMT", "SELL_CNT", "SELL_AMT",
            "NET_AMT", "TURNOVER", "TURNOVER_RATIO", "TOTAL_FEE",
        ],
        primary_keys=["PORT_ID", "BIZ_DT"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 11. 业绩归因
    "dwd_ptl_attribution": TableProfile(
        table_name="dwd_ptl_attribution",
        domain="product",
        display_name="组合业绩归因表",
        purpose=(
            "按因子（INTEREST_RATE/CREDIT_SPREAD/STOCK_SELECT/BOND_SELECT/TRADING）"
            "拆解组合每日收益贡献（CONTRIBUTION）与暴露权重（WEIGHT），"
            "支撑超额来源识别、策略评估与风格分析。"
        ),
        distribution=(
            "BOND 组合归因因子集中在 INTEREST_RATE/BOND_SELECT；"
            "MIXED 组合包含 STOCK_SELECT/TRADING；MMF 重点为 INTEREST_RATE/TRADING；"
            "INDEX 组合 STOCK_SELECT 是核心 Alpha 来源。"
        ),
        trend=(
            "BIZ_DT 日频；INTEREST_RATE 贡献跟随利率波动方向；"
            "CREDIT_SPREAD 在信用事件后短期为负贡献；TRADING 因子在调仓季波动较大。"
        ),
        anomaly=(
            "应关注：1) 各因子 CONTRIBUTION 合计与 DAILY_RET 偏差 > 5bp；"
            "2) 同一因子 WEIGHT > 1.0；3) 缺失关键因子（如 INDEX 缺少 STOCK_SELECT）；"
            "4) CONTRIBUTION 量级异常（远超 DAILY_RET）。"
        ),
        scenarios=[
            "Alpha/Beta 拆解与策略效率评估",
            "风格漂移与暴露管理",
            "归因报告与客户披露",
            "因子模型校验",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "ATTR_FACTOR", "ATTR_DESC",
            "CONTRIBUTION", "WEIGHT",
        ],
        primary_keys=["PORT_ID", "BIZ_DT", "ATTR_FACTOR"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 12. 合规检查记录
    "dwd_ptl_compliance": TableProfile(
        table_name="dwd_ptl_compliance",
        domain="product",
        display_name="组合合规检查记录表",
        purpose=(
            "记录每日合规检查项（CHECK_ITEM）的结果（PASS/WARN/FAIL）、违规描述、"
            "处置动作（ACTION）及违规级别（INFO/MINOR/MAJOR），"
            "用于合规事项跟踪、整改闭环与监管报送。"
        ),
        distribution=(
            "RESULT 以 PASS 为主，少量 WARN/FAIL；LEVEL 分布于 INFO/MINOR/MAJOR；"
            "FAIL 高发项集中在单券集中度、权益区间、跟踪误差、成份股占比；"
            "CHECKER 多为 COMPLIANCE_AUTO（自动校验）。"
        ),
        trend=(
            "日频检查；新规生效时短期 WARN/FAIL 数量上升；"
            "合规整改后 FAIL 项目应在 T+5 内闭环。"
        ),
        anomaly=(
            "应关注：1) RESULT=FAIL 且 ACTION 为空（处置缺失）；"
            "2) 同一 CHECK_ITEM 连续多日 FAIL；3) MAJOR 级违规未上报合规委员会；"
            "4) 与 dwd_ptl_limit 状态不一致。"
        ),
        scenarios=[
            "合规事项闭环管理",
            "重大违规上报与披露",
            "监管检查取证与回溯",
            "合规规则有效性评估",
        ],
        key_fields=[
            "PORT_ID", "CHECK_DT", "CHECK_ITEM", "CHECK_DESC",
            "RESULT", "VIOLATION", "ACTION", "LEVEL", "CHECKER",
        ],
        primary_keys=["PORT_ID", "CHECK_DT", "CHECK_ITEM"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),
}
