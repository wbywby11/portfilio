# -*- coding: utf-8 -*-
"""
将 Wind/同花顺风格的 6 个宽表 Excel（交易日期 + 多 ETF 列）合并为 MongoDB ``asset_prices`` 文档，
并可选写入数据库（与 ``AssetPrice`` / ``import_price_data(replace_existing=True)`` 一致）。

六个文件（默认文件名，可用参数覆盖路径）：
  开盘价.xlsx  最高点.xlsx  最低价.xlsx  收盘价.xlsx  规模.xlsx  成交额.xlsx

表结构约定（与常见导出一致）：
  第 1 行：第 1 列为日期列标题，其余列为 ``510300.SH`` 等形式代码；
  第 2 行：第 1 列为证券简称列标题，其余列为中文简称；
  第 3 行起：第 1 列为日期，其余为数值。

列去重：同一表内若同一 ``asset_code`` 出现多列，按从左到右优先，缺失处用右侧列补全（combine_first）。

**自然日全量**：默认将 Excel 中所有有效交易日/非交易日的行情一并写入 Mongo 与 JSON（含假期仅有收盘价等情形）。
若需恢复「仅写入系统交易日历内日期」的旧行为，请加 ``--filter-trade-days-only``。

前端 ``GET /api/v1/assets/{code}/kline`` 在服务端已按交易日历裁剪（可选 ``all_calendar_days=true`` 取自然日全量）。

输出（与仓库内样例同形的 **JSON 数组** + MongoDB Extended JSON，可供 ``mongoimport --jsonArray``）：

  - ``data/imports/asset_allocation.asset_prices.json``
  - ``data/asset_allocation.assets.json``

行情行字段顺序与样例一致：``_id``, ``date``, ``asset_code``, ``amount``, ``close``, ``high``, ``low``, ``open``, ``volume``, ``scale``。

写库（可选）：使用 ``pymongo`` 直连 ``--mongo-uri`` / ``--db``，对本次涉及的 ``asset_code`` 先 ``delete_many`` 再 ``insert_many`` 行情；``assets`` 按 ``code`` ``replace_one`` upsert（保留已有 ``_id`` 与 ``created_at``）。

用法（在项目根目录）::

  python scripts/import_etf_six_excels_to_asset_prices.py --export-only --excel-dir "C:/Users/me/Downloads"
  python scripts/import_etf_six_excels_to_asset_prices.py --write-mongo --mongo-uri "mongodb://localhost:27017" --db asset_allocation
  # 若需仅写入交易日历内日期：再加 --filter-trade-days-only

依赖：pandas、openpyxl、pymongo、bson（随 pymongo）。
"""
from __future__ import annotations

import argparse
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Set, Tuple

import pandas as pd
from bson import ObjectId
from bson.json_util import RELAXED_JSON_OPTIONS, dumps as bson_dumps

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    return False


def _norm_code(raw: Any) -> str:
    if _is_blank(raw):
        return ""
    s = str(raw).strip().replace(" ", "")
    return s


def _norm_name(raw: Any) -> str:
    if _is_blank(raw):
        return ""
    return str(raw).strip()


def _read_trade_date_set_sync(
    mongo_uri: Optional[str] = None,
    db_name: Optional[str] = None,
) -> Optional[Set[str]]:
    """优先从 Mongo ``trade_dates`` 加载；否则 ``data/trade_dates.xlsx``。"""
    out: Set[str] = set()
    if mongo_uri and db_name:
        try:
            from pymongo import MongoClient

            client = MongoClient(mongo_uri)
            db = client[db_name]
            for r in db["trade_dates"].find({}).sort("date", 1):
                dt = r.get("date")
                if dt is None:
                    continue
                if hasattr(dt, "strftime"):
                    out.add(dt.strftime("%Y-%m-%d")[:10])
                elif isinstance(dt, str) and len(dt.strip()) >= 10:
                    out.add(dt.strip()[:10])
            client.close()
        except Exception:
            out = set()
    if not out:
        try:
            from app.config.settings import settings
            from pymongo import MongoClient

            client = MongoClient(settings.MONGODB_URL)
            db = client[settings.DATABASE_NAME]
            for r in db["trade_dates"].find({}).sort("date", 1):
                dt = r.get("date")
                if dt is None:
                    continue
                if hasattr(dt, "strftime"):
                    out.add(dt.strftime("%Y-%m-%d")[:10])
                elif isinstance(dt, str) and len(dt.strip()) >= 10:
                    out.add(dt.strip()[:10])
            client.close()
        except Exception:
            out = set()
    if out:
        return out
    from app.data.trade_dates import load_trade_dates

    loaded = load_trade_dates()
    if not loaded:
        return None
    _, td_set = loaded
    for d in td_set:
        out.add(pd.Timestamp(d).strftime("%Y-%m-%d"))
    return out if out else None


