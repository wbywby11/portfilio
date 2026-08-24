"""动态策略加载器 - 从模板源代码动态创建策略实例."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any, Dict

from app.allocation.models.base import BaseStrategyModel

if TYPE_CHECKING:
    from app.models.model_template import ModelTemplate


class DynamicStrategyLoader:
    """动态策略加载器.
    
    核心功能：
    1. 从模板的 source_code 动态加载策略类
    2. 验证策略类是否符合规范（继承BaseStrategyModel）
    3. 提供安全的策略实例创建机制
    
    安全措施：
    - 使用受限的全局命名空间
    - 仅暴露必要的模块和类
    - 捕获并报告所有异常
    """
    
    @staticmethod
    def load_strategy_class_from_template(template: "ModelTemplate") -> type[BaseStrategyModel]:
        """从模板动态加载策略类.
        
        Args:
            template: 模型模板实例（必须包含 source_code）
        
        Returns:
            策略类（继承自BaseStrategyModel）
        
        Raises:
            ValueError: 模板无源代码或找不到策略类
            SyntaxError: 源代码语法错误
            TypeError: 策略类未继承BaseStrategyModel
            RuntimeError: 执行源代码时出错
        """
        if not template.source_code:
            raise ValueError(f"模板 {template.code} 缺少源代码")
        
        # 1. 准备受限的全局命名空间（安全沙箱）
        safe_globals = {
            "__builtins__": __builtins__,
            "pd": __import__("pandas"),
            "np": __import__("numpy"),
            "BaseStrategyModel": BaseStrategyModel,
            # 添加常用的策略工具
            "compute_simple_returns": __import__("app.formula.returns", fromlist=["compute_simple_returns"]).compute_simple_returns,
            "compute_covariance": __import__("app.formula.covariance", fromlist=["compute_covariance"]).compute_covariance,
            "compute_risk_contribution": __import__("app.formula.risk_contribution", fromlist=["compute_risk_contribution"]).compute_risk_contribution,
            # 绩效评估工具
            "compute_portfolio_returns": __import__("app.formula.portfolio_returns", fromlist=["compute_portfolio_returns"]).compute_portfolio_returns,
            "compute_annualized_return": __import__("app.formula.sharpe_ratio", fromlist=["compute_annualized_return"]).compute_annualized_return,
            "compute_sharpe_ratio": __import__("app.formula.sharpe_ratio", fromlist=["compute_sharpe_ratio"]).compute_sharpe_ratio,
            # 滚动波动率计算工具
            "compute_asset_rolling_volatility": __import__("app.formula.rolling_volatility", fromlist=["compute_asset_rolling_volatility"]).compute_asset_rolling_volatility,
            "compute_portfolio_volatility": __import__("app.formula.rolling_volatility", fromlist=["compute_portfolio_volatility"]).compute_portfolio_volatility,
            "compute_rolling_volatility": __import__("app.formula.rolling_volatility", fromlist=["compute_rolling_volatility"]).compute_rolling_volatility,
            # 优化求解器
            "solve_slsqp": __import__("app.solvers.slsqp_solver", fromlist=["solve_slsqp"]).solve_slsqp,
            # 参数模型
            "ParamSchema": __import__("app.allocation.models.param_schema", fromlist=["ParamSchema"]).ParamSchema,
            "StrategyParamSchema": __import__("app.allocation.models.param_schema", fromlist=["StrategyParamSchema"]).StrategyParamSchema,
        }
        
        # 2. 清理源代码（去除多余缩进）
        source_code = textwrap.dedent(template.source_code)
        
        # 3. 执行源代码，加载类定义
        local_namespace: Dict[str, Any] = {}
        try:
            exec(source_code, safe_globals, local_namespace)
        except SyntaxError as e:
            raise SyntaxError(f"模板 {template.code} 源代码语法错误: {e}")
        except Exception as e:
            raise RuntimeError(f"模板 {template.code} 源代码执行失败: {e}")
        
        # 4. 从 local_namespace 中查找继承 BaseStrategyModel 的类
        strategy_cls = None
        for name, obj in local_namespace.items():
            if (
                isinstance(obj, type) 
                and issubclass(obj, BaseStrategyModel) 
                and obj is not BaseStrategyModel
            ):
                strategy_cls = obj
                break
        
        if strategy_cls is None:
            raise ValueError(
                f"模板 {template.code} 源代码中未找到继承 BaseStrategyModel 的类。"
                f"可用的对象: {list(local_namespace.keys())}"
            )
        
        return strategy_cls
    
    @staticmethod
    def create_strategy_instance(template: "ModelTemplate") -> BaseStrategyModel:
        """从模板创建策略实例.
        
        Args:
            template: 模型模板实例
        
        Returns:
            策略实例（BaseStrategyModel子类的实例）
        
        Raises:
            ValueError/SyntaxError/TypeError/RuntimeError: 参见 load_strategy_class_from_template
        """
        strategy_cls = DynamicStrategyLoader.load_strategy_class_from_template(template)
        return strategy_cls()
    
    @staticmethod
    def validate_template_source_code(template: "ModelTemplate") -> Dict[str, Any]:
        """验证模板源代码的有效性.
        
        执行完整的加载流程，但不返回策略实例，仅返回验证结果。
        
        Args:
            template: 模型模板实例
        
        Returns:
            {
                "valid": bool,           # 是否有效
                "errors": List[str],     # 错误信息列表
                "warnings": List[str],   # 警告信息列表
                "strategy_class": str    # 策略类名（若成功加载）
            }
        """
        result = {
            "valid": False,
            "errors": [],
            "warnings": [],
            "strategy_class": None
        }
        
        try:
            strategy_cls = DynamicStrategyLoader.load_strategy_class_from_template(template)
            result["valid"] = True
            result["strategy_class"] = strategy_cls.__name__
            
            # 检查是否实现了 get_param_schema 方法
            if not hasattr(strategy_cls, "get_param_schema"):
                result["warnings"].append(
                    "策略类未实现 get_param_schema() 方法，将使用默认空Schema"
                )
            
            # 检查是否实现了 allocate 方法
            if not hasattr(strategy_cls, "allocate"):
                result["errors"].append("策略类必须实现 allocate() 方法")
                result["valid"] = False
        
        except ValueError as e:
            result["errors"].append(str(e))
        except SyntaxError as e:
            result["errors"].append(f"语法错误: {e}")
        except TypeError as e:
            result["errors"].append(str(e))
        except RuntimeError as e:
            result["errors"].append(str(e))
        except Exception as e:
            result["errors"].append(f"未知错误: {e}")
        
        return result
