"""
确定性指标计算工具 — compute_metrics

100% 通过 Python 公式函数计算资产关键风险收益指标，
不依赖 LLM 推理，结果确定性可复现。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.chart_labels import batch_asset_display_labels
from app.agent.tools.data_analyze_tool import (
    _fetch_price_matrix,
    _build_gfm_table,
    _safe_float,
)
from app.analysis.formulas import (
    calculate_simple_returns,
    calculate_cumulative_return,
    calculate_annualized_return,
    calculate_volatility,
    calculate_max_drawdown,
    calculate_sharpe_ratio,
    calculate_calmar_ratio,
)
from app.analysis.formulas.sortino_ratio import calculate_sortino_ratio
from app.analysis.formulas.information_ratio import calculate_information_ratio
from app.analysis.formulas.risk_measures import calculate_var, calculate_cvar


# 支持的指标 → 中文表头映射
_METRIC_ZH: dict[str, str] = {
    "return": "累计收益率",
    "annualized_return": "年化收益率",
    "volatility": "年化波动率",
    "sharpe": "夏普比率",
    "sortino": "索提诺比率",
    "max_drawdown": "最大回撤",
    "var_95": "VaR(95%)",
    "cvar_95": "CVaR(95%)",
    "info_ratio": "信息比率",
    "calmar": "Calmar比率",
}

SUPPORTED_METRICS = list(_METRIC_ZH.keys())


class ComputeMetricsTool(BaseTool):
    """确定性指标计算工具"""

    name = "compute_metrics"
    description = (
        "确定性指标计算工具，100%通过Python函数计算资产的关键风险收益指标。"
        "支持指标：累计收益率、年化收益率、年化波动率、夏普比率、索提诺比率、"
        "最大回撤、VaR(95%)、CVaR(95%)、信息比率、Calmar比率。"
        "返回标准 GFM Markdown 表格。"
    )
    category = "data"
    tags = ["计算", "指标", "风险", "收益", "确定性"]

    parameters = {
        "type": "object",
        "properties": {
            "asset_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "资产代码列表，如 ['SH000300', 'SPX']",
            },
            "start_date": {
                "type": "string",
                "description": "开始日期 YYYY-MM-DD",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期 YYYY-MM-DD",
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "需要计算的指标列表，可选值: "
                    "return, annualized_return, volatility, sharpe, sortino, "
                    "max_drawdown, var_95, cvar_95, info_ratio, calmar"
                ),
            },
            "benchmark_code": {
                "type": "string",
                "description": "基准代码（仅 info_ratio 需要），如 'SH000300'",
            },
        },
        "required": ["asset_codes", "metrics"],
    }

    async def execute(self, **kwargs: Any) -> dict:
        asset_codes: list[str] = kwargs.get("asset_codes", [])
        start_date: str | None = kwargs.get("start_date")
        end_date: str | None = kwargs.get("end_date")
        metrics: list[str] = kwargs.get("metrics", [])
        benchmark_code: str | None = kwargs.get("benchmark_code")

        # ── 参数校验 ──
        if not asset_codes:
            return ToolResult.error("请提供至少一个 asset_codes")
        if not metrics:
            return ToolResult.error("请提供至少一个 metrics 指标名称")

        # 校验指标名称
        invalid_metrics = [m for m in metrics if m not in SUPPORTED_METRICS]
        if invalid_metrics:
            return ToolResult.error(
                f"不支持的指标: {invalid_metrics}。"
                f"支持: {SUPPORTED_METRICS}"
            )

        # 如果需要 info_ratio 但没有 benchmark
        if "info_ratio" in metrics and not benchmark_code:
            return ToolResult.error(
                "计算 info_ratio（信息比率）需要提供 benchmark_code 参数"
            )

        # ── 获取价格数据 ──
        try:
            all_codes = list(asset_codes)
            if benchmark_code and benchmark_code not in all_codes:
                all_codes.append(benchmark_code)

            prices = await _fetch_price_matrix(all_codes, start_date, end_date)
            if prices.empty:
                _err = ToolResult.error(
                    f"未获取到价格数据，请检查资产代码和日期范围。"
                    f"资产: {asset_codes}, 日期: {start_date} ~ {end_date}"
                )
                return self.attach_lineage(
                    _err,
                    tables=["asset_prices", "assets"],
                    domains=["asset"],
                    fields={"asset_prices": ["asset_code", "date", "close"]},
                    records_returned=0,
                    query_operation="compute_metrics",
                    asset_codes=list(asset_codes),
                    no_data=True,
                )
        except Exception as e:
            logger.error("[ComputeMetrics] 获取价格数据失败: {}", e)
            _err = ToolResult.error(f"获取价格数据失败: {str(e)}")
            return self.attach_lineage(
                _err,
                tables=["asset_prices"],
                domains=["asset"],
                fields={"asset_prices": ["asset_code", "date", "close"]},
                records_returned=0,
                query_operation="compute_metrics",
                asset_codes=list(asset_codes),
                error_in_fetch=True,
            )

        # 检查缺失资产
        available_codes = [c for c in asset_codes if c in prices.columns]
        missing_codes = [c for c in asset_codes if c not in prices.columns]
        if not available_codes:
            return ToolResult.error(
                f"所有资产均无数据: {asset_codes}。数据库中可用列: {list(prices.columns)}"
            )

        # ── 计算指标 ──
        results: dict[str, dict[str, Any]] = {}
        benchmark_returns: pd.Series | None = None

        if benchmark_code and benchmark_code in prices.columns:
            benchmark_prices = prices[benchmark_code].dropna()
            if len(benchmark_prices) >= 2:
                benchmark_returns = calculate_simple_returns(benchmark_prices)

        for code in available_codes:
            price_series = prices[code].dropna()
            if len(price_series) < 2:
                results[code] = {m: None for m in metrics}
                continue

            returns = calculate_simple_returns(price_series)
            code_results: dict[str, Any] = {}

            for metric in metrics:
                try:
                    value = self._compute_single_metric(
                        metric, price_series, returns, benchmark_returns
                    )
                    code_results[metric] = _safe_float(value)
                except Exception as e:
                    logger.warning(
                        "[ComputeMetrics] 计算 {} 的 {} 失败: {}",
                        code, metric, e,
                    )
                    code_results[metric] = None

            results[code] = code_results

        # ── 构建 GFM 表格 ──
        label_map = await batch_asset_display_labels(available_codes)
        headers = ["资产"] + [_METRIC_ZH.get(m, m) for m in metrics]
        rows: list[list[str]] = []

        for code in available_codes:
            row = [label_map.get(code, code)]
            for metric in metrics:
                val = results[code].get(metric)
                row.append(self._format_metric_value(metric, val))
            rows.append(row)

        gfm_table = _build_gfm_table(headers, rows)

        # ── 构建 traceable_assets 元数据 ──
        traceable_assets = [
            {
                "code": code,
                "name": label_map.get(code, code).split(" (")[0],
                "has_kline": True,
            }
            for code in available_codes
        ]

        # ── 摘要 ──
        summary_parts = []
        for code in available_codes[:5]:
            parts = []
            r = results[code]
            if "annualized_return" in r and r["annualized_return"] is not None:
                parts.append(f"年化{r['annualized_return'] * 100:.1f}%")
            if "sharpe" in r and r["sharpe"] is not None:
                parts.append(f"夏普{r['sharpe']:.2f}")
            if parts:
                summary_parts.append(f"{label_map.get(code, code)}: {', '.join(parts)}")

        summary = "指标计算完成。" + "; ".join(summary_parts)
        if missing_codes:
            summary += f"\n⚠️ 以下资产无数据: {missing_codes}"

        result = ToolResult.success(
            data={
                "metrics": results,
                "gfm_table": gfm_table,
                "traceable_assets": traceable_assets,
            },
            summary=summary,
            data_shape="table",
            record_count=len(available_codes),
        )
        return self.attach_lineage(
            result,
            tables=["asset_prices", "assets"],
            domains=["asset"],
            fields={
                "asset_prices": ["asset_code", "date", "close"],
                "assets": ["code", "name"],
            },
            join_path="asset_prices.asset_code = assets.code",
            records_returned=len(available_codes),
            query_operation="compute_metrics",
            asset_codes=list(available_codes),
            metrics_computed=list(metrics) if isinstance(metrics, list) else [],
        )
    def _compute_single_metric(
        self,
        metric: str,
        prices: pd.Series,
        returns: pd.Series,
        benchmark_returns: pd.Series | None,
    ) -> float:
        """调用对应公式函数计算单个指标"""
        if metric == "return":
            return calculate_cumulative_return(prices)

        elif metric == "annualized_return":
            return calculate_annualized_return(prices)

        elif metric == "volatility":
            return calculate_volatility(returns, annualize=True)

        elif metric == "sharpe":
            return calculate_sharpe_ratio(returns)

        elif metric == "sortino":
            return calculate_sortino_ratio(returns)

        elif metric == "max_drawdown":
            return calculate_max_drawdown(prices)

        elif metric == "var_95":
            return calculate_var(returns, confidence_level=0.95)

        elif metric == "cvar_95":
            return calculate_cvar(returns, confidence_level=0.95)

        elif metric == "info_ratio":
            if benchmark_returns is None:
                return 0.0
            return calculate_information_ratio(returns, benchmark_returns)

        elif metric == "calmar":
            ann_ret = calculate_annualized_return(prices)
            mdd = calculate_max_drawdown(prices)
            return calculate_calmar_ratio(ann_ret, mdd)

        else:
            raise ValueError(f"未知指标: {metric}")

    @staticmethod
    def _format_metric_value(metric: str, value: float | None) -> str:
        """格式化指标值用于表格展示"""
        if value is None:
            return "N/A"

        # 百分比类指标
        if metric in ("return", "annualized_return", "volatility", "max_drawdown", "var_95", "cvar_95"):
            return f"{value * 100:.2f}%"
        # 比率类指标
        elif metric in ("sharpe", "sortino", "info_ratio", "calmar"):
            if abs(value) == float("inf"):
                return "∞" if value > 0 else "-∞"
            return f"{value:.3f}"
        else:
            return f"{value:.4f}"
