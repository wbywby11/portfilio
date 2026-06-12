"""
Task 1: 生成 subject_risk_records 扩充数据 + 配套 batches
覆盖 24 个月时间序列，多行业/省份/性质交叉，风险等级时序演化。
"""
import sys
import random
import hashlib
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

random.seed(45)

DB_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"

# ─── 时间范围 ────────────────────────────────────────────────────────────
START_DATE = datetime(2024, 6, 1)
END_DATE = datetime(2026, 5, 31)
MONTHS = 24

# ─── 风险等级时序演化：模拟从低风险逐渐恶化 ──────────────────────────────
def get_risk_weights_for_month(month_idx):
    """月份索引0-23，高风险概率从10%升至30%"""
    high_pct = 0.10 + (0.20 * month_idx / 23)
    yellow_pct = 0.55 - (0.10 * month_idx / 23)
    low_pct = 1.0 - high_pct - yellow_pct
    return {"高": high_pct, "黄": yellow_pct, "低": low_pct}

# ─── 行业→规则大类映射 ──────────────────────────────────────────────────
INDUSTRY_RULE_MAP = {
    "房地产业-房地产开发经营": ["客户经营情况", "客户融资情况", "客户经营情况", "客户财务情况"],
    "建筑业-土木工程建筑业": ["客户经营情况", "客户合规情况", "客户融资情况"],
    "金融业-货币金融服务": ["客户合规情况", "客户信用情况", "客户舆情情况"],
    "金融业-资本市场服务": ["客户合规情况", "客户信用情况", "客户舆情情况"],
    "金融业-保险业": ["客户合规情况", "客户经营情况"],
    "信息传输、软件和信息技术服务业": ["客户舆情情况", "客户经营情况", "客户合规情况"],
    "制造业-汽车制造业": ["客户财务情况", "客户经营情况", "客户融资情况"],
    "制造业-医药制造业": ["客户合规情况", "客户舆情情况", "客户财务情况"],
    "批发和零售业": ["客户经营情况", "客户财务情况"],
    "交通运输、仓储和邮政业": ["客户经营情况", "客户财务情况"],
    "电力、热力、燃气及水生产和供应业": ["客户经营情况", "客户合规情况"],
    "农、林、牧、渔业": ["客户经营情况", "客户财务情况"],
}

# ─── 规则中/小类 ──────────────────────────────────────────────────────
RULE_MEDIUM_MAP = {
    "客户经营情况": ["经营异常事件", "重大变更事件", "司法及行政处罚事件", "股权冻结事件"],
    "客户财务情况": ["财务恶化事件", "审计异常事件", "偿债能力下降", "资产减值事件"],
    "客户融资情况": ["债务集中到期", "融资渠道收窄", "债券违约风险", "银行贷款逾期"],
    "客户信用情况": ["评级下调事件", "展望调整事件", "信用违约互换异动", "担保代偿风险"],
    "客户舆情情况": ["负面舆情事件", "高管变动事件", "监管处罚事件", "诉讼仲裁事件"],
    "客户合规情况": ["违规处罚事件", "信息披露违规", "内控缺陷事件", "关联交易违规"],
}

RULE_SMALL_MAP = {
    "经营异常事件": ["企业被列入经营异常名录", "主营业务收入同比下降超30%"],
    "重大变更事件": ["企业发生重大资产重组", "控股股东发生变更"],
    "司法及行政处罚事件": ["企业主体评级被下调或展望调为负面", "被证监会/银保监会处罚"],
    "财务恶化事件": ["净利润连续两季亏损", "资产负债率超过85%"],
    "债务集中到期": ["未来6个月到期债务占比超40%", "短期债务覆盖比率低于1.0"],
    "评级下调事件": ["主体评级被下调1级以上", "展望由稳定调为负面"],
    "负面舆情事件": ["高管涉嫌违法被调查", "重大环保事故被曝光"],
    "违规处罚事件": ["被监管部门罚款超1000万", "业务许可证被暂停"],
}

