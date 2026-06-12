"""TR样本点位计算器.

封装 analysis.formulas.tr 模块的公式，提供面向对象的接口。
根据文档《不同类型资产收益计算公式.md》实现三种资产类型的TR计算：
1. 指数类：直接使用指数收盘价计算累计收益
2. 期货类：处理主力合约展期，使用加权平均收益率
3. 现货类：上市前用替代标的，上市后切换到实际ETF

核心公式：F_t^c = F_{t-1}^c × (1 + r_t^c)，其中 r_t^c 根据资产类型不同而不同。
所有资产的TR序列从基日点位1开始累积计算。
"""

from __future__ import annotations
from typing import Optional, Dict
import pandas as pd
from data.asset_types import AssetMetadata, DEFAULT_ASSET_CONFIGS

# 从 formulas 模块导入核心公式
from app.analysis.formulas.tr import (
    compute_index_tr,
    compute_futures_tr,
    compute_spot_tr,
    batch_compute_tr,
)


class TRCalculator:
    """样本点位TR计算器.
    
    根据资产类型应用不同的计算公式，生成连续的样本点位序列。
    
    核心公式（文档2节）：
    - 指数类：F_t^c = F_{t-1}^c × (close_t / close_{t-1})
    - 期货类：需要处理主力合约展期，收益率分非展期日和展期日两种情况
    - 现货类：上市前用替代标的，上市后用实际ETF
    
    所有类型最终都通过 F_t^c 序列得到 TR_t^c（初始点位为1）。
    """
    
    def __init__(self, asset_configs: Optional[Dict[str, AssetMetadata]] = None):
        """初始化计算器.
        
        Args:
            asset_configs: 资产配置字典 {thscode: AssetMetadata}
                          如果为None，使用默认配置
        """
        self.asset_configs = asset_configs or DEFAULT_ASSET_CONFIGS
    
    def compute_tr_series(
        self,
        thscode: str,
        price_data: pd.DataFrame,
        base_date: Optional[str] = None,
    ) -> pd.Series:
        """计算单个资产的TR样本点位序列.
        
        Args:
            thscode: 资产代码
            price_data: 价格数据，必须包含列：time, close
                       对于期货类，还需要 settlement（结算价）
            base_date: 基日（YYYYMMDD格式），默认使用数据第一个日期
            
        Returns:
            TR序列（pd.Series，index为time，value为TR_t^c）
        """
        if thscode not in self.asset_configs:
            # 未配置的资产默认作为指数类处理
            return compute_index_tr(price_data, base_date)
        
        config = self.asset_configs[thscode]
        
        if config.asset_type == "index":
            return compute_index_tr(price_data, base_date)
        elif config.asset_type == "futures":
            return compute_futures_tr(config, price_data, base_date)
        elif config.asset_type == "spot":
            return compute_spot_tr(config, price_data, base_date)
        else:
            raise ValueError(f"未知资产类型: {config.asset_type}")
    
    def batch_compute_tr(
        self,
        price_data_dict: Dict[str, pd.DataFrame],
        base_date: Optional[str] = None,
    ) -> Dict[str, pd.Series]:
        """批量计算多个资产的TR序列.
        
        Args:
            price_data_dict: {thscode: price_data} 价格数据字典
            base_date: 基日（YYYYMMDD格式）
            
        Returns:
            {thscode: tr_series} TR序列字典
        """
        return batch_compute_tr(
            price_data_dict=price_data_dict,
            asset_configs=self.asset_configs,
            base_date=base_date,
        )
    
    # 以下为向后兼容的私有方法，委托给 formulas.tr
    
    def _compute_index_tr(
        self,
        price_data: pd.DataFrame,
        base_date: Optional[str] = None,
    ) -> pd.Series:
        """计算指数类TR（向后兼容）."""
        return compute_index_tr(price_data, base_date)
    
    def _compute_futures_tr(
        self,
        config: AssetMetadata,
        price_data: pd.DataFrame,
        base_date: Optional[str] = None,
    ) -> pd.Series:
        """计算期货类TR（向后兼容）."""
        return compute_futures_tr(config, price_data, base_date)
    
    def _compute_spot_tr(
        self,
        config: AssetMetadata,
        price_data: pd.DataFrame,
        base_date: Optional[str] = None,
    ) -> pd.Series:
        """计算现货类TR（向后兼容）."""
        return compute_spot_tr(config, price_data, base_date)
    
    def add_asset_config(self, config: AssetMetadata) -> None:
        """添加或更新资产配置.
        
        Args:
            config: 资产元数据配置
        """
        self.asset_configs[config.thscode] = config
    
    def get_asset_type(self, thscode: str) -> str:
        """获取资产类型.
        
        Args:
            thscode: 资产代码
            
        Returns:
            资产类型：'index', 'futures', 'spot'
        """
        if thscode in self.asset_configs:
            return self.asset_configs[thscode].asset_type
        return "index"  # 默认
    
    def get_asset_config(self, thscode: str) -> Optional[AssetMetadata]:
        """获取资产配置.
        
        Args:
            thscode: 资产代码
            
        Returns:
            资产元数据，如果不存在则返回 None
        """
        return self.asset_configs.get(thscode)
