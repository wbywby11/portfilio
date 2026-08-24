# -*- coding: utf-8 -*-
"""
夏普率策略数据导入脚本 — 大类资产模型研究实验数据 → MongoDB

数据源（默认路径）：D:/project/portfilio/大类资产模型研究实验最新在用/raw_data/
  - daily_px.xlsx      : 5590 行 × 18 资产（中文列名），2005-01-03 ~ 2026-06-05
  - fx.xlsx            : USD, CNH, JPY 三列汇率（对人民币）
  - 资产费用.xlsx       : 18 资产的交易费用 + 复制费用
  - trade_dates.xlsx   : 交易日历

目标 MongoDB 集合：
  - assets        : 18 个资产文档（含 trading_cost / replication_cost / currency / weight_cap）
  - asset_prices  : 18 资产 × N 日的价格文档 {date, asset_code, close}
  - fx_rates      : USD / CNH / JPY 汇率文档（增量填补已有集合）
  - trade_dates   : 交易日历文档 {date}

用法：
  # 增量导入（默认）
  python scripts/import_sharpe_strategy_data.py

  # 替换模式（先删后插）
  python scripts/import_sharpe_strategy_data.py --replace

  # 预览不写库
  python scripts/import_sharpe_strategy_data.py --dry-run

  # 指定数据源路径
  python scripts/import_sharpe_strategy_data.py --source "D:/path/to/raw_data"
"""
from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from bson import ObjectId
from pymongo import MongoClient, UpdateOne

# ---------------------------------------------------------------------------
# 项目路径（使 import 可用 app 模块）
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------
DEFAULT_SOURCE = Path("D:/project/portfilio")
DEFAULT_MONGO_URI = "mongodb://localhost:27017"
DEFAULT_DB = "asset_allocation"
BATCH_SIZE = 5000

# ---------------------------------------------------------------------------
# 18 资产代码映射（中文名 → 系统标准代码）
# ---------------------------------------------------------------------------
SHARPE_NAME_TO_CODE = {
    '沪深300': '000300.SH',
    '中证500': 'ZZ000905',
    '创业板指': 'SZ399006',
    '标普500': 'SPX',
    '纳斯达克100': 'NDX',
    '日经225': 'N225',
    '中国10年国债': 'ZQGZ10',
    '中国5年国债': 'ZQGZ5',
    '中国2年国债': 'ZQGZ2',
    '美国10年国债': 'UST10',
    '美国2年国债': 'UST2',
    '可转债': 'CVTBND',
    '黄金': 'GLD',
    '布伦特原油': 'B00Y',
    '沪铜': 'SHCU',
    '沪铝': 'SHAL',
    '沪锡': 'SHSN',
    '豆粕': 'DM',
}

SHARPE_CODE_TO_NAME = {v: k for k, v in SHARPE_NAME_TO_CODE.items()}

# ---------------------------------------------------------------------------
# 18 资产静态配置（费率、货币、权重上限 — 来自原型 资产费用.xlsx + 编制规则）
# ---------------------------------------------------------------------------
ASSET_CURRENCY = {
    '沪深300': 'CNH', '中证500': 'CNH', '创业板指': 'CNH',
    '标普500': 'USD', '纳斯达克100': 'USD', '日经225': 'JPY',
    '中国10年国债': 'CNH', '中国5年国债': 'CNH', '中国2年国债': 'CNH',
    '美国10年国债': 'USD', '美国2年国债': 'USD',
    '可转债': 'CNH', '黄金': 'CNH', '布伦特原油': 'USD',
    '沪铜': 'CNH', '沪铝': 'CNH', '沪锡': 'CNH', '豆粕': 'CNH',
}

WEIGHT_CAPS = {
    '沪深300': 0.10, '中证500': 0.10, '创业板指': 0.10,
    '标普500': 0.15, '纳斯达克100': 0.15, '日经225': 0.10,
    '中国10年国债': 0.60, '中国5年国债': 0.60, '中国2年国债': 0.90,
    '美国10年国债': 0.60, '美国2年国债': 0.60,
    '可转债': 0.10, '黄金': 0.10, '布伦特原油': 0.10,
    '沪铜': 0.10, '沪铝': 0.10, '沪锡': 0.10, '豆粕': 0.10,
}

