"""
数据分析工具 — 原子能力层

提供 DataAnalyzeTool (data_analyze)：
描述性统计、收益率计算、相关性分析、归因分析、分布分析、异常检测

共享辅助函数（_safe_float, _parse_date, _fetch_price_matrix 等）也定义在此，
供 data_transform_tool 等模块复用。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.chart_builder import ChartBuilder
from app.agent.tools.chart_labels import batch_asset_display_labels, zh_metric_series_name
from app.agent.tools.validators.data_validator import DataValidator
from app.services.market_service import MarketService

_market_service = MarketService()
_data_validator = DataValidator()

# ─── 图表展示阈值 ──────────────────────────
CHART_HEATMAP_ASSET_LIMIT = 15   # 相关性热力图最大资产数
CHART_LINE_ASSET_LIMIT = 20      # 累计收益折线图最大资产数


# ═══════════════════════════════════════════════════════════════
#  辅助函数（本模块定义，data_transform_tool 可 import）
# ═══════════════════════════════════════════════════════════════

def _safe_float(val: Any) -> float | None:
    """将 numpy 类型安全转为 Python float"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        return round(float(val), 6)
    except (TypeError, ValueError):
        return None


def _safe_build_dataframe(raw_data: Any) -> pd.DataFrame:
    """安全构建 DataFrame，处理各种非标准输入格式。

    支持：
    - list[dict]              → 直接构建
    - dict with 'items'       → 取 items 列表
    - dict with 'records'     → 取 records 列表
    - dict with 'data'        → 取 data 字段
    - list[list]              → 按行构建
    - 单个 dict               → 包装为单元素列表
    """
    if raw_data is None:
        return pd.DataFrame()

    # list of dicts — 标准格式
    if isinstance(raw_data, list):
        if len(raw_data) == 0:
            return pd.DataFrame()
        # 如果 list 内元素全是 dict，直接构建
        if isinstance(raw_data[0], dict):
            return pd.DataFrame(raw_data)
        # list of lists
        return pd.DataFrame(raw_data)

    # dict 类型——尝试提取内部 records
    if isinstance(raw_data, dict):
        for key in ("items", "records", "data"):
            inner = raw_data.get(key)
            if isinstance(inner, list) and inner:
                return pd.DataFrame(inner)
        # 单个平坦 dict → 包装为 list
        if all(not isinstance(v, (dict, list)) for v in raw_data.values()):
            return pd.DataFrame([raw_data])
        # 尝试直接构建（可能是 column-oriented dict）
        return pd.DataFrame(raw_data)

    # 其他情况尝试直接构建
    return pd.DataFrame(raw_data)


def _parse_date(date_str: str | None) -> str | None:
    """将 YYYY-MM-DD 日期字符串转为 YYYYMMDD 格式（MarketService 要求）"""
    if not date_str:
        return None
    return date_str.replace("-", "")