def _parse_wide_sheet(path: Path) -> Tuple[Dict[str, str], pd.DataFrame]:
    """
    返回 (code -> 证券简称, 宽表 DataFrame)。
    索引：日期（datetime64）；列：去重后的 asset_code；单元格：float 或 NaN。
    """
    raw = pd.read_excel(path, header=None, engine="openpyxl")
    if raw.shape[0] < 3 or raw.shape[1] < 2:
        raise ValueError(f"表过空: {path}")

    code_to_name: Dict[str, str] = {}
    # code -> list of column indices (1-based column index in raw)
    code_to_indices: DefaultDict[str, List[int]] = defaultdict(list)
    for j in range(1, raw.shape[1]):
        code = _norm_code(raw.iat[0, j])
        if not code:
            continue
        code_to_indices[code].append(j)
        nm = _norm_name(raw.iat[1, j])
        if code not in code_to_name and nm:
            code_to_name[code] = nm

    body = raw.iloc[2:].copy()
    body = body.dropna(how="all")
    dt_col = pd.to_datetime(body.iloc[:, 0], errors="coerce")
    body = body.assign(_dt=dt_col).dropna(subset=["_dt"])
    body["_dt"] = body["_dt"].dt.normalize()

    series_list: Dict[str, pd.Series] = {}
    for code, idxs in code_to_indices.items():
        parts: List[pd.Series] = []
        for j in idxs:
            ser = pd.to_numeric(body.iloc[:, j], errors="coerce")
            ser.index = body["_dt"].values
            parts.append(ser)
        merged = parts[0]
        for p in parts[1:]:
            merged = merged.combine_first(p)
        series_list[code] = merged.sort_index()

    df = pd.DataFrame(series_list)
    df.index.name = "date"
    return code_to_name, df


def _merge_six(
    paths: Dict[str, Path],
) -> Tuple[Dict[str, str], Dict[str, Dict[str, Dict[str, Any]]]]:
    """
    返回 (code->name, code -> date_str -> {open,high,low,close,amount,scale})。
    """
    key_map = {
        "open": paths["open"],
        "high": paths["high"],
        "low": paths["low"],
        "close": paths["close"],
        "scale": paths["scale"],
        "amount": paths["amount"],
    }
    names: Dict[str, str] = {}
    merged: DefaultDict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

    # 名称优先采用「收盘价」表中的简称
    close_names, _ = _parse_wide_sheet(paths["close"])
    names.update(close_names)

    field_frames: Dict[str, pd.DataFrame] = {}
    for field, pth in key_map.items():
        cn, df = _parse_wide_sheet(pth)
        for c, n in cn.items():
            if c not in names and n:
                names[c] = n
        field_frames[field] = df

    all_codes: Set[str] = set()
    for df in field_frames.values():
        all_codes.update(df.columns.astype(str))

    for code in sorted(all_codes):
        per_date: Dict[str, Dict[str, Any]] = {}
        for field, df in field_frames.items():
            if code not in df.columns:
                continue
            s = df[code].dropna()
            for idx, val in s.items():
                ds = pd.Timestamp(idx).strftime("%Y-%m-%d")
                if ds not in per_date:
                    per_date[ds] = {}
                try:
                    fv = float(val)
                except (TypeError, ValueError):
                    continue
                per_date[ds][field] = fv
        if per_date:
            merged[code] = per_date

    return names, dict(merged)


def _build_price_rows_for_code(
    code: str,
    date_to_fields: Dict[str, Dict[str, Any]],
    trade_days: Optional[Set[str]],
) -> List[dict]:
    rows: List[dict] = []
    for ds in sorted(date_to_fields.keys()):
        if trade_days is not None and ds not in trade_days:
            continue
        f = date_to_fields[ds]
        close = f.get("close")
        if close is None or close <= 0:
            continue
        row: Dict[str, Any] = {"date": ds, "close": float(close)}
        for k in ("open", "high", "low"):
            v = f.get(k)
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                row[k] = float(v)
        for k in ("amount", "scale"):
            v = f.get(k)
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                row[k] = float(v)
        rows.append(row)
    return rows


def _float_or_null(v: Any) -> Any:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _collect_flat_price_rows(
    merged: Dict[str, Dict[str, Dict[str, Any]]],
    trade_days: Optional[Set[str]],
) -> List[Dict[str, Any]]:
    """拉平为带 asset_code 的行列表（去重前）。"""
    flat: List[Dict[str, Any]] = []
    for code in sorted(merged.keys()):
        for row in _build_price_rows_for_code(code, merged[code], trade_days):
            flat.append(
                {
                    "asset_code": code,
                    "date": row["date"],
                    "open": _float_or_null(row.get("open")),
                    "high": _float_or_null(row.get("high")),
                    "low": _float_or_null(row.get("low")),
                    "close": float(row["close"]),
                    "volume": None,
                    "amount": _float_or_null(row.get("amount")),
                    "scale": _float_or_null(row.get("scale")),
                }
            )
    return flat


