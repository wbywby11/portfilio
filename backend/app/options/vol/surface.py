"""
波动率曲面 —— 二维插值（货币性 × 期限）

用法:
    from vol.surface import VolSurface
    surface = VolSurface(moneyness_grid, tenor_grid, vol_grid)
    vol = surface.get_vol(moneyness=1.05, tenor_years=0.5)
"""

import numpy as np
from typing import List, Optional, Tuple


class VolSurface:
    """二维波动率曲面

    支持线性 / 三次样条插值。

    Attrs:
        moneyness_grid: 货币性网格 (K/S)，如 [0.8, 0.9, 1.0, 1.1, 1.2]
        tenor_grid:     期限网格（年），如 [0.083, 0.25, 0.5, 1.0]
        vol_grid:       波动率网格，shape=(len(tenors), len(moneyness))
    """

    def __init__(self,
                 moneyness_grid: List[float],
                 tenor_grid: List[float],
                 vol_grid: List[List[float]],
                 method: str = 'linear'):
        """
        Args:
            moneyness_grid: K/S 网格
            tenor_grid: 期限网格（年）
            vol_grid: vol_grid[i][j] = σ(tenor_i, moneyness_j)
            method: 'linear' or 'cubic'
        """
        self.moneyness = np.array(moneyness_grid, dtype=float)
        self.tenors = np.array(tenor_grid, dtype=float)
        self.vols = np.array(vol_grid, dtype=float)
        self.method = method

        assert self.vols.shape == (len(self.tenors), len(self.moneyness)), \
            f"vol_grid shape mismatch: {self.vols.shape} vs ({len(self.tenors)}, {len(self.moneyness)})"

    def get_vol(self, moneyness: float, tenor_years: float) -> float:
        """获取任意 (moneyness, tenor) 点的波动率

        边界外推：
        - moneyness 超出范围 → 用最近的边界值外推
        - tenor 超出范围 → 用最近的边界值外推
        """
        if self.method == 'linear':
            return self._interp_linear(moneyness, tenor_years)
        else:
            return self._interp_cubic(moneyness, tenor_years)

    def get_vol_from_strike(self, S: float, K: float, tau: float) -> float:
        """便捷接口：从标价和行权价获取波动率"""
        return self.get_vol(K / S, tau)

    def _interp_linear(self, m: float, t: float) -> float:
        """双线性插值"""
        # 找 moneyness 区间
        m_idx = np.searchsorted(self.moneyness, m)
        if m_idx == 0:
            m_lo = m_hi = self.moneyness[0]
            wm = 0.0
        elif m_idx == len(self.moneyness):
            m_lo = m_hi = self.moneyness[-1]
            wm = 1.0
        else:
            m_lo = self.moneyness[m_idx - 1]
            m_hi = self.moneyness[m_idx]
            wm = (m - m_lo) / (m_hi - m_lo + 1e-16)

        # 找 tenor 区间
        t_idx = np.searchsorted(self.tenors, t)
        if t_idx == 0:
            t_lo = t_hi = self.tenors[0]
            wt = 0.0
        elif t_idx == len(self.tenors):
            t_lo = t_hi = self.tenors[-1]
            wt = 1.0
        else:
            t_lo = self.tenors[t_idx - 1]
            t_hi = self.tenors[t_idx]
            wt = (t - t_lo) / (t_hi - t_lo + 1e-16)

        # 四个角的波动率值
        v00 = self._grid_val(t_idx - 1 if t_idx > 0 else 0,
                             m_idx - 1 if m_idx > 0 else 0)
        v01 = self._grid_val(t_idx - 1 if t_idx > 0 else 0,
                             min(m_idx, len(self.moneyness) - 1))
        v10 = self._grid_val(min(t_idx, len(self.tenors) - 1),
                             m_idx - 1 if m_idx > 0 else 0)
        v11 = self._grid_val(min(t_idx, len(self.tenors) - 1),
                             min(m_idx, len(self.moneyness) - 1))

        # 在每个方向先插值
        if t_idx == 0 or t_idx == len(self.tenors):
            v_on_m_lo = v00
            v_on_m_hi = v01
        else:
            v_on_m_lo = v00 + wt * (v10 - v00)
            v_on_m_hi = v01 + wt * (v11 - v01)

        if m_idx == 0 or m_idx == len(self.moneyness):
            return v_on_m_lo
        else:
            return v_on_m_lo + wm * (v_on_m_hi - v_on_m_lo)

    def _interp_cubic(self, m: float, t: float) -> float:
        """三次样条插值（双变量）
        
        沿 moneyness 方向做三次样条，然后沿 tenor 方向再做一次。
        使用 scipy.interpolate.CubicSpline 保证光滑性。
        """
        from scipy.interpolate import CubicSpline
        
        # 沿每个 tenor 行做 moneyness 方向的 cubic，得到该 tenor 下的插值
        vols_at_tenors = np.zeros(len(self.tenors))
        for i in range(len(self.tenors)):
            cs = CubicSpline(self.moneyness, self.vols[i, :])
            vols_at_tenors[i] = cs(m)
        
        # 沿 tenor 方向做 cubic
        cs_t = CubicSpline(self.tenors, vols_at_tenors)
        return float(cs_t(t))

    @staticmethod
    def _cubic_interp_1d(x: np.ndarray, y: np.ndarray, xi: float) -> float:
        """一维三次样条插值"""
        return np.interp(xi, x, y)

    def _grid_val(self, t_idx: int, m_idx: int) -> float:
        """安全的网格值访问"""
        t_idx = max(0, min(t_idx, len(self.tenors) - 1))
        m_idx = max(0, min(m_idx, len(self.moneyness) - 1))
        return self.vols[t_idx, m_idx]

    def _get_vol_row(self, tenor: float) -> np.ndarray:
        """获取指定期限的一行波动率（插值）"""
        result = np.zeros(len(self.moneyness))
        for i, m in enumerate(self.moneyness):
            result[i] = self._interp_linear(m, tenor)
        return result

    def _get_vol_col(self, moneyness: float) -> np.ndarray:
        """获取指定货币性的一列波动率（插值）"""
        result = np.zeros(len(self.tenors))
        for i, t in enumerate(self.tenors):
            result[i] = self._interp_linear(moneyness, t)
        return result


def build_flat_surface(tenors: List[float], vols: List[float]) -> VolSurface:
    """从一组期限波动率构建平坦波动率曲面（无 smile）

    Args:
        tenors: 期限列表（年），如 [0.083, 0.25, 0.5, 1.0]
        vols: 对应波动率，如 [0.22, 0.20, 0.19, 0.18]

    Returns:
        VolSurface: 平坦曲面（货币性维度只有1个点=无smile）
    """
    return VolSurface(
        moneyness_grid=[1.0],       # 只有 ATM
        tenor_grid=tenors,
        vol_grid=[[v] for v in vols],
    )
