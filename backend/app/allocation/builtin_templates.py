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
            "from app.allocation.models.base import BaseStrategyModel",
            "from app.formula.returns import compute_simple_returns",
            "from app.formula.covariance import compute_covariance",
            "from app.formula.risk_contribution import compute_risk_contribution",
            "from app.formula.rolling_volatility import compute_asset_rolling_volatility, compute_portfolio_volatility, compute_rolling_volatility",
            "from app.solvers.slsqp_solver import solve_slsqp",
        ]
        
        # 组合完整源代码
        full_source = "\n".join(imports) + "\n\n" + class_source
        
        return full_source


# ---------------------------------------------------------------------------
# 三层组合默认配置（从统一策略清单自动派生，只读导出）
# 外部引用兼容：from app.allocation.builtin_templates import COMPOSITION_DEFAULTS
# ---------------------------------------------------------------------------
from app.allocation.strategy_manifest import (
    STRATEGY_MANIFEST,
    get_composition_defaults,
    resolve_class_safe,
)

COMPOSITION_DEFAULTS = get_composition_defaults()


def _composition_for(strategy_type: str, schema_composition):
    """返回策略的三层组合配置，优先使用 schema 声明，回退到 COMPOSITION_DEFAULTS."""
    if schema_composition:
        return schema_composition
    return COMPOSITION_DEFAULTS.get(strategy_type)


def get_builtin_templates() -> List[Dict[str, Any]]:
    """
    获取所有内置策略模板定义（数据驱动，从 STRATEGY_MANIFEST 自动派生）
    
    每个模板包含：
    - code: 模板代码（唯一标识）
    - name: 模板名称
    - description: 模板描述
    - category: 分类（allocation/selection/control）
    - source_code: 策略源代码
    - parameters: 参数定义列表
    
    Returns:
        内置模板列表
    """
    templates = []
    
    # =================================================================
    #  一、配置策略（Allocation）—— 从 STRATEGY_MANIFEST 自动派生
    # =================================================================
    
    for code, entry in STRATEGY_MANIFEST.items():
        strategy_cls = resolve_class_safe(code)
        if strategy_cls is None:
            continue
        
        try:
            schema = strategy_cls.get_param_schema()
            source = _get_strategy_source_with_imports(strategy_cls)
            
            templates.append({
                "code": code,
                "name": entry.name,
                "category": "allocation",
                "description": entry.description,
                "source_code": source,
                "parameters": _convert_schema_to_params(schema),
                "composition": _composition_for(code, getattr(schema, 'composition', None)),
            })
        except Exception:
            # 策略类加载或 schema 获取失败时跳过，不影响其他模板
            continue
    
    # =================================================================
    #  二、资产选择策略（Selection）
    # =================================================================
    
    _add_selection_templates(templates)
    
    # =================================================================
    #  三、风险控制策略（Control）
    # =================================================================
    
    _add_control_templates(templates)
    
    return templates


