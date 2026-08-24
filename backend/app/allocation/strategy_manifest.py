"""统一策略清单 — 一处注册、处处自动派生。

新增 Allocation 策略只需：
1. 在 app/allocation/models/ 下编写策略类（继承 BaseStrategyModel）
2. 在下方 STRATEGY_MANIFEST 中添加一行 StrategyEntry

其余（模板生成、类路径映射、composition 配置）全部由本清单自动派生，
无需再改 builtin_templates.py / model_template_service.py / strategy_model_service.py。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class StrategyEntry:
    """单个 Allocation 策略的注册信息。"""

    class_path: str  # 完整类路径，如 "app.allocation.models.risk_parity.RiskParityStrategy"
    name: str  # 中文展示名称
    description: str  # 策略描述（用于模板）
    composition: Dict[str, Any] = field(default_factory=dict)
    # composition 格式: {"selector": None, "allocator": "<code>", "controller": None, ...}
    # 若为空字典，则自动填充为 {"selector": None, "allocator": code, "controller": None}


# ---------------------------------------------------------------------------
# 策略清单（唯一注册点）
# ---------------------------------------------------------------------------

STRATEGY_MANIFEST: Dict[str, StrategyEntry] = {
    "risk_parity": StrategyEntry(
        class_path="app.allocation.models.risk_parity.RiskParityStrategy",
        name="风险平价",
        description="基于SLSQP优化使各资产风险贡献相等，Maillard et al. (2010) 经典ERC框架。",
        composition={"selector": None, "allocator": "risk_parity", "controller": None},
    ),
    "mean_variance": StrategyEntry(
        class_path="app.allocation.models.mean_variance.MeanVarianceOptimization",
        name="均值-方差 (MVO)",
        description="Markowitz (1952) 现代投资组合理论，支持最小方差/目标收益/最大夏普三种优化模式。",
        composition={"selector": None, "allocator": "mean_variance", "controller": None},
    ),
    "cso": StrategyEntry(
        class_path="app.allocation.models.enhanced_risk_parity.CovarianceSharpeOptimization",
        name="协方差-夏普 (CSO)",
        description="双目标优化：最小化组合方差同时引入Sharpe增强项，原创大类资产配置框架。",
        composition={"selector": None, "allocator": "cso", "controller": None},
    ),
    "risk_budget": StrategyEntry(
        class_path="app.allocation.models.risk_budget.RiskBudgetStrategy",
        name="风险预算 (RB)",
        description="SLSQP优化匹配用户指定风险预算，支持Sharpe/Sortino/手动三种预算模式。",
        composition={"selector": None, "allocator": "risk_budget", "controller": None},
    ),
    "factor_rp": StrategyEntry(
        class_path="app.allocation.models.factor_risk_parity.FactorRiskParityStrategy",
        name="因子风险平价 (Factor RP)",
        description="PCA主成分分解后在因子空间实现等风险贡献，控制因子维度风险暴露。",
        composition={"selector": None, "allocator": "factor_rp", "controller": None},
    ),
    "vol_scaled_budget": StrategyEntry(
        class_path="app.allocation.models.vol_scaled_budget.VolScaledBudgetStrategy",
        name="目标波动率预算 (TVB)",
        description="闭式波动率定标 w=b×σ_tgt/σ，支持标签/选择/反方差三种预算源，三重约束缩放。",
        composition={"selector": None, "allocator": "vol_scaled_budget", "controller": "rolling_vol"},
    ),
    "manual_allocation": StrategyEntry(
        class_path="app.allocation.models.manual_allocation.ManualAllocationStrategy",
        name="主观固定权重",
        description="用户直接指定各资产权重，适用于基准组合构建或主观判断配置。",
        composition={"selector": None, "allocator": "manual_allocation", "controller": None},
    ),
    "black_litterman": StrategyEntry(
        class_path="app.allocation.models.black_litterman.BlackLittermanOptimization",
        name="Black-Litterman 贝叶斯",
        description="逆优化推导市场隐含收益，Idzorek方法融合主观观点，贝叶斯后验MVO优化。",
        composition={"selector": None, "allocator": "black_litterman", "controller": None},
    ),
    "etf_cycle_rotation": StrategyEntry(
        class_path="app.allocation.models.etf_cycle_rotation.ETFCycleRotationStrategy",
        name="等权",
        description="对选中的资产做等权 1/N 分配，资产筛选请在「资产选择」区域配置。",
        composition={"selector": "etf_rotation", "allocator": "etf_cycle_rotation", "controller": None},
    ),
    "trend_cross_sectional": StrategyEntry(
        class_path="app.allocation.models.trend_cross_sectional.TrendCrossSectionalStrategy",
        name="趋势-截面复合",
        description="趋势跟踪+截面动量双信号复合，按权重混合后归一化输出，支持多空交易。",
        composition={
            "selector": None,
            "allocator": "trend_cross_sectional",
            "controller": "dual_window_vol",
            "multi_signal": [
                {"selector": "trend_following", "weight_param": "combo_weight_tf", "weight": 0.5},
                {"selector": "cross_sectional_long_short", "weight_param": "combo_weight_cs", "weight": 0.5},
            ],
        },
    ),
    "signal_weighted": StrategyEntry(
        class_path="app.allocation.models.signal_weighted.SignalWeightedStrategy",
        name="信号加权",
        description="根据上游选择器输出的信号分数分配权重，信号越强权重越大。无信号时退化为等权配置。",
        composition={"selector": None, "allocator": "signal_weighted", "controller": None},
    ),
    "snowball_delta_hedge": StrategyEntry(
        class_path="app.allocation.models.snowball_delta_hedge.SnowballDeltaHedgeStrategy",
        name="类雪球Delta对冲",
        description="蒙特卡洛定价雪球期权Delta，动态调整ETF仓位复制雪球结构收益，支持单/多合约滚动。",
        composition={"selector": None, "allocator": "snowball_delta_hedge", "controller": None},
    ),
}


# ---------------------------------------------------------------------------
# 兼容旧 code 的别名映射（旧模板 code → 当前策略 code）
# ---------------------------------------------------------------------------

LEGACY_ALIASES: Dict[str, str] = {
    "risk_budget_target_vol": "vol_scaled_budget",
    "sharpe_risk_budget": "vol_scaled_budget",
    "momentum_risk_parity": "vol_scaled_budget",
}


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def get_class_paths() -> Dict[str, str]:
    """返回 {code: class_path} 映射（含 LEGACY_ALIASES），供动态加载使用。"""
    paths = {code: entry.class_path for code, entry in STRATEGY_MANIFEST.items()}
    for alias, target in LEGACY_ALIASES.items():
        paths[alias] = STRATEGY_MANIFEST[target].class_path
    return paths


def get_composition_defaults() -> Dict[str, Dict[str, Any]]:
    """返回 {code: composition} 映射，替代原 COMPOSITION_DEFAULTS。"""
    result = {}
    for code, entry in STRATEGY_MANIFEST.items():
        comp = entry.composition if entry.composition else {
            "selector": None, "allocator": code, "controller": None
        }
        result[code] = comp
    return result


def resolve_class(template_code: str):
    """根据 template_code 加载并返回策略类（支持 LEGACY_ALIASES）。

    Raises:
        ValueError: template_code 未注册
        ImportError / AttributeError: 类路径无效
    """
    paths = get_class_paths()
    qualified = paths.get(template_code)
    if not qualified:
        available = ", ".join(sorted(STRATEGY_MANIFEST.keys()))
        raise ValueError(
            f"未知的策略 template_code: {template_code!r}。"
            f"可用策略: {available}"
        )
    module_path, cls_name = qualified.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, cls_name)


def resolve_class_safe(template_code: str):
    """同 resolve_class，但加载失败返回 None 而非抛异常。"""
    try:
        return resolve_class(template_code)
    except Exception:
        return None