TRADING_COST = {
    '沪深300': 0.0003, '中证500': 0.0003, '创业板指': 0.0003,
    '标普500': 0.0002, '纳斯达克100': 0.0002, '日经225': 0.0003,
    '中国10年国债': 0.0003, '中国5年国债': 0.0003, '中国2年国债': 0.0003,
    '美国10年国债': 0.0002, '美国2年国债': 0.0002,
    '可转债': 0.0003, '黄金': 0.0003, '布伦特原油': 0.0001,
    '沪铜': 0.0003, '沪铝': 0.0003, '沪锡': 0.0003, '豆粕': 0.0003,
}

REPLICATION_COST = {
    '沪深300': 0.004, '中证500': 0.004, '创业板指': 0.030,
    '标普500': 0.006, '纳斯达克100': 0.006, '日经225': 0.006,
    '中国10年国债': 0.003, '中国5年国债': 0.003, '中国2年国债': 0.003,
    '美国10年国债': 0.004, '美国2年国债': 0.004,
    '可转债': 0.030, '黄金': 0.006, '布伦特原油': 0.006,
    '沪铜': 0.006, '沪铝': 0.006, '沪锡': 0.006, '豆粕': 0.006,
}

ASSET_CLASS_MAP = {
    '沪深300': '权益', '中证500': '权益', '创业板指': '权益',
    '标普500': '权益', '纳斯达克100': '权益', '日经225': '权益',
    '中国10年国债': '固收', '中国5年国债': '固收', '中国2年国债': '固收',
    '美国10年国债': '固收', '美国2年国债': '固收',
    '可转债': '固收',
    '黄金': '商品', '布伦特原油': '商品',
    '沪铜': '商品', '沪铝': '商品', '沪锡': '商品', '豆粕': '商品',
}


# ===========================================================================
# Step 1: assets 集合 — 创建/更新 18 个资产文档
# ===========================================================================
def build_asset_docs(db=None) -> List[OrderedDict]:
    """为 18 个资产创建/更新 assets 文档。"""
    now = datetime.now(timezone.utc)
    docs: List[OrderedDict] = []

    for cn_name, code in SHARPE_NAME_TO_CODE.items():
        # 检查已有记录以保持 _id 和 created_at
        existing = None
        if db is not None:
            existing = db["assets"].find_one({"code": code})

        oid = existing["_id"] if existing else ObjectId()
        created = (existing.get("created_at") if existing else None) or now

        docs.append(OrderedDict([
            ("_id", oid),
            ("code", code),
            ("name", cn_name),
            ("instrument_type", "指数型"),
            ("asset_class", ASSET_CLASS_MAP.get(cn_name, "商品")),
            ("security_type", "指数"),
            ("asset_type", "指数类"),
            ("exchange", ""),
            ("description", f"夏普率策略18资产 - {cn_name}"),
            ("is_active", True if not existing else existing.get("is_active", True)),
            ("currency", ASSET_CURRENCY.get(cn_name, "CNH")),
            ("weight_cap", WEIGHT_CAPS.get(cn_name, 0.10)),
            ("trading_cost", TRADING_COST.get(cn_name, 0.0003)),
            ("replication_cost", REPLICATION_COST.get(cn_name, 0.006)),
            ("rollover_days", None),
            ("rollover_threshold", None),
            ("rollover_window_p", None),
            ("rollover_window_q", None),
            ("substitute_code", existing.get("substitute_code", "") if existing else ""),
            ("switch_date", existing.get("switch_date", "") if existing else ""),
            ("created_at", created),
            ("updated_at", now),
        ]))

    return docs


def import_assets(db, docs: List[OrderedDict], dry_run: bool = False) -> int:
    """Upsert 资产文档到 MongoDB。"""
    if dry_run:
        print(f"  [dry-run] 将 upsert {len(docs)} 个资产文档")
        return len(docs)

    count = 0
    for doc in docs:
        d = dict(doc)
        db["assets"].replace_one({"code": d["code"]}, d, upsert=True)
        count += 1
    print(f"  assets: 已 upsert {count} 个资产")
    return count


