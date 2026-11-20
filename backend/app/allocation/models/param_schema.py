"""策略参数Schema定义，用于前后端参数配置与验证."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Optional


@dataclass
class ParamSchema:
    """单个策略参数的元信息定义.
    
    用于前端动态生成表单，以及后端参数验证。
    """
    
    name: str  # 参数名称（内部标识）
    label: str  # 参数显示名称（前端展示）
    type: Literal["number", "slider", "select", "text", "checkbox", "dict", "max_weight_dict", "boolean"]  # 输入组件类型
    default: Any  # 默认值
    description: str = ""  # 参数说明
    
    # 数值类参数
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    
    # 选择类参数
    options: Optional[List[tuple[Any, str]]] = None  # [(value, label), ...]
    
    # 条件显示（前端根据其他参数值决定是否展示）
    # 格式: {"field": "budget_source", "value": "selection_equal"}
    condition: Optional[dict[str, Any]] = None
    
    # 前端隐藏（不在表单中展示，但保存时仍写入固定值）
    hidden: bool = False
    
    # 参数分组：core=核心参数（默认展示），advanced=高级参数（折叠展示）
    group: str = "core"
    
    # 验证规则
    required: bool = False
    
    def validate(self, value: Any) -> tuple[bool, str]:
        """验证参数值是否符合规范.
        
        Returns:
            (is_valid, error_message)
        """
        # 必填检查
        if self.required and value is None:
            return False, f"参数 {self.label} 为必填项"
        
        if value is None:
            return True, ""
        
        # 类型检查
        if self.type in ["number", "slider"]:
            try:
                value = float(value)
            except (ValueError, TypeError):
                return False, f"参数 {self.label} 必须为数值"
            
            if self.min_value is not None and value < self.min_value:
                return False, f"参数 {self.label} 不能小于 {self.min_value}"
            
            if self.max_value is not None and value > self.max_value:
                return False, f"参数 {self.label} 不能大于 {self.max_value}"
        
        elif self.type == "select":
            if self.options:
                valid_values = [opt[0] for opt in self.options]
                if value not in valid_values:
                    return False, f"参数 {self.label} 的值不在可选范围内"
        
        elif self.type == "dict":
            if isinstance(value, str):
                import json
                try:
                    json.loads(value)
                except Exception:
                    return False, f"参数 {self.label} 必须是有效的JSON字符串"
            elif not isinstance(value, dict):
                return False, f"参数 {self.label} 必须是字典或JSON字符串"
        
        return True, ""


def vol_targeting_param_group() -> List[ParamSchema]:
    """收益层波动率定标参数组（策略自身计算，非控制器）.

    需要定标能力的分配器在 get_param_schema 的 params 里展开本组即可：
    参数随模型 parameters 持久化、前端模板驱动渲染，回测引擎直读
    （见 BacktestEngine._get_return_targeting_params，口径对齐 GMSI 2.0
    原型 raw_ret × leverage.shift(1)）。
    """
    cond = {"field": "vol_targeting_enabled", "value": True}
    return [
        ParamSchema(
            name="vol_targeting_enabled", label="波动率定标",
            type="boolean", default=False,
            description=(
                "启用后按目标波动率逐日缩放策略收益："
                "leverage = clip(目标vol / 实现vol, 上下界)，"
                "GMSI 2.0 母/子层口径，不产生调仓事件"
            ),
        ),
        ParamSchema(
            name="vol_targeting_target", label="定标目标波动率",
            type="number", default=0.03,
            min_value=0.005, max_value=0.50, step=0.005,
            description="年化目标波动率，如 0.03 = 3%",
            condition=cond,
        ),
        ParamSchema(
            name="vol_targeting_method", label="波动率估计方法",
            type="select", default="rolling",
            options=[("rolling", "滚动窗口标准差"), ("ewma", "指数加权（EWMA）")],
            description="实现波动率的估计方法（双窗口取平均）",
            condition=cond,
        ),
        ParamSchema(
            name="vol_targeting_short_window", label="定标短窗口",
            type="number", default=20,
            min_value=5, max_value=60, step=1,
            description="短期波动率窗口（交易日）",
            condition=cond,
        ),
        ParamSchema(
            name="vol_targeting_long_window", label="定标长窗口",
            type="number", default=60,
            min_value=20, max_value=260, step=5,
            description="长期波动率窗口（交易日）",
            condition=cond,
        ),
        ParamSchema(
            name="vol_targeting_annualization", label="定标年化因子",
            type="number", default=260,
            min_value=52, max_value=365, step=1,
            description="波动率年化因子（期货口径默认 260，股票常用 252）",
            condition=cond,
        ),
        ParamSchema(
            name="vol_targeting_leverage_min", label="定标杠杆下界",
            type="number", default=0.1,
            min_value=0.0, max_value=1.0, step=0.05,
            description="杠杆缩放的最小倍数（按资产类别预设：债券偏高、股票/商品中等）",
            condition=cond,
        ),
        ParamSchema(
            name="vol_targeting_leverage_max", label="定标杠杆上界",
            type="number", default=5.0,
            min_value=1.0, max_value=10.0, step=0.5,
            description="杠杆缩放的最大倍数（按资产类别预设：债券偏高、股票/商品中等）",
            condition=cond,
        ),
    ]


def model_level_param_group() -> List[ParamSchema]:
    """模型级通用执行参数组（引擎/调度/数据源层消费，非 allocator 自有）.

    这些参数由系统通用机制消费：execution_delay 覆盖调度声明的执行延迟
    （schedule.resolve_execution_schedule）；preserve_price_gaps 声明信号
    计算使用保留缺日 NaN 的价格矩阵（数据源层）；inception_weights 声明
    期初建仓权重（引擎 initial_weights）。需要暴露给前端配置的分配器在
    get_param_schema 的 params 里展开本组即可。

    注：逐日推演日历口径不再作为可配置参数——系统策略恒用所选资产价格
    日期并集（与回测轴同源）；Mongo trade_dates 仅研究员策略 sharpe_18/
    hybrid_12 内部使用，不对系统策略暴露。
    """
    return [
        ParamSchema(
            name="execution_delay", label="执行延迟（T+N）",
            type="number", default=0,
            min_value=0, max_value=10, step=1,
            group="advanced",
            description="信号日到成交日的交易日延迟，覆盖模板调度声明的默认值",
        ),
        ParamSchema(
            name="preserve_price_gaps", label="缺日保真",
            type="boolean", default=False,
            group="advanced",
            description=(
                "开启后信号计算使用保留品种缺日 NaN 的价格矩阵，"
                "缺日品种的收益率/窗口计算传播 NaN 并退出候选"
                "（数据源存在零星缺日且需对齐原型口径时启用）"
            ),
        ),
        ParamSchema(
            name="inception_weights", label="期初建仓权重",
            type="dict", default={},
            group="advanced",
            description=(
                "基日初始持仓权重（资产代码→权重），留空则回测起始为空仓"
                "等待首次调仓；指数类策略从基日起满仓运行时声明"
            ),
        ),
        ParamSchema(
            name="inception_weights_auto_normalize", label="期初权重自动归一化",
            type="boolean", default=False,
            group="advanced",
            description="期初建仓权重之和不为 1 时是否自动归一化",
        ),
    ]


@dataclass
class StrategyParamSchema:
    """策略完整参数Schema.

    包含策略的所有参数定义和元信息。
    """

    strategy_type: str  # 策略类型标识
    display_name: str  # 策略显示名称
    description: str  # 策略说明
    params: List[ParamSchema]  # 参数列表

    # 扩展：支持的监控指标及其对应的阈值参数
    # 格式: [{"name": "portfolio_volatility", "label": "组合波动率", "threshold_param": "vol_reset_threshold"}]
    monitoring_metrics: List[dict[str, str]] = None

    # 三层组合配置：selector + allocator + controller
    # 格式: {"selector": "momentum", "allocator": "risk_parity", "controller": "rolling_vol", "schedule": {...}}
    composition: Optional[dict[str, Any]] = None

    # 分配器内部已处理杠杆缩放（Pipeline 不应再次缩放）
    internal_leverage: bool = False

    # 回测快照的持仓权重口径：
    # "actual" — 按市值归一化的实际权重（权重和恒为 1）
    # "target" — 策略下发的目标权重（杠杆策略权重和可 >1，市值归一化会抹平杠杆）
    # 引擎据此声明选择展示口径，不得按策略类名分支。
    snapshot_weight_source: str = "actual"

    # 信号时点口径：
    # "prev_close" — 默认，用前一日收盘算权重、当日收盘成交（无前视）
    # "execution_bar" — 用执行日当日收盘价做信号并当日成交
    #   （如类雪球 Delta 对冲，对齐四象限原型当日定价调仓语义；
    #   决策与成交同价，不构成前视）
    signal_timing: str = "prev_close"
    
    def validate_params(self, params_dict: dict[str, Any]) -> tuple[bool, List[str]]:
        """验证参数字典是否符合Schema定义.
        
        Returns:
            (is_valid, error_messages)
        """
        errors = []
        
        for param_schema in self.params:
            value = params_dict.get(param_schema.name)
            is_valid, error_msg = param_schema.validate(value)
            
            if not is_valid:
                errors.append(error_msg)
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> dict:
        """转换为字典格式，便于前端使用."""
        import json

        def serialize_value(val, p_type):
            if p_type == "dict" and isinstance(val, dict):
                return json.dumps(val, ensure_ascii=False)
            return val

        return {
            "strategy_type": self.strategy_type,
            "display_name": self.display_name,
            "description": self.description,
            "monitoring_metrics": self.monitoring_metrics or [],
            "composition": self.composition,
            "params": [
                {
                    "name": p.name,
                    "label": p.label,
                    "type": p.type,
                    "default": serialize_value(p.default, p.type),
                    "description": p.description,
                    "min_value": p.min_value,
                    "max_value": p.max_value,
                    "step": p.step,
                    "options": p.options,
                    "required": p.required,
                    "condition": p.condition,
                    "hidden": p.hidden,
                    "group": p.group,
                }
                for p in self.params
            ],
        }
