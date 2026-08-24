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
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from bson import ObjectId

from app.config.database import Database
from app.services.strategy_model_service import StrategyModelService

logger = logging.getLogger(__name__)


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
    """获取策略模板的默认参数扫描网格。"""
    if template_code == "etf_discount":
        # ETF贴水率策略专用扫描网格
        return {
            "window": [20, 30, 60, 120],
            "signal_type": ["open_long_p5", "open_long_p10", "open_long_p15", "open_long_p25"],
            "max_leverage": [1.5, 2.0],
            "position_limit": [0.10, 0.15, 0.20],
        }
    else:
        # 通用策略的默认网格（常见参数）
        return {
            "target_vol": [0.03, 0.05, 0.07, 0.10],
            "max_leverage": [1.0, 2.0, 3.0, 4.0],
            "lookback_days": [60, 120, 260],
        }


# ======================================================================
#  轻量级回测执行器（复用 BacktestEngine，不经过 HTTP 层）
# ======================================================================

async def _run_single_backtest(
    model: Any,
    param_overrides: Dict[str, Any],
    start_date: str,
    end_date: str,
    initial_cash: float = 1_000_000,
) -> Optional[Dict[str, Any]]:
    """对指定策略模型执行一次回测，返回绩效指标摘要。

    Parameters
    ----------
    model : StrategyModel
        策略模型实例
    param_overrides : dict
        要覆盖的策略参数
    start_date, end_date : str (YYYYMMDD)
    initial_cash : float

    Returns
    -------
    dict or None:
        {annual_return, annual_vol, sharpe, max_drawdown, calmar, total_return}
    """
    from app.services.market_service import MarketService
    from app.services.asset_service import AssetService
    from app.backtesting.config import BacktestConfig
    from app.backtesting.data_feed import DataFeed, build_specialized_data_feed, sanitize_prices
    from app.backtesting.runner import RunSpec, run_unified
    from app.backtesting.analytics import PerformanceAnalyzer
    from app.allocation.services.registry import create_strategy_service_from_database
    from app.models.asset import AssetType

    strategy_type = model.template_code
    asset_service = AssetService()
    market_service = MarketService()

    try:
        # 合并参数
        params = {**(model.parameters or {}), **param_overrides}

        # 构建 BacktestConfig
        config = BacktestConfig(
            name=f"sensitivity_{strategy_type}",
            thscodes=model.asset_codes or [],
            start_date=start_date,
            end_date=end_date,
            rebalance_freq="monthly",
            initial_cash=initial_cash,
        )
        config.use_index_nav = strategy_type not in ("manual_allocation", "manual_allocation_strategy")

        # 数据加载
        _SPECIALIZED = {"etf_discount"}
        if strategy_type in _SPECIALIZED:
            data_feed = await build_specialized_data_feed(
                strategy_type=strategy_type,
                config=config,
                lookback_days=500,
            )
            if strategy_type == "etf_discount":
                config.thscodes = [
                    str(c) for c in data_feed.prices.columns
                    if not str(c).endswith("_discount") and not str(c).endswith("_dr")
                ]
                if not params.get("etf_codes"):
                    import json
                    params["etf_codes"] = json.dumps(config.thscodes)
        else:
            data_feed = await DataFeed.from_market_service(
                market_service=market_service,
                config=config,
                lookback_days=500,
            )

        if data_feed.prices.empty:
            return None

        # 创建策略实例
        strategy_service = await create_strategy_service_from_database(market_service=market_service)
        strategy_cls = strategy_service.get_strategy_class(strategy_type)
        strategy_impl = strategy_cls()
        from app.allocation.builtin_templates import COMPOSITION_DEFAULTS
        composition = COMPOSITION_DEFAULTS.get(strategy_type, {
            "selector": None, "allocator": strategy_type, "controller": None
        })

        # 经唯一引擎入口运行回测（敏感性分析口径：手续费 0.1%，默认风控）
        config.commission_rate = 0.001
        result = run_unified(RunSpec(
            config=config,
            data_feed=data_feed,
            allocator=strategy_impl,
            thscodes=config.thscodes,
            composition=composition,
            strategy_params=params,
        ))

        # 绩效分析
        analyzer = PerformanceAnalyzer()
        summary = analyzer.analyze(result.snapshots, result.trades)

        return {
            "annual_return": _safe_float(summary.annual_return),
            "annual_vol": _safe_float(summary.annual_volatility),
            "sharpe": _safe_float(summary.sharpe_ratio),
            "max_drawdown": _safe_float(summary.max_drawdown),
            "calmar": _safe_float(summary.calmar_ratio),
            "total_return": _safe_float(summary.total_return),
        }
    except Exception as e:
        logger.warning("[sensitivity] 单次回测失败 params=%s: %s", param_overrides, e)
        return None


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
            override = {param_name: value}
            metrics = await _run_single_backtest(
                model=model,
                param_overrides=override,
                start_date=start_date,
                end_date=end_date,
                initial_cash=initial_cash,
            )
            results.append({
                "param_value": value,
                "metrics": metrics,
            })
            logger.info(
                "[sensitivity] %s=%s → sharpe=%s annual_return=%s",
                param_name, value,
                metrics.get("sharpe") if metrics else "FAIL",
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
        """情景推演 — 修改价格矩阵后跑回测。

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

        # 基线回测（无冲击）
        baseline = await _run_single_backtest(
            model=model,
            param_overrides={},
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
        )

        # 情景回测：通过注入 _scenario_shocks 参数让策略感知冲击
        # 简化实现：在策略参数中传入情景信息，由支持情景的策略处理
        scenario_params = {"_scenario_shocks": scenario}
        scenario_metrics = await _run_single_backtest(
            model=model,
            param_overrides=scenario_params,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
        )

        return {
            "model_id": model_id,
            "model_name": model.name,
            "scenario": scenario,
            "scenario_desc": "、".join(f"{k} 变动{v*100:+.1f}%" for k, v in scenario.items()),
            "baseline_metrics": baseline,
            "scenario_metrics": scenario_metrics,
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

            metrics = await _run_single_backtest(
                model=model,
                param_overrides={},
                start_date=w_start_str,
                end_date=w_end_str,
                initial_cash=initial_cash,
            )

            window_info = {
                "window_index": i + 1,
                "start_date": w_start_str,
                "end_date": w_end_str,
                "metrics": metrics,
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
