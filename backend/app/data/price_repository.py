"""行情读收口仓储（asset_prices 集合只读）.

应用层架构治理（P7）：行情集合的读端统一经本仓储，
api/services/portfolio/backtesting 中禁止对 asset_prices 的裸
find/aggregate（守卫见 tests/test_architecture_guard.py::TestPriceReadFunnel）。
写端（行情导入链路）仍由 app/services/price_importer.py 直持集合。
"""
from datetime import datetime
from typing import Dict, List, Optional

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

    async def get_price_dataframe(
        self,
        asset_codes: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        获取多个资产的价格DataFrame

        Returns:
            DataFrame with columns as asset_codes and index as dates
        """
        all_data = {}

        for code in asset_codes:
            prices = await self.get_price_docs(code, start_date, end_date)
            if prices:
                df = pd.DataFrame([{
                    'date': p.date,  # 现在是字符串格式 YYYY-MM-DD
                    'close': p.close
                } for p in prices])
                # 转换为 datetime 索引
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                all_data[code] = df['close']

        if not all_data:
            return pd.DataFrame()

        # 合并所有资产数据
        result_df = pd.DataFrame(all_data)
        return result_df