def _add_selection_templates(templates: List[Dict[str, Any]]) -> None:
    """追加资产选择策略(Selection)模板."""
    
    # --- 1. 动量+反转双模型选择器 (7+1) ---
    try:
        from app.selection.selectors.momentum_reversal import MomentumReversalSelector
        schema = MomentumReversalSelector.get_param_schema()
        templates.append({
            "code": "sel_momentum_reversal",
            "name": "动量+反转(7+1)",
            "category": "selection",
            "description": "动量7因子+反转1因子选股，MOM/MACD/POSI/SMOM+SKEW偏度，符合编制规则。",
            "source_code": _get_strategy_source_with_imports(MomentumReversalSelector),
            "parameters": _convert_selection_dict_to_params(schema),
        })
    except ImportError:
        pass
    
    # --- 2. 夏普率综合打分 ---
    try:
        from app.selection.selectors.sharpe import SharpeSelector
        schema = SharpeSelector.get_param_schema()
        templates.append({
            "code": "sel_sharpe",
            "name": "夏普率综合打分",
            "category": "selection",
            "description": "三层窗口(22/65/260日)夏普率打分选TopN，并列时MOM决胜，与编制规则一致。",
            "source_code": _get_strategy_source_with_imports(SharpeSelector),
            "parameters": _convert_selection_dict_to_params(schema),
        })
    except ImportError:
        pass
    
    # --- 3. 截面动量 ---
    try:
        from app.selection.selectors.cross_sectional_momentum import CrossSectionalMomentumSelector
        schema = CrossSectionalMomentumSelector.get_param_schema()
        templates.append({
            "code": "sel_cross_sectional_momentum",
            "name": "截面动量",
            "category": "selection",
            "description": "滚动累计收益率截面排序，选动量最强的TopN品种。",
            "source_code": _get_strategy_source_with_imports(CrossSectionalMomentumSelector),
            "parameters": _convert_selection_dict_to_params(schema),
        })
    except ImportError:
        pass
    
    # --- 4. 趋势跟踪 ---
    try:
        from app.selection.selectors.trend_following import TrendFollowingSelector
        schema = TrendFollowingSelector.get_param_schema()
        templates.append({
            "code": "sel_trend_following",
            "name": "趋势跟踪",
            "category": "selection",
            "description": "各品种独立判断多空方向，累计收益sign定方向，波动率倒数加权分配。",
            "source_code": _get_strategy_source_with_imports(TrendFollowingSelector),
            "parameters": _convert_selection_dict_to_params(schema),
        })
    except ImportError:
        pass
    
    # --- 5. ETF轮动 ---
    try:
        from app.selection.selectors.etf_rotation import ETFRotationSelector
        schema = ETFRotationSelector.get_param_schema()
        templates.append({
            "code": "sel_etf_rotation",
            "name": "ETF轮动",
            "category": "selection",
            "description": "ETF轮动因子打分：波动率/收益乖离率/混合因子/强势突破四种子策略。",
            "source_code": _get_strategy_source_with_imports(ETFRotationSelector),
            "parameters": _convert_selection_dict_to_params(schema),
        })
    except ImportError:
        pass
    
    # --- 6. ETF贴水率 ---
    try:
        from app.selection.selectors.etf_discount import ETFDiscountSelector
        schema = ETFDiscountSelector.get_param_schema()
        templates.append({
            "code": "sel_etf_discount",
            "name": "ETF贴水率",
            "category": "selection",
            "description": "贴水率滚动分位点信号选股，低贴水率开仓，反波动率加权。",
            "source_code": _get_strategy_source_with_imports(ETFDiscountSelector),
            "parameters": _convert_selection_dict_to_params(schema),
        })
    except ImportError:
        pass

    # --- 7. 截面多空（GMSI 2.0 GCMI 截面动量子通道）---
    try:
        from app.selection.selectors.cross_sectional_long_short import CrossSectionalLongShortSelector
        schema = CrossSectionalLongShortSelector.get_param_schema()
        templates.append({
            "code": "sel_cross_sectional_long_short",
            "name": "截面多空(50/50)",
            "category": "selection",
            "description": "截面动量排序：做多前50%做空后50%，inv_vol加权归一化到±0.5，用于GMSI 2.0 GCMI截面动量子指数。",
            "source_code": _get_strategy_source_with_imports(CrossSectionalLongShortSelector),
            "parameters": _convert_selection_dict_to_params(schema),
        })
    except ImportError:
        pass


