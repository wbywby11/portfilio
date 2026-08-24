# -*- coding: utf-8 -*-
"""
扩展 asset_prices 和 option_market_data 到最新交易日期
将最新一天数据复制到后续交易日（加微小随机波动模拟行情）
"""
from __future__ import annotations
import sys, random
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"
TARGET_DATE = "2026-06-16"  # 目标日期


def get_trade_dates(db) -> list[str]:
    """从 trade_dates 集合获取交易日列表"""
    docs = list(db["trade_dates"].find().sort("trade_date", 1))
    if docs:
        dates = []
        for d in docs:
            td = d.get("trade_date", "")
            if isinstance(td, datetime):
                td = td.strftime("%Y-%m-%d")
            dates.append(str(td)[:10])
        return dates
    # fallback: 从 asset_prices 中提取已有日期
    return sorted(db["asset_prices"].distinct("date"))


def extend_asset_prices(db, trade_dates: list[str]):
    """扩展 asset_prices 到目标日期"""
    col = db["asset_prices"]

    # 找最新日期
    latest_date = col.find_one(sort=[("date", -1)])
    if not latest_date:
        print("[SKIP] asset_prices 为空")
        return
    last_date = latest_date["date"]
    print(f"[INFO] asset_prices 最新日期: {last_date}")

    # 找需要填充的日期
    future_dates = [d for d in trade_dates if d > last_date and d <= TARGET_DATE]
    if not future_dates:
        # 如果交易日历里没有更新的未来日期，就用工作日生成
        last_dt = datetime.strptime(last_date, "%Y-%m-%d")
        target_dt = datetime.strptime(TARGET_DATE, "%Y-%m-%d")
        future_dates = []
        current = last_dt + timedelta(days=1)
        while current <= target_dt:
            if current.weekday() < 5:  # 工作日
                future_dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

    if not future_dates:
        print("[OK] asset_prices 已是最新")
        return

    print(f"[INFO] 需填充 {len(future_dates)} 个交易日: {future_dates[0]} ~ {future_dates[-1]}")

    # 获取最新一天所有资产数据
    last_docs = list(col.find({"date": last_date}))
    if not last_docs:
        print("[SKIP] 无资产数据")
        return

    inserted = 0
    for fd in future_dates:
        for doc in last_docs:
            # 加随机波动 (-1% ~ +1%)
            drift = 1 + random.uniform(-0.01, 0.01)
            new_doc = {
                "date": fd,
                "asset_code": doc.get("asset_code", doc.get("thsc_code", "")),
                "close": round((doc.get("close") or 0) * drift, 6),
                "open": round((doc.get("open") or doc.get("close") or 0) * drift, 6),
                "high": round((doc.get("high") or doc.get("close") or 0) * drift, 6),
                "low": round((doc.get("low") or doc.get("close") or 0) * drift, 6),
                "amount": doc.get("amount", 0),
                "volume": doc.get("volume", 0),
                "scale": doc.get("scale"),
            }
            if doc.get("thsc_code"):
                new_doc["thsc_code"] = doc["thsc_code"]
            col.update_one(
                {"date": fd, "asset_code": new_doc["asset_code"]},
                {"$set": new_doc},
                upsert=True,
            )
            inserted += 1

    print(f"[OK] asset_prices 写入 {inserted} 条 (覆盖到 {future_dates[-1]})")


def extend_option_market_data(db):
    """扩展 option_market_data 到目标日期"""
    col = db["option_market_data"]

    latest = col.find_one(sort=[("date", -1)])
    if not latest:
        print("[SKIP] option_market_data 为空")
        return
    last_date = latest["date"]
    print(f"[INFO] option_market_data 最新日期: {last_date}")

    future_dates = []
    last_dt = datetime.strptime(last_date, "%Y-%m-%d")
    target_dt = datetime.strptime(TARGET_DATE, "%Y-%m-%d")
    current = last_dt + timedelta(days=1)
    while current <= target_dt:
        if current.weekday() < 5:
            future_dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    if not future_dates:
        print("[OK] option_market_data 已是最新")
        return

    last_docs = list(col.find({"date": last_date}))
    inserted = 0
    for fd in future_dates:
        for doc in last_docs:
            new_doc = dict(doc)
            new_doc.pop("_id", None)
            new_doc["date"] = fd
            new_doc["created_at"] = datetime.now()
            # 微调价格
            for field in ["spot_price", "close", "last_price"]:
                if field in new_doc and isinstance(new_doc[field], (int, float)):
                    drift = 1 + random.uniform(-0.005, 0.005)
                    new_doc[field] = round(new_doc[field] * drift, 4)
            col.update_one(
                {"date": fd, "underlying": new_doc.get("underlying", "")},
                {"$set": new_doc},
                upsert=True,
            )
            inserted += 1

    print(f"[OK] option_market_data 写入 {inserted} 条 (覆盖到 {future_dates[-1]})")


def extend_fx_rates(db):
    """扩展 fx_rates 到目标日期"""
    col = db["fx_rates"]

    latest = col.find_one(sort=[("date", -1)])
    if not latest:
        print("[SKIP] fx_rates 为空")
        return
    last_date = latest["date"]
    print(f"[INFO] fx_rates 最新日期: {last_date}")

    last_dt = datetime.strptime(str(last_date)[:10], "%Y-%m-%d")
    target_dt = datetime.strptime(TARGET_DATE, "%Y-%m-%d")
    future_dates = []
    current = last_dt + timedelta(days=1)
    while current <= target_dt:
        if current.weekday() < 5:
            future_dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    if not future_dates:
        print("[OK] fx_rates 已是最新")
        return

    last_doc = dict(latest)
    last_doc.pop("_id", None)
    inserted = 0
    for fd in future_dates:
        new_doc = dict(last_doc)
        new_doc["date"] = fd
        col.update_one({"date": fd}, {"$set": new_doc}, upsert=True)
        inserted += 1

    print(f"[OK] fx_rates 写入 {inserted} 条 (覆盖到 {future_dates[-1]})")


if __name__ == "__main__":
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    trade_dates = get_trade_dates(db)
    print(f"[INFO] 交易日历共 {len(trade_dates)} 天, 最新: {trade_dates[-1] if trade_dates else 'N/A'}")

    extend_asset_prices(db, trade_dates)
    extend_option_market_data(db)
    extend_fx_rates(db)

    print("\n[DONE] 数据扩展完成")
    client.close()
