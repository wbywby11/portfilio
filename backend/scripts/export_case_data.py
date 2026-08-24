"""
典型案例 MongoDB 数据导出脚本
将血缘溯源/L1-L5画像/数据视图联动三大案例涉及的全部集合
导出为 MongoDB Extended JSON（.jsonl 格式），供跨系统移植。

使用方法:
    d:/portfilio-end/venv/Scripts/python.exe scripts/export_case_data.py

Output:
    d:/portfilio-end/exports/case_data_export_<timestamp>.zip
"""

import os
import sys
import json
import zipfile
import time
from datetime import datetime
from pathlib import Path

# 确保可以 import 项目依赖
sys.path.insert(0, str(Path(__file__).parent.parent))

from pymongo import MongoClient
from bson import json_util
from bson.json_util import JSONOptions, DatetimeRepresentation, JSONMode

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"
OUTPUT_DIR = Path(__file__).parent.parent / "exports"

# ── 案例涉及的集合清单（按业务域分组）──────────────────────────
#
# 案例一: 广东省房地产业高风险主体与组合持仓共振风险分析
# 案例二: 清仓房地产资产对组合波动率与预期收益的影响分析
# 案例三: 多行业风险事件分布与组合穿透收益/风险/波动率贡献对比
# 附录A:  固收+理财产品穿透尽调报告模板

COLLECTIONS = {
    # ── 案例一核心表 ──
    "subject_risk_records":           "主体观点风险记录 (617条)",
    "subject_risk_import_batches":    "风险记录导入批次 (44条)",

    # ── 案例二核心表 ──
    "dwd_ptl_ast_hld":               "产品资产持仓 (1412条)",
    "dwd_ast_info":                  "资产信息主表 (100条)",
    "dwd_isr_institution":           "机构主表 (57条)",
    "dwd_isr_institution_finance":   "机构财务信息 (30条)",

    # ── 案例二/三辅助表 ──
    "dwd_ptl_info":                  "产品主表 (80条)",
    "dwd_ast_yield_info":            "收益率信息表 (110条)",

    # ── 案例一路由候选表 ──
    "dwd_rsk_sentiment":             "舆情事件表 (4条)",
    "dwd_rsk_credit":                "内部信用评级表 (4条)",
    "dwd_rsk_credit_position":       "信用风险持仓表 (5条)",
    "dwd_crdt_agme_info":            "增信措施信息表 (3条)",
    "dwd_ast_fiveclass":             "资产五级分类表 (50条)",

    # ── 附录A 固收+尽调报告相关 ──
    "dwd_val_summary":               "估值汇总 (50条)",
    "dwd_mkt_bond":                  "债券市场数据 (840条)",
    "dwd_mkt_bond_creditrating":     "债券信用评级 (4条)",
    "dwd_mkt_bond_ecl":              "债券预期信用损失 (3条)",
    "dwd_mkt_bond_duration":         "债券久期 (5条)",
    "dwd_mkt_bond_issue":            "债券发行信息 (7条)",
    "dwd_mkt_bond_market":           "债券市场行情 (5条)",
    "dwd_mkt_bond_amount":           "债券量价数据 (4条)",
    "dwd_mkt_stock":                 "股票市场数据 (285条)",
    "dwd_mkt_stock_yield":           "股票收益率 (4条)",
    "tag_ptl_info":                  "产品标签信息 (101条)",
    "dwd_ptl_asset_config_info":     "产品资产配置 (6条)",
    "dwd_ptl_managers":              "基金经理 (5条)",
    "dwd_ptl_manager":               "产品管理人 (50条)",
    "dwd_ast_fund_manager":          "基金-经理关联 (5条)",
    "dwd_ptl_nav":                   "产品净值 (1500条)",
    "dwd_ptl_attribution":           "业绩归因 (50条)",
    "dwd_ptl_risk":                  "产品风险指标 (50条)",

    # ── 血缘图谱 & L5画像（系统能力元数据） ──
    "lineage_nodes":                 "血缘节点 (9条)",
    "lineage_edges":                 "血缘边 (12条)",
    "semantic_stats_profiles":       "L5统计画像 (13条)",
    "semantic_domain_macro":         "L5.2域宏观画像 (1条)",
    "profile_dynamic_stats":         "动态统计 (3条)",
}


def export_collection(db, collection_name: str, output_path: Path) -> int:
    """将单个集合导出为 JSONL 文件（每行一条 MongoDB Extended JSON），返回记录数"""
    collection = db[collection_name]
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for doc in collection.find({}):
            json_opts = JSONOptions(json_mode=JSONMode.RELAXED,
                                    datetime_representation=DatetimeRepresentation.ISO8601)
            line = json_util.dumps(doc, json_options=json_opts)
            f.write(line + "\n")
            count += 1
    return count