def _add_control_templates(templates: List[Dict[str, Any]]) -> None:
    """追加风险控制策略(Control)模板."""
    
    # --- 1. 滚动窗口波动率控制器 ---
    try:
        from app.control.volatility.rolling_vol import RollingVolMonitor
        templates.append({
            "code": "ctrl_rolling_vol",
            "name": "滚动窗口波动率",
            "category": "control",
            "description": "多窗口滚动vol监测，超阈值时按target_vol/vol比例缩放权重。",
            "source_code": _get_strategy_source_with_imports(RollingVolMonitor),
            "parameters": [
                {"name": "vol_window_short", "label": "短期窗口", "param_type": "number",
                 "default_value": 22, "required": False, "min_value": 5, "max_value": 60, "step": 1,
                 "description": "短期波动率计算窗口(交易日)"},
                {"name": "vol_window_medium", "label": "中期窗口", "param_type": "number",
                 "default_value": 65, "required": False, "min_value": 20, "max_value": 130, "step": 5,
                 "description": "中期波动率计算窗口(交易日)"},
                {"name": "vol_window_long", "label": "长期窗口", "param_type": "number",
                 "default_value": 130, "required": False, "min_value": 60, "max_value": 260, "step": 10,
                 "description": "长期波动率计算窗口(交易日)"},
                {"name": "target_vol", "label": "目标年化波动率", "param_type": "number",
                 "default_value": 0.05, "required": False, "min_value": 0.01, "max_value": 0.20,
                 "description": "组合目标年化波动率，超过阈值时缩放权重"},
                {"name": "vol_reset_threshold", "label": "波动率触发阈值", "param_type": "number",
                 "default_value": 0.06, "required": False, "min_value": 0.02, "max_value": 0.30,
                 "description": "当组合波动率超过此阈值时触发权重缩放"},
                {"name": "enable_vol_reset", "label": "启用波动率重置", "param_type": "boolean",
                 "default_value": True, "required": False,
                 "description": "是否启用波动率重置功能"},
            ],
        })
    except ImportError:
        pass
    
    # --- 2. 双层窗口波动率控制器 ---
    try:
        from app.control.volatility.dual_window_vol import DualWindowVolMonitor
        templates.append({
            "code": "ctrl_dual_window_vol",
            "name": "双层窗口波动率",
            "category": "control",
            "description": "双窗口平均vol估计 + 阈值重置（超阈值降杠杆），适用于趋势策略。",
            "source_code": _get_strategy_source_with_imports(DualWindowVolMonitor),
            "parameters": [
                {"name": "annualization_factor", "label": "年化因子", "param_type": "number",
                 "default_value": 260, "required": False, "min_value": 52, "max_value": 365,
                 "description": "波动率年化因子（期货口径默认 260，股票常用 252）"},
                {"name": "vol_method", "label": "波动率估计方法", "param_type": "select",
                 "default_value": "rolling", "required": False,
                 "options": [["rolling", "滚动窗口标准差"], ["ewma", "指数加权（EWMA）"]],
                 "description": "组合波动率估计方法"},
                {"name": "vc_short", "label": "短期波动率窗口", "param_type": "number",
                 "default_value": 20, "required": False, "min_value": 5, "max_value": 60,
                 "description": "短期波动率计算窗口(交易日)"},
                {"name": "vc_long", "label": "长期波动率窗口", "param_type": "number",
                 "default_value": 60, "required": False, "min_value": 20, "max_value": 260,
                 "description": "长期波动率计算窗口(交易日)"},
                {"name": "target_vol", "label": "目标年化波动率", "param_type": "number",
                 "default_value": 0.03, "required": False, "min_value": 0.01, "max_value": 0.20,
                 "description": "组合目标年化波动率"},
                {"name": "enable_vol_reset", "label": "启用波动率重置", "param_type": "boolean",
                 "default_value": True, "required": False,
                 "description": "是否启用波动率重置功能"},
                {"name": "vol_reset_threshold", "label": "波动率重置阈值", "param_type": "number",
                 "default_value": 0.06, "required": False, "min_value": 0.02, "max_value": 0.30,
                 "description": "触发波动率重置的阈值(默认6%)"},
            ],
        })
    except ImportError:
        pass

    # --- 3. 波动率定标：已回归策略参数（vol_targeting_*），不再作为控制器模板 ---

    # --- 4. 编制规则波动率控制器（已移除，与滚动窗口波动率重复）---


def _convert_selection_dict_to_params(schema_dict: dict) -> List[Dict[str, Any]]:
    """
    将 selection 模块的 dict 格式 schema 转换为模板参数格式。
    
    selection 的 get_param_schema() 返回普通 dict，不是 StrategyParamSchema。
    """
    params = []
    type_mapping = {
        "number": "number",
        "slider": "slider",
        "select": "select",
        "text": "string",
        "checkbox": "boolean",
        "boolean": "boolean",
    }
    for p in schema_dict.get("params", []):
        param_dict = {
            "name": p.get("name"),
            "label": p.get("label", p.get("name")),
            "param_type": type_mapping.get(p.get("type"), "string"),
            "default_value": p.get("default"),
            "required": p.get("required", False),
            "description": p.get("description", ""),
            "min_value": p.get("min_value"),
            "max_value": p.get("max_value"),
        }
        if "step" in p:
            param_dict["step"] = p["step"]
        if "condition" in p:
            param_dict["condition"] = p["condition"]
        if "group" in p:
            param_dict["group"] = p["group"]
        if "options" in p:
            opts = p["options"]
            if opts and isinstance(opts[0], tuple):
                # 保留 [value, label] 格式，前端可显示中文标签
                param_dict["options"] = [[o[0], o[1]] for o in opts]
            else:
                param_dict["options"] = opts
        params.append(param_dict)
    return params


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
            "boolean": "boolean",
            "dict": "dict",
            "max_weight_dict": "max_weight_dict",
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
        
        # 处理条件显示字段
        if hasattr(param, 'condition') and param.condition is not None:
            param_dict["condition"] = param.condition
        
        # 处理隐藏标记
        if getattr(param, 'hidden', False):
            param_dict["hidden"] = True
        
        # 处理参数分组
        if getattr(param, 'group', 'core') != 'core':
            param_dict["group"] = param.group
        
        # 处理选项
        if param.options:
            # 保留 [(value, label), ...] 格式，前端可显示中文标签
            if isinstance(param.options[0], tuple):
                param_dict["options"] = [[opt[0], opt[1]] for opt in param.options]
            else:
                param_dict["options"] = param.options
        
        params.append(param_dict)
    
    return params
