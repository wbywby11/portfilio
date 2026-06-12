"""动量资产选择器（基于SHARP动量因子）.

实现文档中描述的动量选择方法：
1. 筛选有效资产（≥260天历史）
2. 计算多窗口SHARP动量（22/65/260天）
3. 排序打分并综合
4. 选择TopN资产
"""

from __future__ import annotations

import pandas as pd

from app.selection.selectors.base import BaseAssetSelector
from app.selection.types import SelectionResult
from app.selection.formula.momentum_factors import rank_and_select_assets


class MomentumSelector(BaseAssetSelector):
    """SHARP动量资产选择器.
    
    核心特点：
    - 多周期验证：结合短期（1月）、中期（3月）、长期（1年）动量
    - 风险调整：使用夏普比率而非简单收益率
    - 相对排序：横截面排序筛选当前最强资产
    """
    
    @classmethod
    def get_param_schema(cls):
        """返回动量选择器的参数Schema."""
        return {
            "selector_type": "momentum",
            "display_name": "SHARP动量选择器",
            "description": "基于多窗口夏普动量的资产筛选方法，选择风险调整后收益最优的资产",
            "params": [
                {
                    "name": "min_history_days",
                    "label": "最小历史数据要求",
                    "type": "number",
                    "default": 260,
                    "min_value": 100,
                    "max_value": 500,
                    "step": 10,
                    "description": "资产进入候选池的最小交易日数（默认260天，建议≥260天以支持多窗口指标计算）"
                },
                {
                    "name": "momentum_windows",
                    "label": "动量窗口",
                    "type": "text",
                    "default": "22,65,260",
                    "description": "动量计算窗口（交易日），用逗号分隔，默认22/65/260对应1月/3月/1年"
                },
                {
                    "name": "tie_break_window",
                    "label": "并列决胜窗口",
                    "type": "number",
                    "default": 22,
                    "min_value": 5,
                    "max_value": 260,
                    "step": 1,
                    "description": "综合得分相同时，优先选择该窗口动量更高的资产（默认22天）"
                },
            ]
        }
    
    def select(
        self,
        prices: pd.DataFrame,
        n_assets: int,
        **params
    ) -> SelectionResult:
        """执行动量资产选择.
        
        Args:
            prices: 候选资产价格矩阵（index: 日期，columns: 资产代码）
            n_assets: 选择资产数量
            **params: 选择器参数
                - min_history_days: 最小历史数据要求（默认260）
                - momentum_windows: 动量窗口（默认"22,65,260"）
                - tie_break_window: 并列决胜窗口（默认22）
        
        Returns:
            SelectionResult: 选择结果
        """
        if prices.empty:
            raise ValueError("prices DataFrame为空")
        
        if n_assets <= 0:
            raise ValueError(f"n_assets必须大于0，当前值：{n_assets}")
        
        # 1. 获取参数
        min_history_days = int(params.get("min_history_days", 260))
        momentum_windows_str = params.get("momentum_windows", "22,65,260")
        tie_break_window = int(params.get("tie_break_window", 22))
        
        # 解析动量窗口
        try:
            momentum_windows = [
                int(w.strip()) 
                for w in momentum_windows_str.split(",")
            ]
        except Exception as e:
            raise ValueError(f"动量窗口参数格式错误：{momentum_windows_str}，错误：{e}")
        
        # 2. 执行选择
        selected_assets, ranking_df = rank_and_select_assets(
            prices=prices,
            n_assets=n_assets,
            windows=momentum_windows,
            min_history_days=min_history_days,
            tie_break_window=tie_break_window
        )
        
        # 3. 提取得分字典
        scores = ranking_df["TotalScore"].to_dict()
        
        # 4. 构造结果
        result = SelectionResult(
            selected_assets=selected_assets,
            scores=scores,
            ranking=ranking_df,
            timestamp=pd.Timestamp.now().isoformat(),
            selector_type="momentum",
            params=params
        )
        
        return result
