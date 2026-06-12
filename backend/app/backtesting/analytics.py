from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Dict, Optional, Any

import pandas as pd
from loguru import logger

from app.backtesting.types import PortfolioSnapshot, Trade
from app.analysis.formulas.drawdown import calculate_drawdown_series

# 绩效指标合理范围上限，用于数据缺失/不一致时避免回撤、收益率、波动率、卡玛等极端值
METRIC_TOTAL_RETURN_MIN = -1.0
METRIC_TOTAL_RETURN_MAX = 10.0
METRIC_ANNUAL_VOLATILITY_MAX = 5.0
METRIC_MAX_DRAWDOWN_MIN = -1.0
METRIC_MAX_DRAWDOWN_MAX = 0.0
METRIC_RATIO_ABS_MAX = 50.0  # 夏普、卡玛等比率绝对值上限
# 单日净值涨跌幅超过此阈值视为异常，用前一日净值填充，避免异常数据导致年化收益/波动率失真
MAX_DAILY_NAV_CHANGE = 0.5  # 50%


def _safe_float(x: float, default: float = 0.0) -> float:
    """将 inf/nan 转为可 JSON 序列化的有限值，避免 'Out of range float values' 错误。"""
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return default
    return float(x)


def _clamp_performance_metric(
    value: float,
    name: str,
) -> float:
    """将绩效指标限制在合理范围内，避免缺失/不一致数据导致的极端值。"""
    v = _safe_float(value, 0.0)
    if name == "total_return" or name == "annual_return":
        return max(METRIC_TOTAL_RETURN_MIN, min(METRIC_TOTAL_RETURN_MAX, v))
    if name == "volatility" or name == "annual_volatility":
        return max(0.0, min(METRIC_ANNUAL_VOLATILITY_MAX, v))
    if name == "max_drawdown":
        return max(METRIC_MAX_DRAWDOWN_MIN, min(METRIC_MAX_DRAWDOWN_MAX, v))
    if name in ("sharpe_ratio", "calmar_ratio", "return_drawdown_ratio"):
        return max(-METRIC_RATIO_ABS_MAX, min(METRIC_RATIO_ABS_MAX, v))
    return v


@dataclass
class PerformanceSummary:
    """回测绩效汇总指标.

    仅承载计算结果数据，不包含逻辑。
    """

    # 收益类
    total_return: float              # 总收益率
    annual_return: float             # 年化收益率

    # 波动 & 风险类
    volatility: float                # 日度波动率
    annual_volatility: float         # 年化波动率
    max_drawdown: float              # 最大回撤

    # 比率类
    sharpe_ratio: float              # 夏普比率
    calmar_ratio: float              # 卡玛比率（年化收益率 / |最大回撤|）
    return_drawdown_ratio: float     # 收益回撤比（总收益 / |最大回撤|）

    # 交易统计
    win_rate: float                  # 胜率（盈利交易次数 / 总交易次数）


