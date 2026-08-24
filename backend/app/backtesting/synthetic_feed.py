"""SyntheticAssetFeed：合成资产价格矩阵（引擎层数据供给）.

将各子策略的 NAV 序列（第一段引擎运行输出）折算为合成资产价格序列，
接口与 DataFeed 同构：日期取各子策略 NAV 的**并集**并对缺日前向/后向
填充（与 composite_engine 对齐口径），逐列归一到统一起点后作为"价格"。

组合层第二段引擎运行以合成资产为标的，经 runner.run_unified 由同一个
BacktestEngine 逐日撮合——与单策略回测共用同一套调度/撮合/风控/净值
逻辑，不再存在"组合专用"的第二套计算口径。

本模块只依赖引擎层内部组件（DataFeed / BacktestConfig），不引入任何
上层依赖，保持依赖方向契约。
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed


def build_synthetic_prices(
    sub_nav_series: Dict[str, pd.Series],
    base: float = 1000.0,
) -> pd.DataFrame:
    """将各子策略 NAV 折算为合成资产价格矩阵.

    对齐口径与 composite_engine.run_portfolio_backtest 一致：
    - 日期取所有子策略 NAV 的并集（任一子策略数据截止不截断组合区间）；
    - 缺日前向填充 + 后向填充（reindex(common_idx).ffill().bfill()）；
    - 逐列按首个有效点归一到 base（收益率序列保持不变）。

    Args:
        sub_nav_series: 子策略标识 → NAV 序列（DatetimeIndex → float）
        base: 合成资产起始价格（通常取组合 initial_nav）

    Returns:
        DataFrame（index=并集日期，columns=子策略标识），全为有限值
    """
    if not sub_nav_series:
        raise ValueError("sub_nav_series 为空，无法构建合成资产价格矩阵")

    common_idx = None
    for nav in sub_nav_series.values():
        idx = pd.DatetimeIndex(nav.index)
        common_idx = idx if common_idx is None else common_idx.union(idx)
    common_idx = common_idx.sort_values()
    if common_idx is None or len(common_idx) < 2:
        raise ValueError("子策略 NAV 日期对齐后数据不足")

    columns: Dict[str, pd.Series] = {}
    for key, nav in sub_nav_series.items():
        aligned = nav.reindex(common_idx).ffill().bfill()
        first = aligned.iloc[0]
        if first is None or pd.isna(first) or first == 0:
            raise ValueError(f"子策略 {key} 的 NAV 起点无效，无法折算合成资产价格")
        columns[key] = aligned / first * float(base)
    return pd.DataFrame(columns, index=common_idx)


def build_synthetic_feed(
    sub_nav_series: Dict[str, pd.Series],
    config: BacktestConfig,
    base: Optional[float] = None,
) -> DataFeed:
    """构建合成资产 DataFeed（组合层第二段引擎运行的数据供给）.

    合成价格由 NAV 折算而来，无缺失/异常值，无需 sanitize；
    strategy_prices 与 prices 相同（合成资产不存在缺日保真问题）。
    """
    prices = build_synthetic_prices(
        sub_nav_series, base=float(base if base is not None else config.initial_nav)
    )
    return DataFeed(prices=prices, config=config, strategy_prices=prices)
