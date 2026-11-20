# -*- coding: utf-8 -*-
"""
回测多维分析服务 — 参数敏感度 / 情景推演 / 鲁棒性检验

第5层策略验证的增强层，在 BacktestEngine 之上提供多维分析能力。

职责：
  1. sensitivity_analysis: 单参数扫描，输出热力图数据
  2. scenario_analysis: 修改价格矩阵后跑回测（情景推演）
  3. robustness_check: 滑动子区间回测
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from bson import ObjectId

from app.config.database import Database
from app.services.strategy_model_service import StrategyModelService

logger = logging.getLogger(__name__)

# 分析口径的基准交易成本：与既有敏感性/情景对比口径一致（手续费 0.1%）。
# 情景/敏感性结果必须包含成本，否则两组指标都不含成本，对比失去意义。
_ANALYSIS_COMMISSION_RATE = 0.001

# 单参数扫描取值上限：超过则等间距抽样（保端点），防止 step 过小导致笛卡尔积爆炸
_MAX_GRID_VALUES = 10

# get_param_grid 的进程内缓存：{canonical_code: {参数名: [取值...]}}
# schema 是策略类的静态声明，运行期不会变化，缓存不设 TTL。
_PARAM_GRID_CACHE: Dict[str, Dict[str, list]] = {}


def _safe_float(v, default=0.0) -> float:
    """将 NaN/inf 转为安全浮点数。"""
    if v is None:
        return default
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


# ======================================================================
#  参数扫描网格
# ======================================================================

def get_param_grid(template_code: str) -> Dict[str, list]:
    """获取策略模板真的参数扫描网格（按 get_param_schema 的声明推导）。

    口径（S17）：
        - 只抽「已声明搜索范围」的参数：数值/滑块类看 min_value+max_value
          （step 缺省时按 4 等分），选择类看 options；其余类型（text /
          checkbox / dict / boolean）不参与扫描；hidden 参数是固定值，不扫描；
        - 无任何声明 → 返回空 dict（不伪造通用 3 键网格）；
        - 单参数取值上限 10 个，超出时按等间距抽样并保端点，避免网格爆炸。

    结果按典型化后的 code 做进程内缓存（schema 是静态类属性，不会运行中变化）。
    """
    from app.allocation.strategy_manifest import canonical_code, resolve_class_safe

    code = canonical_code(str(template_code or "").strip())
    if not code:
        return {}
    cached = _PARAM_GRID_CACHE.get(code)
    if cached is not None:
        return {name: list(values) for name, values in cached.items()}

    grid: Dict[str, list] = {}
    strategy_cls = resolve_class_safe(code)
    if strategy_cls is not None:
        try:
            schema = strategy_cls.get_param_schema()
        except Exception as exc:  # noqa: BLE001 —— 单个策略 schema 异常不得拖垮网格接口
            logger.warning("[param_grid] %s get_param_schema 失败: %s", code, exc)
            schema = None
        for param in getattr(schema, "params", None) or []:
            if getattr(param, "hidden", False):
                continue
            values = _grid_values_for_param(param)
            if values:
                grid[param.name] = values

    _PARAM_GRID_CACHE[code] = {name: list(values) for name, values in grid.items()}
    return grid


def _grid_values_for_param(param: Any) -> list:
    """单个参数 → 扫描取值；未声明范围返回空列表。"""
    ptype = getattr(param, "type", None)
    if ptype == "select":
        return [opt[0] for opt in (getattr(param, "options", None) or []) if opt]
    if ptype not in ("number", "slider"):
        return []
    lo = getattr(param, "min_value", None)
    hi = getattr(param, "max_value", None)
    if lo is None or hi is None:
        return []
    lo, hi = float(lo), float(hi)
    if hi <= lo:
        return []
    step = getattr(param, "step", None)
    step = float(step) if step else (hi - lo) / 4.0
    if step <= 0:
        return []
    # 取值个数超过上限时按步长整数倍放大（保持落在声明步长网格上），
    # 而不是按区间等分——后者会产生 128.8888… 这类无意义的搜索取值。
    count = int((hi - lo) / step) + 1
    if count > _MAX_GRID_VALUES:
        factor = math.ceil((count - 1) / (_MAX_GRID_VALUES - 1))
        step = step * factor
    values: List[float] = []
    value = lo
    while value <= hi + step * 1e-9:
        values.append(round(value, 10))
        value += step
    # 上界可能落在最后一个步长之外，作为端点补上（不超过上限个数）
    if values and values[-1] < hi and len(values) < _MAX_GRID_VALUES:
        values.append(round(hi, 10))
    values = values[:_MAX_GRID_VALUES]
    # 数值型参数保留整数形态，避免 60 变 60.0
    if all(float(v).is_integer() for v in values):
        return [int(v) for v in values]
    return values


# ======================================================================
#  轻量级回测执行器（复用 BacktestEngine，不经过 HTTP 层）
# ======================================================================

@dataclass
class _AnalysisRunSpec:
    """一次分析回测的输入参数（集中封装，避免调用点参数散落）。"""

    model: Any
    start_date: str
    end_date: str
    initial_cash: float = 1_000_000
    param_overrides: Dict[str, Any] = field(default_factory=dict)
    scenario_shocks: Optional[Dict[str, float]] = None


@dataclass
class _SingleRunResult:
    """单次分析回测结果：成功带 metrics，失败带 error（不静默吞成 None）。"""

    metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def compute_metrics_from_result(result: Any) -> Dict[str, Any]:
    """引擎结果 → 分析指标摘要（指标与交易成本同源于统一绩效内核）。

    单独抽出为纯函数，便于用固定快照/成交构造的单元测试直接验证口径。

    Args:
        result: 引擎 BacktestResult，需含 snapshots 与 trades

    Returns:
        指标字典：年化收益/波动、夏普、回撤、Calmar、总收益，
        以及成交笔数/累计手续费/累计滑点/累计换手率

    Raises:
        ValueError: 快照为空，无法产出净值序列
    """
    from app.backtesting.analytics import PerformanceAnalyzer

    if not getattr(result, "snapshots", None):
        raise ValueError("回测结果快照为空，无法计算绩效指标")
    summary = PerformanceAnalyzer(risk_free_rate=0.02).from_results(
        result.snapshots, result.trades
    )
    return {
        "annual_return": _safe_float(summary.annual_return),
        "annual_vol": _safe_float(summary.annual_volatility),
        "sharpe": _safe_float(summary.sharpe_ratio),
        "max_drawdown": _safe_float(summary.max_drawdown),
        "calmar": _safe_float(summary.calmar_ratio),
        "total_return": _safe_float(summary.total_return),
        "annual_return_365": _safe_float(summary.annual_return_365),
        "annual_vol_365": _safe_float(summary.annual_volatility_365),
        "sharpe_365": _safe_float(summary.sharpe_ratio_365),
        "calmar_365": _safe_float(summary.calmar_ratio_365),
        "n_trades": int(summary.n_trades),
        "total_commission": _safe_float(summary.total_commission),
        "total_slippage": _safe_float(summary.total_slippage),
        "turnover": _safe_float(summary.turnover),
    }


async def _run_single_backtest(spec: _AnalysisRunSpec) -> _SingleRunResult:
    """对指定策略模型执行一次回测，返回指标摘要或失败原因。

    与单策略回测同源：strategy_params 由 build_backtest_params 组装，
    composition 由 build_strategy_composition 推导，调仓频率按
    force_month_end 校正，风控参数经 _build_risk_config 透传。
    scenario_shocks 非空时在 DataFeed 价格矩阵副本上施加冲击后再运行。

    Parameters
    ----------
    spec : _AnalysisRunSpec
        model / 日期区间 / 初始资金 / 参数覆盖 / 情景冲击

    Returns
    -------
    _SingleRunResult：metrics 与 error 二选一
    """
    from app.services.backtest_service import BacktestService
    from app.services.backtest_execution import _build_risk_config
    from app.services.market_service import MarketService
    from app.backtesting.composition_builder import build_strategy_composition
    from app.backtesting.config import BacktestConfig
    from app.backtesting.data_feed import DataFeed, resolve_lookback_days
    from app.backtesting.runner import RunSpec, run_unified
    from app.allocation.services.registry import create_strategy_service_from_database

    try:
        request_data = BacktestService(StrategyModelService()).to_backtest_request(
            model=spec.model,
            start_date=spec.start_date,
            end_date=spec.end_date,
            initial_cash=spec.initial_cash,
        )
        strategy_type = request_data["strategy_type"]
        thscodes = list(request_data["thscodes"] or [])
        params = {**request_data["strategy_params"], **spec.param_overrides}

        composition_spec = build_strategy_composition(strategy_type, thscodes, params)
        config = BacktestConfig(
            name=f"analysis_{strategy_type}",
            thscodes=thscodes,
            start_date=spec.start_date,
            end_date=spec.end_date,
            rebalance_freq=(
                "month_end" if composition_spec.force_month_end
                else request_data["rebalance_freq"]
            ),
            initial_cash=float(request_data["initial_cash"]),
            commission_rate=_ANALYSIS_COMMISSION_RATE,
        )

        market_service = MarketService()
        lookback_days = resolve_lookback_days(
            params, request_data.get("lookback_days", 500), strategy_type=strategy_type
        )
        data_feed = await DataFeed.from_market_service(
            market_service=market_service,
            config=config,
            lookback_days=lookback_days,
            strategy_type=strategy_type,
        )
        if data_feed.prices.empty:
            return _SingleRunResult(error="行情数据为空，无法执行回测")
        if spec.scenario_shocks:
            data_feed = data_feed.with_scenario_shocks(spec.scenario_shocks)

        strategy_service = await create_strategy_service_from_database(
            market_service=market_service
        )
        strategy_impl = strategy_service.get_strategy_class(strategy_type)()
        result = run_unified(RunSpec(
            config=config,
            data_feed=data_feed,
            allocator=strategy_impl,
            thscodes=thscodes,
            composition=composition_spec.composition,
            strategy_params=params,
            risk_config=_build_risk_config(params),
        ))
        return _SingleRunResult(metrics=compute_metrics_from_result(result))
    except Exception as exc:
        logger.exception(
            "[analysis] 单次回测失败 model=%s params=%s",
            getattr(spec.model, "id", None), spec.param_overrides,
        )
        return _SingleRunResult(error=f"{type(exc).__name__}: {exc}")


# ======================================================================
#  服务类
# ======================================================================

class BacktestAnalysisService:
    """回测多维分析服务"""

    def __init__(self):
        self._model_service = StrategyModelService()

    async def sensitivity_analysis(
        self,
        model_id: str,
        param_name: str,
        param_values: List[Any],
        start_date: str,
        end_date: str,
        initial_cash: float = 1_000_000,
    ) -> Dict[str, Any]:
        """参数敏感度分析 — 单参数扫描。

        Parameters
        ----------
        model_id : str
            策略模型 ID
        param_name : str
            要扫描的参数名
        param_values : list
            参数值列表
        start_date, end_date : str (YYYYMMDD)
        initial_cash : float

        Returns
        -------
        dict: {param_name, results: [{param_value, metrics}, ...]}
        """
        model = await self._model_service.get_model(model_id)
        if not model:
            raise ValueError(f"策略模型不存在: {model_id}")

        results = []
        for value in param_values:
            run = await _run_single_backtest(_AnalysisRunSpec(
                model=model,
                start_date=start_date,
                end_date=end_date,
                initial_cash=initial_cash,
                param_overrides={param_name: value},
            ))
            metrics = run.metrics
            results.append({
                "param_value": value,
                "metrics": metrics,
                "error": run.error,
            })
            logger.info(
                "[sensitivity] %s=%s → sharpe=%s annual_return=%s",
                param_name, value,
                metrics.get("sharpe") if metrics else f"FAIL({run.error})",
                metrics.get("annual_return") if metrics else "FAIL",
            )

        return {
            "model_id": model_id,
            "model_name": model.name,
            "template_code": model.template_code,
            "param_name": param_name,
            "results": results,
            "total_runs": len(param_values),
            "successful_runs": sum(1 for r in results if r["metrics"] is not None),
        }

    async def scenario_analysis(
        self,
        model_id: str,
        scenario: Dict[str, float],
        start_date: str,
        end_date: str,
        initial_cash: float = 1_000_000,
    ) -> Dict[str, Any]:
        """情景推演 — 在价格矩阵副本上施加冲击后重跑回测。

        Parameters
        ----------
        model_id : str
        scenario : dict
            {asset_code: shock_pct}，如 {"SH000300": -0.20} 表示该资产跌20%
        start_date, end_date : str (YYYYMMDD)
        initial_cash : float

        Returns
        -------
        dict: {baseline_metrics, scenario_metrics, scenario_desc}
        """
        model = await self._model_service.get_model(model_id)
        if not model:
            raise ValueError(f"策略模型不存在: {model_id}")
        if not scenario:
            raise ValueError("情景冲击为空：至少指定一个资产的冲击幅度")

        # 基线回测（无冲击）
        baseline = await _run_single_backtest(_AnalysisRunSpec(
            model=model,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
        ))

        # 情景回测：DataFeed 在回测前修改价格矩阵副本，策略真实承受冲击
        scenario_run = await _run_single_backtest(_AnalysisRunSpec(
            model=model,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            scenario_shocks=scenario,
        ))

        return {
            "model_id": model_id,
            "model_name": model.name,
            "scenario": scenario,
            "scenario_desc": "、".join(f"{k} 变动{v*100:+.1f}%" for k, v in scenario.items()),
            "baseline_metrics": baseline.metrics,
            "baseline_error": baseline.error,
            "scenario_metrics": scenario_run.metrics,
            "scenario_error": scenario_run.error,
        }

    async def robustness_check(
        self,
        model_id: str,
        n_windows: int = 5,
        start_date: str = None,
        end_date: str = None,
        initial_cash: float = 1_000_000,
    ) -> Dict[str, Any]:
        """时间窗口鲁棒性检验 — 滑动子区间回测。

        将回测区间切分为 n_windows 个子区间，每个独立跑回测，
        展示绩效指标的稳定性。

        Parameters
        ----------
        model_id : str
        n_windows : int
            子区间数量（默认5）
        start_date, end_date : str (YYYYMMDD)
            可选，不传则使用模型默认

        Returns
        -------
        dict: {windows: [{start, end, metrics}, ...], summary_stats}
        """
        model = await self._model_service.get_model(model_id)
        if not model:
            raise ValueError(f"策略模型不存在: {model_id}")

        # 确定总区间
        if not start_date or not end_date:
            # 使用最近一次回测的区间，或默认 3 年
            if model.latest_backtest_summary:
                start_date = model.latest_backtest_summary.get("start_date", "20210101")
                end_date = model.latest_backtest_summary.get("end_date", "20240101")
            else:
                start_date = "20210101"
                end_date = "20240101"

        start_ts = pd.Timestamp(start_date[:10])
        end_ts = pd.Timestamp(end_date[:10])
        total_days = (end_ts - start_ts).days

        if total_days < n_windows * 60:
            n_windows = max(2, total_days // 60)

        window_days = total_days // n_windows
        windows = []
        all_metrics = []

        for i in range(n_windows):
            w_start = start_ts + pd.Timedelta(days=i * window_days)
            w_end = start_ts + pd.Timedelta(days=(i + 1) * window_days - 1)
            if i == n_windows - 1:
                w_end = end_ts  # 最后一个窗口到末尾

            w_start_str = w_start.strftime("%Y%m%d")
            w_end_str = w_end.strftime("%Y%m%d")

            run = await _run_single_backtest(_AnalysisRunSpec(
                model=model,
                start_date=w_start_str,
                end_date=w_end_str,
                initial_cash=initial_cash,
            ))
            metrics = run.metrics

            window_info = {
                "window_index": i + 1,
                "start_date": w_start_str,
                "end_date": w_end_str,
                "metrics": metrics,
                "error": run.error,
            }
            windows.append(window_info)
            if metrics:
                all_metrics.append(metrics)

            logger.info(
                "[robustness] window %d/%d: %s ~ %s → sharpe=%s",
                i + 1, n_windows, w_start_str, w_end_str,
                metrics.get("sharpe") if metrics else "FAIL",
            )

        # 汇总统计
        summary_stats = {}
        if all_metrics:
            for key in ["annual_return", "annual_vol", "sharpe", "max_drawdown"]:
                values = [m[key] for m in all_metrics if m.get(key) is not None]
                if values:
                    summary_stats[key] = {
                        "mean": round(float(np.mean(values)), 4),
                        "std": round(float(np.std(values)), 4),
                        "min": round(float(np.min(values)), 4),
                        "max": round(float(np.max(values)), 4),
                        "median": round(float(np.median(values)), 4),
                    }

        return {
            "model_id": model_id,
            "model_name": model.name,
            "n_windows": n_windows,
            "windows": windows,
            "summary_stats": summary_stats,
            "total_runs": n_windows,
            "successful_runs": len(all_metrics),
        }
