"""
chart_builder - 统一 ECharts 图表配置生成模块

将散落在多个工具文件中的 ECharts 配置生成逻辑收敛到此模块，
提供统一的构建接口和一致的输出格式。

所有 build_xxx 方法返回统一格式:
{
    "chart_type": "<type>",
    "title": "<标题>",
    "echarts_option": { ... }
}

此模块为纯工具模块，不依赖任何外部库，仅生成 dict/JSON。
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union


class ChartType(str, Enum):
    """ECharts 图表类型枚举"""

    LINE = "line"              # 折线图（时间序列/趋势）
    BAR = "bar"                # 柱状图（对比）
    PIE = "pie"                # 饼图（占比）
    HEATMAP = "heatmap"        # 热力图（相关性矩阵）
    RADAR = "radar"            # 雷达图（多维对比）
    AREA_STACK = "area_stack"  # 堆叠面积图（权重变化）
    SCATTER = "scatter"        # 散点图（收益-风险）


# ── 默认配置 ──────────────────────────────────────────────

_DEFAULT_GRID = {
    "left": 60, "right": 20, "bottom": 60, "top": 30,
    "containLabel": False,
}

_DEFAULT_AXIS_LABEL_FONT_SIZE = 11


class ChartBuilder:
    """
    ECharts 图表配置统一构建器。

    所有方法均为 @staticmethod，返回包含 chart_type / title / echarts_option 的字典。
    """

    # ── 折线图 ────────────────────────────────────────────

    @staticmethod
    def build_line(
        title: str,
        dates: List[str],
        series_list: List[Dict[str, Any]],
        **opts,
    ) -> Dict[str, Any]:
        """构建折线图配置。

        Args:
            title: 图表标题。
            dates: X 轴日期/类目列表。
            series_list: 系列数据列表，每项格式:
                {"name": "xxx", "data": [...], "smooth": True, "areaStyle": {...}, ...}
            **opts:
                y_name (str): Y 轴名称，默认 ""。
                y_scale (bool): Y 轴是否开启 scale 模式，默认 True。
                data_zoom (bool): 是否显示 dataZoom，默认 True。
                boundary_gap (bool): X 轴 boundaryGap，默认 False。

        Returns:
            统一格式图表配置字典。
        """
        y_name: str = opts.get("y_name", "")
        y_scale: bool = opts.get("y_scale", True)
        data_zoom: bool = opts.get("data_zoom", True)
        boundary_gap: bool = opts.get("boundary_gap", False)
        grid = opts.get("grid", _DEFAULT_GRID.copy())

        # 构建 series
        series = []
        for s in series_list:
            item: Dict[str, Any] = {
                "name": s.get("name", ""),
                "type": "line",
                "data": s.get("data", []),
                "smooth": s.get("smooth", True),
                "symbol": s.get("symbol", "none"),
            }
            # 线条样式
            if "lineStyle" in s:
                item["lineStyle"] = s["lineStyle"]
            elif "color" in s:
                item["lineStyle"] = {"width": 2, "color": s["color"]}
            # 面积样式
            if "areaStyle" in s:
                item["areaStyle"] = s["areaStyle"]
            series.append(item)

        option: Dict[str, Any] = {
            "tooltip": {"trigger": "axis"},
            "grid": grid,
            "xAxis": {
                "type": "category",
                "data": dates,
                "boundaryGap": boundary_gap,
                "axisLabel": {
                    "rotate": 30,
                    "fontSize": _DEFAULT_AXIS_LABEL_FONT_SIZE,
                    "interval": "auto",
                },
            },
            "yAxis": {
                "type": "value",
                "name": y_name,
                "scale": y_scale,
            },
            "series": series,
        }

        # 多系列时自动添加 legend
        if len(series) > 1:
            option["legend"] = {
                "data": [s["name"] for s in series],
                "bottom": 0,
            }

        if data_zoom:
            option["dataZoom"] = [{"type": "inside", "start": 0, "end": 100}]

        return {
            "chart_type": ChartType.LINE.value,
            "title": title,
            "echarts_option": option,
        }

    # ── 柱状图 ────────────────────────────────────────────

    @staticmethod
    def build_bar(
        title: str,
        categories: List[str],
        series_list: List[Dict[str, Any]],
        **opts,
    ) -> Dict[str, Any]:
        """构建柱状图配置。

        Args:
            title: 图表标题。
            categories: X 轴类目列表。
            series_list: 系列数据列表，每项格式:
                {"name": "xxx", "data": [...], "itemStyle": {...}}
            **opts:
                y_name (str): Y 轴名称，默认 ""。
                y_formatter (str): Y 轴标签格式化模板，如 "{value}%"。
                x_rotate (int): X 轴标签旋转角度，默认 30。
                legend_bottom (int): legend 距底部距离，默认 0。

        Returns:
            统一格式图表配置字典。
        """
        y_name: str = opts.get("y_name", "")
        y_formatter: Optional[str] = opts.get("y_formatter")
        x_rotate: int = opts.get("x_rotate", 30)
        legend_bottom: int = opts.get("legend_bottom", 0)
        grid = opts.get("grid", _DEFAULT_GRID.copy())

        # 构建 series
        series = []
        for s in series_list:
            item: Dict[str, Any] = {
                "name": s.get("name", ""),
                "type": "bar",
                "data": s.get("data", []),
            }
            if "itemStyle" in s:
                item["itemStyle"] = s["itemStyle"]
            elif "color" in s:
                item["itemStyle"] = {"color": s["color"]}
            series.append(item)

        y_axis: Dict[str, Any] = {"type": "value", "name": y_name}
        if y_formatter:
            y_axis["axisLabel"] = {"formatter": y_formatter}

        option: Dict[str, Any] = {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": grid,
            "xAxis": {
                "type": "category",
                "data": categories,
                "axisLabel": {
                    "rotate": x_rotate,
                    "fontSize": _DEFAULT_AXIS_LABEL_FONT_SIZE,
                },
            },
            "yAxis": y_axis,
            "series": series,
        }

        # 多系列时添加 legend
        if len(series) > 1:
            option["legend"] = {
                "data": [s["name"] for s in series],
                "bottom": legend_bottom,
            }

        return {
            "chart_type": ChartType.BAR.value,
            "title": title,
            "echarts_option": option,
        }

    # ── 饼图 ──────────────────────────────────────────────

    @staticmethod
    def build_pie(
        title: str,
        data_items: List[Dict[str, Any]],
        **opts,
    ) -> Dict[str, Any]:
        """构建饼图（环形图）配置。

        Args:
            title: 图表标题。
            data_items: 数据项列表，每项格式: {"name": "xxx", "value": 123}
            **opts:
                radius (list): 内外半径，默认 ["40%", "70%"]。
                center (list): 圆心位置，默认 ["60%", "50%"]。

        Returns:
            统一格式图表配置字典。
        """
        radius = opts.get("radius", ["40%", "70%"])
        center = opts.get("center", ["60%", "50%"])

        # 确保 data_items 中的数值是原生 Python 类型（兑容 numpy 等）
        safe_data = [
            {"value": float(item.get("value", 0)), "name": str(item.get("name", ""))}
            for item in data_items
        ]

        option: Dict[str, Any] = {
            "tooltip": {"trigger": "item", "formatter": "{b}: {d}%"},
            "legend": {
                "orient": "vertical",
                "left": "left",
                "top": "middle",
            },
            "series": [{
                "name": title,
                "type": "pie",
                "radius": radius,
                "center": center,
                "avoidLabelOverlap": True,
                "itemStyle": {"borderRadius": 4},
                "label": {"show": True, "formatter": "{b}\n{d}%"},
                "data": safe_data,
            }],
        }

        return {
            "chart_type": ChartType.PIE.value,
            "title": title,
            "echarts_option": option,
        }

    # ── 热力图 ────────────────────────────────────────────

    @staticmethod
    def build_heatmap(
        title: str,
        x_labels: List[str],
        y_labels: List[str],
        values: List,
        **opts,
    ) -> Dict[str, Any]:
        """构建热力图配置（如相关性矩阵）。

        Args:
            title: 图表标题。
            x_labels: X 轴标签列表。
            y_labels: Y 轴标签列表。
            values: 数据值，支持两种格式:
                - 三元组列表 [[col_idx, row_idx, value], ...]
                - 二维矩阵 [[row0_col0, row0_col1, ...], [row1_col0, ...], ...]
            **opts:
                min_val (float): 颜色映射最小值，默认 -1。
                max_val (float): 颜色映射最大值，默认 1。
                color_range (list): 颜色梯度列表。
                show_label (bool): 是否在格子上显示数值，默认 True。

        Returns:
            统一格式图表配置字典。
        """
        min_val: float = opts.get("min_val", -1)
        max_val: float = opts.get("max_val", 1)
        show_label: bool = opts.get("show_label", True)
        color_range: List[str] = opts.get("color_range", [
            "#313695", "#4575b4", "#74add1", "#abd9e9",
            "#fee090", "#fdae61", "#f46d43", "#d73027",
        ])

        # 如果传入二维矩阵，转换为三元组格式
        heatmap_data = values
        if values and isinstance(values[0], list) and len(values[0]) != 3:
            heatmap_data = []
            for i, row in enumerate(values):
                for j, val in enumerate(row):
                    heatmap_data.append([j, i, val])

        grid = opts.get("grid", {
            "left": 80, "right": 40, "bottom": 60, "top": 30,
        })

        option: Dict[str, Any] = {
            "tooltip": {"position": "top"},
            "grid": grid,
            "xAxis": {
                "type": "category",
                "data": x_labels,
                "axisLabel": {"rotate": 45},
            },
            "yAxis": {
                "type": "category",
                "data": y_labels,
            },
            "visualMap": {
                "min": min_val,
                "max": max_val,
                "calculable": True,
                "orient": "horizontal",
                "left": "center",
                "bottom": 0,
                "inRange": {"color": color_range},
            },
            "series": [{
                "name": title,
                "type": "heatmap",
                "data": heatmap_data,
                "label": {"show": show_label},
            }],
        }

        return {
            "chart_type": ChartType.HEATMAP.value,
            "title": title,
            "echarts_option": option,
        }

    # ── 雷达图 ────────────────────────────────────────────

    @staticmethod
    def build_radar(
        title: str,
        indicators: List[Dict[str, Any]],
        series_list: List[Dict[str, Any]],
        **opts,
    ) -> Dict[str, Any]:
        """构建雷达图配置。

        Args:
            title: 图表标题。
            indicators: 维度指标列表，每项格式: {"name": "xxx", "max": 100}
            series_list: 系列数据列表，每项格式:
                {"name": "xxx", "data": [v1, v2, ...]}
            **opts:
                shape (str): 雷达形状，"polygon" 或 "circle"，默认 "polygon"。
                radius (str): 雷达半径，默认 "65%"。

        Returns:
            统一格式图表配置字典。
        """
        shape: str = opts.get("shape", "polygon")
        radius: str = opts.get("radius", "65%")

        # 构建 series data
        radar_data = []
        for s in series_list:
            item: Dict[str, Any] = {
                "name": s.get("name", ""),
                "value": s.get("data", []),
            }
            if "areaStyle" in s:
                item["areaStyle"] = s["areaStyle"]
            else:
                item["areaStyle"] = {"opacity": 0.2}
            radar_data.append(item)

        option: Dict[str, Any] = {
            "tooltip": {"trigger": "item"},
            "legend": {
                "data": [s.get("name", "") for s in series_list],
                "bottom": 0,
            },
            "radar": {
                "indicator": indicators,
                "shape": shape,
                "radius": radius,
            },
            "series": [{
                "name": title,
                "type": "radar",
                "data": radar_data,
            }],
        }

        return {
            "chart_type": ChartType.RADAR.value,
            "title": title,
            "echarts_option": option,
        }

    # ── 堆叠面积图 ────────────────────────────────────────

    @staticmethod
    def build_area_stack(
        title: str,
        dates: List[str],
        series_list: List[Dict[str, Any]],
        **opts,
    ) -> Dict[str, Any]:
        """构建堆叠面积图配置（如资产权重变化）。

        Args:
            title: 图表标题。
            dates: X 轴日期列表。
            series_list: 系列数据列表，每项格式:
                {"name": "xxx", "data": [...]}
            **opts:
                y_max (int|float): Y 轴最大值，默认 100。
                y_formatter (str): Y 轴标签格式化模板，默认 "{value}%"。
                legend_scroll (bool): legend 是否可滚动，默认 True。
                data_zoom (bool): 是否显示 dataZoom，默认 True。

        Returns:
            统一格式图表配置字典。
        """
        y_max = opts.get("y_max", 100)
        y_formatter: str = opts.get("y_formatter", "{value}%")
        legend_scroll: bool = opts.get("legend_scroll", True)
        data_zoom: bool = opts.get("data_zoom", True)
        grid = opts.get("grid", {
            "left": 50, "right": 20, "bottom": 80, "top": 30,
            "containLabel": False,
        })

        # 构建 series
        series = []
        legend_names = []
        for s in series_list:
            name = s.get("name", "")
            legend_names.append(name)
            series.append({
                "name": name,
                "type": "line",
                "stack": "total",
                "areaStyle": s.get("areaStyle", {"opacity": 0.6}),
                "emphasis": {"focus": "series"},
                "data": s.get("data", []),
                "symbol": s.get("symbol", "none"),
            })

        option: Dict[str, Any] = {
            "tooltip": {
                "trigger": "axis",
                "axisPointer": {"type": "cross"},
            },
            "legend": {
                "data": legend_names,
                "bottom": 0,
                "type": "scroll" if legend_scroll else "plain",
            },
            "grid": grid,
            "xAxis": {
                "type": "category",
                "data": dates,
                "boundaryGap": False,
                "axisLabel": {
                    "rotate": 30,
                    "fontSize": _DEFAULT_AXIS_LABEL_FONT_SIZE,
                    "interval": "auto",
                },
            },
            "yAxis": {
                "type": "value",
                "name": opts.get("y_name", "权重"),
                "max": y_max,
                "min": 0,
                "axisLabel": {"formatter": y_formatter},
            },
            "series": series,
        }

        if data_zoom:
            option["dataZoom"] = [{"type": "inside", "start": 0, "end": 100}]

        return {
            "chart_type": ChartType.AREA_STACK.value,
            "title": title,
            "echarts_option": option,
        }

    # ── 散点图 ────────────────────────────────────────────

    @staticmethod
    def build_scatter(
        title: str,
        data_points: List[Dict[str, Any]],
        **opts,
    ) -> Dict[str, Any]:
        """构建散点图配置（如收益-风险散点图）。

        Args:
            title: 图表标题。
            data_points: 散点系列列表，每项格式:
                {"name": "xxx", "data": [[x1,y1], [x2,y2], ...]}
                或单点列表: [{"name": "资产A", "x": 0.1, "y": 0.05}, ...]
            **opts:
                x_name (str): X 轴名称，默认 ""。
                y_name (str): Y 轴名称，默认 ""。
                symbol_size (int): 标记点大小，默认 14。

        Returns:
            统一格式图表配置字典。
        """
        x_name: str = opts.get("x_name", "")
        y_name: str = opts.get("y_name", "")
        symbol_size: int = opts.get("symbol_size", 14)
        grid = opts.get("grid", _DEFAULT_GRID.copy())

        # 兼容两种输入格式
        series = []
        if data_points and "data" in data_points[0]:
            # 标准系列格式: [{"name": "...", "data": [[x,y], ...]}, ...]
            for s in data_points:
                series.append({
                    "name": s.get("name", ""),
                    "type": "scatter",
                    "data": s.get("data", []),
                    "symbolSize": s.get("symbolSize", symbol_size),
                })
        else:
            # 单点格式: [{"name": "资产A", "x": 0.1, "y": 0.05}, ...]
            scatter_data = [[p.get("x", 0), p.get("y", 0)] for p in data_points]
            labels = [p.get("name", "") for p in data_points]
            series.append({
                "name": title,
                "type": "scatter",
                "data": scatter_data,
                "symbolSize": symbol_size,
                "label": {
                    "show": True,
                    "formatter": None,  # 由前端处理
                    "position": "top",
                },
                "_labels": labels,  # 供前端映射名称
            })

        option: Dict[str, Any] = {
            "tooltip": {"trigger": "item"},
            "grid": grid,
            "xAxis": {
                "type": "value",
                "name": x_name,
                "axisLabel": {"fontSize": _DEFAULT_AXIS_LABEL_FONT_SIZE},
            },
            "yAxis": {
                "type": "value",
                "name": y_name,
            },
            "series": series,
        }

        # 多系列时添加 legend
        if len(series) > 1:
            option["legend"] = {
                "data": [s["name"] for s in series],
                "bottom": 0,
            }

        return {
            "chart_type": ChartType.SCATTER.value,
            "title": title,
            "echarts_option": option,
        }

    # ── 自动推断 ──────────────────────────────────────────

    @staticmethod
    def auto_detect_type(data: Dict[str, Any], hint: Optional[str] = None) -> ChartType:
        """基于数据形状自动推断合适的图表类型。

        推断规则（按优先级）:
        1. hint 参数不为空时直接使用 hint 指定的类型
        2. data 中包含 "indicators" → RADAR
        3. data 中包含 "x_labels" + "y_labels" + "values" → HEATMAP
        4. data 中包含 "items" 且每项有 name/value → PIE
        5. data 中包含 "dates" + "series" → LINE
        6. data 中包含 "categories" + "series" → BAR
        7. 默认返回 LINE

        Args:
            data: 数据字典。
            hint: 显式指定图表类型字符串，可覆盖自动推断。

        Returns:
            推断出的 ChartType 枚举值。
        """
        # hint 覆盖
        if hint:
            try:
                return ChartType(hint)
            except ValueError:
                pass

        # 按数据特征推断
        if "indicators" in data:
            return ChartType.RADAR

        if "x_labels" in data and "y_labels" in data and "values" in data:
            return ChartType.HEATMAP

        if "items" in data:
            items = data["items"]
            if items and isinstance(items, list):
                first = items[0]
                if isinstance(first, dict) and "name" in first and "value" in first:
                    return ChartType.PIE

        if "dates" in data and "series" in data:
            return ChartType.LINE

        if "categories" in data and "series" in data:
            return ChartType.BAR

        return ChartType.LINE

    @staticmethod
    def build_auto(
        title: str,
        data: Dict[str, Any],
        hint: Optional[str] = None,
        **opts,
    ) -> Dict[str, Any]:
        """根据数据自动推断图表类型并构建配置。

        自动调用 auto_detect_type 判断图表类型，然后路由到对应的 build_xxx 方法。

        Args:
            title: 图表标题。
            data: 数据字典，结构决定图表类型。
            hint: 显式指定图表类型，可覆盖自动推断。
            **opts: 传递给具体 build_xxx 方法的额外参数。

        Returns:
            统一格式图表配置字典。
        """
        chart_type = ChartBuilder.auto_detect_type(data, hint)

        if chart_type == ChartType.LINE:
            return ChartBuilder.build_line(
                title,
                dates=data.get("dates", []),
                series_list=data.get("series", []),
                **opts,
            )

        if chart_type == ChartType.BAR:
            return ChartBuilder.build_bar(
                title,
                categories=data.get("categories", []),
                series_list=data.get("series", []),
                **opts,
            )

        if chart_type == ChartType.PIE:
            return ChartBuilder.build_pie(
                title,
                data_items=data.get("items", []),
                **opts,
            )

        if chart_type == ChartType.HEATMAP:
            return ChartBuilder.build_heatmap(
                title,
                x_labels=data.get("x_labels", []),
                y_labels=data.get("y_labels", []),
                values=data.get("values", []),
                **opts,
            )

        if chart_type == ChartType.RADAR:
            return ChartBuilder.build_radar(
                title,
                indicators=data.get("indicators", []),
                series_list=data.get("series", []),
                **opts,
            )

        if chart_type == ChartType.AREA_STACK:
            return ChartBuilder.build_area_stack(
                title,
                dates=data.get("dates", []),
                series_list=data.get("series", []),
                **opts,
            )

        if chart_type == ChartType.SCATTER:
            return ChartBuilder.build_scatter(
                title,
                data_points=data.get("points", data.get("series", [])),
                **opts,
            )

        # fallback
        return ChartBuilder.build_line(
            title,
            dates=data.get("dates", []),
            series_list=data.get("series", []),
            **opts,
        )
