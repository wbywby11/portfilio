# -*- coding: utf-8 -*-
"""查看关键表的字段样例"""
from pymongo import MongoClient
import json

client = MongoClient("mongodb://localhost:27017")
db = client["asset_allocation"]

KEY_COLLS = [
    "dwd_cust_info", "dwd_cust_belong", "dwd_cust_contact", "dwd_cust_intention",
    "dwd_cust_risk", "dwd_cust_tag", "dwd_cust_trade", "dwd_cust_asset_summary",
    "dwd_cust_make_pstn_info",
    "dwd_isr_institution", "dwd_isr_trd_cntp",
    "dwd_mkt_fund", "dwd_mkt_stock", "dwd_mkt_bond", "dwd_mkt_yield_curve",
    "dwd_ast_info", "dwd_ast_info_ch", "dwd_ast_info_zg",
    "dwd_ast_cf_plan", "dwd_ast_exe_plan", "dwd_ast_fiveclass", "dwd_ast_party",
    "dwd_ast_pledge", "dwd_ast_yield_info", "dwd_ast_bottom_raito",
    "dwd_ast_calc_rule", "dwd_ast_fund_manager",
    "dwd_ptl_info", "dwd_ptl_attribution", "dwd_ptl_channel", "dwd_ptl_class_map",
    "dwd_ptl_contract", "dwd_ptl_fee", "dwd_ptl_manager", "dwd_ptl_nav",
    "dwd_ptl_pstn_detail", "dwd_ptl_risk", "dwd_ptl_sub_red",
    "dwd_rsk_alert", "dwd_rsk_compliance", "dwd_rsk_limit", "dwd_rsk_report",
    "dwd_rsk_stress_test",
    "dwd_sls_sales",
    "dwd_trn_trade_ast", "dwd_trn_trade_fund", "dwd_trn_trade_ptl",
    "dwd_val_adjustment", "dwd_val_bal", "dwd_val_detail", "dwd_val_diff",
    "dwd_val_exception", "dwd_val_impairment", "dwd_val_method",
    "dwd_val_receivable_payable", "dwd_val_review", "dwd_val_summary",
]

for c in KEY_COLLS:
    coll = db[c]
    cnt = coll.count_documents({})
    if cnt == 0:
        continue
    doc = coll.find_one({}, {"_id": 0})
    print(f"### {c} ({cnt}行)")
    print(json.dumps(doc, ensure_ascii=False, default=str)[:600])
    print()
