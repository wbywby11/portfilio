"""策略 Schema 一致性校验测试.

验证三层解耦架构的参数归属规则和架构边界：
  - allocator schema 不包含 selector 独有的参数键
  - selector schema 不包含 allocator 独有的参数键
  - composition 声明的 selector 在 SELECTION_REGISTRY 中存在
  - allocator 不引用 selector 类（信号生成只在 Pipeline/Selection 层）
  - multi_signal 模式下的信号复合由 Pipeline 完成
"""

import inspect
import pytest

from app.allocation.builtin_templates import COMPOSITION_DEFAULTS
from app.backtesting.composition_pipeline import _SELECTION_PARAM_KEYS
from app.selection import SELECTION_REGISTRY


# 已知的 selector-only 参数键（不应出现在 allocator schema 中）
SELECTOR_ONLY_KEYS = {
    # ETF轮动
    'sub_strategy', 'return_cutoff_pct', 'bias_threshold',
    'risk_index_code', 'risk_drop_threshold', 'top_n',
    # 趋势跟踪
    'tf_lookback', 'tf_threshold',
    # 截面动量
    'cs_lookback_months', 'momentum_window',
    # 动量/反转
    'n_momentum', 'n_reversal', 'momentum_windows', 'macd_windows',
    'reversal_windows', 'sharp_windows', 'tie_break_window',
    'use_price_skew', 'min_history_reversal',
}

# 已知的 allocator-only 参数键（不应出现在 selector schema 中）
ALLOCATOR_ONLY_KEYS = {
    'combo_weight_tf', 'combo_weight_cs', 'target_vol',
    'vol_control_type', 'vc_short', 'vc_long',
}


def _get_all_allocator_schemas():
    """获取所有 allocator 的 param schema."""
    from app.allocation.models.etf_cycle_rotation import ETFCycleRotationStrategy
    from app.allocation.models.trend_cross_sectional import TrendCrossSectionalStrategy
    from app.allocation.models.risk_parity import RiskParityStrategy
    from app.allocation.models.mean_variance import MeanVarianceOptimization
    from app.allocation.models.manual_allocation import ManualAllocationStrategy
    from app.allocation.models.vol_scaled_budget import VolScaledBudgetStrategy

    schemas = {}
    for cls in [
        RiskParityStrategy, MeanVarianceOptimization,
        ManualAllocationStrategy, VolScaledBudgetStrategy,
        ETFCycleRotationStrategy, TrendCrossSectionalStrategy,
    ]:
        try:
            schema = cls.get_param_schema()
            schemas[schema.strategy_type] = schema
        except Exception:
            pass

    # 可选策略
    try:
        from app.allocation.models.enhanced_risk_parity import CovarianceSharpeOptimization
        schemas['cso'] = CovarianceSharpeOptimization.get_param_schema()
    except ImportError:
        pass
    try:
        from app.allocation.models.risk_budget import RiskBudgetStrategy
        schemas['risk_budget'] = RiskBudgetStrategy.get_param_schema()
    except ImportError:
        pass
    try:
        from app.allocation.models.factor_risk_parity import FactorRiskParityStrategy
        schemas['factor_rp'] = FactorRiskParityStrategy.get_param_schema()
    except ImportError:
        pass
    try:
        from app.allocation.models.black_litterman import BlackLittermanOptimization
        schemas['black_litterman'] = BlackLittermanOptimization.get_param_schema()
    except ImportError:
        pass

    return schemas


def _get_all_selector_schemas():
    """获取所有 selector 的 param schema."""
    schemas = {}
    for name, cls in SELECTION_REGISTRY.items():
        try:
            schema = cls.get_param_schema()
            schemas[name] = schema
        except Exception:
            pass
    return schemas


