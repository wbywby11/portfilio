"""监测引擎适配器：统一通过 CompositionPipeline（三层引擎）计算权重

替代 strategy_engine.py 的独立实现，确保监测与回测使用同一套策略逻辑。

两种构建路径：
1. from MonitoredStrategy（新路径）：直接从模型的 composition/strategy_params 构建
2. from MonitorRuntimeConfig（兼容路径）：将旧运行时配置翻译为 composition 格式
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 动态 Allocator 解析（即插即用核心）
# ---------------------------------------------------------------------------

def _resolve_allocator_class(template_code: str):
    """从 template_code 动态加载对应的 allocator 策略类。

    查找统一策略清单（strategy_manifest.py），
    通过 importlib 加载模块并返回策略类。
    任何已注册的策略均可通过此函数获取，无需硬编码。
    """
    from app.allocation.strategy_manifest import resolve_class
    return resolve_class(template_code)


def _build_strategy_params_from_rt(rt, template_code: str, composition: Dict) -> Dict[str, Any]:
    """从 MonitorRuntimeConfig 构建 strategy_params。

    根据 template_code 决定参数构建逻辑：
    - vol_scaled_budget: 保留原有 TVB 参数翻译
    - 其他策略: 直接使用 rt.strategy_params（已在模型中完整保存）
    """
    selector_type = composition.get("selector")

    if template_code == "vol_scaled_budget":
        # TVB 专用参数翻译（保留向后兼容）
        params: Dict[str, Any] = {
            "target_vol": rt.target_vol,
            "max_total_leverage": rt.max_leverage,
            "vol_windows": "22,65,130",
            "min_history_days": getattr(rt, "min_history_momentum", None) or 260,
            "lookback_days": 260,
            "enable_vol_reset": True,
            "vol_reset_threshold": rt.vol_trigger_threshold,
        }
        if rt.weight_caps:
            params["weight_caps"] = rt.weight_caps

        if selector_type == "sharpe":
            params["budget_source"] = "selection_equal"
            composition["n_assets"] = rt.strategy_params.get("n_assets", 13)
            composition["selection_params"] = {
                "sharp_windows": "22,65,260",
                "tie_break_window": 22,
                "min_history_days": 260,
            }
            params["sharp_windows"] = "22,65,260"
            params["tie_break_window"] = 22
        elif selector_type == "momentum_reversal":
            params["budget_source"] = "tag_based"
            n_momentum = rt.strategy_params.get("n_momentum", 7)
            n_reversal = rt.strategy_params.get("n_reversal", 1)
            params["n_momentum"] = n_momentum
            params["n_reversal"] = n_reversal
            mom_w = rt.mom_windows or (20, 60, 120, 250)
            macd_w = rt.macd_windows or (40, 80, 120, 160)
            rev_w = rt.reversal_windows or (10, 22)
            params["momentum_windows"] = ",".join(str(w) for w in mom_w)
            params["macd_windows"] = ",".join(str(w) for w in macd_w)
            params["reversal_windows"] = ",".join(str(w) for w in rev_w)
            params["min_history_reversal"] = getattr(rt, "min_history_reversal", None) or 22
            composition["selection_params"] = {
                "n_momentum": n_momentum,
                "n_reversal": n_reversal,
                "momentum_windows": params["momentum_windows"],
                "macd_windows": params["macd_windows"],
                "reversal_windows": params["reversal_windows"],
                "min_history_days": params["min_history_days"],
                "min_history_reversal": params["min_history_reversal"],
            }
        else:
            params["budget_source"] = "selection_equal"

        # 合并 rt.strategy_params 中的额外参数
        for k, v in (rt.strategy_params or {}).items():
            params.setdefault(k, v)
        return params

    # ---- 通用策略：直接使用 rt.strategy_params ----
    params = dict(rt.strategy_params or {})
    if rt.weight_caps and "weight_caps" not in params:
        params["weight_caps"] = rt.weight_caps
    return params


class MonitorEngineAdapter:
    """监测引擎适配器：封装 CompositionPipeline，提供与原 StrategyEngine 兼容的接口。

    核心方法：
    - compute_weights(prices_df, calc_date) → Dict[str, float]
      替代 StrategyEngine.run_asset_selection() + run_weight_calculation()
    """

    def __init__(self, pipeline, asset_codes: List[str]):
        """
        Args:
            pipeline: CompositionPipeline 实例
            asset_codes: 资产池代码列表（用于补全权重）
        """
        self._pipeline = pipeline
        self._asset_codes = list(asset_codes)

    @property
    def pipeline(self):
        return self._pipeline

    def compute_weights(
        self,
        prices_df: pd.DataFrame,
        calc_date: pd.Timestamp,
    ) -> Dict[str, float]:
        """计算指定日期的目标权重（替代 StrategyEngine 的两步调用）。

        Args:
            prices_df: 价格矩阵（index=日期, columns=资产代码）
            calc_date: 计算日（月末日期）

        Returns:
            {asset_code: weight} 字典，所有资产池中的资产都有值（未选中为0）
        """
        # 截取 calc_date 及之前的数据（模拟回测中"只看历史"）
        history = prices_df.loc[:calc_date]
        if history.empty or len(history) < 30:
            logger.warning(f"历史数据不足（{len(history)}行），无法计算权重")
            return {code: 0.0 for code in self._asset_codes}

        signal = self._pipeline.generate_target_weights(history, calc_date)
        weights = signal.target_weights

        # 确保所有资产池中的资产都有权重值
        return {code: weights.get(code, 0.0) for code in self._asset_codes}

    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        prices_df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """计算监控指标（波动率等），委托给 Pipeline。"""
        return self._pipeline.compute_monitoring_metrics(current_weights, prices_df)

    def check_volatility_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ):
        """检查波动率触发（紧急降杠杆），委托给 Pipeline。"""
        return self._pipeline.check_volatility_trigger(current_weights, prices, **params)

    def compute_volatility_reset_weights(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ):
        """计算波动率重置权重，委托给 Pipeline。"""
        return self._pipeline.compute_volatility_reset_weights(
            current_weights, prices, **params
        )

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------

    @classmethod
    def from_monitored_strategy(cls, strategy) -> "MonitorEngineAdapter":
        """从 MonitoredStrategy 模型构建适配器（新路径）。

        动态解析 composition.allocator 对应的策略类，
        任何已注册策略均可自动加载，无需硬编码。
        """
        from app.backtesting.runner import build_pipeline
        from app.allocation.builtin_templates import COMPOSITION_DEFAULTS

        asset_codes = strategy.asset_codes
        composition = dict(strategy.composition or {})
        params = dict(strategy.strategy_params or {})

        # 注入权重上限
        if strategy.weight_caps and "weight_caps" not in params:
            params["weight_caps"] = strategy.weight_caps

        # 动态解析 allocator
        allocator_name = composition.get("allocator") or "vol_scaled_budget"
        try:
            allocator_cls = _resolve_allocator_class(allocator_name)
        except ValueError:
            logger.warning(f"无法解析 allocator {allocator_name!r}，回退到 vol_scaled_budget")
            allocator_cls = _resolve_allocator_class("vol_scaled_budget")
            allocator_name = "vol_scaled_budget"
            composition["allocator"] = allocator_name

        allocator = allocator_cls()
        pipeline = build_pipeline(
            allocator=allocator,
            thscodes=asset_codes,
            composition=composition,
            strategy_params=params,
        )
        return cls(pipeline=pipeline, asset_codes=asset_codes)

    @classmethod
    def from_runtime_config(cls, rt) -> "MonitorEngineAdapter":
        """从 MonitorRuntimeConfig 构建适配器（兼容旧路径）。

        动态解析 template_code 对应的 allocator，
        从 COMPOSITION_DEFAULTS 获取默认 composition，
        任何已注册策略均可自动加载，无需硬编码。
        """
        from app.backtesting.runner import build_pipeline
        from app.allocation.builtin_templates import COMPOSITION_DEFAULTS

        asset_codes = list(rt.asset_list)
        template_code = getattr(rt, "template_code", "") or "vol_scaled_budget"

        # 1. 从 COMPOSITION_DEFAULTS 获取默认 composition（含 fallback）
        base_comp = COMPOSITION_DEFAULTS.get(template_code, {
            "selector": None, "allocator": template_code, "controller": None
        })

        # 2. 动态加载 allocator
        try:
            allocator_cls = _resolve_allocator_class(template_code)
        except ValueError:
            logger.warning(f"无法解析 allocator {template_code!r}，回退到 vol_scaled_budget")
            allocator_cls = _resolve_allocator_class("vol_scaled_budget")
            template_code = "vol_scaled_budget"
            base_comp = COMPOSITION_DEFAULTS.get("vol_scaled_budget")

        allocator = allocator_cls()

        # 3. 翻译 selector_type（兼容旧数据中的 hybrid/reversal 别名）
        selector_type = getattr(rt, "selector_type", None)
        if selector_type in ("hybrid", "reversal"):
            selector_type = "momentum_reversal"

        # 4. 构建 composition（复用 base_comp，覆盖 selector）
        composition = {**base_comp, "selector": selector_type or base_comp.get("selector")}
        composition.setdefault("schedule", {"rebalance_freq": "month_end", "execution_delay": 2})

        # 5. 构建 strategy_params（通用参数构建器）
        params = _build_strategy_params_from_rt(rt, template_code, composition)

        pipeline = build_pipeline(
            allocator=allocator,
            thscodes=asset_codes,
            composition=composition,
            strategy_params=params,
        )
        return cls(pipeline=pipeline, asset_codes=asset_codes)

    @classmethod
    def from_researcher_strategy(cls, code: str) -> "MonitorEngineAdapter":
        """从研究员策略 code 构建适配器。

        Args:
            code: 研究员策略码（如 'hybrid_12', 'sharpe_18'）
        """
        from app.monitor.researcher_strategies import get_researcher_strategy

        strategy = get_researcher_strategy(code)
        if strategy is None:
            raise ValueError(f"未知的研究员策略: {code!r}")

        pipeline = strategy.build_pipeline()
        return cls(pipeline=pipeline, asset_codes=strategy.asset_codes)


class PortfolioMonitorAdapter:
    """组合监测适配器：多个子策略在 NAV 层复合。

    用于 source_type='portfolio' 的监测策略。
    每个子策略独立计算权重和 NAV，然后按配置权重复合为组合 NAV。
    """

    def __init__(
        self,
        sub_adapters: Dict[str, MonitorEngineAdapter],
        sub_weights: Dict[str, float],
        rebalance_freq: str = "monthly",
    ):
        """
        Args:
            sub_adapters: {sub_id: MonitorEngineAdapter} 子策略适配器映射
            sub_weights: {sub_id: weight} 子策略配置权重（总和=1）
            rebalance_freq: 组合再平衡频率
        """
        self._sub_adapters = sub_adapters
        self._sub_weights = sub_weights
        self._rebalance_freq = rebalance_freq

    @property
    def sub_adapters(self) -> Dict[str, MonitorEngineAdapter]:
        return self._sub_adapters

    @property
    def sub_weights(self) -> Dict[str, float]:
        return self._sub_weights

    def compute_sub_weights(
        self,
        prices_df: pd.DataFrame,
        calc_date: pd.Timestamp,
    ) -> Dict[str, Dict[str, float]]:
        """计算每个子策略的目标权重。

        Returns:
            {sub_id: {asset_code: weight}}
        """
        result = {}
        for sub_id, adapter in self._sub_adapters.items():
            result[sub_id] = adapter.compute_weights(prices_df, calc_date)
        return result

    def compute_composite_weights(
        self,
        prices_df: pd.DataFrame,
        calc_date: pd.Timestamp,
    ) -> Dict[str, float]:
        """计算组合层面的加权资产权重。

        将各子策略权重按配置比例加权合并为单一资产权重向量。
        用于初始化或再平衡日的组合级权重。
        """
        sub_weights_map = self.compute_sub_weights(prices_df, calc_date)
        composite: Dict[str, float] = {}

        for sub_id, asset_weights in sub_weights_map.items():
            w = self._sub_weights.get(sub_id, 0.0)
            for code, weight in asset_weights.items():
                composite[code] = composite.get(code, 0.0) + w * weight

        return composite

    @classmethod
    def from_monitored_strategy(cls, strategy) -> "PortfolioMonitorAdapter":
        """从 MonitoredStrategy（source_type=portfolio）构建组合适配器。

        composition 格式：
        {
            "sub_strategies": [
                {"ref": "hybrid_12", "weight": 0.6},
                {"ref": "sharpe_18", "weight": 0.4},
            ],
            "rebalance_freq": "monthly",
        }
        """
        from app.monitor.researcher_strategies import get_researcher_strategy

        composition = strategy.composition or {}
        sub_configs = composition.get("sub_strategies", [])
        rebalance_freq = composition.get("rebalance_freq", "monthly")

        sub_adapters: Dict[str, MonitorEngineAdapter] = {}
        sub_weights: Dict[str, float] = {}

        for sub_cfg in sub_configs:
            ref = sub_cfg.get("ref", "")
            weight = float(sub_cfg.get("weight", 0.0))

            # 尝试从研究员策略构建
            researcher = get_researcher_strategy(ref)
            if researcher is not None:
                sub_adapters[ref] = MonitorEngineAdapter.from_researcher_strategy(ref)
                sub_weights[ref] = weight
                continue

            # TODO: 支持从系统策略模型 / 其他组合构建
            logger.warning(f"组合子策略 {ref!r} 无法解析，跳过")

        if not sub_adapters:
            raise ValueError("组合监测策略无有效子策略")

        return cls(
            sub_adapters=sub_adapters,
            sub_weights=sub_weights,
            rebalance_freq=rebalance_freq,
        )
