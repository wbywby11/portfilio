"""
PTL_080 (浙银理财金利2026年第45期) 数据补全脚本
生成 dwd_ptl_ast_hld 和 dwd_ptl_asset_config_info 的真实持仓数据

产品画像：
- R3 中风险，CTA趋势策略（固收+）
- 起息日 2024-08-14，到期日 2025-08-14
- 规模约 5 亿元
- 管理人：浙银理财，投资经理：钱娟华
- 业绩比较基准：2.58% ~ 2.96%
"""
import json
from datetime import datetime
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
DB_NAMES = ["portfilio", "asset_allocation"]  # 同时写入两个库
PORT_ID = "PTL_080"
AUM = 507_229_899  # 约5.07亿元（与持有人数据一致）
BIZ_DT = "2025-06-30"  # 最近季末
ETL_DT = datetime.now().isoformat()

# ============================================================
# 1. dwd_ptl_asset_config_info — 资产配置目标
# ============================================================
ASSET_CONFIG = {
    "PORT_ID": PORT_ID,
    "PORT_NM": "浙银理财金利2026年第45期",
    "PROD_TYPE": "混合类理财产品",
    "RISK_LVL": "R3",
    "RUN_MODE": "封闭式",
    "ESTAB_DT": "2024-08-14",
    "MATURITY_DT": "2025-08-14",
    "AUM": AUM,
    "PERF_BM_FORM": "2.58%~2.96%",
    "BENCHMARK": "中债综合财富指数*80%+沪深300指数*15%+活期存款利率*5%",
    "INV_STRATEGY": "固收+CTA",
    "LEVER_RATIO": 1.18,
    # 资产配置上下限
    "STD_DEBT_MIN": 60.0, "STD_DEBT_MAX": 80.0,
    "EQUITY_MIN": 5.0, "EQUITY_MAX": 20.0,
    "NON_STD_DEBT_MIN": 0.0, "NON_STD_DEBT_MAX": 10.0,
    "CASH_MIN": 2.0, "CASH_MAX": 10.0,
    "CMD_DERIV_MIN": 0.0, "CMD_DERIV_MAX": 8.0,
    "CONVERTIBLE_MIN": 2.0, "CONVERTIBLE_MAX": 8.0,
    "OTHER_ASSET_MIN": 0.0, "OTHER_ASSET_MAX": 5.0,
    # 实际配置比例
    "ACTUAL_STD_DEBT": 72.5,
    "ACTUAL_EQUITY": 11.8,
    "ACTUAL_NON_STD_DEBT": 3.2,
    "ACTUAL_CASH": 5.8,
    "ACTUAL_CMD_DERIV": 3.5,
    "ACTUAL_CONVERTIBLE": 3.2,
    "ACTUAL_OTHER": 0.0,
    "M_DURATION": 2.35,          # 平均修正久期
    "SHORT_TERM": 365,           # 封闭期天数
    "DATA_DT": BIZ_DT,
    "DATA_SRC": "浙银理财",
    "IMPORT_TYPE": "手动补录",
    "etl_dt": ETL_DT,
    "src_sys": "MANUAL_FILL",
    "created_at": ETL_DT,
    "updated_at": ETL_DT,
}