# ===========================================================================
# Step 2: asset_prices 集合 — 导入 18 资产价格
# ===========================================================================
def build_price_docs(df: pd.DataFrame, replace: bool = False) -> List[OrderedDict]:
    """从 daily_px.xlsx DataFrame 构建 asset_prices 文档。"""
    docs: List[OrderedDict] = []

    for cn_name in df.columns:
        code = SHARPE_NAME_TO_CODE.get(cn_name)
        if not code:
            print(f"  [警告] 跳过未知资产: {cn_name}")
            continue

        series = df[cn_name].dropna()
        for dt_idx, val in series.items():
            try:
                close_val = float(val)
            except (TypeError, ValueError):
                continue
            if close_val <= 0 or pd.isna(close_val):
                continue
            ds = pd.Timestamp(dt_idx).strftime("%Y-%m-%d")
            docs.append(OrderedDict([
                ("date", ds),
                ("asset_code", code),
                ("amount", None),
                ("close", close_val),
                ("high", None),
                ("low", None),
                ("open", None),
                ("volume", None),
                ("scale", None),
            ]))

    return docs


def import_prices(
    db, docs: List[OrderedDict], asset_codes: List[str],
    replace: bool = False, dry_run: bool = False,
) -> Dict[str, int]:
    """写入 asset_prices 集合。"""
    result = {"inserted": 0, "updated": 0}

    if dry_run:
        print(f"  [dry-run] 将写入 {len(docs)} 条价格文档 "
              f"(replace={replace}, 涉及 {len(asset_codes)} 个资产)")
        result["inserted"] = len(docs)
        return result

    coll = db["asset_prices"]

    if replace:
        dr = coll.delete_many({"asset_code": {"$in": asset_codes}})
        print(f"  [replace] asset_prices 已删除: {dr.deleted_count} 条")
        # 替换模式：直接批量插入
        ins = 0
        for i in range(0, len(docs), BATCH_SIZE):
            chunk = [dict(x) for x in docs[i:i + BATCH_SIZE]]
            if chunk:
                coll.insert_many(chunk)
                ins += len(chunk)
                print(f"    asset_prices 已插入: {ins}/{len(docs)}")
        result["inserted"] = ins
        print(f"  asset_prices 完成: 共插入 {ins} 条")
    else:
        # 增量模式：UpdateOne(upsert=True) 按 (asset_code, date) 去重
        total_updated = 0
        total_inserted = 0
        for i in range(0, len(docs), BATCH_SIZE):
            chunk = docs[i:i + BATCH_SIZE]
            ops = []
            for doc in chunk:
                set_doc = {k: v for k, v in doc.items() if k != "_id"}
                ops.append(UpdateOne(
                    {"asset_code": doc["asset_code"], "date": doc["date"]},
                    {"$set": set_doc},
                    upsert=True,
                ))
            if ops:
                r = coll.bulk_write(ops, ordered=False)
                total_updated += r.modified_count
                total_inserted += r.upserted_count
            done = min(i + BATCH_SIZE, len(docs))
            print(f"    asset_prices 进度: {done}/{len(docs)} "
                  f"(新增={total_inserted}, 更新={total_updated})")
        result["inserted"] = total_inserted
        result["updated"] = total_updated
        print(f"  asset_prices 完成: 新增={total_inserted}, 更新={total_updated}")

    return result


