"""策略注册器 - 统一管理所有可用策略的注册（支持模板自动注册）."""

from typing import TYPE_CHECKING
from app.strategies.services.strategy_service import StrategyService
from app.strategies.models.risk_parity import RiskParityStrategy
from app.strategies.models.enhanced_risk_parity import CovarianceSharpeOptimization
from app.strategies.models.risk_budget import RiskBudgetStrategy
from app.strategies.models.factor_risk_parity import FactorRiskParityStrategy
from app.strategies.models.mean_variance import MeanVarianceOptimization
from app.strategies.models.risk_budget_target_vol import RiskBudgetTargetVolStrategy
from app.strategies.models.manual_allocation import ManualAllocationStrategy
from app.strategies.models.etf_cycle_rotation import ETFCycleRotationStrategy

if TYPE_CHECKING:
    from app.services.model_template_service import ModelTemplateService


# ==================== 已废弃的函数（保留以兼容旧代码） ====================

def register_all_strategies(service: StrategyService) -> None:
    """
    注册所有可用的策略模型.
    
    ⚠️ 已废弃：请使用 create_strategy_service_from_database() 替代
    内置策略现在都存储在数据库中，通过模板系统统一管理。
    
    Args:
        service: 策略服务实例
    """
    import warnings
    warnings.warn(
        "register_all_strategies() 已废弃，请使用 create_strategy_service_from_database()",
        DeprecationWarning,
        stacklevel=2
    )
    
    # 注册风险平价策略
    service.register("risk_parity", RiskParityStrategy)
    service.register("cso", CovarianceSharpeOptimization)
    service.register("risk_budget", RiskBudgetStrategy)
    service.register("factor_rp", FactorRiskParityStrategy)
    service.register("mean_variance", MeanVarianceOptimization)
    service.register("risk_budget_target_vol", RiskBudgetTargetVolStrategy)
    service.register("manual_allocation", ManualAllocationStrategy)
    service.register("etf_cycle_rotation", ETFCycleRotationStrategy)


def create_strategy_service(market_service=None, config_file="data/strategy_configs.json") -> StrategyService:
    """
    创建并初始化策略服务（工厂函数）.
    
    ⚠️ 已废弃：请使用 create_strategy_service_from_database() 替代
    
    Args:
        market_service: 行情查询服务实例
        config_file: 配置文件路径
    
    Returns:
        已注册所有策略的服务实例
    """
    import warnings
    warnings.warn(
        "create_strategy_service() 已废弃，请使用 create_strategy_service_from_database()",
        DeprecationWarning,
        stacklevel=2
    )
    service = StrategyService(market_service=market_service, config_file=config_file)
    register_all_strategies(service)
    return service


# ==================== 推荐的工厂函数 ====================

async def create_strategy_service_from_database(
    market_service=None,
    config_file="data/strategy_configs.json"
) -> StrategyService:
    """
    从数据库创建策略服务（推荐使用）
    
    完全从数据库的 model_templates 集合加载策略，不依赖硬编码的内置策略。
    
    Args:
        market_service: 行情查询服务实例
        config_file: 配置文件路径
    
    Returns:
        已注册所有数据库模板策略的服务实例
    """
    from app.services.model_template_service import ModelTemplateService
    
    service = StrategyService(market_service=market_service, config_file=config_file)
    template_service = ModelTemplateService()
    
    # 从数据库加载所有模板
    results = await service.auto_register_templates_from_database(template_service)
    
    # 记录注册结果
    success_count = sum(1 for success in results.values() if success)
    total_count = len(results)
    if total_count > 0:
        print(f"策略服务初始化完成: {success_count}/{total_count} 模板加载成功")
    
    return service


async def create_strategy_service_with_templates(
    market_service=None, 
    template_service: "ModelTemplateService" = None,
    config_file="data/strategy_configs.json",
    skip_builtin: bool = True  # 默认跳过内置策略
) -> StrategyService:
    """
    创建策略服务并自动注册模板策略（兼容旧接口）.
    
    推荐使用 create_strategy_service_from_database() 替代。
    
    此方法会：
    1. 注册所有内置策略（可选，默认跳过）
    2. 从数据库加载模板并动态注册
    
    Args:
        market_service: 行情查询服务实例
        template_service: 模板服务实例
        config_file: 配置文件路径
        skip_builtin: 是否跳过内置策略注册（默认True，推荐）
    
    Returns:
        已注册所有策略（内置+模板）的服务实例
    """
    # 1. 创建基础服务
    service = StrategyService(market_service=market_service, config_file=config_file)
    
    # 2. 注册内置策略（可选，不推荐）
    if not skip_builtin:
        import warnings
        warnings.warn(
            "不推荐使用内置策略注册，所有策略应存储在数据库中",
            DeprecationWarning,
            stacklevel=2
        )
        register_all_strategies(service)
    
    # 3. 自动注册模板策略
    if template_service:
        results = await service.auto_register_templates_from_database(template_service)
        
        # 记录注册结果
        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        if total_count > 0:
            print(f"模板注册完成: {success_count}/{total_count} 成功")
    
    return service