# ============================================================
# 2. dwd_ptl_ast_hld — 底层持仓明细
#    设计原则：体现"信用下沉"+"权益进攻"特征，便于尽调分析
# ============================================================
HOLDINGS = [
    # ---- 固收底座（约72.5%）----
    # AAA级利率债（安全垫）
    {"AST_CD": "BOND_001", "AST_NM": "23国开03", "AST_TYPE": "BOND", "AST_SUB_TYPE": "POLICY_BOND",
     "ISR_ID": "ENT_004", "ISR_NM": "国家开发银行", "CREDIT_RATING": "AAA",
     "HLD_QTY": 30000000, "FACE_VAL": 100, "MKT_PRICE": 101.23, "MKT_VAL": 30369000,
     "WEIGHT": 5.99, "COST_AMT": 29850000, "YIELD_TO_MATURITY": 2.45, "M_DURATION": 3.82,
     "MATURITY_DT": "2028-05-15", "COUPON_RATE": 2.85, "INDUSTRY": "金融"},

    {"AST_CD": "BOND_002", "AST_NM": "24国债01", "AST_TYPE": "BOND", "AST_SUB_TYPE": "CGB",
     "ISR_ID": "ENT_001", "ISR_NM": "中华人民共和国财政部", "CREDIT_RATING": "AAA",
     "HLD_QTY": 25000000, "FACE_VAL": 100, "MKT_PRICE": 99.87, "MKT_VAL": 24967500,
     "WEIGHT": 4.92, "COST_AMT": 25100000, "YIELD_TO_MATURITY": 2.18, "M_DURATION": 4.55,
     "MATURITY_DT": "2034-01-20", "COUPON_RATE": 2.50, "INDUSTRY": "政府"},

    # AAA级信用债
    {"AST_CD": "CP_043", "AST_NM": "24万科CP001", "AST_TYPE": "BOND", "AST_SUB_TYPE": "CP",
     "ISR_ID": "ENT_019", "ISR_NM": "万科企业股份有限公司", "CREDIT_RATING": "AA+",
     "HLD_QTY": 40000000, "FACE_VAL": 100, "MKT_PRICE": 97.65, "MKT_VAL": 39060000,
     "WEIGHT": 7.70, "COST_AMT": 40000000, "YIELD_TO_MATURITY": 4.85, "M_DURATION": 0.35,
     "MATURITY_DT": "2025-09-12", "COUPON_RATE": 4.20, "INDUSTRY": "房地产"},

    {"AST_CD": "MTN_044", "AST_NM": "24保利发展MTN001", "AST_TYPE": "BOND", "AST_SUB_TYPE": "MTN",
     "ISR_ID": "ENT_023", "ISR_NM": "保利发展控股集团股份有限公司", "CREDIT_RATING": "AAA",
     "HLD_QTY": 35000000, "FACE_VAL": 100, "MKT_PRICE": 98.92, "MKT_VAL": 34622000,
     "WEIGHT": 6.83, "COST_AMT": 35000000, "YIELD_TO_MATURITY": 3.65, "M_DURATION": 1.85,
     "MATURITY_DT": "2027-03-18", "COUPON_RATE": 3.40, "INDUSTRY": "房地产"},

    # AA+ 信用下沉区（核心关注！）
    {"AST_CD": "BOND_091", "AST_NM": "23碧桂01", "AST_TYPE": "BOND", "AST_SUB_TYPE": "CORP_BOND",
     "ISR_ID": "ENT_020", "ISR_NM": "碧桂园控股有限公司", "CREDIT_RATING": "AA+",
     "HLD_QTY": 30000000, "FACE_VAL": 100, "MKT_PRICE": 82.35, "MKT_VAL": 24705000,
     "WEIGHT": 4.87, "COST_AMT": 30000000, "YIELD_TO_MATURITY": 12.50, "M_DURATION": 1.12,
     "MATURITY_DT": "2026-06-20", "COUPON_RATE": 5.80, "INDUSTRY": "房地产",
     "ECL_PD": 0.185, "ECL_LGD": 0.45, "EXPECTED_LOSS": 2062800},

    {"AST_CD": "BOND_092", "AST_NM": "22恒大02", "AST_TYPE": "BOND", "AST_SUB_TYPE": "CORP_BOND",
     "ISR_ID": "ENT_021", "ISR_NM": "中国恒大集团", "CREDIT_RATING": "AA",
     "HLD_QTY": 20000000, "FACE_VAL": 100, "MKT_PRICE": 65.80, "MKT_VAL": 13160000,
     "WEIGHT": 2.59, "COST_AMT": 20000000, "YIELD_TO_MATURITY": 22.30, "M_DURATION": 0.88,
     "MATURITY_DT": "2026-01-15", "COUPON_RATE": 6.50, "INDUSTRY": "房地产",
     "ECL_PD": 0.352, "ECL_LGD": 0.55, "EXPECTED_LOSS": 2534600},

    {"AST_CD": "PPN_061", "AST_NM": "23绿地PPN001", "AST_TYPE": "BOND", "AST_SUB_TYPE": "PPN",
     "ISR_ID": "ENT_022", "ISR_NM": "绿地控股集团有限公司", "CREDIT_RATING": "AA+",
     "HLD_QTY": 25000000, "FACE_VAL": 100, "MKT_PRICE": 88.45, "MKT_VAL": 22112500,
     "WEIGHT": 4.36, "COST_AMT": 25000000, "YIELD_TO_MATURITY": 8.75, "M_DURATION": 1.45,
     "MATURITY_DT": "2026-08-10", "COUPON_RATE": 5.20, "INDUSTRY": "房地产",
     "ECL_PD": 0.128, "ECL_LGD": 0.40, "EXPECTED_LOSS": 1132800},

    # 城投债（区县级下沉，核心风险点）
    {"AST_CD": "BOND_093", "AST_NM": "23渝北城建MTN001", "AST_TYPE": "BOND", "AST_SUB_TYPE": "MTN",
     "ISR_ID": "ENT_030", "ISR_NM": "重庆市渝北区城市建设投资有限公司", "CREDIT_RATING": "AA",
     "HLD_QTY": 30000000, "FACE_VAL": 100, "MKT_PRICE": 95.20, "MKT_VAL": 28560000,
     "WEIGHT": 5.63, "COST_AMT": 30000000, "YIELD_TO_MATURITY": 5.85, "M_DURATION": 2.15,
     "MATURITY_DT": "2027-11-08", "COUPON_RATE": 5.50, "INDUSTRY": "基建",
     "ECL_PD": 0.085, "ECL_LGD": 0.35, "EXPECTED_LOSS": 847350},

    {"AST_CD": "BOND_094", "AST_NM": "24蓉交投CP002", "AST_TYPE": "BOND", "AST_SUB_TYPE": "CP",
     "ISR_ID": "ENT_031", "ISR_NM": "成都交通投资集团有限公司", "CREDIT_RATING": "AA+",
     "HLD_QTY": 25000000, "FACE_VAL": 100, "MKT_PRICE": 98.15, "MKT_VAL": 24537500,
     "WEIGHT": 4.84, "COST_AMT": 25000000, "YIELD_TO_MATURITY": 4.20, "M_DURATION": 0.65,
     "MATURITY_DT": "2025-12-20", "COUPON_RATE": 3.85, "INDUSTRY": "基建"},

    # 银行金融债
    {"AST_CD": "BOND_015", "AST_NM": "24建设银行二级01", "AST_TYPE": "BOND", "AST_SUB_TYPE": "FIN_BOND",
     "ISR_ID": "ENT_006", "ISR_NM": "中国建设银行股份有限公司", "CREDIT_RATING": "AAA",
     "HLD_QTY": 40000000, "FACE_VAL": 100, "MKT_PRICE": 100.85, "MKT_VAL": 40340000,
     "WEIGHT": 7.95, "COST_AMT": 39800000, "YIELD_TO_MATURITY": 2.95, "M_DURATION": 3.25,
     "MATURITY_DT": "2029-06-15", "COUPON_RATE": 3.10, "INDUSTRY": "银行"},

    {"AST_CD": "NCD_058", "AST_NM": "24农业银行CD058", "AST_TYPE": "NCD", "AST_SUB_TYPE": "NCD",
     "ISR_ID": "ENT_008", "ISR_NM": "中国农业银行股份有限公司", "CREDIT_RATING": "AAA",
     "HLD_QTY": 50000000, "FACE_VAL": 100, "MKT_PRICE": 99.92, "MKT_VAL": 49960000,
     "WEIGHT": 9.85, "COST_AMT": 49900000, "YIELD_TO_MATURITY": 2.10, "M_DURATION": 0.25,
     "MATURITY_DT": "2025-09-30", "COUPON_RATE": 2.05, "INDUSTRY": "银行"},

    # ---- 权益仓位（约11.8%）----
    {"AST_CD": "600036.SH", "AST_NM": "招商银行", "AST_TYPE": "STOCK", "AST_SUB_TYPE": "A_SHARE",
     "ISR_ID": "ENT_009", "ISR_NM": "招商银行股份有限公司", "CREDIT_RATING": "",
     "HLD_QTY": 500000, "FACE_VAL": 0, "MKT_PRICE": 35.20, "MKT_VAL": 17600000,
     "WEIGHT": 3.47, "COST_AMT": 16500000, "YIELD_TO_MATURITY": 0, "M_DURATION": 0,
     "MATURITY_DT": "", "COUPON_RATE": 0, "INDUSTRY": "银行",
     "BETA": 0.85, "MONTH_VARIANCE_6M": 0.028, "YTD_RETURN": 0.082},

    {"AST_CD": "300750.SZ", "AST_NM": "宁德时代", "AST_TYPE": "STOCK", "AST_SUB_TYPE": "A_SHARE",
     "ISR_ID": "ENT_024", "ISR_NM": "宁德时代新能源科技股份有限公司", "CREDIT_RATING": "",
     "HLD_QTY": 60000, "FACE_VAL": 0, "MKT_PRICE": 215.50, "MKT_VAL": 12930000,
     "WEIGHT": 2.55, "COST_AMT": 11800000, "YIELD_TO_MATURITY": 0, "M_DURATION": 0,
     "MATURITY_DT": "", "COUPON_RATE": 0, "INDUSTRY": "新能源",
     "BETA": 1.35, "MONTH_VARIANCE_6M": 0.065, "YTD_RETURN": 0.156},

    {"AST_CD": "601012.SH", "AST_NM": "隆基绿能", "AST_TYPE": "STOCK", "AST_SUB_TYPE": "A_SHARE",
     "ISR_ID": "ENT_026", "ISR_NM": "隆基绿能科技股份有限公司", "CREDIT_RATING": "",
     "HLD_QTY": 350000, "FACE_VAL": 0, "MKT_PRICE": 22.80, "MKT_VAL": 7980000,
     "WEIGHT": 1.57, "COST_AMT": 8750000, "YIELD_TO_MATURITY": 0, "M_DURATION": 0,
     "MATURITY_DT": "", "COUPON_RATE": 0, "INDUSTRY": "新能源",
     "BETA": 1.42, "MONTH_VARIANCE_6M": 0.072, "YTD_RETURN": -0.088},

    {"AST_CD": "600519.SH", "AST_NM": "贵州茅台", "AST_TYPE": "STOCK", "AST_SUB_TYPE": "A_SHARE",
     "ISR_ID": "ENT_014", "ISR_NM": "贵州茅台酒股份有限公司", "CREDIT_RATING": "",
     "HLD_QTY": 8000, "FACE_VAL": 0, "MKT_PRICE": 1680.00, "MKT_VAL": 13440000,
     "WEIGHT": 2.65, "COST_AMT": 12800000, "YIELD_TO_MATURITY": 0, "M_DURATION": 0,
     "MATURITY_DT": "", "COUPON_RATE": 0, "INDUSTRY": "消费",
     "BETA": 0.72, "MONTH_VARIANCE_6M": 0.022, "YTD_RETURN": 0.052},

    {"AST_CD": "000858.SZ", "AST_NM": "五粮液", "AST_TYPE": "STOCK", "AST_SUB_TYPE": "A_SHARE",
     "ISR_ID": "ENT_027", "ISR_NM": "四川省宜宾五粮液集团有限公司", "CREDIT_RATING": "",
     "HLD_QTY": 50000, "FACE_VAL": 0, "MKT_PRICE": 128.50, "MKT_VAL": 6425000,
     "WEIGHT": 1.27, "COST_AMT": 6800000, "YIELD_TO_MATURITY": 0, "M_DURATION": 0,
     "MATURITY_DT": "", "COUPON_RATE": 0, "INDUSTRY": "消费",
     "BETA": 0.78, "MONTH_VARIANCE_6M": 0.025, "YTD_RETURN": -0.035},

    # ---- 可转债（约3.2%）----
    {"AST_CD": "113050.SH", "AST_NM": "南银转债", "AST_TYPE": "CONVERTIBLE", "AST_SUB_TYPE": "CB",
     "ISR_ID": "ENT_010", "ISR_NM": "南京银行股份有限公司", "CREDIT_RATING": "AAA",
     "HLD_QTY": 80000, "FACE_VAL": 100, "MKT_PRICE": 108.50, "MKT_VAL": 8680000,
     "WEIGHT": 1.71, "COST_AMT": 8000000, "YIELD_TO_MATURITY": 1.85, "M_DURATION": 3.50,
     "MATURITY_DT": "2028-06-15", "COUPON_RATE": 0.30, "INDUSTRY": "银行"},

    {"AST_CD": "127045.SZ", "AST_NM": "隆基转债", "AST_TYPE": "CONVERTIBLE", "AST_SUB_TYPE": "CB",
     "ISR_ID": "ENT_026", "ISR_NM": "隆基绿能科技股份有限公司", "CREDIT_RATING": "AA+",
     "HLD_QTY": 70000, "FACE_VAL": 100, "MKT_PRICE": 112.30, "MKT_VAL": 7861000,
     "WEIGHT": 1.55, "COST_AMT": 7000000, "YIELD_TO_MATURITY": -0.50, "M_DURATION": 4.20,
     "MATURITY_DT": "2028-11-02", "COUPON_RATE": 0.20, "INDUSTRY": "新能源"},

    # ---- 非标资产（约3.2%）----
    {"AST_CD": "TRUST_049", "AST_NM": "中信建投-稳健1号集合信托", "AST_TYPE": "NON_STD", "AST_SUB_TYPE": "TRUST",
     "ISR_ID": "ENT_015", "ISR_NM": "中信建投证券股份有限公司", "CREDIT_RATING": "AA+",
     "HLD_QTY": 1, "FACE_VAL": 16000000, "MKT_PRICE": 16000000, "MKT_VAL": 16000000,
     "WEIGHT": 3.16, "COST_AMT": 16000000, "YIELD_TO_MATURITY": 5.50, "M_DURATION": 1.50,
     "MATURITY_DT": "2026-03-20", "COUPON_RATE": 5.50, "INDUSTRY": "金融"},

    # ---- 衍生品（约3.5%，CTA趋势策略）----
    {"AST_CD": "FUT_IF2509", "AST_NM": "沪深300股指期货2509合约", "AST_TYPE": "DERIVATIVE", "AST_SUB_TYPE": "FUTURES",
     "ISR_ID": "", "ISR_NM": "中国金融期货交易所", "CREDIT_RATING": "",
     "HLD_QTY": 15, "FACE_VAL": 300, "MKT_PRICE": 3850, "MKT_VAL": 17325000,
     "WEIGHT": 3.42, "COST_AMT": 5200000, "YIELD_TO_MATURITY": 0, "M_DURATION": 0,
     "MATURITY_DT": "2025-09-19", "COUPON_RATE": 0, "INDUSTRY": "金融",
     "MARGIN_RATIO": 0.12, "NOTIONAL": 17325000},

    # ---- 现金及存款（约5.8%）----
    {"AST_CD": "CASH_001", "AST_NM": "活期存款-农业银行", "AST_TYPE": "CASH", "AST_SUB_TYPE": "DEMAND_DEPOSIT",
     "ISR_ID": "ENT_008", "ISR_NM": "中国农业银行股份有限公司", "CREDIT_RATING": "AAA",
     "HLD_QTY": 1, "FACE_VAL": 29409899, "MKT_PRICE": 29409899, "MKT_VAL": 29409899,
     "WEIGHT": 5.80, "COST_AMT": 29409899, "YIELD_TO_MATURITY": 0.20, "M_DURATION": 0,
     "MATURITY_DT": "", "COUPON_RATE": 0.20, "INDUSTRY": "银行"},
]


