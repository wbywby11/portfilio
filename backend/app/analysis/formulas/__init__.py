"""核心计算公式模块.

本模块包含所有资产分析的基础计算公式，采用纯函数设计。

公式分类：
1. TR样本点位计算（tr.py）
2. 净值计算（nav.py）
3. 收益率计算（returns.py）
4. 波动率计算（volatility.py）
5. 回撤计算（drawdown.py）
6. 夏普比率（sharpe_ratio.py）
7. Calmar比率（calmar_ratio.py）
8. 相关性计算（correlation.py）
"""

from app.analysis.formulas.returns import (
    calculate_simple_returns,
    calculate_log_returns,
    calculate_cumulative_return,
    calculate_annualized_return,
)

from app.analysis.formulas.volatility import (
    calculate_volatility,
    calculate_rolling_volatility,
)

from app.analysis.formulas.drawdown import (
    calculate_drawdown_series,
    calculate_max_drawdown,
)

from app.analysis.formulas.sharpe_ratio import (
    calculate_sharpe_ratio,
)

from app.analysis.formulas.calmar_ratio import (
    calculate_calmar_ratio,
)

from app.analysis.formulas.correlation import (
    calculate_correlation_matrix,
)

from app.analysis.formulas.sortino_ratio import (
    calculate_sortino_ratio,
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
