"""
估值域(Valuation Domain) - L1 单表画像定义
覆盖 dwd_val_* 共 10 张表，主键以 PORT_ID + BIZ_DT (+ 维度键) 为锚点。
画像内容依据 mongo-seed/04_valuation_domain.js 的 Schema 与业务语义编写。
"""
from ..models import DomainOverview, TableProfile

# ====================== 域概览 ======================
DOMAIN_OVERVIEW = DomainOverview(
    domain_code="valuation",
    domain_name="估值域",
    description=(
        "围绕组合每日估值核算，沉淀估值表头、资产明细、收入/费用、资金流水、"
        "外汇敞口及久期/信用/行业/集中度等多维度分布，是产品净值生成、"
        "财务核算、风险敞口分析与监管报送的事实层。"
    ),
    table_count=10,
    tables=[
        "dwd_val_valtable",
        "dwd_val_asset_detail",
        "dwd_val_income",
        "dwd_val_expense",
        "dwd_val_cash_flow",
        "dwd_val_fx_exposure",
        "dwd_val_duration_bucket",
        "dwd_val_credit_bucket",
        "dwd_val_sector_bucket",
        "dwd_val_concentration",
    ],
    core_scenarios=[
        "组合每日估值与净值生成",
        "持仓资产 MTM 损益核算",
        "收入费用计提与利润表生成",
        "资金流水与申赎对账",
        "外汇敞口与对冲监控",
        "久期/信用/行业敞口结构分析",
        "集中度风险（TOP1/TOP5）监控",
    ],
    key_entities=["PORT_ID", "BIZ_DT", "AST_CD", "VAL_STATUS"],
)


