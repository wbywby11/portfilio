"""
MongoDB 集合元数据注册中心

启动时扫描数据库中所有业务集合，自动推断 Schema，
存储元数据供 data_query 工具使用。
"""

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from loguru import logger

from app.config.database import Database

# ---------------------------------------------------------------------------
# 业务域元数据预注册：9 域 82+ 张表
# ---------------------------------------------------------------------------

DOMAIN_METADATA: dict[str, dict] = {
    # ============================= 资产域 (14表) =============================
    "asset": {
        "display_name": "资产域",
        "description": "管理债券、股票、基金、ABS等资产的基础信息、行情K线和估值数据，共14张表",
        "tables": {
            "dwd_ast_info": {
                "display_name": "资产基础信息表",
                "description": "记录所有资产的代码、名称、类型、发行人、期限、票面利率等核心属性，是资产域的核心主表",
                "primary_keys": ["AST_CD"],
                "foreign_keys": {"ISR_ID": "dwd_isr_institution.ISR_ID"},
                "key_fields": ["AST_CD", "AST_NM", "AST_TYPE", "AST_SUB_TYPE", "ISR_ID", "MATURITY_DT", "COUPON_RATE", "ISSUE_AMT", "MARKET"],
                "typical_queries": ["查询所有国债类资产", "筛选到期日在2025年内的债券", "按发行人分组统计资产数量", "查询票面利率高于3%的债券"]
            },
            "dwd_ast_info_ch": {
                "display_name": "中债估值表",
                "description": "中央国债登记结算公司每日估值数据，包含净价、全价、到期收益率、修正久期、凸性等核心指标",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BIZ_DT", "VAL_NET_PRC", "VAL_FULL_PRC", "VAL_YIELD", "DURATION", "CONVEXITY"],
                "typical_queries": ["查询某债券最新中债估值", "对比两个日期的久期变化", "筛选估值收益率低于2%的债券"]
            },
            "dwd_ast_info_zg": {
                "display_name": "中证估值表",
                "description": "中证指数公司每日估值数据，与中债估值对照使用",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BIZ_DT", "VAL_NET_PRC", "VAL_FULL_PRC", "VAL_YIELD", "DURATION"],
                "typical_queries": ["查询中证估值与中债估值对比", "获取某资产的中证估值历史"]
            },
            "dwd_ast_yield_info": {
                "display_name": "资产收益率表",
                "description": "资产到期收益率、行权收益率以及日/周/月/年初至今等多周期收益率",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BIZ_DT", "YIELD_TM", "YIELD_EX", "DAILY_RTN", "YTD_RTN"],
                "typical_queries": ["查询某债券近一个月收益率", "筛选年初至今收益最高的资产", "按到期收益率排序"]
            },
            "dwd_ast_cf_plan": {
                "display_name": "资产现金流计划表",
                "description": "债券等资产的利息和本金偿还计划明细",
                "primary_keys": ["AST_CD", "CF_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "CF_DT", "CF_TYPE", "CF_AMT", "CCY"],
                "typical_queries": ["查询某债券未来现金流计划", "统计本月到期的利息总额"]
            },
            "dwd_ast_pledge": {
                "display_name": "资产质押状态表",
                "description": "资产的质押登记状态、质押比例和标准券折算信息",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BIZ_DT", "PLEDGE_FLAG", "PLEDGE_RATIO", "PLEDGE_STD_BOND"],
                "typical_queries": ["查询当前已质押资产", "统计质押比例超过50%的资产"]
            },
            "dwd_ast_party": {
                "display_name": "资产关联方表",
                "description": "资产相关的发行人、担保人、受托人、托管人、承销商等关联方信息",
                "primary_keys": ["AST_CD", "PARTY_ID"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "PARTY_ID", "PARTY_NM", "PARTY_ROLE"],
                "typical_queries": ["查询某债券的所有关联方", "按角色筛选担保人"]
            },
            "dwd_ast_exe_plan": {
                "display_name": "资产行权计划表",
                "description": "含权债的行权计划，包含回售、赎回、延期等行权类型与日期",
                "primary_keys": ["AST_CD", "EXE_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "EXE_DT", "EXE_TYPE", "EXE_PRC"],
                "typical_queries": ["查询近期有行权计划的债券", "筛选可回售的含权债"]
            },
            "dwd_ast_fund_manager": {
                "display_name": "资产基金经理表",
                "description": "基金资产对应的基金经理任职信息，包含共管标识",
                "primary_keys": ["AST_CD", "MANAGER_ID"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "MANAGER_ID", "MANAGER_NM", "START_DT", "END_DT"],
                "typical_queries": ["查询某基金的历任经理", "筛选当前在任经理管理的基金"]
            },
            "dwd_ast_bottom_raito": {
                "display_name": "资产穿透底层表",
                "description": "FOF、资管计划等产品的底层资产穿透占比数据",
                "primary_keys": ["AST_CD", "BTM_AST_CD"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BTM_AST_CD", "RATIO", "BTM_NM"],
                "typical_queries": ["查看某产品穿透后底层资产构成", "统计底层重仓资产"]
            },
            "dwd_ast_fiveclass": {
                "display_name": "资产五级分类表",
                "description": "资产信用质量五级分类（正常/关注/次级/可疑/损失）及变动历史",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BIZ_DT", "CLASS_LVL", "CLASS_REASON", "ADJ_FLAG"],
                "typical_queries": ["查询当前非正常类资产", "统计五级分类分布", "查看资产分类调整历史"]
            },
            "dwd_ast_calc_rule": {
                "display_name": "资产计算规则表",
                "description": "不同资产类型适用的估值计算公式与生效日期",
                "primary_keys": ["AST_TYPE", "RULE_CD"],
                "foreign_keys": {},
                "key_fields": ["AST_TYPE", "RULE_CD", "RULE_NM", "FORMULA", "EFF_DT"],
                "typical_queries": ["查询债券类适用的计算规则", "获取最新生效的估值公式"]
            },
            "assets": {
                "display_name": "资产列表主数据表",
                "description": "组合管理系统的资产主数据，包含资产代码(code)、名称(name)、类型(asset_type)、创建时间等，是K线行情和产品持仓的父表",
                "primary_keys": ["code"],
                "foreign_keys": {},
                "key_fields": ["code", "name", "asset_type", "created_at"],
                "typical_queries": ["查询所有资产列表", "按资产类型筛选", "获取资产代码与名称映射"]
            },
            "asset_prices": {
                "display_name": "资产日频K线行情表",
                "description": "资产日频行情数据，包含日期(date)、资产代码(asset_code)、开盘价(open)、最高价(high)、最低价(low)、收盘价(close)、成交量(volume)、成交额(amount)、规模(scale)等OHLC字段",
                "primary_keys": ["asset_code", "date"],
                "foreign_keys": {"asset_code": "assets.code"},
                "key_fields": ["asset_code", "date", "open", "high", "low", "close", "volume", "amount", "scale"],
                "typical_queries": ["查询某资产近30日K线", "获取多资产收盘价对比", "计算区间收益率", "查询某日全市场行情"]
            },
        }
    },
    # ============================= 主体域 (3表) =============================
    "subject": {
        "display_name": "主体域",
        "description": "管理发行人、交易对手等市场主体的基本信息和财务数据",
        "tables": {
            "dwd_isr_institution": {
                "display_name": "机构基础信息表",
                "description": "记录所有发行人/机构的名称、类型、行业、注册地等基本信息",
                "primary_keys": ["ISR_ID"],
                "foreign_keys": {},
                "key_fields": ["ISR_ID", "ISR_NM", "ISR_SHORT_NM", "ISR_TYPE", "INDUSTRY_CD", "REG_PROV"],
                "typical_queries": ["查询所有政府类发行人", "按行业筛选机构", "查询某机构详情"]
            },
            "dwd_isr_institution_finance": {
                "display_name": "机构财务报表",
                "description": "机构/发行人的定期财务数据，包含总资产、总负债、营收、净利润、ROE等",
                "primary_keys": ["ISR_ID", "RPT_DT", "RPT_TYPE"],
                "foreign_keys": {"ISR_ID": "dwd_isr_institution.ISR_ID"},
                "key_fields": ["ISR_ID", "RPT_DT", "RPT_TYPE", "TOT_AST", "TOT_LIA", "EQUITY", "REVENUE", "NET_PRFT", "ROE"],
                "typical_queries": ["查询某发行人最新财报", "对比多家机构资产规模", "分析某机构利润趋势"]
            },
            "dwd_isr_trd_cntp": {
                "display_name": "交易对手信息表",
                "description": "债券交易的交易对手方信息，含类型、市场、评级、白名单、结算信息等",
                "primary_keys": ["CNTP_ID"],
                "foreign_keys": {"LINKED_ISR_ID": "dwd_isr_institution.ISR_ID"},
                "key_fields": ["CNTP_ID", "CNTP_NM", "CNTP_TYPE", "MARKET", "RATING", "WHITELIST"],
                "typical_queries": ["查询所有白名单交易对手", "按类型筛选对手方", "查询银行间市场对手"]
            },
        }
    },
    # ============================= 产品域 (12表) =============================
    "product": {
        "display_name": "产品域",
        "description": "管理投资组合/产品的基础信息、持仓明细、申赎、费率、账户等12张表",
        "tables": {
            "dwd_ptl_info": {
                "display_name": "产品基础信息表",
                "description": "投资组合/产品的名称、类型、风险等级、管理规模、业绩基准等核心属性",
                "primary_keys": ["PORT_ID"],
                "foreign_keys": {},
                "key_fields": ["PORT_ID", "PORT_NM", "PORT_TYPE", "RISK_LVL", "AUM", "BENCHMARK", "ESTAB_DT", "STATUS"],
                "typical_queries": ["查询所有产品列表", "按类型筛选产品", "查找AUM超过10亿的组合"]
            },
            "tag_ptl_info": {
                "display_name": "产品标签表",
                "description": "产品的多维度标签分组信息，用于标签化管理",
                "primary_keys": ["PORT_ID", "TAG_GROUP", "TAG_VAL"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "TAG_GROUP", "TAG_VAL"],
                "typical_queries": ["查询某产品的所有标签", "按标签组筛选产品"]
            },
            "dwd_ptl_acc": {
                "display_name": "产品账户表",
                "description": "产品关联的资金账户、托管账户等多类型账户信息",
                "primary_keys": ["PORT_ID", "ACCT_NO"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "ACCT_NO", "ACCT_TYPE", "ACCT_NM", "BANK_BR"],
                "typical_queries": ["查询某产品的所有账户", "按账户类型筛选"]
            },
            "dwd_ptl_cedetail": {
                "display_name": "产品申赎明细表",
                "description": "产品的申购、赎回、分红等资金变动明细记录",
                "primary_keys": ["PORT_ID", "TRADE_DT", "CE_TYPE"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "TRADE_DT", "CE_TYPE", "AMT", "CCY"],
                "typical_queries": ["查询某产品近期申赎记录", "统计本月赎回总额"]
            },
            "dwd_ptl_fee": {
                "display_name": "产品费率表",
                "description": "产品各类费率（管理费、托管费、销售费、业绩报酬等）及其生效时间",
                "primary_keys": ["PORT_ID", "FEE_TYPE"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "FEE_TYPE", "FEE_RATE", "FEE_BASE", "EFF_DT"],
                "typical_queries": ["查询某产品当前费率", "对比各产品管理费率"]
            },
            "dwd_ptl_managers": {
                "display_name": "产品经理表",
                "description": "产品/组合的投资经理信息，包含主管、副管、助理等角色",
                "primary_keys": ["PORT_ID", "MANAGER_ID"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "MANAGER_ID", "MANAGER_NM", "ROLE", "START_DT"],
                "typical_queries": ["查询某产品的投资经理", "查询某经理管理的所有产品"]
            },
            "dwd_ptl_open_plan": {
                "display_name": "产品开放计划表",
                "description": "封闭式产品的开放申赎日期安排及额度控制",
                "primary_keys": ["PORT_ID", "OPEN_DT"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "OPEN_DT", "OPEN_TYPE", "CLOSE_DT", "QUOTA_AMT"],
                "typical_queries": ["查询某产品下一个开放日", "获取支持申购的开放计划"]
            },
            "dwd_ptl_asset_config_info": {
                "display_name": "产品资产配置表",
                "description": "产品的大类资产配置目标比例及上下限约束",
                "primary_keys": ["PORT_ID", "AST_CLASS"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "AST_CLASS", "TGT_RATIO", "MIN_RATIO", "MAX_RATIO"],
                "typical_queries": ["查询某产品资产配置比例", "筛选债券配置上限超过80%的产品"]
            },
            "dwd_ptl_acct_bal": {
                "display_name": "产品账户余额表",
                "description": "产品各类型账户（总额/可用/冻结）的逐日余额",
                "primary_keys": ["PORT_ID", "BIZ_DT", "BAL_TYPE"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "BIZ_DT", "BAL_TYPE", "AMT", "CCY"],
                "typical_queries": ["查询某产品最新可用余额", "查看账户余额变动趋势"]
            },
            "dwd_ptl_ast_hld": {
                "display_name": "产品持仓表",
                "description": "产品逐日持仓明细，含持仓数量、成本、市值、权重等核心持仓指标",
                "primary_keys": ["PORT_ID", "AST_CD", "BIZ_DT"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID", "AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["PORT_ID", "AST_CD", "BIZ_DT", "HLD_QTY", "MKT_VAL", "WEIGHT", "COST_AMT"],
                "typical_queries": ["查询某产品最新持仓", "获取持仓权重前10的资产", "查看某资产在各产品中的持仓"]
            },
            "dwd_ptl_holder_summary": {
                "display_name": "产品持有人汇总表",
                "description": "产品各类持有人（机构/个人/内部等）的份额与金额汇总",
                "primary_keys": ["PORT_ID", "BIZ_DT", "HOLDER_TYPE"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "BIZ_DT", "HOLDER_TYPE", "HOLDER_CNT", "TOT_SHR", "RATIO"],
                "typical_queries": ["查询某产品持有人结构", "统计机构客户占比"]
            },
            "dwd_cash_acc": {
                "display_name": "现金账户表",
                "description": "产品的现金账户逐日余额及利率信息",
                "primary_keys": ["PORT_ID", "ACCT_NO", "BIZ_DT"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "ACCT_NO", "BIZ_DT", "BAL", "AVAIL_BAL", "FROZEN_BAL", "RATE"],
                "typical_queries": ["查询某产品现金余额", "汇总所有产品的现金总额"]
            },
        }
    },
    # ============================= 估值域 (10表) =============================
    "valuation": {
        "display_name": "估值域",
        "description": "管理产品估值核算，包含估值表、凭证、科目余额、三张报表等10张表",
        "tables": {
            "dwd_val_valtable": {
                "display_name": "估值表",
                "description": "产品逐日估值核心数据，含总资产、净资产、份额净值、累计净值等",
                "primary_keys": ["PORT_ID", "BIZ_DT"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "BIZ_DT", "TOT_AST", "NET_AST", "SHR_NAV", "ACC_NAV", "DAILY_RTN"],
                "typical_queries": ["查询某产品最新净值", "获取产品净值走势", "对比多产品收益率"]
            },
            "dwd_val_voucher": {
                "display_name": "估值凭证表",
                "description": "估值核算产生的会计凭证明细，包含借贷金额和凭证类型",
                "primary_keys": ["PORT_ID", "BIZ_DT", "VOUCHER_NO"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "BIZ_DT", "VOUCHER_NO", "VOUCHER_TYPE", "DR_AMT", "CR_AMT"],
                "typical_queries": ["查询某日估值凭证", "筛选调整类凭证"]
            },
            "dwd_val_summary": {
                "display_name": "估值汇总表",
                "description": "按大类资产分类的持仓市值与权重汇总",
                "primary_keys": ["PORT_ID", "BIZ_DT", "AST_CLASS"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "BIZ_DT", "AST_CLASS", "MKT_VAL", "WEIGHT"],
                "typical_queries": ["查询某产品大类资产配置比例", "对比债券与现金占比变化"]
            },
            "dwd_val_detail": {
                "display_name": "估值明细表",
                "description": "产品逐券估值明细，含成本、市值、浮动盈亏、实现盈亏、摊销等",
                "primary_keys": ["PORT_ID", "AST_CD", "BIZ_DT"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID", "AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["PORT_ID", "AST_CD", "BIZ_DT", "MKT_VAL", "UNREAL_PNL", "REAL_PNL", "DAILY_PNL"],
                "typical_queries": ["查询某产品盈亏最大的持仓", "统计浮动盈亏汇总", "按日盈亏排序"]
            },
            "dwd_val_notice": {
                "display_name": "估值通知表",
                "description": "净值公告、分红通知、重大事项通知等产品公告信息",
                "primary_keys": ["PORT_ID", "BIZ_DT", "NOTICE_TYPE"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "BIZ_DT", "NOTICE_TYPE", "TITLE", "CONTENT"],
                "typical_queries": ["查询某产品最新公告", "筛选分红通知"]
            },
            "dwd_val_bal": {
                "display_name": "估值科目余额表",
                "description": "产品估值体系下各会计科目的借方/贷方余额",
                "primary_keys": ["PORT_ID", "BIZ_DT", "ACC_CD"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID", "ACC_CD": "dwd_val_acc.ACC_CD"},
                "key_fields": ["PORT_ID", "BIZ_DT", "ACC_CD", "ACC_NM", "DR_BAL", "CR_BAL", "BAL"],
                "typical_queries": ["查询某产品科目余额", "获取某科目各产品的余额对比"]
            },
            "dwd_val_acc": {
                "display_name": "估值科目表",
                "description": "估值核算使用的会计科目树结构定义",
                "primary_keys": ["ACC_CD"],
                "foreign_keys": {},
                "key_fields": ["ACC_CD", "ACC_NM", "PARENT_CD", "ACC_LVL", "DIRECTION"],
                "typical_queries": ["查询所有科目列表", "获取科目层级结构"]
            },
            "dwd_val_rpt_bs": {
                "display_name": "资产负债表",
                "description": "产品定期资产负债表，含现金、各类持仓、应收利息、应付款等",
                "primary_keys": ["PORT_ID", "RPT_DT"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "RPT_DT", "CASH", "BOND_HLD", "TOT_AST", "TOT_LIA", "EQUITY"],
                "typical_queries": ["查询某产品最新资产负债表", "对比多期资产规模变化"]
            },
            "dwd_val_rpt_is": {
                "display_name": "利润表",
                "description": "产品定期利润表，含利息收入、交易盈亏、管理费等收支项目",
                "primary_keys": ["PORT_ID", "RPT_DT"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "RPT_DT", "INT_INC", "TRD_PNL", "FV_CHG_PNL", "MGT_FEE", "NET_INC"],
                "typical_queries": ["查询某产品利润表", "对比利息收入与交易盈亏"]
            },
            "dwd_val_rpt_cf": {
                "display_name": "现金流量表",
                "description": "产品定期现金流量表，分投资活动和筹资活动列示现金流入流出",
                "primary_keys": ["PORT_ID", "RPT_DT"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["PORT_ID", "RPT_DT", "CF_FROM_INV_NET", "CF_FROM_FIN_NET", "CASH_NET_CHG"],
                "typical_queries": ["查询某产品现金流量表", "分析投资活动净流出"]
            },
        }
    },
    # ============================= 交易域 (6表) =============================
    "transaction": {
        "display_name": "交易域",
        "description": "管理债券/股票交易的指令下达、成交记录、结算交收全流程6张表",
        "tables": {
            "dwd_trn_trade_ast": {
                "display_name": "资产维度交易表",
                "description": "以资产为维度的交易成交记录，含方向、价格、金额、对手方等",
                "primary_keys": ["TRADE_ID"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD", "CNTP_ID": "dwd_isr_trd_cntp.CNTP_ID"},
                "key_fields": ["TRADE_ID", "AST_CD", "TRADE_DT", "BS_DIR", "QTY", "PRC", "AMT", "CNTP_ID", "STATUS"],
                "typical_queries": ["查询某资产的交易历史", "统计某日买入总额", "筛选某交易对手的成交"]
            },
            "dwd_trn_trade_ptl": {
                "display_name": "组合维度交易表",
                "description": "以组合为维度的交易明细，关联产品与资产",
                "primary_keys": ["TRADE_ID", "PORT_ID"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID", "AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["TRADE_ID", "PORT_ID", "AST_CD", "TRADE_DT", "BS_DIR", "AMT", "FEE"],
                "typical_queries": ["查询某产品的交易记录", "统计产品交易费用", "按日汇总交易金额"]
            },
            "dwd_trn_trade_val": {
                "display_name": "估值维度交易表",
                "description": "交易在估值体系中的入账信息，含净价、全价、应计利息、盈亏、摊销等",
                "primary_keys": ["TRADE_ID", "PORT_ID"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID", "AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["TRADE_ID", "PORT_ID", "AST_CD", "NET_PRC", "FULL_PRC", "REAL_PNL", "VAL_STATUS"],
                "typical_queries": ["查询未估值的交易", "统计实现盈亏汇总"]
            },
            "dwd_trn_trade_zg": {
                "display_name": "中证登结算表",
                "description": "通过中证登渠道的债券结算记录，含结算方式、账户及结算状态",
                "primary_keys": ["TRADE_ID"],
                "foreign_keys": {},
                "key_fields": ["TRADE_ID", "SETT_DT", "SETT_AMT", "SETT_TYPE", "SETT_STATUS"],
                "typical_queries": ["查询待结算交易", "按结算方式统计", "筛选DVP结算记录"]
            },
            "dwd_trn_trade_jy": {
                "display_name": "交易所结算表",
                "description": "通过上交所/深交所渠道的结算记录，含佣金、印花税等",
                "primary_keys": ["TRADE_ID"],
                "foreign_keys": {},
                "key_fields": ["TRADE_ID", "SETT_DT", "EXCH", "SETT_AMT", "COMMISSION", "SETT_STATUS"],
                "typical_queries": ["按交易所统计结算量", "查询结算失败的交易"]
            },
            "dwd_trn_order": {
                "display_name": "交易指令表",
                "description": "投资经理下达的交易指令，含审批状态、执行情况、成交均价等",
                "primary_keys": ["ORDER_ID"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID", "AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["ORDER_ID", "PORT_ID", "AST_CD", "BS_DIR", "ORD_QTY", "STATUS", "FILL_QTY", "AVG_PRC"],
                "typical_queries": ["查询待执行指令", "统计指令完成率", "查看某产品的指令历史"]
            },
        }
    },
    # ============================= 销售域 (1表) =============================
    "seller": {
        "display_name": "销售域",
        "description": "管理销售人员基本信息、渠道分类和资质证书",
        "tables": {
            "dwd_seller_info": {
                "display_name": "销售人员表",
                "description": "销售人员的姓名、类型、渠道、所属机构、资格证书、状态等信息",
                "primary_keys": ["SELLER_ID"],
                "foreign_keys": {},
                "key_fields": ["SELLER_ID", "SELLER_NM", "SELLER_TYPE", "CHANNEL_TYPE", "ORG", "STATUS"],
                "typical_queries": ["查询所有在职销售", "按渠道类型统计", "筛选银行渠道销售"]
            },
        }
    },
    # ============================= 客户域 (9表) =============================
    "customer": {
        "display_name": "客户域",
        "description": "管理客户基本信息、持仓、交易账户、申购赎回、分红及流水等9张表",
        "tables": {
            "dwd_cust_info": {
                "display_name": "客户基础信息表",
                "description": "个人/机构客户的身份信息、联系方式、风险等级、销售归属等",
                "primary_keys": ["CUSTOMER_ID"],
                "foreign_keys": {"SELLER_ID": "dwd_seller_info.SELLER_ID"},
                "key_fields": ["CUSTOMER_ID", "CUST_NM", "CUST_TYPE", "RISK_LVL", "CHANNEL", "SELLER_ID"],
                "typical_queries": ["查询所有机构客户", "按风险等级统计客户分布", "查询某销售名下客户"]
            },
            "dwd_cust_make_pstn_info": {
                "display_name": "客户持仓表",
                "description": "客户在各产品中的持仓份额、金额、成本及浮动盈亏",
                "primary_keys": ["CUSTOMER_ID", "PORT_ID", "BIZ_DT"],
                "foreign_keys": {"CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID", "PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["CUSTOMER_ID", "PORT_ID", "BIZ_DT", "HLD_SHR", "HLD_AMT", "UNREAL_PNL"],
                "typical_queries": ["查询某客户的全部持仓", "统计某产品的客户持仓分布"]
            },
            "dwd_cust_trans_acct_info": {
                "display_name": "客户交易账户表",
                "description": "客户用于申赎的银行/证券交易账户信息",
                "primary_keys": ["CUSTOMER_ID", "ACCT_NO"],
                "foreign_keys": {"CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID"},
                "key_fields": ["CUSTOMER_ID", "ACCT_NO", "ACCT_TYPE", "BANK", "STATUS"],
                "typical_queries": ["查询某客户绑定的银行卡", "统计各银行开户数量"]
            },
            "dwd_cust_trans_apply_info_s5": {
                "display_name": "申请单(直销)表",
                "description": "通过直销渠道提交的申购/赎回/分红申请单",
                "primary_keys": ["APPLY_NO"],
                "foreign_keys": {"CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID", "PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["APPLY_NO", "CUSTOMER_ID", "PORT_ID", "TRADE_DT", "TRD_TYPE", "AMT", "STATUS"],
                "typical_queries": ["查询待确认的直销申请", "统计直销渠道申购总额"]
            },
            "dwd_cust_trans_apply_info_ta": {
                "display_name": "申请单(TA)表",
                "description": "通过TA系统提交的申购/赎回/分红申请单",
                "primary_keys": ["APPLY_NO"],
                "foreign_keys": {"CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID", "PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["APPLY_NO", "CUSTOMER_ID", "PORT_ID", "TRADE_DT", "TRD_TYPE", "AMT", "STATUS"],
                "typical_queries": ["查询TA渠道申请单", "按交易类型统计TA申请量"]
            },
            "dwd_cust_trans_apply_info_yh": {
                "display_name": "申请单(银行)表",
                "description": "通过银行代销渠道提交的申购/赎回/分红申请单",
                "primary_keys": ["APPLY_NO"],
                "foreign_keys": {"CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID", "PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["APPLY_NO", "CUSTOMER_ID", "PORT_ID", "TRADE_DT", "TRD_TYPE", "AMT", "STATUS"],
                "typical_queries": ["查询银行渠道赎回申请", "统计银行渠道交易金额"]
            },
            "dwd_cust_trans_cfm_info": {
                "display_name": "确认信息表",
                "description": "申请单的确认结果，含确认金额、份额、净值、费用等",
                "primary_keys": ["CFM_NO"],
                "foreign_keys": {"CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID", "PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["CFM_NO", "APPLY_NO", "CUSTOMER_ID", "CFM_DT", "CFM_AMT", "CFM_SHR", "STATUS"],
                "typical_queries": ["查询某申请单的确认结果", "统计确认失败的记录"]
            },
            "dwd_cust_trans_divd_info": {
                "display_name": "客户分红表",
                "description": "客户获得的产品分红明细，含每份分红、分红方式、税额等",
                "primary_keys": ["CUSTOMER_ID", "PORT_ID", "DIV_DT"],
                "foreign_keys": {"CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID", "PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["CUSTOMER_ID", "PORT_ID", "DIV_DT", "DIV_PER_SHR", "DIV_AMT", "DIV_TYPE"],
                "typical_queries": ["查询某客户的分红历史", "统计某产品的分红总额"]
            },
            "dwd_cust_trans_srl_info": {
                "display_name": "客户流水表",
                "description": "客户资金变动的完整流水记录，含变动前后余额",
                "primary_keys": ["SRL_NO"],
                "foreign_keys": {"CUSTOMER_ID": "dwd_cust_info.CUSTOMER_ID", "PORT_ID": "dwd_ptl_info.PORT_ID"},
                "key_fields": ["SRL_NO", "CUSTOMER_ID", "PORT_ID", "BIZ_DT", "BIZ_TYPE", "AMT"],
                "typical_queries": ["查询某客户资金流水", "按业务类型汇总流水金额"]
            },
        }
    },
    # ============================= 风险域 (5表) =============================
    "risk": {
        "display_name": "风险域",
        "description": "管理舆情监控、信用风险评估、授信协议和关联关系等5张表",
        "tables": {
            "dwd_rsk_sentiment": {
                "display_name": "舆情表",
                "description": "针对主体/资产/产品的舆情监控数据，含情绪分析评分",
                "primary_keys": ["SENT_ID"],
                "foreign_keys": {},
                "key_fields": ["SENT_ID", "TARGET_TYPE", "TARGET_CD", "PUB_DT", "TITLE", "SENT_TYPE", "SCORE"],
                "typical_queries": ["查询某主体的负面舆情", "筛选最近一周的舆情", "统计各类情绪分布"]
            },
            "dwd_rsk_credit": {
                "display_name": "主体信用风险表",
                "description": "发行人的内外部评级、违约概率PD、违约损失率LGD、预期损失EL等",
                "primary_keys": ["ISR_ID", "BIZ_DT"],
                "foreign_keys": {"ISR_ID": "dwd_isr_institution.ISR_ID"},
                "key_fields": ["ISR_ID", "BIZ_DT", "INTERNAL_RATING", "EXT_RATING", "PD_1Y", "LGD", "EXPECTED_LOSS"],
                "typical_queries": ["查询高违约概率主体", "对比内外部评级差异", "统计观察名单主体"]
            },
            "dwd_rsk_credit_position": {
                "display_name": "信用风险敞口表",
                "description": "各组合持仓的信用风险敞口，含评级、久期、VaR和限额状态",
                "primary_keys": ["PORT_ID", "AST_CD", "BIZ_DT"],
                "foreign_keys": {"PORT_ID": "dwd_ptl_info.PORT_ID", "AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["PORT_ID", "AST_CD", "BIZ_DT", "EXPOSURE", "RATING", "VAR_99", "LIMIT_FLAG"],
                "typical_queries": ["查询突破限额的敞口", "按评级汇总风险敞口", "统计某产品VaR"]
            },
            "dwd_crdt_agme_info": {
                "display_name": "授信协议表",
                "description": "与交易对手签订的授信协议，含额度、已用额度、剩余额度等",
                "primary_keys": ["AGME_NO"],
                "foreign_keys": {"CNTP_ID": "dwd_isr_trd_cntp.CNTP_ID"},
                "key_fields": ["AGME_NO", "CNTP_ID", "AGME_TYPE", "LIMIT_AMT", "USED_AMT", "REMAIN_AMT"],
                "typical_queries": ["查询额度即将用尽的协议", "按协议类型统计总额度", "查询某对手的授信额度"]
            },
            "dwd_crdt_main_rela_rela_info": {
                "display_name": "主体关联关系表",
                "description": "发行人之间的关联关系(同业/母子/承销等)及持股比例",
                "primary_keys": ["SRC_ISR_ID", "TGT_ISR_ID", "REL_TYPE"],
                "foreign_keys": {"SRC_ISR_ID": "dwd_isr_institution.ISR_ID", "TGT_ISR_ID": "dwd_isr_institution.ISR_ID"},
                "key_fields": ["SRC_ISR_ID", "TGT_ISR_ID", "REL_TYPE", "SHARE_RATIO"],
                "typical_queries": ["查询某主体的关联方", "统计母子公司关系", "获取关联关系网络图数据"]
            },
        }
    },
    # ============================= 行情域 (25表) =============================
    "market": {
        "display_name": "行情域",
        "description": "管理债券/股票/基金/指数/利率/汇率/曲线等市场行情数据，共25张表",
        "tables": {
            "dwd_mkt_bond": {
                "display_name": "债券行情表",
                "description": "债券逐日OHLC行情、成交量、到期收益率及涨跌",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BIZ_DT", "CLOSE_PRC", "VOL", "AMT", "YTM", "CHG_BP"],
                "typical_queries": ["查询某债券最新行情", "获取债券价格走势", "筛选成交活跃的债券"]
            },
            "dwd_mkt_bond_amount": {
                "display_name": "债券存量表",
                "description": "债券发行规模、当前存量规模、已偿还金额的逐日数据",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BIZ_DT", "ISSUE_AMT", "OUTSTANDING_AMT", "REPAID_AMT"],
                "typical_queries": ["查询某债券存量规模", "统计存量规模最大的债券"]
            },
            "dwd_mkt_bond_creditrating": {
                "display_name": "债项评级表",
                "description": "债券的债项评级和发行人评级数据，含评级机构和展望",
                "primary_keys": ["AST_CD", "RATING_DT", "AGENCY"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "RATING_DT", "AGENCY", "BOND_RATING", "ISSUER_RATING", "OUTLOOK"],
                "typical_queries": ["查询某债券最新评级", "筛选被下调评级的债券"]
            },
            "dwd_mkt_bond_duration": {
                "display_name": "久期凸性表",
                "description": "债券的修正久期、麦考利久期、凸性及关键利率久期",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BIZ_DT", "MOD_DURATION", "MAC_DURATION", "CONVEXITY"],
                "typical_queries": ["查询组合持仓的久期分布", "筛选久期超过5年的债券"]
            },
            "dwd_mkt_bond_ecl": {
                "display_name": "预期信用损失表",
                "description": "债券的IFRS9预期信用损失(ECL)计量数据，含阶段、PD、LGD、EAD",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BIZ_DT", "STAGE", "PD_12M", "LGD", "EAD", "ECL_AMT"],
                "typical_queries": ["查询阶段二/三资产", "统计ECL总额", "筛选PD超过阈值的债券"]
            },
            "dwd_mkt_bond_market": {
                "display_name": "债券逐日成交表",
                "description": "债券市场逐日成交统计，含成交量、成交额、加权均价和成交笔数",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {"AST_CD": "dwd_ast_info.AST_CD"},
                "key_fields": ["AST_CD", "BIZ_DT", "VOL", "AMT", "AVG_PRC", "AVG_YTM"],
                "typical_queries": ["查询某债券市场成交情况", "统计全市场日成交额"]
            },
            "dwd_mkt_calendar": {
                "display_name": "交易日历表",
                "description": "银行间/上交所/深交所各市场的交易日历",
                "primary_keys": ["CAL_DT", "CAL_TYPE"],
                "foreign_keys": {},
                "key_fields": ["CAL_DT", "CAL_TYPE", "IS_TRADE", "WEEK_DAY"],
                "typical_queries": ["判断某日是否为交易日", "查询下一个交易日"]
            },
            "dwd_mkt_date": {
                "display_name": "日期维度表",
                "description": "日期的年/季/月/周等维度属性及月末/季末/年末标识",
                "primary_keys": ["DT"],
                "foreign_keys": {},
                "key_fields": ["DT", "YEAR", "QUARTER", "MONTH", "IS_MONTH_END", "IS_QUARTER_END"],
                "typical_queries": ["查询某月的所有月末日期", "获取某季度的交易日列表"]
            },
            "dwd_mkt_curve": {
                "display_name": "收益率曲线主数据表",
                "description": "收益率曲线的定义信息，含曲线名称、币种、来源和类型",
                "primary_keys": ["CURVE_ID"],
                "foreign_keys": {},
                "key_fields": ["CURVE_ID", "CURVE_NM", "CCY", "SOURCE", "CURVE_TYPE"],
                "typical_queries": ["查询所有可用曲线", "按类型筛选曲线"]
            },
            "dwd_mkt_curve_quote": {
                "display_name": "曲线节点报价表",
                "description": "收益率曲线各期限节点的逐日收益率及变动",
                "primary_keys": ["CURVE_ID", "BIZ_DT", "TENOR"],
                "foreign_keys": {"CURVE_ID": "dwd_mkt_curve.CURVE_ID"},
                "key_fields": ["CURVE_ID", "BIZ_DT", "TENOR", "YIELD", "CHG_BP"],
                "typical_queries": ["获取国债收益率曲线", "对比两日曲线变动", "查询10年期收益率历史"]
            },
            "dwd_mkt_exrate": {
                "display_name": "汇率表",
                "description": "主要币种对的逐日中间价、买入价、卖出价",
                "primary_keys": ["CCY_PAIR", "BIZ_DT"],
                "foreign_keys": {},
                "key_fields": ["CCY_PAIR", "BIZ_DT", "MID", "BID", "ASK"],
                "typical_queries": ["查询最新美元兑人民币汇率", "获取汇率历史走势"]
            },
            "dwd_mkt_fund": {
                "display_name": "基金主数据表",
                "description": "公募/私募基金的基本信息，含类型、管理人、托管行、规模等",
                "primary_keys": ["AST_CD"],
                "foreign_keys": {},
                "key_fields": ["AST_CD", "FUND_NM", "FUND_TYPE", "MGR_INST", "AUM", "ESTAB_DT"],
                "typical_queries": ["按类型查询基金列表", "筛选规模超过100亿的基金"]
            },
            "dwd_mkt_fund_allocation": {
                "display_name": "基金资产配置表",
                "description": "基金定期报告中披露的大类资产配置比例",
                "primary_keys": ["AST_CD", "RPT_DT", "AST_CLASS"],
                "foreign_keys": {},
                "key_fields": ["AST_CD", "RPT_DT", "AST_CLASS", "MKT_VAL", "RATIO"],
                "typical_queries": ["查询某基金最新资产配置", "对比多期配置变化"]
            },
            "dwd_mkt_fund_derive": {
                "display_name": "基金衍生指标表",
                "description": "基金的夏普比率、最大回撤、波动率、Beta、Alpha等风险收益指标",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {},
                "key_fields": ["AST_CD", "BIZ_DT", "SHARPE_1Y", "MAX_DD_1Y", "VOL_1Y", "BETA_1Y", "ALPHA_1Y"],
                "typical_queries": ["查询夏普比率最高的基金", "筛选最大回撤小于5%的基金"]
            },
            "dwd_mkt_fund_market": {
                "display_name": "基金行情(净值)表",
                "description": "基金每日单位净值、累计净值、日收益率及成交数据",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {},
                "key_fields": ["AST_CD", "BIZ_DT", "UNIT_NAV", "ACC_NAV", "DAILY_RTN"],
                "typical_queries": ["查询某基金净值走势", "对比多只基金日收益率"]
            },
            "dwd_mkt_fund_structure": {
                "display_name": "基金份额结构表",
                "description": "基金定期报告中的持有人结构（机构/个人/内部）占比",
                "primary_keys": ["AST_CD", "RPT_DT", "HOLDER_TYPE"],
                "foreign_keys": {},
                "key_fields": ["AST_CD", "RPT_DT", "HOLDER_TYPE", "TOT_SHR", "RATIO"],
                "typical_queries": ["查询某基金机构持有占比", "筛选机构占比超90%的基金"]
            },
            "dwd_mkt_fund_suspension": {
                "display_name": "基金停牌表",
                "description": "基金暂停申赎的时间段及原因",
                "primary_keys": ["AST_CD", "SUS_DT"],
                "foreign_keys": {},
                "key_fields": ["AST_CD", "SUS_DT", "RES_DT", "SUS_TYPE", "REASON"],
                "typical_queries": ["查询当前停牌的基金", "获取某基金停牌历史"]
            },
            "dwd_mkt_index": {
                "display_name": "指数主数据表",
                "description": "各类指数的基本信息，含发布机构、基期、指数类型等",
                "primary_keys": ["INDEX_CD"],
                "foreign_keys": {},
                "key_fields": ["INDEX_CD", "INDEX_NM", "PUBLISHER", "INDEX_TYPE", "BASE_DT"],
                "typical_queries": ["查询所有债券指数", "按发布机构筛选指数"]
            },
            "dwd_mkt_index_member": {
                "display_name": "指数成分表",
                "description": "指数的成分券/股及其权重、调入调出日期",
                "primary_keys": ["INDEX_CD", "AST_CD", "BIZ_DT"],
                "foreign_keys": {},
                "key_fields": ["INDEX_CD", "AST_CD", "BIZ_DT", "WEIGHT", "IN_DT", "OUT_DT"],
                "typical_queries": ["查询某指数的成分列表", "获取某资产在哪些指数中"]
            },
            "dwd_mkt_index_quote": {
                "display_name": "指数行情表",
                "description": "指数的逐日行情数据，含开高低收、收益率等",
                "primary_keys": ["INDEX_CD", "BIZ_DT"],
                "foreign_keys": {},
                "key_fields": ["INDEX_CD", "BIZ_DT", "CLOSE_VAL", "DAILY_RTN", "YTD_RTN", "VOL", "AMT"],
                "typical_queries": ["查询某指数最新行情", "获取指数走势图数据", "对比多指数表现"]
            },
            "dwd_mkt_rate": {
                "display_name": "利率主数据表",
                "description": "各类基准利率的定义信息，含名称、来源、币种",
                "primary_keys": ["RATE_CD"],
                "foreign_keys": {},
                "key_fields": ["RATE_CD", "RATE_NM", "SOURCE", "CCY"],
                "typical_queries": ["查询所有可用利率", "筛选人民币利率"]
            },
            "dwd_mkt_rate_quote": {
                "display_name": "利率报价表",
                "description": "各基准利率的逐日报价值及变动",
                "primary_keys": ["RATE_CD", "BIZ_DT"],
                "foreign_keys": {"RATE_CD": "dwd_mkt_rate.RATE_CD"},
                "key_fields": ["RATE_CD", "BIZ_DT", "RATE_VAL", "CHG_BP"],
                "typical_queries": ["查询DR007最新报价", "获取Shibor历史走势"]
            },
            "dwd_mkt_rating": {
                "display_name": "评级动作表",
                "description": "评级机构对发行人的评级调整动作记录（升级/降级/维持/列入观察）",
                "primary_keys": ["ISR_ID", "RATING_DT", "AGENCY"],
                "foreign_keys": {"ISR_ID": "dwd_isr_institution.ISR_ID"},
                "key_fields": ["ISR_ID", "RATING_DT", "AGENCY", "RATING", "PREV_RATING", "ACTION", "OUTLOOK"],
                "typical_queries": ["查询近期被降级的主体", "统计某机构的评级变动历史"]
            },
            "dwd_mkt_stock": {
                "display_name": "股票主数据表",
                "description": "A股/港股的基本信息，含交易所、行业、市值等",
                "primary_keys": ["AST_CD"],
                "foreign_keys": {"ISR_ID": "dwd_isr_institution.ISR_ID"},
                "key_fields": ["AST_CD", "STOCK_NM", "EXCH", "INDUSTRY_CD", "TOT_CAP", "FREE_CAP"],
                "typical_queries": ["查询所有上交所股票", "按行业筛选股票", "市值排名前20"]
            },
            "dwd_mkt_stock_yield": {
                "display_name": "股票收益率表",
                "description": "股票逐日OHLC行情、多周期收益率及PE/PB估值指标",
                "primary_keys": ["AST_CD", "BIZ_DT"],
                "foreign_keys": {},
                "key_fields": ["AST_CD", "BIZ_DT", "CLOSE_PRC", "DAILY_RTN", "VOL", "AMT", "PE_TTM", "PB_LF"],
                "typical_queries": ["查询某股票行情走势", "筛选低估值股票", "按日收益率排序"]
            },
        }
    },
    # ============================= 通用数据接入域 (6表) =============================
    "data_hub": {
        "display_name": "通用数据接入域",
        "description": "管理通过通用数据接入中心（Data Hub）从上游API拉取并落地的业务数据，含3张业务记录表和3张导入批次表，共6张表",
        "tables": {
            "subject_risk_records": {
                "display_name": "主体观点风险记录表",
                "description": "记录上游 adm_subject_opinion_risk_stats 接口的风险舆情数据，含主体名称、风险等级（高/黄/低）、信号描述、规则分类（大/中/小类）、行业、省份、企业性质、白名单标识等，按 risk_id upsert",
                "primary_keys": ["risk_id"],
                "foreign_keys": {"subject_name": "dwd_isr_institution.ISR_NM"},
                "key_fields": ["risk_id", "biz_date", "subject_name", "subject_type", "risk_signal_level", "signal_dascribe", "rule_large", "rule_medium", "rule_small", "enterprise_nature", "industry_classification_gb", "affiliated_province", "affiliated_city", "is_approved_investment_quota_client", "is_partner_access_client", "is_parent_bank_veto_client", "unified_social_credit_code"],
                "typical_queries": ["查询高风险等级的主体", "按省份统计风险分布", "筛选某行业的企业风险信号", "查询近期新增的风险记录", "统计各风险等级数量分布", "查询某主体名称的历史风险事件"]
            },
            "subject_risk_import_batches": {
                "display_name": "主体风险导入批次表",
                "description": "记录每次从上游拉取主体风险数据的导入批次信息，含批次ID、状态、参数、耗时、上游响应、插入/更新/跳过/失败计数等",
                "primary_keys": ["batch_id"],
                "foreign_keys": {},
                "key_fields": ["batch_id", "status", "started_at", "finished_at", "duration_ms", "total_returned", "inserted", "updated", "failed"],
                "typical_queries": ["查询最近的导入批次", "统计导入成功率", "查询某批次的详情"]
            },
            "zysc_ptl_info_records": {
                "display_name": "产品信息记录表",
                "description": "从上游 ZYSC_DWD_PTL_INFO 拉取的理财产品/资管产品主数据，含产品代码、简称、名称、产品性质、类型、系列、风险等级、估值方法、管理人、托管人、投资经理、币种、基准信息、策略类型、开放频率等52个字段，按产品代码 upsert",
                "primary_keys": ["产品代码"],
                "foreign_keys": {"产品代码": "dwd_ptl_info.PORT_ID", "管理人": "dwd_isr_institution.ISR_NM"},
                "key_fields": ["产品代码", "产品简称", "产品名称", "产品性质", "产品类型", "产品系列", "风险等级", "估值方法", "管理人", "托管人", "投资经理", "币种", "策略类型", "产品起息日", "产品到期日", "市场基准", "合约基准"],
                "typical_queries": ["查询所有理财产品", "按风险等级筛选产品", "按管理人统计产品数量", "查询某产品系列的子产品", "筛选即将到期的产品", "按估值方法分类统计", "对比不同策略类型的产品数量"]
            },
            "zysc_ptl_info_import_batches": {
                "display_name": "产品信息导入批次表",
                "description": "记录每次从上游拉取产品信息的导入批次信息",
                "primary_keys": ["batch_id"],
                "foreign_keys": {},
                "key_fields": ["batch_id", "status", "started_at", "finished_at", "duration_ms", "total_returned", "inserted", "updated", "failed"],
                "typical_queries": ["查询产品信息最近导入时间", "统计导入成功批次"]
            },
            "zysc_ptl_holder_records": {
                "display_name": "产品持有人汇总记录表",
                "description": "从上游 ZYSC_DWD_PTL_HOLDER_SUMMARY 拉取的产品持有人结构数据，含产品代码、生效日期、前十份额/金额、个人份额/金额、机构份额/金额、数据来源、导入方法等，按复合键（产品代码+生效日期）upsert",
                "primary_keys": ["_holder_row_uid"],
                "foreign_keys": {"产品代码": "zysc_ptl_info_records.产品代码"},
                "key_fields": ["_holder_row_uid", "产品代码", "生效日期", "前十份额", "前十金额", "个人份额", "个人金额", "机构份额", "机构金额", "数据来源", "导入方法"],
                "typical_queries": ["查询某产品的持有人结构", "统计机构占比最高的产品", "对比两期持有人变化", "按数据来源分组统计", "查询机构份额超过个人份额的产品"]
            },
            "zysc_ptl_holder_import_batches": {
                "display_name": "产品持有人导入批次表",
                "description": "记录每次从上游拉取产品持有人数据的导入批次信息",
                "primary_keys": ["batch_id"],
                "foreign_keys": {},
                "key_fields": ["batch_id", "status", "started_at", "finished_at", "duration_ms", "total_returned", "inserted", "updated", "failed"],
                "typical_queries": ["查询持有人数据最近导入时间", "统计导入成功率"]
            },
        }
    },
}


class CollectionNotFoundError(Exception):
    """集合不存在或未授权查询"""
    pass


class CollectionRegistry:
    """MongoDB 集合元数据注册中心"""

    REGISTRY_COLLECTION = "_collection_registry"
    # 跳过的系统集合前缀
    SKIP_PREFIXES = ("_", "system.")
    # 采样数量
    SAMPLE_SIZE = 100

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    async def _seed_domain_metadata(self) -> int:
        """预注册所有业务域表的元数据，启动时调用。

        遍历 DOMAIN_METADATA，对每张表执行 upsert：
        - 若已存在则合并更新（不覆盖手动标注的 sensitive_fields 等）
        - 若不存在则插入完整元数据文档
        返回预注册的表数量。
        """
        registry_col = self.db[self.REGISTRY_COLLECTION]

        seeded_count = 0
        for domain_key, domain_info in DOMAIN_METADATA.items():
            for table_name, table_meta in domain_info["tables"].items():
                doc = {
                    "collection_name": table_name,
                    "display_name": table_meta["display_name"],
                    "description": table_meta["description"],
                    "domain": domain_key,
                    "is_whitelisted": True,
                    "primary_keys": table_meta.get("primary_keys", []),
                    "foreign_keys": table_meta.get("foreign_keys", {}),
                    "key_fields": table_meta.get("key_fields", []),
                    "typical_queries": table_meta.get("typical_queries", []),
                }

                # upsert: 若已存在则合并更新（不覆盖手动标注的 sensitive_fields 等）
                await registry_col.update_one(
                    {"collection_name": table_name},
                    {
                        "$set": doc,
                        "$setOnInsert": {"sensitive_fields": [], "last_scanned": None},
                    },
                    upsert=True,
                )
                seeded_count += 1

        logger.info(
            "domain_metadata_seeded",
            extra={"seeded_count": seeded_count},
        )
        return seeded_count

    async def refresh(self) -> int:
        """扫描 MongoDB 所有集合，自动推断 Schema。

        - 先执行域元数据预注册，确保业务表有基础描述
        - 跳过以 _ 或 system. 开头的集合
        - 对每个集合采样 SAMPLE_SIZE 条文档推断字段类型
        - 与已有 registry 合并（保留手动标注的 display_name/description/domain/sensitive_fields）
        - 返回发现的集合数量
        """
        # 预注册业务域元数据
        await self._seed_domain_metadata()

        collection_names: list[str] = await self.db.list_collection_names()
        business_collections = [
            name for name in collection_names
            if not any(name.startswith(prefix) for prefix in self.SKIP_PREFIXES)
        ]

        registry_col = self.db[self.REGISTRY_COLLECTION]
        discovered_count = 0

        for col_name in business_collections:
            try:
                inferred = await self._sample_and_infer(col_name)

                # 查找已有记录，保留手动标注
                existing = await registry_col.find_one({"collection_name": col_name})

                if existing:
                    # 保留手动标注字段
                    preserved_keys = ("display_name", "description", "domain",
                                      "sensitive_fields", "is_whitelisted")
                    for key in preserved_keys:
                        if existing.get(key):
                            inferred[key] = existing[key]

                    # 保留字段级 description
                    existing_field_map = {
                        f["name"]: f.get("description", "")
                        for f in existing.get("fields", [])
                    }
                    for field in inferred.get("fields", []):
                        if field["name"] in existing_field_map and existing_field_map[field["name"]]:
                            field["description"] = existing_field_map[field["name"]]

                    await registry_col.replace_one(
                        {"collection_name": col_name}, inferred
                    )
                else:
                    await registry_col.insert_one(inferred)

                discovered_count += 1
            except Exception as e:
                logger.warning(
                    "collection_scan_failed",
                    extra={"collection": col_name, "error": str(e)},
                )

        logger.info(
            "registry_refresh_complete",
            extra={"discovered": discovered_count, "total_scanned": len(business_collections)},
        )
        return discovered_count

    async def list_collections(self, domain: str | None = None) -> list[dict]:
        """返回所有可查询集合的摘要。

        仅返回 is_whitelisted=True 的集合。
        每条包含: collection_name, display_name, description, domain, record_count, field_count
        可按 domain 过滤。
        """
        registry_col = self.db[self.REGISTRY_COLLECTION]
        query: dict[str, Any] = {"is_whitelisted": True}
        if domain:
            query["domain"] = domain

        cursor = registry_col.find(query)
        results: list[dict] = []

        async for doc in cursor:
            results.append({
                "collection_name": doc["collection_name"],
                "display_name": doc.get("display_name", ""),
                "description": doc.get("description", ""),
                "domain": doc.get("domain", ""),
                "record_count": doc.get("record_count", 0),
                "field_count": len(doc.get("fields", [])),
            })

        return results

    async def get_schema(self, collection: str) -> dict:
        """返回指定集合的完整 Schema。

        包含: collection_name, display_name, description, fields, indexes, record_count
        如果集合不在 registry 中或未白名单，抛出 CollectionNotFoundError。
        """
        registry_col = self.db[self.REGISTRY_COLLECTION]
        doc = await registry_col.find_one({"collection_name": collection})

        if not doc:
            raise CollectionNotFoundError(f"集合 '{collection}' 未注册")
        if not doc.get("is_whitelisted", True):
            raise CollectionNotFoundError(f"集合 '{collection}' 未授权查询")

        return {
            "collection_name": doc["collection_name"],
            "display_name": doc.get("display_name", ""),
            "description": doc.get("description", ""),
            "fields": doc.get("fields", []),
            "indexes": doc.get("indexes", []),
            "record_count": doc.get("record_count", 0),
        }

    async def annotate(self, collection: str, updates: dict) -> None:
        """手动标注集合元数据。

        可更新: display_name, description, domain, sensitive_fields, is_whitelisted,
                以及 fields 中单个字段的 description。
        """
        registry_col = self.db[self.REGISTRY_COLLECTION]
        doc = await registry_col.find_one({"collection_name": collection})

        if not doc:
            raise CollectionNotFoundError(f"集合 '{collection}' 未注册")

        allowed_top_keys = {"display_name", "description", "domain",
                            "sensitive_fields", "is_whitelisted"}
        set_ops: dict[str, Any] = {}

        for key, value in updates.items():
            if key in allowed_top_keys:
                set_ops[key] = value

        # 处理字段级 description 更新
        field_updates = updates.get("fields", {})
        if isinstance(field_updates, dict):
            for field_name, field_desc in field_updates.items():
                # 更新 fields 数组中对应字段的 description
                existing_fields = doc.get("fields", [])
                for i, f in enumerate(existing_fields):
                    if f["name"] == field_name:
                        set_ops[f"fields.{i}.description"] = field_desc
                        break

        if set_ops:
            await registry_col.update_one(
                {"collection_name": collection},
                {"$set": set_ops},
            )
            logger.info(
                "collection_annotated",
                extra={"collection": collection, "updated_keys": list(set_ops.keys())},
            )

    def _infer_field_type(self, value: object) -> str:
        """推断 MongoDB 值的类型标签。

        ObjectId → "id", datetime → "datetime", int → "int", float → "float",
        str → "string", bool → "bool", list → "array", dict → "object", None → "null"
        """
        if isinstance(value, ObjectId):
            return "id"
        if isinstance(value, datetime):
            return "datetime"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "null"

    async def _sample_and_infer(self, collection_name: str) -> dict:
        """采样并推断单个集合的 Schema。

        采样 SAMPLE_SIZE 条文档，统计每个字段的出现频率和类型，
        选取出现频率最高的类型作为字段类型，取第一个非空值作为 sample。
        """
        col = self.db[collection_name]

        # 获取记录数
        record_count: int = await col.estimated_document_count()

        # 采样文档
        pipeline = [{"$sample": {"size": self.SAMPLE_SIZE}}]
        docs: list[dict] = []
        async for doc in col.aggregate(pipeline):
            docs.append(doc)

        # 统计字段信息
        field_stats: dict[str, dict[str, Any]] = {}
        # field_stats[field_name] = {"type_counts": {type: count}, "sample": value, "count": N}

        for doc in docs:
            for key, value in doc.items():
                if key == "_id":
                    continue
                if key not in field_stats:
                    field_stats[key] = {"type_counts": {}, "sample": None, "count": 0}

                stats = field_stats[key]
                stats["count"] += 1
                field_type = self._infer_field_type(value)
                stats["type_counts"][field_type] = stats["type_counts"].get(field_type, 0) + 1

                # 取第一个非空值作为 sample
                if stats["sample"] is None and value is not None:
                    if isinstance(value, (ObjectId, datetime)):
                        stats["sample"] = str(value)
                    elif isinstance(value, (str, int, float, bool)):
                        stats["sample"] = value
                    elif isinstance(value, list):
                        stats["sample"] = str(value)[:100]
                    elif isinstance(value, dict):
                        stats["sample"] = str(value)[:100]

        # 构建 fields 列表
        fields: list[dict[str, Any]] = []
        for field_name, stats in field_stats.items():
            # 选取出现频率最高的类型
            type_counts = stats["type_counts"]
            dominant_type = max(type_counts, key=type_counts.get) if type_counts else "null"
            fields.append({
                "name": field_name,
                "type": dominant_type,
                "description": "",
                "sample": stats["sample"],
            })

        # 获取索引信息
        indexes: list[str] = []
        try:
            index_info = await col.index_information()
            for idx_name, idx_detail in index_info.items():
                if idx_name == "_id_":
                    continue
                for key_tuple in idx_detail.get("key", []):
                    if key_tuple[0] not in indexes:
                        indexes.append(key_tuple[0])
        except Exception as e:
            logger.warning(
                "index_fetch_failed",
                extra={"collection": collection_name, "error": str(e)},
            )

        return {
            "collection_name": collection_name,
            "display_name": "",
            "description": "",
            "domain": "",
            "record_count": record_count,
            "fields": fields,
            "indexes": indexes,
            "is_whitelisted": True,
            "sensitive_fields": [],
            "last_scanned": datetime.now(timezone.utc).isoformat(),
        }
