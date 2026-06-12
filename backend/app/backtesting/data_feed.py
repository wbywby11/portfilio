from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Tuple

import pandas as pd

from app.services.market_service import MarketService
from app.backtesting.config import BacktestConfig
from app.backtesting.types import Bar

# 单资产单日涨跌幅超过此阈值视为异常，用前一日价格填充，避免异常导致净值/年化收益/波动率失真
_MAX_DAILY_PRICE_CHANGE = 0.5  # 50%


def sanitize_prices(prices: pd.DataFrame, max_daily_pct_change: float = _MAX_DAILY_PRICE_CHANGE) -> pd.DataFrame:
    """对价格矩阵做异常填充：nan/inf 用前向/后向填充；单日涨跌幅超过阈值时用前一日价格填充。返回新 DataFrame。"""
    if prices is None or prices.empty:
        return prices
    out = prices.copy()
    # 先按列处理 nan/inf
    out = out.replace([float("inf"), float("-inf")], float("nan"))
    out = out.ffill().bfill()
    if out.isna().all().all():
        return out
    # 按列：单日涨跌幅超过阈值则用前一日价格填充
    for col in out.columns:
        prev = out[col].shift(1)
        pct = out[col].pct_change()
        abnormal = (prev > 1e-12) & (pct.abs() > max_daily_pct_change)
        if abnormal.any():
            out.loc[abnormal, col] = prev[abnormal]
    out = out.ffill().bfill()
    return out


@dataclass
class DataFeed:
    """回测使用的行情数据提供器.

    内部保存一份已经从 data 模块拉取好的收盘价矩阵:
    - index: time (DatetimeIndex)
    - columns: thscode
    - values: close
    """

    prices: pd.DataFrame
    config: BacktestConfig

    @classmethod
    async def from_market_service(
        cls,
        market_service: MarketService,
        config: BacktestConfig,
        lookback_days: int = 252,  # 默认252天（约1年交易日），预留足够的历史数据缓冲
    ) -> "DataFeed":
        """从 MarketService 构造 DataFeed.

        为了避免前视偏差，需要在 start_date 之前预留足够的历史数据。
        lookback_days参数为数据预加载缓冲，默认500天确保覆盖各类策略需求。
        """
        prices = await market_service.get_price_matrix_with_lookback(
            thscodes=config.thscodes,
            start_date=config.start_date,
            end_date=config.end_date,
            lookback_days=lookback_days,
        )
        prices = sanitize_prices(prices)
        return cls(prices=prices, config=config)

    def iter_bars(self) -> Iterator[Tuple[pd.Timestamp, Bar]]:
        """按时间顺序逐行输出 Bar 数据，为回测引擎驱动时间提供基础."""
        for time, row in self.prices.iterrows():
            # 确保 close 是字典格式
            # row 应该是 pandas Series，to_dict() 应该返回字典
            try:
                close_dict = row.to_dict()
            except Exception as e:
                # 如果 to_dict() 失败，手动构建字典
                close_dict = {col: row[col] for col in self.prices.columns}
            
            # 防御性检查：确保返回的是字典
            if not isinstance(close_dict, dict):
                # 如果 close_dict 不是字典，尝试从 row 构建
                if isinstance(row, pd.Series):
                    close_dict = row.to_dict()
                else:
                    # 如果 row 也不是 Series，尝试从 DataFrame 的列构建
                    close_dict = {col: getattr(row, col, None) for col in self.prices.columns}
            
            # 确保所有值都是浮点数，过滤掉 NaN 和无效值
            close_dict = {
                code: float(price) 
                for code, price in close_dict.items() 
                if pd.notna(price) and isinstance(price, (int, float, str))
            }
            
            # 再次检查：确保 close_dict 是字典且不为空
            if not isinstance(close_dict, dict):
                raise ValueError(
                    f"无法将价格数据转换为字典格式。"
                    f"时间: {time}, 数据类型: {type(close_dict)}, 值: {close_dict}"
                )
            
            yield time, Bar(time=time, close=close_dict)

    def get_history_window(
        self,
        current_time: pd.Timestamp,
    ) -> pd.DataFrame:
        """返回当前时点之前的全部历史数据,用于策略计算.

        注意: 只包含 current_time 之前的数据（不含 current_time），避免前视偏差。
        即在 T 日调仓时，只能使用 T-1 及之前的数据。
        
        lookback截断由策略内部根据自身参数处理。
        """
        # 返回 current_time 之前的所有数据
        window = self.prices.loc[self.prices.index < current_time]
        return window
