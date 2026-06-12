#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成关联 Mock 数据（简化可靠版）
"""

import json
from pathlib import Path

# 业务日期
BIZ_DT = "20250324"

def generate_data():
    """生成具有复杂关联的数据"""
    
    data = {}
    
    # ========================================
    # 1. 主体域（基础表）
    # ========================================
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
    ]
    data["dwd_isr_institution"] = institutions
    print(f"✓ dwd_isr_institution: {len(institutions)} 条")
    
    # ========================================
    # 2. 资产域（关联到主体域）
    # ========================================
    assets = [
        {
            "AST_CD": "019601.IB",
            "AST_NM": "25国债03",
            "AST_TYPE": "BOND",
            "AST_SUB_TYPE": "CGB",
            "ISR_ID": "ISR000001",  # ← 关联财政部
            "CCY": "CNY",
            "LIST_DT": "20250115",
            "MATURITY_DT": "20350115",
            "COUPON_RATE": 0.0195,
            "ISSUE_AMT": 50000000000,
            "MARKET": "银行间",
            "BOND_TERM": 10,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "AST_CD": "230210.IB",
            "AST_NM": "23国开10",
            "AST_TYPE": "BOND",
            "AST_SUB_TYPE": "POLICY",
            "ISR_ID": "ISR000002",  # ← 关联国开行
            "CCY": "CNY",
            "LIST_DT": "20230615",
            "MATURITY_DT": "20330615",
            "COUPON_RATE": 0.0278,
            "ISSUE_AMT": 120000000000,
            "MARKET": "银行间",
            "BOND_TERM": 10,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "AST_CD": "2480006.IB",
            "AST_NM": "24工商银行MTN001",
            "AST_TYPE": "BOND",
            "AST_SUB_TYPE": "MTN",
            "ISR_ID": "ISR000003",  # ← 关联工商银行
            "CCY": "CNY",
            "LIST_DT": "20240315",
            "MATURITY_DT": "20270315",
            "COUPON_RATE": 0.0310,
            "ISSUE_AMT": 10000000000,
            "MARKET": "银行间",
            "BOND_TERM": 3,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "AST_CD": "112311.SZ",
            "AST_NM": "24万科MTN003",
            "AST_TYPE": "BOND",
            "AST_SUB_TYPE": "MTN",
            "ISR_ID": "ISR000005",  # ← 关联万科
            "CCY": "CNY",
            "LIST_DT": "20240520",
            "MATURITY_DT": "20260520",
            "COUPON_RATE": 0.0450,
            "ISSUE_AMT": 3000000000,
            "MARKET": "深交所",
            "BOND_TERM": 2,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
    ]
    data["dwd_ast_info"] = assets
    print(f"✓ dwd_ast_info: {len(assets)} 条 [关联: ISR_ID → dwd_isr_institution]")
    
    # ========================================
    # 3. 产品域（关联到资产域）
    # ========================================
    portfolios = [
        {
            "PORT_ID": "PORT001",
            "PORT_NM": "稳健配置一号",
            "PORT_SHORT_NM": "稳健1号",
            "PORT_TYPE": "MIXED",
            "RISK_LVL": "R3",
            "ESTAB_DT": "20210601",
            "CCY": "CNY",
            "BENCHMARK": "中债综合指数*70%+沪深300*30%",
            "SHR_NAV": 1.0512,
            "ACC_NAV": 1.1835,
            "AUM": 1250000000,
            "MGR_INST": "ISR000003",  # ← 关联工商银行
            "CUSTODY_BANK": "ISR000003",
            "STATUS": "ACTIVE",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "PORT_ID": "PORT002",
            "PORT_NM": "纯债精选二号",
            "PORT_SHORT_NM": "纯债2号",
            "PORT_TYPE": "BOND",
            "RISK_LVL": "R2",
            "ESTAB_DT": "20200315",
            "CCY": "CNY",
            "BENCHMARK": "中债综合财富指数",
            "SHR_NAV": 1.0285,
            "ACC_NAV": 1.1520,
            "AUM": 2800000000,
            "MGR_INST": "ISR000003",
            "CUSTODY_BANK": "ISR000003",
            "STATUS": "ACTIVE",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
    ]
    data["dwd_ptl_info"] = portfolios
    print(f"✓ dwd_ptl_info: {len(portfolios)} 条 [关联: MGR_INST → dwd_isr_institution]")
    
    # ========================================
    # 4. 产品持仓表（关联产品域+资产域）
    # ========================================
    holdings = [
        {
            "PORT_ID": "PORT001",  # ← 关联产品
            "AST_CD": "019601.IB",  # ← 关联资产
            "AST_NM": "25国债03",
            "AST_TYPE": "BOND",
            "HLD_RATIO": 0.15,
            "MKT_VAL": 187500000,
            "QTY": 1875000,
            "COST_VAL": 186000000,
            "UNREALIZED_PNL": 1500000,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "PORT_ID": "PORT001",
            "AST_CD": "230210.IB",
            "AST_NM": "23国开10",
            "AST_TYPE": "BOND",
            "HLD_RATIO": 0.12,
            "MKT_VAL": 150000000,
            "QTY": 1500000,
            "COST_VAL": 149000000,
            "UNREALIZED_PNL": 1000000,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "PORT_ID": "PORT001",
            "AST_CD": "112311.SZ",
            "AST_NM": "24万科MTN003",
            "AST_TYPE": "BOND",
            "HLD_RATIO": 0.05,
            "MKT_VAL": 62500000,
            "QTY": 650000,
            "COST_VAL": 63000000,
            "UNREALIZED_PNL": -500000,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "PORT_ID": "PORT002",
            "AST_CD": "019601.IB",
            "AST_NM": "25国债03",
            "AST_TYPE": "BOND",
            "HLD_RATIO": 0.25,
            "MKT_VAL": 700000000,
            "QTY": 7000000,
            "COST_VAL": 695000000,
            "UNREALIZED_PNL": 5000000,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "PORT_ID": "PORT002",
            "AST_CD": "230210.IB",
            "AST_NM": "23国开10",
            "AST_TYPE": "BOND",
            "HLD_RATIO": 0.18,
            "MKT_VAL": 504000000,
            "QTY": 5040000,
            "COST_VAL": 500000000,
            "UNREALIZED_PNL": 4000000,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
    ]
    data["dwd_ptl_ast_hld"] = holdings
    print(f"✓ dwd_ptl_ast_hld: {len(holdings)} 条 [关联: PORT_ID → dwd_ptl_info, AST_CD → dwd_ast_info]")
    
    # ========================================
    # 5. 客户域（关联到产品域）
    # ========================================
    customers = [
        {
            "CUSTOMER_ID": "CUS0000001",
            "CUST_NM": "张明远",
            "CUST_TYPE": "IND",
            "GENDER": "M",
            "BIRTH_DT": "19780815",
            "ID_TYPE": "IDCARD",
            "ID_NO": "310115197808157612",
            "PHONE": "13812345001",
            "EMAIL": "zhangmingyuan@163.com",
            "ADDR": "上海市浦东新区世纪大道1090号",
            "RISK_LVL": "C3",
            "OPEN_DT": "20210601",
            "CHANNEL": "DIRECT",
            "SELLER_ID": "SEL00001",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "CUSTOMER_ID": "CUS0000002",
            "CUST_NM": "李秀芬",
            "CUST_TYPE": "IND",
            "GENDER": "F",
            "BIRTH_DT": "19820320",
            "ID_TYPE": "IDCARD",
            "ID_NO": "110108198203208425",
            "PHONE": "13912345002",
            "EMAIL": "lixiufen@126.com",
            "ADDR": "北京市朝阳区建国门外大街甲6号",
            "RISK_LVL": "C2",
            "OPEN_DT": "20200315",
            "CHANNEL": "BANK",
            "SELLER_ID": "SEL00002",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
    ]
    data["dwd_cust_info"] = customers
    print(f"✓ dwd_cust_info: {len(customers)} 条")
    
    # ========================================
    # 6. 客户持仓表（关联客户+产品）
    # ========================================
    customer_holdings = [
        {
            "CUSTOMER_ID": "CUS0000001",  # ← 关联客户
            "PORT_ID": "PORT001",  # ← 关联产品
            "HLD_AMT": 5000000,
            "HLD_SHARE": 4741379.31,
            "PURCHASE_DT": "20240101",
            "LAST_NAV": 1.0512,
            "UNREALIZED_PNL": 256000,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "CUSTOMER_ID": "CUS0000001",
            "PORT_ID": "PORT002",
            "HLD_AMT": 3000000,
            "HLD_SHARE": 2917647.06,
            "PURCHASE_DT": "20240601",
            "LAST_NAV": 1.0285,
            "UNREALIZED_PNL": 85500,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "CUSTOMER_ID": "CUS0000002",
            "PORT_ID": "PORT002",
            "HLD_AMT": 10000000,
            "HLD_SHARE": 9724770.64,
            "PURCHASE_DT": "20230101",
            "LAST_NAV": 1.0285,
            "UNREALIZED_PNL": 285000,
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
    ]
    data["dwd_cust_ptl_hld"] = customer_holdings
    print(f"✓ dwd_cust_ptl_hld: {len(customer_holdings)} 条 [关联: CUSTOMER_ID → dwd_cust_info, PORT_ID → dwd_ptl_info]")
    
    # ========================================
    # 7. 资产估值表（高度关联到资产域）
    # ========================================
    valuations = [
        {
            "AST_CD": "019601.IB",  # ← 关联资产
            "BIZ_DT": BIZ_DT,
            "VAL_NET_PRC": 99.5600,
            "VAL_FULL_PRC": 99.8012,
            "VAL_YIELD": 0.0215,
            "DURATION": 9.5200,
            "CONVEXITY": 98.5,
            "RATING_AGENCY": "中诚信国际",
            "VAL_SRC": "CCDC",
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "AST_CD": "230210.IB",
            "BIZ_DT": BIZ_DT,
            "VAL_NET_PRC": 100.8200,
            "VAL_FULL_PRC": 101.5680,
            "VAL_YIELD": 0.0265,
            "DURATION": 7.2100,
            "CONVEXITY": 62.4,
            "RATING_AGENCY": "联合资信",
            "VAL_SRC": "CCDC",
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "AST_CD": "112311.SZ",
            "BIZ_DT": BIZ_DT,
            "VAL_NET_PRC": 95.8800,
            "VAL_FULL_PRC": 96.5420,
            "VAL_YIELD": 0.0512,
            "DURATION": 1.1500,
            "CONVEXITY": 1.8,
            "RATING_AGENCY": "联合资信",
            "VAL_SRC": "CSI",
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
    ]
    data["dwd_ast_info_ch"] = valuations
    print(f"✓ dwd_ast_info_ch: {len(valuations)} 条 [关联: AST_CD → dwd_ast_info]")
    
    # ========================================
    # 8. 风控限额表（关联产品域）
    # ========================================
    risk_limits = [
        {
            "PORT_ID": "PORT001",  # ← 关联产品
            "RULE_CD": "CONCENTRATION_SINGLE",
            "RULE_NM": "单一资产集中度限制",
            "RULE_DESC": "单一资产持仓不超过基金净资产的10%",
            "THRESHOLD": 0.10,
            "CURRENT_VALUE": 0.15,  # 超标！
            "STATUS": "WARNING",
            "CHECK_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "PORT_ID": "PORT002",
            "RULE_CD": "CONCENTRATION_SINGLE",
            "RULE_NM": "单一资产集中度限制",
            "RULE_DESC": "单一资产持仓不超过基金净资产的10%",
            "THRESHOLD": 0.10,
            "CURRENT_VALUE": 0.25,  # 严重超标！
            "STATUS": "BREACH",
            "CHECK_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
    ]
    data["dwd_rsk_limit_check"] = risk_limits
    print(f"✓ dwd_rsk_limit_check: {len(risk_limits)} 条 [关联: PORT_ID → dwd_ptl_info]")
    
    # ========================================
    # 9. 评级变动表（关联主体域）
    # ========================================
    rating_changes = [
        {
            "ISR_ID": "ISR000005",  # ← 关联万科
            "ISR_NM": "万科企业股份有限公司",
            "AGENCY": "联合资信",
            "PREV_RATING": "AA",
            "NEW_RATING": "AA-",
            "CHANGE_TYPE": "DOWNGRADE",
            "CHANGE_DT": "20250320",
            "REASON": "该主体近12个月内经营性现金流持续为负，有息债务规模未见明显压降，土地储备去化周期延长，偿债能力持续弱化",
            "BIZ_DT": BIZ_DT,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
    ]
    data["dwd_crdt_rating_change"] = rating_changes
    print(f"✓ dwd_crdt_rating_change: {len(rating_changes)} 条 [关联: ISR_ID → dwd_isr_institution]")
    
    # ========================================
    # 10. 质押表（轻度关联到资产域）
    # ========================================
    pledges = [
        {
            "AST_CD": "019601.IB",  # ← 关联国债
            "BIZ_DT": BIZ_DT,
            "PLEDGE_FLAG": "Y",
            "PLEDGE_RATIO": 0.95,
            "PLEDGE_STD_BOND": 0.98,
            "PLEDGE_BOND_CD": "019601.IB",
            "PLEDGE_NOTE": "用于央行公开市场操作质押",
            "PLEDGE_INST": "中国人民银行",
            "PLEDGE_AMT": 200000000,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
        {
            "AST_CD": "112311.SZ",  # ← 万科债不可质押
            "BIZ_DT": BIZ_DT,
            "PLEDGE_FLAG": "N",
            "PLEDGE_RATIO": 0,
            "PLEDGE_STD_BOND": 0,
            "PLEDGE_BOND_CD": "",
            "PLEDGE_NOTE": "不可质押，信用债评级低于AA",
            "PLEDGE_INST": "",
            "PLEDGE_AMT": 0,
            "etl_dt": BIZ_DT,
            "src_sys": "MOCK"
        },
    ]
    data["dwd_ast_pledge"] = pledges
    print(f"✓ dwd_ast_pledge: {len(pledges)} 条 [关联: AST_CD → dwd_ast_info]")
    
    return data


def main():
    """主函数"""
    print("开始生成关联 Mock 数据...")
    print("="*60)
    
    # 生成数据
    data = generate_data()
    
    # 保存
    output_path = Path("d:/portfilio/scripts/zy_data_mock_associated.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    file_size = output_path.stat().st_size
    print("="*60)
    print(f"✓ 已保存到: {output_path}")
    print(f"文件大小: {file_size / 1024:.2f} KB")
    print(f"集合数量: {len(data)}")
    
    # 生成关联说明
    print("\n关联关系说明:")
    print("  1. 直接关联: ISR_ID, AST_CD, PORT_ID, CUSTOMER_ID")
    print("  2. 间接关联: 客户→产品→资产→发行人")
    print("  3. 高度关联: 资产有估值/质押/评级等多表")
    print("  4. 重度关联: 一个产品持有多个资产")
    print("  5. 轻度关联: 部分资产有质押信息")
    
    print("\nAI 可以分析的场景:")
    print("  - 客户风险敞口分析（通过产品持仓穿透到资产和发行人）")
    print("  - 集中度风险（产品持仓超标）")
    print("  - 评级下调影响（万科→产品→客户）")
    print("  - 质押风险分析")
    print("  - 估值对比分析")


if __name__ == "__main__":
    main()
