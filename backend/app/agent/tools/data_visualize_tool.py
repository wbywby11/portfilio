"""
数据可视化工具 — 原子能力层

提供 DataVisualizeTool (data_visualize)：
根据数据和图表类型生成 ECharts 可视化
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.chart_builder import ChartBuilder
from app.services.asset_service import AssetService

# 模块级单例，避免每次调用创建新实例
_asset_service = AssetService()


class DataVisualizeTool(BaseTool):
    """数据可视化工具"""

    name = "data_visualize"
    description = (
        "数据可视化工具。根据数据和图表类型生成可视化："
        "折线图(line)、柱状图(bar)、饼图(pie)、散点图(scatter)、"
        "热力图(heatmap)、箱线图(box)、面积图(area)、仪表板(dashboard)"
    )
    category = "data"
    tags = ["可视化", "图表", "折线图", "柱状图", "饼图"]

    parameters = {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": ["line", "bar", "pie", "scatter", "heatmap",
                         "box", "area", "dashboard"],
                "description": "图表类型",
            },
            "data_source": {
                "type": "object",
                "description": "图表数据（来自前序工具结果或直接提供）",
            },
            "config": {
                "type": "object",
                "description": "图表配置: {title, x_axis, y_axis, group_by, series}",
            },
        },
        "required": ["chart_type", "data_source"],
    }

    async def execute(self, **kwargs: Any) -> dict:
        chart_type: str = kwargs.get("chart_type", "line")
        data_source = kwargs.get("data_source")
        config = kwargs.get("config", {})

        # 修复：处理 config 可能是字符串的情况（Qwen3 嵌套编码）
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (json.JSONDecodeError, ValueError):
                config = {}
        if not isinstance(config, dict):
            config = {}
        config = config or {}

        # 修复：处理 data_source 可能是字符串的情况
        if isinstance(data_source, str):
            try:
                data_source = json.loads(data_source)
            except (json.JSONDecodeError, ValueError):
                data_source = None

        if data_source is None:
            return ToolResult.error("data_source 不能为空")

        # ── asset_code 自动取数：从 MongoDB 查询价格并转为 records 格式 ──
        if isinstance(data_source, dict) and "asset_code" in data_source and "records" not in data_source:
            try:
                from datetime import datetime as _dt
                _ac = data_source["asset_code"]
                _sd = data_source.get("start_date")
                _ed = data_source.get("end_date")
                _start_dt = _dt.strptime(_sd, "%Y-%m-%d") if _sd else None
                _end_dt = _dt.strptime(_ed, "%Y-%m-%d") if _ed else None
                _prices = await _asset_service.get_asset_prices(
                    asset_code=_ac, start_date=_start_dt, end_date=_end_dt,
                )
                if _prices:
                    _records = [{"date": str(p.date)[:10], "close": p.close} for p in _prices]
                    data_source = {"records": _records}
                    logger.info("[DataVisualize] asset_code={} 自动取数 {} 条", _ac, len(_records))
                else:
                    logger.warning("[DataVisualize] asset_code={} 查询无数据，保持原 data_source", _ac)
            except Exception as _e:
                logger.warning("[DataVisualize] asset_code 自动取数失败 (fallback): {}", _e)

        title: str = config.get("title", "数据可视化")

        try:
            handler = {
                "line": self._build_line,
                "bar": self._build_bar,
                "pie": self._build_pie,
                "scatter": self._build_scatter,
                "heatmap": self._build_heatmap,
                "box": self._build_box,
                "area": self._build_area,
                "dashboard": self._build_dashboard,
            }.get(chart_type)

            if handler is None:
                return ToolResult.error(f"不支持的图表类型: {chart_type}")

            chart = handler(data_source, config, title)

            if chart_type == "dashboard" and isinstance(chart, list):
                _r = ToolResult.success(
                    data={"chart_count": len(chart)},
                    charts=chart,
                    summary=f"仪表板生成完成，包含 {len(chart)} 个子图",
                    data_shape="dashboard",
                    record_count=len(chart),
                )
                return self.attach_lineage(
                    _r,
                    tables=["asset_prices"] if (isinstance(data_source, dict) and data_source.get("asset_code")) else [],
                    domains=["asset"] if (isinstance(data_source, dict) and data_source.get("asset_code")) else [],
                    fields={},
                    records_returned=len(chart),
                    query_operation=f"data_visualize:{chart_type}",
                )

            _r = ToolResult.success(
                data={"chart_type": chart_type},
                charts=[chart],
                summary=f"已生成{chart_type}图表: {title}",
                data_shape="chart",
                record_count=1,
            )
            return self.attach_lineage(
                _r,
                tables=["asset_prices"] if (isinstance(data_source, dict) and data_source.get("asset_code")) else [],
                domains=["asset"] if (isinstance(data_source, dict) and data_source.get("asset_code")) else [],
                fields={},
                records_returned=1,
                query_operation=f"data_visualize:{chart_type}",
            )
        except ValueError as e:
            logger.error("[DataVisualize] 参数错误: {}", e)
            return ToolResult.error(f"参数错误: {e}")
        except Exception as e:
            logger.error("[DataVisualize] 执行失败: {}", e)
            return ToolResult.error(f"图表生成失败: {e}")

    # ── 数据提取辅助 ─────────────────────────────────────────

    @staticmethod
    def _extract_series(data_source: Any, config: dict) -> tuple[list[str], list[dict]]:
        """从 data_source 中提取 dates/categories 和 series_list"""
        # 直接提供 dates + series 结构
        if isinstance(data_source, dict):
            if "dates" in data_source and "series" in data_source:
                return data_source["dates"], data_source["series"]
            if "categories" in data_source and "series" in data_source:
                return data_source["categories"], data_source["series"]

        # records 格式 → 自动提取
        records = data_source
        if isinstance(data_source, dict) and "records" in data_source:
            records = data_source["records"]

        if not isinstance(records, list) or not records:
            return [], []

        df = pd.DataFrame(records)
        x_axis: str = config.get("x_axis", "")
        y_axis: str | list = config.get("y_axis", "")
        group_by: str = config.get("group_by", "")

        # 推断 X 轴
        if not x_axis:
            for candidate in ("date", "dates", "name", "category"):
                if candidate in df.columns:
                    x_axis = candidate
                    break
            if not x_axis and len(df.columns) > 0:
                x_axis = df.columns[0]

        categories = [str(v) for v in df[x_axis].tolist()] if x_axis in df.columns else []

        # 推断 Y 轴系列
        if y_axis:
            y_cols = [y_axis] if isinstance(y_axis, str) else y_axis
        elif group_by and group_by in df.columns:
            y_cols = [c for c in df.select_dtypes(include=[np.number]).columns
                      if c != x_axis]
        else:
            y_cols = [c for c in df.select_dtypes(include=[np.number]).columns
                      if c != x_axis]

        series_list: list[dict] = []
        if group_by and group_by in df.columns:
            for grp_name, grp_df in df.groupby(group_by):
                for col in y_cols:
                    if col in grp_df.columns:
                        series_list.append({
                            "name": f"{grp_name}-{col}",
                            "data": [float(v) if pd.notna(v) else None
                                     for v in grp_df[col].tolist()],
                        })
        else:
            for col in y_cols:
                if col in df.columns:
                    series_list.append({
                        "name": col,
                        "data": [float(v) if pd.notna(v) else None
                                 for v in df[col].tolist()],
                    })

        return categories, series_list

    # ── 各图表构建 ───────────────────────────────────────────

    def _build_line(self, data_source: Any, config: dict, title: str) -> dict:
        dates, series_list = self._extract_series(data_source, config)
        return ChartBuilder.build_line(
            title=title, dates=dates, series_list=series_list,
            y_name=config.get("y_axis_name", ""),
        )

    def _build_bar(self, data_source: Any, config: dict, title: str) -> dict:
        categories, series_list = self._extract_series(data_source, config)
        return ChartBuilder.build_bar(
            title=title, categories=categories, series_list=series_list,
            y_name=config.get("y_axis_name", ""),
        )

    def _build_pie(self, data_source: Any, config: dict, title: str) -> dict:
        # 尝试提取 name-value 对
        items: list[dict] = []
        if isinstance(data_source, dict) and "items" in data_source:
            items = data_source["items"]
        elif isinstance(data_source, list):
            items = data_source
        elif isinstance(data_source, dict) and "records" in data_source:
            records = data_source["records"]
            name_col = config.get("name_field", "name")
            value_col = config.get("value_field", "value")
            for r in records:
                if name_col in r and value_col in r:
                    items.append({"name": str(r[name_col]), "value": float(r[value_col])})
        return ChartBuilder.build_pie(title=title, data_items=items)

    def _build_scatter(self, data_source: Any, config: dict, title: str) -> dict:
        # 直接提供 points 结构
        if isinstance(data_source, dict) and "points" in data_source:
            return ChartBuilder.build_scatter(
                title=title, data_points=data_source["points"],
                x_name=config.get("x_axis_name", ""),
                y_name=config.get("y_axis_name", ""),
            )
        # records → 提取 x/y
        records = data_source
        if isinstance(data_source, dict) and "records" in data_source:
            records = data_source["records"]
        if isinstance(records, list) and records:
            x_col = config.get("x_axis", "x")
            y_col = config.get("y_axis", "y")
            points = [{"name": str(r.get("name", i)),
                        "x": float(r.get(x_col, 0)),
                        "y": float(r.get(y_col, 0))}
                       for i, r in enumerate(records)]
            return ChartBuilder.build_scatter(
                title=title, data_points=points,
                x_name=config.get("x_axis_name", x_col),
                y_name=config.get("y_axis_name", y_col),
            )
        return ChartBuilder.build_scatter(title=title, data_points=[])

    def _build_heatmap(self, data_source: Any, config: dict, title: str) -> dict:
        if isinstance(data_source, dict):
            x_labels = data_source.get("x_labels", [])
            y_labels = data_source.get("y_labels", [])
            values = data_source.get("values", [])
            if x_labels and y_labels and values:
                return ChartBuilder.build_heatmap(
                    title=title, x_labels=x_labels, y_labels=y_labels, values=values,
                )
        # 从 records 构建
        records = data_source if isinstance(data_source, list) else data_source.get("records", [])
        if records:
            df = pd.DataFrame(records)
            numeric_df = df.select_dtypes(include=[np.number])
            corr = numeric_df.corr()
            labels = list(corr.columns)
            vals = corr.values.tolist()
            return ChartBuilder.build_heatmap(
                title=title, x_labels=labels, y_labels=labels, values=vals,
            )
        return ChartBuilder.build_heatmap(title=title, x_labels=[], y_labels=[], values=[])

    def _build_box(self, data_source: Any, config: dict, title: str) -> dict:
        """箱线图 → 通过柱状图展示五数概括"""
        records = data_source
        if isinstance(data_source, dict) and "records" in data_source:
            records = data_source["records"]
        if not isinstance(records, list) or not records:
            return ChartBuilder.build_bar(title=title, categories=[], series_list=[])

        df = pd.DataFrame(records)
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

        categories = numeric_cols
        stats_names = ["min", "Q1", "median", "Q3", "max"]
        series_list: list[dict] = []
        for stat_name in stats_names:
            data_vals: list[float] = []
            for col in numeric_cols:
                s = df[col].dropna()
                if stat_name == "min":
                    data_vals.append(float(s.min()))
                elif stat_name == "Q1":
                    data_vals.append(float(s.quantile(0.25)))
                elif stat_name == "median":
                    data_vals.append(float(s.median()))
                elif stat_name == "Q3":
                    data_vals.append(float(s.quantile(0.75)))
                else:
                    data_vals.append(float(s.max()))
            series_list.append({"name": stat_name, "data": data_vals})

        return ChartBuilder.build_bar(
            title=f"{title}（五数概括）", categories=categories, series_list=series_list,
        )

    def _build_area(self, data_source: Any, config: dict, title: str) -> dict:
        dates, series_list = self._extract_series(data_source, config)
        return ChartBuilder.build_area_stack(
            title=title, dates=dates, series_list=series_list,
        )

    def _build_dashboard(self, data_source: Any, config: dict, title: str) -> list[dict]:
        """仪表板：根据 sub_charts 配置生成多个子图"""
        sub_charts_config: list[dict] = config.get("sub_charts", [])
        charts: list[dict] = []

        if not sub_charts_config:
            # 自动模式：尝试 build_auto
            chart = ChartBuilder.build_auto(title=title, data=data_source if isinstance(data_source, dict) else {})
            return [chart]

        for sc in sub_charts_config:
            sc_type = sc.get("chart_type", "line")
            sc_title = sc.get("title", title)
            sc_data = sc.get("data_source", data_source)
            sc_config = sc.get("config", config)

            handler = {
                "line": self._build_line,
                "bar": self._build_bar,
                "pie": self._build_pie,
                "scatter": self._build_scatter,
                "heatmap": self._build_heatmap,
                "area": self._build_area,
            }.get(sc_type)

            if handler:
                charts.append(handler(sc_data, sc_config, sc_title))

        return charts if charts else [ChartBuilder.build_auto(title=title, data={})]
