# -*- coding: utf-8 -*-
"""风险预警检测（纯计算模块，无 DB / 无状态）。

两条通道共用同一套算法：
- 策略通道：``daily_stepper._process_single_day`` 步骤 E3 调用；
- 组合通道：``monitor_service._run_portfolio_backtest_monitor`` 在
  ``build_monitor_state_fields`` 之后、``save_state`` 之前调用。

本期实现两类预警：
1. ``vol_compare``     波动率比较：短窗口波动率 / 长窗口波动率，比值越高风险越大；
2. ``corr_reversal``   相关性反转：近 N 日滚动相关性与历史中枢偏离，状态反转升级为 red。

阈值全部走 ``config`` 入参（默认 ``DEFAULT_ALERT_CONFIG``），本期不做配置 UI，
调用方需要调整时在调用点传参即可，不改检测函数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

# 年化因子只用于 detail 里展示年化波动率量级；vol_compare 的比值本身与年化因子无关。
ANNUALIZE_FACTOR = 260

# 默认配置（本期硬编码默认值，留 config 入口不实现 UI）。
DEFAULT_ALERT_CONFIG: Dict[str, Any] = {
    # ── 行情新鲜度 ──
    # 资产最后有效行情日早于面板最新日超过该天数（自然日）视为停更，不参与检测；
    # 否则陈旧价格会被当成「当前」信号（尤其相关性，dropna 后会停在停更日）。
    "price_stale_days": 7,
    # ── 波动率比较 ──
    "vol_short_window": 20,
    "vol_long_window": 60,
    "vol_yellow_ratio": 1.2,   # 比值 >= 1.2 记 yellow
    "vol_red_ratio": 1.5,      # 比值 >  1.5 记 red
    "vol_record_green": True,  # 比值 < 1.2 是否也记一条 green（前端折叠展示）
    "vol_max_assets": 20,      # 单次检测的资产上限（按传入顺序，调用方已按权重排序）
    # ── 相关性反转 ──
    "corr_window": 60,             # 当前相关性窗口（交易日）
    "corr_baseline_window": 250,   # 历史中枢窗口（约 1 年）
    "corr_max_assets": 10,         # 只取前 N 大持仓，避免 O(N^2)
    "corr_deviation_delta": 0.30,  # 与中枢偏离绝对值达到该值记 yellow
    "corr_reversal_delta": 0.40,   # 状态反转且偏离达到该值记 red
    "corr_pos_to_neg_base": 0.30,  # 正相关判定下限（中枢）
    "corr_pos_to_neg_now": -0.10,  # 反转为负相关判定上限（当前）
    "corr_low_to_high_base": 0.10,  # 低相关判定上限（中枢）
    "corr_low_to_high_now": 0.60,   # 转为高相关判定下限（当前）
}

# 排序权重：red 置顶，info（如停更跳过提示）垫底
SEVERITY_ORDER = {"red": 0, "yellow": 1, "green": 2, "info": 3}


@dataclass
class RiskAlert:
    """单条风险预警（落库前形态，由服务层补 monitor_id / signal_date）。"""

    signal_type: str                      # vol_compare / corr_reversal
    severity: str                         # green / yellow / red
    trigger_value: float                  # 触发指标值（波动率比值 / 相关系数）
    threshold: float                      # 对应级别的阈值
    window_pair: Dict[str, int] = field(default_factory=dict)
    asset_codes: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_type": self.signal_type,
            "severity": self.severity,
            "trigger_value": float(self.trigger_value),
            "threshold": float(self.threshold),
            "window_pair": dict(self.window_pair),
            "asset_codes": list(self.asset_codes),
            "detail": dict(self.detail),
        }


def _merged_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(DEFAULT_ALERT_CONFIG)
    merged.update(config or {})
    return merged


def _annualized_vol(series: pd.Series, window: int) -> Optional[float]:
    """窗口内日收益标准差 → 年化波动率；样本不足返回 None。"""
    clean = series.dropna()
    if len(clean) < window:
        return None
    return float(clean.tail(window).std(ddof=1) * np.sqrt(ANNUALIZE_FACTOR))


def detect_vol_compare_alerts(
    returns_matrix: pd.DataFrame,
    vol_windows: Optional[Dict[str, int]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[RiskAlert]:
    """波动率比较预警：短窗口年化波动率 / 长窗口年化波动率。

    Args:
        returns_matrix: 日收益矩阵（index=日期升序，columns=资产代码）。
            调用方负责只传持仓资产并按权重降序排列。
        vol_windows: ``{"short": 20, "long": 60}``，缺省取配置默认值。
        config: 阈值配置，缺省 ``DEFAULT_ALERT_CONFIG``。

    Returns:
        按 ``severity``（red → yellow → green）与比值降序排列的预警列表。
        多空/零权重资产不会出现在矩阵里；样本不足长窗口的资产直接跳过。
    """
    cfg = _merged_config(config)
    windows = dict(vol_windows or {})
    short_w = int(windows.get("short") or cfg["vol_short_window"])
    long_w = int(windows.get("long") or cfg["vol_long_window"])
    yellow_ratio = float(cfg["vol_yellow_ratio"])
    red_ratio = float(cfg["vol_red_ratio"])
    record_green = bool(cfg["vol_record_green"])
    max_assets = int(cfg["vol_max_assets"])

    if returns_matrix is None or returns_matrix.empty or short_w < 2 or long_w <= short_w:
        return []

    alerts: List[RiskAlert] = []
    for asset in list(returns_matrix.columns)[:max_assets]:
        series = returns_matrix[asset]
        short_vol = _annualized_vol(series, short_w)
        long_vol = _annualized_vol(series, long_w)
        if short_vol is None or long_vol is None:
            continue
        # 短期窗口价格完全不动（数据停更 / 合成资产）不构成「低波」信号，跳过
        if short_vol <= 0 or long_vol <= 0:
            continue
        ratio = short_vol / long_vol
        if ratio > red_ratio:
            severity, threshold = "red", red_ratio
        elif ratio >= yellow_ratio:
            severity, threshold = "yellow", yellow_ratio
        else:
            if not record_green:
                continue
            severity, threshold = "green", yellow_ratio
        alerts.append(RiskAlert(
            signal_type="vol_compare",
            severity=severity,
            trigger_value=round(ratio, 6),
            threshold=float(threshold),
            window_pair={"short": short_w, "long": long_w},
            asset_codes=[str(asset)],
            detail={
                "short_vol": round(short_vol, 6),
                "long_vol": round(long_vol, 6),
                "annualize_factor": ANNUALIZE_FACTOR,
            },
        ))

    alerts.sort(key=lambda a: (SEVERITY_ORDER.get(a.severity, 9), -a.trigger_value))
    return alerts


def detect_corr_reversal_alerts(
    returns_matrix: pd.DataFrame,
    corr_window: Optional[int] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[RiskAlert]:
    """相关性反转预警：近 N 日相关系数 vs 历史中枢（约 1 年）。

    判定顺序（先 red 后 yellow，同一资产对只产出一条）：
    1. red：状态反转且偏离达到 ``corr_reversal_delta``
       - 正相关转负：中枢 >= ``corr_pos_to_neg_base`` 且当前 <= ``corr_pos_to_neg_now``
       - 低相关转高：中枢 <= ``corr_low_to_high_base`` 且当前 >= ``corr_low_to_high_now``
    2. yellow：偏离绝对值达到 ``corr_deviation_delta``（未构成反转也提示）
    3. 其余不记录（相关性预警只落 yellow / red，避免资产对数量爆炸）

    Args:
        returns_matrix: 日收益矩阵，列顺序即持仓权重降序（只取前
            ``corr_max_assets`` 列做两两配对）。
        corr_window: 当前相关性窗口，缺省取配置默认值。
        config: 阈值配置，缺省 ``DEFAULT_ALERT_CONFIG``。

    Returns:
        按 ``severity`` 与偏离绝对值降序排列的预警列表。
    """
    cfg = _merged_config(config)
    window = int(corr_window or cfg["corr_window"])
    baseline_w = int(cfg["corr_baseline_window"])
    max_assets = int(cfg["corr_max_assets"])
    deviation_delta = float(cfg["corr_deviation_delta"])
    reversal_delta = float(cfg["corr_reversal_delta"])

    if returns_matrix is None or returns_matrix.empty or window < 5:
        return []

    columns = list(returns_matrix.columns)[:max_assets]
    if len(columns) < 2:
        return []

    alerts: List[RiskAlert] = []
    for left, right in combinations(columns, 2):
        pair = returns_matrix[[left, right]].dropna()
        if len(pair) < window:
            continue
        # 任一资产在当前窗口内价格完全不动时，相关系数无定义，跳过该资产对
        if pair.tail(window).std(ddof=1).min() <= 0:
            continue
        current = float(pair.tail(window).corr().iloc[0, 1])
        baseline_slice = pair.tail(max(baseline_w, window))
        baseline = float(baseline_slice.corr().iloc[0, 1])
        if np.isnan(current) or np.isnan(baseline):
            continue
        delta = current - baseline
        reversed_to_negative = (
            baseline >= float(cfg["corr_pos_to_neg_base"])
            and current <= float(cfg["corr_pos_to_neg_now"])
        )
        reversed_to_high = (
            baseline <= float(cfg["corr_low_to_high_base"])
            and current >= float(cfg["corr_low_to_high_now"])
        )
        is_reversal = reversed_to_negative or reversed_to_high

        if is_reversal and abs(delta) >= reversal_delta:
            severity, threshold = "red", reversal_delta
        elif abs(delta) >= deviation_delta:
            severity, threshold = "yellow", deviation_delta
        else:
            continue

        alerts.append(RiskAlert(
            signal_type="corr_reversal",
            severity=severity,
            trigger_value=round(current, 6),
            threshold=float(threshold),
            window_pair={"window": window, "baseline_window": baseline_w},
            asset_codes=[str(left), str(right)],
            detail={
                "current_corr": round(current, 6),
                "baseline_corr": round(baseline, 6),
                "delta": round(delta, 6),
                "reversal": "pos_to_neg" if reversed_to_negative else (
                    "low_to_high" if reversed_to_high else "none"
                ),
            },
        ))

    alerts.sort(key=lambda a: (SEVERITY_ORDER.get(a.severity, 9), -abs(a.detail.get("delta", 0.0))))
    return alerts


def build_returns_matrix(
    prices: pd.DataFrame,
    asset_codes: Sequence[str],
    window: int,
) -> pd.DataFrame:
    """从价格矩阵构建指定资产的近 ``window`` 日收益矩阵。

    Args:
        prices: 价格 DataFrame（index=交易日 Timestamp 升序，columns=资产代码）。
        asset_codes: 需要的资产，按权重降序（决定列顺序与后续两两配对优先级）。
        window: 需要的交易日数量（收益率序列长度 = window，价格行数 = window + 1）。

    Returns:
        日收益矩阵；缺失资产列被跳过；不足 2 行时返回空 DataFrame。
    """
    if prices is None or prices.empty or not asset_codes:
        return pd.DataFrame()
    cols = [c for c in asset_codes if c in prices.columns]
    if not cols:
        return pd.DataFrame()
    tail_rows = max(int(window) + 1, 2)
    sub = prices[cols].tail(tail_rows)
    # 全空列视为无行情，剔除后不算收益（避免整列 NaN 参与相关矩阵）
    sub = sub.dropna(axis=1, how="all")
    if sub.empty or len(sub) < 2:
        return pd.DataFrame()
    return sub.pct_change().iloc[1:]