def main():
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 开始导出案例数据...")
    print(f"  MongoDB: {MONGO_URI}  DB: {DB_NAME}")
    print()

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    # 创建输出目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"case_data_export_{timestamp}.zip"
    temp_dir = OUTPUT_DIR / f"_temp_{timestamp}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "export_time": datetime.now().isoformat(),
        "mongo_uri": MONGO_URI,
        "database": DB_NAME,
        "description": "血缘溯源·L1-L5数据画像·数据视图联动 典型案例数据导出包",
        "cases": [
            "案例一: 广东省房地产业高风险主体与组合持仓共振风险分析",
            "案例二: 清仓房地产资产对组合波动率与预期收益的影响分析",
            "案例三: 多行业风险事件分布与组合穿透收益风险波动率贡献对比",
            "附录A:  固收+理财产品穿透尽调报告模板",
        ],
        "collections": {},
    }

    total_records = 0
    total_files = 0
    skipped = []

    print(f"{'集合名':<50} {'描述':<30} {'导出':>8}")
    print("-" * 92)

    for coll_name, description in COLLECTIONS.items():
        # 检查集合是否存在
        if coll_name not in db.list_collection_names():
            print(f"{coll_name:<50} {description:<30} {'[不存在]':>8}")
            skipped.append(coll_name)
            continue

        file_path = temp_dir / f"{coll_name}.jsonl"
        count = export_collection(db, coll_name, file_path)

        if count == 0:
            print(f"{coll_name:<50} {description:<30} {'(0条)':>8}")
            skipped.append(coll_name)
            file_path.unlink()  # 删除空文件
            continue

        total_records += count
        total_files += 1
        print(f"{coll_name:<50} {description:<30} {count:>8,}")

        manifest["collections"][coll_name] = {
            "description": description,
            "record_count": count,
            "file": f"{coll_name}.jsonl",
        }

    print("-" * 92)
    print(f"  合计导出: {total_files} 个集合, {total_records:,} 条记录")
    if skipped:
        print(f"  跳过（不存在/空）: {len(skipped)} 个集合")

    # 写入 manifest.json
    manifest_path = temp_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 写入导入说明
    readme_path = temp_dir / "README_import.md"
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("# 典型案例数据导入说明\n\n")
        f.write("## 导出信息\n\n")
        f.write(f"- 导出时间: {manifest['export_time']}\n")
        f.write(f"- 源数据库: `{DB_NAME}`\n")
        f.write(f"- 导出集合: {total_files} 个\n")
        f.write(f"- 导出记录: {total_records:,} 条\n\n")
        f.write("## 使用 mongoimport 导入\n\n")
        f.write("```bash\n")
        f.write("# 逐个导入\n")
        for coll_name, info in manifest["collections"].items():
            f.write(f"mongoimport --uri '{MONGO_URI}/{DB_NAME}' "
                    f"--collection {coll_name} "
                    f"--file {coll_name}.jsonl "
                    f"--mode upsert --upsertFields _id\n")
        f.write("```\n\n")
        f.write("## 使用 Python pymongo 导入\n\n")
        f.write("```python\n")
        f.write("from pymongo import MongoClient\n")
        f.write("from bson import json_util\n\n")
        f.write("client = MongoClient('mongodb://目标地址:27017')\n")
        f.write(f"db = client['{DB_NAME}']\n\n")
        f.write("collections = [\n")
        for coll_name in manifest["collections"]:
            f.write(f"    '{coll_name}',\n")
        f.write("]\n\n")
        f.write("for coll_name in collections:\n")
        f.write("    with open(f'{coll_name}.jsonl', 'r', encoding='utf-8') as f:\n")
        f.write("        docs = [json_util.loads(line) for line in f if line.strip()]\n")
        f.write("    if docs:\n")
        f.write("        from pymongo import UpdateOne\n")
        f.write("        ops = [UpdateOne({'_id': d['_id']}, {'$set': d}, upsert=True) for d in docs]\n")
        f.write("        db[coll_name].bulk_write(ops)\n")
        f.write("        print(f'{coll_name}: {len(docs)} 条导入完成')\n")
        f.write("```\n")

    # 打包为 zip
    zip_path = OUTPUT_DIR / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in temp_dir.iterdir():
            zf.write(file_path, file_path.name)

    # 清理临时目录
    for file_path in temp_dir.iterdir():
        file_path.unlink()
    temp_dir.rmdir()

    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
    print()
    print(f"导出完成: {zip_path}")
    print(f"文件大小: {zip_size_mb:.2f} MB")
    print()
    print("包含文件:")
    print(f"  manifest.json       — 导出清单（集合/记录数/描述）")
    print(f"  README_import.md    — 导入使用说明")
    for coll_name, info in manifest["collections"].items():
        print(f"  {coll_name}.jsonl    — {info['description']} ({info['record_count']:,}条)")

    client.close()
    print()
    print("跨系统导入: 解压 zip → 按 README_import.md 操作即可")


if __name__ == "__main__":
    main()
