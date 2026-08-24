"""
Agent 工具共享工具函数 — 序列化、格式化、图表构造

富媒体契约（与前端 chatUtils.js / ChatChartRenderer.vue 对齐）：
- 表格：result.data.records[] → getMessageDataTables 提取为交互表格
- 图表：result.charts[]，每项 {title, chart_type, echarts_option}
  （前端直接消费 echarts_option，缺失则不渲染）
"""
import json
from datetime import date, datetime


# ── 序列化 ──────────────────────────────────────────────────────────────────

def bson_safe(obj):
    """JSON 往返一次，将 datetime/ObjectId/numpy 等转为可存储/可序列化形态"""
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return str(obj)


def extract_context(kwargs: dict) -> dict:
    """从 execute kwargs 中剥离 tool_context 注入字段，返回上下文（原 dict 被修改）"""
    return {k: kwargs.pop(k) for k in ("conversation_id", "user_id") if k in kwargs}


# ── 格式化 ──────────────────────────────────────────────────────────────────

def fmt_date(value) -> str:
    """日期 → 'YYYY-MM-DD'，None → ''"""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def fmt_datetime(value) -> str:
    """日期时间 → 'YYYY-MM-DD HH:MM:SS'，None → ''"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def pct(value, digits: int = 2):
    """小数比例 → 百分比数值（0.1234 → 12.34），None/非法 → None"""
    try:
        if value is None:
            return None
        return round(float(value) * 100, digits)
    except (TypeError, ValueError):
        return None


def round_or_none(value, digits: int = 4):
    """安全四舍五入，None/非法 → None"""
    try:
        if value is None:
            return None
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def sample_series(points: list, max_points: int = 120) -> list:
    """长序列均匀采样（保留首尾点），用于图表降采样"""
    n = len(points)
    if n <= max_points:
        return list(points)
    step = (n - 1) / (max_points - 1)
    idxs = sorted({int(round(i * step)) for i in range(max_points)} | {0, n - 1})
    return [points[i] for i in idxs]


# ── 图表构造（echarts option） ──────────────────────────────────────────────

def line_chart(title: str, x_data: list, series: list[dict], y_name: str = "") -> dict:
    """折线图。series: [{name, data}]，data 为与 x_data 等长的数值列表"""
    return {
        "title": title,
        "chart_type": "line",
        "echarts_option": {
            "xAxis": {"type": "category", "data": x_data, "boundaryGap": False},
            "yAxis": {"type": "value", "name": y_name, "scale": True},
            "series": [{"name": s["name"], "type": "line", "data": s["data"]} for s in series],
        },
    }


def bar_chart(title: str, x_data: list, series: list[dict], y_name: str = "") -> dict:
    """柱状图。series: [{name, data}]"""
    return {
        "title": title,
        "chart_type": "bar",
        "echarts_option": {
            "xAxis": {"type": "category", "data": x_data},
            "yAxis": {"type": "value", "name": y_name},
            "series": [{"name": s["name"], "type": "bar", "data": s["data"]} for s in series],
        },
    }


def pie_chart(title: str, items: list[dict]) -> dict:
    """饼图。items: [{name, value}]"""
    return {
        "title": title,
        "chart_type": "pie",
        "echarts_option": {
            "series": [{"type": "pie", "data": items}],
        },
    }
