"""内置策略模板定义

在程序启动时，会自动将这些内置模板同步到数据库中。
"""

from typing import List, Dict, Any
import inspect
import textwrap
from pathlib import Path


def _get_strategy_source_with_imports(strategy_class) -> str:
    """
    获取策略类的完整源代码（包含所有 import）
    
    通过读取策略类所在的源文件，获取完整的源代码。
    
    Args:
        strategy_class: 策略类
    
    Returns:
        包含所有 import 和类定义的完整源代码
    """
    try:
        # 获取类所在的文件路径
        source_file = inspect.getfile(strategy_class)
        
        # 读取整个文件
        with open(source_file, 'r', encoding='utf-8') as f:
            full_source = f.read()
        
        return full_source
        
    except Exception as e:
        # 如果无法读取文件，回退到只返回类定义 + 通用 import
        class_source = inspect.getsource(strategy_class)
        
        # 添加必要的 import 语句
        imports = [
            "from abc import ABC, abstractmethod",
            "import pandas as pd",
            "import numpy as np",
            "from typing import Dict, Any, Optional",
            "from app.strategies.models.base import BaseStrategyModel",
            "from app.strategies.formula.returns import compute_simple_returns",
            "from app.strategies.formula.covariance import compute_covariance",
            "from app.strategies.formula.risk_contribution import compute_risk_contribution",
            "from app.strategies.formula.rolling_volatility import compute_asset_rolling_volatility, compute_portfolio_volatility, compute_rolling_volatility",
            "from app.strategies.solvers.slsqp_solver import solve_slsqp",
        ]
        
        # 组合完整源代码
        full_source = "\n".join(imports) + "\n\n" + class_source
        
        return full_source