# ─── 信号描述模板 ──────────────────────────────────────────────────────
SIGNAL_TEMPLATES = {
    "客户经营情况": [
        "企业({name})({date})被列入经营异常名录，工商部门已做出标记。",
        "企业({name})近期主营业务收入同比下降{pct}%，经营现金流持续为负。",
        "企业({name})({date})发生控股股东变更，实控人由{from_}变为{to_}。",
    ],
    "客户财务情况": [
        "企业({name})({date})最新财报显示净利润亏损{amt}亿元，同比下降{pct}%。",
        "企业({name})资产负债率升至{ratio}%，超过行业警戒线。",
    ],
    "客户融资情况": [
        "企业({name})({date})未来6个月到期债务合计{amt}亿元，覆盖比率仅{ratio}倍。",
        "企业({name})近期多笔银行贷款展期申请被拒，融资渠道明显收窄。",
    ],
    "客户信用情况": [
        "企业({name})({date})主体信用评级由{from_}下调至{to_}，展望调整为负面。评级机构关注其债务集中到期压力。",
        "企业({name})信用违约互换(CDS)价差近一周走阔{bp}BP，暗示市场对其违约概率预期上升。",
    ],
    "客户舆情情况": [
        "企业({name})({date})高管{person}因涉嫌{crime}被有关部门调查。",
        "企业({name})因{event}被媒体广泛报道，舆情热度指数升至{score}。",
    ],
    "客户合规情况": [
        "企业({name})({date})因{reason}被{regulator}罚款{amt}万元。",
        "企业({name})信息披露违规，未按期披露{report}。",
    ],
}


def gen_risk_id(biz_date_str, idx):
    raw = f"{biz_date_str}{idx}"
    return f"{biz_date_str.replace('-', '')}DG{hashlib.md5(raw.encode()).hexdigest()[:16].upper()}"


def gen_signal_description(rule_large, name, date_str):
    templates = SIGNAL_TEMPLATES.get(rule_large, ["企业({name})({date})触发风险信号。"])
    tpl = random.choice(templates)
    return tpl.format(
        name=name, date=date_str,
        pct=random.randint(15, 60), amt=round(random.uniform(1, 50), 1),
        ratio=random.randint(70, 95), from_="AA", to_="A+",
        bp=random.randint(20, 150), person="某高管", crime="违法行为",
        event="环保事故", score=random.randint(70, 99),
        reason="违规操作", regulator="银保监会", report="年度报告",
    )


