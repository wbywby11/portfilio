"""策略服务 - 核心策略管理与调度服务."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence, TYPE_CHECKING

import pandas as pd

from app.strategies.models.base import BaseStrategyModel
from app.strategies.services.config import StrategyConfig

if TYPE_CHECKING:
    from app.services.market_service import MarketService


class StrategyService:
    """策略服务 - 统一的策略管理与调度.
    
    核心职责：
    1. 策略注册管理：维护策略类型到实现类的映射
    2. 配置持久化：保存/加载/删除策略实例配置
    3. 参数验证：基于Schema验证策略参数
    4. 权重计算：提供统一的权重计算接口
    
    设计原则：
    - 服务化：提供标准化的API接口
    - 无状态：计算接口不依赖内部状态
    - 可扩展：易于添加新策略类型
    """
    
    def __init__(
        self, 
        market_service: "MarketService" | None = None,
        config_file: str = "data/strategy_configs.json"
    ) -> None:
        """初始化策略服务.
        
        Args:
            market_service: 行情查询服务实例（用于获取市场数据）
            config_file: 策略配置持久化文件路径
        """
        # 策略注册表：{strategy_type: strategy_class}
        self._registry: Dict[str, type[BaseStrategyModel]] = {}
        
        # 策略配置：{config_id: StrategyConfig}
        self._configs: Dict[str, StrategyConfig] = {}
        
        # 行情查询服务
        self._market_service = market_service
        
        # 配置文件路径
        self._config_file = Path(config_file)
        
        # 加载已保存的配置
        self._load_configs()
    
    # ================================================================
    # 策略注册管理
    # ================================================================
    
    def register(self, strategy_type: str, strategy_cls: type[BaseStrategyModel]) -> None:
        """注册策略类型.
        
        Args:
            strategy_type: 策略类型标识（如 "risk_parity"）
            strategy_cls: 策略实现类（必须继承BaseStrategyModel）
        """
        if not issubclass(strategy_cls, BaseStrategyModel):
            raise TypeError(f"{strategy_cls} 必须继承 BaseStrategyModel")
        
        self._registry[strategy_type] = strategy_cls
    
    def list_strategy_types(self) -> List[str]:
        """列出所有已注册的策略类型."""
        return list(self._registry.keys())
    
    def get_strategy_class(self, strategy_type: str) -> type[BaseStrategyModel]:
        """获取策略实现类.
        
        Args:
            strategy_type: 策略类型标识
        
        Returns:
            策略实现类
        
        Raises:
            KeyError: 策略类型不存在
        """
        if strategy_type not in self._registry:
            raise KeyError(f"策略类型 '{strategy_type}' 未注册")
        
        return self._registry[strategy_type]
    
    async def auto_register_templates_from_database(self, template_service) -> Dict[str, bool]:
        """
        从数据库自动注册所有模板到策略服务
        
        Args:
            template_service: ModelTemplateService实例
        
        Returns:
            {
                template_code: success (bool)
            }
        """
        templates = await template_service.list_templates(is_active=True)
        results = {}
        
        for template in templates:
            try:
                success = await template_service.register_template_to_strategy_service(
                    template, self
                )
                results[template.code] = success
            except Exception as e:
                import warnings
                warnings.warn(f"注册模板 {template.code} 失败: {e}")
                results[template.code] = False
        
        return results
    
    # ================================================================
    # 参数Schema管理
    # ================================================================
    
    def get_param_schema(self, strategy_type: str) -> dict:
        """获取策略参数Schema.
        
        Args:
            strategy_type: 策略类型标识
        
        Returns:
            Schema字典（包含参数定义、显示名称、说明等）
        
        Raises:
            KeyError: 策略类型不存在
        """
        strategy_cls = self.get_strategy_class(strategy_type)
        schema = strategy_cls.get_param_schema()
        return schema.to_dict()
    
    def get_all_param_schemas(self) -> Dict[str, dict]:
        """获取所有策略的参数Schema.
        
        Returns:
            {strategy_type: schema_dict}
        """
        schemas = {}
        for strategy_type in self.list_strategy_types():
            try:
                schemas[strategy_type] = self.get_param_schema(strategy_type)
            except Exception:
                # 跳过获取失败的策略
                continue
        return schemas
    
    def validate_params(self, strategy_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """验证策略参数.
        
        Args:
            strategy_type: 策略类型
            params: 待验证的参数字典
        
        Returns:
            {
                "valid": bool,
                "errors": List[str],
                "warnings": List[str]
            }
        """
        try:
            strategy_cls = self.get_strategy_class(strategy_type)
            schema = strategy_cls.get_param_schema()
            is_valid, errors = schema.validate_params(params)
            
            return {
                "valid": is_valid,
                "errors": errors,
                "warnings": []
            }
        except KeyError as e:
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": []
            }
    
    # ================================================================
    # 策略配置持久化
    # ================================================================
    
    def _load_configs(self) -> None:
        """从文件加载已保存的策略配置."""
        self._configs.clear()  # 清空现有配置，确保重新加载
        
        if not self._config_file.exists():
            return
        
        try:
            with open(self._config_file, 'r', encoding='utf-8') as f:
                configs_data = json.load(f)
            
            for config_dict in configs_data:
                config = StrategyConfig.from_dict(config_dict)
                self._configs[config.id] = config
        except Exception as e:
            import warnings
            warnings.warn(f"加载策略配置失败: {e}")
    
    def _save_configs(self) -> None:
        """将当前所有策略配置保存到文件."""
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        
        configs_data = [config.to_dict() for config in self._configs.values()]
        
        with open(self._config_file, 'w', encoding='utf-8') as f:
            json.dump(configs_data, f, indent=2, ensure_ascii=False)
    
    def save_config(self, config: StrategyConfig) -> None:
        """保存或更新策略配置.
        
        Args:
            config: 策略配置实例
        """
        # 验证策略类型是否已注册
        if config.type not in self._registry:
            raise KeyError(f"策略类型 '{config.type}' 未注册")
        
        # 验证参数
        validation = self.validate_params(config.type, config.params)
        if not validation["valid"]:
            raise ValueError(f"参数验证失败: {', '.join(validation['errors'])}")
        
        self._configs[config.id] = config
        self._save_configs()
    
    def get_config(self, config_id: str) -> StrategyConfig:
        """获取策略配置.
        
        Args:
            config_id: 策略实例ID
        
        Returns:
            策略配置实例
        
        Raises:
            KeyError: 配置不存在
        """
        # 每次获取前重新加载，确保跨页面配置同步
        self._load_configs()
        
        if config_id not in self._configs:
            raise KeyError(f"策略配置 '{config_id}' 不存在")
        
        return self._configs[config_id]
    
    def list_configs(self) -> List[StrategyConfig]:
        """列出所有已保存的策略配置."""
        # 每次调用前重新加载，确保跨页面配置同步
        self._load_configs()
        return list(self._configs.values())
    
    def delete_config(self, config_id: str) -> None:
        """删除策略配置.
        
        Args:
            config_id: 策略实例ID
        """
        self._configs.pop(config_id, None)
        self._save_configs()
    
    # ================================================================
    # 权重计算服务
    # ================================================================
    
    async def compute_weights(
        self,
        strategy_type: str,
        thscodes: Sequence[str],
        start_date: str,
        end_date: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """计算策略权重（无状态接口）.
        
        这是核心的权重计算服务，直接接收所有参数，无需预先保存配置。
        
        Args:
            strategy_type: 策略类型标识
            thscodes: 资产代码列表
            start_date: 开始日期（格式：YYYYMMDD）
            end_date: 结束日期（格式：YYYYMMDD）
            params: 策略参数字典
        
        Returns:
            {
                "thscodes": List[str],       # 资产代码
                "weights": List[float],      # 对应权重
                "timestamp": str,            # 计算时间戳
                "strategy_type": str,        # 策略类型
                "params_used": dict          # 实际使用的参数
            }
        
        Raises:
            ValueError: 参数验证失败或数据获取失败
            KeyError: 策略类型不存在
            RuntimeError: 行情服务未注入
        """
        if self._market_service is None:
            raise RuntimeError("行情查询服务未注入，无法获取市场数据")
        
        # 1. 验证参数
        validation = self.validate_params(strategy_type, params)
        if not validation["valid"]:
            raise ValueError(f"参数验证失败: {', '.join(validation['errors'])}")
        
        # 2. 获取策略类
        strategy_cls = self.get_strategy_class(strategy_type)
        
        # 3. 获取市场数据（异步调用）
        prices = await self._market_service.get_price_matrix(
            thscodes=list(thscodes),
            start_date=start_date,
            end_date=end_date,
        )
        
        if prices.empty:
            raise ValueError("获取的价格数据为空，请检查资产代码和日期区间")
        
        # 4. 实例化策略并计算权重
        strategy = strategy_cls()
        weights = strategy.allocate(prices, **params)
        
        # 5. 标准化输出（确保权重非负且和为1）
        weights = weights.reindex(thscodes).fillna(0.0)
        weights = weights.clip(lower=0.0)
        total = float(weights.sum())
        if total > 0:
            weights = weights / total
        
        # 6. 返回标准格式
        return {
            "thscodes": weights.index.tolist(),
            "weights": weights.values.tolist(),
            "timestamp": pd.Timestamp.now().isoformat(),
            "strategy_type": strategy_type,
            "params_used": params
        }
    
    async def run_strategy(
        self,
        config_id: str,
        start_date: str,
        end_date: str,
        thscodes: Sequence[str] | None = None,
        **override_params: Any,
    ) -> pd.Series:
        """运行已保存的策略配置.
        
        这是配置驱动的权重计算接口，基于已保存的策略配置运行。
        
        Args:
            config_id: 策略配置ID
            start_date: 开始日期
            end_date: 结束日期
            thscodes: 资产池（可选，默认使用配置中的资产池）
            **override_params: 临时覆盖的参数
        
        Returns:
            权重Series（index为资产代码，values为权重）
        
        Raises:
            KeyError: 配置不存在
            ValueError: 数据获取失败
            RuntimeError: 行情服务未注入
        """
        # 获取配置
        config = self.get_config(config_id)
        
        # 确定资产池
        target_thscodes = list(thscodes) if thscodes else config.thscodes
        if not target_thscodes:
            raise ValueError("资产池为空")
        
        # 合并参数
        params = {**config.params, **override_params}
        
        # 调用无状态接口计算权重（异步）
        result = await self.compute_weights(
            strategy_type=config.type,
            thscodes=target_thscodes,
            start_date=start_date,
            end_date=end_date,
            params=params
        )
        
        # 转换为Series格式
        weights = pd.Series(result["weights"], index=result["thscodes"])
        return weights