# ===========================================================================
# Step 3: fx_rates 集合 — 导入含 JPY 的汇率数据
# ===========================================================================
def import_fx_rates(db, fx_df: pd.DataFrame, replace: bool = False,
                    dry_run: bool = False) -> Dict[str, int]:
    """导入汇率数据到 fx_rates 集合。"""
    result = {"inserted": 0, "updated": 0}

    if fx_df.empty:
        print("  fx.xlsx 为空，跳过汇率导入")
        return result

    # 构建文档列表
    records: List[Dict[str, Any]] = []
    for dt, row in fx_df.iterrows():
        date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
        rec: Dict[str, Any] = {"date": date_str}
        has_value = False
        for col in fx_df.columns:
            v = row.get(col)
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                fv = float(v)
                if fv > 0:
                    rec[col.upper()] = fv
                    has_value = True
        if has_value:
            records.append(rec)

    if dry_run:
        print(f"  [dry-run] 将写入 {len(records)} 条汇率文档 "
              f"(列: {list(fx_df.columns)})")
        result["inserted"] = len(records)
        return result

    coll = db["fx_rates"]

    if replace:
        dr = coll.delete_many({})
        print(f"  [replace] fx_rates 已删除: {dr.deleted_count} 条")
        ins = 0
        for i in range(0, len(records), BATCH_SIZE):
            chunk = records[i:i + BATCH_SIZE]
            if chunk:
                coll.insert_many(chunk)
                ins += len(chunk)
        result["inserted"] = ins
        print(f"  fx_rates 完成: 共插入 {ins} 条")
    else:
        # 增量模式：只填补缺失列
        inserted = 0
        updated = 0
        record_dates = [r["date"] for r in records]
        existing_map: Dict[str, Dict] = {}
        chunk_size = 500
        for ci in range(0, len(record_dates), chunk_size):
            chunk = record_dates[ci:ci + chunk_size]
            for doc in coll.find({"date": {"$in": chunk}}):
                existing_map[doc["date"]] = doc

        insert_docs: List[Dict] = []
        update_ops: List[UpdateOne] = []

        for rec in records:
            date_str = rec["date"]
            existing = existing_map.get(date_str)
            if not existing:
                insert_docs.append(rec)
                continue
            to_set: Dict[str, Any] = {}
            for col in ["USD", "CNH", "JPY", "EUR", "HKD"]:
                if col not in rec:
                    continue
                new_v = rec[col]
                if new_v is None or (isinstance(new_v, float) and new_v <= 0):
                    continue
                old_v = existing.get(col)
                if old_v is None or (isinstance(old_v, float) and np.isnan(old_v)):
                    to_set[col] = new_v
            if to_set:
                update_ops.append(UpdateOne({"date": date_str}, {"$set": to_set}))

        # 批量插入
        if insert_docs:
            for bi in range(0, len(insert_docs), BATCH_SIZE):
                batch = insert_docs[bi:bi + BATCH_SIZE]
                r = coll.insert_many(batch, ordered=False)
                inserted += len(r.inserted_ids)

        # 批量更新
        if update_ops:
            for bi in range(0, len(update_ops), BATCH_SIZE):
                batch = update_ops[bi:bi + BATCH_SIZE]
                r = coll.bulk_write(batch, ordered=False)
                updated += r.modified_count

        result["inserted"] = inserted
        result["updated"] = updated
        print(f"  fx_rates 完成: 新增={inserted}, 更新={updated}")

    return result


# ===========================================================================
# Step 4: trade_dates 集合 — 导入交易日历
# ===========================================================================
def import_trade_dates(db, td_df: pd.DataFrame, replace: bool = False,
                       dry_run: bool = False) -> int:
    """导入交易日历到 trade_dates 集合。"""
    count = 0

    if td_df.empty:
        print("  trade_dates.xlsx 为空，跳过交易日历导入")
        return 0

    # 提取日期列
    if td_df.shape[1] == 0:
        # 单列：index 为日期
        dates = pd.to_datetime(td_df.index).normalize()
    else:
        # 取第一列
        dates = pd.to_datetime(td_df.iloc[:, 0]).dropna()
        dates = dates.dt.normalize() if hasattr(dates, 'dt') else dates.normalize()

    date_list = sorted(set(dates))
    if dry_run:
        print(f"  [dry-run] 将写入 {len(date_list)} 个交易日文档")
        return len(date_list)

    coll = db["trade_dates"]

    if replace:
        dr = coll.delete_many({})
        print(f"  [replace] trade_dates 已删除: {dr.deleted_count} 条")

    # 构建文档并批量 upsert
    ops = []
    for dt in date_list:
        ds = dt.strftime("%Y-%m-%d")
        ops.append(UpdateOne(
            {"date": ds},
            {"$set": {"date": ds}},
            upsert=True,
        ))

    for i in range(0, len(ops), BATCH_SIZE):
        chunk = ops[i:i + BATCH_SIZE]
        r = coll.bulk_write(chunk, ordered=False)
        count += r.upserted_count + r.modified_count

    print(f"  trade_dates 完成: upsert {count} 个交易日")
    return count


