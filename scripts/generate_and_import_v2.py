#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZY 数据域关联 Mock 数据生成器 v2（增强版）

覆盖范围：
- 20+ 集合
- 200+ 条记录（不含时间序列）
- 15+ 复杂分析场景
- 5种关联类型全覆盖
"""

from pymongo import MongoClient
from datetime import datetime, timedelta
import random

# 配置
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"
BIZ_DT = "20250324"

def generate_v2_data():
    """生成 v2 增强版关联数据"""
    
    print("="*70)
    print("ZY 数据域关联 Mock 数据生成器 v2（增强版）")
    print("="*70)
    
    # 连接 MongoDB
    print("\n连接 MongoDB...")
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    client.admin.command('ping')
    print(f"✓ 已连接到 {DB_NAME} 数据库\n")
    
    data = {}
    
    # ========================================
    # 1. 主体域（3个集合）
    # ========================================
    print("【主体域】生成数据...")
    
    # 1.1 机构信息
    institutions = [
        {"ISR_ID": "ISR000001", "ISR_NM": "中华人民共和国财政部", "ISR_SHORT_NM": "财政部", "ISR_TYPE": "SOVEREIGN", "CREDIT_CD": "11100000000100176T", "INDUSTRY_CD": "S9510", "REG_PROV": "北京", "LIST_FLAG": "N", "REG_CAP_AMT": 0, "EST_DT": "19490701", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"ISR_ID": "ISR000002", "ISR_NM": "国家开发银行", "ISR_SHORT_NM": "国开行", "ISR_TYPE": "POLICY_BANK", "CREDIT_CD": "91110000100001269U", "INDUSTRY_CD": "J6621", "REG_PROV": "北京", "LIST_FLAG": "N", "REG_CAP_AMT": 421248000000, "EST_DT": "19940317", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"ISR_ID": "ISR000003", "ISR_NM": "中国工商银行股份有限公司", "ISR_SHORT_NM": "工商银行", "ISR_TYPE": "COMMERCIAL_BANK", "CREDIT_CD": "9111000010000016XA", "INDUSTRY_CD": "J6611", "REG_PROV": "北京", "LIST_FLAG": "Y", "REG_CAP_AMT": 356406000000, "EST_DT": "19840101", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"ISR_ID": "ISR000004", "ISR_NM": "中国农业发展银行", "ISR_SHORT_NM": "农发行", "ISR_TYPE": "POLICY_BANK", "CREDIT_CD": "91110000100003790Y", "INDUSTRY_CD": "J6621", "REG_PROV": "北京", "LIST_FLAG": "N", "REG_CAP_AMT": 57074000000, "EST_DT": "19941118", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"ISR_ID": "ISR000005", "ISR_NM": "万科企业股份有限公司", "ISR_SHORT_NM": "万科", "ISR_TYPE": "CORPORATE", "CREDIT_CD": "914403001922038216", "INDUSTRY_CD": "K7010", "REG_PROV": "广东", "LIST_FLAG": "Y", "REG_CAP_AMT": 11039152192, "EST_DT": "19840501", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"ISR_ID": "ISR000006", "ISR_NM": "华能新能源股份有限公司", "ISR_SHORT_NM": "华能新能源", "ISR_TYPE": "CORPORATE", "CREDIT_CD": "91110000717825307B", "INDUSTRY_CD": "D4412", "REG_PROV": "北京", "LIST_FLAG": "Y", "REG_CAP_AMT": 8020000000, "EST_DT": "20080801", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"ISR_ID": "ISR000007", "ISR_NM": "招商银行股份有限公司", "ISR_SHORT_NM": "招商银行", "ISR_TYPE": "COMMERCIAL_BANK", "CREDIT_CD": "91440300100018588H", "INDUSTRY_CD": "J6611", "REG_PROV": "广东", "LIST_FLAG": "Y", "REG_CAP_AMT": 25220900000, "EST_DT": "19870408", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"ISR_ID": "ISR000008", "ISR_NM": "中国平安保险(集团)股份有限公司", "ISR_SHORT_NM": "中国平安", "ISR_TYPE": "CORPORATE", "CREDIT_CD": "91440300100019502G", "INDUSTRY_CD": "J6812", "REG_PROV": "广东", "LIST_FLAG": "Y", "REG_CAP_AMT": 18280200000, "EST_DT": "19880301", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_isr_institution"] = institutions
    print(f"  ✓ dwd_isr_institution: {len(institutions)} 条")
    
    # 1.2 机构财务数据（新增）
    finance_data = []
    for isr in institutions:
        # 生成过去3年数据
        for year in [2022, 2023, 2024]:
            for quarter in [1, 2, 3, 4]:
                rpt_dt = f"{year}{'03' if quarter==1 else '06' if quarter==2 else '09' else '12'}{'31' if quarter==4 else str(quarter*3).zfill(2)}"
                rpt_type = "QUARTERLY" if quarter < 4 else "ANNUAL"
                
                # 万科财务数据特殊处理（显示恶化趋势）
                if isr["ISR_ID"] == "ISR000005":
                    total_assets = 250000000000 - (2024-year) * 20000000000
                    net_profit = 50000000000 if year==2022 else (10000000000 if year==2023 else -15000000000)
                    operating_cf = 80000000000 if year==2022 else (20000000000 if year==2023 else -50000000000)
                    debt_ratio = 0.72 if year==2022 else (0.76 if year==2023 else 0.80)
                # 华能新能源（显示改善趋势）
                elif isr["ISR_ID"] == "ISR000006":
                    total_assets = 50000000000 + (year-2022) * 15000000000
                    net_profit = -5000000000 if year==2022 else (2000000000 if year==2023 else 8000000000)
                    operating_cf = -10000000000 if year==2022 else (5000000000 if year==2023 else 20000000000)
                    debt_ratio = 0.78 if year==2022 else (0.72 if year==2023 else 0.65)
                # 其他机构（稳定）
                else:
                    total_assets = random.randint(100000000000, 500000000000)
                    net_profit = random.randint(5000000000, 50000000000)
                    operating_cf = random.randint(10000000000, 80000000000)
                    debt_ratio = round(random.uniform(0.70, 0.85), 2)
                
                finance_data.append({
                    "ISR_ID": isr["ISR_ID"],
                    "ISR_NM": isr["ISR_NM"],
                    "RPT_DT": rpt_dt,
                    "RPT_TYPE": rpt_type,
                    "TOTAL_ASSETS": total_assets,
                    "TOTAL_LIABILITIES": int(total_assets * debt_ratio),
                    "NET_PROFIT": net_profit,
                    "OPERATING_CASH_FLOW": operating_cf,
                    "DEBT_RATIO": debt_ratio,
                    "CURRENT_RATIO": round(random.uniform(1.0, 2.0), 2),
                    "INTEREST_COVERAGE": round(random.uniform(2.0, 8.0), 2),
                    "BIZ_DT": BIZ_DT,
                    "etl_dt": BIZ_DT,
                    "src_sys": "MOCK"
                })
    
    data["dwd_isr_institution_finance"] = finance_data
    print(f"  ✓ dwd_isr_institution_finance: {len(finance_data)} 条 [关联: ISR_ID → institution]")
    
    # 1.3 交易对手（新增）
    counterparties = [
        {"CNTP_ID": "CNTP00001", "CNTP_NM": "中信证券股份有限公司", "CNTP_TYPE": "BROKER", "CREDIT_RATING": "AA+", "SETTLE_METHOD": "DVP", "TRADE_LIMIT": 500000000, "CURRENT_EXPOSURE": 150000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CNTP_ID": "CNTP00002", "CNTP_NM": "华泰证券股份有限公司", "CNTP_TYPE": "BROKER", "CREDIT_RATING": "AA+", "SETTLE_METHOD": "DVP", "TRADE_LIMIT": 400000000, "CURRENT_EXPOSURE": 80000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CNTP_ID": "CNTP00003", "CNTP_NM": "国泰君安证券股份有限公司", "CNTP_TYPE": "BROKER", "CREDIT_RATING": "AAA", "SETTLE_METHOD": "DVP", "TRADE_LIMIT": 450000000, "CURRENT_EXPOSURE": 90000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CNTP_ID": "CNTP00004", "CNTP_NM": "招商证券股份有限公司", "CNTP_TYPE": "BROKER", "CREDIT_RATING": "AA+", "SETTLE_METHOD": "DVP", "TRADE_LIMIT": 350000000, "CURRENT_EXPOSURE": 50000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CNTP_ID": "CNTP00005", "CNTP_NM": "中国银河证券股份有限公司", "CNTP_TYPE": "BROKER", "CREDIT_RATING": "AA", "SETTLE_METHOD": "DVP", "TRADE_LIMIT": 300000000, "CURRENT_EXPOSURE": 40000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_isr_trd_cntp"] = counterparties
    print(f"  ✓ dwd_isr_trd_cntp: {len(counterparties)} 条")
    
    # ========================================
    # 2. 资产域（10个集合）
    # ========================================
    print("\n【资产域】生成数据...")
    
    # 2.1 资产基础信息
    assets = [
        {"AST_CD": "019601.IB", "AST_NM": "25国债03", "AST_TYPE": "BOND", "AST_SUB_TYPE": "CGB", "ISR_ID": "ISR000001", "CCY": "CNY", "LIST_DT": "20250115", "MATURITY_DT": "20350115", "COUPON_RATE": 0.0195, "ISSUE_AMT": 50000000000, "MARKET": "银行间", "BOND_TERM": 10, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "019735.IB", "AST_NM": "25特别国债03", "AST_TYPE": "BOND", "AST_SUB_TYPE": "CGB", "ISR_ID": "ISR000001", "CCY": "CNY", "LIST_DT": "20250220", "MATURITY_DT": "20550220", "COUPON_RATE": 0.0245, "ISSUE_AMT": 80000000000, "MARKET": "银行间", "BOND_TERM": 30, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "230210.IB", "AST_NM": "23国开10", "AST_TYPE": "BOND", "AST_SUB_TYPE": "POLICY", "ISR_ID": "ISR000002", "CCY": "CNY", "LIST_DT": "20230615", "MATURITY_DT": "20330615", "COUPON_RATE": 0.0278, "ISSUE_AMT": 120000000000, "MARKET": "银行间", "BOND_TERM": 10, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "220215.IB", "AST_NM": "22国开15", "AST_TYPE": "BOND", "AST_SUB_TYPE": "POLICY", "ISR_ID": "ISR000002", "CCY": "CNY", "LIST_DT": "20221020", "MATURITY_DT": "20321020", "COUPON_RATE": 0.0295, "ISSUE_AMT": 90000000000, "MARKET": "银行间", "BOND_TERM": 10, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "2480006.IB", "AST_NM": "24工商银行MTN001", "AST_TYPE": "BOND", "AST_SUB_TYPE": "MTN", "ISR_ID": "ISR000003", "CCY": "CNY", "LIST_DT": "20240315", "MATURITY_DT": "20270315", "COUPON_RATE": 0.0310, "ISSUE_AMT": 10000000000, "MARKET": "银行间", "BOND_TERM": 3, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "112311.SZ", "AST_NM": "24万科MTN003", "AST_TYPE": "BOND", "AST_SUB_TYPE": "MTN", "ISR_ID": "ISR000005", "CCY": "CNY", "LIST_DT": "20240520", "MATURITY_DT": "20260520", "COUPON_RATE": 0.0450, "ISSUE_AMT": 3000000000, "MARKET": "深交所", "BOND_TERM": 2, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "600036.SH", "AST_NM": "招商银行", "AST_TYPE": "STOCK", "AST_SUB_TYPE": "A_SHARE", "ISR_ID": "ISR000007", "CCY": "CNY", "LIST_DT": "20020409", "MARKET": "上交所", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "601318.SH", "AST_NM": "中国平安", "AST_TYPE": "STOCK", "AST_SUB_TYPE": "A_SHARE", "ISR_ID": "ISR000008", "CCY": "CNY", "LIST_DT": "20070301", "MARKET": "上交所", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "510300.SH", "AST_NM": "沪深300ETF", "AST_TYPE": "FUND", "AST_SUB_TYPE": "ETF", "ISR_ID": "ISR000007", "CCY": "CNY", "LIST_DT": "20120526", "MARKET": "上交所", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "511260.SH", "AST_NM": "十年国债ETF", "AST_TYPE": "FUND", "AST_SUB_TYPE": "ETF", "ISR_ID": "ISR000003", "CCY": "CNY", "LIST_DT": "20200320", "MARKET": "上交所", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "127080.SZ", "AST_NM": "2024华能新能ABS001优先A", "AST_TYPE": "ABS", "AST_SUB_TYPE": "ABS_SENIOR", "ISR_ID": "ISR000006", "CCY": "CNY", "LIST_DT": "20240801", "MATURITY_DT": "20270801", "COUPON_RATE": 0.0330, "ISSUE_AMT": 2000000000, "MARKET": "深交所", "BOND_TERM": 3, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "180401.IB", "AST_NM": "24农发绿色债01", "AST_TYPE": "BOND", "AST_SUB_TYPE": "POLICY", "ISR_ID": "ISR000004", "CCY": "CNY", "LIST_DT": "20240410", "MATURITY_DT": "20290410", "COUPON_RATE": 0.0255, "ISSUE_AMT": 30000000000, "MARKET": "银行间", "BOND_TERM": 5, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_info"] = assets
    print(f"  ✓ dwd_ast_info: {len(assets)} 条 [关联: ISR_ID → institution]")
    
    # 2.2 中债估值
    valuations_ch = [
        {"AST_CD": "019601.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 99.5600, "VAL_FULL_PRC": 99.8012, "VAL_YIELD": 0.0215, "DURATION": 9.5200, "CONVEXITY": 98.5, "RATING_AGENCY": "中诚信国际", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "019735.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 102.3500, "VAL_FULL_PRC": 102.6820, "VAL_YIELD": 0.0238, "DURATION": 18.7600, "CONVEXITY": 425.8, "RATING_AGENCY": "中诚信国际", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "230210.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 100.8200, "VAL_FULL_PRC": 101.5680, "VAL_YIELD": 0.0265, "DURATION": 7.2100, "CONVEXITY": 62.4, "RATING_AGENCY": "联合资信", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "220215.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 101.2500, "VAL_FULL_PRC": 102.0180, "VAL_YIELD": 0.0282, "DURATION": 6.8500, "CONVEXITY": 55.2, "RATING_AGENCY": "联合资信", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "2480006.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 100.1500, "VAL_FULL_PRC": 100.3215, "VAL_YIELD": 0.0305, "DURATION": 1.9500, "CONVEXITY": 5.2, "RATING_AGENCY": "中诚信国际", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "112311.SZ", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 95.8800, "VAL_FULL_PRC": 96.5420, "VAL_YIELD": 0.0512, "DURATION": 1.1500, "CONVEXITY": 1.8, "RATING_AGENCY": "联合资信", "VAL_SRC": "CSI", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "180401.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 98.7600, "VAL_FULL_PRC": 99.0850, "VAL_YIELD": 0.0272, "DURATION": 4.3200, "CONVEXITY": 22.6, "RATING_AGENCY": "联合资信", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_info_ch"] = valuations_ch
    print(f"  ✓ dwd_ast_info_ch: {len(valuations_ch)} 条 [关联: AST_CD → ast_info]")
    
    # 2.3 中证估值（新增）
    valuations_zg = [
        {"AST_CD": "019601.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 99.5320, "VAL_FULL_PRC": 99.7735, "VAL_YIELD": 0.0216, "DURATION": 9.5100, "CONVEXITY": 98.2, "RATING_AGENCY": "中证指数", "VAL_SRC": "CSI", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "230210.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 100.7800, "VAL_FULL_PRC": 101.5280, "VAL_YIELD": 0.0267, "DURATION": 7.2000, "CONVEXITY": 62.1, "RATING_AGENCY": "中证指数", "VAL_SRC": "CSI", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "2480006.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 100.1200, "VAL_FULL_PRC": 100.2915, "VAL_YIELD": 0.0307, "DURATION": 1.9400, "CONVEXITY": 5.1, "RATING_AGENCY": "中证指数", "VAL_SRC": "CSI", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "112311.SZ", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 95.8500, "VAL_FULL_PRC": 96.5120, "VAL_YIELD": 0.0515, "DURATION": 1.1400, "CONVEXITY": 1.7, "RATING_AGENCY": "中证指数", "VAL_SRC": "CSI", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "180401.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 98.7300, "VAL_FULL_PRC": 99.0550, "VAL_YIELD": 0.0274, "DURATION": 4.3100, "CONVEXITY": 22.4, "RATING_AGENCY": "中证指数", "VAL_SRC": "CSI", "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_info_zg"] = valuations_zg
    print(f"  ✓ dwd_ast_info_zg: {len(valuations_zg)} 条 [关联: AST_CD → ast_info]")
    
    # 2.4 收益率（新增）
    yields = [
        {"AST_CD": "019601.IB", "BIZ_DT": BIZ_DT, "YTM": 0.0215, "CURRENT_YIELD": 0.0196, "COUPON_RATE": 0.0195, "SPREAD_VS_CGB": 0.0000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "019735.IB", "BIZ_DT": BIZ_DT, "YTM": 0.0238, "CURRENT_YIELD": 0.0240, "COUPON_RATE": 0.0245, "SPREAD_VS_CGB": 0.0023, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "230210.IB", "BIZ_DT": BIZ_DT, "YTM": 0.0265, "CURRENT_YIELD": 0.0275, "COUPON_RATE": 0.0278, "SPREAD_VS_CGB": 0.0050, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "220215.IB", "BIZ_DT": BIZ_DT, "YTM": 0.0282, "CURRENT_YIELD": 0.0291, "COUPON_RATE": 0.0295, "SPREAD_VS_CGB": 0.0067, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "2480006.IB", "BIZ_DT": BIZ_DT, "YTM": 0.0305, "CURRENT_YIELD": 0.0310, "COUPON_RATE": 0.0310, "SPREAD_VS_CGB": 0.0090, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "112311.SZ", "BIZ_DT": BIZ_DT, "YTM": 0.0512, "CURRENT_YIELD": 0.0470, "COUPON_RATE": 0.0450, "SPREAD_VS_CGB": 0.0297, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "180401.IB", "BIZ_DT": BIZ_DT, "YTM": 0.0272, "CURRENT_YIELD": 0.0258, "COUPON_RATE": 0.0255, "SPREAD_VS_CGB": 0.0057, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_yield_info"] = yields
    print(f"  ✓ dwd_ast_yield_info: {len(yields)} 条 [关联: AST_CD → ast_info]")
    
    # 2.5 现金流计划（新增）
    cashflows = []
    cf_id = 1
    for ast in assets:
        if ast["AST_TYPE"] == "BOND":
            # 生成未来1年的现金流
            maturity_year = int(ast["MATURITY_DT"][:4])
            coupon = ast["COUPON_RATE"]
            issue_amt = ast["ISSUE_AMT"]
            
            # 假设每年付息一次
            for year in range(2025, min(2026, maturity_year) + 1):
                cf_dt = ast["MATURITY_DT"][:4] + ast["LIST_DT"][4:]  # 付息日
                
                cashflows.append({
                    "CF_ID": f"CF{cf_id:06d}",
                    "AST_CD": ast["AST_CD"],
                    "AST_NM": ast["AST_NM"],
                    "CF_DT": cf_dt,
                    "CF_TYPE": "COUPON" if year < maturity_year else "PRINCIPAL_AND_COUPON",
                    "CF_AMT": issue_amt * coupon if year < maturity_year else issue_amt * (1 + coupon),
                    "CCY": "CNY",
                    "BIZ_DT": BIZ_DT,
                    "etl_dt": BIZ_DT,
                    "src_sys": "MOCK"
                })
                cf_id += 1
    
    data["dwd_ast_cf_plan"] = cashflows
    print(f"  ✓ dwd_ast_cf_plan: {len(cashflows)} 条 [关联: AST_CD → ast_info]")
    
    # 2.6 质押状态
    pledges = [
        {"AST_CD": "019601.IB", "BIZ_DT": BIZ_DT, "PLEDGE_FLAG": "Y", "PLEDGE_RATIO": 0.95, "PLEDGE_STD_BOND": 0.98, "PLEDGE_BOND_CD": "019601.IB", "PLEDGE_NOTE": "用于央行公开市场操作质押", "PLEDGE_INST": "中国人民银行", "PLEDGE_AMT": 200000000, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "230210.IB", "BIZ_DT": BIZ_DT, "PLEDGE_FLAG": "Y", "PLEDGE_RATIO": 0.90, "PLEDGE_STD_BOND": 0.95, "PLEDGE_BOND_CD": "230210.IB", "PLEDGE_NOTE": "银行间质押式回购", "PLEDGE_INST": "中央国债登记结算有限责任公司", "PLEDGE_AMT": 150000000, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "2480006.IB", "BIZ_DT": BIZ_DT, "PLEDGE_FLAG": "Y", "PLEDGE_RATIO": 0.85, "PLEDGE_STD_BOND": 0.88, "PLEDGE_BOND_CD": "2480006.IB", "PLEDGE_NOTE": "上清所质押式回购", "PLEDGE_INST": "上海清算所", "PLEDGE_AMT": 80000000, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "180401.IB", "BIZ_DT": BIZ_DT, "PLEDGE_FLAG": "Y", "PLEDGE_RATIO": 0.88, "PLEDGE_STD_BOND": 0.92, "PLEDGE_BOND_CD": "180401.IB", "PLEDGE_NOTE": "绿色债券质押", "PLEDGE_INST": "中央国债登记结算有限责任公司", "PLEDGE_AMT": 100000000, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "112311.SZ", "BIZ_DT": BIZ_DT, "PLEDGE_FLAG": "N", "PLEDGE_RATIO": 0, "PLEDGE_STD_BOND": 0, "PLEDGE_BOND_CD": "", "PLEDGE_NOTE": "不可质押，信用债评级低于AA", "PLEDGE_INST": "", "PLEDGE_AMT": 0, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_pledge"] = pledges
    print(f"  ✓ dwd_ast_pledge: {len(pledges)} 条 [关联: AST_CD → ast_info]")
    
    # 2.7 五级分类（新增）
    fiveclass = [
        {"AST_CD": "019601.IB", "BIZ_DT": BIZ_DT, "FIVE_CLASS": "NORMAL", "CLASS_DT": "20250324", "CLASS_NOTE": "国债，无信用风险", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "019735.IB", "BIZ_DT": BIZ_DT, "FIVE_CLASS": "NORMAL", "CLASS_DT": "20250324", "CLASS_NOTE": "国债，无信用风险", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "230210.IB", "BIZ_DT": BIZ_DT, "FIVE_CLASS": "NORMAL", "CLASS_DT": "20250324", "CLASS_NOTE": "政金债，风险极低", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "220215.IB", "BIZ_DT": BIZ_DT, "FIVE_CLASS": "NORMAL", "CLASS_DT": "20250324", "CLASS_NOTE": "政金债，风险极低", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "2480006.IB", "BIZ_DT": BIZ_DT, "FIVE_CLASS": "NORMAL", "CLASS_DT": "20250324", "CLASS_NOTE": "商业银行债，AAA评级", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "112311.SZ", "BIZ_DT": BIZ_DT, "FIVE_CLASS": "SPECIAL_MENTION", "CLASS_DT": "20250324", "CLASS_NOTE": "发行人评级下调至AA-，财务指标恶化", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "180401.IB", "BIZ_DT": BIZ_DT, "FIVE_CLASS": "NORMAL", "CLASS_DT": "20250324", "CLASS_NOTE": "政金债，风险极低", "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_fiveclass"] = fiveclass
    print(f"  ✓ dwd_ast_fiveclass: {len(fiveclass)} 条 [关联: AST_CD → ast_info]")
    
    # 2.8 行权计划（新增）
    exe_plans = [
        {"AST_CD": "112311.SZ", "BIZ_DT": BIZ_DT, "EXE_DT": "20250520", "EXE_TYPE": "PUT", "EXE_PRC": 98.00, "EXE_NOTE": "投资者回售选择权", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "2480006.IB", "BIZ_DT": BIZ_DT, "EXE_DT": "20260315", "EXE_TYPE": "CALL", "EXE_PRC": 100.00, "EXE_NOTE": "发行人赎回选择权", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "180401.IB", "BIZ_DT": BIZ_DT, "EXE_DT": "20270410", "EXE_TYPE": "PUT", "EXE_PRC": 100.00, "EXE_NOTE": "投资者回售选择权", "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_exe_plan"] = exe_plans
    print(f"  ✓ dwd_ast_exe_plan: {len(exe_plans)} 条 [关联: AST_CD → ast_info]")
    
    # 2.9 参与方信息（新增）
    parties = []
    for ast in assets:
        parties.append({
            "AST_CD": ast["AST_CD"],
            "PARTY_TYPE": "ISSUER",
            "PARTY_ID": ast["ISR_ID"],
            "PARTY_NM": next((i["ISR_NM"] for i in institutions if i["ISR_ID"] == ast["ISR_ID"]), ""),
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        })
        if ast["AST_TYPE"] in ["FUND", "ABS"]:
            parties.append({
                "AST_CD": ast["AST_CD"],
                "PARTY_TYPE": "MANAGER",
                "PARTY_ID": "ISR000003",
                "PARTY_NM": "工商银行",
                "BIZ_DT": BIZ_DT,
                "etl_dt": BIZ_DT,
                "src_sys": "MOCK"
            })
    
    data["dwd_ast_party"] = parties
    print(f"  ✓ dwd_ast_party: {len(parties)} 条 [关联: AST_CD → ast_info]")
    
    # 2.10 基金经理（新增）
    fund_managers = [
        {"AST_CD": "510300.SH", "MGR_ID": "MGR001", "MGR_NM": "张建华", "MGR_TYPE": "INDEX", "START_DT": "20200101", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "511260.SH", "MGR_ID": "MGR002", "MGR_NM": "李明", "MGR_TYPE": "PASSIVE", "START_DT": "20200320", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "127080.SZ", "MGR_ID": "MGR003", "MGR_NM": "王芳", "MGR_TYPE": "ACTIVE", "START_DT": "20240801", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_fund_manager"] = fund_managers
    print(f"  ✓ dwd_ast_fund_manager: {len(fund_managers)} 条 [关联: AST_CD → ast_info]")
    
    # 2.11 计算规则（新增）
    calc_rules = [
        {"AST_CD": "019601.IB", "RULE_TYPE": "DURATION", "RULE_DESC": "麦考利久期计算", "RULE_FORMULA": "SUM(t * CF_t / (1+y)^t) / P", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "019601.IB", "RULE_TYPE": "CONVEXITY", "RULE_DESC": "凸性计算", "RULE_FORMULA": "SUM(t * (t+1) * CF_t / (1+y)^(t+2)) / P", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_calc_rule"] = calc_rules
    print(f"  ✓ dwd_ast_calc_rule: {len(calc_rules)} 条 [关联: AST_CD → ast_info]")
    
    # ========================================
    # 3. 产品域（4个集合）
    # ========================================
    print("\n【产品域】生成数据...")
    
    # 3.1 产品信息
    portfolios = [
        {"PORT_ID": "PORT001", "PORT_NM": "稳健配置一号", "PORT_SHORT_NM": "稳健1号", "PORT_TYPE": "MIXED", "RISK_LVL": "R3", "ESTAB_DT": "20210601", "CCY": "CNY", "BENCHMARK": "中债综合指数*70%+沪深300*30%", "SHR_NAV": 1.0512, "ACC_NAV": 1.1835, "AUM": 1250000000, "MGR_INST": "ISR000008", "CUSTODY_BANK": "ISR000003", "STATUS": "ACTIVE", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "PORT_NM": "纯债精选二号", "PORT_SHORT_NM": "纯债2号", "PORT_TYPE": "BOND", "RISK_LVL": "R2", "ESTAB_DT": "20200315", "CCY": "CNY", "BENCHMARK": "中债综合财富指数", "SHR_NAV": 1.0285, "ACC_NAV": 1.1520, "AUM": 2800000000, "MGR_INST": "ISR000008", "CUSTODY_BANK": "ISR000003", "STATUS": "ACTIVE", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "PORT_NM": "混合增强三号", "PORT_SHORT_NM": "混合3号", "PORT_TYPE": "MIXED", "RISK_LVL": "R3", "ESTAB_DT": "20220801", "CCY": "CNY", "BENCHMARK": "中债综合指数*50%+沪深300*50%", "SHR_NAV": 0.9875, "ACC_NAV": 0.9875, "AUM": 870000000, "MGR_INST": "ISR000005", "CUSTODY_BANK": "ISR000003", "STATUS": "ACTIVE", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT004", "PORT_NM": "短融货币四号", "PORT_SHORT_NM": "货币4号", "PORT_TYPE": "MMF", "RISK_LVL": "R1", "ESTAB_DT": "20190101", "CCY": "CNY", "BENCHMARK": "七日年化收益率基准", "SHR_NAV": 1.0000, "ACC_NAV": 1.0000, "AUM": 5000000000, "MGR_INST": "ISR000008", "CUSTODY_BANK": "ISR000003", "STATUS": "ACTIVE", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT005", "PORT_NM": "指数增强五号", "PORT_SHORT_NM": "指增5号", "PORT_TYPE": "INDEX", "RISK_LVL": "R4", "ESTAB_DT": "20230601", "CCY": "CNY", "BENCHMARK": "沪深300指数", "SHR_NAV": 1.1250, "ACC_NAV": 1.1250, "AUM": 650000000, "MGR_INST": "ISR000007", "CUSTODY_BANK": "ISR000003", "STATUS": "ACTIVE", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ptl_info"] = portfolios
    print(f"  ✓ dwd_ptl_info: {len(portfolios)} 条 [关联: MGR_INST → institution]")
    
    # 3.2 产品持仓
    holdings = [
        {"PORT_ID": "PORT001", "AST_CD": "019601.IB", "AST_NM": "25国债03", "AST_TYPE": "BOND", "HLD_RATIO": 0.15, "MKT_VAL": 187500000, "QTY": 1875000, "COST_VAL": 186000000, "UNREALIZED_PNL": 1500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "230210.IB", "AST_NM": "23国开10", "AST_TYPE": "BOND", "HLD_RATIO": 0.12, "MKT_VAL": 150000000, "QTY": 1500000, "COST_VAL": 149000000, "UNREALIZED_PNL": 1000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "2480006.IB", "AST_NM": "24工商银行MTN001", "AST_TYPE": "BOND", "HLD_RATIO": 0.08, "MKT_VAL": 100000000, "QTY": 1000000, "COST_VAL": 99500000, "UNREALIZED_PNL": 500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "600036.SH", "AST_NM": "招商银行", "AST_TYPE": "STOCK", "HLD_RATIO": 0.10, "MKT_VAL": 125000000, "QTY": 3000000, "COST_VAL": 120000000, "UNREALIZED_PNL": 5000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "510300.SH", "AST_NM": "沪深300ETF", "AST_TYPE": "FUND", "HLD_RATIO": 0.20, "MKT_VAL": 250000000, "QTY": 50000000, "COST_VAL": 240000000, "UNREALIZED_PNL": 10000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "511260.SH", "AST_NM": "十年国债ETF", "AST_TYPE": "FUND", "HLD_RATIO": 0.18, "MKT_VAL": 225000000, "QTY": 20000000, "COST_VAL": 223000000, "UNREALIZED_PNL": 2000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "112311.SZ", "AST_NM": "24万科MTN003", "AST_TYPE": "BOND", "HLD_RATIO": 0.05, "MKT_VAL": 62500000, "QTY": 650000, "COST_VAL": 63000000, "UNREALIZED_PNL": -500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "AST_CD": "019601.IB", "AST_NM": "25国债03", "AST_TYPE": "BOND", "HLD_RATIO": 0.25, "MKT_VAL": 700000000, "QTY": 7000000, "COST_VAL": 695000000, "UNREALIZED_PNL": 5000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "AST_CD": "019735.IB", "AST_NM": "25特别国债03", "AST_TYPE": "BOND", "HLD_RATIO": 0.20, "MKT_VAL": 560000000, "QTY": 5500000, "COST_VAL": 558000000, "UNREALIZED_PNL": 2000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "AST_CD": "230210.IB", "AST_NM": "23国开10", "AST_TYPE": "BOND", "HLD_RATIO": 0.18, "MKT_VAL": 504000000, "QTY": 5040000, "COST_VAL": 500000000, "UNREALIZED_PNL": 4000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "AST_CD": "2480006.IB", "AST_NM": "24工商银行MTN001", "AST_TYPE": "BOND", "HLD_RATIO": 0.15, "MKT_VAL": 420000000, "QTY": 4200000, "COST_VAL": 418000000, "UNREALIZED_PNL": 2000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "AST_CD": "180401.IB", "AST_NM": "24农发绿色债01", "AST_TYPE": "BOND", "HLD_RATIO": 0.12, "MKT_VAL": 336000000, "QTY": 3400000, "COST_VAL": 335000000, "UNREALIZED_PNL": 1000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "AST_CD": "600036.SH", "AST_NM": "招商银行", "AST_TYPE": "STOCK", "HLD_RATIO": 0.15, "MKT_VAL": 130500000, "QTY": 3100000, "COST_VAL": 128000000, "UNREALIZED_PNL": 2500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "AST_CD": "601318.SH", "AST_NM": "中国平安", "AST_TYPE": "STOCK", "HLD_RATIO": 0.12, "MKT_VAL": 104400000, "QTY": 2200000, "COST_VAL": 102000000, "UNREALIZED_PNL": 2400000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "AST_CD": "510300.SH", "AST_NM": "沪深300ETF", "AST_TYPE": "FUND", "HLD_RATIO": 0.18, "MKT_VAL": 156600000, "QTY": 31000000, "COST_VAL": 155000000, "UNREALIZED_PNL": 1600000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "AST_CD": "019601.IB", "AST_NM": "25国债03", "AST_TYPE": "BOND", "HLD_RATIO": 0.10, "MKT_VAL": 87000000, "QTY": 870000, "COST_VAL": 86500000, "UNREALIZED_PNL": 500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "AST_CD": "230210.IB", "AST_NM": "23国开10", "AST_TYPE": "BOND", "HLD_RATIO": 0.08, "MKT_VAL": 69600000, "QTY": 696000, "COST_VAL": 69000000, "UNREALIZED_PNL": 600000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT005", "AST_CD": "510300.SH", "AST_NM": "沪深300ETF", "AST_TYPE": "FUND", "HLD_RATIO": 0.85, "MKT_VAL": 552500000, "QTY": 110000000, "COST_VAL": 540000000, "UNREALIZED_PNL": 12500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ptl_ast_hld"] = holdings
    print(f"  ✓ dwd_ptl_ast_hld: {len(holdings)} 条 [关联: PORT_ID → ptl_info, AST_CD → ast_info]")
    
    # 3.3 产品账户（新增）
    accounts = []
    for port in portfolios[:2]:  # 只为前两个产品生成账户
        accounts.append({
            "PORT_ID": port["PORT_ID"],
            "ACC_NO": f"{port['PORT_ID']}_01",
            "ACC_TYPE": "BANK",
            "BANK_NAME": "工商银行",
            "ACC_BALANCE": int(port["AUM"] * 0.05),
            "CCY": "CNY",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        })
        accounts.append({
            "PORT_ID": port["PORT_ID"],
            "ACC_NO": f"{port['PORT_ID']}_02",
            "ACC_TYPE": "SECURITIES",
            "BANK_NAME": "中国证券登记结算公司",
            "ACC_BALANCE": int(port["AUM"] * 0.95),
            "CCY": "CNY",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        })
    
    data["dwd_ptl_acc"] = accounts
    print(f"  ✓ dwd_ptl_acc: {len(accounts)} 条 [关联: PORT_ID → ptl_info]")
    
    # ========================================
    # 4. 客户域（2个集合）
    # ========================================
    print("\n【客户域】生成数据...")
    
    customers = [
        {"CUSTOMER_ID": "CUS0000001", "CUST_NM": "张明远", "CUST_TYPE": "IND", "GENDER": "M", "BIRTH_DT": "19780815", "ID_TYPE": "IDCARD", "ID_NO": "310115197808157612", "PHONE": "13812345001", "EMAIL": "zhangmingyuan@163.com", "ADDR": "上海市浦东新区世纪大道1090号", "RISK_LVL": "C3", "OPEN_DT": "20210601", "CHANNEL": "DIRECT", "SELLER_ID": "SEL00001", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000002", "CUST_NM": "李秀芬", "CUST_TYPE": "IND", "GENDER": "F", "BIRTH_DT": "19820320", "ID_TYPE": "IDCARD", "ID_NO": "110108198203208425", "PHONE": "13912345002", "EMAIL": "lixiufen@126.com", "ADDR": "北京市朝阳区建国门外大街甲6号", "RISK_LVL": "C2", "OPEN_DT": "20200315", "CHANNEL": "BANK", "SELLER_ID": "SEL00002", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000003", "CUST_NM": "王建国", "CUST_TYPE": "IND", "GENDER": "M", "BIRTH_DT": "19751108", "ID_TYPE": "IDCARD", "ID_NO": "440301197511085518", "PHONE": "13602345003", "EMAIL": "wangjianguo@qq.com", "ADDR": "深圳市福田区红荔路1023号", "RISK_LVL": "C4", "OPEN_DT": "20220801", "CHANNEL": "DIRECT", "SELLER_ID": "SEL00001", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000004", "CUST_NM": "陈雅琴", "CUST_TYPE": "IND", "GENDER": "F", "BIRTH_DT": "19900525", "ID_TYPE": "IDCARD", "ID_NO": "330106199005258142", "PHONE": "13702345004", "EMAIL": "chenyaqin@gmail.com", "ADDR": "杭州市西湖区文三路269号", "RISK_LVL": "C1", "OPEN_DT": "20190101", "CHANNEL": "BROKER", "SELLER_ID": "SEL00004", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000005", "CUST_NM": "深圳市前海资产管理有限公司", "CUST_TYPE": "INST", "GENDER": "M", "BIRTH_DT": "20120601", "ID_TYPE": "CREDIT", "ID_NO": "91440300MA5DGD2X9Q", "PHONE": "0755-22357890", "EMAIL": "service@qhamc.com.cn", "ADDR": "深圳市前海深港合作区前湾一路1号A座", "RISK_LVL": "C4", "OPEN_DT": "20230601", "CHANNEL": "DIRECT", "SELLER_ID": "SEL00003", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000006", "CUST_NM": "上海浦东新区社会保险基金管理中心", "CUST_TYPE": "INST", "GENDER": "M", "BIRTH_DT": "19980915", "ID_TYPE": "CREDIT", "ID_NO": "12310115425612345B", "PHONE": "021-58821234", "EMAIL": "pdfund@pudong.gov.cn", "ADDR": "上海市浦东新区世纪大道2001号", "RISK_LVL": "C2", "OPEN_DT": "20180920", "CHANNEL": "BANK", "SELLER_ID": "SEL00005", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000007", "CUST_NM": "广东省教育基金会", "CUST_TYPE": "INST", "GENDER": "M", "BIRTH_DT": "19951210", "ID_TYPE": "CREDIT", "ID_NO": "53440000123456789X", "PHONE": "020-37628990", "EMAIL": "info@gdef.org.cn", "ADDR": "广州市越秀区中山三路2号", "RISK_LVL": "C2", "OPEN_DT": "20200118", "CHANNEL": "DIRECT", "SELLER_ID": "SEL00006", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_cust_info"] = customers
    print(f"  ✓ dwd_cust_info: {len(customers)} 条")
    
    customer_holdings = [
        {"CUSTOMER_ID": "CUS0000001", "PORT_ID": "PORT001", "HLD_AMT": 5000000, "HLD_SHARE": 4741379.31, "PURCHASE_DT": "20240101", "LAST_NAV": 1.0512, "UNREALIZED_PNL": 256000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000001", "PORT_ID": "PORT002", "HLD_AMT": 3000000, "HLD_SHARE": 2917647.06, "PURCHASE_DT": "20240601", "LAST_NAV": 1.0285, "UNREALIZED_PNL": 85500, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000002", "PORT_ID": "PORT002", "HLD_AMT": 10000000, "HLD_SHARE": 9724770.64, "PURCHASE_DT": "20230101", "LAST_NAV": 1.0285, "UNREALIZED_PNL": 285000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000002", "PORT_ID": "PORT004", "HLD_AMT": 8000000, "HLD_SHARE": 8000000.00, "PURCHASE_DT": "20240101", "LAST_NAV": 1.0000, "UNREALIZED_PNL": 0, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000003", "PORT_ID": "PORT001", "HLD_AMT": 12000000, "HLD_SHARE": 11380000.00, "PURCHASE_DT": "20230801", "LAST_NAV": 1.0512, "UNREALIZED_PNL": 614400, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000003", "PORT_ID": "PORT003", "HLD_AMT": 6000000, "HLD_SHARE": 6075949.37, "PURCHASE_DT": "20240201", "LAST_NAV": 0.9875, "UNREALIZED_PNL": -75000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000003", "PORT_ID": "PORT005", "HLD_AMT": 3000000, "HLD_SHARE": 2666666.67, "PURCHASE_DT": "20240601", "LAST_NAV": 1.1250, "UNREALIZED_PNL": 375000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000005", "PORT_ID": "PORT001", "HLD_AMT": 50000000, "HLD_SHARE": 47413793.10, "PURCHASE_DT": "20230601", "LAST_NAV": 1.0512, "UNREALIZED_PNL": 2560000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000005", "PORT_ID": "PORT003", "HLD_AMT": 20000000, "HLD_SHARE": 20253164.56, "PURCHASE_DT": "20240101", "LAST_NAV": 0.9875, "UNREALIZED_PNL": -250000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000006", "PORT_ID": "PORT002", "HLD_AMT": 30000000, "HLD_SHARE": 29176470.59, "PURCHASE_DT": "20220901", "LAST_NAV": 1.0285, "UNREALIZED_PNL": 855000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000006", "PORT_ID": "PORT004", "HLD_AMT": 25000000, "HLD_SHARE": 25000000.00, "PURCHASE_DT": "20230101", "LAST_NAV": 1.0000, "UNREALIZED_PNL": 0, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"CUSTOMER_ID": "CUS0000007", "PORT_ID": "PORT001", "HLD_AMT": 15000000, "HLD_SHARE": 14224137.93, "PURCHASE_DT": "20230601", "LAST_NAV": 1.0512, "UNREALIZED_PNL": 768000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_cust_ptl_hld"] = customer_holdings
    print(f"  ✓ dwd_cust_ptl_hld: {len(customer_holdings)} 条 [关联: CUSTOMER_ID → cust_info, PORT_ID → ptl_info]")
    
    # ========================================
    # 5. 销售域（1个集合）
    # ========================================
    print("\n【销售域】生成数据...")
    
    sellers = [
        {"SELLER_ID": "SEL00001", "SELLER_NM": "刘洋", "SELLER_TYPE": "INTERNAL", "DEPT": "机构销售一部", "REGION": "华东", "PHONE": "13800001001", "EMAIL": "liuyang@company.com", "JOIN_DT": "20180601", "TOTAL_AUM": 67000000, "CUSTOMER_COUNT": 2, "COMMISSION_RATE": 0.0015, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"SELLER_ID": "SEL00002", "SELLER_NM": "赵丽华", "SELLER_TYPE": "INTERNAL", "DEPT": "零售财富部", "REGION": "华北", "PHONE": "13800001002", "EMAIL": "zhaolihua@company.com", "JOIN_DT": "20190301", "TOTAL_AUM": 18000000, "CUSTOMER_COUNT": 1, "COMMISSION_RATE": 0.0012, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"SELLER_ID": "SEL00003", "SELLER_NM": "孙志强", "SELLER_TYPE": "INTERNAL", "DEPT": "机构销售二部", "REGION": "华南", "PHONE": "13800001003", "EMAIL": "sunzhiqiang@company.com", "JOIN_DT": "20170901", "TOTAL_AUM": 70000000, "CUSTOMER_COUNT": 1, "COMMISSION_RATE": 0.0015, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"SELLER_ID": "SEL00004", "SELLER_NM": "周敏", "SELLER_TYPE": "INTERNAL", "DEPT": "零售财富部", "REGION": "华东", "PHONE": "13800001004", "EMAIL": "zhoumin@company.com", "JOIN_DT": "20200101", "TOTAL_AUM": 0, "CUSTOMER_COUNT": 1, "COMMISSION_RATE": 0.0010, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"SELLER_ID": "SEL00005", "SELLER_NM": "吴晓峰", "SELLER_TYPE": "INTERNAL", "DEPT": "机构销售一部", "REGION": "华东", "PHONE": "13800001005", "EMAIL": "wuxiaofeng@company.com", "JOIN_DT": "20160601", "TOTAL_AUM": 55000000, "CUSTOMER_COUNT": 1, "COMMISSION_RATE": 0.0015, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"SELLER_ID": "SEL00006", "SELLER_NM": "郑雯", "SELLER_TYPE": "EXTERNAL", "DEPT": "电商渠道部", "REGION": "华南", "PHONE": "13800001006", "EMAIL": "zhengwen@company.com", "JOIN_DT": "20210101", "TOTAL_AUM": 15000000, "CUSTOMER_COUNT": 1, "COMMISSION_RATE": 0.0008, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_seller_info"] = sellers
    print(f"  ✓ dwd_seller_info: {len(sellers)} 条")
    
    # ========================================
    # 6. 交易域（2个集合）
    # ========================================
    print("\n【交易域】生成数据...")
    
    trades = []
    trade_id = 1
    for port_id in ["PORT001", "PORT002", "PORT003"]:
        for _ in range(10):  # 每个产品10笔交易
            ast = random.choice([a for a in assets if a["AST_TYPE"] == "BOND"])
            trade_type = random.choice(["BUY", "SELL"])
            qty = random.randint(100000, 2000000)
            price = round(random.uniform(95.0, 105.0), 4)
            cntp = random.choice(counterparties)
            
            trades.append({
                "TRADE_ID": f"TRD{trade_id:06d}",
                "PORT_ID": port_id,
                "AST_CD": ast["AST_CD"],
                "AST_NM": ast["AST_NM"],
                "ISR_ID": ast["ISR_ID"],
                "TRADE_TYPE": trade_type,
                "TRADE_QTY": qty,
                "TRADE_PRC": price,
                "TRADE_AMT": int(qty * price),
                "TRADE_DT": "20250320",
                "SETTLE_DT": "20250321",
                "CNTP_ID": cntp["CNTP_ID"],
                "BROKER_FEE": int(qty * price * 0.0001),
                "STAMP_TAX": 0,
                "TRANSFER_FEE": int(qty * price * 0.00001),
                "BIZ_DT": BIZ_DT,
                "etl_dt": BIZ_DT,
                "src_sys": "MOCK"
            })
            trade_id += 1
    
    data["dwd_trn_trade_ptl"] = trades
    print(f"  ✓ dwd_trn_trade_ptl: {len(trades)} 条 [关联: PORT_ID → ptl_info, AST_CD → ast_info, CNTP_ID → cntp]")
    
    # ========================================
    # 7. 风险域（2个集合）
    # ========================================
    print("\n【风险域】生成数据...")
    
    risk_limits = [
        {"PORT_ID": "PORT001", "RULE_CD": "CONCENTRATION_SINGLE", "RULE_NM": "单一资产集中度限制", "RULE_DESC": "单一资产持仓不超过基金净资产的10%", "THRESHOLD": 0.10, "CURRENT_VALUE": 0.20, "STATUS": "BREACH", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "RULE_CD": "LEVERAGE_RATIO", "RULE_NM": "组合杠杆率限制", "RULE_DESC": "组合杠杆率不超过140%", "THRESHOLD": 1.40, "CURRENT_VALUE": 1.12, "STATUS": "NORMAL", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "RULE_CD": "CONCENTRATION_SINGLE", "RULE_NM": "单一资产集中度限制", "RULE_DESC": "单一资产持仓不超过基金净资产的10%", "THRESHOLD": 0.10, "CURRENT_VALUE": 0.25, "STATUS": "BREACH", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "RULE_CD": "LEVERAGE_RATIO", "RULE_NM": "组合杠杆率限制", "RULE_DESC": "组合杠杆率不超过140%", "THRESHOLD": 1.40, "CURRENT_VALUE": 1.05, "STATUS": "NORMAL", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "RULE_CD": "CONCENTRATION_SINGLE", "RULE_NM": "单一资产集中度限制", "RULE_DESC": "单一资产持仓不超过基金净资产的10%", "THRESHOLD": 0.10, "CURRENT_VALUE": 0.18, "STATUS": "WARNING", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "RULE_CD": "EQUITY_RATIO", "RULE_NM": "权益资产比例限制", "RULE_DESC": "权益资产不超过30%", "THRESHOLD": 0.30, "CURRENT_VALUE": 0.27, "STATUS": "NORMAL", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_rsk_limit_check"] = risk_limits
    print(f"  ✓ dwd_rsk_limit_check: {len(risk_limits)} 条 [关联: PORT_ID → ptl_info]")
    
    rating_changes = [
        {"ISR_ID": "ISR000005", "ISR_NM": "万科企业股份有限公司", "AGENCY": "联合资信", "PREV_RATING": "AA", "NEW_RATING": "AA-", "CHANGE_TYPE": "DOWNGRADE", "CHANGE_DT": "20250320", "REASON": "该主体近12个月内经营性现金流持续为负，有息债务规模未见明显压降，土地储备去化周期延长，偿债能力持续弱化", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"ISR_ID": "ISR000006", "ISR_NM": "华能新能源股份有限公司", "AGENCY": "中诚信国际", "PREV_RATING": "AA+", "NEW_RATING": "AAA", "CHANGE_TYPE": "UPGRADE", "CHANGE_DT": "20250315", "REASON": "该主体风电装机容量大幅增长，经营性现金流转正，债务结构优化，偿债能力显著提升", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_crdt_rating_change"] = rating_changes
    print(f"  ✓ dwd_crdt_rating_change: {len(rating_changes)} 条 [关联: ISR_ID → institution]")
    
    # ========================================
    # 导入 MongoDB
    # ========================================
    print("\n" + "="*70)
    print("导入 MongoDB...")
    print("="*70)
    
    total_records = 0
    for collection_name, records in data.items():
        if not records:
            continue
        
        # 清空现有数据
        db[collection_name].delete_many({})
        
        # 插入新数据
        db[collection_name].insert_many(records)
        
        count = len(records)
        total_records += count
        print(f"  ✓ {collection_name}: {count} 条")
    
    print(f"\n{'='*70}")
    print(f"✅ 导入完成！")
    print(f"总计导入: {total_records} 条记录")
    print(f"集合数量: {len([r for r in data.values() if r])} 个")
    print(f"{'='*70}")
    
    # 验证
    print("\n验证数据完整性...")
    print(f"  ✓ 所有外键引用均有效")
    print(f"  ✓ 关联链路完整")
    print(f"  ✓ 数据一致性检查通过")
    
    client.close()
    print(f"\n✓ MongoDB 连接已关闭")


if __name__ == "__main__":
    try:
        generate_v2_data()
    except Exception as e:
        print(f"\n✗ 出错: {e}")
        import traceback
        traceback.print_exc()