# ====================== L1 单表画像 ======================
TABLE_PROFILES: dict[str, TableProfile] = {
    # 1. 估值表
    "dwd_val_valtable": TableProfile(
        table_name="dwd_val_valtable",
        domain="valuation",
        display_name="估值表（表头）",
        purpose=(
            "存储每个组合每日的估值表头信息：总资产、总负债、净资产、份额净值、"
            "累计净值、总份额、日收益率、估值状态（CONFIRMED/PUBLISHED）与版本号，"
            "是估值汇总与产品净值披露的核心头表。"
        ),
        distribution=(
            "TOTAL_ASSET = NET_ASSET + TOTAL_LIAB（约 0.2% 应付负债）；"
            "VAL_STATUS 多为 CONFIRMED（最新交易日为 PUBLISHED）；"
            "VAL_VERSION 通常为 1，重估时递增；MMF 组合 SHR_NAV 恒为 1.0000。"
        ),
        trend=(
            "工作日日频生成；NAV 与组合持仓估值变化同步；"
            "每月底/季度末加发披露版本，估值版本号会增加。"
        ),
        anomaly=(
            "应关注：1) NET_ASSET ≠ SHR_NAV * TOTAL_SHARE；"
            "2) DAILY_RET 与 ACC_NAV 链式变动不一致；"
            "3) VAL_STATUS 长期为 CONFIRMED 未升级到 PUBLISHED；"
            "4) VAL_VERSION 突然跳升（重估事件）；5) 与 dwd_ptl_nav_hist 数据冲突。"
        ),
        scenarios=[
            "组合每日净值生成与发布",
            "估值版本变更追溯",
            "净值与其他模块（产品域 NAV）对账",
            "监管报送与披露口径核对",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "TOTAL_ASSET", "TOTAL_LIAB", "NET_ASSET",
            "SHR_NAV", "ACC_NAV", "TOTAL_SHARE", "DAILY_RET",
            "VAL_STATUS", "VAL_VERSION",
        ],
        primary_keys=["PORT_ID", "BIZ_DT"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 2. 估值资产明细
    "dwd_val_asset_detail": TableProfile(
        table_name="dwd_val_asset_detail",
        domain="valuation",
        display_name="估值资产明细表",
        purpose=(
            "逐资产记录估值的成本价/市值价、持仓数量、成本金额、市值、估值变动"
            "（VAL_CHANGE）、浮动盈亏（UNREAL_PNL）与日盈亏（DAILY_PNL），"
            "是组合估值最细粒度的事实表。"
        ),
        distribution=(
            "记录数 = 组合数 × 平均持仓只数（约 25 条）；"
            "UNREAL_PNL 大部分为正（经过升值），少部分为负（地产信用债下跌）；"
            "DAILY_PNL 量级覆盖几千到千万，反映持仓规模与价格弹性。"
        ),
        trend=(
            "BIZ_DT 日频；调仓后成本价更新、市值随估值变动；"
            "MTM 全面采用估值源（中债/中证），不存在自定义价。"
        ),
        anomaly=(
            "应关注：1) MKT_VAL 与 dwd_ptl_holding.HOLD_MV 不一致；"
            "2) UNREAL_PNL 与 (MKT_VAL - COST_AMT) 偏差；"
            "3) MKT_PRC 与 dwd_ast_info_ch.VAL_NET_PRC 偏离 > 50bp；"
            "4) HOLD_QTY 为 0 但仍有 MKT_VAL；5) DAILY_PNL 异常脉冲（疑似估值跳变）。"
        ),
        scenarios=[
            "持仓 MTM 估值入账",
            "浮动盈亏明细分析",
            "估值跳变与定价异常审查",
            "归因分析的资产侧底数",
            "持仓资产价格波动监控",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "AST_CD", "AST_NM",
            "HOLD_QTY", "COST_PRC", "MKT_PRC", "COST_AMT", "MKT_VAL",
            "VAL_CHANGE", "UNREAL_PNL", "DAILY_PNL",
        ],
        primary_keys=["PORT_ID", "AST_CD", "BIZ_DT"],
        foreign_keys={
            "PORT_ID": "dwd_ptl_info.PORT_ID",
            "AST_CD": "dwd_ast_info.AST_CD",
        },
    ),

    # 3. 收入明细
    "dwd_val_income": TableProfile(
        table_name="dwd_val_income",
        domain="valuation",
        display_name="估值收入明细表",
        purpose=(
            "按收入类型（INTEREST 利息收入、DIVIDEND 股息收入、FV_CHANGE 公允价值变动）"
            "记录每个组合每日的收入金额与币种，是利润表收入侧的明细源。"
        ),
        distribution=(
            "BOND/MMF 组合以 INTEREST 为主、DIVIDEND 为 0；"
            "MIXED/INDEX 组合三类收入俱全；FV_CHANGE 量级最大但波动剧烈，"
            "下跌日可为大额负值。"
        ),
        trend=(
            "INTEREST 平稳累积（每日按息票计提）；DIVIDEND 集中在分红披露日；"
            "FV_CHANGE 与市场行情同步波动。"
        ),
        anomaly=(
            "应关注：1) INTEREST 与现金流计划（dwd_ast_cf_plan）不匹配；"
            "2) DIVIDEND 在无权益持仓的组合中出现非零值；"
            "3) FV_CHANGE 与 dwd_val_asset_detail.DAILY_PNL 总和偏差大；"
            "4) CCY 与组合本币不一致。"
        ),
        scenarios=[
            "利润表收入侧核对",
            "利息计提合理性检查",
            "公允价值变动与市场行情联动",
            "股息事件追溯",
        ],
        key_fields=["PORT_ID", "BIZ_DT", "INC_TYPE", "INC_DESC", "AMT", "CCY"],
        primary_keys=["PORT_ID", "BIZ_DT", "INC_TYPE"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 4. 费用明细
    "dwd_val_expense": TableProfile(
        table_name="dwd_val_expense",
        domain="valuation",
        display_name="估值费用明细表",
        purpose=(
            "按费用类型（MGT_FEE 管理费、CUSTODY_FEE 托管费、TXN_FEE 交易费用）"
            "记录每个组合每日的费用金额，与产品域费率表（dwd_ptl_fee）对账，"
            "支撑利润表费用侧核算。"
        ),
        distribution=(
            "MGT_FEE 占比最大，CUSTODY_FEE 次之，TXN_FEE 与换手率相关；"
            "费率结构与 dwd_ptl_fee 严格一致，按日（/365）计提。"
        ),
        trend=(
            "工作日日频；管理费与托管费稳定，与 AUM 成线性；"
            "交易费用在月末/调仓日明显放大。"
        ),
        anomaly=(
            "应关注：1) 计提金额 ≠ NET_ASSET × 费率 / 365；"
            "2) TXN_FEE 与 dwd_ptl_transaction_summary.TOTAL_FEE 不一致；"
            "3) EXP_TYPE 缺失关键类型；4) AMT 出现负值；5) CCY 与 base 不一致。"
        ),
        scenarios=[
            "利润表费用侧核对",
            "费用计提与费率合规校验",
            "交易冲击成本测算",
            "成本/收入比与产品盈利能力评估",
        ],
        key_fields=["PORT_ID", "BIZ_DT", "EXP_TYPE", "EXP_DESC", "AMT", "CCY"],
        primary_keys=["PORT_ID", "BIZ_DT", "EXP_TYPE"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 5. 资金流水
    "dwd_val_cash_flow": TableProfile(
        table_name="dwd_val_cash_flow",
        domain="valuation",
        display_name="估值资金流水表",
        purpose=(
            "按现金流类型（SUBSCRIBE 申购、REDEEM 赎回、INTEREST 利息、DIVIDEND 分红）"
            "和序列号记录每个组合每日的资金进出，"
            "是现金管理与申赎对账的源表。"
        ),
        distribution=(
            "MMF 组合 SUBSCRIBE/REDEEM 量级最大（亿元级 T+0），"
            "其余组合在百万到千万级别；INTEREST 与收入表对应；"
            "DIVIDEND 在派息日为负值（流出），其他日 0 或微小。"
        ),
        trend=(
            "工作日日频；申赎波动随客户行为；"
            "市场恐慌/利好时净流出/净流入会明显放大。"
        ),
        anomaly=(
            "应关注：1) SUBSCRIBE/REDEEM 总额与产品销售系统不一致；"
            "2) 大额 REDEEM 触发流动性风险；3) INTEREST 金额与收入表偏差；"
            "4) CF_SEQ 重复或缺失；5) 货基日结收益与份额转换金额不平。"
        ),
        scenarios=[
            "申赎对账与流动性管理",
            "现金缺口预测",
            "大额申赎客户行为分析",
            "现金流分类汇总（流入/流出）",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "CF_TYPE", "CF_SEQ", "AMT", "CCY", "SUMMARY",
        ],
        primary_keys=["PORT_ID", "BIZ_DT", "CF_TYPE", "CF_SEQ"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 6. 外汇敞口
    "dwd_val_fx_exposure": TableProfile(
        table_name="dwd_val_fx_exposure",
        domain="valuation",
        display_name="估值外汇敞口表",
        purpose=(
            "记录每个组合各币种（USD/HKD/EUR/JPY/OTHER）的敞口金额、"
            "净敞口比例（NET_FX_RATIO）、对冲比例（HEDGE_RATIO）与对冲说明，"
            "用于外汇风险监控、对冲策略评估与监管报送。"
        ),
        distribution=(
            "本批组合均为 CNY 计价，外币敞口为 0；HEDGE_RATIO 为 0；"
            "对于 QDII/全球配置型产品，USD/HKD 敞口通常占比最高。"
        ),
        trend=(
            "BASE_CCY/外币敞口随产品投资范围扩张而增加；"
            "对冲比例随汇率波动率与组合风险偏好动态调整。"
        ),
        anomaly=(
            "应关注：1) 各币种敞口合计 ≠ NET_ASSET（含 CNY）；"
            "2) NET_FX_RATIO 突破合规上限；3) HEDGE_RATIO > 1.0（过度对冲）；"
            "4) HEDGE_DESC 与 HEDGE_RATIO 不一致；5) 出现新币种但未登记。"
        ),
        scenarios=[
            "汇率风险敞口监控",
            "对冲策略有效性评估",
            "QDII 监管报送",
            "汇率剧烈波动的应急扫描",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "BASE_CCY", "NET_ASSET_CNY",
            "USD_EXPOSURE", "HKD_EXPOSURE", "EUR_EXPOSURE", "JPY_EXPOSURE",
            "OTHER_EXPOSURE", "NET_FX_RATIO", "HEDGE_RATIO", "HEDGE_DESC",
        ],
        primary_keys=["PORT_ID", "BIZ_DT"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 7. 久期分布
    "dwd_val_duration_bucket": TableProfile(
        table_name="dwd_val_duration_bucket",
        domain="valuation",
        display_name="估值久期分布表",
        purpose=(
            "按久期区间（0-1Y/1-3Y/3-5Y/5-7Y/7-10Y/10Y+）汇总每个组合"
            "对应区间的权重（WEIGHT）、市值（MKT_VAL）与平均久期（AVG_DUR），"
            "用于利率风险敞口管理与久期目标控制。"
        ),
        distribution=(
            "MMF 组合集中在 0-1Y/1-3Y；BOND 组合权重在 3-10Y 区间；"
            "MIXED 组合 1-5Y 占主导；INDEX 组合久期波动取决于权益占比。"
        ),
        trend=(
            "BIZ_DT 日频；调仓后区间权重平滑漂移；"
            "利率上行/下行预期会驱动整体久期主动收缩或拉长。"
        ),
        anomaly=(
            "应关注：1) 各 DUR_BUCKET 权重合计 ≠ 1.0（仅债券维度）；"
            "2) MMF 出现 5Y+ 区间持仓；3) AVG_DUR 与 BUCKET 不匹配；"
            "4) MKT_VAL 求和与组合债券市值不闭环。"
        ),
        scenarios=[
            "利率风险敞口结构分析",
            "久期目标管理与限额监控",
            "收益率曲线变形对组合的影响",
            "压力测试场景下的久期暴露",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "DUR_BUCKET", "WEIGHT", "MKT_VAL", "AVG_DUR",
        ],
        primary_keys=["PORT_ID", "BIZ_DT", "DUR_BUCKET"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 8. 信用分布
    "dwd_val_credit_bucket": TableProfile(
        table_name="dwd_val_credit_bucket",
        domain="valuation",
        display_name="估值信用分布表",
        purpose=(
            "按信用评级桶（AAA/AAA-/AA+/AA/AA-）汇总每个组合的权重与市值，"
            "记录评级机构（RATING_AGENCY），用于信用敞口结构分析与下沉策略评估。"
        ),
        distribution=(
            "AAA 占比最高（多数组合 > 60%），AAA-/AA+ 次之；"
            "AA 及以下占比较低；MMF/INDEX 类组合几乎全部在 AAA。"
        ),
        trend=(
            "BIZ_DT 日频；信用下沉策略阶段 AA+/AA 权重抬升；"
            "信用风险事件后高资质权重被动上升（低资质资产被估值下调）。"
        ),
        anomaly=(
            "应关注：1) 权重合计 ≠ 1.0；2) 出现未在评级表中登记的桶；"
            "3) 不同评级机构差异大但仅记录单一来源；4) 信用集中度突破合规限值。"
        ),
        scenarios=[
            "信用敞口结构与下沉/上沉决策",
            "评级合规约束监控（如禁投 AA 以下）",
            "信用利差贡献度分析",
            "压力测试中评级迁移影响",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "CREDIT_BUCKET", "WEIGHT", "MKT_VAL", "RATING_AGENCY",
        ],
        primary_keys=["PORT_ID", "BIZ_DT", "CREDIT_BUCKET"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 9. 行业分布
    "dwd_val_sector_bucket": TableProfile(
        table_name="dwd_val_sector_bucket",
        domain="valuation",
        display_name="估值行业分布表",
        purpose=(
            "按行业/品种（利率债/银行/宽基ETF/同业存单/绿色债券/ABS 等）汇总组合权重、"
            "市值与资产数量（ASSET_CNT），用于行业敞口分析与板块策略评估。"
        ),
        distribution=(
            "BOND 组合以利率债为主导；MMF 组合以利率债+同业存单+国债ETF 为主；"
            "INDEX 组合宽基ETF 与银行/保险并重；MIXED 组合行业更分散。"
        ),
        trend=(
            "BIZ_DT 日频；行业切换与板块景气度相关；"
            "新主题债（绿色债、科技债）入池后会出现新的 SECTOR 分类。"
        ),
        anomaly=(
            "应关注：1) 权重合计 ≠ 1.0；2) SECTOR 命名不统一（同义词碎片化）；"
            "3) ASSET_CNT 与持仓表统计不一致；4) 行业集中度突破合规限值（如单行业 > 30%）。"
        ),
        scenarios=[
            "行业/板块敞口结构分析",
            "板块轮动策略效果评估",
            "行业集中度合规检查",
            "ESG/绿色资产占比披露",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "SECTOR", "WEIGHT", "MKT_VAL", "ASSET_CNT",
        ],
        primary_keys=["PORT_ID", "BIZ_DT", "SECTOR"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),

    # 10. 集中度
    "dwd_val_concentration": TableProfile(
        table_name="dwd_val_concentration",
        domain="valuation",
        display_name="估值集中度表",
        purpose=(
            "按集中度类型（TOP1/TOP5/TOP10）记录每个组合前 N 大持仓的合计市值与占比，"
            "用于集中度风险监控、合规检查与流动性评估。"
        ),
        distribution=(
            "TOP1 占比通常 15%~45%（INDEX 组合最高）；"
            "TOP5 占比 30%~90%（MMF 组合最高）；"
            "BOND 组合相对分散，MIXED 组合分散度居中。"
        ),
        trend=(
            "BIZ_DT 日频；调仓后集中度短期波动；"
            "市场单边行情中头部资产集中度被动抬升或下降。"
        ),
        anomaly=(
            "应关注：1) RATIO 与 dwd_ptl_holding 计算不一致；"
            "2) TOP1 突破单券合规上限（如 10%）；3) TOP5 RATIO 长期 > 0.80（极度集中）；"
            "4) NOTE 字段与实际 TOP1 资产不匹配。"
        ),
        scenarios=[
            "集中度合规检查（双十规则等）",
            "流动性风险压力测试",
            "TOP 持仓变动跟踪",
            "组合分散度评分模型",
        ],
        key_fields=[
            "PORT_ID", "BIZ_DT", "CONC_TYPE", "RANK_DESC",
            "TOP_N", "MKT_VAL", "RATIO", "NOTE",
        ],
        primary_keys=["PORT_ID", "BIZ_DT", "CONC_TYPE"],
        foreign_keys={"PORT_ID": "dwd_ptl_info.PORT_ID"},
    ),
}