# ===========================================================================
# Step 5: sharpe_rebalance_weights 集合 — 导入原型预计算权重
# ===========================================================================
def import_rebalance_weights(
    db, source_dir: Path, replace: bool = False, dry_run: bool = False,
) -> Dict[str, int]:
    """导入原型 step2 输出的月度权重到 MongoDB sharpe_rebalance_weights 集合。

    文件来源: results/权重计算结果.xlsx → sheet '权重矩阵'
    文档格式: {calc_date, weights: {asset_cn_name: weight, ...},
               total_leverage, portfolio_vol, scale_factor}
    """
    result = {"inserted": 0, "updated": 0}
    wx_path = source_dir.parent / "results" / "权重计算结果.xlsx"
    if not wx_path.is_file():
        print(f"  [警告] 权重文件不存在: {wx_path}，跳过权重导入")
        return result

    try:
        weight_df = pd.read_excel(wx_path, sheet_name="权重矩阵")
    except Exception as e:
        print(f"  [警告] 读取权重文件失败: {e}")
        return result

    if "计算日期" not in weight_df.columns:
        print(f"  [警告] 权重文件缺少 '计算日期' 列")
        return result

    weight_df["计算日期"] = pd.to_datetime(weight_df["计算日期"])
    all_assets = [c for c in weight_df.columns if c in SHARPE_NAME_TO_CODE]
    print(f"  权重文件: {len(weight_df)} 个调仓日, {len(all_assets)} 个资产")

    if dry_run:
        print(f"  [dry-run] 将写入 {len(weight_df)} 条权重文档")
        result["inserted"] = len(weight_df)
        return result

    coll = db["sharpe_rebalance_weights"]
    if replace:
        dr = coll.delete_many({})
        print(f"  [replace] sharpe_rebalance_weights 已删除: {dr.deleted_count} 条")

    ops: List[UpdateOne] = []
    for _, row in weight_df.iterrows():
        calc_date = pd.Timestamp(row["计算日期"])
        weights = {}
        for asset_cn in all_assets:
            w = row.get(asset_cn, 0.0)
            if w is not None and not (isinstance(w, float) and np.isnan(w)):
                weights[asset_cn] = float(w)
            else:
                weights[asset_cn] = 0.0
        doc = {
            "calc_date": calc_date.strftime("%Y-%m-%d"),
            "weights": weights,
            "total_leverage": float(row.get("总杠杆", sum(weights.values())) or 0.0),
            "portfolio_vol": float(row.get("组合波动率", 0.0) or 0.0),
            "scale_factor": float(row.get("缩放系数", 1.0) or 1.0),
        }
        ops.append(UpdateOne(
            {"calc_date": doc["calc_date"]},
            {"$set": doc},
            upsert=True,
        ))

    inserted = 0
    updated = 0
    for i in range(0, len(ops), BATCH_SIZE):
        chunk = ops[i:i + BATCH_SIZE]
        r = coll.bulk_write(chunk, ordered=False)
        inserted += r.upserted_count
        updated += r.modified_count

    result["inserted"] = inserted
    result["updated"] = updated
    print(f"  sharpe_rebalance_weights 完成: 新增={inserted}, 更新={updated}")
    return result


