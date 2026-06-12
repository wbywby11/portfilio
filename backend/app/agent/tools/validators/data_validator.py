"""数据校验层 - 验证Agent工具取数和计算的真实性、准确性"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from app.config.database import Database


class DataValidator:
    """数据源与计算结果校验器"""

    TOLERANCE = 1e-6  # 数值比对容差

    # ─── 资产存在性校验 ─────────────────────────────────────

    async def validate_asset_exists(self, asset_code: str) -> dict:
        """验证资产在assets集合中存在且is_active=True"""
        try:
            db = Database.get_database()
            doc = await db["assets"].find_one(
                {"code": asset_code},
                {"code": 1, "name": 1, "is_active": 1},
            )
            if doc is None:
                return {"exists": False, "is_active": False, "name": None}
            return {
                "exists": True,
                "is_active": bool(doc.get("is_active", False)),
                "name": doc.get("name"),
            }
        except Exception as e:
            logger.warning("[DataValidator] validate_asset_exists failed: {}", e)
            return {"exists": False, "is_active": False, "name": None}

    # ─── 价格数据覆盖校验 ───────────────────────────────────

    async def validate_price_data(self, asset_code: str, start_date: str, end_date: str) -> dict:
        """验证日期范围内asset_prices集合有数据

        Args:
            asset_code: 资产代码
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
        """
        try:
            db = Database.get_database()
            query: dict = {"asset_code": asset_code}
            if start_date or end_date:
                date_filter = {}
                if start_date:
                    date_filter["$gte"] = start_date
                if end_date:
                    date_filter["$lte"] = end_date
                query["date"] = date_filter

            count = await db["asset_prices"].count_documents(query)
            if count == 0:
                return {"has_data": False, "count": 0, "date_range": {"first": None, "last": None}}

            first_doc = await db["asset_prices"].find_one(query, sort=[("date", 1)])
            last_doc = await db["asset_prices"].find_one(query, sort=[("date", -1)])

            return {
                "has_data": True,
                "count": count,
                "date_range": {
                    "first": str(first_doc.get("date", "")) if first_doc else None,
                    "last": str(last_doc.get("date", "")) if last_doc else None,
                },
            }
        except Exception as e:
            logger.warning("[DataValidator] validate_price_data failed: {}", e)
            return {"has_data": False, "count": 0, "date_range": {"first": None, "last": None}}

    # ─── 汇率数据覆盖度校验 ─────────────────────────────────

    async def validate_fx_coverage(
        self, start_date: str, end_date: str, currencies: list = None
    ) -> dict:
        """验证汇率数据覆盖度

        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            currencies: 需要校验的币种列表，如 ['USD', 'EUR']
        """
        try:
            db = Database.get_database()
            query: dict = {}
            if start_date or end_date:
                date_filter = {}
                if start_date:
                    date_filter["$gte"] = start_date
                if end_date:
                    date_filter["$lte"] = end_date
                query["date"] = date_filter

            total_count = await db["fx_rates"].count_documents(query)

            # 计算理论交易日数（简单估算：日历天数 * 5/7）
            try:
                sd = datetime.strptime(start_date, "%Y-%m-%d")
                ed = datetime.strptime(end_date, "%Y-%m-%d")
                calendar_days = (ed - sd).days + 1
                expected_days = max(1, int(calendar_days * 5 / 7))
            except (ValueError, TypeError):
                expected_days = total_count or 1

            coverage_rate = min(1.0, total_count / expected_days) if expected_days > 0 else 0.0

            # 检查缺失的币种数据
            missing_dates: list[str] = []
            if currencies and total_count > 0:
                for ccy in currencies[:5]:  # 限制检查数量
                    ccy_query = {**query, ccy: {"$exists": False}}
                    miss_count = await db["fx_rates"].count_documents(ccy_query)
                    if miss_count > 0:
                        missing_dates.append(f"{ccy}: {miss_count}条缺失")

            status = "passed" if coverage_rate >= 0.95 else "warning"
            return {
                "coverage_rate": round(coverage_rate, 4),
                "missing_dates": missing_dates,
                "total_records": total_count,
                "status": status,
            }
        except Exception as e:
            logger.warning("[DataValidator] validate_fx_coverage failed: {}", e)
            return {"coverage_rate": 0.0, "missing_dates": [], "status": "warning"}

    # ─── 指标重算校验 ───────────────────────────────────────

    async def validate_metric(
        self,
        metric_name: str,
        reported_value: float,
        prices: pd.Series,
        **kwargs,
    ) -> dict:
        """用Python函数重新计算指标并与报告值比对

        Args:
            metric_name: 指标名称，支持 return, volatility, sharpe, max_drawdown,
                         cumulative_return, annualized_return
            reported_value: 工具报告的计算值
            prices: 价格序列
            **kwargs: 额外参数（如 risk_free_rate, frequency）
        """
        from app.analysis.formulas import (
            calculate_annualized_return,
            calculate_cumulative_return,
            calculate_max_drawdown,
            calculate_sharpe_ratio,
            calculate_simple_returns,
            calculate_volatility,
        )

        computed: Optional[float] = None
        risk_free_rate = kwargs.get("risk_free_rate", 0.02)
        frequency = kwargs.get("frequency", 252)

        try:
            if metric_name in ("annualized_return", "annual_return", "return"):
                computed = calculate_annualized_return(prices, freq_factor=frequency)
            elif metric_name in ("volatility", "annual_volatility"):
                returns = calculate_simple_returns(prices)
                computed = calculate_volatility(returns, annualize=True, freq_factor=frequency)
            elif metric_name in ("sharpe", "sharpe_ratio"):
                returns = calculate_simple_returns(prices)
                computed = calculate_sharpe_ratio(
                    returns, risk_free_rate=risk_free_rate, freq_factor=frequency
                )
            elif metric_name in ("max_drawdown",):
                computed = calculate_max_drawdown(prices)
            elif metric_name in ("cumulative_return",):
                computed = calculate_cumulative_return(prices)
            else:
                return {
                    "metric": metric_name,
                    "reported": reported_value,
                    "computed": None,
                    "diff": None,
                    "status": "unsupported",
                }
        except Exception as e:
            logger.warning("[DataValidator] validate_metric {} failed: {}", metric_name, e)
            return {
                "metric": metric_name,
                "reported": reported_value,
                "computed": None,
                "diff": None,
                "status": "error",
            }

        if computed is None:
            return {
                "metric": metric_name,
                "reported": reported_value,
                "computed": None,
                "diff": None,
                "status": "error",
            }

        diff = abs(reported_value - computed)
        status = "passed" if diff <= self.TOLERANCE else "corrected"

        return {
            "metric": metric_name,
            "reported": round(reported_value, 6),
            "computed": round(computed, 6),
            "diff": round(diff, 8),
            "status": status,
        }

    # ─── 完整校验结果构建 ───────────────────────────────────

    async def build_validation_result(
        self,
        asset_codes: list,
        start_date: str,
        end_date: str,
        computed_metrics: dict = None,
    ) -> dict:
        """构建完整的校验结果

        Args:
            asset_codes: 资产代码列表
            start_date: 开始日期
            end_date: 结束日期
            computed_metrics: 各资产已计算的指标校验结果
        """
        traceable_assets = []
        overall_status = "passed"

        for code in asset_codes:
            price_info = await self.validate_price_data(code, start_date, end_date)
            asset_info = await self.validate_asset_exists(code)
            traceable_assets.append({
                "code": code,
                "name": asset_info.get("name"),
                "data_points": price_info.get("count", 0),
            })
            if not price_info.get("has_data"):
                overall_status = "warning"

        # 如果有指标校验结果，检查是否有 corrected 状态
        if computed_metrics:
            for asset_metrics in computed_metrics.values():
                if isinstance(asset_metrics, list):
                    for m in asset_metrics:
                        if m.get("status") == "corrected":
                            overall_status = "corrected"
                            break
                elif isinstance(asset_metrics, dict):
                    if asset_metrics.get("status") == "corrected":
                        overall_status = "corrected"

        query_info = {"asset_codes": asset_codes}
        if start_date:
            query_info["start_date"] = start_date
        if end_date:
            query_info["end_date"] = end_date

        return {
            "data_source": {
                "collection": "asset_prices",
                "query": query_info,
                "count": sum(a["data_points"] for a in traceable_assets),
            },
            "validation_status": overall_status,
            "computed_by": "python_formula",
            "traceable_assets": traceable_assets,
        }