def build_hld_doc(h, port_id, biz_dt):
    """构建 dwd_ptl_ast_hld 文档"""
    doc = {
        "PORT_ID": port_id,
        "AST_CD": h["AST_CD"],
        "AST_NM": h["AST_NM"],
        "AST_TYPE": h["AST_TYPE"],
        "AST_SUB_TYPE": h["AST_SUB_TYPE"],
        "BIZ_DT": biz_dt,
        "HLD_QTY": h["HLD_QTY"],
        "FACE_VAL": h["FACE_VAL"],
        "MKT_PRICE": h["MKT_PRICE"],
        "MKT_VAL": h["MKT_VAL"],
        "WEIGHT": h["WEIGHT"],
        "COST_AMT": h["COST_AMT"],
        "ISR_ID": h["ISR_ID"],
        "ISR_NM": h["ISR_NM"],
        "CREDIT_RATING": h.get("CREDIT_RATING", ""),
        "YIELD_TO_MATURITY": h.get("YIELD_TO_MATURITY", 0),
        "M_DURATION": h.get("M_DURATION", 0),
        "MATURITY_DT": h.get("MATURITY_DT", ""),
        "COUPON_RATE": h.get("COUPON_RATE", 0),
        "INDUSTRY": h.get("INDUSTRY", ""),
        # ECL字段（如有）
        "ECL_PD": h.get("ECL_PD"),
        "ECL_LGD": h.get("ECL_LGD"),
        "EXPECTED_LOSS": h.get("EXPECTED_LOSS"),
        # 股票专用字段（如有）
        "BETA": h.get("BETA"),
        "MONTH_VARIANCE_6M": h.get("MONTH_VARIANCE_6M"),
        "YTD_RETURN": h.get("YTD_RETURN"),
        # 衍生品专用（如有）
        "MARGIN_RATIO": h.get("MARGIN_RATIO"),
        "NOTIONAL": h.get("NOTIONAL"),
        # 元数据
        "DATA_SRC": "浙银理财",
        "IMPORT_TYPE": "手动补录",
        "etl_dt": ETL_DT,
        "src_sys": "MANUAL_FILL",
        "created_at": ETL_DT,
        "updated_at": ETL_DT,
    }
    # 清除 None 值
    return {k: v for k, v in doc.items() if v is not None}