def _dedupe_price_rows(flat: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 (asset_code, date) 去重；同键多行合并非空字段（收盘价以最后一条非空为准）。"""
    buckets: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
    for r in flat:
        key = (r["asset_code"], r["date"])
        if key not in buckets:
            buckets[key] = {**r}
            order.append(key)
            continue
        b = buckets[key]
        for fld in ("open", "high", "low", "amount", "scale"):
            v = r.get(fld)
            if v is not None:
                b[fld] = v
        if r.get("close") is not None and float(r["close"]) > 0:
            b["close"] = float(r["close"])
    return [buckets[k] for k in order]


def _price_doc_native(r: Dict[str, Any], oid: Optional[ObjectId] = None) -> OrderedDict:
    """与 ``asset_allocation.asset_prices.json`` 样例一致的字段顺序；``_id`` 为 BSON ObjectId。"""
    oid = oid or ObjectId()
    return OrderedDict(
        [
            ("_id", oid),
            ("date", r["date"]),
            ("asset_code", r["asset_code"]),
            ("amount", r.get("amount")),
            ("close", float(r["close"])),
            ("high", r.get("high")),
            ("low", r.get("low")),
            ("open", r.get("open")),
            ("volume", r.get("volume")),
            ("scale", r.get("scale")),
        ]
    )


def _resolve_asset_name(code: str, names: Dict[str, str]) -> str:
    base = (names.get(code) or "").strip() or code
    return base


def _build_asset_docs_native(
    codes: List[str],
    names: Dict[str, str],
    mongo_uri: Optional[str],
    db_name: Optional[str],
) -> List[OrderedDict]:
    """
    与 ``asset_allocation.assets.json`` 样例一致的字段；
    ETF 使用 ``asset_type`` = ``指数类``（与同仓库导出样例中 159915.SZ 一致）。
    """
    from pymongo import MongoClient

    now = datetime.now(timezone.utc)
    client = None
    db = None
    if mongo_uri and db_name:
        client = MongoClient(mongo_uri)
        db = client[db_name]
    out: List[OrderedDict] = []
    for code in codes:
        base_name = _resolve_asset_name(code, names)
        name = base_name
        existing = db["assets"].find_one({"code": code}) if db is not None else None
        if db is not None:
            other = db["assets"].find_one({"name": name, "code": {"$ne": code}})
            if other:
                name = f"{base_name} ({code})"
        oid = existing["_id"] if existing else ObjectId()
        created = existing.get("created_at") if existing else now
        if created is None:
            created = now
        doc = OrderedDict(
            [
                ("_id", oid),
                ("code", code),
                ("name", name),
                ("asset_type", "指数类"),
                ("exchange", ""),
                ("description", ""),
                ("is_active", True if not existing else existing.get("is_active", True)),
                ("rollover_days", None),
                ("rollover_threshold", None),
                ("rollover_window_p", None),
                ("rollover_window_q", None),
                (
                    "substitute_code",
                    (existing.get("substitute_code") or "")
                    if existing
                    else "",
                ),
                (
                    "switch_date",
                    (existing.get("switch_date") or "")
                    if existing
                    else "",
                ),
                ("created_at", created),
                ("updated_at", now),
            ]
        )
        out.append(doc)
    if client is not None:
        client.close()
    return out


def _write_json_array_extended(path: Path, docs: List[Any]) -> None:
    """
    写入 JSON 数组，Extended JSON（``$oid`` / ``$date``），缩进与仓库内
    ``data/imports/asset_allocation.asset_prices.json`` 样例一致。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    opts = RELAXED_JSON_OPTIONS
    with path.open("w", encoding="utf-8") as fp:
        fp.write(bson_dumps(docs, json_options=opts, indent=2))
        fp.write("\n")


def _import_pymongo(
    mongo_uri: str,
    db_name: str,
    price_docs: List[OrderedDict],
    asset_docs: List[OrderedDict],
    asset_codes: List[str],
) -> None:
    from pymongo import MongoClient

    client = MongoClient(mongo_uri)
    db = client[db_name]
    coll_p = db["asset_prices"]
    coll_a = db["assets"]

    dr = coll_p.delete_many({"asset_code": {"$in": asset_codes}})
    print(f"asset_prices 已删除（涉及代码）: {dr.deleted_count} 条")

    batch = 5000
    ins = 0
    for i in range(0, len(price_docs), batch):
        chunk = [dict(x) for x in price_docs[i : i + batch]]
        if chunk:
            coll_p.insert_many(chunk)
            ins += len(chunk)
            print(f"  asset_prices 已插入: {ins}/{len(price_docs)}")

    for ad in asset_docs:
        d = dict(ad)
        coll_a.replace_one({"code": d["code"]}, d, upsert=True)
    print(f"assets 已 upsert: {len(asset_docs)} 条（按 code）")
    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="六宽表合并 → Extended JSON 数组 + MongoDB")
    parser.add_argument(
        "--excel-dir",
        type=str,
        default=str(Path.home() / "Downloads"),
        help="六个 xlsx 所在目录",
    )
    parser.add_argument(
        "--mongo-uri",
        type=str,
        default="mongodb://localhost:27017",
        help="MongoDB URI（读 trade_dates、写 asset_prices / assets）",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="asset_allocation",
        help="数据库名",
    )
    parser.add_argument(
        "--out-prices-json",
        type=str,
        default=str(project_root / "data" / "imports" / "asset_allocation.asset_prices.json"),
        help="行情导出路径（JSON 数组 + Extended JSON）",
    )
    parser.add_argument(
        "--out-assets-json",
        type=str,
        default=str(project_root / "data" / "asset_allocation.assets.json"),
        help="资产导出路径（JSON 数组 + Extended JSON）",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="只写两个 JSON 文件，不连库写入（仍可用 --mongo-uri 解析名称冲突与读交易日历）",
    )
    parser.add_argument(
        "--write-mongo",
        action="store_true",
        help="写入 Mongo：先删本次涉及代码在 asset_prices 中的文档，再插入；assets 按 code upsert",
    )
    parser.add_argument(
        "--filter-trade-days-only",
        action="store_true",
        help="仅导出/导入系统交易日历内的日期（默认关闭：自然日全量）",
    )
    args = parser.parse_args()
    excel_dir = Path(args.excel_dir)
    names_default = {
        "open": "开盘价.xlsx",
        "high": "最高点.xlsx",
        "low": "最低价.xlsx",
        "close": "收盘价.xlsx",
        "scale": "规模.xlsx",
        "amount": "成交额.xlsx",
    }
    paths = {k: excel_dir / v for k, v in names_default.items()}
    for k, p in paths.items():
        if not p.is_file():
            print(f"错误: 找不到文件 [{k}] {p}")
            sys.exit(1)

    mongo_uri = args.mongo_uri.strip() or None
    db_name = (args.db or "").strip() or None

    trade_days: Optional[Set[str]] = None
    if args.filter_trade_days_only:
        trade_days = _read_trade_date_set_sync(mongo_uri, db_name)
        if trade_days:
            print(f"已加载交易日历: {len(trade_days)} 天（--filter-trade-days-only：仅导出/导入历内日期）")
        else:
            print("警告: --filter-trade-days-only 已指定但未加载到交易日历，将按 Excel 全部日期写入")
    else:
        print("自然日全量：不按交易日历过滤导入/导出（前端 K 线按交易日历展示）")

    print("合并 Excel …")
    names, merged = _merge_six(paths)
    codes = sorted(merged.keys())
    print(f"资产代码数: {len(merged)}，名称表条目: {len(names)}")

    flat = _collect_flat_price_rows(merged, trade_days)
    flat = _dedupe_price_rows(flat)
    print(f"行情行（去重后）: {len(flat)}")

    price_docs = [_price_doc_native(r) for r in flat]
    asset_docs = _build_asset_docs_native(codes, names, mongo_uri, db_name)

    prices_path = Path(args.out_prices_json)
    assets_path = Path(args.out_assets_json)
    _write_json_array_extended(prices_path, price_docs)
    _write_json_array_extended(assets_path, asset_docs)
    print(f"已写入: {prices_path}")
    print(f"已写入: {assets_path}")

    if args.write_mongo and not args.export_only:
        _import_pymongo(mongo_uri, db_name, price_docs, asset_docs, codes)
        print("Mongo 导入完成。")
    elif args.write_mongo and args.export_only:
        print("提示: 已指定 --export-only，已跳过写库。")
    else:
        print("未写 Mongo（加 --write-mongo 且不指定 --export-only）。")

    print()
    print("mongoimport 示例（覆盖前请自行备份）：")
    print(
        f'  mongoimport --uri="{mongo_uri}" --db={db_name} '
        f'--collection=asset_prices --file="{prices_path}" --jsonArray'
    )
    print(
        f'  mongoimport --uri="{mongo_uri}" --db={db_name} '
        f'--collection=assets --file="{assets_path}" --jsonArray --mode=merge'
    )
    print("说明: asset_prices 若用 mongoimport 全量插入，请先自行删除本批 asset_code 或整表，避免 _id 重复。")


if __name__ == "__main__":
    main()