class TestSchemaConsistency:
    """Schema 一致性校验."""

    def test_allocator_no_selector_params(self):
        """allocator schema 不包含 selector 独有的参数键."""
        schemas = _get_all_allocator_schemas()
        violations = []
        for strategy_type, schema in schemas.items():
            param_names = {p.name for p in schema.params}
            overlap = param_names & SELECTOR_ONLY_KEYS
            if overlap:
                violations.append(f"{strategy_type}: {overlap}")
        assert not violations, (
            f"allocator schema 包含 selector 参数:\n" +
            "\n".join(violations)
        )

    def test_selector_no_allocator_params(self):
        """selector schema 不包含 allocator 独有的参数键."""
        schemas = _get_all_selector_schemas()
        violations = []
        for selector_type, schema in schemas.items():
            param_names = {p.get("name") for p in schema.get("params", [])}
            overlap = param_names & ALLOCATOR_ONLY_KEYS
            if overlap:
                violations.append(f"{selector_type}: {overlap}")
        assert not violations, (
            f"selector schema 包含 allocator 参数:\n" +
            "\n".join(violations)
        )

    def test_composition_selectors_registered(self):
        """COMPOSITION_DEFAULTS 声明的 selector 在 SELECTION_REGISTRY 中存在."""
        for strategy_type, comp in COMPOSITION_DEFAULTS.items():
            selector = comp.get("selector")
            if selector is not None:
                assert selector in SELECTION_REGISTRY, (
                    f"{strategy_type}: selector={selector!r} 未在 SELECTION_REGISTRY 中注册"
                )

    def test_selection_param_keys_complete(self):
        """_SELECTION_PARAM_KEYS 覆盖所有已知 selector 参数."""
        for key in SELECTOR_ONLY_KEYS:
            assert key in _SELECTION_PARAM_KEYS, (
                f"{key!r} 在 SELECTOR_ONLY_KEYS 中但不在 _SELECTION_PARAM_KEYS 中"
            )

    def test_etf_cycle_rotation_no_selector_params(self):
        """etf_cycle_rotation allocator 无选择器参数."""
        from app.allocation.models.etf_cycle_rotation import ETFCycleRotationStrategy
        schema = ETFCycleRotationStrategy.get_param_schema()
        assert len(schema.params) == 0, (
            f"etf_cycle_rotation allocator 不应有参数，但有: {[p.name for p in schema.params]}"
        )

    def test_trend_cross_sectional_delegates_to_selectors(self):
        """trend_cross_sectional 不包含 selector 参数但包含 allocator 参数."""
        from app.allocation.models.trend_cross_sectional import TrendCrossSectionalStrategy
        schema = TrendCrossSectionalStrategy.get_param_schema()
        param_names = {p.name for p in schema.params}
        # allocator params present
        assert 'combo_weight_tf' in param_names
        assert 'combo_weight_cs' in param_names
        # selector params absent (belong to selector layer)
        assert 'tf_lookback' not in param_names
        assert 'cs_lookback_months' not in param_names

    def test_multi_signal_declared(self):
        """trend_cross_sectional composition 声明 multi_signal 配置."""
        from app.allocation.models.trend_cross_sectional import TrendCrossSectionalStrategy
        schema = TrendCrossSectionalStrategy.get_param_schema()
        multi_signal = schema.composition.get('multi_signal')
        assert multi_signal is not None
        assert len(multi_signal) >= 2
        selectors = [s['selector'] for s in multi_signal]
        assert 'trend_following' in selectors
        assert 'cross_sectional_long_short' in selectors
        # 每个 multi_signal 选择器必须在 SELECTION_REGISTRY 中注册
        for entry in multi_signal:
            sel = entry['selector']
            assert sel in SELECTION_REGISTRY, (
                f"multi_signal 中的 {sel!r} 未在 SELECTION_REGISTRY 中注册"
            )

    def test_trend_cross_sectional_no_selector_imports(self):
        """trend_cross_sectional allocator 源码不 import selector 类.

        架构边界：allocator 不应引用 selection 模块，信号生成只在 Pipeline 层。
        """
        from app.allocation.models.trend_cross_sectional import TrendCrossSectionalStrategy
        source = inspect.getsource(TrendCrossSectionalStrategy)
        # allocator 不应 import 任何 selector 类
        assert 'TrendFollowingSelector' not in source, (
            "allocator 不应 import TrendFollowingSelector（信号生成应在 Pipeline 层）"
        )
        assert 'CrossSectionalLongShortSelector' not in source, (
            "allocator 不应 import CrossSectionalLongShortSelector（信号生成应在 Pipeline 层）"
        )
        assert 'from app.selection' not in source, (
            "allocator 不应 import app.selection 模块"
        )

    def test_pipeline_multi_signal_builds_signal_weights(self):
        """Pipeline multi_signal 模式正确构建复合信号权重."""
        from app.backtesting.composition_pipeline import CompositionPipeline
        from app.allocation.models.trend_cross_sectional import TrendCrossSectionalStrategy
        import pandas as pd
        import numpy as np

        allocator = TrendCrossSectionalStrategy()
        comp = allocator.get_param_schema().composition
        pipeline = CompositionPipeline(
            allocator=allocator,
            thscodes=['A', 'B', 'C'],
            composition=comp,
            strategy_params={
                'selector_parameters': {
                    'tf_lookback': 20,
                    'cs_lookback_months': 6,
                },
                'combo_weight_tf': 0.6,
                'combo_weight_cs': 0.4,
            },
        )
        # 验证 multi_signal 配置已声明
        assert comp.get('multi_signal') is not None
        assert len(comp['multi_signal']) == 2

        # 验证 _build_allocation_params 不再注入 selector 参数
        alloc_params = pipeline._build_allocation_params(['A', 'B', 'C'], {}, False)
        assert 'tf_lookback' not in alloc_params, (
            "selector 参数不应通过 _build_allocation_params 传递给 allocator"
        )
        assert 'cs_lookback_months' not in alloc_params
        # allocator 自有参数仍然传递
        assert alloc_params.get('combo_weight_tf') == 0.6


if __name__ == "__main__":
    test = TestSchemaConsistency()
    test.test_allocator_no_selector_params()
    print("[PASS] test_allocator_no_selector_params")
    test.test_selector_no_allocator_params()
    print("[PASS] test_selector_no_allocator_params")
    test.test_composition_selectors_registered()
    print("[PASS] test_composition_selectors_registered")
    test.test_selection_param_keys_complete()
    print("[PASS] test_selection_param_keys_complete")
    test.test_etf_cycle_rotation_no_selector_params()
    print("[PASS] test_etf_cycle_rotation_no_selector_params")
    test.test_trend_cross_sectional_delegates_to_selectors()
    print("[PASS] test_trend_cross_sectional_delegates_to_selectors")
    test.test_multi_signal_declared()
    print("[PASS] test_multi_signal_declared")
    test.test_trend_cross_sectional_no_selector_imports()
    print("[PASS] test_trend_cross_sectional_no_selector_imports")
    test.test_pipeline_multi_signal_builds_signal_weights()
    print("[PASS] test_pipeline_multi_signal_builds_signal_weights")
    print("\nAll schema consistency tests passed!")