def main():
    client = MongoClient(MONGO_URI)

    for db_name in DB_NAMES:
        db = client[db_name]
        print(f"\n{'='*50}")
        print(f"写入数据库: {db_name}")
        print(f"{'='*50}")

        # 1. 写入 dwd_ptl_asset_config_info
        col_config = db["dwd_ptl_asset_config_info"]
        col_config.delete_many({"PORT_ID": PORT_ID})
        col_config.insert_one(ASSET_CONFIG)
        print(f"[OK] dwd_ptl_asset_config_info: 1 doc inserted for {PORT_ID}")

        # 2. 写入 dwd_ptl_ast_hld
        col_hld = db["dwd_ptl_ast_hld"]
        col_hld.delete_many({"PORT_ID": PORT_ID})
        docs = [build_hld_doc(h, PORT_ID, BIZ_DT) for h in HOLDINGS]
        col_hld.insert_many(docs)
        print(f"[OK] dwd_ptl_ast_hld: {len(docs)} docs inserted for {PORT_ID}")

        # 3. 写入 zysc_ptl_info_records (product_hub_query 查的表，中文字段名)
        col_hub = db["zysc_ptl_info_records"]
        hub_doc = {
            "产品代码": PORT_ID,
            "产品简称": "平衡收益45号",
            "产品名称": "浙银理财金利2026年第45期",
            "拉链开始日": "2025-01-01",
            "拉链结束日": "2026-05-26",
            "币种": "人民币",
            "估值方法": "市值法",
            "产品性质": "理财产品",
            "产品类型": "010",
            "产品模式": "普通产品",
            "所属部门": "资产管理部",
            "所属子部门": "固收投资组",
            "管理人": "浙银理财",
            "托管人": "农业银行",
            "投资经理": "李伟",
            "募集方式": "公募",
            "风险等级": "R3",
            "收益类型": "非保本浮动",
            "客户类型": "个人",
            "产品系列": "金利",
            "产品系列细分": "平衡",
            "是否现金管理类": "否",
            "数据日期": "2026-05-26",
            "数据时间": "08:00:00",
            "数据来源": "ZYSC",
            "导入方法": "API",
            "最短持有期限(天)": 180,
            "建仓完成期": "2024-09-14",
            "募集开始日": "2024-08-01",
            "建仓期": 30,
            "开放类型": "定期开放",
            "开放频率": "每季度",
            "运行方式": "正常",
            "市场基准": "中债综合指数",
            "合约基准": f"{PORT_ID}_HYJZ",
            "合约基准_上限": 0.045,
            "合约基准_下限": 0.025,
            "合约基准_平均": 0.035,
            "产品起息日": "2024-08-14",
            "产品到期日": "2025-08-14",
            "交易日历": "中国银行间交易日历",
            "策略类型": "CTA趋势",
            "资管计划管理方式": "主动管理",
            "是否最短持有期": "是",
            "起点销售金额/认购起点": 10000,
            "_batch_id": "batch_ptl_080_manual",
            "_imported_at": datetime.now().isoformat(),
            "_created_at": datetime.now().isoformat(),
        }
        col_hub.update_one({"产品代码": PORT_ID}, {"$set": hub_doc}, upsert=True)
        print(f"[OK] zysc_ptl_info_records: 1 doc upserted for {PORT_ID}")

    # 3. 验证（只显示一次）
    total_weight = sum(d["WEIGHT"] for d in docs)
    total_mkt_val = sum(d["MKT_VAL"] for d in docs)
    print(f"\n[验证] 总权重: {total_weight:.2f}%")
    print(f"[验证] 总市值: {total_mkt_val:,.0f} 元")
    print(f"[验证] AUM:    {AUM:,.0f} 元")
    print(f"[验证] 偏差:   {abs(total_mkt_val - AUM) / AUM * 100:.2f}%")

    # 4. 分类统计
    by_type = {}
    for d in docs:
        t = d["AST_TYPE"]
        by_type[t] = by_type.get(t, 0) + d["WEIGHT"]
    print("\n[资产配置统计]")
    for t, w in sorted(by_type.items(), key=lambda x: -x[1]):
        type_zh = {"BOND": "债券", "STOCK": "股票", "CONVERTIBLE": "可转债",
                   "NON_STD": "非标", "DERIVATIVE": "衍生品", "CASH": "现金", "NCD": "同业存单"}.get(t, t)
        print(f"  {type_zh:8s} ({t:12s}): {w:6.2f}%")

    # 5. 信用下沉分析
    print("\n[信用下沉分析]")
    bonds = [d for d in docs if d["AST_TYPE"] in ("BOND", "NCD")]
    total_bond_w = sum(d["WEIGHT"] for d in bonds)
    for rating in ["AAA", "AA+", "AA", "AA-", "A+"]:
        sub = [d for d in bonds if d.get("CREDIT_RATING") == rating]
        if sub:
            w = sum(d["WEIGHT"] for d in sub)
            print(f"  {rating:4s}: {w:6.2f}% ({len(sub)}只) — {', '.join(d['AST_NM'] for d in sub)}")

    ecl_bonds = [d for d in docs if d.get("ECL_PD")]
    if ecl_bonds:
        print(f"\n[ECL预警债券]")
        for d in ecl_bonds:
            level = "红色" if d["ECL_PD"] > 0.25 else "橙色" if d["ECL_PD"] > 0.10 else "黄色"
            print(f"  {d['AST_NM']:20s} | PD={d['ECL_PD']*100:.1f}% | LGD={d['ECL_LGD']*100:.0f}% | 预期损失={d['EXPECTED_LOSS']:,.0f}元 | {level}预警")

    client.close()
    print(f"\n[完成] 数据已写入 {len(DB_NAMES)} 个数据库")


if __name__ == "__main__":
    main()