# ===========================================================================
# 主流程
# ===========================================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="夏普率策略数据导入 — daily_px/fx/资产费用/trade_dates → MongoDB"
    )
    parser.add_argument("--source", type=str, default=str(DEFAULT_SOURCE),
                        help="raw_data 目录路径")
    parser.add_argument("--mongo-uri", type=str, default=DEFAULT_MONGO_URI,
                        help="MongoDB URI")
    parser.add_argument("--db", type=str, default=DEFAULT_DB,
                        help="数据库名")
    parser.add_argument("--replace", action="store_true",
                        help="替换模式：先删后插（默认增量 upsert）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只解析不写库")
    args = parser.parse_args()

    source_dir = Path(args.source)
    if not source_dir.is_dir():
        print(f"错误: 数据源目录不存在 {source_dir}")
        sys.exit(1)

    print("=" * 70)
    print("夏普率策略数据导入")
    print(f"数据源: {source_dir}")
    print(f"MongoDB: {args.mongo_uri}/{args.db}")
    print(f"模式: {'替换' if args.replace else '增量'}"
          f"{'（dry-run）' if args.dry_run else ''}")
    print("=" * 70)

    # ---- 读取数据文件 ----
    # daily_px.xlsx 或 daily_px (1).xlsx
    px_path = source_dir / "daily_px (1).xlsx"
    if not px_path.is_file():
        px_path = source_dir / "daily_px.xlsx"
    print(f"\n[1/4] 读取价格数据: {px_path}")
    if not px_path.is_file():
        print(f"错误: 文件不存在 {px_path}")
        sys.exit(1)
    px_df = pd.read_excel(px_path, index_col=0, parse_dates=True)
    px_df.index = pd.to_datetime(px_df.index).normalize()
    # 过滤只保留映射表中存在的中文列名
    valid_cols = [c for c in px_df.columns if c in SHARPE_NAME_TO_CODE]
    px_df = px_df[valid_cols]
    print(f"  资产数: {len(px_df.columns)}, 行数: {len(px_df)}")
    print(f"  日期范围: {px_df.index.min().date()} ~ {px_df.index.max().date()}")
    print(f"  资产列表: {list(px_df.columns)}")

    # fx.xlsx
    fx_path = source_dir / "fx.xlsx"
    print(f"\n[2/4] 读取汇率数据: {fx_path}")
    fx_df = pd.DataFrame()
    if fx_path.is_file():
        fx_df = pd.read_excel(fx_path, index_col=0, parse_dates=True)
        fx_df.index = pd.to_datetime(fx_df.index).normalize()
        fx_df.columns = fx_df.columns.astype(str).str.strip().str.upper()
        print(f"  列: {list(fx_df.columns)}, 行数: {len(fx_df)}")
        print(f"  日期范围: {fx_df.index.min().date()} ~ {fx_df.index.max().date()}")
    else:
        print(f"  [警告] 文件不存在: {fx_path}，跳过汇率导入")

    # 资产费用.xlsx（用于验证费率配置）
    fee_path = source_dir / "资产费用.xlsx"
    print(f"\n[3/4] 资产费用: {fee_path}")
    if fee_path.is_file():
        fee_df = pd.read_excel(fee_path)
        print(f"  行数: {len(fee_df)}, 列: {list(fee_df.columns)}")
        print(f"  使用硬编码费率配置（与原型一致）")
    else:
        print(f"  [警告] 文件不存在: {fee_path}，使用硬编码费率")

    # trade_dates.xlsx
    td_path = source_dir / "trade_dates.xlsx"
    print(f"\n[4/4] 交易日历: {td_path}")
    td_df = pd.DataFrame()
    if td_path.is_file():
        td_df = pd.read_excel(td_path)
        # 兼容：第一列为日期（无索引）或以索引为日期
        if td_df.shape[1] > 0:
            col = td_df.columns[0]
            td_df[col] = pd.to_datetime(td_df[col])
            td_df = td_df.set_index(col)
        print(f"  行数: {len(td_df)}")
    else:
        print(f"  [警告] 文件不存在: {td_path}，跳过交易日历导入")

    # ---- 构建文档 ----
    asset_codes = sorted(set(SHARPE_NAME_TO_CODE.values()))
    print(f"\n构建文档...")
    print(f"  目标资产代码: {asset_codes}")

    # ---- 连接 MongoDB ----
    db = None
    if not args.dry_run:
        client = MongoClient(args.mongo_uri)
        db = client[args.db]
        # 统计现有数据
        existing_prices = db["asset_prices"].count_documents(
            {"asset_code": {"$in": asset_codes}}
        )
        existing_assets = db["assets"].count_documents(
            {"code": {"$in": asset_codes}}
        )
        print(f"\n数据库现有数据:")
        print(f"  asset_prices (涉及本次资产): {existing_prices} 条")
        print(f"  assets (涉及本次资产): {existing_assets} 条")
    else:
        # dry-run 模式也需要 db=None 传给 build_asset_docs
        db = None

    # ---- Step 1: assets ----
    print(f"\n{'=' * 50}")
    print("Step 1: 导入 assets 集合")
    print(f"{'=' * 50}")
    asset_docs = build_asset_docs(db)
    if args.dry_run:
        import_assets(None, asset_docs, dry_run=True)
    else:
        import_assets(db, asset_docs, dry_run=False)

    # ---- Step 2: asset_prices ----
    print(f"\n{'=' * 50}")
    print("Step 2: 导入 asset_prices 集合")
    print(f"{'=' * 50}")
    price_docs = build_price_docs(px_df)
    print(f"  文档数: {len(price_docs)}")
    if args.dry_run:
        import_prices(None, price_docs, asset_codes,
                      replace=args.replace, dry_run=True)
    else:
        import_prices(db, price_docs, asset_codes,
                      replace=args.replace, dry_run=False)

    # ---- Step 3: fx_rates ----
    print(f"\n{'=' * 50}")
    print("Step 3: 导入 fx_rates 集合 (含 JPY)")
    print(f"{'=' * 50}")
    if not fx_df.empty:
        if args.dry_run:
            import_fx_rates(None, fx_df, replace=args.replace, dry_run=True)
        else:
            import_fx_rates(db, fx_df, replace=args.replace, dry_run=False)

    # ---- Step 4: trade_dates ----
    print(f"\n{'=' * 50}")
    print("Step 4: 导入 trade_dates 集合")
    print(f"{'=' * 50}")
    if not td_df.empty:
        if args.dry_run:
            import_trade_dates(None, td_df, replace=args.replace, dry_run=True)
        else:
            import_trade_dates(db, td_df, replace=args.replace, dry_run=False)

    # ---- 验证 ----
    if not args.dry_run:
        print(f"\n{'=' * 50}")
        print("导入验证")
        print(f"{'=' * 50}")

        final_prices = db["asset_prices"].count_documents(
            {"asset_code": {"$in": asset_codes}}
        )
        final_assets = db["assets"].count_documents(
            {"code": {"$in": asset_codes}}
        )
        final_fx = db["fx_rates"].count_documents({})
        final_td = db["trade_dates"].count_documents({})

        print(f"  asset_prices (涉及本次资产): {final_prices} 条")
        print(f"  assets (涉及本次资产): {final_assets} 条")
        print(f"  fx_rates (全部): {final_fx} 条")
        print(f"  trade_dates (全部): {final_td} 条")

        # 抽样验证
        sample_code = asset_codes[0]
        sample_docs = list(
            db["asset_prices"].find({"asset_code": sample_code})
            .sort("date", -1).limit(3)
        )
        print(f"\n  抽样验证 ({sample_code} 最新3条):")
        for d in sample_docs:
            print(f"    date={d['date']}  close={d['close']}")

        sample_asset = db["assets"].find_one({"code": sample_code})
        if sample_asset:
            cn = SHARPE_CODE_TO_NAME.get(sample_code, sample_code)
            print(f"\n  assets 抽样 ({sample_code} / {cn}):")
            print(f"    name={sample_asset.get('name')}  "
                  f"currency={sample_asset.get('currency')}  "
                  f"trading_cost={sample_asset.get('trading_cost')}  "
                  f"weight_cap={sample_asset.get('weight_cap')}")

        client.close()

    print(f"\n{'=' * 70}")
    print("导入完成！")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()