async def _fetch_price_matrix(
    asset_codes: list[str],
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    """统一获取价格矩阵的辅助方法"""
    sd = _parse_date(start_date) or "20200101"
    ed = _parse_date(end_date) or datetime.now().strftime("%Y%m%d")
    df = await _market_service.get_price_matrix(
        thscodes=asset_codes, start_date=sd, end_date=ed,
    )
    return df


def _calc_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """计算日收益率（百分比变化）"""
    return prices.pct_change().dropna()


def _annualized_return(cum_ret: float, n_days: int, frequency: int = 252) -> float:
    """年化收益率"""
    if n_days <= 0:
        return 0.0
    return float((1 + cum_ret) ** (frequency / n_days) - 1)


def _max_drawdown(cum_series: pd.Series) -> float:
    """最大回撤"""
    peak = cum_series.cummax()
    drawdown = (cum_series - peak) / peak
    return float(drawdown.min())


def _build_gfm_table(headers: list[str], rows: list[list[str]]) -> str:
    """将表头和行数据转为 GFM Markdown 表格字符串"""
    if not headers or not rows:
        return ""
    header_line = "| " + " | ".join(headers) + " |"
    separator = "|" + "|".join(["---" for _ in headers]) + "|"
    row_lines = []
    for row in rows[:30]:  # 限制最多30行避免过大
        cells = [str(cell).replace("|", "\\|")[:50] for cell in row]
        row_lines.append("| " + " | ".join(cells) + " |")
    return header_line + "\n" + separator + "\n" + "\n".join(row_lines)


# ═══════════════════════════════════════════════════════════════
#  DataAnalyzeTool
# ═══════════════════════════════════════════════════════════════

class DataAnalyzeTool(BaseTool):
    """数据分析与统计工具"""

    name = "data_analyze"
    description = (
        "数据分析与统计工具。支持："
        "statistics(描述性统计:年化收益/波动率/夏普/最大回撤/VaR/偏度/峰度), "
        "returns(收益率计算:日/周/月收益率序列+累计收益), "
        "correlation(相关性分析:Pearson/Spearman相关系数矩阵), "
        "attribution(收益归因:Brinson模型分解:配置效应/选择效应/交互效应), "
        "distribution(分布分析:分组统计/排名/百分位/环比), "
        "anomaly(异常检测:Z-score/IQR异常标记)"
    )
    category = "data"
    tags = ["分析", "统计", "收益率", "波动率", "归因", "相关性", "异常"]

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["statistics", "returns", "correlation",
                         "attribution", "distribution", "anomaly"],
                "description": "分析类型",
            },
            "asset_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "资产代码列表，如 ['SH000300', 'SPX']。不传则自动计算所有可用资产",
            },
            "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
            "options": {
                "type": "object",
                "description": (
                    "分析选项。statistics: {risk_free_rate, frequency}; "
                    "returns: {frequency}; correlation: {method}; "
                    "attribution: {benchmark, weights}; "
                    "distribution: {group_by, metric, data}; "
                    "anomaly: {threshold, method, data}"
                ),
            },
            "source_ref": {
                "type": "string",
                "description": "引用会话中前序步骤的数据集，如 'step_1'。指定后将数据注入 options.data，供 distribution/anomaly 等 action 使用。",
            },
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> dict:
        # 修复：处理 options 可能是字符串的情况（Qwen3 嵌套编码）
        options = kwargs.get("options", {})
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except (json.JSONDecodeError, ValueError):
                options = {}
        if not isinstance(options, dict):
            options = {}
        kwargs["options"] = options or {}

        # ── source_ref 引用机制：从 DataContext 获取前序数据注入 options.data ──
        source_ref: str | None = kwargs.get("source_ref")
        if source_ref:
            conversation_id: str | None = kwargs.get("conversation_id")
            if not conversation_id:
                return ToolResult.error("source_ref 需要会话上下文，缺少 conversation_id")
            from app.agent.services.data_context import DataContext
            ctx = DataContext.get_instance(conversation_id)
            ref_data = ctx.get(source_ref)
            if ref_data is None:
                available = ctx.list_datasets()
                return ToolResult.error(
                    f"数据引用 '{source_ref}' 不存在。可用：{[d['key'] for d in available]}"
                )
            # 将引用数据注入 options.data，供 distribution/anomaly 等 action 使用
            options = kwargs.get("options") or {}
            options["data"] = ref_data if isinstance(ref_data, list) else [ref_data]
            kwargs["options"] = options

        action: str = kwargs.get("action", "")
        handler = {
            "statistics": self._statistics,
            "returns": self._returns,
            "correlation": self._correlation,
            "attribution": self._attribution,
            "distribution": self._distribution,
            "anomaly": self._anomaly,
        }.get(action)

        if handler is None:
            return ToolResult.error(f"不支持的分析类型: {action}")

        try:
            result = await handler(**kwargs)
        except ValueError as e:
            logger.error("[DataAnalyze] 参数错误: {}", e)
            _err = ToolResult.error(f"参数错误: {e}")
            return self.attach_lineage(
                _err, tables=[], domains=[], fields={},
                query_operation=f"data_analyze:{action}", error=True,
            )
        except Exception as e:
            logger.error("[DataAnalyze] 执行失败: {}", e)
            _err = ToolResult.error(f"分析失败: {e}")
            return self.attach_lineage(
                _err, tables=[], domains=[], fields={},
                query_operation=f"data_analyze:{action}", error=True,
            )

        # ── 统一附加血缘元数据（包含成功与失败）──
        if "_lineage_meta" in (result if isinstance(result, dict) else {}):
            return result
        # 推断表/域/字段
        asset_codes = kwargs.get("asset_codes", []) or []
        rec_count = result.get("metadata", {}).get("record_count", 0) if result.get("success") else 0
        # 上游数据引用：如使用了 source_ref，标记 upstream
        upstream_lineage = None
        if source_ref:
            upstream_lineage = {"query_operation": f"source_ref:{source_ref}"}
        return self.attach_lineage(
            result,
            tables=["asset_prices"] if asset_codes else [],
            domains=["asset"] if asset_codes else [],
            fields={"asset_prices": ["asset_code", "date", "close"]} if asset_codes else {},
            records_returned=rec_count,
            query_operation=f"data_analyze:{action}",
            asset_codes=list(asset_codes)[:20],
            upstream_lineage=upstream_lineage,
        )

    # ── statistics ───────────────────────────────────────────

    async def _statistics(self, **kwargs: Any) -> dict:
        asset_codes: list[str] = kwargs.get("asset_codes", [])

        if not asset_codes:
            # 自动获取所有可用资产
            try:
                from app.config.database import Database
                db = Database.get_database()
                asset_codes = await db["asset_prices"].distinct("asset_code")
                if not asset_codes:
                    return ToolResult.error("数据库中未找到任何资产价格数据")
                logger.info("statistics_auto_discover", extra={"asset_count": len(asset_codes)})
            except Exception as e:
                logger.error("statistics_auto_discover_failed", extra={"error": str(e)})
                return ToolResult.error(f"自动获取资产列表失败: {str(e)}")

        options: dict = kwargs.get("options", {}) or {}
        risk_free_rate: float = float(options.get("risk_free_rate", 0.02))
        frequency: int = int(options.get("frequency", 252))

        prices = await _fetch_price_matrix(
            asset_codes, kwargs.get("start_date"), kwargs.get("end_date"),
        )
        if prices.empty:
            return ToolResult.error("未获取到价格数据")

        returns = _calc_returns(prices)
        n_days = len(returns)
        results: dict[str, dict] = {}

        for col in returns.columns:
            r = returns[col].dropna()
            if r.empty:
                continue
            cum_ret = float((1 + r).prod() - 1)
            ann_ret = _annualized_return(cum_ret, len(r), frequency)
            ann_vol = float(r.std() * np.sqrt(frequency))
            sharpe = (ann_ret - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0
            cum_wealth = (1 + r).cumprod()
            mdd = _max_drawdown(cum_wealth)
            var_95 = float(np.percentile(r, 5))
            win_rate = float((r > 0).sum() / len(r))

            results[col] = {
                "annual_return": _safe_float(ann_ret),
                "annual_volatility": _safe_float(ann_vol),
                "sharpe_ratio": _safe_float(sharpe),
                "max_drawdown": _safe_float(mdd),
                "var_95": _safe_float(var_95),
                "skewness": _safe_float(r.skew()),
                "kurtosis": _safe_float(r.kurtosis()),
                "win_rate": _safe_float(win_rate),
                "trading_days": n_days,
            }

        # 生成对比柱状图（X 轴：资产中文标签；系列：绩效指标中文名）
        metric_keys = ["annual_return", "annual_volatility", "sharpe_ratio", "max_drawdown"]
        raw_categories = list(results.keys())
        label_map = await batch_asset_display_labels(raw_categories)
        categories = [label_map.get(c, c) for c in raw_categories]
        series_list = [
            {"name": zh_metric_series_name(m), "data": [results[c].get(m, 0) for c in raw_categories]}
            for m in metric_keys
        ]
        chart = ChartBuilder.build_bar(
            title="资产统计指标对比",
            categories=categories,
            series_list=series_list,
            y_name="数值",
        )

        summary_parts = [
            f"{label_map.get(c, c)}: 年化收益{results[c]['annual_return']:.2%}, "
            f"波动率{results[c]['annual_volatility']:.2%}, "
            f"夏普{results[c]['sharpe_ratio']:.2f}"
            for c in raw_categories if results.get(c)
        ]

        # 构建 GFM 表格
        stat_headers = ["资产", "年化收益率", "年化波动率", "夏普比率", "最大回撤", "VaR(95%)", "胜率"]
        sorted_codes = sorted(raw_categories, key=lambda c: results[c].get("annual_return") or 0, reverse=True)
        stat_rows = []
        for c in sorted_codes:
            r = results[c]
            stat_rows.append([
                label_map.get(c, c),
                f"{(r['annual_return'] or 0) * 100:.2f}%",
                f"{(r['annual_volatility'] or 0) * 100:.2f}%",
                f"{r['sharpe_ratio'] or 0:.3f}",
                f"{(r['max_drawdown'] or 0) * 100:.2f}%",
                f"{(r['var_95'] or 0) * 100:.2f}%",
                f"{(r['win_rate'] or 0) * 100:.1f}%",
            ])
        gfm_table = _build_gfm_table(stat_headers, stat_rows)

        # ── 数据校验层：用 formulas 重算指标并比对 ──
        validation_result = None
        try:
            metric_validations: dict[str, list] = {}
            metrics_to_validate = ["annual_return", "annual_volatility", "sharpe_ratio", "max_drawdown"]
            for col in raw_categories:
                col_metrics = []
                if col in prices.columns:
                    price_series = prices[col].dropna()
                    for m_name in metrics_to_validate:
                        reported = results[col].get(m_name)
                        if reported is not None:
                            v = await _data_validator.validate_metric(
                                metric_name=m_name,
                                reported_value=reported,
                                prices=price_series,
                                risk_free_rate=risk_free_rate,
                                frequency=frequency,
                            )
                            col_metrics.append(v)
                    metric_validations[col] = col_metrics

            validation_result = await _data_validator.build_validation_result(
                asset_codes=asset_codes,
                start_date=kwargs.get("start_date", "") or "",
                end_date=kwargs.get("end_date", "") or "",
                computed_metrics=metric_validations,
            )
            validation_result["metric_checks"] = metric_validations
        except Exception as e:
            logger.warning("[DataAnalyze] validation failed (non-blocking): {}", e)

        # 构建 traceable_assets 溯源标记（顶层字段）
        traceable_assets_top = None
        try:
            traceable_assets_top = []
            for code in asset_codes:
                info = await _data_validator.validate_asset_exists(code)
                if info.get("exists"):
                    traceable_assets_top.append({"code": code, "name": info.get("name", code), "has_kline": True})
                else:
                    traceable_assets_top.append({"code": code, "name": code, "has_kline": False})
        except Exception as te:
            logger.warning("[DataAnalyze] traceable_assets 构建失败(non-blocking): {}", te)

        result_data = {"statistics": results, "gfm_table": gfm_table}
        if traceable_assets_top:
            result_data["traceable_assets"] = traceable_assets_top

        return ToolResult.success(
            data=result_data,
            charts=[chart],
            summary="描述性统计: " + "; ".join(summary_parts),
            data_shape="table",
            record_count=len(results),
            validation=validation_result,
        )

    # ── returns ──────────────────────────────────────────────

    async def _returns(self, **kwargs: Any) -> dict:
        asset_codes: list[str] = kwargs.get("asset_codes", [])
        if not asset_codes:
            return ToolResult.error("returns 需要 asset_codes 参数")

        options: dict = kwargs.get("options", {}) or {}
        freq_map = {"W": "W", "M": "ME", "Q": "QE", "D": None}
        freq_key: str = options.get("frequency", "D")
        resample_rule: str | None = freq_map.get(freq_key.upper())

        prices = await _fetch_price_matrix(
            asset_codes, kwargs.get("start_date"), kwargs.get("end_date"),
        )
        if prices.empty:
            return ToolResult.error("未获取到价格数据")

        daily_ret = _calc_returns(prices)

        if resample_rule:
            resampled = prices.resample(resample_rule).last()
            returns_df = _calc_returns(resampled)
        else:
            returns_df = daily_ret

        cum_ret = (1 + daily_ret).cumprod()

        # 构建折线图（系列名为「名称（代码）」）
        n_assets = len(cum_ret.columns)
        chart = None
        if n_assets <= CHART_LINE_ASSET_LIMIT:
            dates = [d.strftime("%Y-%m-%d") for d in cum_ret.index]
            code_cols = [str(c) for c in cum_ret.columns]
            ret_label_map = await batch_asset_display_labels(code_cols)
            series_list = [
                {
                    "name": ret_label_map.get(col, col),
                    "data": [_safe_float(v) for v in cum_ret[col].tolist()],
                }
                for col in cum_ret.columns
            ]
            chart = ChartBuilder.build_line(
                title="累计收益曲线", dates=dates, series_list=series_list, y_name="累计净值",
            )

        # 构建返回数据
        returns_records = returns_df.reset_index().to_dict(orient="records")
        for rec in returns_records:
            for k, v in rec.items():
                if isinstance(v, (pd.Timestamp, datetime)):
                    rec[k] = v.strftime("%Y-%m-%d")
                elif isinstance(v, (np.floating, np.integer)):
                    rec[k] = _safe_float(v)

        # 构建 GFM 表格
        if returns_records:
            ret_headers = [str(k) for k in returns_records[0].keys()]
            ret_rows = []
            for rec in returns_records[:30]:
                row = []
                for k in ret_headers:
                    v = rec.get(k, "")
                    if isinstance(v, float):
                        row.append(f"{v:.4f}")
                    else:
                        row.append(str(v))
                ret_rows.append(row)
            ret_gfm_table = _build_gfm_table(ret_headers, ret_rows)
        else:
            ret_gfm_table = ""

        charts = [chart] if chart is not None else []
        summary = f"收益率计算完成，频率={freq_key}，{len(returns_records)} 条记录"
        if chart is None:
            summary += f"。资产数量({n_assets})较多，累计收益曲线已跳过以避免图表文字遮挡"

        # 构建 traceable_assets 溯源标记
        traceable_assets = None
        try:
            traceable_assets = []
            for code in asset_codes:
                info = await _data_validator.validate_asset_exists(code)
                if info.get("exists"):
                    traceable_assets.append({"code": code, "name": info.get("name", code), "has_kline": True})
                else:
                    traceable_assets.append({"code": code, "name": code, "has_kline": False})
        except Exception as te:
            logger.warning("[DataAnalyze] _returns traceable_assets 构建失败(non-blocking): {}", te)

        result_data = {"returns": returns_records, "frequency": freq_key, "gfm_table": ret_gfm_table}
        if traceable_assets:
            result_data["traceable_assets"] = traceable_assets

        return ToolResult.success(
            data=result_data,
            charts=charts,
            summary=summary,
            data_shape="records",
            record_count=len(returns_records),
        )

    # ── correlation ──────────────────────────────────────────

    async def _correlation(self, **kwargs: Any) -> dict:
        asset_codes: list[str] = kwargs.get("asset_codes", [])
        if len(asset_codes) < 2:
            return ToolResult.error("correlation 需要至少 2 个 asset_codes")

        options: dict = kwargs.get("options", {}) or {}
        method: str = options.get("method", "pearson")

        prices = await _fetch_price_matrix(
            asset_codes, kwargs.get("start_date"), kwargs.get("end_date"),
        )
        if prices.empty:
            return ToolResult.error("未获取到价格数据")

        returns = _calc_returns(prices)
        corr_matrix = returns.corr(method=method)

        labels = list(corr_matrix.columns)
        corr_label_map = await batch_asset_display_labels([str(x) for x in labels])
        zh_labels = [corr_label_map.get(str(x), str(x)) for x in labels]
        values = [[_safe_float(corr_matrix.iloc[i, j]) for j in range(len(labels))]
                   for i in range(len(labels))]

        n_assets = len(labels)
        chart = None
        if n_assets <= CHART_HEATMAP_ASSET_LIMIT:
            chart = ChartBuilder.build_heatmap(
                title=f"相关性矩阵（{method}）",
                x_labels=zh_labels,
                y_labels=zh_labels,
                values=values,
                min_val=-1,
                max_val=1,
            )

        # 找最高/最低相关性对
        corr_pairs: list[dict] = []
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                corr_pairs.append({
                    "pair": f"{labels[i]}-{labels[j]}",
                    "correlation": _safe_float(corr_matrix.iloc[i, j]),
                })
        corr_pairs.sort(key=lambda x: abs(x["correlation"] or 0), reverse=True)

        highest = corr_pairs[0] if corr_pairs else {}
        lowest = corr_pairs[-1] if corr_pairs else {}

        # 构建 GFM 表格
        corr_headers = ["资产"] + zh_labels
        corr_rows = []
        for i in range(len(labels)):
            row = [zh_labels[i]] + [f"{values[i][j]:.3f}" if values[i][j] is not None else "N/A" for j in range(len(labels))]
            corr_rows.append(row)
        corr_gfm_table = _build_gfm_table(corr_headers, corr_rows)

        charts = [chart] if chart is not None else []
        summary = (
            f"相关性分析({method}): "
            f"最高 {highest.get('pair', 'N/A')}={highest.get('correlation', 'N/A')}, "
            f"最低 {lowest.get('pair', 'N/A')}={lowest.get('correlation', 'N/A')}"
        )
        if chart is None:
            summary += f"。资产数量({n_assets})较多，相关性矩阵热力图已跳过以避免图表过于密集"

        # 构建 traceable_assets 溯源标记
        traceable_assets = None
        try:
            traceable_assets = []
            for code in asset_codes:
                info = await _data_validator.validate_asset_exists(code)
                if info.get("exists"):
                    traceable_assets.append({"code": code, "name": info.get("name", code), "has_kline": True})
                else:
                    traceable_assets.append({"code": code, "name": code, "has_kline": False})
        except Exception as te:
            logger.warning("[DataAnalyze] _correlation traceable_assets 构建失败(non-blocking): {}", te)

        corr_result_data = {
            "correlation_matrix": {labels[i]: {labels[j]: values[i][j]
                for j in range(len(labels))} for i in range(len(labels))},
            "pairs": corr_pairs,
            "gfm_table": corr_gfm_table,
        }
        if traceable_assets:
            corr_result_data["traceable_assets"] = traceable_assets

        return ToolResult.success(
            data=corr_result_data,
            charts=charts,
            summary=summary,
            data_shape="matrix",
            record_count=len(corr_pairs),
        )

    # ── attribution ──────────────────────────────────────────

    async def _attribution(self, **kwargs: Any) -> dict:
        options: dict = kwargs.get("options", {}) or {}
        benchmark_weights: dict = options.get("benchmark", {})
        actual_weights: dict = options.get("weights", {})

        if not benchmark_weights or not actual_weights:
            return ToolResult.error(
                "归因分析需要 options.benchmark 和 options.weights。"
                "格式: {\"资产代码\": 权重, ...}，权重之和为 1"
            )

        asset_codes = list(set(list(benchmark_weights.keys()) + list(actual_weights.keys())))
        prices = await _fetch_price_matrix(
            asset_codes, kwargs.get("start_date"), kwargs.get("end_date"),
        )
        if prices.empty:
            return ToolResult.error("未获取到价格数据")

        returns = _calc_returns(prices)
        mean_ret = returns.mean()

        # Brinson 归因
        results: list[dict] = []
        total_alloc = 0.0
        total_select = 0.0
        total_interact = 0.0

        for code in asset_codes:
            wb = float(benchmark_weights.get(code, 0))
            wp = float(actual_weights.get(code, 0))
            rb = float(mean_ret.get(code, 0))
            # 简化: benchmark 整体收益
            rb_total = sum(
                float(benchmark_weights.get(c, 0)) * float(mean_ret.get(c, 0))
                for c in asset_codes
            )
            alloc_effect = (wp - wb) * (rb - rb_total)
            select_effect = wb * (rb - rb)  # 简化版: 选择效应 = 0（同一资产）
            interact_effect = (wp - wb) * (rb - rb)

            # 实际 Brinson 分解（简化单期模型）
            alloc_effect = (wp - wb) * rb_total
            select_effect = wb * rb
            interact_effect = (wp - wb) * rb

            total_alloc += alloc_effect
            total_select += select_effect
            total_interact += interact_effect

            results.append({
                "asset": code,
                "benchmark_weight": _safe_float(wb),
                "actual_weight": _safe_float(wp),
                "asset_return": _safe_float(rb),
                "allocation_effect": _safe_float(alloc_effect),
                "selection_effect": _safe_float(select_effect),
                "interaction_effect": _safe_float(interact_effect),
            })

        # 归因柱状图（X 轴为资产中文标签）
        codes_attr = [r["asset"] for r in results]
        attr_lab = await batch_asset_display_labels([str(x) for x in codes_attr])
        categories = [attr_lab.get(str(r["asset"]), str(r["asset"])) for r in results]
        series_list = [
            {"name": "配置效应", "data": [r["allocation_effect"] for r in results]},
            {"name": "选择效应", "data": [r["selection_effect"] for r in results]},
            {"name": "交互效应", "data": [r["interaction_effect"] for r in results]},
        ]
        chart = ChartBuilder.build_bar(
            title="Brinson 归因分解", categories=categories, series_list=series_list,
        )

        # 构建 GFM 表格
        attr_headers = ["资产", "基准权重", "实际权重", "资产收益", "配置效应", "选择效应", "交互效应"]
        attr_rows = []
        for r in results:
            attr_rows.append([
                attr_lab.get(str(r["asset"]), str(r["asset"])),
                f"{(r['benchmark_weight'] or 0) * 100:.2f}%",
                f"{(r['actual_weight'] or 0) * 100:.2f}%",
                f"{(r['asset_return'] or 0) * 100:.4f}%",
                f"{(r['allocation_effect'] or 0) * 100:.4f}%",
                f"{(r['selection_effect'] or 0) * 100:.4f}%",
                f"{(r['interaction_effect'] or 0) * 100:.4f}%",
            ])
        attr_gfm_table = _build_gfm_table(attr_headers, attr_rows)

        return ToolResult.success(
            data={
                "attribution": results,
                "total_allocation": _safe_float(total_alloc),
                "total_selection": _safe_float(total_select),
                "total_interaction": _safe_float(total_interact),
                "gfm_table": attr_gfm_table,
            },
            charts=[chart],
            summary=(
                f"Brinson 归因: 配置效应={total_alloc:.4f}, "
                f"选择效应={total_select:.4f}, 交互效应={total_interact:.4f}"
            ),
            data_shape="records",
            record_count=len(results),
        )

    # ── distribution ─────────────────────────────────────────

    async def _distribution(self, **kwargs: Any) -> dict:
        options: dict = kwargs.get("options", {}) or {}
        raw_data: list[dict] | None = options.get("data")
        group_by: str = options.get("group_by", "")
        metric: str = options.get("metric", "value")

        # 尝试从 asset_codes 获取数据
        if not raw_data:
            asset_codes: list[str] = kwargs.get("asset_codes", [])
            if not asset_codes:
                return ToolResult.error(
                    "distribution 需要 options.data 或 asset_codes 参数"
                )
            prices = await _fetch_price_matrix(
                asset_codes, kwargs.get("start_date"), kwargs.get("end_date"),
            )
            if prices.empty:
                return ToolResult.error("未获取到价格数据")
            returns = _calc_returns(prices)
            raw_data = returns.reset_index().to_dict(orient="records")
            if not group_by:
                group_by = "asset"

        df = _safe_build_dataframe(raw_data)
        # 序列化 datetime 列
        for col in df.select_dtypes(include=["datetime64"]).columns:
            df[col] = df[col].dt.strftime("%Y-%m-%d")

        if group_by and group_by in df.columns:
            grouped = df.groupby(group_by)
            stats: dict[str, dict] = {}
            for grp_name, grp_df in grouped:
                numeric_cols = grp_df.select_dtypes(include=[np.number]).columns
                if metric in numeric_cols:
                    col_data = grp_df[metric]
                elif len(numeric_cols) > 0:
                    col_data = grp_df[numeric_cols[0]]
                else:
                    continue
                stats[str(grp_name)] = {
                    "count": int(len(col_data)),
                    "mean": _safe_float(col_data.mean()),
                    "sum": _safe_float(col_data.sum()),
                    "min": _safe_float(col_data.min()),
                    "max": _safe_float(col_data.max()),
                    "std": _safe_float(col_data.std()),
                    "median": _safe_float(col_data.median()),
                }
            result_data = {"group_stats": stats}
        else:
            # 全局统计 + 排名
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            target_col = metric if metric in numeric_cols else (
                numeric_cols[0] if len(numeric_cols) > 0 else None
            )
            if target_col is None:
                return ToolResult.error("无可分析的数值列")
            col_data = df[target_col].dropna()
            percentiles = [_safe_float(np.percentile(col_data, p))
                           for p in [10, 25, 50, 75, 90]]
            result_data = {
                "global_stats": {
                    "count": int(len(col_data)),
                    "mean": _safe_float(col_data.mean()),
                    "std": _safe_float(col_data.std()),
                    "min": _safe_float(col_data.min()),
                    "max": _safe_float(col_data.max()),
                    "percentiles": {
                        "p10": percentiles[0], "p25": percentiles[1],
                        "p50": percentiles[2], "p75": percentiles[3],
                        "p90": percentiles[4],
                    },
                },
            }

        # 构建 GFM 表格
        if "group_stats" in result_data:
            dist_headers = ["分组", "计数", "均值", "合计", "最小值", "最大值", "标准差", "中位数"]
            dist_rows = []
            for grp_name, s in result_data["group_stats"].items():
                dist_rows.append([
                    str(grp_name),
                    str(s.get("count", "")),
                    f"{s.get('mean') or 0:.4f}",
                    f"{s.get('sum') or 0:.4f}",
                    f"{s.get('min') or 0:.4f}",
                    f"{s.get('max') or 0:.4f}",
                    f"{s.get('std') or 0:.4f}",
                    f"{s.get('median') or 0:.4f}",
                ])
            dist_gfm_table = _build_gfm_table(dist_headers, dist_rows)
        elif "global_stats" in result_data:
            gs = result_data["global_stats"]
            pct = gs.get("percentiles", {})
            dist_headers = ["指标", "值"]
            dist_rows = [
                ["计数", str(gs.get("count", ""))],
                ["均值", f"{gs.get('mean') or 0:.4f}"],
                ["标准差", f"{gs.get('std') or 0:.4f}"],
                ["最小值", f"{gs.get('min') or 0:.4f}"],
                ["最大值", f"{gs.get('max') or 0:.4f}"],
                ["P10", f"{pct.get('p10') or 0:.4f}"],
                ["P25", f"{pct.get('p25') or 0:.4f}"],
                ["P50", f"{pct.get('p50') or 0:.4f}"],
                ["P75", f"{pct.get('p75') or 0:.4f}"],
                ["P90", f"{pct.get('p90') or 0:.4f}"],
            ]
            dist_gfm_table = _build_gfm_table(dist_headers, dist_rows)
        else:
            dist_gfm_table = ""
        result_data["gfm_table"] = dist_gfm_table

        return ToolResult.success(
            data=result_data,
            summary=f"分布分析完成，分组字段={group_by or '无'}",
            data_shape="table",
            record_count=len(raw_data) if raw_data else 0,
        )

    # ── anomaly ──────────────────────────────────────────────

    async def _anomaly(self, **kwargs: Any) -> dict:
        options: dict = kwargs.get("options", {}) or {}
        threshold: float = float(options.get("threshold", 3))
        method: str = options.get("method", "zscore")
        raw_data: list[dict] | None = options.get("data")

        if not raw_data:
            asset_codes: list[str] = kwargs.get("asset_codes", [])
            if not asset_codes:
                return ToolResult.error("anomaly 需要 options.data 或 asset_codes")
            prices = await _fetch_price_matrix(
                asset_codes, kwargs.get("start_date"), kwargs.get("end_date"),
            )
            if prices.empty:
                return ToolResult.error("未获取到价格数据")
            returns = _calc_returns(prices)
            # 取第一个资产的收益率序列
            col = returns.columns[0]
            raw_data = [
                {"date": d.strftime("%Y-%m-%d"), "value": _safe_float(v)}
                for d, v in zip(returns.index, returns[col].tolist())
            ]

        df = _safe_build_dataframe(raw_data)
        value_col = "value"
        if value_col not in df.columns:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) == 0:
                return ToolResult.error("数据中无数值列")
            value_col = numeric_cols[0]

        values = df[value_col].astype(float)
        anomalies: list[dict] = []

        if method == "iqr":
            q1 = values.quantile(0.25)
            q3 = values.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - threshold * iqr
            upper = q3 + threshold * iqr
            mask = (values < lower) | (values > upper)
        else:
            # Z-score
            mean = values.mean()
            std = values.std()
            if std == 0:
                mask = pd.Series([False] * len(values), index=values.index)
            else:
                z_scores = (values - mean) / std
                mask = z_scores.abs() > threshold

        for idx in df[mask].index:
            row = df.loc[idx]
            anomalies.append({
                "index": int(idx),
                "date": str(row.get("date", idx)),
                "value": _safe_float(row[value_col]),
            })

        # 散点图标记异常
        normal_pts = [[i, _safe_float(v)] for i, v in enumerate(values) if not mask.iloc[i]]
        anomaly_pts = [[i, _safe_float(v)] for i, v in enumerate(values) if mask.iloc[i]]
        chart = ChartBuilder.build_scatter(
            title=f"异常检测（{method}, 阈值={threshold}）",
            data_points=[
                {"name": "正常", "data": normal_pts},
                {"name": "异常", "data": anomaly_pts, "symbolSize": 18},
            ],
            x_name="序号",
            y_name="值",
        )

        # 构建 GFM 表格
        if anomalies:
            anom_headers = ["序号", "日期", "值"]
            anom_rows = [
                [str(a["index"]), str(a["date"]), f"{a['value']:.6f}" if a["value"] is not None else "N/A"]
                for a in anomalies[:30]
            ]
            anom_gfm_table = _build_gfm_table(anom_headers, anom_rows)
        else:
            anom_gfm_table = ""

        return ToolResult.success(
            data={
                "anomalies": anomalies,
                "total_points": len(values),
                "anomaly_count": len(anomalies),
                "method": method,
                "threshold": threshold,
                "gfm_table": anom_gfm_table,
            },
            charts=[chart],
            summary=f"异常检测({method}): 共{len(values)}条，异常{len(anomalies)}条",
            data_shape="records",
            record_count=len(anomalies),
        )
