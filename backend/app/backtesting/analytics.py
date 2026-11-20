"""回测绩效分析 — 净值指标委托统一内核，此处只做「快照 → 净值/曲线/持仓」的形态转换.

绩效口径（年化因子、无风险利率、回撤算法、夏普定义）全部由
`app.analysis.performance` 定义，本模块不得自行实现任何指标公式。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

import pandas as pd
from loguru import logger

from app.analysis.performance import (
    DEFAULT_RISK_FREE_RATE,
    PerformanceMetrics,
    compute_drawdown_series,
    compute_performance,
)
from app.backtesting.types import PortfolioSnapshot, Trade


@dataclass
class PerformanceSummary:
    """回测绩效汇总指标.

    仅承载计算结果数据，不包含逻辑。数值口径见 `app.analysis.performance`。
    """

    # 收益类
    total_return: float              # 总收益率
    annual_return: float             # 年化收益率

    # 波动 & 风险类
    volatility: float                # 日度波动率
    annual_volatility: float         # 年化波动率
    max_drawdown: float              # 最大回撤（与 equity_curve 的回撤曲线同源）

    # 比率类
    sharpe_ratio: float              # 夏普比率
    calmar_ratio: float              # 卡玛比率（年化收益率 / |最大回撤|）
    return_drawdown_ratio: float     # 收益回撤比（总收益 / |最大回撤|）

    # 交易统计
    win_rate: float                  # 调仓周期胜率（净值上涨的调仓周期占比）

    # 365 口径（自然日/年）——与 260 口径并存，累计收益/回撤/胜率不复制
    annual_return_365: float = 0.0
    annual_volatility_365: float = 0.0
    sharpe_ratio_365: float = 0.0
    calmar_ratio_365: float = 0.0

    # 交易成本统计（来自 trades，无成交记录时为 0）
    n_trades: int = 0                # 成交笔数
    total_commission: float = 0.0    # 累计手续费
    total_slippage: float = 0.0      # 累计滑点成本
    turnover: float = 0.0            # 累计换手额 / 期初净值（单边）

    # 数据质量告警：历史上这些异常被静默钳制，现在如实上报
    warnings: List[str] = field(default_factory=list)


def _summary_from_metrics(
    metrics: PerformanceMetrics,
    trade_stats: Optional[Dict[str, float]] = None,
) -> PerformanceSummary:
    """内核指标 + 交易统计 → 对外的 PerformanceSummary。"""
    stats = trade_stats or {}
    return PerformanceSummary(
        total_return=metrics.total_return,
        annual_return=metrics.annual_return,
        volatility=metrics.volatility,
        annual_volatility=metrics.annual_volatility,
        max_drawdown=metrics.max_drawdown,
        sharpe_ratio=metrics.sharpe_ratio,
        calmar_ratio=metrics.calmar_ratio,
        return_drawdown_ratio=metrics.return_drawdown_ratio,
        win_rate=metrics.win_rate,
        annual_return_365=metrics.annual_return_365,
        annual_volatility_365=metrics.annual_volatility_365,
        sharpe_ratio_365=metrics.sharpe_ratio_365,
        calmar_ratio_365=metrics.calmar_ratio_365,
        n_trades=int(stats.get("n_trades", 0)),
        total_commission=float(stats.get("total_commission", 0.0)),
        total_slippage=float(stats.get("total_slippage", 0.0)),
        turnover=float(stats.get("turnover", 0.0)),
        warnings=list(metrics.warnings),
    )


def _nav_from_snapshots(snapshots: List[PortfolioSnapshot]) -> pd.Series:
    """快照列表 → 净值序列（按时间升序，重复时间取最后一条）。"""
    if not snapshots:
        return pd.Series(dtype=float)
    df = pd.DataFrame(
        {
            "time": [s.time for s in snapshots],
            "total_value": [s.total_value for s in snapshots],
        }
    ).set_index("time").sort_index()
    return df["total_value"]


def _rebalance_dates(snapshots: List[PortfolioSnapshot]) -> List[pd.Timestamp]:
    """提取调仓日，供胜率计算使用。"""
    return [s.time for s in snapshots if s.is_rebalance_day]


def _compute_trade_stats(
    trades: Optional[List[Trade]],
    initial_value: float,
) -> Dict[str, float]:
    """汇总成交记录 → 笔数 / 手续费 / 滑点 / 换手率.

    换手额按单边成交金额累加，除以期初净值。之前这些数据被生成后完全丢弃，
    导致回测无法回答「成本吃掉了多少收益」。
    """
    if not trades:
        return {"n_trades": 0, "total_commission": 0.0,
                "total_slippage": 0.0, "turnover": 0.0}

    total_commission = 0.0
    total_slippage = 0.0
    gross_amount = 0.0
    for t in trades:
        total_commission += float(getattr(t, "commission", 0.0) or 0.0)
        total_slippage += float(getattr(t, "slippage_cost", 0.0) or 0.0)
        gross_amount += abs(float(getattr(t, "quantity", 0.0) or 0.0)) * float(
            getattr(t, "price", 0.0) or 0.0
        )

    turnover = gross_amount / initial_value if initial_value > 1e-12 else 0.0
    return {
        "n_trades": len(trades),
        "total_commission": total_commission,
        "total_slippage": total_slippage,
        "turnover": turnover,
    }


class PerformanceAnalyzer:
    """绩效分析模块.

    职责限定为「回测产物形态转换」：把引擎输出的快照/成交记录整理成净值序列，
    交给 `app.analysis.performance` 计算指标，再组装成曲线、持仓回溯等展示结构。
    所有指标公式均不在此实现。
    """

    def __init__(self, risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> None:
        self._rf = risk_free_rate

    def from_results(
        self,
        snapshots: List[PortfolioSnapshot],
        trades: List[Trade] | None = None,
        max_leverage: Optional[float] = None,
    ) -> PerformanceSummary:
        """根据组合快照和交易记录计算绩效指标.

        - snapshots: BacktestEngine 生成的组合快照列表
        - trades:    成交记录，用于统计换手与交易成本
        - max_leverage: 保留参数（历史上用于异常净值填充阈值，现已改为如实上报告警，
          不再影响任何数值）
        """
        nav = _nav_from_snapshots(snapshots)
        metrics = compute_performance(
            nav,
            risk_free_rate=self._rf,
            rebalance_dates=_rebalance_dates(snapshots),
        )
        initial_value = float(nav.iloc[0]) if not nav.empty else 0.0
        summary = _summary_from_metrics(metrics, _compute_trade_stats(trades, initial_value))

        if summary.warnings:
            logger.warning(
                f"[PerformanceAnalyzer] 数据质量告警 {len(summary.warnings)} 条: "
                f"{'; '.join(summary.warnings)}"
            )
        logger.debug(
            f"[PerformanceAnalyzer] total_return={summary.total_return:.6f}, "
            f"n_periods={metrics.n_periods}, annual_return={summary.annual_return:.6f}, "
            f"annual_vol={summary.annual_volatility:.6f}, max_dd={summary.max_drawdown:.6f}"
        )
        return summary

    def create_model_result(
        self,
        snapshots: List[PortfolioSnapshot],
        trades: List[Trade] | None = None,
        asset_names: Dict[str, str] | None = None,
        initial_capital: float = 1000000.0,
        max_leverage: Optional[float] = None,
    ) -> Any:
        """将回测引擎结果转换为数据库存储模型 ModelBacktestResult.

        净值曲线、回撤曲线与汇总指标全部基于同一条净值序列，
        保证 `max_drawdown == min(equity_curve[].drawdown)`。
        """
        from app.models.strategy_model import (
            BacktestResult, EquityPoint, ReturnPoint,
            PositionRecord, AssetPosition, WeightChangePoint
        )

        summary = self.from_results(snapshots, trades, max_leverage=max_leverage)

        nav = _nav_from_snapshots(snapshots)
        initial_val = float(nav.iloc[0]) if not nav.empty else initial_capital
        if initial_val == 0:
            initial_val = initial_capital or 1.0

        # 曲线与指标同源：回撤取自统一内核，日收益取自同一条净值序列
        drawdown_series = compute_drawdown_series(nav)
        daily_returns = nav.pct_change(fill_method=None).fillna(0.0)

        equity_curve = [
            EquityPoint(
                date=s.time,
                value=s.total_value,
                unit_value=s.total_value / initial_val,
                cumulative_return=s.total_value / initial_val - 1,
                portfolio_volatility=getattr(s, "portfolio_volatility", None),
                drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0,
            )
            for i, s in enumerate(snapshots)
        ]

        return_curve = [
            ReturnPoint(
                date=s.time,
                daily_return=float(daily_returns.iloc[i]) if i < len(daily_returns) else 0.0,
                cumulative_return=s.total_value / initial_val - 1,
            )
            for i, s in enumerate(snapshots)
        ]

        # 持仓记录与权重变化只记录调仓日
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
                        market_value=s.total_value * weight,
                    )
                    for code, weight in s.weights.items()
                ],
            )
            for s in snapshots if s.is_rebalance_day
        ]

        weight_changes = [
            WeightChangePoint(
                date=s.time.strftime('%Y-%m-%d'),
                weights=s.weights,
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
            annual_return_365=summary.annual_return_365,
            annual_volatility_365=summary.annual_volatility_365,
            sharpe_ratio_365=summary.sharpe_ratio_365,
            calmar_ratio_365=summary.calmar_ratio_365,
            latest_unit_value=equity_curve[-1].unit_value if equity_curve else 1.0,
            win_rate=summary.win_rate,
            equity_curve=equity_curve,
            return_curve=return_curve,
            positions=positions_record,
            weight_changes=weight_changes,
            asset_names=asset_names,
        )

    @staticmethod
    def build_nav_and_drawdown_series(
        snapshots: List[PortfolioSnapshot],
    ) -> pd.DataFrame:
        """从快照构建净值及回撤走势序列，便于前端/可视化使用.

        返回 DataFrame:
            index: time
            columns:
                - nav: 累计净值（以首日为 1）
                - drawdown: 回撤（负值），与绩效指标的 max_drawdown 同源
        """
        nav_raw = _nav_from_snapshots(snapshots)
        if nav_raw.empty:
            return pd.DataFrame(columns=["nav", "drawdown"])

        drawdown = compute_drawdown_series(nav_raw)
        first = float(nav_raw.iloc[0])
        nav = nav_raw / first if first > 1e-12 else nav_raw
        return pd.DataFrame({"nav": nav, "drawdown": drawdown})

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


def compute_paused_metrics(
    snapshots: list,
    trades: list = None,
    max_leverage: Optional[float] = None,
) -> Dict[str, Any]:
    """根据至暂停日的快照计算当前绩效指标，供交互对话框展示.

    兼容两种输入：PortfolioSnapshot 对象列表，或快照 dict 列表（自动转换）。
    输入为空时返回占位 dict；输入格式非法时抛出异常，由调用方处理——
    静默吞掉异常只会让前端显示空白且无从排查。
    """
    placeholder = {
        "total_return": None,
        "annual_return": None,
        "volatility": None,
        "max_drawdown": None,
        "sharpe_ratio": None,
        "calmar_ratio": None,
        "current_nav": None,
        "initial_nav": None,
        "warnings": [],
    }
    if not snapshots:
        return placeholder

    if hasattr(snapshots[0], "total_value") and hasattr(snapshots[0], "is_rebalance_day"):
        snap_list = snapshots
    else:
        snap_list = [
            PortfolioSnapshot(
                time=pd.Timestamp(x["time"]) if not isinstance(x.get("time"), pd.Timestamp) else x["time"],
                total_value=float(x.get("total_value", 0)),
                cash=float(x.get("cash", 0)),
                holdings_value=float(x.get("holdings_value", 0)),
                weights=x.get("weights") or {},
                is_rebalance_day=bool(x.get("is_rebalance_day", False)),
                rebalance_type=x.get("rebalance_type"),
                rebalance_reason=x.get("rebalance_reason"),
                portfolio_volatility=x.get("portfolio_volatility"),
                monitoring_metrics=x.get("monitoring_metrics", {}),
            )
            for x in snapshots
        ]

    analyzer = PerformanceAnalyzer()
    perf = analyzer.from_results(snap_list, trades or [], max_leverage=max_leverage)
    return {
        "total_return": perf.total_return,
        "annual_return": perf.annual_return,
        "volatility": perf.annual_volatility,
        "max_drawdown": perf.max_drawdown,
        "sharpe_ratio": perf.sharpe_ratio,
        "calmar_ratio": perf.calmar_ratio,
        "current_nav": float(snap_list[-1].total_value),
        "initial_nav": float(snap_list[0].total_value),
        "warnings": perf.warnings,
    }