def main():
    client = MongoClient(DB_URI)
    db = client[DB_NAME]

    # 获取所有可用主体
    isr_docs = list(db["dwd_isr_institution"].find({}, {
        "ISR_NM": 1, "PROVINCE": 1, "COMPANY_NATURE": 1, "INDUSTRY_GB2": 1
    }))
    print(f"可用主体: {len(isr_docs)} 个")

    # 构建主体池（按行业分组）
    by_industry = defaultdict(list)
    for doc in isr_docs:
        ind = doc.get("INDUSTRY_GB2", "未知")
        by_industry[ind].append(doc)

    # 行业权重（房地产/建筑风险高频）
    industry_weights = {
        "房地产业-房地产开发经营": 5,
        "建筑业-土木工程建筑业": 3,
        "金融业-货币金融服务": 2,
        "金融业-资本市场服务": 2,
        "信息传输、软件和信息技术服务业": 2,
        "制造业-汽车制造业": 2,
        "制造业-医药制造业": 1,
    }

    # 清除旧扩充（保留原始40条）
    del_result = db["subject_risk_records"].delete_many({"_batch_id": {"$regex": "^batch_risk_enriched_"}})
    print(f"清除旧扩充: {del_result.deleted_count} 条")

    new_risk_docs = []
    batch_docs = []
    record_idx = 0

    for month_idx in range(MONTHS):
        month_date = START_DATE + timedelta(days=month_idx * 30)
        month_str = month_date.strftime("%Y-%m")
        risk_weights = get_risk_weights_for_month(month_idx)
        records_this_month = random.randint(18, 28)

        batch_id = f"batch_risk_enriched_{month_str}_01"
        batch_records = 0

        for _ in range(records_this_month):
            # 选行业（加权）
            available_industries = [k for k in by_industry if by_industry[k]]
            if not available_industries:
                continue
            weights = [industry_weights.get(k, 1) for k in available_industries]
            total_w = sum(weights)
            weights = [w / total_w for w in weights]
            chosen_industry = random.choices(available_industries, weights=weights, k=1)[0]

            # 选主体
            subject = random.choice(by_industry[chosen_industry])
            subject_name = subject["ISR_NM"]
            province = subject.get("PROVINCE", "北京市")
            nature = subject.get("COMPANY_NATURE", "国有企业")

            # 风险等级
            risk_level = random.choices(
                list(risk_weights.keys()),
                weights=list(risk_weights.values()),
                k=1
            )[0]

            # 规则
            rule_large_options = INDUSTRY_RULE_MAP.get(chosen_industry, ["客户经营情况"])
            rule_large = random.choice(rule_large_options)
            rule_medium_options = RULE_MEDIUM_MAP.get(rule_large, ["通用事件"])
            rule_medium = random.choice(rule_medium_options)
            rule_small_options = RULE_SMALL_MAP.get(rule_medium, [rule_medium])
            rule_small = random.choice(rule_small_options)

            # 日期（月内随机天）
            day_offset = random.randint(0, 27)
            biz_date = month_date + timedelta(days=day_offset)
            biz_date_str = biz_date.strftime("%Y-%m-%d")

            doc = {
                "risk_id": gen_risk_id(biz_date_str, record_idx),
                "biz_date": biz_date_str,
                "data_date": biz_date_str,
                "sign_date": (biz_date - timedelta(days=1)).strftime("%Y-%m-%d"),
                "subject_name": subject_name,
                "subject_type": "企业法人(非金融机构)" if "金融" not in chosen_industry else "金融机构",
                "risk_signal_level": risk_level,
                "signal_dascribe": gen_signal_description(rule_large, subject_name, biz_date_str),
                "rule_large": rule_large,
                "rule_medium": rule_medium,
                "rule_small": rule_small,
                "enterprise_nature": nature,
                "industry_classification_gb": chosen_industry,
                "affiliated_province": province,
                "affiliated_city": "",
                "affiliated_county_town": None,
                "unified_social_credit_code": f"91{random.randint(100000, 999999)}{random.randint(100000000, 999999999)}",
                "is_approved_investment_quota_client": random.choice(["是", "否", "否", "否"]),
                "is_partner_access_client": random.choice(["是", "否", "否"]),
                "is_parent_bank_veto_client": "是" if risk_level == "高" and random.random() < 0.3 else "否",
                "parent_bank_classify_queue_type": None,
                "parent_bank_monitor_manager_type": "重点关注" if risk_level == "高" else ("一般关注" if risk_level == "黄" else None),
                "financial_lease_monitor_manager_type": None,
                "wealth_child_monitor_manager_type": None,
                "_batch_id": batch_id,
                "_imported_at": datetime.now().isoformat(),
            }
            new_risk_docs.append(doc)
            batch_records += 1
            record_idx += 1

        # 生成 batch 记录
        status = random.choices(["success", "partial", "failed_upstream"], weights=[0.70, 0.20, 0.10], k=1)[0]
        batch_docs.append({
            "batch_id": batch_id,
            "connector_id": "subject_opinion_risk",
            "status": status,
            "started_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat(),
            "duration_ms": random.randint(800, 5000),
            "total_returned": batch_records + random.randint(0, 5),
            "inserted": batch_records if status == "success" else int(batch_records * 0.8),
            "updated": 0,
            "failed": 0 if status == "success" else random.randint(1, 5),
            "upstream_message": None if status == "success" else "timeout" if status == "failed_upstream" else "partial_page",
            "_created_at": datetime.now().isoformat(),
        })

    print(f"生成风险记录: {len(new_risk_docs)} 条")
    print(f"生成批次记录: {len(batch_docs)} 条")

    # 插入
    if new_risk_docs:
        batch_size = 500
        for i in range(0, len(new_risk_docs), batch_size):
            db["subject_risk_records"].insert_many(new_risk_docs[i:i + batch_size])
        print("风险记录插入完成")

    # 清除旧扩充批次并重新插入
    db["subject_risk_import_batches"].delete_many({"batch_id": {"$regex": "^batch_risk_enriched_"}})
    if batch_docs:
        for bd in batch_docs:
            db["subject_risk_import_batches"].update_one(
                {"batch_id": bd["batch_id"]},
                {"$set": bd},
                upsert=True,
            )
        print(f"批次记录upsert完成: {len(batch_docs)} 条")

    # 统计
    final = db["subject_risk_records"].count_documents({})
    final_batches = db["subject_risk_import_batches"].count_documents({})
    print(f"\n最终 subject_risk_records: {final} 条")
    print(f"最终 subject_risk_import_batches: {final_batches} 条")
    print("\n风险等级月度分布(前3月/后3月对比):")
    for level in ["高", "黄", "低"]:
        early = db["subject_risk_records"].count_documents({"risk_signal_level": level, "biz_date": {"$lt": "2024-09-01"}})
        late = db["subject_risk_records"].count_documents({"risk_signal_level": level, "biz_date": {"$gte": "2026-03-01"}})
        print(f"  {level}: 早期={early}, 近期={late}")

    client.close()


if __name__ == "__main__":
    main()
