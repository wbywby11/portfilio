# -*- coding: utf-8 -*-
"""
全面审计 asset_allocation 库所有 dwd_ 集合的数据质量。
分类：
  A 类（好）：数据真实、字段有意义
  B 类（占位符）：名称含 "_001"、"某XX"、"客户_" 等模式
  C 类（重复/无效）：所有行某字段值相同、或名称字段是列名文字
"""
import re
import sys
from collections import Counter
from pymongo import MongoClient

PLACEHOLDER_PATTERNS = [
    re.compile(r"_\d{2,4}$"),
    re.compile(r"^某[\u4e00-\u9fa5]"),
    re.compile(r"^客户_"),
    re.compile(r"^主体企业_"),
    re.compile(r"^主体_"),
    re.compile(r"^FUND_\d+$"),
    re.compile(r"^STOCK_\d+$"),
    re.compile(r"^基金名称$"),
    re.compile(r"^股票名称$"),
    re.compile(r"^补充.*\d+$"),
    re.compile(r"^占位"),
    re.compile(r"^placeholder", re.IGNORECASE),
]

# 倾向于检查的"名称/代码"类字段
NAME_LIKE_FIELDS = [
    "CUST_NM", "客户名称", "INST_NM", "主体名称", "ISR_NM",
    "AST_NM", "资产名称", "FUND_NM", "STOCK_NM", "证券名称",
    "PROD_NM", "产品名称", "COMPANY_NM", "INDU_NM",
]
CODE_LIKE_FIELDS = [
    "CUST_CD", "客户代码", "INST_CD", "AST_CD", "资产代码",
    "FUND_CD", "STOCK_CD", "证券代码", "PROD_CD", "产品代码",
    "INDU_CD",
]


def is_placeholder(v):
    if v is None:
        return False
    s = str(v).strip()
    if not s:
        return False
    for p in PLACEHOLDER_PATTERNS:
        if p.search(s):
            return True
    return False


def audit():
    client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
    db = client["asset_allocation"]
    report = []
    cnames = sorted([c for c in db.list_collection_names() if c.startswith("dwd_")])
    print(f"共发现 {len(cnames)} 个 dwd_ 集合\n")
    for cname in cnames:
        coll = db[cname]
        count = coll.count_documents({})
        if count == 0:
            report.append((cname, count, "EMPTY", [], []))
            continue
        samples = list(coll.find({}, {"_id": 0}).limit(3))
        # 第一条所有字段
        keys = list(samples[0].keys()) if samples else []

        # 找候选名称/代码字段（含中英文）
        cand_fields = [k for k in keys if k in NAME_LIKE_FIELDS or k in CODE_LIKE_FIELDS]
        # 同时把含 NM/_NM/名称/代码/CD 关键字的字段也加入
        for k in keys:
            kl = k.upper()
            if k in cand_fields:
                continue
            if "NM" in kl or "名称" in k or "CD" in kl or "代码" in k or "NAME" in kl or "CODE" in kl:
                cand_fields.append(k)

        issues = []
        # 重复值检查：抽样最多 200 条
        sample_for_dup = list(coll.find({}, {"_id": 0}).limit(200))
        for f in cand_fields:
            vals = [str(d.get(f)) for d in sample_for_dup if d.get(f) is not None]
            if not vals:
                continue
            cnt = Counter(vals)
            most_v, most_n = cnt.most_common(1)[0]
            ratio = most_n / len(vals)
            # 占位符检查
            ph_hits = [v for v in vals[:30] if is_placeholder(v)]
            if ph_hits:
                issues.append(f"B类:字段[{f}]含占位符样例 {ph_hits[:3]}")
            if ratio >= 0.9 and len(vals) >= 5:
                issues.append(f"C类:字段[{f}] {most_n}/{len(vals)}行同值={most_v!r}")

        category = "A"
        if any(s.startswith("C类") for s in issues):
            category = "C"
        elif any(s.startswith("B类") for s in issues):
            category = "B"
        report.append((cname, count, category, issues, samples[:1]))

    # 输出报告
    print("=" * 80)
    print(f"{'集合名':<35}{'行数':>8}  {'类':<3}  问题")
    print("-" * 80)
    for cname, count, cat, issues, _ in report:
        issue_s = "; ".join(issues) if issues else "-"
        print(f"{cname:<35}{count:>8}  {cat:<3}  {issue_s}")
    print("=" * 80)

    bc = [r for r in report if r[2] in ("B", "C")]
    print(f"\nB/C 类问题表共 {len(bc)} 张：")
    for cname, count, cat, issues, _ in bc:
        print(f"  - {cname}({cat}, {count}行)")
    return report


if __name__ == "__main__":
    sys.exit(0 if audit() else 1)
