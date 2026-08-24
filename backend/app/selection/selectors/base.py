"""资产选择器基类.

提供选择器抽象接口和通用技术指标过滤能力。
所有选择器继承此类，通过 select() 执行资产选择，
通过 apply_tech_filter() 叠加技术指标 N 选 M 过滤（可选）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from app.selection.types import SelectionResult


class BaseAssetSelector(ABC):
    """资产选择器抽象基类.
    
    所有选择器需要实现：
    1. select() 方法：执行资产选择
    2. get_param_schema() 方法：返回参数Schema
    """
    
    @abstractmethod
    def select(
        self, 
        prices: pd.DataFrame, 
        n_assets: int,
        **params
    ) -> "SelectionResult":
        """从价格数据中筛选资产.
        
        Args:
            prices: 候选资产价格矩阵（index: 日期，columns: 资产代码）
            n_assets: 选择资产数量
            **params: 选择器参数
        
        Returns:
            SelectionResult: 选择结果（包含选中资产、得分、排名等）
        """
        raise NotImplementedError
    
    @classmethod
    def get_param_schema(cls):
        """返回参数Schema定义（用于前端表单生成）.
        
        Returns:
            dict: 参数Schema字典
        """
        return {
            "selector_type": cls.__name__,
            "display_name": cls.__name__,
            "description": "",
            "params": []
        }

    @staticmethod
    def apply_tech_filter(
        prices: pd.DataFrame,
        candidates: List[str],
        tech_conditions: Optional[List[Dict[str, str]]] = None,
        min_pass: int = 2,
        rolling_window: int = 30,
    ) -> Dict[str, bool]:
        """通用技术指标 N 选 M 过滤.

        对每个候选资产检查多个技术条件，满足 >= min_pass 个条件的才通过。
        任何选择器均可调用此方法叠加技术过滤，实现趋势/动量确认。

        Args:
            prices: 价格矩阵（含附加指标列，如 {code}_RSI、{code}_bull_bear_ma、{code}_STD）
            candidates: 候选资产代码列表
            tech_conditions: 条件列表，每个条件为 {"column": "{code}_RSI", "op": "<", "value": "70"}
                其中 {code} 会被替换为实际资产代码。
                支持的操作符：<, >, ==, <=, >=, percentile_rank<
                percentile_rank<: 当前值在最近 rolling_window 个交易日中的排名分位，
                    计算方式为 (recent < current).sum() / len(recent)，与 step3 原始策略对齐。
            min_pass: 最少通过条件数（N 选 M 中的 M）
            rolling_window: percentile_rank 操作符使用的滚动窗口（默认 30 个交易日）

        Returns:
            {code: bool}: 各资产是否通过技术过滤
        """
        if not tech_conditions:
            return {code: True for code in candidates}

        result: Dict[str, bool] = {}
        for code in candidates:
            passed = 0
            for cond in tech_conditions:
                col_template = cond.get("column", "")
                col = col_template.replace("{code}", code)
                if col not in prices.columns:
                    # 条件数据不存在时自动通过（与原始策略一致）
                    continue
                val = prices[col].iloc[-1] if not prices[col].empty else None
                if val is None or pd.isna(val):
                    continue
                op = cond.get("op", "<")
                threshold = cond.get("value", "")
                try:
                    if op == "percentile_rank<":
                        # 当前值在最近 rolling_window 日中的排名分位（不含当日）
                        series = prices[col].iloc[:-1]  # 不含当日
                        if len(series) >= 10:
                            window = min(rolling_window, len(series))
                            recent = series.iloc[-window:]
                            rank_pct = (recent < float(val)).sum() / len(recent)
                            if rank_pct < float(threshold):
                                passed += 1
                        # 数据不足时不通过（保守策略）
                    elif op == "<" and float(val) < float(threshold):
                        passed += 1
                    elif op == ">" and float(val) > float(threshold):
                        passed += 1
                    elif op == "==" and str(val) == str(threshold):
                        passed += 1
                    elif op == "<=" and float(val) <= float(threshold):
                        passed += 1
                    elif op == ">=" and float(val) >= float(threshold):
                        passed += 1
                except (ValueError, TypeError):
                    continue
            result[code] = passed >= min_pass
        return result