class PerformanceAnalyzer:
    """绩效分析模块.

    基于组合净值曲线和交易记录计算常见风险收益指标，
    并提供净值/回撤走势和持仓回溯所需的基础数据结构。
    """

    def __init__(self, risk_free_rate: float = 0.0) -> None:
        self._rf = risk_free_rate

    def from_results(
        self,
        snapshots: List[PortfolioSnapshot],
        trades: List[Trade] | None = None,
    ) -> PerformanceSummary:
        """根据组合快照和交易记录计算绩效指标.

        - snapshots: BacktestEngine 生成的组合快照列表
        - trades:    可选的成交记录列表，用于计算胜率等交易统计
        
        注意: 调仓日当天没有收益，在计算时需要排除
        """
        df = pd.DataFrame(
            {
                "time": [s.time for s in snapshots],
                "total_value": [s.total_value for s in snapshots],
                "is_rebalance_day": [s.is_rebalance_day for s in snapshots],
            }
        ).set_index("time").sort_index()

        # 1. 净值与收益率序列（清理异常值：缺失/不一致数据可能导致 inf/nan）
        total_values = pd.to_numeric(df["total_value"], errors="coerce")
        total_values = total_values.replace([float("inf"), float("-inf")], float("nan"))
        total_values = total_values.ffill().bfill()
        # 单日净值异常跳变：按最近日期净值填充，避免某日某资产/数据异常导致年化收益与波动率失真
        if len(total_values) >= 2:
            prev = total_values.shift(1)
            pct = total_values.pct_change()
            # 仅当前一日有效且当日涨跌幅超过阈值时视为异常，用前一日净值填充
            abnormal = (prev > 1e-12) & (pct.abs() > MAX_DAILY_NAV_CHANGE)
            if abnormal.any():
                total_values = total_values.where(~abnormal, prev)
                total_values = total_values.ffill().bfill()
        if total_values.isna().all() or len(total_values) < 2:
            return PerformanceSummary(
                total_return=0.0,
                annual_return=0.0,
                volatility=0.0,
                annual_volatility=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                calmar_ratio=0.0,
                return_drawdown_ratio=0.0,
                win_rate=0.0,
            )
        # 收益率序列，剔除 inf/nan
        returns = total_values.pct_change()
        returns = returns.replace([float("inf"), float("-inf")], float("nan")).dropna()

        # 注意: 不再将调仓日收益率强制置零。
        # 调仓日的 total_value 已由引擎按 T 日规则正确计算，
        # 如果在此处置零会导致 annual_return / annual_volatility / max_drawdown 等指标
        # 在净值变化集中于调仓日的场景下全部变为 0，与 total_return 不一致。

        if returns.empty:
            return PerformanceSummary(
                total_return=0.0,
                annual_return=0.0,
                volatility=0.0,
                annual_volatility=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                calmar_ratio=0.0,
                return_drawdown_ratio=0.0,
                win_rate=0.0,
            )

        periods_per_year = 252
        vol = returns.std()
        if not math.isfinite(float(vol)):
            vol = 0.0

        # 日度波动率 & 年化波动率（避免 inf/nan，并限制在合理范围）
        volatility = _safe_float(float(vol))
        annual_vol = _safe_float(float(vol * (periods_per_year ** 0.5)))
        annual_vol = _clamp_performance_metric(annual_vol, "annual_volatility")

        # 总收益率 & 年化收益率（start_value<=0 或异常时避免极端值）
        start_value = float(total_values.iloc[0])
        end_value = float(total_values.iloc[-1])
        total_return = (end_value / start_value - 1.0) if start_value > 1e-12 else 0.0
        total_return = _safe_float(total_return)
        total_return = _clamp_performance_metric(total_return, "total_return")

        # 年化收益率：使用 CAGR 公式（基于 total_return 和实际交易天数），
        # 与 total_return 保持一致，避免 mean_ret 被稀释或异常导致不一致。
        n_trading_days = len(returns)
        if n_trading_days > 0 and total_return > -1.0:
            annual_return = (1.0 + total_return) ** (periods_per_year / n_trading_days) - 1.0
        else:
            annual_return = 0.0
        annual_return = _safe_float(annual_return)
        annual_return = _clamp_performance_metric(annual_return, "annual_return")

        logger.debug(
            f"[PerformanceAnalyzer] total_return={total_return:.6f}, "
            f"n_trading_days={n_trading_days}, annual_return={annual_return:.6f}, "
            f"vol={float(vol):.6f}, annual_vol={annual_vol:.6f}"
        )

        # 夏普比率（年化波动率过小时不计算，并限制范围）
        sharpe = (annual_return - self._rf) / annual_vol if annual_vol > 1e-12 else 0.0
        sharpe = _safe_float(sharpe)
        sharpe = _clamp_performance_metric(sharpe, "sharpe_ratio")

        # 最大回撤（避免 peak=0 导致 inf，并限制在 [-1, 0]）
        cum = (1 + returns).cumprod()
        peak = cum.cummax()
        drawdown = (cum - peak) / peak.where(peak > 0, float("nan"))
        drawdown = drawdown.fillna(0.0).replace([float("inf"), float("-inf")], 0.0)
        max_dd = float(drawdown.min()) if not drawdown.empty else 0.0
        max_dd = _safe_float(max_dd)
        max_dd = _clamp_performance_metric(max_dd, "max_drawdown")

        # 卡玛比率（避免除零，并限制范围）
        calmar = annual_return / abs(max_dd) if max_dd < -1e-12 else 0.0
        calmar = _safe_float(calmar)
        calmar = _clamp_performance_metric(calmar, "calmar_ratio")

        # 收益回撤比（总收益率 / 最大回撤，限制范围）
        return_dd_ratio = total_return / abs(max_dd) if max_dd < -1e-12 else 0.0
        return_dd_ratio = _safe_float(return_dd_ratio)
        return_dd_ratio = _clamp_performance_metric(return_dd_ratio, "return_drawdown_ratio")

        # 胜率（基于 trades，如果提供的话）
        win_rate = 0.0
        if trades:
            # 这里简单用每笔交易的方向与价格变化近似衡量盈利与否，
            # 真实项目中可以基于单笔盈亏字段来统计。
            # 由于当前 Trade 结构未包含盈亏字段，此处仅保留接口和占位实现。
            total_trades = len(trades)
            if total_trades > 0:
                win_rate = 0.0

        return PerformanceSummary(
            total_return=total_return,
            annual_return=annual_return,
            volatility=volatility,
            annual_volatility=annual_vol,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            calmar_ratio=calmar,
            return_drawdown_ratio=return_dd_ratio,
            win_rate=win_rate,
        )

    def create_model_result(
        self,
        snapshots: List[PortfolioSnapshot],
        trades: List[Trade] | None = None,
        asset_names: Dict[str, str] | None = None,
        initial_capital: float = 1000000.0
    ) -> Any:
        """
        统一的业绩分析转换逻辑：将回测引擎结果转换为数据库存储模型 ModelBacktestResult
        """
        from app.models.strategy_model import (
            BacktestResult, EquityPoint, ReturnPoint, 
            PositionRecord, AssetPosition, WeightChangePoint
        )
        
        # 1. 计算基础指标
        summary = self.from_results(snapshots, trades)
        
        # 2. 转换曲线数据
        initial_val = snapshots[0].total_value if snapshots else initial_capital
        
        # 计算回撤序列
        total_values_series = pd.Series([s.total_value for s in snapshots])
        drawdown_series = calculate_drawdown_series(total_values_series) if not total_values_series.empty else pd.Series()
        
        equity_curve = [
            EquityPoint(
                date=s.time,
                value=s.total_value,
                unit_value=s.total_value / initial_val if initial_val != 0 else 1.0,
                cumulative_return=(s.total_value / initial_val - 1) if initial_val != 0 else 0.0,
                portfolio_volatility=getattr(s, "portfolio_volatility", None),
                drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0
            )
            for i, s in enumerate(snapshots)
        ]
        
        return_curve = [
            ReturnPoint(
                date=s.time,
                daily_return=0.0, # 暂时不计算日收益率
                cumulative_return=(s.total_value / initial_val - 1) if initial_val != 0 else 0.0
            )
            for s in snapshots
        ]
        
        # 3. 转换持仓记录 (只记录调仓日)
        positions_record = [
            PositionRecord(
                date=s.time,
                portfolio_value=s.total_value,
                cash=s.cash,
                rebalance_reason=getattr(s, "rebalance_reason", None),
                positions=[
                    AssetPosition(
                        asset_code=code,
                        asset_name=asset_names.get(code) if asset_names else code,
                        weight=weight,
                        market_value=s.total_value * weight
                    )
                    for code, weight in s.weights.items()
                ]
            )
            for s in snapshots if s.is_rebalance_day
        ]
        
        # 4. 转换权重变化记录
        weight_changes = [
            WeightChangePoint(
                date=s.time.strftime('%Y-%m-%d'),
                weights=s.weights
            )
            for s in snapshots if s.is_rebalance_day
        ]

        return BacktestResult(
            total_return=summary.total_return,
            annual_return=summary.annual_return,
            annual_volatility=summary.annual_volatility,
            sharpe_ratio=summary.sharpe_ratio,
            max_drawdown=summary.max_drawdown,
            calmar_ratio=summary.calmar_ratio,
            latest_unit_value=equity_curve[-1].unit_value if equity_curve else 1.0,
            win_rate=summary.win_rate,
            equity_curve=equity_curve,
            return_curve=return_curve,
            positions=positions_record,
            weight_changes=weight_changes,
            asset_names=asset_names
        )

    @staticmethod
    def build_nav_and_drawdown_series(
        snapshots: List[PortfolioSnapshot],
    ) -> pd.DataFrame:
        """从快照构建净值及回撤走势序列，便于前端/可视化使用.

        返回 DataFrame:
            index: time
            columns:
                - nav: 累计净值
                - drawdown: 回撤（负值）
        """
        df = pd.DataFrame(
            {
                "time": [s.time for s in snapshots],
                "total_value": [s.total_value for s in snapshots],
            }
        ).set_index("time").sort_index()

        if df.empty:
            return pd.DataFrame(columns=["nav", "drawdown"])

        total_val = pd.to_numeric(df["total_value"], errors="coerce").replace(
            [float("inf"), float("-inf")], float("nan")
        ).ffill().bfill()
        first = total_val.iloc[0]
        if first is None or (isinstance(first, float) and (first <= 0 or math.isnan(first))):
            return pd.DataFrame({"nav": total_val.replace(float("nan"), 1.0), "drawdown": 0.0}, index=df.index)
        nav = total_val / first
        peak = nav.cummax()
        drawdown = (nav - peak) / peak.where(peak > 0, float("nan"))
        drawdown = drawdown.fillna(0.0).replace([float("inf"), float("-inf")], 0.0)
        drawdown = drawdown.clip(lower=-1.0, upper=0.0)
        out = pd.DataFrame({"nav": nav, "drawdown": drawdown})
        return out

    @staticmethod
    def build_position_history(
        snapshots: List[PortfolioSnapshot],
    ) -> pd.DataFrame:
        """构建持仓详情回溯表.

        返回长表 DataFrame:
            columns: [time, thscode, weight]
        便于前端/分析模块按时间和资产维度查看持仓变化。
        """
        records = []
        for s in snapshots:
            for code, w in s.weights.items():
                records.append({"time": s.time, "thscode": code, "weight": w})

        if not records:
            return pd.DataFrame(columns=["time", "thscode", "weight"])

        df = pd.DataFrame(records)
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.sort_values(["time", "thscode"])
        return df
