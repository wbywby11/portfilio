# -*- coding: utf-8 -*-
"""补丁修复：补充第一轮 fix_dwd_quality 没覆盖到的字段。"""
import re
from pymongo import MongoClient, UpdateOne

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_dwd_quality import (  # noqa
    is_placeholder_str, num_suffix, product_real_name,
    fund_real, stock_real, gen_company_name, COMPANY_NAMES,
)

db = MongoClient("mongodb://localhost:27017")["asset_allocation"]


def fix_prod_name_in_cust_tables():
    """dwd_cust_trade / dwd_cust_make_pstn_info 的 PROD_NAME 占位符"""
    for cname in ["dwd_cust_trade", "dwd_cust_make_pstn_info"]:
        coll = db[cname]
        ops = []
        for d in coll.find({}, {"_id": 1, "PROD_CD": 1, "PARENT_PROD_CD": 1, "PROD_NAME": 1}):
            if is_placeholder_str(d.get("PROD_NAME")):
                pcd = d.get("PROD_CD") or d.get("PARENT_PROD_CD")
                idx = num_suffix(pcd)
                if idx:
                    ops.append(UpdateOne({"_id": d["_id"]},
                                         {"$set": {"PROD_NAME": product_real_name(idx)}}))
        if ops:
            r = coll.bulk_write(ops, ordered=False)
            print(f"[补丁] {cname}.PROD_NAME: 修复 {r.modified_count} 行")


def fix_ast_pledge_diverse():
    """dwd_ast_pledge: PLEDGE_BOND_CD 全部为 019601.IB → 分散到 30 个真实债券代码"""
    coll = db.dwd_ast_pledge
    BOND_PLEDGE_POOL = [f"019{600 + i:03d}.IB" for i in range(20)] + [
        f"230{1 + i:04d}.IB" for i in range(10)
    ]
    ops = []
    docs = list(coll.find({}).sort("_id", 1))
    for i, d in enumerate(docs):
        ops.append(UpdateOne({"_id": d["_id"]},
                             {"$set": {"PLEDGE_BOND_CD": BOND_PLEDGE_POOL[i % len(BOND_PLEDGE_POOL)]}}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"[补丁] dwd_ast_pledge.PLEDGE_BOND_CD: 修复 {r.modified_count} 行")


def fix_ptl_info_extra():
    """dwd_ptl_info: 多个字段需要修复"""
    coll = db.dwd_ptl_info
    BANKS = ["招商银行", "工商银行", "建设银行", "中国银行", "交通银行",
             "兴业银行", "浦发银行", "民生银行", "中信银行", "光大银行"]
    ops = []
    for d in coll.find({}):
        sets = {}
        prod_cd = d.get("PROD_CD") or d.get("PORT_ID")
        idx = num_suffix(prod_cd)
        real_name = product_real_name(idx) if idx else None

        if is_placeholder_str(d.get("PROD_NSP_PRPR_NM")) and real_name:
            sets["PROD_NSP_PRPR_NM"] = real_name
        if is_placeholder_str(d.get("PORT_NM")) and real_name:
            sets["PORT_NM"] = real_name
        if d.get("PORT_SHORT_NM") in (None, "", "产品简称") and real_name:
            sets["PORT_SHORT_NM"] = real_name[:6]
        # 托管账户名 & 行 — 跨产品分散
        if is_placeholder_str(d.get("FNC_PROD_FNDS_CSTDY_ACCT_NM")):
            sets["FNC_PROD_FNDS_CSTDY_ACCT_NM"] = f"{BANKS[idx % len(BANKS)]}托管专户{idx:03d}"
        # 托管行代码：BANK_002 -> 用真实大行代码
        if is_placeholder_str(d.get("DMSTC_CSTDY_ORG_CD")):
            bank_codes = ["ICBC", "ABC", "BOC", "CCB", "BCM", "CMB", "CITIC", "CMBC", "CIB", "SPDB"]
            sets["DMSTC_CSTDY_ORG_CD"] = bank_codes[idx % len(bank_codes)]
        if sets:
            ops.append(UpdateOne({"_id": d["_id"]}, {"$set": sets}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"[补丁] dwd_ptl_info: 修复 {r.modified_count} 行")


def fix_isr_institution_credit():
    """dwd_isr_institution: 上一轮 CREDIT_CD 设成评级（AAA等），但还有些原值 CREDIT_CD_xxx 没清理"""
    coll = db.dwd_isr_institution
    ratings = ["AAA", "AA+", "AA", "AA-", "A+", "A", "BBB+", "BBB"]
    ops = []
    for i, d in enumerate(coll.find({}).sort("_id", 1)):
        cd = d.get("CREDIT_CD")
        if cd and re.match(r"^CREDIT_CD_", str(cd)):
            ops.append(UpdateOne({"_id": d["_id"]},
                                 {"$set": {"CREDIT_CD": ratings[i % len(ratings)]}}))
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        print(f"[补丁] dwd_isr_institution.CREDIT_CD: 再修 {r.modified_count} 行")


if __name__ == "__main__":
    fix_prod_name_in_cust_tables()
    fix_ast_pledge_diverse()
    fix_ptl_info_extra()
    fix_isr_institution_credit()
    print("补丁修复完成")
