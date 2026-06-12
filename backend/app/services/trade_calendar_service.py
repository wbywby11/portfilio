"""
交易日历服务 - 管理 MongoDB trade_dates 集合

集合存储格式：
    { "date": datetime(...) }
其中 date 字段为 Python datetime 对象（ISODate），并非字符串。
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import pandas as pd
from loguru import logger

from app.config.database import Database

# 兼容多种日期列名（与 data_import_tool.TRADE_DATES_COLUMN_MAPPING 保持一致）
_DATE_COLUMN_MAPPING = {
    "交易日": "date", "交易日期": "date", "交易日期*": "date",
    "trade_dates": "date", "trade_date": "date", "TradeDate": "date",
    "TRADE_DATE": "date", "TRADE_DATES": "date",
    "日期": "date", "日期*": "date", "Date": "date", "DATE": "date", "date": "date",
}


class TradeCalendarService:
    """交易日历服务"""

    def __init__(self, db=None):
        self._db = db
        self._collection = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.db["trade_dates"]
        return self._collection

    # ───────────────────────── 工具方法 ─────────────────────────

    @staticmethod
    def _to_datetime(date_str: str) -> datetime:
        """将 YYYY-MM-DD 字符串规范化为 datetime（去掉时分秒）"""
        ts = pd.to_datetime(date_str, errors="coerce")
        if pd.isna(ts):
            raise ValueError(f"无效日期: {date_str}")
        return ts.to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _date_to_str(val: Any) -> Optional[str]:
        """将存储值（datetime / str / Timestamp）转换为 YYYY-MM-DD"""
        if val is None:
            return None
        if hasattr(val, "strftime"):
            return val.strftime("%Y-%m-%d")
        try:
            return str(val)[:10]
        except Exception:
            return None

    async def _existing_date_strings(self) -> Set[str]:
        """读取库中已存在的交易日期字符串集合（YYYY-MM-DD）"""
        distinct_dates = await self.collection.distinct("date")
        result: Set[str] = set()
        for d in distinct_dates:
            s = self._date_to_str(d)
            if s:
                result.add(s)
        return result

    # ───────────────────────── 公共接口 ─────────────────────────

    async def get_stats(self) -> Dict[str, Any]:
        """获取交易日历统计信息"""
        cursor = self.collection.find({}, {"date": 1, "_id": 0}).sort("date", 1)
        date_strs: List[str] = []
        last_updated: Optional[str] = None
        async for doc in cursor:
            s = self._date_to_str(doc.get("date"))
            if s:
                date_strs.append(s)

        if not date_strs:
            return {
                "count": 0,
                "start_date": None,
                "end_date": None,
                "this_year_count": 0,
                "last_updated": None,
            }

        current_year = datetime.now().year
        this_year_prefix = f"{current_year}-"
        this_year_count = sum(1 for s in date_strs if s.startswith(this_year_prefix))
        last_updated = date_strs[-1]

        return {
            "count": len(date_strs),
            "start_date": date_strs[0],
            "end_date": date_strs[-1],
            "this_year_count": this_year_count,
            "last_updated": last_updated,
        }

    async def get_dates_by_year(self, year: Optional[int] = None) -> List[str]:
        """获取交易日期列表，可按年份过滤"""
        query: Dict[str, Any] = {}
        if year is not None:
            start = datetime(year, 1, 1)
            end = datetime(year + 1, 1, 1)
            query["date"] = {"$gte": start, "$lt": end}

        cursor = self.collection.find(query, {"date": 1, "_id": 0}).sort("date", 1)
        result: List[str] = []
        async for doc in cursor:
            s = self._date_to_str(doc.get("date"))
            if s:
                result.append(s)
        return result

    async def import_from_excel(
        self, file_content: bytes, mode: str = "incremental"
    ) -> Dict[str, Any]:
        """
        从 Excel 字节流导入交易日历

        mode:
        - replace: 清空后全量导入
        - incremental: 仅新增不存在的日期
        """
        td_mode = "replace" if (mode or "").strip().lower() in ("replace", "overwrite") else "incremental"

        try:
            df = pd.read_excel(io.BytesIO(file_content))
        except Exception as e:
            raise ValueError(f"Excel 解析失败: {e}")

        if df is None or df.empty:
            raise ValueError("文件为空或无法解析出有效数据")

        # 列名标准化
        df.columns = df.columns.astype(str).str.strip()
        df.rename(
            columns={k: v for k, v in _DATE_COLUMN_MAPPING.items() if k in df.columns},
            inplace=True,
        )

        # 没有 date 列时使用第一列
        if "date" not in df.columns and len(df.columns) > 0:
            df.rename(columns={df.columns[0]: "date"}, inplace=True)

        if "date" not in df.columns:
            raise ValueError("文件缺少日期列，无法识别")

        df = df[["date"]].copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df.dropna(subset=["date"], inplace=True)
        df.drop_duplicates(subset=["date"], inplace=True)

        if df.empty:
            raise ValueError("文件无有效日期数据")

        total_in_file = len(df)
        file_dates_dt: List[datetime] = [
            ts.to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0)
            for ts in df["date"].tolist()
        ]
        file_date_strs: List[str] = [dt.strftime("%Y-%m-%d") for dt in file_dates_dt]

        inserted_count = 0
        skipped_count = 0

        if td_mode == "replace":
            await self.collection.delete_many({})
            docs = [{"date": dt} for dt in file_dates_dt]
            if docs:
                batch_size = 1000
                for i in range(0, len(docs), batch_size):
                    batch = docs[i:i + batch_size]
                    result = await self.collection.insert_many(batch, ordered=False)
                    inserted_count += len(result.inserted_ids)
        else:
            existing = await self._existing_date_strings()
            new_docs: List[Dict[str, Any]] = []
            for dt, ds in zip(file_dates_dt, file_date_strs):
                if ds in existing:
                    skipped_count += 1
                    continue
                new_docs.append({"date": dt})
                existing.add(ds)  # 防止文件内重复
            if new_docs:
                batch_size = 1000
                for i in range(0, len(new_docs), batch_size):
                    batch = new_docs[i:i + batch_size]
                    try:
                        result = await self.collection.insert_many(batch, ordered=False)
                        inserted_count += len(result.inserted_ids)
                    except Exception as e:
                        logger.warning(
                            "[TradeCalendarService] 批量插入失败：{}", e
                        )

        logger.info(
            "[TradeCalendarService] 导入完成 mode={} total={} inserted={} skipped={}",
            td_mode, total_in_file, inserted_count, skipped_count,
        )

        return {
            "mode": td_mode,
            "inserted_count": inserted_count,
            "skipped_count": skipped_count,
            "total_in_file": total_in_file,
            "date_range": (
                f"{min(file_date_strs)} ~ {max(file_date_strs)}"
                if file_date_strs else ""
            ),
        }

    async def add_dates(self, dates: List[str]) -> Dict[str, Any]:
        """手动批量添加交易日期"""
        if not dates:
            return {"inserted_count": 0, "skipped_count": 0}

        # 规范化 + 去重
        normalized: List[datetime] = []
        normalized_strs: List[str] = []
        seen_in_input: Set[str] = set()
        for d in dates:
            if d is None:
                continue
            s_raw = str(d).strip()
            if not s_raw:
                continue
            try:
                dt = self._to_datetime(s_raw)
            except ValueError:
                logger.warning("[TradeCalendarService] 跳过无效日期: {}", s_raw)
                continue
            ds = dt.strftime("%Y-%m-%d")
            if ds in seen_in_input:
                continue
            seen_in_input.add(ds)
            normalized.append(dt)
            normalized_strs.append(ds)

        if not normalized:
            return {"inserted_count": 0, "skipped_count": 0}

        existing = await self._existing_date_strings()
        new_docs: List[Dict[str, Any]] = []
        skipped_count = 0
        for dt, ds in zip(normalized, normalized_strs):
            if ds in existing:
                skipped_count += 1
                continue
            new_docs.append({"date": dt})

        inserted_count = 0
        if new_docs:
            result = await self.collection.insert_many(new_docs, ordered=False)
            inserted_count = len(result.inserted_ids)

        return {
            "inserted_count": inserted_count,
            "skipped_count": skipped_count,
        }

    async def delete_date(self, date_str: str) -> Dict[str, Any]:
        """按日期字符串删除交易日期"""
        try:
            dt = self._to_datetime(date_str)
        except ValueError as e:
            raise ValueError(str(e))

        result = await self.collection.delete_many({"date": dt})
        return {"deleted_count": int(result.deleted_count)}
