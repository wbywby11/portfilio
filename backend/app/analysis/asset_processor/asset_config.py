"""资产配置管理器.

提供资产元数据的保存、加载、管理功能，连接数据库存储层。
"""

from __future__ import annotations
from typing import Dict, List, Optional
import pandas as pd
from data.asset_types import AssetMetadata
from data.storage import SQLitePriceStorage


class AssetConfigManager:
    """资产元数据配置管理器.
    
    功能：
    1. 保存资产元数据到数据库
    2. 加载资产元数据
    3. 管理资产配置的增删改查
    """
    
    def __init__(self, storage: SQLitePriceStorage):
        """初始化管理器.
        
        Args:
            storage: 数据存储实例
        """
        self.storage = storage
    
    def save_config(self, metadata: AssetMetadata) -> None:
        """保存资产元数据到数据库.
        
        Args:
            metadata: 资产元数据对象
        """
        metadata_dict = {
            'thscode': metadata.thscode,
            'asset_type': metadata.asset_type,
            'name': metadata.name,
            'rollover_days': metadata.rollover_days,
            'rollover_threshold': metadata.rollover_threshold,
            'rollover_window_p': metadata.rollover_window_p,
            'rollover_window_q': metadata.rollover_window_q,
            'substitute_code': metadata.substitute_code,
            'switch_date': metadata.switch_date,
        }
        self.storage.save_asset_metadata(metadata_dict)
    
    def load_config(self, thscode: str) -> Optional[AssetMetadata]:
        """加载单个资产的元数据.
        
        Args:
            thscode: 资产代码
            
        Returns:
            资产元数据对象，如果不存在则返回 None
        """
        data = self.storage.load_asset_metadata(thscode)
        if data is None:
            return None
        
        # 将数据库字典转换为 AssetMetadata 对象
        return AssetMetadata(
            thscode=data['thscode'],
            asset_type=data['asset_type'],
            name=data.get('name', ''),
            rollover_days=data.get('rollover_days', 5),
            rollover_threshold=data.get('rollover_threshold', 1.0),
            rollover_window_p=data.get('rollover_window_p', 10),
            rollover_window_q=data.get('rollover_window_q', 5),
            substitute_code=data.get('substitute_code'),
            switch_date=data.get('switch_date'),
        )
    
    def get_all_configs(self) -> Dict[str, AssetMetadata]:
        """获取所有已配置资产的元数据.
        
        Returns:
            {thscode: AssetMetadata} 字典
        """
        df = self.storage.load_all_asset_metadata()
        
        if df.empty:
            return {}
        
        configs = {}
        for _, row in df.iterrows():
            metadata = AssetMetadata(
                thscode=row['thscode'],
                asset_type=row['asset_type'],
                name=row.get('name', ''),
                rollover_days=row.get('rollover_days', 5),
                rollover_threshold=row.get('rollover_threshold', 1.0),
                rollover_window_p=row.get('rollover_window_p', 10),
                rollover_window_q=row.get('rollover_window_q', 5),
                substitute_code=row.get('substitute_code'),
                switch_date=row.get('switch_date'),
            )
            configs[row['thscode']] = metadata
        
        return configs
    
    def get_configured_thscodes(self) -> List[str]:
        """获取所有已配置资产的代码列表.
        
        Returns:
            资产代码列表
        """
        df = self.storage.load_all_asset_metadata()
        if df.empty:
            return []
        return df['thscode'].tolist()
    
    def delete_config(self, thscode: str) -> None:
        """删除资产配置.
        
        Args:
            thscode: 资产代码
        """
        self.storage.delete_asset_metadata(thscode)
    
    def update_config(self, metadata: AssetMetadata) -> None:
        """更新资产配置.
        
        Args:
            metadata: 更新后的资产元数据
            
        注意：使用 save_config，数据库使用 INSERT OR REPLACE 自动处理更新
        """
        self.save_config(metadata)
    
    def get_configs_by_type(self, asset_type: str) -> Dict[str, AssetMetadata]:
        """按资产类型筛选配置.
        
        Args:
            asset_type: 资产类型 ('index', 'futures', 'spot')
            
        Returns:
            {thscode: AssetMetadata} 字典
        """
        all_configs = self.get_all_configs()
        return {
            thscode: config
            for thscode, config in all_configs.items()
            if config.asset_type == asset_type
        }
    
    def get_summary_dataframe(self) -> pd.DataFrame:
        """获取配置摘要表格（用于前端展示）.
        
        Returns:
            包含资产代码、类型、名称等信息的DataFrame
        """
        df = self.storage.load_all_asset_metadata()
        
        if df.empty:
            return pd.DataFrame(columns=['资产代码', '资产类型', '名称'])
        
        # 翻译类型
        type_mapping = {
            'index': '指数类',
            'futures': '期货类',
            'spot': '现货类'
        }
        
        display_df = pd.DataFrame({
            '资产代码': df['thscode'],
            '资产类型': df['asset_type'].map(type_mapping),
            '名称': df['name']
        })
        
        return display_df
