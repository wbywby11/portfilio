"""核心计算公式模块.

本模块包含所有资产分析的基础计算公式，采用纯函数设计。

公式分类：
1. TR样本点位计算（tr.py）
2. 净值计算（nav.py）
3. 收益率计算（returns.py）
4. 波动率计算（volatility.py）
5. 回撤计算（drawdown.py）
6. 夏普比率（委托 formula/）
7. Calmar比率（calmar_ratio.py）
8. 相关性计算（correlation.py）
9. Sortino比率（委托 formula/）

收益率/波动率/夏普/索提诺的基础计算统一委托 app.formula/，
此处通过薄包装保持 calculate_* 命名兼容并增加空值防护。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---- 委托 formula/ 的基础公式（薄包装 + 空值防护） ----

from app.formula.returns import compute_simple_returns, compute_log_returns
from app.formula.volatility import compute_volatility
from app.formula.sharpe_ratio import compute_sharpe_ratio
from app.formula.sortino_ratio import compute_sortino_ratio


def calculate_simple_returns(prices: pd.Series) -> pd.Series:
    """计算简单收益率（委托 formula/，增加空值防护）."""
    if prices is None or (hasattr(prices, 'empty') and prices.empty):
        return pd.Series(dtype=float)
    result = compute_simple_returns(prices.to_frame()) if isinstance(prices, pd.Series) else compute_simple_returns(prices)
    if isinstance(result, pd.DataFrame):
        return result.iloc[:, 0]
    return result


def calculate_log_returns(prices: pd.Series) -> pd.Series:
    """计算对数收益率（委托 formula/，增加空值防护）."""
    if prices is None or (hasattr(prices, 'empty') and prices.empty):
        return pd.Series(dtype=float)
    log_returns = np.log(prices / prices.shift(1))
    return log_returns.dropna()


def calculate_volatility(
    returns: pd.Series,
    annualize: bool = False,
    freq_factor: int = 260
) -> float:
    """计算波动率（委托 formula/，增加空值防护）."""
    if returns is None or (hasattr(returns, 'empty') and returns.empty):
        return 0.0
    result = compute_volatility(returns.to_frame() if isinstance(returns, pd.Series) else returns,
                                annualize=annualize, freq_factor=freq_factor)
    if isinstance(result, pd.Series):
        return float(result.iloc[0]) if len(result) > 0 else 0.0
    return float(result)


def calculate_sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    freq_factor: int = 260
) -> float:
    """计算夏普比率（委托 formula/，增加空值防护）."""
    if returns is None or (hasattr(returns, 'empty') and returns.empty) or len(returns) < 2:
        return 0.0
    return compute_sharpe_ratio(returns, risk_free_rate=risk_free_rate, freq_factor=freq_factor)


def calculate_sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    annualize: bool = True,
    freq_factor: int = 260,
) -> float:
    """计算索提诺比率（委托 formula/，增加空值防护）.

    annualize 参数保留以兼容历史调用，实际年化由 formula 层统一处理。
    """
    if returns is None or (hasattr(returns, 'empty') and returns.empty) or len(returns) < 2:
        return 0.0
    return compute_sortino_ratio(returns, risk_free_rate=risk_free_rate, freq_factor=freq_factor)


# ---- analysis 独有公式（从本地子模块导入） ----

from app.analysis.formulas.returns import (
    calculate_cumulative_return,
    calculate_annualized_return,
)

from app.analysis.formulas.volatility import (
    calculate_rolling_volatility,
)

from app.analysis.formulas.drawdown import (
    calculate_drawdown_series,
    calculate_max_drawdown,
)

from app.analysis.formulas.calmar_ratio import (
    calculate_calmar_ratio,
)

from app.analysis.formulas.correlation import (
    calculate_correlation_matrix,
)

from app.analysis.formulas.information_ratio import (
    calculate_information_ratio,
)

from app.analysis.formulas.risk_measures import (
    calculate_var,
    calculate_cvar,
)

from app.analysis.formulas.nav import (
    calculate_nav_from_prices,
    calculate_nav_from_returns,
    calculate_index_nav,
)

from app.analysis.formulas.tr import (
    compute_index_tr,
    compute_futures_tr,
    compute_spot_tr,
    batch_compute_tr,
)

__all__ = [
    # 收益率
    "calculate_simple_returns",
    "calculate_log_returns",
    "calculate_cumulative_return",
    "calculate_annualized_return",
    # 波动率
    "calculate_volatility",
    "calculate_rolling_volatility",
    # 回撤
    "calculate_drawdown_series",
    "calculate_max_drawdown",
    # 风险调整收益
    "calculate_sharpe_ratio",
    "calculate_calmar_ratio",
    "calculate_sortino_ratio",
    "calculate_information_ratio",
    # 风险度量
    "calculate_var",
    "calculate_cvar",
    # 相关性
    "calculate_correlation_matrix",
    # 净值
    "calculate_nav_from_prices",
    "calculate_nav_from_returns",
    "calculate_index_nav",
    # TR样本点位
    "compute_index_tr",
    "compute_futures_tr",
    "compute_spot_tr",
    "batch_compute_tr",
]
