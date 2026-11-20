# -*- coding: utf-8 -*-
"""四象限信号驱动组合权重模型。

基于信号标的（默认 600905.SH 三峡能源）的方向信号与波动信号判定四象限，
对各子策略按「逆波动率基础权重 × 象限放大」动态调权。

支持三种调仓模式（rebalance_mode）：
- signal_driven: 事件驱动，象限切换即触发再平衡（T+2 生效），逆波动率 + 象限 Boost
- monthly_quadrant: 月度定期再平衡，逆波动率基础权重 + 象限 Boost 缩放
- monthly_inv_vol: 月度定期再平衡，仅逆波动率权重分配（无象限 Boost，无需信号标的）

信号定义（与原型 signal_engine.py 一致，仅 signal_driven / monthly_quadrant 模式使用）：
- 方向信号：收盘价相对 60 日均线偏离度，> +5% → up，< -5% → down，否则保持上期
- 波动信号：HV20 在过去 252 日的百分位，> 70% → high_vol，< 30% → low_vol，否则保持上期
- 象限：方向与波动均非盲区时确定，否则保持上期

权重机制（基于原型 quadrant_allocator.py，并修复其 boost 坍塌缺陷）：
- 基础权重：各子策略近一年（252日）波动率倒数，无效策略权重为 0（无最低权重兜底）
- 象限调权：侧重策略权重 × boost（默认 1.5）后整体归一化，其余策略等比压缩但不清零；
  原型「增量扣减」实现在侧重策略基础权重 > 1/boost 时会把其余策略清零，已修正

本模型只负责「给定日期 → 输出权重」与「输出象限序列」，
不决定何时调仓（由回测引擎消费象限序列做事件驱动再平衡）。
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from app.portfolio.weight_models.base import PortfolioWeightModel

# 默认象限 → 侧重策略映射已移除：必须在前端组合配置中显式指定 quadrant_strategy_map，
# 键为象限名（up_low_vol/up_high_vol/down_low_vol/down_high_vol），
# 值为组合内实际存在的子策略标识。

# 支持的调仓模式
REBALANCE_MODES = ("signal_driven", "monthly_quadrant", "monthly_inv_vol")


class QuadrantWeightModel(PortfolioWeightModel):
    """四象限信号驱动组合权重模型。

    支持三种调仓模式：
    - signal_driven: 事件驱动（象限切换触发），逆波动率 + 象限 Boost
    - monthly_quadrant: 月度定期，逆波动率 + 象限 Boost
    - monthly_inv_vol: 月度定期，仅逆波动率（无 Boost，无需信号标的）
    """

    def __init__(
        self,
        signal_prices: Optional[pd.Series] = None,
        vol_window: int = 252,
        boost_factor: float = 1.5,
        quadrant_strategy_map: Optional[Dict[str, str]] = None,
        sma_window: int = 60,
        direction_up_threshold: float = 0.05,
        direction_down_threshold: float = -0.05,
        hv_window: int = 20,
        vol_percentile_window: int = 252,
        vol_high_threshold: float = 0.70,
        vol_low_threshold: float = 0.30,
        rebalance_mode: str = "signal_driven",
    ) -> None:
        """
        Args:
            signal_prices: 信号标的日收盘价序列（DatetimeIndex → float）。
                monthly_inv_vol 模式下可为 None。
            vol_window: 逆波动率基础权重的计算窗口（交易日，默认 252）
            boost_factor: 象限侧重策略的权重放大倍数（默认 1.5）
            quadrant_strategy_map: 象限名 → 子策略标识的映射。
                signal_driven / monthly_quadrant 模式必传；monthly_inv_vol 模式忽略。
            sma_window: 方向信号均线窗口（默认 60）
            direction_up_threshold: 偏离度上涨阈值（默认 +5%）
            direction_down_threshold: 偏离度下跌阈值（默认 -5%）
            hv_window: 历史波动率计算窗口（默认 20）
            vol_percentile_window: 波动率百分位排名窗口（默认 252）
            vol_high_threshold: 高波百分位阈值（默认 70%）
            vol_low_threshold: 低波百分位阈值（默认 30%）
            rebalance_mode: 调仓模式，可选 signal_driven / monthly_quadrant / monthly_inv_vol
        """
        if rebalance_mode not in REBALANCE_MODES:
            raise ValueError(
                f"不支持的调仓模式 '{rebalance_mode}'，可选值: {REBALANCE_MODES}"
            )
        self._rebalance_mode = rebalance_mode
        self._enable_boost = rebalance_mode != "monthly_inv_vol"

        # monthly_inv_vol 模式不需要象限映射和信号标的
        if self._enable_boost:
            if not quadrant_strategy_map:
                raise ValueError(
                    "四象限调权（signal_driven / monthly_quadrant）必须配置 quadrant_strategy_map"
                    "（象限名→子策略标识），请在组合设置中为每个象限指定对应的侧重策略。"
                )
            if signal_prices is None or signal_prices.empty:
                raise ValueError(
                    f"调仓模式 '{rebalance_mode}' 需要提供信号标的价格序列（signal_prices）"
                )

        self._vol_window = vol_window
        self._boost_factor = boost_factor
        self._quadrant_strategy_map = dict(quadrant_strategy_map) if quadrant_strategy_map else {}
        self._sma_window = sma_window
        self._direction_up = direction_up_threshold
        self._direction_down = direction_down_threshold
        self._hv_window = hv_window
        self._vol_pct_window = vol_percentile_window
        self._vol_high = vol_high_threshold
        self._vol_low = vol_low_threshold

        # 预计算象限序列（避免每次 compute_weights 重复计算）
        if self._enable_boost and signal_prices is not None:
            self._quadrant_series = self._compute_quadrant_series(signal_prices)
        else:
            self._quadrant_series = pd.Series(dtype=str)

    # ------------------------------------------------------------------
    # 参数 Schema（供 API 层派生可配置参数集合，避免白名单漂移）
    # ------------------------------------------------------------------

    @classmethod
    def get_param_schema(cls):
        """返回参数 Schema 定义（对齐 selection/selectors/base.py 的模式）.

        覆盖除 signal_prices（运行时价格序列对象，不可前端配置）外的
        全部 11 个构造参数，默认值与 __init__ 签名保持一致。

        Returns:
            dict: {weight_model_type, display_name, description, params}
        """
        return {
            "weight_model_type": "quadrant",
            "display_name": "四象限信号驱动",
            "description": (
                "基于信号标的的方向/波动信号判定四象限，"
                "对子策略按逆波动率基础权重 × 象限放大动态调权"
            ),
            "params": [
                {"name": "vol_window", "label": "逆波动率窗口", "type": "number",
                 "default": 252, "description": "逆波动率基础权重的计算窗口（交易日）"},
                {"name": "boost_factor", "label": "象限放大倍数", "type": "number",
                 "default": 1.5, "description": "象限侧重策略的权重放大倍数"},
                {"name": "quadrant_strategy_map", "label": "象限→子策略映射", "type": "object",
                 "default": None,
                 "description": "象限名→子策略标识；signal_driven/monthly_quadrant 必传"},
                {"name": "sma_window", "label": "方向信号均线窗口", "type": "number",
                 "default": 60, "description": "方向信号均线窗口（交易日）"},
                {"name": "direction_up_threshold", "label": "上涨阈值", "type": "number",
                 "default": 0.05, "description": "偏离度上涨阈值（默认 +5%）"},
                {"name": "direction_down_threshold", "label": "下跌阈值", "type": "number",
                 "default": -0.05, "description": "偏离度下跌阈值（默认 -5%）"},
                {"name": "hv_window", "label": "历史波动率窗口", "type": "number",
                 "default": 20, "description": "历史波动率计算窗口（交易日）"},
                {"name": "vol_percentile_window", "label": "波动百分位窗口", "type": "number",
                 "default": 252, "description": "波动率百分位排名窗口（交易日）"},
                {"name": "vol_high_threshold", "label": "高波阈值", "type": "number",
                 "default": 0.70, "description": "高波百分位阈值（默认 70%）"},
                {"name": "vol_low_threshold", "label": "低波阈值", "type": "number",
                 "default": 0.30, "description": "低波百分位阈值（默认 30%）"},
                {"name": "rebalance_mode", "label": "调仓模式", "type": "select",
                 "default": "signal_driven",
                 "options": [
                     ("signal_driven", "事件驱动（象限切换触发）"),
                     ("monthly_quadrant", "月度定期 + 象限 Boost"),
                     ("monthly_inv_vol", "月度定期仅逆波动率"),
                 ],
                 "description": "调仓模式"},
            ],
        }

    # ------------------------------------------------------------------
    # PortfolioWeightModel 接口
    # ------------------------------------------------------------------

    @property
    def rebalance_mode(self) -> str:
        """当前调仓模式。"""
        return self._rebalance_mode

    def compute_weights(
        self,
        sub_navs: Dict[str, pd.Series],
        as_of: pd.Timestamp,
    ) -> Dict[str, float]:
        """计算给定日期的目标权重。

        - monthly_inv_vol 模式：仅返回逆波动率权重
        - signal_driven / monthly_quadrant 模式：逆波动率 + 象限 Boost
        """
        # 1. 基础权重：逆波动率
        vols = self._calc_strategy_vols(sub_navs, as_of)
        base_weights = self._inverse_vol_weights(vols)

        # 2. 象限调权（仅 enable_boost 模式）
        if self._enable_boost:
            # 组合起始日：对齐原型 _align_data 的 ffill 域（只用组合区间内的信号，
            # 起始日之前的信号不参与前向填充，否则首月会错误 Boost）
            combo_start = None
            for nav in sub_navs.values():
                if len(nav) > 0:
                    d0 = nav.index[0]
                    combo_start = d0 if combo_start is None else min(combo_start, d0)
            quadrant = self._quadrant_at(as_of, combo_start)
            favored = self._quadrant_strategy_map.get(quadrant)
            if favored is not None and favored in base_weights:
                weights = self._boost_weights(base_weights, favored)
            else:
                weights = base_weights
        else:
            weights = base_weights

        # 3. 归一化（防浮点误差）
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        return weights

    def get_quadrant_series(self) -> pd.Series:
        """暴露象限序列，供外部（API 层）传给引擎做事件驱动再平衡。"""
        return self._quadrant_series.copy()

    # ------------------------------------------------------------------
    # 信号计算（私有）
    # ------------------------------------------------------------------

    def _compute_quadrant_series(self, price: pd.Series) -> pd.Series:
        """计算四象限信号序列（含盲区保持逻辑）。

        Returns:
            Series（DatetimeIndex → str）：
            "up_low_vol" / "up_high_vol" / "down_low_vol" / "down_high_vol" / "neutral"
        """
        price = price.dropna()

        # ---- 方向信号 ----
        sma = price.rolling(self._sma_window, min_periods=self._sma_window).mean()
        deviation = price / sma - 1
        direction = pd.Series("neutral", index=price.index)
        direction[deviation > self._direction_up] = "up"
        direction[deviation < self._direction_down] = "down"
        # 盲区保持：neutral → 上一个非 neutral 值
        direction = direction.replace("neutral", np.nan).ffill().fillna("neutral")

        # ---- 波动信号 ----
        returns = price.pct_change()
        hv = returns.rolling(self._hv_window, min_periods=self._hv_window).std() * np.sqrt(260)
        hv_percentile = hv.rolling(
            self._vol_pct_window, min_periods=self._vol_pct_window
        ).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
        vol_state = pd.Series("neutral", index=price.index)
        vol_state[hv_percentile > self._vol_high] = "high_vol"
        vol_state[hv_percentile < self._vol_low] = "low_vol"
        # 盲区保持
        vol_state = vol_state.replace("neutral", np.nan).ffill().fillna("neutral")

        # ---- 象限判定 ----
        quadrant = pd.Series("neutral", index=price.index)
        both_valid = (direction != "neutral") & (vol_state != "neutral")
        quadrant[both_valid] = direction[both_valid] + "_" + vol_state[both_valid]
        # 象限盲区保持
        quadrant = quadrant.replace("neutral", np.nan).ffill().fillna("neutral")

        quadrant.name = "quadrant"
        return quadrant

    def _quadrant_at(
        self,
        as_of: pd.Timestamp,
        combo_start: Optional[pd.Timestamp] = None,
    ) -> Optional[str]:
        """取 as_of 的有效象限；无有效值或 neutral 时返回 None（不做 Boost）。

        与原型 quadrant_allocator._align_data + _run_monthly 口径一致：
        信号先 reindex 到组合日期轴再 ffill，因此组合起始日之前的信号
        不参与前向填充（首月无象限 → 不 Boost，等权）；
        组合区间内的信号缺失日则用前值填充。
        """
        if self._quadrant_series.empty:
            return None
        s = self._quadrant_series
        if combo_start is not None:
            s = s[s.index >= combo_start]
        valid = s[s.index <= as_of]
        if valid.empty:
            return None
        value = valid.iloc[-1]
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        return None if value == "neutral" else str(value)

    # ------------------------------------------------------------------
    # 权重计算（私有）
    # ------------------------------------------------------------------

    def _calc_strategy_vols(
        self,
        sub_navs: Dict[str, pd.Series],
        as_of: pd.Timestamp,
    ) -> Dict[str, float]:
        """计算各子策略近一年年化波动率。数据不足返回 NaN。"""
        result: Dict[str, float] = {}
        window = self._vol_window
        for key, nav in sub_navs.items():
            nav_slice = nav[nav.index <= as_of].tail(window + 1)
            if len(nav_slice) < 60:  # 至少 60 日数据
                result[key] = np.nan
                continue
            ret = nav_slice.pct_change(fill_method=None).dropna()
            result[key] = float(ret.std() * np.sqrt(260))
        return result

    @staticmethod
    def _inverse_vol_weights(vols: Dict[str, float]) -> Dict[str, float]:
        """波动率倒数权重。有效策略按波动率倒数分配，无效策略权重为 0，全部无效时等权。"""
        n = len(vols)
        valid = {k: v for k, v in vols.items() if not np.isnan(v) and v > 0}

        if not valid:
            return {k: 1.0 / n for k in vols} if n > 0 else {}

        inv_vol = {k: 1.0 / v for k, v in valid.items()}
        total = sum(inv_vol.values())

        weights: Dict[str, float] = {}
        for k in vols:
            weights[k] = inv_vol[k] / total if k in valid else 0.0
        return weights

    def _boost_weights(
        self,
        base_weights: Dict[str, float],
        favored: str,
    ) -> Dict[str, float]:
        """象限调权：侧重策略权重 × boost 后整体归一化，合计仍为 100%。

        其余策略被等比压缩（相互间比例不变）但永不清零。
        旧实现用「增量从其余策略扣减」，当侧重策略基础权重 > 1/boost 时
        增量超出其余策略总权重，会把其余策略全部清零（boost 坍塌），
        例如逆波动率下低波策略基础权重 ~0.78 > 1/1.5 ≈ 0.667 时必然坍塌。
        """
        boost = self._boost_factor
        if favored not in base_weights:
            return dict(base_weights)

        boosted: Dict[str, float] = {
            k: (w * boost if k == favored else w) for k, w in base_weights.items()
        }
        total = sum(boosted.values())
        if total > 0:
            boosted = {k: v / total for k, v in boosted.items()}
        return boosted
