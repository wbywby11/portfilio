"""统一策略清单 — 一处注册、处处自动派生。

新增策略只需两步：
1. 编写策略类（继承 BaseStrategyModel）
   - 三层组合形态 → app/allocation/models/<code>.py
   - 打包独立形态 → app/standalone_strategies/<code>/strategy.py
2. 在下方 STRATEGY_MANIFEST 中添加一行 StrategyEntry
   （打包独立形态带 strategy_form="standalone"）

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
    strategy_form: str = "composite"
    # 策略形态：composite=三层组合（选样/赋权/风控各层可独立复用库内模块）
    #           standalone=打包独立（选样/赋权/约束/风控全部写在策略类内，
    #                        composition 只把自己的 code 填进 allocator，
    #                        selector/controller 保持 None，前端隐藏三层配置卡片）
    # 由 get_builtin_templates() 派生进 ModelTemplate.strategy_form，前端据此渲染。


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
    "nous_low_vol": StrategyEntry(
        class_path="app.standalone_strategies.nous_low_vol.strategy.NousLowVolStrategy",
        name="夏普风险平价",
        description=(
            "夏普动量选样 + 朴素风险平价基础权重 + 目标波动率档缩放 + 组约束顺序投影"
            "（QDII/商品/黄金上限、A股下限抬升、综合风险预算与混合风险预算封顶），"
            "日度风控写在包内；支持 FOF 三档、含港股直投档、无商品低波档三类口径，"
            "改分组与约束参数即可切换；打包独立形态，选样/赋权/约束/风控一体化，"
            "composition 三层全 None。"
        ),
        composition={"selector": None, "allocator": "nous_low_vol", "controller": None},
        strategy_form="standalone",
    ),
    "factor_score_index": StrategyEntry(
        class_path="app.standalone_strategies.factor_score_index.strategy.FactorScoreIndexStrategy",
        name="因子打分指数",
        description=(
            "每个调仓生效日取当期因子截面，逐因子 winsorize 后 min-max 打分"
            "（反向因子取 (max-x)/(max-min)、非正值记 0），综合得分相加 → 行业内前 M"
            " → 全体前 N → 按总市值加权（尾差归市值最大股）；"
            "打包独立形态，选样/打分/赋权一体化，composition 三层全 None，"
            "调仓日由因子截面期日驱动。"
        ),
        composition={"selector": None, "allocator": "factor_score_index", "controller": None},
        strategy_form="standalone",
    ),
    "bond_factor_score_index": StrategyEntry(
        class_path="app.standalone_strategies.bond_factor_score_index.strategy.BondFactorScoreIndexStrategy",
        name="债券券池因子打分指数",
        description=(
            "每个调仓生效日取当期债券券池截面：发行规模/主体规模按名次线性打分、"
            "修正久期按距目标线性扣分，加权合成综合分 → 按券池分组逐组单发行人限额后"
            "取得分前 K 只 → 等权 1/N；截面缺因子列时按指数成分快照全截面等权；"
            "打包独立形态，选样/打分/赋权一体化，composition 三层全 None，"
            "调仓日由券池截面期日驱动。"
        ),
        composition={"selector": None, "allocator": "bond_factor_score_index", "controller": None},
        strategy_form="standalone",
    ),
    "dividend_garp": StrategyEntry(
        class_path="app.standalone_strategies.dividend_garp.strategy.DividendGarpStrategy",
        name="红利 GARP 增强",
        description=(
            "月末信号、次一交易日成交：权益端按红利/成长配比合成实现波动率，参与度 = "
            "clip(目标波动/实现波动, 下界, 上界)；估值序列近 N 年分位做红利估值防守"
            "（高位进入、低位退出、滞回保持）；成长端按相对长期均线的偏离做防守与线性加仓；"
            "再按账户中枢、权益上限/下限得到目标权重，剩余进债券端；"
            "交易成本与指数年费由日结算钩子从现金扣除；打包独立形态，"
            "composition 三层全 None。"
        ),
        composition={"selector": None, "allocator": "dividend_garp", "controller": None},
        strategy_form="standalone",
    ),
    "industry_timing_target_vol": StrategyEntry(
        class_path=(
            "app.standalone_strategies.industry_timing_target_vol.strategy."
            "IndustryTimingTargetVolStrategy"
        ),
        name="行业择时目标波动",
        description=(
            "每日信号、次一交易日成交：月末按分组风险平价 + 目标波动解出中性配置，"
            "三形态（下跌反弹/顶部切换/横盘突破）识别行业时点事件，事件生效时把权益"
            "半仓切成 Top 行业、空窗期在权益内风险平价，融合结果沿中性→候选线段"
            "按总波动上限与主动风险上限收缩；DAR 只压成长仓位，释放资金转入现金；"
            "打包独立形态，composition 三层全 None。"
        ),
        composition={
            "selector": None,
            "allocator": "industry_timing_target_vol",
            "controller": None,
        },
        strategy_form="standalone",
    ),
    "erp_timing_enhance": StrategyEntry(
        class_path=(
            "app.standalone_strategies.erp_timing_enhance.strategy."
            "ErpTimingEnhanceStrategy"
        ),
        name="ERP 择时指数增强",
        description=(
            "月末信号、次一交易日成交：用股息率、十年国债、美债、汇率与中长期贷款合成"
            "改进版 ERP2，取 920 日滚动分位经 sigmoid 映射为权益战略中枢；再用成交活跃度、"
            "行业成交集中度、高低 PB 组收益差三个信号做比例偏离；权益端在基金池内按超额、"
            "信息比率、稳定性、alpha、胜率、t 值、跟踪误差贴近度与风格暴露八项因子做赛道内"
            "相对打分，取前若干只且单赛道设上限后等权买入，剩余权重进债券腿；"
            "打包独立形态，composition 三层全 None。"
        ),
        composition={
            "selector": None,
            "allocator": "erp_timing_enhance",
            "controller": None,
        },
        strategy_form="standalone",
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


def canonical_code(template_code: str) -> str:
    """把旧别名归一为正式 code（非别名原样返回）。

    归一与解析是两件事：``get_class_paths()`` 会把别名也映射进 paths，
    因此别名在 ``resolve_class`` 里永远成功、不经过任何失败分支。
    需要在「解析成功」与「拿到的到底是什么策略」之间对齐时（如监控适配器
    构造 composition 与参数），必须先归一再构造；本函数不改
    ``get_class_paths()`` 的返回值，避免波及 resolve_class 的其他调用方。
    """
    code = str(template_code or "")
    return LEGACY_ALIASES.get(code, code)


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
