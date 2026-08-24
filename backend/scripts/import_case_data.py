"""
典型案例数据批量导入脚本

从导出的 zip 包中一次性导入全部集合到目标 MongoDB。
支持幂等导入（upsert），可重复执行。

用法:
    python import_case_data.py <zip_path> [--uri mongodb://host:port] [--db asset_allocation] [--dry-run]

示例:
    # 默认导入本地
    python import_case_data.py d:/portfilio-end/exports/case_data_export_20260615_110906.zip

    # 指定远程目标库
    python import_case_data.py case_data_export_20260615_110906.zip --uri mongodb://192.168.1.100:27017 --db asset_allocation

    # 仅预览，不实际写入
    python import_case_data.py case_data_export_20260615_110906.zip --dry-run
"""

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

from pymongo import MongoClient, UpdateOne
from bson import json_util


def import_collection(db, coll_name: str, jsonl_bytes: bytes) -> int:
    """将 JSONL 字节流导入指定集合，返回导入条数"""
    lines = jsonl_bytes.decode("utf-8").strip().split("\n")
    if not lines or not lines[0]:
        return 0

    docs = [json_util.loads(line) for line in lines if line.strip()]
    if not docs:
        return 0

    ops = [UpdateOne({"_id": d["_id"]}, {"$set": d}, upsert=True) for d in docs]
    result = db[coll_name].bulk_write(ops, ordered=False)
    return result.upserted_count + result.modified_count


def main():
    parser = argparse.ArgumentParser(description="批量导入典型案例 MongoDB 数据")
    parser.add_argument("zip_path", help="导出的 zip 文件路径")
    parser.add_argument("--uri", default="mongodb://localhost:27017", help="目标 MongoDB URI")
    parser.add_argument("--db", default="asset_allocation", help="目标数据库名")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不实际写入")
    args = parser.parse_args()

    zip_path = Path(args.zip_path)
    if not zip_path.exists():
        print(f"错误: 文件不存在 {zip_path}")
        sys.exit(1)

    print(f"{'='*70}")
    print(f"  典型案例数据批量导入")
    print(f"{'='*70}")
    print(f"  ZIP:      {zip_path.name}")
    print(f"  Target:   {args.uri}/{args.db}")
    print(f"  Dry-run:  {'YES (仅预览)' if args.dry_run else 'NO (实际写入)'}")
    print(f"{'='*70}")
    print()

    z = zipfile.ZipFile(str(zip_path))
    manifest = json.loads(z.read("manifest.json"))

    collections = manifest.get("collections", {})
    total_expected = sum(c["record_count"] for c in collections.values())

    print(f"  Manifest: {len(collections)} 个集合, {total_expected:,} 条记录")
    print(f"  Cases:    {len(manifest.get('cases', []))} 个典型案例")
    print()
    print(f"  {'#':<4} {'集合名':<45} {'预期':>8} {'实际':>8} {'耗时':>8}")
    print(f"  {'-'*75}")

    if not args.dry_run:
        client = MongoClient(args.uri)
        db = client[args.db]

    total_imported = 0
    total_time = 0.0
    errors = []

    for idx, (coll_name, info) in enumerate(collections.items(), 1):
        file_name = info["file"]
        expected = info["record_count"]
        desc = info.get("description", "")

        t0 = time.time()
        try:
            raw = z.read(file_name)
            if args.dry_run:
                lines = raw.decode("utf-8").strip().split("\n")
                actual = len([l for l in lines if l.strip()])
            else:
                actual = import_collection(db, coll_name, raw)
        except Exception as e:
            actual = 0
            errors.append((coll_name, str(e)))

        elapsed = time.time() - t0
        total_imported += actual
        total_time += elapsed

        status = "OK" if actual == expected else f"MISMATCH({actual}!={expected})"
        print(f"  {idx:<4} {coll_name:<45} {expected:>8,} {actual:>8,} {elapsed:>6.2f}s  {status}")

    print(f"  {'-'*75}")
    print(f"  {'合计':<49} {total_expected:>8,} {total_imported:>8,} {total_time:>6.2f}s")

    if errors:
        print(f"\n  错误列表 ({len(errors)} 个):")
        for coll, err in errors:
            print(f"    {coll}: {err}")
    else:
        print(f"\n  全部导入成功！0 个错误。")

    if not args.dry_run:
        # 验证：打印各集合实际记录数
        print(f"\n  导入后各集合记录数验证:")
        for coll_name, info in collections.items():
            actual_count = db[coll_name].estimated_document_count()
            marker = "OK" if actual_count >= info["record_count"] else "LOW"
            print(f"    {coll_name:<45} {actual_count:>8,} (预期>={info['record_count']:,}) {marker}")
        client.close()

    print(f"\n{'='*70}")
    print(f"  导入完成: {total_imported:,}/{total_expected:,} 条, 耗时 {total_time:.1f}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
