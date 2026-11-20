"""行情读收口仓储（asset_prices 集合只读）.

应用层架构治理（P7）：行情集合的读端统一经本仓储，
api/services/portfolio/backtesting 中禁止对 asset_prices 的裸
find/aggregate（守卫见 tests/test_architecture_guard.py::TestPriceReadFunnel）。
写端（行情导入链路）仍由 app/services/price_importer.py 直持集合。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from app.config.database import Database
from app.models.asset import AssetPrice


class PriceRepository:
    """asset_prices 集合只读仓储.

    依赖注入 db（默认 Database.get_database()），只提供查询，
    不做任何写入/删除。
    """

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
            from app.config.collections import COL_ASSET_PRICES
            self._collection = self.db[COL_ASSET_PRICES]
        return self._collection

    async def get_price_docs(
        self,
        asset_code: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[AssetPrice]:
        """
        获取资产价格数据

        Args:
            asset_code: 资产代码
            start_date: 开始日期
            end_date: 结束日期
        """
        query = {"asset_code": asset_code}
        if start_date or end_date:
            query["date"] = {}
            if start_date:
                # 转换为 YYYY-MM-DD 字符串进行比较
                query["date"]["$gte"] = start_date.strftime('%Y-%m-%d')
            if end_date:
                query["date"]["$lte"] = end_date.strftime('%Y-%m-%d')

        cursor = self.collection.find(query).sort("date", 1)
        prices = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            prices.append(AssetPrice(**doc))

        return prices

    async def get_latest_price_date(self, asset_code: str) -> Optional[str]:
        """
        获取资产的最新价格数据日期

        Returns:
            最新日期字符串（YYYY-MM-DD），如果没有数据则返回 None
        """
        cursor = self.collection.find(
            {"asset_code": asset_code}
        ).sort("date", -1).limit(1)

        async for doc in cursor:
            return doc.get("date")  # 已经是 YYYY-MM-DD 字符串格式
        return None

    async def get_latest_price_dates(self, asset_codes: List[str]) -> Dict[str, Optional[str]]:
        """
        批量获取多个资产的最新价格数据日期

        Returns:
            字典：{asset_code: latest_date 或 None}
        """
        result = {}
        for code in asset_codes:
            result[code] = await self.get_latest_price_date(code)
        return result

    async def get_latest_closes(
        self, asset_codes: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """批量取各资产最近一条收盘价及对应日期（一次聚合，不逐资产往返）。

        按 ``asset_code`` 分组各取最新，不用全局最新日期过滤：停牌或行情
        陈旧的资产仍能给出自己的最后价格，由调用方把 ``price_date`` 标出来，
        避免用一个统一日期掩盖个别资产的行情缺口。

        Returns:
            {asset_code: {"price": float, "price_date": "YYYY-MM-DD"}}；
            无行情的资产不出现在结果里（调用方按缺失处理，不用 0 兜底）。
        """
        codes = [str(code).strip() for code in (asset_codes or []) if str(code or "").strip()]
        if not codes:
            return {}

        rows = await self.collection.aggregate([
            {"$match": {"asset_code": {"$in": codes}}},
            {"$sort": {"asset_code": 1, "date": -1}},
            {"$group": {
                "_id": "$asset_code",
                "close": {"$first": "$close"},
                "date": {"$first": "$date"},
            }},
        ]).to_list(length=None)

        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            close = row.get("close")
            if close is None:
                continue
            out[str(row.get("_id"))] = {
                "price": float(close),
                "price_date": str(row.get("date") or "")[:10],
            }
        return out

    async def get_price_dataframe(
        self,
        asset_codes: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """获取多个资产的价格DataFrame（一次查询 + pivot，替代逐资产往返）.

        与逐资产版本保持同一输出口径：index 为 ``DatetimeIndex``（日期升序，
        并集日历），columns 按入参 ``asset_codes`` 顺序（仅含有数据的资产），
        缺日为 NaN。

        Args:
            asset_codes: 资产代码列表，决定列顺序
            start_date: 起始日期（含）
            end_date: 截止日期（含）

        Returns:
            价格矩阵；无任何数据时返回空 DataFrame。

        Raises:
            ValueError: close 非数值/非正，或同一 ``(asset_code, date)`` 重复，
                宁可显式失败也不让脏数据静默进入回测。
        """
        codes = [str(code) for code in asset_codes if code is not None]
        if not codes:
            return pd.DataFrame()

        query: Dict = {"asset_code": {"$in": codes}}
        date_filter: Dict = {}
        if start_date:
            date_filter["$gte"] = start_date.strftime('%Y-%m-%d')
        if end_date:
            date_filter["$lte"] = end_date.strftime('%Y-%m-%d')
        if date_filter:
            query["date"] = date_filter

        cursor = self.collection.find(
            query,
            {"_id": 0, "asset_code": 1, "date": 1, "close": 1},
        )
        records = await cursor.to_list(length=None)
        if not records:
            return pd.DataFrame()

        frame = pd.DataFrame(records)
        duplicated = frame.duplicated(subset=["asset_code", "date"], keep=False)
        if duplicated.any():
            bad = frame.loc[duplicated, ["asset_code", "date"]].head(5).to_dict("records")
            raise ValueError(f"asset_prices 存在重复的 (asset_code, date)：{bad}")

        close = pd.to_numeric(frame["close"], errors="coerce").astype(float)
        invalid = ~close.notna() | (close <= 0)
        if invalid.any():
            bad = frame.loc[invalid, ["asset_code", "date", "close"]].head(5).to_dict("records")
            raise ValueError(f"asset_prices 存在非数值或非正 close：{bad}")
        frame["close"] = close
        frame["date"] = pd.to_datetime(frame["date"])

        pivot = frame.pivot(index="date", columns="asset_code", values="close")
        ordered = [code for code in codes if code in pivot.columns]
        result_df = pivot.reindex(columns=ordered).sort_index()
        result_df.columns.name = None
        return result_df
