# -*- coding: utf-8 -*-
"""因子模型：为配置策略提供因子暴露 / 因子协方差 / 特异性风险。

定位
----
因子提取属于策略公式的一部分（被 FactorRiskParityStrategy 消费），
因此与策略模型同住 allocation 域，不放在 backtesting（回测只负责执行）。

核心组件
--------
- FactorSignal: 因子模型输出数据类
- FactorModel: 因子模型抽象基类，新增因子模型继承它即可被策略消费
- PcaFactorModel: PCA 因子模型（从 factor_risk_parity 抽取）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA


@dataclass
class FactorSignal:
    """因子模型输出。

    Attributes:
        date: 信号计算日期
        factor_exposures: (assets × factors) 因子暴露矩阵
        factor_returns: (dates × factors) 因子收益序列
        factor_covariance: (factors × factors) 因子协方差矩阵
        specific_risk: (assets,) 特异性风险（标准差）
    """

    date: pd.Timestamp
    factor_exposures: pd.DataFrame
    factor_returns: pd.DataFrame
    factor_covariance: np.ndarray
    specific_risk: pd.Series


class FactorModel(ABC):
    """因子模型基类。策略消费因子信号，与具体配置算法解耦。"""

    @abstractmethod
    def compute(
        self, prices: pd.DataFrame, as_of: pd.Timestamp
    ) -> FactorSignal:
        """计算截止到 as_of 日期的因子信号。

        Args:
            prices: 资产价格历史数据（行=日期，列=资产）
            as_of: 截止日期

        Returns:
            FactorSignal: 因子信号
        """

    @abstractmethod
    def get_factor_names(self) -> List[str]:
        """返回因子名称列表。"""


class PcaFactorModel(FactorModel):
    """PCA 因子模型：从资产收益率自动提取主成分因子。

    与 factor_risk_parity.py 中原 _extract_pca_factors 逻辑完全一致，
    抽取为独立可复用的 FactorModel。
    """

    def __init__(
        self,
        n_factors: int = 3,
        explained_variance: float = 0.85,
        lookback_days: int = 252,
    ) -> None:
        """
        Args:
            n_factors: 因子数量，0 表示根据解释方差自动确定
            explained_variance: 累计解释方差阈值（仅 n_factors=0 时生效）
            lookback_days: 用于 PCA 计算的回看窗口（交易日）
        """
        self._n_factors = n_factors
        self._explained_variance = explained_variance
        self._lookback_days = lookback_days

    def get_factor_names(self) -> List[str]:
        if self._n_factors and self._n_factors > 0:
            return [f"PC{i+1}" for i in range(self._n_factors)]
        # 动态模式：返回占位，实际名称在 compute() 中确定
        return [f"PC{i+1}" for i in range(10)]

    def compute(
        self, prices: pd.DataFrame, as_of: pd.Timestamp
    ) -> FactorSignal:
        """使用 PCA 从资产收益率中提取因子信号。"""
        from app.formula.returns import compute_simple_returns

        # 截取到 as_of 并应用回看窗口
        prices_slice = prices[prices.index <= as_of]
        if self._lookback_days and len(prices_slice) > self._lookback_days:
            prices_slice = prices_slice.iloc[-self._lookback_days:]

        returns = compute_simple_returns(prices_slice)
        if len(returns) < 20:
            raise ValueError(
                f"PCA 因子计算需要至少 20 个交易日收益率，实际仅有 {len(returns)} 个"
            )

        assets = returns.columns

        # 处理缺失值
        if returns.isna().any().any():
            returns = returns.ffill().bfill()
            if returns.isna().any().any():
                nan_cols = returns.columns[returns.isna().any()].tolist()
                raise ValueError(
                    f"以下资产的收益率数据存在无法填充的 NaN: {nan_cols}"
                )

        # 标准化
        returns_mean = returns.mean()
        returns_std = returns.std()
        zero_std_assets = returns_std[returns_std == 0].index.tolist()
        if zero_std_assets:
            raise ValueError(
                f"以下资产的收益率方差为 0，无法进行 PCA: {zero_std_assets}"
            )
        returns_scaled = (returns - returns_mean) / returns_std

        # 执行 PCA
        pca = PCA()
        factor_scores = pca.fit_transform(returns_scaled)

        # 确定因子数量
        n_factors = self._n_factors
        if n_factors == 0 or n_factors is None:
            cumulative_var = np.cumsum(pca.explained_variance_ratio_)
            n_factors = int(np.argmax(cumulative_var >= self._explained_variance) + 1)
        n_factors = min(n_factors, len(assets))

        factor_names = [f"PC{i+1}" for i in range(n_factors)]

        # 因子收益
        factor_returns = pd.DataFrame(
            factor_scores[:, :n_factors],
            index=returns.index,
            columns=factor_names,
        )

        # 因子暴露（载荷矩阵转置，还原到原始收益尺度）
        #
        # PCA 在标准化空间分解：z = L·s，其中 z = (r - μ)/σ
        # 还原到原始收益空间：r = σ·z + μ = (diag(σ)·L)·s + μ + σ·e
        # 所以原始尺度的因子暴露为 B = diag(σ)·L，因子收益 s 与其协方差不变。
        #
        # 必须乘回 σ：下方 specific_risk 已乘 σ 还原到原始尺度，
        # 若因子暴露留在标准化空间，两者量纲不一致（相差约 1/σ²），
        # 消费方把 factor_var 与 specific_var 相加时，特异性风险会被完全淹没。
        factor_exposures = pd.DataFrame(
            pca.components_[:n_factors, :].T * returns_std.values[:, None],
            index=assets,
            columns=factor_names,
        )

        # 特异性风险（残差标准差，还原到原始尺度）
        reconstructed = factor_scores[:, :n_factors] @ pca.components_[:n_factors, :]
        residuals = returns_scaled.values - reconstructed
        specific_risk = pd.Series(
            np.std(residuals, axis=0, ddof=1) * returns_std.values,
            index=assets,
        )

        # 因子协方差
        factor_cov = factor_returns.cov().values

        return FactorSignal(
            date=as_of,
            factor_exposures=factor_exposures,
            factor_returns=factor_returns,
            factor_covariance=factor_cov,
            specific_risk=specific_risk,
        )