def get_builtin_templates() -> List[Dict[str, Any]]:
    """
    获取所有内置策略模板定义
    
    每个模板包含：
    - code: 模板代码（唯一标识）
    - name: 模板名称
    - description: 模板描述
    - source_code: 策略源代码
    - parameters: 参数定义列表
    
    Returns:
        内置模板列表
    """
    templates = []
    
    # ==================== 1. 风险平价策略 ====================
    from app.strategies.models.risk_parity import RiskParityStrategy
    
    risk_parity_schema = RiskParityStrategy.get_param_schema()
    risk_parity_source = _get_strategy_source_with_imports(RiskParityStrategy)
    
    templates.append({
        "code": "risk_parity",
        "name": "风险平价策略",
        "description": "各资产风险贡献相等的组合配置策略，适合多元化投资。通过优化使每个资产对组合风险的边际贡献相等。",
        "source_code": risk_parity_source,
        "parameters": _convert_schema_to_params(risk_parity_schema)
    })
    
    # ==================== 2. 均值-方差优化 ====================
    from app.strategies.models.mean_variance import MeanVarianceOptimization
    
    mean_variance_schema = MeanVarianceOptimization.get_param_schema()
    mean_variance_source = _get_strategy_source_with_imports(MeanVarianceOptimization)
    
    templates.append({
        "code": "mean_variance",
        "name": "均值-方差优化",
        "description": "基于Markowitz现代投资组合理论，在预期收益和风险之间寻找最优平衡。支持最小方差、目标收益和最大夏普比率三种优化模式。",
        "source_code": mean_variance_source,
        "parameters": _convert_schema_to_params(mean_variance_schema)
    })
    
    # ==================== 3. 增强风险平价策略 ====================
    try:
        from app.strategies.models.enhanced_risk_parity import CovarianceSharpeOptimization
        
        cso_schema = CovarianceSharpeOptimization.get_param_schema()
        cso_source = _get_strategy_source_with_imports(CovarianceSharpeOptimization)
        
        templates.append({
            "code": "cso",
            "name": "协方差-夏普优化",
            "description": "增强的风险平价策略，结合协方差矩阵和夏普比率优化。",
            "source_code": cso_source,
            "parameters": _convert_schema_to_params(cso_schema)
        })
    except ImportError:
        pass  # 如果模块不存在，跳过
    
    # ==================== 4. 风险预算策略 ====================
    try:
        from app.strategies.models.risk_budget import RiskBudgetStrategy
        
        risk_budget_schema = RiskBudgetStrategy.get_param_schema()
        risk_budget_source = _get_strategy_source_with_imports(RiskBudgetStrategy)
        
        templates.append({
            "code": "risk_budget",
            "name": "风险预算策略",
            "description": "根据预设的风险预算分配各资产权重，允许自定义每个资产的风险贡献目标。",
            "source_code": risk_budget_source,
            "parameters": _convert_schema_to_params(risk_budget_schema)
        })
    except ImportError:
        pass
    
    # ==================== 5. 因子风险平价策略 ====================
    try:
        from app.strategies.models.factor_risk_parity import FactorRiskParityStrategy
        
        factor_rp_schema = FactorRiskParityStrategy.get_param_schema()
        factor_rp_source = _get_strategy_source_with_imports(FactorRiskParityStrategy)
        
        templates.append({
            "code": "factor_rp",
            "name": "因子风险平价",
            "description": "基于因子分解的风险平价策略，考虑资产之间的因子暴露。",
            "source_code": factor_rp_source,
            "parameters": _convert_schema_to_params(factor_rp_schema)
        })
    except ImportError:
        pass
    
    # ==================== 6. 风险预算+目标波动率 ====================
    try:
        from app.strategies.models.risk_budget_target_vol import RiskBudgetTargetVolStrategy
        
        rb_tv_schema = RiskBudgetTargetVolStrategy.get_param_schema()
        rb_tv_source = _get_strategy_source_with_imports(RiskBudgetTargetVolStrategy)
        
        templates.append({
            "code": "risk_budget_target_vol",
            "name": "风险预算+目标波动率",
            "description": "结合风险预算和目标波动率的策略，提供双重风险控制。",
            "source_code": rb_tv_source,
            "parameters": _convert_schema_to_params(rb_tv_schema)
        })
    except ImportError:
        pass
    
    # ==================== 8. 主观配置策略 ====================
    try:
        from app.strategies.models.manual_allocation import ManualAllocationStrategy
        
        manual_schema = ManualAllocationStrategy.get_param_schema()
        manual_source = _get_strategy_source_with_imports(ManualAllocationStrategy)
        
        templates.append({
            "code": "manual_allocation",
            "name": "主观配置策略",
            "description": "根据用户指定的权重进行资产配置，支持完全自定义。",
            "source_code": manual_source,
            "parameters": _convert_schema_to_params(manual_schema)
        })
    except ImportError:
        pass
    
    # ==================== 9. Black-Litterman 模型 ====================
    try:
        from app.strategies.models.black_litterman import BlackLittermanOptimization
        bl_schema = BlackLittermanOptimization.get_param_schema()
        bl_source = _get_strategy_source_with_imports(BlackLittermanOptimization)
        templates.append({
            "code": "black_litterman",
            "name": "Black-Litterman 模型",
            "description": bl_schema.description,
            "source_code": bl_source,
            "parameters": _convert_schema_to_params(bl_schema)
        })
    except ImportError:
        pass
    
    # ==================== 10. ETF周期轮动策略 ====================
    try:
        from app.strategies.models.etf_cycle_rotation import ETFCycleRotationStrategy
        
        cycle_schema = ETFCycleRotationStrategy.get_param_schema()
        cycle_source = _get_strategy_source_with_imports(ETFCycleRotationStrategy)
        
        templates.append({
            "code": "etf_cycle_rotation",
            "name": "ETF周期轮动策略",
            "description": "基于ETF的周频轮动策略，支持波动率轮动、收益+乖离率、混合因子、强势突破四种子策略。通过参数选择子策略类型。",
            "source_code": cycle_source,
            "parameters": _convert_schema_to_params(cycle_schema)
        })
    except ImportError:
        pass
    
    return templates


def _convert_schema_to_params(schema) -> List[Dict[str, Any]]:
    """
    将 StrategyParamSchema 转换为 ModelParameter 格式
    
    Args:
        schema: StrategyParamSchema 实例
    
    Returns:
        参数列表（ModelParameter 格式）
    """
    params = []
    
    for param in schema.params:
        # 类型映射
        type_mapping = {
            "number": "number",
            "slider": "slider",
            "select": "select",
            "text": "string",
            "checkbox": "boolean",
            "dict": "dict"
        }
        
        param_dict = {
            "name": param.name,
            "label": param.label,
            "param_type": type_mapping.get(param.type, "string"),
            "default_value": param.default,
            "required": param.required,
            "description": param.description,
            "min_value": param.min_value,
            "max_value": param.max_value,
        }
        
        # 处理 step 字段
        if hasattr(param, 'step') and param.step is not None:
            param_dict["step"] = param.step
        
        # 处理选项
        if param.options:
            # 如果是 [(value, label), ...] 格式，只取 value
            if isinstance(param.options[0], tuple):
                param_dict["options"] = [opt[0] for opt in param.options]
            else:
                param_dict["options"] = param.options
        
        params.append(param_dict)
    
    return params
