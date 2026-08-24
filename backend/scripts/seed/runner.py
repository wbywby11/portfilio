# -*- coding: utf-8 -*-
"""
生产数据初始化统一入口

按依赖顺序执行所有 seed 脚本：
  1. trade_dates（交易日历 — 其他导入可能校验交易日）
  2. assets（资产主数据 — 行情导入依赖资产存在）
  3. fx_rates（汇率 — 独立）
  4. prices（行情 — 依赖 assets）

数据文件约定放在 --data-dir 目录下：
  data/seed/
  ├── trade_dates.xlsx    ← 交易日历
  ├── assets.xlsx         ← 资产主数据
  ├── fx_rates.xlsx       ← 汇率
  └── prices.xlsx         ← 行情（宽表或长表）

用法：
    # 全量初始化（生产部署时）
    python -m scripts.seed.runner --data-dir data/seed

    # 预览模式
    python -m scripts.seed.runner --data-dir data/seed --dry-run

    # 只执行部分（跳过某些步骤）
    python -m scripts.seed.runner --data-dir data/seed --only assets,prices

    # 指定数据库
    python -m scripts.seed.runner --data-dir data/seed --db asset_allocation --mongo-uri mongodb://localhost:27017
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import settings  # noqa: E402

# 导入顺序（按依赖关系）
SEED_ORDER = [
    ("trade_dates", "trade_dates.xlsx", "scripts.seed.seed_trade_dates", "SeedTradeDates"),
    ("assets", "assets.xlsx", "scripts.seed.seed_assets", "SeedAssets"),
    ("fx_rates", "fx_rates.xlsx", "scripts.seed.seed_fx_rates", "SeedFxRates"),
    ("prices", "prices.xlsx", "scripts.seed.seed_prices", "SeedPrices"),
]


def main():
    parser = argparse.ArgumentParser(
        description="生产数据初始化统一入口（按依赖顺序执行）"
    )
    parser.add_argument(
        "--data-dir", type=str, default="data/seed",
        help="数据文件目录（默认: data/seed）"
    )
    parser.add_argument(
        "--mongo-uri", type=str, default=settings.MONGODB_URL,
        help=f"MongoDB URI（默认: {settings.MONGODB_URL}）"
    )
    parser.add_argument(
        "--db", type=str, default=settings.DATABASE_NAME,
        help=f"数据库名（默认: {settings.DATABASE_NAME}）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只解析校验，不写库"
    )
    parser.add_argument(
        "--only", type=str, default="",
        help="只执行指定步骤（逗号分隔），如: assets,prices"
    )
    parser.add_argument(
        "--skip", type=str, default="",
        help="跳过指定步骤（逗号分隔），如: fx_rates"
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(f"错误: 数据目录不存在 {data_dir}")
        print(f"请创建目录并放入数据文件: {data_dir.resolve()}")
        sys.exit(1)

    # 解析 only/skip
    only_set = set(s.strip() for s in args.only.split(",") if s.strip()) if args.only else None
    skip_set = set(s.strip() for s in args.skip.split(",") if s.strip()) if args.skip else set()

    print("=" * 70)
    print("  生产数据初始化")
    print(f"  数据目录: {data_dir.resolve()}")
    print(f"  目标数据库: {args.db} ({args.mongo_uri})")
    print(f"  模式: {'DRY-RUN（不写库）' if args.dry_run else '正式写入'}")
    if only_set:
        print(f"  仅执行: {', '.join(only_set)}")
    if skip_set:
        print(f"  跳过: {', '.join(skip_set)}")
    print("=" * 70)

    t0 = time.time()
    results: Dict[str, Dict] = {}
    skipped_files: List[str] = []

    for step_name, filename, module_path, class_name in SEED_ORDER:
        # 过滤
        if only_set and step_name not in only_set:
            continue
        if step_name in skip_set:
            print(f"\n[skip] {step_name}（用户跳过）")
            continue

        file_path = data_dir / filename
        if not file_path.is_file():
            skipped_files.append(f"{step_name} ({filename} 不存在)")
            print(f"\n[skip] {step_name}: 文件不存在 {file_path}")
            continue

        # 动态导入模块并执行
        try:
            import importlib
            mod = importlib.import_module(module_path)
            seed_cls = getattr(mod, class_name)

            # 构造参数
            seed_args = argparse.Namespace(
                file=str(file_path),
                mongo_uri=args.mongo_uri,
                db=args.db,
                dry_run=args.dry_run,
                mode="upsert",
                format="auto",
                auto_create_assets=True,
            )
            instance = seed_cls(seed_args)
            stats = instance.execute(file_path)
            instance.close()
            results[step_name] = stats

        except Exception as e:
            print(f"\n[ERROR] {step_name} 执行失败: {e}")
            results[step_name] = {"error": str(e)}

    # 汇总
    duration = time.time() - t0
    print("\n" + "=" * 70)
    print("  执行汇总")
    print("=" * 70)
    print(f"  {'步骤':<15} {'总行数':>8} {'新增':>8} {'更新':>8} {'跳过':>8} {'错误':>8}")
    print(f"  {'-'*15} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for step_name, _, _, _ in SEED_ORDER:
        if step_name not in results:
            continue
        r = results[step_name]
        if "error" in r:
            print(f"  {step_name:<15} {'FAILED':>8} {r['error']}")
        else:
            print(f"  {step_name:<15} {r.get('total_rows',0):>8} {r.get('inserted',0):>8} "
                  f"{r.get('updated',0):>8} {r.get('skipped',0):>8} {r.get('errors',0):>8}")

    if skipped_files:
        print(f"\n  跳过（文件缺失）: {', '.join(skipped_files)}")

    print(f"\n  总耗时: {duration:.1f}s")
    print("=" * 70)

    # 退出码
    has_errors = any("error" in r or r.get("errors", 0) > 0 for r in results.values())
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
