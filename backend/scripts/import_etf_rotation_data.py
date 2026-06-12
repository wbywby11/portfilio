# -*- coding: utf-8 -*-
"""
一次性脚本：导入 ETF 周期轮动策略所需的 ETF 数据到系统数据库

数据源：d:/project/周期轮动策略/ 下的 7 个 Excel 文件 + 上证指数
  - 收盘价.xlsx、开盘价.xlsx、最高点.xlsx、最低价.xlsx
  - 成交额.xlsx、涨跌幅.xlsx、规模.xlsx
  - 上证指数.xlsx

Excel 格式（ETF 文件）:
  第 0 行 = ETF 代码（如 159869.SZ）
  第 1 行 = ETF 中文名称
  第 2 行起 = 日期(第0列) + 各 ETF 数据

处理流程:
  1. 读取并合并 open/high/low/close/volume 到每个 ETF 的逐日行情
  2. 执行相关性剔除（复用 data_preprocessing 逻辑），得到最终 ETF 候选池
  3. 为候选池中的每个 ETF 创建 Asset 记录（类型=基金）并导入行情
  4. 导入上证指数（000001.SH）作为风控指数

用法（在 portfilio-end 项目根目录）:
  py -m scripts.import_etf_rotation_data                   # 正式导入
  py -m scripts.import_etf_rotation_data --dry-run         # 仅预览，不写库
  py -m scripts.import_etf_rotation_data --replace         # 覆盖已有行情
  py -m scripts.import_etf_rotation_data --all-etfs        # 导入全部 ETF（不做相关性剔除）
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd

# 添加项目根目录
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

# ETF 数据目录
ETF_DATA_DIR = Path(r"d:\project\周期轮动策略")


# ============================================================
# 1. 数据读取（从 data_preprocessing.py 精简迁移）
# ============================================================

def _read_etf_excel(filepath: Path, key: str) -> tuple[pd.DataFrame, dict[str, str]]:
    """
    读取单个 ETF Excel 文件，返回 (DataFrame, etf_names_dict).

    DataFrame: index=DatetimeIndex, columns=ETF代码, values=float64
    etf_names_dict: {代码: 中文名}
    """
    df_raw = pd.read_excel(filepath, header=None)

    etf_codes = df_raw.iloc[0, 1:].values
    etf_names_row = df_raw.iloc[1, 1:].values

    # 最高点.xlsx 含 Unnamed 列，需剔除
    if key == "high":
        valid_mask = np.array([
            not (pd.isna(c) or (isinstance(c, str) and "Unnamed" in c))
            for c in etf_codes
        ])
        etf_codes = etf_codes[valid_mask]
        etf_names_row = etf_names_row[valid_mask]
        valid_cols = [0] + [i + 1 for i, v in enumerate(valid_mask) if v]
        df_raw = df_raw.iloc[:, valid_cols]

    # 构建名称映射
    names: dict[str, str] = {}
    for code, name in zip(etf_codes, etf_names_row):
        if not pd.isna(code):
            names[str(code)] = str(name) if not pd.isna(name) else ""

    # 数据区：从第 2 行开始
    df_data = df_raw.iloc[2:, :].copy()
    columns = ["date"] + [str(c) for c in etf_codes if not pd.isna(c)]
    df_data.columns = columns[: len(df_data.columns)]

    if key == "high":
        df_data = df_data.dropna(subset=["date"])

    df_data["date"] = pd.to_datetime(df_data["date"])
    df_data = df_data.set_index("date").sort_index()

    for col in df_data.columns:
        df_data[col] = pd.to_numeric(df_data[col], errors="coerce").astype(np.float64)

    return df_data, names


def load_all_etf_data() -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """
    读取 7 个 Excel 文件，返回 (data_dict, etf_names).

    data_dict 键: open, close, high, low, volume, pct_change, scale
    """
    file_map = {
        "open": "开盘价.xlsx",
        "close": "收盘价.xlsx",
        "high": "最高点.xlsx",
        "low": "最低价.xlsx",
        "volume": "成交额.xlsx",
        "pct_change": "涨跌幅.xlsx",
        "scale": "规模.xlsx",
    }

    data_dict: dict[str, pd.DataFrame] = {}
    etf_names: dict[str, str] = {}

    for key, filename in file_map.items():
        filepath = ETF_DATA_DIR / filename
        if not filepath.exists():
            print(f"  警告: {filepath} 不存在，跳过")
            continue
        print(f"  读取: {filename} ...", end=" ")
        df, names = _read_etf_excel(filepath, key)
        data_dict[key] = df
        if not etf_names:
            etf_names = names
        print(f"{df.shape[0]} 行 x {df.shape[1]} 列")

    # 交易日过滤：成交额>0 的日期
    if "volume" in data_dict:
        vol_df = data_dict["volume"]
        trading_days = vol_df.index[vol_df.max(axis=1) > 0]
        n_removed = len(vol_df) - len(trading_days)
        if n_removed > 0:
            print(f"  过滤非交易日: {n_removed} 天")
        for k in data_dict:
            data_dict[k] = data_dict[k].loc[data_dict[k].index.intersection(trading_days)]

    # 零值替换 NaN（涨跌幅除外）
    for k in data_dict:
        if k != "pct_change":
            data_dict[k] = data_dict[k].replace(0, np.nan)

    # 缺失值处理：上市后 ffill
    if "open" in data_dict:
        open_df = data_dict["open"]
        listing_dates: dict[str, pd.Timestamp] = {}
        for col in open_df.columns:
            non_nan = open_df[col].dropna().index
            if len(non_nan) > 0:
                listing_dates[col] = non_nan[0]

        for k, df in data_dict.items():
            for col in df.columns:
                if col in listing_dates:
                    mask = df.index >= listing_dates[col]
                    df.loc[mask, col] = df.loc[mask, col].ffill()
            data_dict[k] = df

    return data_dict, etf_names


def load_sh_index() -> pd.DataFrame:
    """
    加载上证指数数据，返回 DataFrame (index=日期, columns=[sh_open, sh_close]).
    """
    filepath = ETF_DATA_DIR / "上证指数.xlsx"
    if not filepath.exists():
        print(f"  警告: {filepath} 不存在")
        return pd.DataFrame()
    df = pd.read_excel(filepath, header=2)
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.set_index("日期").sort_index()
    sh = df[["open", "close"]].copy()
    sh.columns = ["sh_open", "sh_close"]
    for c in sh.columns:
        sh[c] = pd.to_numeric(sh[c], errors="coerce").astype(np.float64)
    print(f"  上证指数: {sh.shape[0]} 行, 范围 {sh.index[0].date()} ~ {sh.index[-1].date()}")
    return sh


# ============================================================
# 2. 相关性剔除（精简版）
# ============================================================

def filter_correlated_etfs(
    data_dict: dict[str, pd.DataFrame],
    etf_names: dict[str, str],
    corr_threshold: float = 0.9,
) -> tuple[list[str], list[dict]]:
    """
    剔除高相关性 ETF，返回 (filtered_pool, removed_list).
    """
    close_df = data_dict["close"]
    scale_df = data_dict.get("scale")

    last_year = close_df.tail(250)
    returns = last_year.pct_change()
    valid_counts = returns.notna().sum()
    valid_etfs = valid_counts[valid_counts >= 100].index.tolist()
    returns = returns[valid_etfs]

    corr_matrix = returns.corr()
    latest_scale = scale_df.iloc[-1] if scale_df is not None else pd.Series(dtype=float)

    remaining: set[str] = set(valid_etfs)
    removed: list[dict] = []

    for i, etf1 in enumerate(valid_etfs):
        if etf1 not in remaining:
            continue
        for j, etf2 in enumerate(valid_etfs):
            if i >= j or etf2 not in remaining:
                continue
            corr_val = corr_matrix.loc[etf1, etf2]
            if pd.notna(corr_val) and abs(corr_val) > corr_threshold:
                s1 = latest_scale.get(etf1, 0)
                s2 = latest_scale.get(etf2, 0)
                s1 = 0 if pd.isna(s1) else s1
                s2 = 0 if pd.isna(s2) else s2
                to_remove = etf2 if s1 >= s2 else etf1
                kept = etf1 if to_remove == etf2 else etf2
                if to_remove in remaining:
                    remaining.remove(to_remove)
                    removed.append({
                        "removed": to_remove,
                        "removed_name": etf_names.get(to_remove, ""),
                        "kept": kept,
                        "kept_name": etf_names.get(kept, ""),
                        "corr": round(corr_val, 4),
                    })

    return sorted(remaining), removed


# ============================================================
# 3. 合并行情记录
# ============================================================

def build_price_records(
    etf_code: str,
    data_dict: dict[str, pd.DataFrame],
) -> list[dict]:
    """
    为单个 ETF 合并 open/high/low/close/volume 到行情记录列表.

    返回: [{"date": "YYYY-MM-DD", "open": float|None, "close": float, ...}, ...]
    """
    close_df = data_dict.get("close")
    if close_df is None or etf_code not in close_df.columns:
        return []

    close_series = close_df[etf_code].dropna()
    if close_series.empty:
        return []

    records: list[dict] = []
    for date_idx, close_val in close_series.items():
        rec: dict = {
            "date": date_idx.strftime("%Y-%m-%d"),
            "close": float(close_val),
        }

        # open
        if "open" in data_dict and etf_code in data_dict["open"].columns:
            v = data_dict["open"].loc[date_idx, etf_code] if date_idx in data_dict["open"].index else None
            rec["open"] = float(v) if v is not None and not pd.isna(v) else None
        else:
            rec["open"] = None

        # high
        if "high" in data_dict and etf_code in data_dict["high"].columns:
            v = data_dict["high"].loc[date_idx, etf_code] if date_idx in data_dict["high"].index else None
            rec["high"] = float(v) if v is not None and not pd.isna(v) else None
        else:
            rec["high"] = None

        # low
        if "low" in data_dict and etf_code in data_dict["low"].columns:
            v = data_dict["low"].loc[date_idx, etf_code] if date_idx in data_dict["low"].index else None
            rec["low"] = float(v) if v is not None and not pd.isna(v) else None
        else:
            rec["low"] = None

        # volume (成交额)
        if "volume" in data_dict and etf_code in data_dict["volume"].columns:
            v = data_dict["volume"].loc[date_idx, etf_code] if date_idx in data_dict["volume"].index else None
            rec["volume"] = float(v) if v is not None and not pd.isna(v) else None
        else:
            rec["volume"] = None

        rec["amount"] = None
        records.append(rec)

    return records


def build_sh_index_records(sh_df: pd.DataFrame) -> list[dict]:
    """
    将上证指数 DataFrame 转为行情记录列表（open + close）.
    """
    if sh_df.empty:
        return []
    records: list[dict] = []
    for date_idx, row in sh_df.iterrows():
        o = row.get("sh_open")
        c = row.get("sh_close")
        if pd.isna(c):
            continue
        records.append({
            "date": date_idx.strftime("%Y-%m-%d"),
            "open": float(o) if not pd.isna(o) else None,
            "high": None,
            "low": None,
            "close": float(c),
            "volume": None,
            "amount": None,
        })
    return records


# ============================================================
# 4. 主流程
# ============================================================

async def main() -> None:
    parser = argparse.ArgumentParser(description="导入 ETF 周期轮动策略数据")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入数据库")
    parser.add_argument("--replace", action="store_true", help="覆盖已有行情（先删后写）")
    parser.add_argument("--all-etfs", action="store_true", help="导入全部 ETF（不做相关性剔除）")
    parser.add_argument("--corr-threshold", type=float, default=0.9, help="相关性剔除阈值（默认 0.9）")
    args = parser.parse_args()

    print("=" * 60)
    print("ETF 周期轮动策略 - 数据导入脚本")
    print("=" * 60)
    print(f"  数据目录: {ETF_DATA_DIR}")
    print(f"  模式: {'dry-run（不写库）' if args.dry_run else '正式导入'}")
    print(f"  覆盖已有: {args.replace}")
    print(f"  相关性剔除: {'跳过' if args.all_etfs else f'阈值={args.corr_threshold}'}")
    print()

    # ------ 1. 读取 ETF 数据 ------
    print("【1/5】读取 ETF 数据文件")
    data_dict, etf_names = load_all_etf_data()

    if "close" not in data_dict:
        print("错误: 缺少收盘价数据，无法继续")
        return

    all_etf_codes = list(data_dict["close"].columns)
    print(f"  ETF 总数: {len(all_etf_codes)}")
    close_df = data_dict["close"]
    print(f"  数据范围: {close_df.index[0].date()} ~ {close_df.index[-1].date()}")
    print(f"  交易日数: {len(close_df)}")
    print()

    # ------ 2. 读取上证指数 ------
    print("【2/5】读取上证指数")
    sh_df = load_sh_index()
    print()

    # ------ 3. 相关性剔除 ------
    print("【3/5】确定 ETF 候选池")
    if args.all_etfs:
        # 导入全部 ETF，不做任何过滤
        etf_pool = all_etf_codes
        removed = []
        print(f"  跳过相关性剔除，导入全部 ETF: {len(etf_pool)}")
    else:
        etf_pool, removed = filter_correlated_etfs(data_dict, etf_names, args.corr_threshold)
        print(f"  剔除高相关 ETF: {len(removed)} 只")
        if removed[:5]:
            for r in removed[:5]:
                print(f"    剔除 {r['removed']}({r['removed_name']}) ← 与 {r['kept']}({r['kept_name']}) 相关性={r['corr']}")
            if len(removed) > 5:
                print(f"    ... 共 {len(removed)} 只")
    print(f"  最终候选池: {len(etf_pool)} 只 ETF")
    print()

    # ------ 4. 汇总待导入 ------
    # 候选池 ETF + 上证指数
    import_list: list[tuple[str, str, str]] = []  # (code, name, asset_type_str)
    for code in etf_pool:
        name = etf_names.get(code, code)
        import_list.append((code, name, "ETF"))

    sh_index_code = "000001.SH"
    sh_index_name = "上证指数"
    if not sh_df.empty:
        import_list.append((sh_index_code, sh_index_name, "INDEX"))

    print("【4/5】数据预览")
    total_records = 0
    preview_rows: list[tuple[str, str, int, str, str]] = []
    for code, name, atype in import_list:
        if code == sh_index_code:
            recs = build_sh_index_records(sh_df)
        else:
            recs = build_price_records(code, data_dict)
        n = len(recs)
        total_records += n
        d_min = recs[0]["date"] if recs else "-"
        d_max = recs[-1]["date"] if recs else "-"
        preview_rows.append((code, name, n, d_min, d_max))

    # 打印预览表
    print(f"  {'代码':<15} {'名称':<20} {'行数':>6} {'起始日期':<12} {'截止日期':<12}")
    print(f"  {'-' * 15} {'-' * 20} {'-' * 6} {'-' * 12} {'-' * 12}")
    for code, name, n, d_min, d_max in preview_rows[:10]:
        display_name = name[:18] if len(name) > 18 else name
        print(f"  {code:<15} {display_name:<20} {n:>6} {d_min:<12} {d_max:<12}")
    if len(preview_rows) > 10:
        print(f"  ... 共 {len(preview_rows)} 个资产")
    print(f"  总行情记录数: {total_records:,}")
    print()

    if args.dry_run:
        print("【dry-run 模式】预览结束，未写入数据库。")
        return

    # ------ 5. 写入数据库 ------
    print("【5/5】写入数据库")

    from app.config.database import Database
    from app.models.asset import Asset, AssetType
    from app.services.asset_service import AssetService

    Database.connect()
    asset_service = AssetService()

    created_count = 0
    skipped_count = 0
    total_inserted = 0
    total_updated = 0
    errors: list[str] = []

    for idx, (code, name, atype) in enumerate(import_list, 1):
        progress = f"[{idx}/{len(import_list)}]"

        # 创建 Asset（如不存在）
        existing = await asset_service.get_asset_by_code(code)
        if not existing:
            asset_type = AssetType.FUND if atype == "ETF" else AssetType.INDEX
            asset = Asset(
                code=code,
                name=name,
                asset_type=asset_type,
                exchange=_infer_exchange(code),
                is_active=True,
            )
            await asset_service.create_asset(asset)
            created_count += 1
            print(f"  {progress} 创建资产: {code} ({name})")
        else:
            skipped_count += 1

        # 构建行情
        if code == sh_index_code:
            price_list = build_sh_index_records(sh_df)
        else:
            price_list = build_price_records(code, data_dict)

        if not price_list:
            print(f"  {progress} {code}: 无行情数据，跳过")
            continue

        # 导入行情
        try:
            result = await asset_service.import_price_data(
                asset_code=code,
                price_data_list=price_list,
                replace_existing=args.replace,
            )
            ins = result["inserted_count"]
            upd = result["updated_count"]
            err = result["error_count"]
            total_inserted += ins
            total_updated += upd
            if err > 0:
                errors.append(f"{code}: {err} 条错误")
            # 每 20 个资产打印一次进度
            if idx % 20 == 0 or idx == len(import_list):
                print(f"  {progress} 进度: {code} ins={ins} upd={upd}")
        except Exception as e:
            errors.append(f"{code}: {str(e)}")
            print(f"  {progress} 错误: {code} - {e}")

    # ------ 结果汇总 ------
    print()
    print("=" * 60)
    print("导入完成")
    print("=" * 60)
    print(f"  资产总数: {len(import_list)}")
    print(f"  新建资产: {created_count}")
    print(f"  已存在(跳过): {skipped_count}")
    print(f"  行情插入: {total_inserted:,}")
    print(f"  行情更新: {total_updated:,}")
    if errors:
        print(f"  错误数: {len(errors)}")
        for e in errors[:10]:
            print(f"    - {e}")
    print()
    print("提示: ETF 候选池中的资产代码可在前端创建 ETF 周期轮动模型时选择。")
    print(f"风控指数代码: {sh_index_code}（需加入模型的资产列表中）")


def _infer_exchange(code: str) -> Optional[str]:
    """从代码后缀推断交易所."""
    c = str(code).upper()
    if ".SH" in c:
        return "SSE"
    if ".SZ" in c:
        return "SZSE"
    return None


if __name__ == "__main__":
    asyncio.run(main())
