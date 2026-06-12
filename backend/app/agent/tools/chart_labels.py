"""
图表展示用标签：绩效指标英文字段 → 中文，资产代码 →「名称（代码）」等。
"""

from __future__ import annotations

from typing import Dict

# 统计分析 / 柱状图等系列名（英文名 → 图表图例）
METRIC_SERIES_LABEL_ZH: Dict[str, str] = {
    "annual_return": "年化收益率",
    "annual_volatility": "年化波动率",
    "sharpe_ratio": "夏普比率",
    "max_drawdown": "最大回撤",
    "total_return": "累计收益率",
    "var_95": "VaR(95%)",
    "skewness": "偏度",
    "kurtosis": "峰度",
    "win_rate": "胜率",
}


def zh_metric_series_name(key: str) -> str:
    """系列名用中文，未知键则原样返回。"""
    return METRIC_SERIES_LABEL_ZH.get(key, key)


async def batch_asset_display_labels(codes: list[str]) -> dict[str, str]:
    """
    资产代码 → 图表用标签：有中文名时用「名称（代码）」，否则仅代码。
    复用 AssetService.resolve_display_names_for_codes（含代码变体匹配）。
    """
    from app.services.asset_service import AssetService

    uniq = list(dict.fromkeys([c for c in codes if c]))
    if not uniq:
        return {}
    svc = AssetService()
    name_by = await svc.resolve_display_names_for_codes(uniq)
    out: dict[str, str] = {}
    for c in uniq:
        nm = (name_by.get(c) or "").strip()
        if nm and nm != str(c):
            out[c] = f"{nm} ({c})"
        else:
            out[c] = str(c)
    return out
