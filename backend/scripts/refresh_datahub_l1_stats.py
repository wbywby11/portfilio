"""
刷新 data_hub 域 L1 TableProfile 的动态统计字段

从 MongoDB 实时查询三张核心业务表的统计数据，输出 JSON 供 profile_engine 合并。
可手动执行或集成到定时任务中。

用法:
  python scripts/refresh_datahub_l1_stats.py          # 输出 JSON
  python scripts/refresh_datahub_l1_stats.py --apply  # 直接写回 MongoDB 配置集合
"""
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient


CORE_TABLES = {
    "subject_risk_records": {
        "key_fields": [
            "risk_id", "biz_date", "subject_name", "risk_signal_level",
            "signal_dascribe", "rule_large", "rule_medium", "rule_small",
            "enterprise_nature", "industry_classification_gb", "affiliated_province",
        ],
        "date_field": "biz_date",
        "enum_fields": ["risk_signal_level", "enterprise_nature", "rule_large"],
    },
    "zysc_ptl_info_records": {
        "key_fields": [
            "产品代码", "产品简称", "产品名称", "产品性质", "风险等级",
            "估值方法", "管理人", "托管人", "投资经理", "币种",
            "策略类型", "产品起息日", "产品到期日",
        ],
        "date_field": "产品起息日",
        "enum_fields": ["风险等级", "估值方法", "策略类型", "产品性质"],
    },
    "zysc_ptl_holder_records": {
        "key_fields": [
            "_holder_row_uid", "产品代码", "生效日期",
            "前十份额", "前十金额", "个人份额", "个人金额",
            "机构份额", "机构金额", "数据来源",
        ],
        "date_field": "生效日期",
        "enum_fields": ["数据来源"],
        "numeric_fields": ["前十份额", "前十金额", "个人份额", "个人金额", "机构份额", "机构金额"],
    },
}


def compute_table_stats(db, table_name: str, cfg: dict) -> dict:
    """计算单张表的动态统计数据"""
    col = db[table_name]
    total = col.count_documents({})
    if total == 0:
        return {"record_count": 0}

    # 字段非空覆盖率
    coverage = {}
    for f in cfg["key_fields"]:
        non_null = col.count_documents({f: {"$ne": None, "$exists": True}})
        coverage[f] = round(non_null / total, 4)

    # 最新业务日期
    date_field = cfg.get("date_field")
    last_biz_date = None
    if date_field:
        latest = col.find_one(
            {date_field: {"$ne": None}},
            {date_field: 1},
            sort=[(date_field, -1)],
        )
        if latest:
            last_biz_date = str(latest.get(date_field, ""))

    # 枚举字段分布
    enum_dist = {}
    for ef in cfg.get("enum_fields", []):
        pipeline = [
            {"$group": {"_id": f"${ef}", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        dist = {str(d["_id"]): d["count"] for d in col.aggregate(pipeline) if d["_id"]}
        enum_dist[ef] = dist

    # 数值字段统计（仅holder表）
    numeric_stats = {}
    for nf in cfg.get("numeric_fields", []):
        pipeline = [
            {"$match": {nf: {"$type": "number"}}},
            {"$group": {
                "_id": None,
                "min": {"$min": f"${nf}"},
                "max": {"$max": f"${nf}"},
                "avg": {"$avg": f"${nf}"},
                "sum": {"$sum": f"${nf}"},
            }},
        ]
        result = list(col.aggregate(pipeline))
        if result:
            r = result[0]
            numeric_stats[nf] = {
                "min": round(r["min"], 2) if r["min"] else 0,
                "max": round(r["max"], 2) if r["max"] else 0,
                "avg": round(r["avg"], 2) if r["avg"] else 0,
            }

    return {
        "table_name": table_name,
        "record_count": total,
        "field_coverage": coverage,
        "last_biz_date": last_biz_date,
        "enum_distribution": enum_dist,
        "numeric_stats": numeric_stats,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    apply_mode = "--apply" in sys.argv
    client = MongoClient("mongodb://localhost:27017")
    db = client["asset_allocation"]

    results = {}
    for table_name, cfg in CORE_TABLES.items():
        stats = compute_table_stats(db, table_name, cfg)
        results[table_name] = stats
        print(f"\n{'='*60}")
        print(f"  {table_name}")
        print(f"{'='*60}")
        print(f"  记录数: {stats['record_count']}")
        print(f"  最新业务日期: {stats['last_biz_date']}")
        print(f"  字段覆盖率:")
        for f, c in stats["field_coverage"].items():
            flag = "OK" if c >= 0.95 else "LOW"
            print(f"    {f}: {c:.1%} [{flag}]")
        if stats["enum_distribution"]:
            print(f"  枚举分布:")
            for ef, dist in stats["enum_distribution"].items():
                top3 = list(dist.items())[:5]
                print(f"    {ef}: {', '.join(f'{k}={v}' for k, v in top3)}")
        if stats["numeric_stats"]:
            print(f"  数值统计:")
            for nf, ns in stats["numeric_stats"].items():
                print(f"    {nf}: min={ns['min']:,.0f}  max={ns['max']:,.0f}  avg={ns['avg']:,.0f}")

    if apply_mode:
        config_col = db["profile_dynamic_stats"]
        for table_name, stats in results.items():
            config_col.update_one(
                {"table_name": table_name},
                {"$set": stats},
                upsert=True,
            )
        print(f"\n[APPLY] 已写入 profile_dynamic_stats 集合")
    else:
        print(f"\n[DRY-RUN] 未写入数据库，使用 --apply 参数写入")

    client.close()
    return results


if __name__ == "__main__":
    main()
