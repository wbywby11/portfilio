#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成关联 Mock 数据并导入 MongoDB

功能：
1. 生成具有复杂关联关系的数据
2. 直接导入 MongoDB
3. 验证数据完整性
"""

import json
from pymongo import MongoClient
from datetime import datetime

# 配置
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"
BIZ_DT = "20250324"

def generate_and_import():
    """生成并导入数据"""
    
    print("="*60)
    print("ZY 数据域关联 Mock 数据生成器")
    print("="*60)
    
    # 连接 MongoDB
    print("\n连接 MongoDB...")
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    # 测试连接
    client.admin.command('ping')
    print(f"✓ 已连接到 {DB_NAME} 数据库\n")
    
    data = {}
    
    # ========================================
    # 1. 主体域 - 机构信息
    # ========================================
    print("生成主体域数据...")
    institutions = [
        {
            "ISR_ID": "ISR000001",
            "ISR_NM": "中华人民共和国财政部",
            "ISR_SHORT_NM": "财政部",
            "ISR_TYPE": "SOVEREIGN",
            "CREDIT_CD": "11100000000100176T",
            "INDUSTRY_CD": "S9510",
            "REG_PROV": "北京",
            "LIST_FLAG": "N",
            "REG_CAP_AMT": 0,
            "EST_DT": "19490701",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "ISR_ID": "ISR000002",
            "ISR_NM": "国家开发银行",
            "ISR_SHORT_NM": "国开行",
            "ISR_TYPE": "POLICY_BANK",
            "CREDIT_CD": "91110000100001269U",
            "INDUSTRY_CD": "J6621",
            "REG_PROV": "北京",
            "LIST_FLAG": "N",
            "REG_CAP_AMT": 421248000000,
            "EST_DT": "19940317",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "ISR_ID": "ISR000003",
            "ISR_NM": "中国工商银行股份有限公司",
            "ISR_SHORT_NM": "工商银行",
            "ISR_TYPE": "COMMERCIAL_BANK",
            "CREDIT_CD": "9111000010000016XA",
            "INDUSTRY_CD": "J6611",
            "REG_PROV": "北京",
            "LIST_FLAG": "Y",
            "REG_CAP_AMT": 356406000000,
            "EST_DT": "19840101",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "ISR_ID": "ISR000004",
            "ISR_NM": "中国农业发展银行",
            "ISR_SHORT_NM": "农发行",
            "ISR_TYPE": "POLICY_BANK",
            "CREDIT_CD": "91110000100003790Y",
            "INDUSTRY_CD": "J6621",
            "REG_PROV": "北京",
            "LIST_FLAG": "N",
            "REG_CAP_AMT": 57074000000,
            "EST_DT": "19941118",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "ISR_ID": "ISR000005",
            "ISR_NM": "万科企业股份有限公司",
            "ISR_SHORT_NM": "万科",
            "ISR_TYPE": "CORPORATE",
            "CREDIT_CD": "914403001922038216",
            "INDUSTRY_CD": "K7010",
            "REG_PROV": "广东",
            "LIST_FLAG": "Y",
            "REG_CAP_AMT": 11039152192,
            "EST_DT": "19840501",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "ISR_ID": "ISR000006",
            "ISR_NM": "华能新能源股份有限公司",
            "ISR_SHORT_NM": "华能新能源",
            "ISR_TYPE": "CORPORATE",
            "CREDIT_CD": "91110000717825307B",
            "INDUSTRY_CD": "D4412",
            "REG_PROV": "北京",
            "LIST_FLAG": "Y",
            "REG_CAP_AMT": 8020000000,
            "EST_DT": "20080801",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "ISR_ID": "ISR000007",
            "ISR_NM": "招商银行股份有限公司",
            "ISR_SHORT_NM": "招商银行",
            "ISR_TYPE": "COMMERCIAL_BANK",
            "CREDIT_CD": "91440300100018588H",
            "INDUSTRY_CD": "J6611",
            "REG_PROV": "广东",
            "LIST_FLAG": "Y",
            "REG_CAP_AMT": 25220900000,
            "EST_DT": "19870408",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "ISR_ID": "ISR000008",
            "ISR_NM": "中国平安保险(集团)股份有限公司",
            "ISR_SHORT_NM": "中国平安",
            "ISR_TYPE": "CORPORATE",
            "CREDIT_CD": "91440300100019502G",
            "INDUSTRY_CD": "J6812",
            "REG_PROV": "广东",
            "LIST_FLAG": "Y",
            "REG_CAP_AMT": 18280200000,
            "EST_DT": "19880301",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        }
    ]
    data["dwd_isr_institution"] = institutions
    print(f"  ✓ dwd_isr_institution: {len(institutions)} 条")
    
    # ========================================
    # 2. 资产域 - 资产基础信息（关联到机构）
    # ========================================
    print("\n生成资产域数据...")
    assets = [
        {
            "AST_CD": "019601.IB", "AST_NM": "25国债03", "AST_TYPE": "BOND", "AST_SUB_TYPE": "CGB",
            "ISR_ID": "ISR000001", "CCY": "CNY", "LIST_DT": "20250115", "MATURITY_DT": "20350115",
            "COUPON_RATE": 0.0195, "ISSUE_AMT": 50000000000, "MARKET": "银行间", "BOND_TERM": 10,
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "019735.IB", "AST_NM": "25特别国债03", "AST_TYPE": "BOND", "AST_SUB_TYPE": "CGB",
            "ISR_ID": "ISR000001", "CCY": "CNY", "LIST_DT": "20250220", "MATURITY_DT": "20550220",
            "COUPON_RATE": 0.0245, "ISSUE_AMT": 80000000000, "MARKET": "银行间", "BOND_TERM": 30,
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "230210.IB", "AST_NM": "23国开10", "AST_TYPE": "BOND", "AST_SUB_TYPE": "POLICY",
            "ISR_ID": "ISR000002", "CCY": "CNY", "LIST_DT": "20230615", "MATURITY_DT": "20330615",
            "COUPON_RATE": 0.0278, "ISSUE_AMT": 120000000000, "MARKET": "银行间", "BOND_TERM": 10,
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "220215.IB", "AST_NM": "22国开15", "AST_TYPE": "BOND", "AST_SUB_TYPE": "POLICY",
            "ISR_ID": "ISR000002", "CCY": "CNY", "LIST_DT": "20221020", "MATURITY_DT": "20321020",
            "COUPON_RATE": 0.0295, "ISSUE_AMT": 90000000000, "MARKET": "银行间", "BOND_TERM": 10,
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "2480006.IB", "AST_NM": "24工商银行MTN001", "AST_TYPE": "BOND", "AST_SUB_TYPE": "MTN",
            "ISR_ID": "ISR000003", "CCY": "CNY", "LIST_DT": "20240315", "MATURITY_DT": "20270315",
            "COUPON_RATE": 0.0310, "ISSUE_AMT": 10000000000, "MARKET": "银行间", "BOND_TERM": 3,
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "112311.SZ", "AST_NM": "24万科MTN003", "AST_TYPE": "BOND", "AST_SUB_TYPE": "MTN",
            "ISR_ID": "ISR000005", "CCY": "CNY", "LIST_DT": "20240520", "MATURITY_DT": "20260520",
            "COUPON_RATE": 0.0450, "ISSUE_AMT": 3000000000, "MARKET": "深交所", "BOND_TERM": 2,
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "600036.SH", "AST_NM": "招商银行", "AST_TYPE": "STOCK", "AST_SUB_TYPE": "A_SHARE",
            "ISR_ID": "ISR000007", "CCY": "CNY", "LIST_DT": "20020409", "MARKET": "上交所",
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "601318.SH", "AST_NM": "中国平安", "AST_TYPE": "STOCK", "AST_SUB_TYPE": "A_SHARE",
            "ISR_ID": "ISR000008", "CCY": "CNY", "LIST_DT": "20070301", "MARKET": "上交所",
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "510300.SH", "AST_NM": "沪深300ETF", "AST_TYPE": "FUND", "AST_SUB_TYPE": "ETF",
            "ISR_ID": "ISR000007", "CCY": "CNY", "LIST_DT": "20120526", "MARKET": "上交所",
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "511260.SH", "AST_NM": "十年国债ETF", "AST_TYPE": "FUND", "AST_SUB_TYPE": "ETF",
            "ISR_ID": "ISR000003", "CCY": "CNY", "LIST_DT": "20200320", "MARKET": "上交所",
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "127080.SZ", "AST_NM": "2024华能新能ABS001优先A", "AST_TYPE": "ABS", "AST_SUB_TYPE": "ABS_SENIOR",
            "ISR_ID": "ISR000006", "CCY": "CNY", "LIST_DT": "20240801", "MATURITY_DT": "20270801",
            "COUPON_RATE": 0.0330, "ISSUE_AMT": 2000000000, "MARKET": "深交所", "BOND_TERM": 3,
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "AST_CD": "180401.IB", "AST_NM": "24农发绿色债01", "AST_TYPE": "BOND", "AST_SUB_TYPE": "POLICY",
            "ISR_ID": "ISR000004", "CCY": "CNY", "LIST_DT": "20240410", "MATURITY_DT": "20290410",
            "COUPON_RATE": 0.0255, "ISSUE_AMT": 30000000000, "MARKET": "银行间", "BOND_TERM": 5,
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        }
    ]
    data["dwd_ast_info"] = assets
    print(f"  ✓ dwd_ast_info: {len(assets)} 条 [关联: ISR_ID → dwd_isr_institution]")
    
    # ========================================
    # 3. 产品域 - 产品信息
    # ========================================
    print("\n生成产品域数据...")
    portfolios = [
        {
            "PORT_ID": "PORT001", "PORT_NM": "稳健配置一号", "PORT_SHORT_NM": "稳健1号",
            "PORT_TYPE": "MIXED", "RISK_LVL": "R3", "ESTAB_DT": "20210601", "CCY": "CNY",
            "BENCHMARK": "中债综合指数*70%+沪深300*30%", "SHR_NAV": 1.0512, "ACC_NAV": 1.1835,
            "AUM": 1250000000, "MGR_INST": "ISR000008", "CUSTODY_BANK": "ISR000003", "STATUS": "ACTIVE",
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "PORT_ID": "PORT002", "PORT_NM": "纯债精选二号", "PORT_SHORT_NM": "纯债2号",
            "PORT_TYPE": "BOND", "RISK_LVL": "R2", "ESTAB_DT": "20200315", "CCY": "CNY",
            "BENCHMARK": "中债综合财富指数", "SHR_NAV": 1.0285, "ACC_NAV": 1.1520,
            "AUM": 2800000000, "MGR_INST": "ISR000008", "CUSTODY_BANK": "ISR000003", "STATUS": "ACTIVE",
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "PORT_ID": "PORT003", "PORT_NM": "混合增强三号", "PORT_SHORT_NM": "混合3号",
            "PORT_TYPE": "MIXED", "RISK_LVL": "R3", "ESTAB_DT": "20220801", "CCY": "CNY",
            "BENCHMARK": "中债综合指数*50%+沪深300*50%", "SHR_NAV": 0.9875, "ACC_NAV": 0.9875,
            "AUM": 870000000, "MGR_INST": "ISR000005", "CUSTODY_BANK": "ISR000003", "STATUS": "ACTIVE",
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "PORT_ID": "PORT004", "PORT_NM": "短融货币四号", "PORT_SHORT_NM": "货币4号",
            "PORT_TYPE": "MMF", "RISK_LVL": "R1", "ESTAB_DT": "20190101", "CCY": "CNY",
            "BENCHMARK": "七日年化收益率基准", "SHR_NAV": 1.0000, "ACC_NAV": 1.0000,
            "AUM": 5000000000, "MGR_INST": "ISR000008", "CUSTODY_BANK": "ISR000003", "STATUS": "ACTIVE",
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        },
        {
            "PORT_ID": "PORT005", "PORT_NM": "指数增强五号", "PORT_SHORT_NM": "指增5号",
            "PORT_TYPE": "INDEX", "RISK_LVL": "R4", "ESTAB_DT": "20230601", "CCY": "CNY",
            "BENCHMARK": "沪深300指数", "SHR_NAV": 1.1250, "ACC_NAV": 1.1250,
            "AUM": 650000000, "MGR_INST": "ISR000007", "CUSTODY_BANK": "ISR000003", "STATUS": "ACTIVE",
            "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"
        }
    ]
    data["dwd_ptl_info"] = portfolios
    print(f"  ✓ dwd_ptl_info: {len(portfolios)} 条 [关联: MGR_INST → dwd_isr_institution]")
    
    # ========================================
    # 4. 产品持仓表（关联产品+资产）
    # ========================================
    print("\n生成产品持仓数据...")
    holdings = [
        # PORT001 持仓
        {"PORT_ID": "PORT001", "AST_CD": "019601.IB", "AST_NM": "25国债03", "AST_TYPE": "BOND", "HLD_RATIO": 0.15, "MKT_VAL": 187500000, "QTY": 1875000, "COST_VAL": 186000000, "UNREALIZED_PNL": 1500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "230210.IB", "AST_NM": "23国开10", "AST_TYPE": "BOND", "HLD_RATIO": 0.12, "MKT_VAL": 150000000, "QTY": 1500000, "COST_VAL": 149000000, "UNREALIZED_PNL": 1000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "2480006.IB", "AST_NM": "24工商银行MTN001", "AST_TYPE": "BOND", "HLD_RATIO": 0.08, "MKT_VAL": 100000000, "QTY": 1000000, "COST_VAL": 99500000, "UNREALIZED_PNL": 500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "600036.SH", "AST_NM": "招商银行", "AST_TYPE": "STOCK", "HLD_RATIO": 0.10, "MKT_VAL": 125000000, "QTY": 3000000, "COST_VAL": 120000000, "UNREALIZED_PNL": 5000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "510300.SH", "AST_NM": "沪深300ETF", "AST_TYPE": "FUND", "HLD_RATIO": 0.20, "MKT_VAL": 250000000, "QTY": 50000000, "COST_VAL": 240000000, "UNREALIZED_PNL": 10000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "511260.SH", "AST_NM": "十年国债ETF", "AST_TYPE": "FUND", "HLD_RATIO": 0.18, "MKT_VAL": 225000000, "QTY": 20000000, "COST_VAL": 223000000, "UNREALIZED_PNL": 2000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "AST_CD": "112311.SZ", "AST_NM": "24万科MTN003", "AST_TYPE": "BOND", "HLD_RATIO": 0.05, "MKT_VAL": 62500000, "QTY": 650000, "COST_VAL": 63000000, "UNREALIZED_PNL": -500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        
        # PORT002 持仓（集中度高）
        {"PORT_ID": "PORT002", "AST_CD": "019601.IB", "AST_NM": "25国债03", "AST_TYPE": "BOND", "HLD_RATIO": 0.25, "MKT_VAL": 700000000, "QTY": 7000000, "COST_VAL": 695000000, "UNREALIZED_PNL": 5000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "AST_CD": "019735.IB", "AST_NM": "25特别国债03", "AST_TYPE": "BOND", "HLD_RATIO": 0.20, "MKT_VAL": 560000000, "QTY": 5500000, "COST_VAL": 558000000, "UNREALIZED_PNL": 2000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "AST_CD": "230210.IB", "AST_NM": "23国开10", "AST_TYPE": "BOND", "HLD_RATIO": 0.18, "MKT_VAL": 504000000, "QTY": 5040000, "COST_VAL": 500000000, "UNREALIZED_PNL": 4000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "AST_CD": "2480006.IB", "AST_NM": "24工商银行MTN001", "AST_TYPE": "BOND", "HLD_RATIO": 0.15, "MKT_VAL": 420000000, "QTY": 4200000, "COST_VAL": 418000000, "UNREALIZED_PNL": 2000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "AST_CD": "180401.IB", "AST_NM": "24农发绿色债01", "AST_TYPE": "BOND", "HLD_RATIO": 0.12, "MKT_VAL": 336000000, "QTY": 3400000, "COST_VAL": 335000000, "UNREALIZED_PNL": 1000000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        
        # PORT003 持仓
        {"PORT_ID": "PORT003", "AST_CD": "600036.SH", "AST_NM": "招商银行", "AST_TYPE": "STOCK", "HLD_RATIO": 0.15, "MKT_VAL": 130500000, "QTY": 3100000, "COST_VAL": 128000000, "UNREALIZED_PNL": 2500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "AST_CD": "601318.SH", "AST_NM": "中国平安", "AST_TYPE": "STOCK", "HLD_RATIO": 0.12, "MKT_VAL": 104400000, "QTY": 2200000, "COST_VAL": 102000000, "UNREALIZED_PNL": 2400000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "AST_CD": "510300.SH", "AST_NM": "沪深300ETF", "AST_TYPE": "FUND", "HLD_RATIO": 0.18, "MKT_VAL": 156600000, "QTY": 31000000, "COST_VAL": 155000000, "UNREALIZED_PNL": 1600000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "AST_CD": "019601.IB", "AST_NM": "25国债03", "AST_TYPE": "BOND", "HLD_RATIO": 0.10, "MKT_VAL": 87000000, "QTY": 870000, "COST_VAL": 86500000, "UNREALIZED_PNL": 500000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "AST_CD": "230210.IB", "AST_NM": "23国开10", "AST_TYPE": "BOND", "HLD_RATIO": 0.08, "MKT_VAL": 69600000, "QTY": 696000, "COST_VAL": 69000000, "UNREALIZED_PNL": 600000, "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
    ]
    data["dwd_ptl_ast_hld"] = holdings
    print(f"  ✓ dwd_ptl_ast_hld: {len(holdings)} 条 [关联: PORT_ID → dwd_ptl_info, AST_CD → dwd_ast_info]")
    
    # ========================================
    # 5. 客户信息
    # ========================================
    print("\n生成客户域数据...")
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
    
    # ========================================
    # 6. 客户持仓表（关联客户+产品）
    # ========================================
    print("\n生成客户持仓数据...")
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
    print(f"  ✓ dwd_cust_ptl_hld: {len(customer_holdings)} 条 [关联: CUSTOMER_ID → dwd_cust_info, PORT_ID → dwd_ptl_info]")
    
    # ========================================
    # 7. 资产估值表（高度关联资产）
    # ========================================
    print("\n生成资产估值数据...")
    valuations = [
        {"AST_CD": "019601.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 99.5600, "VAL_FULL_PRC": 99.8012, "VAL_YIELD": 0.0215, "DURATION": 9.5200, "CONVEXITY": 98.5, "RATING_AGENCY": "中诚信国际", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "019735.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 102.3500, "VAL_FULL_PRC": 102.6820, "VAL_YIELD": 0.0238, "DURATION": 18.7600, "CONVEXITY": 425.8, "RATING_AGENCY": "中诚信国际", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "230210.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 100.8200, "VAL_FULL_PRC": 101.5680, "VAL_YIELD": 0.0265, "DURATION": 7.2100, "CONVEXITY": 62.4, "RATING_AGENCY": "联合资信", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "220215.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 101.2500, "VAL_FULL_PRC": 102.0180, "VAL_YIELD": 0.0282, "DURATION": 6.8500, "CONVEXITY": 55.2, "RATING_AGENCY": "联合资信", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "2480006.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 100.1500, "VAL_FULL_PRC": 100.3215, "VAL_YIELD": 0.0305, "DURATION": 1.9500, "CONVEXITY": 5.2, "RATING_AGENCY": "中诚信国际", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "112311.SZ", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 95.8800, "VAL_FULL_PRC": 96.5420, "VAL_YIELD": 0.0512, "DURATION": 1.1500, "CONVEXITY": 1.8, "RATING_AGENCY": "联合资信", "VAL_SRC": "CSI", "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "180401.IB", "BIZ_DT": BIZ_DT, "VAL_NET_PRC": 98.7600, "VAL_FULL_PRC": 99.0850, "VAL_YIELD": 0.0272, "DURATION": 4.3200, "CONVEXITY": 22.6, "RATING_AGENCY": "联合资信", "VAL_SRC": "CCDC", "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_info_ch"] = valuations
    print(f"  ✓ dwd_ast_info_ch: {len(valuations)} 条 [关联: AST_CD → dwd_ast_info]")
    
    # ========================================
    # 8. 风控限额表（关联产品）
    # ========================================
    print("\n生成风控限额数据...")
    risk_limits = [
        {"PORT_ID": "PORT001", "RULE_CD": "CONCENTRATION_SINGLE", "RULE_NM": "单一资产集中度限制", "RULE_DESC": "单一资产持仓不超过基金净资产的10%", "THRESHOLD": 0.10, "CURRENT_VALUE": 0.20, "STATUS": "BREACH", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT001", "RULE_CD": "LEVERAGE_RATIO", "RULE_NM": "组合杠杆率限制", "RULE_DESC": "组合杠杆率不超过140%", "THRESHOLD": 1.40, "CURRENT_VALUE": 1.12, "STATUS": "NORMAL", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "RULE_CD": "CONCENTRATION_SINGLE", "RULE_NM": "单一资产集中度限制", "RULE_DESC": "单一资产持仓不超过基金净资产的10%", "THRESHOLD": 0.10, "CURRENT_VALUE": 0.25, "STATUS": "BREACH", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT002", "RULE_CD": "LEVERAGE_RATIO", "RULE_NM": "组合杠杆率限制", "RULE_DESC": "组合杠杆率不超过140%", "THRESHOLD": 1.40, "CURRENT_VALUE": 1.05, "STATUS": "NORMAL", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "RULE_CD": "CONCENTRATION_SINGLE", "RULE_NM": "单一资产集中度限制", "RULE_DESC": "单一资产持仓不超过基金净资产的10%", "THRESHOLD": 0.10, "CURRENT_VALUE": 0.18, "STATUS": "WARNING", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"PORT_ID": "PORT003", "RULE_CD": "EQUITY_RATIO", "RULE_NM": "权益资产比例限制", "RULE_DESC": "权益资产不超过30%", "THRESHOLD": 0.30, "CURRENT_VALUE": 0.27, "STATUS": "NORMAL", "CHECK_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_rsk_limit_check"] = risk_limits
    print(f"  ✓ dwd_rsk_limit_check: {len(risk_limits)} 条 [关联: PORT_ID → dwd_ptl_info]")
    
    # ========================================
    # 9. 评级变动表（关联机构）
    # ========================================
    print("\n生成评级变动数据...")
    rating_changes = [
        {"ISR_ID": "ISR000005", "ISR_NM": "万科企业股份有限公司", "AGENCY": "联合资信", "PREV_RATING": "AA", "NEW_RATING": "AA-", "CHANGE_TYPE": "DOWNGRADE", "CHANGE_DT": "20250320", "REASON": "该主体近12个月内经营性现金流持续为负，有息债务规模未见明显压降，土地储备去化周期延长，偿债能力持续弱化", "BIZ_DT": BIZ_DT, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_crdt_rating_change"] = rating_changes
    print(f"  ✓ dwd_crdt_rating_change: {len(rating_changes)} 条 [关联: ISR_ID → dwd_isr_institution]")
    
    # ========================================
    # 10. 质押表（轻度关联资产）
    # ========================================
    print("\n生成质押数据...")
    pledges = [
        {"AST_CD": "019601.IB", "BIZ_DT": BIZ_DT, "PLEDGE_FLAG": "Y", "PLEDGE_RATIO": 0.95, "PLEDGE_STD_BOND": 0.98, "PLEDGE_BOND_CD": "019601.IB", "PLEDGE_NOTE": "用于央行公开市场操作质押", "PLEDGE_INST": "中国人民银行", "PLEDGE_AMT": 200000000, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "230210.IB", "BIZ_DT": BIZ_DT, "PLEDGE_FLAG": "Y", "PLEDGE_RATIO": 0.90, "PLEDGE_STD_BOND": 0.95, "PLEDGE_BOND_CD": "230210.IB", "PLEDGE_NOTE": "银行间质押式回购", "PLEDGE_INST": "中央国债登记结算有限责任公司", "PLEDGE_AMT": 150000000, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "2480006.IB", "BIZ_DT": BIZ_DT, "PLEDGE_FLAG": "Y", "PLEDGE_RATIO": 0.85, "PLEDGE_STD_BOND": 0.88, "PLEDGE_BOND_CD": "2480006.IB", "PLEDGE_NOTE": "上清所质押式回购", "PLEDGE_INST": "上海清算所", "PLEDGE_AMT": 80000000, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "180401.IB", "BIZ_DT": BIZ_DT, "PLEDGE_FLAG": "Y", "PLEDGE_RATIO": 0.88, "PLEDGE_STD_BOND": 0.92, "PLEDGE_BOND_CD": "180401.IB", "PLEDGE_NOTE": "绿色债券质押", "PLEDGE_INST": "中央国债登记结算有限责任公司", "PLEDGE_AMT": 100000000, "etl_dt": BIZ_DT, "src_sys": "MOCK"},
        {"AST_CD": "112311.SZ", "BIZ_DT": BIZ_DT, "PLEDGE_FLAG": "N", "PLEDGE_RATIO": 0, "PLEDGE_STD_BOND": 0, "PLEDGE_BOND_CD": "", "PLEDGE_NOTE": "不可质押，信用债评级低于AA", "PLEDGE_INST": "", "PLEDGE_AMT": 0, "etl_dt": BIZ_DT, "src_sys": "MOCK"}
    ]
    data["dwd_ast_pledge"] = pledges
    print(f"  ✓ dwd_ast_pledge: {len(pledges)} 条 [关联: AST_CD → dwd_ast_info]")
    
    # ========================================
    # 导入 MongoDB
    # ========================================
    print("\n" + "="*60)
    print("导入 MongoDB...")
    print("="*60)
    
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
    
    print(f"\n{'='*60}")
    print(f"✅ 导入完成！")
    print(f"总计导入: {total_records} 条记录")
    print(f"集合数量: {len([r for r in data.values() if r])} 个")
    print(f"{'='*60}")
    
    # ========================================
    # 验证数据完整性
    # ========================================
    print("\n验证数据完整性...")
    
    # 检查所有持仓的资产是否存在
    holdings = list(db.dwd_ptl_ast_hld.find())
    assets = set(r['AST_CD'] for r in db.dwd_ast_info.find())
    invalid_holdings = [h for h in holdings if h['AST_CD'] not in assets]
    
    if invalid_holdings:
        print(f"  ✗ 发现 {len(invalid_holdings)} 条持仓引用了不存在的资产")
    else:
        print(f"  ✓ 所有产品持仓的资产都存在")
    
    # 检查所有客户持仓的产品是否存在
    cust_holdings = list(db.dwd_cust_ptl_hld.find())
    portfolios = set(r['PORT_ID'] for r in db.dwd_ptl_info.find())
    invalid_cust = [c for c in cust_holdings if c['PORT_ID'] not in portfolios]
    
    if invalid_cust:
        print(f"  ✗ 发现 {len(invalid_cust)} 条客户持仓引用了不存在的产品")
    else:
        print(f"  ✓ 所有客户持仓的产品都存在")
    
    # 检查所有资产的发行人是否存在
    all_assets = list(db.dwd_ast_info.find())
    institutions = set(r['ISR_ID'] for r in db.dwd_isr_institution.find())
    invalid_assets = [a for a in all_assets if a['ISR_ID'] not in institutions]
    
    if invalid_assets:
        print(f"  ✗ 发现 {len(invalid_assets)} 条资产引用了不存在的发行人")
    else:
        print(f"  ✓ 所有资产的发行人都存在")
    
    print(f"\n✓ 数据完整性验证完成")
    
    # 打印关联关系统计
    print("\n关联关系统计:")
    print(f"  - 直接关联: {len(holdings) + len(cust_holdings) + len(all_assets)} 条外键引用")
    print(f"  - 间接关联: 客户→产品→资产→发行人 (穿透链路)")
    print(f"  - 高度关联: 资产有估值/质押等多表关联")
    print(f"  - 重度关联: 产品平均持有 {len(holdings)/len(portfolios):.1f} 只资产")
    print(f"  - 轻度关联: {len(pledges)}/{len(all_assets)} 只资产有质押信息")
    
    client.close()
    print(f"\n✓ MongoDB 连接已关闭")


if __name__ == "__main__":
    try:
        generate_and_import()
    except Exception as e:
        print(f"\n✗ 出错: {e}")
        import traceback
        traceback.print_exc()
