"""ETF贴水率资产选择器.

从 etf_discount_strategy.py 提取的贴水率信号选择逻辑：
- 对每只 ETF 的贴水率序列计算滚动分位点
- 当前贴水率 <= 对应分位点阈值 → 开仓信号 (score=1.0)
- 当前贴水率 > 平仓阈值（中位数/均值） → 平仓信号 (score=-1.0)
- 可选叠加技术指标 N 选 M 过滤（趋势确认）
- 可选月度滚动参数优选（对齐原始策略 Step2）：
  回看 12 个月，对每只 ETF 在 4 窗口 × 4 信号网格中
  选出历史累计收益最高的 (window, signal) 组合
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np
import pandas as pd

from app.selection.selectors.base import BaseAssetSelector
from app.selection.types import SelectionResult

logger = logging.getLogger(__name__)

# 月度参数优选: 候选参数网格（对齐原始策略 Step0/Step1/Step2）
_OPTIMIZATION_WINDOWS = [20, 30, 60, 120]
_OPTIMIZATION_SIGNALS = ['open_long_p5', 'open_long_p10', 'open_long_p15', 'open_long_p25']
_SIGNAL_TO_QUANTILE = {
    'open_long_p5': 0.05,
    'open_long_p10': 0.10,
    'open_long_p15': 0.15,
    'open_long_p25': 0.25,
}
# 回看期内至少完成的完整交易次数（对齐原始策略 Step2 的 min_trades=3）
_MIN_TRADES_FOR_SELECTION = 3


class ETFDiscountSelector(BaseAssetSelector):
    """ETF贴水率选择器：贴水率分位点信号.

    核心特点：
    - 对每只 ETF 的贴水率序列计算滚动分位点 (p5/p10/p15/p25)
    - 当前贴水率 <= 对应分位点阈值 -> 开仓信号
    - 反波动率加权分配仓位

    参数:
        window:      贴水率滚动窗口（交易日，默认 60）
        signal_type: 开仓信号分位点（默认 open_long_p5）
    """

    @classmethod
    def get_param_schema(cls):
        return {
            "selector_type": "etf_discount",
            "display_name": "ETF贴水率",
            "description": "基于贴水率分位点信号的ETF选择器，贴水率降至历史低位时开仓，回升至中位数时平仓。"
                            "系统已自动实现T+1信号延迟：T日收盘后计算信号，T+1日执行调仓",
            "params": [
                {
                    "name": "window",
                    "label": "贴水率滚动窗口",
                    "type": "number",
                    "default": 60,
                    "min_value": 10,
                    "max_value": 252,
                    "step": 1,
                    "description": "贴水率滚动分位点计算窗口（交易日），月度参数优选开启时由系统自动选定",
                    "condition": {"field": "enable_rolling_params", "value": False},
                },
                {
                    "name": "signal_type",
                    "label": "开仓信号分位点",
                    "type": "select",
                    "default": "open_long_p5",
                    "options": [
                        ("open_long_p5", "p5 分位点"),
                        ("open_long_p10", "p10 分位点"),
                        ("open_long_p15", "p15 分位点"),
                        ("open_long_p25", "p25 分位点"),
                    ],
                    "description": "开仓信号使用的贴水率分位点，月度参数优选开启时由系统自动选定",
                    "condition": {"field": "enable_rolling_params", "value": False},
                },
                {
                    "name": "close_signal_type",
                    "label": "平仓信号分位点",
                    "type": "select",
                    "default": "close_long_median",
                    "options": [
                        ("close_long_median", "中位数 (p50)"),
                        ("close_long_p75", "p75 分位点"),
                        ("close_long_p90", "p90 分位点"),
                        ("disabled", "不启用平仓信号"),
                    ],
                    "description": "平仓信号使用的贴水率分位点，贴水率回升至此阈值时发出平仓信号",
                },
                {
                    "name": "enable_tech_filter",
                    "label": "技术指标过滤",
                    "type": "boolean",
                    "default": False,
                    "description": "是否叠加技术指标 N 选 M 过滤（趋势确认）",
                },
                {
                    "name": "std_filter_mode",
                    "label": "STD过滤模式",
                    "type": "select",
                    "default": "fixed_threshold",
                    "options": [
                        ("fixed_threshold", "固定阈值 (STD < 0.02)"),
                        ("rolling_percentile", "滚动分位 (30日排名 < 0.9)"),
                    ],
                    "description": "技术指标中 STD 条件的计算方式：固定阈值为绝对值过滤，滚动分位与原始策略 step3 对齐",
                    "condition": {"field": "enable_tech_filter", "value": True},
                },
                {
                    "name": "tech_min_pass",
                    "label": "最少通过条件数",
                    "type": "number",
                    "default": 2,
                    "min_value": 1,
                    "max_value": 3,
                    "step": 1,
                    "description": "N 选 M 中的 M，需满足的技术条件数",
                    "condition": {"field": "enable_tech_filter", "value": True},
                },
                {
                    "name": "enable_rolling_params",
                    "label": "月度参数优选",
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "开启后，每月自动回看历史数据，为每只 ETF 在 4 窗口 × 4 信号"
                        "网格中选出累计收益最高的参数组合。对齐原始策略 Step2"
                    ),
                },
                {
                    "name": "lookback_months",
                    "label": "参数优选回看月数",
                    "type": "number",
                    "default": 12,
                    "min_value": 3,
                    "max_value": 24,
                    "step": 1,
                    "description": "参数优选的历史回看月数（对齐原始策略的 12 个月回看）",
                    "condition": {"field": "enable_rolling_params", "value": True},
                },
            ],
        }

    @staticmethod
    def _detect_etf_codes(columns) -> List[str]:
        """自动检测 ETF 列（排除 _discount 后缀列）."""
        return [
            str(c) for c in columns
            if not str(c).endswith("_discount") and not str(c).endswith("_dr")
        ]

    @staticmethod
    def _signal_to_quantile(signal_type: str) -> float:
        mapping = {
            "open_long_p5": 0.05,
            "open_long_p10": 0.10,
            "open_long_p15": 0.15,
            "open_long_p25": 0.25,
            "close_long_median": 0.50,
            "close_long_p75": 0.75,
            "close_long_p90": 0.90,
        }
        return mapping.get(signal_type, 0.05)

    @staticmethod
    def _compute_rolling_percentile(
        series: pd.Series, window: int, quantile: float,
    ) -> pd.Series:
        min_periods = max(10, window // 4)
        return series.rolling(window, min_periods=min_periods).quantile(quantile)

    def _optimize_single_etf(
        self,
        dr_series: pd.Series,
        close_series: pd.Series,
        lookback_end,
        lookback_months: int,
    ) -> dict:
        """对单只 ETF 执行参数网格搜索，选出最优 (window, signal).

        对每个 (window, signal) 组合，在回看期内模拟信号开平仓并计算累计收益。
        排序规则: (-累计收益, -窗口大小, 信号名)。

        Returns:
            {best_window, best_signal} 或 {} 若无有效候选
        """
        lookback_start = lookback_end - pd.DateOffset(months=lookback_months)
        dr_lookback = dr_series.loc[lookback_start:lookback_end]
        close_lookback = close_series.loc[lookback_start:lookback_end]

        if len(dr_lookback) < 30:
            return {}

        # 预计算各窗口的滚动均值（平仓阈值，对齐原始策略的均值回归平仓）
        rolling_means: Dict[int, pd.Series] = {}
        for w in _OPTIMIZATION_WINDOWS:
            rolling_means[w] = dr_series.rolling(w, min_periods=max(10, w // 4)).mean()

        candidates = []
        for w in _OPTIMIZATION_WINDOWS:
            # 预计算该窗口所有信号的开仓阈值
            thresholds: Dict[str, pd.Series] = {}
            for sig in _OPTIMIZATION_SIGNALS:
                q = _SIGNAL_TO_QUANTILE[sig]
                thresholds[sig] = self._compute_rolling_percentile(dr_series, w, q)

            mean_thresh = rolling_means[w]

            for sig in _OPTIMIZATION_SIGNALS:
                open_thresh = thresholds[sig]

                # 在回看期内模拟信号交易
                position = 0
                entry_price = 0.0
                trade_returns = []

                for dt in dr_lookback.index:
                    dr_val = dr_lookback.loc[dt]
                    price_val = close_lookback.loc[dt]
                    if pd.isna(dr_val) or pd.isna(price_val):
                        continue

                    thresh_val = open_thresh.loc[dt] if dt in open_thresh.index else np.nan
                    mean_val = mean_thresh.loc[dt] if dt in mean_thresh.index else np.nan

                    # 平仓优先：持仓且贴水率回归均值
                    if position == 1 and not pd.isna(mean_val) and dr_val >= mean_val:
                        if entry_price > 0:
                            trade_returns.append(price_val / entry_price - 1.0)
                        position = 0
                        continue

                    # 开仓：空仓且贴水率低于分位阈值
                    if position == 0 and not pd.isna(thresh_val) and dr_val <= thresh_val:
                        position = 1
                        entry_price = price_val

                # 评估: 交易充分性过滤
                n_trades = len(trade_returns)
                if n_trades < _MIN_TRADES_FOR_SELECTION:
                    continue
                if len(dr_lookback) < 10:
                    continue

                cum_return = float(np.prod([1.0 + r for r in trade_returns]) - 1.0)
                candidates.append({
                    'window': w,
                    'signal': sig,
                    'cum_return': cum_return,
                    'n_trades': n_trades,
                })

        if not candidates:
            return {}

        # 排序: 累计收益降序 → 窗口降序 → 信号名升序（对齐原始策略 Step2）
        candidates.sort(key=lambda c: (-c['cum_return'], -c['window'], c['signal']))
        best = candidates[0]
        return {'best_window': best['window'], 'best_signal': best['signal']}

    def select(
        self,
        prices: pd.DataFrame,
        n_assets: int,
        **params,
    ) -> SelectionResult:
        """执行贴水率信号选择.

        Args:
            prices: Date x (ETF close + discount_rate) 矩阵
            n_assets: 不使用
            **params:
                - window: 滚动窗口（默认 60）
                - signal_type: 信号类型（默认 open_long_p5）

        Returns:
            SelectionResult: 选择结果
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        # ── 基础参数 ──
        default_window = int(params.get("window", 60))
        default_signal = str(params.get("signal_type", "open_long_p5"))

        # 平仓信号配置
        close_signal_type = str(params.get("close_signal_type", "close_long_median"))
        enable_close_signal = close_signal_type != "disabled"
        close_quantile = self._signal_to_quantile(close_signal_type) if enable_close_signal else None

        # 技术指标过滤配置
        enable_tech_filter = bool(params.get("enable_tech_filter", False))
        tech_min_pass = int(params.get("tech_min_pass", 2))
        std_filter_mode = str(params.get("std_filter_mode", "fixed_threshold"))

        # ── 月度参数优选配置 ──
        enable_rolling_params = bool(params.get("enable_rolling_params", False))
        lookback_months = int(params.get("lookback_months", 12))

        etf_codes = self._detect_etf_codes(prices.columns)
        if not etf_codes:
            return SelectionResult(
                selected_assets=[],
                scores={},
                ranking=pd.DataFrame(),
                timestamp=pd.Timestamp.now().isoformat(),
                selector_type="etf_discount",
                params=params,
            )

        # 逐标的计算信号
        hold_codes: List[str] = []
        signal_scores: Dict[str, float] = {}

        for code in etf_codes:
            dr_col = f"{code}_discount"
            if dr_col not in prices.columns:
                signal_scores[code] = 0.0
                continue

            dr_series = prices[dr_col].dropna()

            # ── 确定本标的使用的 (window, signal) ──
            if enable_rolling_params:
                # 月度参数优选: 回看历史，选出最优参数
                close_col = code  # 收盘价列
                close_series = (
                    prices[close_col].dropna()
                    if close_col in prices.columns else pd.Series(dtype=float)
                )
                lookback_end = dr_series.index[-1]
                best = self._optimize_single_etf(
                    dr_series, close_series, lookback_end, lookback_months,
                )
                if best:
                    window = best['best_window']
                    signal_type = best['best_signal']
                    quantile = _SIGNAL_TO_QUANTILE[signal_type]
                    logger.debug(
                        "[%s] 优选参数: window=%d, signal=%s",
                        code, window, signal_type,
                    )
                else:
                    # 优化失败 → 直接报错，不静默回退
                    raise ValueError(
                        f"ETF [{code}] 月度参数优选失败: "
                        f"回看 {lookback_months} 个月内无有效候选参数组合"
                        f"（可能原因: 历史数据不足或无足够完整交易）。"
                        f"请增加历史数据长度或关闭月度参数优选。"
                    )
            else:
                # 固定参数模式（原有逻辑）
                window = default_window
                signal_type = default_signal
                quantile = self._signal_to_quantile(signal_type)

            if len(dr_series) < window:
                signal_scores[code] = 0.0
                continue

            current_dr = dr_series.iloc[-1]
            open_threshold = self._compute_rolling_percentile(
                dr_series, window, quantile
            ).iloc[-1]

            if pd.isna(open_threshold):
                signal_scores[code] = 0.0
                continue

            # 开仓条件：贴水率 <= 分位点阈值
            if current_dr <= open_threshold:
                signal_scores[code] = 1.0
                hold_codes.append(code)
            elif enable_close_signal:
                if enable_rolling_params:
                    # 均值回归平仓（对齐原始策略 Step3）
                    mean_val = dr_series.rolling(
                        window, min_periods=max(10, window // 4)
                    ).mean().iloc[-1]
                    if not pd.isna(mean_val) and current_dr >= mean_val:
                        signal_scores[code] = -1.0
                        continue
                elif close_quantile is not None:
                    # 分位点平仓（原有逻辑）
                    close_threshold = self._compute_rolling_percentile(
                        dr_series, window, close_quantile
                    ).iloc[-1]
                    if not pd.isna(close_threshold) and current_dr > close_threshold:
                        signal_scores[code] = -1.0
                        continue

            if signal_scores.get(code, 0.0) == 0.0:
                signal_scores[code] = 0.0

        # 技术指标 N 选 M 过滤（可选，仅对开仓信号生效）
        if enable_tech_filter and hold_codes:
            if std_filter_mode == "rolling_percentile":
                # 与原始策略 step3 对齐：STD 使用 30 日滚动排名分位
                tech_conditions = [
                    {"column": "{code}_bull_bear_ma", "op": "==", "value": "TRUE"},
                    {"column": "{code}_RSI", "op": "<", "value": "70"},
                    {"column": "{code}_STD", "op": "percentile_rank<", "value": "0.9"},
                ]
                tech_pass = self.apply_tech_filter(
                    prices=prices,
                    candidates=hold_codes,
                    tech_conditions=tech_conditions,
                    min_pass=tech_min_pass,
                    rolling_window=30,
                )
            else:
                # 默认：固定阈值模式（STD < 0.02），与原有行为一致
                tech_conditions = [
                    {"column": "{code}_bull_bear_ma", "op": "==", "value": "TRUE"},
                    {"column": "{code}_RSI", "op": "<", "value": "70"},
                    {"column": "{code}_STD", "op": "<", "value": "0.02"},
                ]
                tech_pass = self.apply_tech_filter(
                    prices=prices,
                    candidates=hold_codes,
                    tech_conditions=tech_conditions,
                    min_pass=tech_min_pass,
                )
            # 未通过技术过滤的资产降级为无信号
            filtered_out = [c for c in hold_codes if not tech_pass.get(c, False)]
            for code in filtered_out:
                signal_scores[code] = 0.0
            hold_codes = [c for c in hold_codes if tech_pass.get(c, False)]

        ranking = pd.DataFrame({
            "Asset": etf_codes,
            "Selected": [c in hold_codes for c in etf_codes],
            "Signal": [signal_scores.get(c, 0.0) for c in etf_codes],
        }).set_index("Asset")

        return SelectionResult(
            selected_assets=hold_codes,
            scores=signal_scores,
            ranking=ranking,
            timestamp=pd.Timestamp.now().isoformat(),
            selector_type="etf_discount",
            params=params,
        )
