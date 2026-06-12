# -*- coding: utf-8 -*-
"""最终抽查：对修复过的关键表抽查 3-5 条样本，验证无占位符、数据多样化。"""
import json
from collections import Counter
from pymongo import MongoClient

db = MongoClient("mongodb://localhost:27017")["asset_allocation"]

CHECK_TABLES = {
    "dwd_cust_info": ["CUSTOMER_NAME", "CUST_NAME", "CUST_NM", "BIRTH_DT", "GENDER"],
    "dwd_cust_belong": ["CUST_ID", "CUST_NAME"],
    "dwd_cust_trade": ["CUST_ID", "CUST_NAME", "PROD_CD", "PROD_NAME"],
    "dwd_cust_make_pstn_info": ["CUST_NAME", "PARENT_PROD_CD", "PROD_NAME"],
    "dwd_mkt_fund": ["AST_CD", "AST_NAME", "FUND_NM", "FUND_MANAGER"],
    "dwd_mkt_stock": ["AST_CD", "AST_NAME", "STOCK_NM", "INDUSTRY_NM"],
    "dwd_mkt_bond": ["AST_CD", "AST_NAME"],
    "dwd_mkt_yield_curve": ["CURVE_NAME", "TERM"],
    "dwd_isr_institution": ["CUSTOMER_NAME", "CREDIT_CD"],
    "dwd_isr_trd_cntp": ["CNTP_ID", "CNTP_NM", "SETT_BANK"],
    "dwd_ptl_info": ["PROD_CD", "PROD_NSP_PRPR_NM", "PORT_NM", "DMSTC_CSTDY_ORG_CD"],
    "dwd_ptl_channel": ["PROD_CD", "PROD_NAME", "CHANNEL_CD", "CHANNEL_NAME"],
    "dwd_ptl_nav": ["PROD_CD", "PROD_NAME"],
    "dwd_ast_info": ["AST_CD", "AST_ABBR", "CUSTOMER_NAME"],
    "dwd_ast_calc_rule": ["AST_CD", "AST_NAME", "RULE_CD", "RULE_NM"],
    "dwd_ast_pledge": ["AST_CD", "PLEDGE_BOND_CD", "PLEDGEE"],
    "dwd_ast_fund_manager": ["AST_CD", "MANAGER_NM"],
    "dwd_val_bal": ["PROD_NAME", "ACC_CD", "ACC_NM", "ACCOUNT_NAME"],
    "dwd_val_detail": ["AST_CD", "AST_NAME"],
    "dwd_sls_sales": ["PROD_CD", "PROD_NAME", "CUST_NAME"],
    "dwd_trn_trade_ptl": ["PROD_NAME", "CUST_NAME", "AST_CD"],
    "dwd_trn_trade_fund": ["CNTP_NM"],
}

print("=" * 80)
print("最终验证报告：抽查关键字段样本")
print("=" * 80)
for cname, fields in CHECK_TABLES.items():
    coll = db[cname]
    cnt = coll.count_documents({})
    if cnt == 0:
        continue
    docs = list(coll.find({}, {f: 1 for f in fields} | {"_id": 0}).limit(5))
    # 多样性统计
    div = {}
    for f in fields:
        all_vals = [d.get(f) for d in coll.find({}, {f: 1, "_id": 0}).limit(500)]
        nonempty = [str(v) for v in all_vals if v not in (None, "")]
        if nonempty:
            uniq = len(set(nonempty))
            div[f] = f"{uniq}种/{len(nonempty)}行"
    print(f"\n## {cname} ({cnt}行)")
    print(f"   字段多样性: {div}")
    print("   抽样:")
    for d in docs[:3]:
        print(f"     - {json.dumps(d, ensure_ascii=False, default=str)[:200]}")

print("\n" + "=" * 80)
print("跨表一致性验证：CUST_001 在不同表中是否同一姓名")
print("=" * 80)
for cname in ["dwd_cust_info", "dwd_cust_belong", "dwd_cust_contact",
              "dwd_cust_intention", "dwd_cust_risk", "dwd_cust_tag",
              "dwd_cust_trade", "dwd_cust_asset_summary"]:
    coll = db[cname]
    field = "CUSTOMER_NAME" if cname == "dwd_cust_info" else "CUST_NAME"
    if cname == "dwd_cust_info":
        d = coll.find_one({"CUSTOMER_ID": "CUST_001"})
        name = d.get("CUSTOMER_NAME") or d.get("CUST_NM") if d else None
    else:
        d = coll.find_one({"CUST_ID": "CUST_001"})
        name = d.get("CUST_NAME") if d else None
    print(f"  {cname:35s} CUST_001 → {name}")
