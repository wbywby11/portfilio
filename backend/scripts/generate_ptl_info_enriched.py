"""
Task 3: 扩充 zysc_ptl_info_records 产品信息表
从35扩充到80个产品，增加管理人/策略/期限/风险等级多样性。
"""
import sys
import random
from datetime import datetime, timedelta

sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

random.seed(43)

DB_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"

# ─── 产品配置种子 ───────────────────────────────────────────────────────
MANAGERS = ["浙银理财", "招银理财", "交银理财", "工银理财"]
MANAGER_WEIGHTS = [0.35, 0.25, 0.25, 0.15]

RISK_LEVELS = ["R1", "R2", "R3", "R4", "R5"]
RISK_WEIGHTS = [0.05, 0.20, 0.45, 0.25, 0.05]

STRATEGIES = ["纯债策略", "固收+", "混合策略", "FOF配置", "CTA趋势", "指数增强", "QDII海外", "量化对冲", "目标日期"]
# 风险等级→策略映射概率
RISK_STRATEGY_MAP = {
    "R1": ["纯债策略", "纯债策略", "固收+"],
    "R2": ["纯债策略", "固收+", "固收+", "混合策略"],
    "R3": ["混合策略", "FOF配置", "CTA趋势", "指数增强", "固收+"],
    "R4": ["CTA趋势", "指数增强", "QDII海外", "量化对冲", "FOF配置"],
    "R5": ["QDII海外", "量化对冲", "CTA趋势", "目标日期"],
}

OPEN_TYPES = ["每日开放", "定期开放", "封闭式"]
OPEN_FREQ = {"每日开放": "每日", "定期开放": ["每周", "双周", "每月", "每季", "每年"], "封闭式": "封闭"}

DEPARTMENTS = ["零售金融部", "私人银行部", "机构客户部", "资管部"]
SUB_DEPTS = {"零售金融部": ["固收组", "权益组"], "私人银行部": ["权益投资组", "量化组"], "机构客户部": ["机构业务组"], "资管部": ["主动管理组", "被动指数组"]}

PRODUCT_SERIES = ["优选", "稳健", "进取", "尊享", "智选", "鑫享", "金利", "慧享"]
SERIES_SUB = ["稳健", "平衡", "积极", "保守", "进取"]

VALUATION_METHODS = {"R1": "摊余成本法", "R2": "市值法", "R3": "市值法", "R4": "市值法", "R5": "市值法"}

CURRENCIES = ["人民币", "人民币", "人民币", "人民币", "美元", "港币"]
YIELD_TYPES = {"R1": "保本保收益", "R2": "保本浮动", "R3": "非保本浮动", "R4": "非保本浮动", "R5": "非保本浮动"}

PRODUCT_NATURES = ["理财产品", "理财产品", "资管计划"]
PRODUCT_MODES = ["普通产品", "普通产品", "FOF产品"]


def weighted_choice(items, weights):
    return random.choices(items, weights=weights, k=1)[0]


def gen_product_code(idx):
    return f"PTL_{str(idx).zfill(3)}"


def gen_benchmark_code(ptl_code):
    return f"{ptl_code}_HYJZ"


def gen_dates(risk_level):
    """根据风险等级生成起息日/到期日"""
    base = datetime(2023, 1, 1) + timedelta(days=random.randint(0, 730))
    if risk_level in ("R1", "R2"):
        duration = random.choice([90, 180, 365])
    elif risk_level == "R3":
        duration = random.choice([365, 730, 1095])
    else:
        duration = random.choice([730, 1095, 0])  # 0=无固定期限

    start = base
    end = base + timedelta(days=duration) if duration > 0 else None
    return start, end


