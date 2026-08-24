"""DataFeed：行情矩阵供给与清洗（计算内核层，模式无关）.

向引擎提供价格矩阵与价格日历（``data_feed.prices.index`` 即完整行情交易日），
含异常值清洗（sanitize_prices / strip_invalid_values）与技术列构建。
数据源可由 MarketService 或上游注入，引擎不感知来源。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.market_service import MarketService
from app.backtesting.config import BacktestConfig
from app.backtesting.types import Bar

# 单资产单日涨跌幅超过此阈值视为异常，用前一日价格填充，避免异常导致净值/年化收益/波动率失真
_MAX_DAILY_PRICE_CHANGE = 0.5  # 50%


async def build_specialized_data_feed(
    strategy_type: str,
    config: BacktestConfig,
    lookback_days: int = 500,
) -> "DataFeed":
    """为特殊策略类型构建专用 DataFeed。

    当 strategy_type 为 etf_discount 时调用，
    从 MongoDB 集合加载数据并构造 DataFeed。
    """
    from app.config.database import Database

    db = Database.get_database()

    if strategy_type == "etf_discount":
        # 从 etf_discount_market_data 集合加载 ETF 收盘价 + 贴水率 + 额外价格维度
        from app.config.collections import COL_ETF_DISCOUNT_MARKET_DATA
        collection = db[COL_ETF_DISCOUNT_MARKET_DATA]
        cursor = collection.find({}, {"_id": 0})
        docs = await cursor.to_list(length=None)
        if not docs:
            raise ValueError(
                "etf_discount_market_data 集合为空，无法运行 etf_discount 策略回测。"
                "请先导入 ETF 折溢价数据（字段结构见 app/models/etf_discount.py）。"
            )
        df = pd.DataFrame(docs)
        # 预期字段：date, code, close, discount_ratio, vwap, nav, ...
        if "date" not in df.columns:
            raise ValueError("etf_discount_market_data 缺少 date 字段")
        df["date"] = pd.to_datetime(df["date"])

        # 构建 close 宽表
        if "code" in df.columns and "close" in df.columns:
            close_df = df.pivot_table(index="date", columns="code", values="close", aggfunc="last")
        else:
            raise ValueError("etf_discount_market_data 缺少 code 或 close 字段")

        # 构建 discount_ratio 宽表（附加为 {code}_discount 列）
        if "discount_ratio" in df.columns:
            dr_df = df.pivot_table(index="date", columns="code", values="discount_ratio", aggfunc="last")
            dr_df.columns = [f"{c}_discount" for c in dr_df.columns]
            close_df = pd.concat([close_df, dr_df], axis=1)

        # 构建 vwap 宽表（额外价格维度，供 Bar.extra 消费）
        extra_prices: Dict[str, pd.DataFrame] = {}
        if "vwap" in df.columns:
            vwap_df = df.pivot_table(index="date", columns="code", values="vwap", aggfunc="last")
            extra_prices["vwap"] = vwap_df

        # 加载 GC001 回购利率数据（204001.SH 的 close 字段为年化百分比利率）
        gc001_mask = df["code"] == "204001.SH" if "code" in df.columns else pd.Series(False, index=df.index)
        if gc001_mask.any():
            gc001_df = df.loc[gc001_mask, ["date", "close"]].copy()
            gc001_df = gc001_df.rename(columns={"close": "204001.SH"})
            gc001_df = gc001_df.set_index("date")
            gc001_df.index = pd.to_datetime(gc001_df.index)
            extra_prices["gc001_rate"] = gc001_df

        # 构建技术指标附加列（bull_bear_ma / RSI / STD）
        tech_df = _build_tech_columns(df, close_df)
        if tech_df is not None:
            close_df = pd.concat([close_df, tech_df], axis=1)

        close_df = close_df.sort_index()
        if config.start_date:
            start = pd.Timestamp(config.start_date) - pd.Timedelta(days=int(lookback_days * 1.5))
            close_df = close_df.loc[close_df.index >= start]
            for key in extra_prices:
                extra_prices[key] = extra_prices[key].loc[extra_prices[key].index >= start]
        if config.end_date:
            end = pd.Timestamp(config.end_date)
            close_df = close_df.loc[close_df.index <= end]
            for key in extra_prices:
                extra_prices[key] = extra_prices[key].loc[extra_prices[key].index <= end]

        return DataFeed(prices=close_df, config=config, extra_prices=extra_prices)

    else:
        raise ValueError(f"不支持的特殊策略类型: {strategy_type}")


def strip_invalid_values(prices: pd.DataFrame) -> pd.DataFrame:
    """仅将 inf/-inf 置为 NaN，保留缺日 NaN（不做前向填充）。

    用于构建保真价格矩阵 strategy_prices：原型口径中品种缺日在并集日历上为 NaN，
    收益率/动量/波动率计算自然传播 NaN（缺日附近窗口失效），
    与 sanitize_prices 的 ffill 填平缺日语义不同。
    """
    if prices is None or prices.empty:
        return prices
    return prices.replace([float("inf"), float("-inf")], float("nan"))


def sanitize_prices(prices: pd.DataFrame, max_daily_pct_change: float = _MAX_DAILY_PRICE_CHANGE) -> pd.DataFrame:
    """对价格矩阵做异常填充：nan/inf 用前向填充；单日涨跌幅超过阈值时用前一日价格填充。返回新 DataFrame。

    注意：各列首个有效观测点之前的日期保持 NaN（不做后向填充）——
    否则上市/首个数据日之前的区间会被未来价格回填成「恒定价格」，
    制造零波动率/零动量的假数据，污染选择与定权（原型口径中未上市区间为 NaN 不参与）。
    """
    if prices is None or prices.empty:
        return prices
    out = prices.copy()
    # 先按列处理 nan/inf
    out = out.replace([float("inf"), float("-inf")], float("nan"))
    # 记录各列首个有效观测点，用于禁止上市前后向回填
    first_valid = {col: out[col].first_valid_index() for col in out.columns}
    out = out.ffill()
    # 按列：单日涨跌幅超过阈值则用前一日价格填充
    for col in out.columns:
        prev = out[col].shift(1)
        pct = out[col].pct_change(fill_method=None)
        abnormal = (prev > 1e-12) & (pct.abs() > max_daily_pct_change)
        if abnormal.any():
            out.loc[abnormal, col] = prev[abnormal]
    out = out.ffill()
    # 首个有效观测点之前的回填值置回 NaN（防前视）
    for col, fv in first_valid.items():
        if fv is not None:
            out.loc[out.index < fv, col] = float("nan")
    return out


def _build_tech_columns(df: pd.DataFrame, close_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """从原始数据构建技术指标附加列，附加到 prices DataFrame。

    优先从 MongoDB 原始数据中提取预计算的技术指标（bull_bear_ma / RSI / STD）；
    若原始数据不含这些字段，则基于收盘价自动计算 RSI-14 和 STD-20，
    均线多空通过 MA5 > MA20 判定。任何选择器均可消费这些附加列。
    """
    codes = [c for c in close_df.columns if not c.endswith("_discount")]
    tech_parts: list[pd.DataFrame] = []

    has_bull_bear = "bull_bear_ma" in df.columns
    has_rsi = "RSI" in df.columns
    has_std = "STD" in df.columns

    if has_bull_bear or has_rsi or has_std:
        # 从 MongoDB 原始数据直接提取预计算指标
        if has_bull_bear:
            bb = df.pivot_table(index="date", columns="code", values="bull_bear_ma", aggfunc="last")
            bb.columns = [f"{c}_bull_bear_ma" for c in bb.columns]
            tech_parts.append(bb)
        if has_rsi:
            rsi = df.pivot_table(index="date", columns="code", values="RSI", aggfunc="last")
            rsi.columns = [f"{c}_RSI" for c in rsi.columns]
            tech_parts.append(rsi)
        if has_std:
            std = df.pivot_table(index="date", columns="code", values="STD", aggfunc="last")
            std.columns = [f"{c}_STD" for c in std.columns]
            tech_parts.append(std)
    else:
        # 基于收盘价自动计算技术指标
        close_only = close_df[codes]
        # RSI-14
        delta = close_only.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.rolling(14, min_periods=14).mean()
        avg_loss = loss.rolling(14, min_periods=14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi_calc = 100 - (100 / (1 + rs))
        rsi_calc.columns = [f"{c}_RSI" for c in rsi_calc.columns]
        tech_parts.append(rsi_calc)

        # STD-20
        std_calc = close_only.pct_change().rolling(20, min_periods=20).std()
        std_calc.columns = [f"{c}_STD" for c in std_calc.columns]
        tech_parts.append(std_calc)

        # 均线多空（MA5 > MA20 → TRUE）
        ma5 = close_only.rolling(5, min_periods=5).mean()
        ma20 = close_only.rolling(20, min_periods=20).mean()
        bull_bear = (ma5 > ma20).replace({True: "TRUE", False: "FALSE"})
        bull_bear.columns = [f"{c}_bull_bear_ma" for c in bull_bear.columns]
        tech_parts.append(bull_bear)

    if not tech_parts:
        return None
    return pd.concat(tech_parts, axis=1)


@dataclass
class DataFeed:
    """回测使用的行情数据提供器.

    prices 是主价格矩阵（close + 附加指标列），index 为 DatetimeIndex。
    extra_prices 承载额外的价格维度（如 vwap），供 iter_bars() 填充到 Bar.extra，
    使 ExecutionEngine 可按优先级取价（vwap → close），所有策略自动受益。
    """

    prices: pd.DataFrame
    config: BacktestConfig
    extra_prices: Dict[str, pd.DataFrame] = field(default_factory=dict)
    # 缺日保真矩阵：保留品种缺日 NaN（仅清理 inf），供声明了缺日保真的策略信号计算使用；
    # 引擎逐日估值始终用 prices（ffill 后）。None 时回退 prices。
    strategy_prices: Optional[pd.DataFrame] = None

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
        # 缺日保真矩阵：sanitize 前的原始矩阵（仅清理 inf），是否消费由策略声明决定
        strategy_prices = strip_invalid_values(prices)
        prices = sanitize_prices(prices)
        return cls(prices=prices, config=config, strategy_prices=strategy_prices)

    def iter_bars(self) -> Iterator[Tuple[pd.Timestamp, Bar]]:
        """按时间顺序逐行输出 Bar 数据，为回测引擎驱动时间提供基础.

        若 extra_prices 非空（如 vwap 宽表），自动填充到 Bar.extra，
        使下游 ExecutionEngine 通过 Bar.get_price() 按优先级取价。
        """
        for time, row in self.prices.iterrows():
            # 确保 close 是字典格式
            try:
                close_dict = row.to_dict()
            except Exception:
                close_dict = {col: row[col] for col in self.prices.columns}

            if not isinstance(close_dict, dict):
                if isinstance(row, pd.Series):
                    close_dict = row.to_dict()
                else:
                    close_dict = {col: getattr(row, col, None) for col in self.prices.columns}

            # 确保所有值都是浮点数，过滤掉 NaN 和无效值
            close_dict = {
                code: float(price)
                for code, price in close_dict.items()
                if pd.notna(price) and isinstance(price, (int, float, str))
            }

            if not isinstance(close_dict, dict):
                raise ValueError(
                    f"无法将价格数据转换为字典格式。"
                    f"时间: {time}, 数据类型: {type(close_dict)}, 值: {close_dict}"
                )

            # 构建 Bar.extra：从 extra_prices 提取当日数据
            extra: Optional[Dict[str, Dict[str, float]]] = None
            if self.extra_prices:
                extra = {}
                for source_name, source_df in self.extra_prices.items():
                    if time in source_df.index:
                        src_row = source_df.loc[time]
                        extra[source_name] = {
                            code: float(val)
                            for code, val in (src_row.to_dict() if isinstance(src_row, pd.Series) else {}).items()
                            if pd.notna(val) and isinstance(val, (int, float))
                        }

            yield time, Bar(time=time, close=close_dict, extra=extra if extra else None)

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
