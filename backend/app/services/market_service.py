"""
行情查询服务

提供统一的行情数据查询接口，供回测引擎和策略使用
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import pandas as pd

from app.services.asset_service import AssetService


class MarketService:
    """行情查询服务
    
    封装资产价格数据的查询功能，为回测引擎提供统一的数据接口。
    
    核心功能：
    1. 获取单个资产的价格序列
    2. 获取多个资产的价格矩阵（DataFrame格式）
    3. 支持日期范围查询
    4. 支持历史数据预加载（避免前视偏差）
    """
    
    def __init__(self, asset_service: Optional[AssetService] = None):
        """初始化行情查询服务
        
        Args:
            asset_service: 资产服务实例（可选，默认创建新实例）
        """
        self.asset_service = asset_service or AssetService()
    
    async def get_price_series(
        self,
        thscode: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.Series:
        """获取单个资产的价格序列
        
        Args:
            thscode: 资产代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            以日期为索引，收盘价为值的 Series
        """
        prices = await self.asset_service.get_asset_prices(
            asset_code=thscode,
            start_date=start_date,
            end_date=end_date
        )
        
        if not prices:
            return pd.Series(dtype=float)
        
        # 构建 Series
        data = {p.date: p.close for p in prices}
        series = pd.Series(data)
        series.index = pd.to_datetime(series.index)
        series = series.sort_index()
        
        return series
    
    async def get_price_matrix(
        self,
        thscodes: List[str],
        start_date: str,  # 格式：YYYYMMDD
        end_date: str,    # 格式：YYYYMMDD
    ) -> pd.DataFrame:
        """获取多个资产的价格矩阵
        
        Args:
            thscodes: 资产代码列表
            start_date: 开始日期（格式：YYYYMMDD）
            end_date: 结束日期（格式：YYYYMMDD）
        
        Returns:
            DataFrame，index 为日期，columns 为资产代码，values 为收盘价
        """
        # 转换日期格式
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        
        # 使用 AssetService 的现有方法
        price_df = await self.asset_service.get_price_dataframe(
            asset_codes=thscodes,
            start_date=start_dt,
            end_date=end_dt
        )
        
        return price_df
    
    async def get_price_matrix_with_lookback(
        self,
        thscodes: List[str],
        start_date: str,  # 格式：YYYYMMDD
        end_date: str,    # 格式：YYYYMMDD
        lookback_days: int = 500,  # 预加载历史数据天数
    ) -> pd.DataFrame:
        """获取价格矩阵（含历史预加载）
        
        为避免前视偏差，在实际回测开始日期之前预加载足够的历史数据。
        
        Args:
            thscodes: 资产代码列表
            start_date: 回测开始日期（格式：YYYYMMDD）
            end_date: 回测结束日期（格式：YYYYMMDD）
            lookback_days: 预加载的历史数据天数（默认500天）
        
        Returns:
            DataFrame，包含从 (start_date - lookback_days) 到 end_date 的价格数据
        """
        # 计算扩展的开始日期
        start_dt = pd.to_datetime(start_date)
        extended_start_dt = start_dt - pd.Timedelta(days=lookback_days)
        extended_start_date = extended_start_dt.strftime('%Y%m%d')
        
        # 获取价格矩阵
        return await self.get_price_matrix(
            thscodes=thscodes,
            start_date=extended_start_date,
            end_date=end_date
        )
    
    async def get_latest_price(
        self,
        thscode: str,
        as_of_date: Optional[datetime] = None,
    ) -> Optional[float]:
        """获取资产的最新价格
        
        Args:
            thscode: 资产代码
            as_of_date: 截至日期（可选，默认为最新）
        
        Returns:
            最新收盘价，如果没有数据则返回 None
        """
        # 如果没有指定日期，获取最近的数据
        if as_of_date is None:
            as_of_date = datetime.now()
        
        # 获取最近的价格数据
        prices = await self.asset_service.get_asset_prices(
            asset_code=thscode,
            start_date=None,
            end_date=as_of_date
        )
        
        if not prices:
            return None
        
        # 返回最后一条记录的收盘价
        return prices[-1].close
    
    async def get_latest_prices(
        self,
        thscodes: List[str],
        as_of_date: Optional[datetime] = None,
    ) -> dict[str, float]:
        """批量获取多个资产的最新价格
        
        Args:
            thscodes: 资产代码列表
            as_of_date: 截至日期（可选，默认为最新）
        
        Returns:
            字典，键为资产代码，值为最新收盘价
        """
        result = {}
        
        for thscode in thscodes:
            price = await self.get_latest_price(thscode, as_of_date)
            if price is not None:
                result[thscode] = price
        
        return result