def build_new_products(existing_codes: set):
    """生成新产品文档"""
    new_docs = []
    idx = 36  # 从PTL_036开始

    target_total = 80
    to_generate = target_total - 35  # 需要新增45个

    for i in range(to_generate):
        code = gen_product_code(idx)
        if code in existing_codes:
            idx += 1
            continue

        risk = weighted_choice(RISK_LEVELS, RISK_WEIGHTS)
        manager = weighted_choice(MANAGERS, MANAGER_WEIGHTS)
        strategy = random.choice(RISK_STRATEGY_MAP[risk])
        dept = random.choice(DEPARTMENTS)
        sub_dept = random.choice(SUB_DEPTS[dept])
        series = random.choice(PRODUCT_SERIES)
        series_sub = random.choice(SERIES_SUB)
        open_type = random.choice(OPEN_TYPES)
        currency = random.choice(CURRENCIES)

        if open_type == "定期开放":
            freq = random.choice(OPEN_FREQ["定期开放"])
        elif open_type == "封闭式":
            freq = "封闭"
        else:
            freq = "每日"

        start_date, end_date = gen_dates(risk)
        build_days = random.choice([15, 20, 30, 45])
        min_hold = {"R1": 0, "R2": 30, "R3": 90, "R4": 180, "R5": 365}.get(risk, 90)
        min_amount = {"R1": 10000, "R2": 50000, "R3": 50000, "R4": 100000, "R5": 300000}.get(risk, 50000)

        product_name = f"{manager}{series}{datetime.now().year}年第{idx-35}期"
        short_name = f"{series_sub}收益{idx-35}号"

        doc = {
            "产品代码": code,
            "产品名称": product_name,
            "产品简称": short_name,
            "产品性质": random.choice(PRODUCT_NATURES),
            "产品模式": "FOF产品" if "FOF" in strategy else "普通产品",
            "产品类型": random.choice(["010", "020", "030"]),
            "产品系列": series,
            "产品系列细分": series_sub,
            "风险等级": risk,
            "策略类型": strategy,
            "估值方法": VALUATION_METHODS[risk],
            "管理人": manager,
            "托管人": random.choice(["交通银行", "中国银行", "工商银行", "建设银行", "农业银行"]),
            "投资经理": f"{'赵钱孙李周吴郑王冯陈'[random.randint(0,9)]}{'伟强磊军洋勇艳杰娟敏'[random.randint(0,9)]}{'华明志强丽芳'[random.randint(0,5)]}",
            "币种": currency,
            "开放类型": open_type,
            "开放频率": freq,
            "产品起息日": start_date.strftime("%Y-%m-%d"),
            "产品到期日": end_date.strftime("%Y-%m-%d") if end_date else None,
            "募集开始日": (start_date - timedelta(days=7)).strftime("%Y-%m-%d"),
            "募集方式": random.choice(["公募", "私募"]),
            "建仓期": build_days,
            "建仓完成期": (start_date + timedelta(days=build_days)).strftime("%Y-%m-%d"),
            "清盘日": end_date.strftime("%Y-%m-%d") if end_date else None,
            "收益类型": YIELD_TYPES[risk],
            "运行方式": "正常",
            "所属部门": dept,
            "所属子部门": sub_dept,
            "客户类型": random.choice(["个人", "机构", "个人和机构"]),
            "客户周期(天)": min_hold,
            "是否最短持有期": "是" if min_hold > 0 else "否",
            "最短持有期限(天)": min_hold,
            "是否现金管理类": "是" if risk == "R1" and strategy == "纯债策略" else "否",
            "起点销售金额/认购起点": min_amount,
            "市场基准": random.choice(["中债国债总指数", "沪深300", "中证500", "恒生指数", "MSCI中国"]),
            "市场基准说明": "对标市场基准指数",
            "合约基准": gen_benchmark_code(code),
            "合约基准_上限": str(round(random.uniform(0.02, 0.06), 4)),
            "合约基准_下限": str(round(random.uniform(0.01, 0.03), 4)),
            "合约基准_平均": str(round(random.uniform(0.03, 0.05), 4)),
            "合约基准说明": "按合同约定的基准收益率",
            "内部基准": None,
            "内部基准说明": None,
            "所属产品": None,
            "SPV分类": None,
            "委外资产ID": None,
            "交易日历": "中国银行间交易日历",
            "资管计划管理方式": "主动管理" if strategy != "指数增强" else "被动管理",
            "拉链开始日": "2024-01-01",
            "拉链结束日": "2026-05-26",
            "数据日期": "2026-05-26",
            "数据时间": "08:00:00",
            "数据来源": "ZYSC",
            "导入方法": "API",
            "_batch_id": "batch_ptl_enriched_01",
            "_imported_at": datetime.now().isoformat(),
            "_created_at": datetime.now().isoformat(),
        }
        new_docs.append(doc)
        idx += 1

    return new_docs


def main():
    client = MongoClient(DB_URI)
    db = client[DB_NAME]
    col = db["zysc_ptl_info_records"]

    existing = col.count_documents({})
    existing_codes = set(col.distinct("产品代码"))
    print(f"现有 zysc_ptl_info_records: {existing} 条, 产品代码 {len(existing_codes)} 个")

    new_docs = build_new_products(existing_codes)
    to_insert = [d for d in new_docs if d["产品代码"] not in existing_codes]
    print(f"待插入: {len(to_insert)} 条")

    if to_insert:
        result = col.insert_many(to_insert)
        print(f"插入完成: {len(result.inserted_ids)} 条")

    # 同步到 dwd_ptl_info（产品域内部表也需要这些产品）
    dwd_col = db["dwd_ptl_info"]
    dwd_existing = set(dwd_col.distinct("PORT_ID"))
    dwd_to_add = []
    for doc in to_insert:
        if doc["产品代码"] not in dwd_existing:
            dwd_to_add.append({
                "PORT_ID": doc["产品代码"],
                "PORT_NM": doc["产品名称"],
                "PORT_SHORT_NM": doc["产品简称"],
                "PORT_TYPE": doc["产品类型"],
                "RISK_LEVEL": doc["风险等级"],
                "STRATEGY_TYPE": doc["策略类型"],
                "MANAGER": doc["管理人"],
                "CUSTODIAN": doc["托管人"],
                "INCEPTION_DT": doc["产品起息日"],
                "MATURITY_DT": doc["产品到期日"],
                "CCY": doc["币种"],
                "STATUS": "正常",
                "BIZ_DT": "2026-05-26",
                "src_sys": "hermes_enriched",
                "etl_dt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
    if dwd_to_add:
        dwd_col.insert_many(dwd_to_add)
        print(f"同步 dwd_ptl_info: {len(dwd_to_add)} 条")

    # 统计
    final = col.count_documents({})
    print(f"\n最终 zysc_ptl_info_records: {final} 条")
    print("风险等级分布:")
    for d in col.aggregate([{"$group": {"_id": "$风险等级", "c": {"$sum": 1}}}, {"$sort": {"c": -1}}]):
        print(f"  {d['_id']}: {d['c']}")
    print("管理人分布:")
    for d in col.aggregate([{"$group": {"_id": "$管理人", "c": {"$sum": 1}}}, {"$sort": {"c": -1}}]):
        print(f"  {d['_id']}: {d['c']}")
    print("策略类型分布:")
    for d in col.aggregate([{"$group": {"_id": "$策略类型", "c": {"$sum": 1}}}, {"$sort": {"c": -1}}]):
        print(f"  {d['_id']}: {d['c']}")

    client.close()


if __name__ == "__main__":
    main()
