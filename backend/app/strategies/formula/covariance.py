"""Covariance matrix related formulas."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


CovarianceMethod = Literal["sample", "ledoit_wolf"]


def _ledoit_wolf_shrinkage(returns: pd.DataFrame) -> pd.DataFrame:
    """Ledoit-Wolf 收缩协方差估计。

    优先使用 sklearn 实现；若 sklearn 不可用则降级为手动实现。

    Parameters
    ----------
    returns : pd.DataFrame
        资产收益率矩阵，行为时间，列为资产。

    Returns
    -------
    pd.DataFrame
        收缩后的协方差矩阵，索引和列与 ``returns.columns`` 一致。
    """
    try:
        from sklearn.covariance import LedoitWolf

        lw = LedoitWolf().fit(returns.values)
        cov_array = lw.covariance_
    except ImportError:
        # 手动实现 Ledoit-Wolf 收缩估计
        sample_cov = returns.cov().values
        n, p = returns.shape
        if p == 0:
            return returns.cov()

        # 目标矩阵: mu * I
        mu = np.trace(sample_cov) / p

        # 计算最优收缩强度 delta (Oracle Approximating Shrinkage)
        X = returns.values - returns.values.mean(axis=0)
        sum_sq = 0.0
        for t in range(n):
            x_t = X[t, :].reshape(-1, 1)
            m_t = x_t @ x_t.T - sample_cov
            sum_sq += np.sum(m_t ** 2)
        beta = sum_sq / (n ** 2)

        gamma = np.sum((sample_cov - mu * np.eye(p)) ** 2)

        delta = min(beta / gamma, 1.0) if gamma > 0 else 1.0

        cov_array = delta * mu * np.eye(p) + (1 - delta) * sample_cov

    return pd.DataFrame(cov_array, index=returns.columns, columns=returns.columns)


def compute_covariance(returns: pd.DataFrame, method: CovarianceMethod = "sample") -> pd.DataFrame:
    """Compute covariance matrix of asset returns.

    Parameters
    ----------
    returns : pd.DataFrame
        资产收益率矩阵，行为时间，列为资产。
    method : CovarianceMethod, default ``"sample"``
        协方差估计方法：
        - ``"sample"``: 样本协方差矩阵。
        - ``"ledoit_wolf"``: Ledoit-Wolf 收缩估计，提供更稳健的协方差估计。

    Returns
    -------
    pd.DataFrame
        协方差矩阵，索引和列与 ``returns.columns`` 一致。

    Raises
    ------
    ValueError
        当 ``method`` 不是受支持的值时抛出。
    """
    if method == "sample":
        return returns.cov()
    elif method == "ledoit_wolf":
        return _ledoit_wolf_shrinkage(returns)
    else:
        raise ValueError(f"Unsupported covariance method: {method}")
