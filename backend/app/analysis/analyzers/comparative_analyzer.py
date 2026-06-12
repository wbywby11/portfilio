"""多资产对比分析器.

负责多个资产之间的对比分析，包括指标排名、相关性矩阵等。
注意：这里不涉及资产组合后的绩效分析（组合净值/组合夏普等），
组合绩效分析属于回测模块的职责。
"""

from __future__ import annotations

from typing import Dict, List, Optional
from dataclasses import dataclass

import pandas as pd

from app.analysis.config import AnalysisConfig
from app.analysis.metrics import AssetMetrics
from app.analysis.types import CorrelationMatrix


@dataclass
class ComparativeMetrics:
    """多资产对比指标.
    
    包含各资产的指标值及排名信息。
    """
    
    metrics: Dict[str, AssetMetrics]      # {thscode: AssetMetrics}
    rankings: Dict[str, Dict[str, int]]   # {metric_name: {thscode: rank}}
    start_date: str
    end_date: str
    
    def get_sorted_by(self, metric_name: str, ascending: bool = False) -> List[str]:
        """按指定指标排序资产.
        
        参数:
            metric_name: 指标名称（如 'sharpe_ratio'）
            ascending: 是否升序（默认降序）
        
        返回:
            排序后的资产代码列表
        """
        metric_values = []
        for thscode, metrics in self.metrics.items():
            value = getattr(metrics, metric_name, None)
            if value is not None:
                metric_values.append((thscode, value))
        
        # 排序
        sorted_assets = sorted(metric_values, key=lambda x: x[1], reverse=not ascending)
        return [code for code, _ in sorted_assets]
    
    def get_top_n(self, metric_name: str, n: int = 5) -> List[str]:
        """获取指定指标的前N名资产.
        
        参数:
            metric_name: 指标名称
            n: 返回前N名
        
        返回:
            前N名资产代码列表
        """
        sorted_assets = self.get_sorted_by(metric_name, ascending=False)
        return sorted_assets[:n]
    
    def to_dataframe(self, metrics_list: Optional[List[str]] = None) -> pd.DataFrame:
        """将对比指标转换为DataFrame格式.
        
        参数:
            metrics_list: 要包含的指标列表，None表示全部
        
        返回:
            DataFrame（行=资产，列=指标）
        """
        if metrics_list is None:
            metrics_list = [
                'cumulative_return',
                'annualized_return',
                'annualized_volatility',
                'max_drawdown',
                'sharpe_ratio',
                'calmar_ratio',
            ]
        
        data = []
        for thscode, asset_metrics in self.metrics.items():
            row = {'thscode': thscode}
            for metric in metrics_list:
                value = getattr(asset_metrics, metric, None)
                if value is not None:
                    row[metric] = value
            data.append(row)
        
        return pd.DataFrame(data).set_index('thscode')


class ComparativeAnalyzer:
    """多资产对比分析器.
    
    专注于单资产之间的横向对比分析，不涉及组合绩效。
    """
    
    def __init__(self, config: AnalysisConfig | None = None) -> None:
        """初始化分析器.
        
        参数:
            config: 分析配置（可选）
        """
        self._config = config or AnalysisConfig()
    
    def analyze(
        self,
        asset_metrics: Dict[str, AssetMetrics],
    ) -> ComparativeMetrics:
        """进行多资产对比分析.
        
        参数:
            asset_metrics: {thscode: AssetMetrics} 各资产的指标
        
        返回:
            ComparativeMetrics 对象
        """
        if not asset_metrics:
            raise ValueError("asset_metrics 不能为空")
        
        # 获取时间区间（使用第一个资产的时间）
        first_metrics = next(iter(asset_metrics.values()))
        start_date = first_metrics.start_date
        end_date = first_metrics.end_date
        
        # 计算各指标的排名
        rankings = self._calculate_rankings(asset_metrics)
        
        return ComparativeMetrics(
            metrics=asset_metrics,
            rankings=rankings,
            start_date=start_date,
            end_date=end_date,
        )
    
    def _calculate_rankings(
        self,
        asset_metrics: Dict[str, AssetMetrics],
    ) -> Dict[str, Dict[str, int]]:
        """计算各指标的排名.
        
        参数:
            asset_metrics: {thscode: AssetMetrics}
        
        返回:
            {metric_name: {thscode: rank}}
        """
        # 需要排名的指标（值越大越好）
        metrics_to_rank = [
            'cumulative_return',
            'annualized_return',
            'sharpe_ratio',
            'calmar_ratio',
        ]
        
        # 需要反向排名的指标（值越小越好）
        reverse_metrics = [
            'annualized_volatility',
            'max_drawdown',  # 最大回撤是负值，越接近0越好
        ]
        
        rankings = {}
        
        # 正向排名
        for metric_name in metrics_to_rank:
            metric_values = {
                thscode: getattr(metrics, metric_name)
                for thscode, metrics in asset_metrics.items()
            }
            # 按值降序排名（值越大排名越前）
            sorted_assets = sorted(metric_values.items(), key=lambda x: x[1], reverse=True)
            rankings[metric_name] = {thscode: rank + 1 for rank, (thscode, _) in enumerate(sorted_assets)}
        
        # 反向排名
        for metric_name in reverse_metrics:
            metric_values = {
                thscode: getattr(metrics, metric_name)
                for thscode, metrics in asset_metrics.items()
            }
            # 按值升序排名（值越小排名越前）
            if metric_name == 'max_drawdown':
                # 最大回撤是负值，绝对值越小越好
                sorted_assets = sorted(metric_values.items(), key=lambda x: abs(x[1]), reverse=False)
            else:
                sorted_assets = sorted(metric_values.items(), key=lambda x: x[1], reverse=False)
            rankings[metric_name] = {thscode: rank + 1 for rank, (thscode, _) in enumerate(sorted_assets)}
        
        return rankings
    
    def compare_two_assets(
        self,
        asset1_metrics: AssetMetrics,
        asset2_metrics: AssetMetrics,
    ) -> Dict[str, str]:
        """对比两个资产的指标.
        
        参数:
            asset1_metrics: 资产1的指标
            asset2_metrics: 资产2的指标
        
        返回:
            对比结果字典 {metric_name: comparison_text}
        """
        comparisons = {}
        
        # 收益对比
        if asset1_metrics.annualized_return > asset2_metrics.annualized_return:
            comparisons['return'] = f"{asset1_metrics.thscode} 年化收益率更高"
        else:
            comparisons['return'] = f"{asset2_metrics.thscode} 年化收益率更高"
        
        # 风险对比
        if abs(asset1_metrics.max_drawdown) < abs(asset2_metrics.max_drawdown):
            comparisons['risk'] = f"{asset1_metrics.thscode} 最大回撤更小"
        else:
            comparisons['risk'] = f"{asset2_metrics.thscode} 最大回撤更小"
        
        # 风险调整收益对比
        if asset1_metrics.sharpe_ratio > asset2_metrics.sharpe_ratio:
            comparisons['risk_adjusted'] = f"{asset1_metrics.thscode} 夏普比率更高"
        else:
            comparisons['risk_adjusted'] = f"{asset2_metrics.thscode} 夏普比率更高"
        
        return comparisons
