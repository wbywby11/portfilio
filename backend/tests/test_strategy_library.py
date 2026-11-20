"""策略库一致性守卫测试（S18）.

治理契约：
  1. 面板声明单源：6 个 standalone 策略的「类方法声明」与「契约派生结果」
     必须一致，不允许两份声明长期漂移；
  2. 别名不是独立策略：LEGACY_ALIASES 只做 code 归一，不产生新的策略身份，
     档案/血缘查询必须按 canonical_code 聚合；
  3. 单点注册：新增第 19 个策略只改 STRATEGY_MANIFEST 一处，模板派生 /
     类解析 / 契约门禁 / 回测装配四条链路自动生效；
  4. 参数搜索空间：派生网格的键必须 ⊆ 策略 schema 声明的参数名。

全部为纯内存断言，不连数据库。
"""

import pytest

from app.allocation.strategy_manifest import (
    LEGACY_ALIASES,
    STRATEGY_MANIFEST,
    canonical_code,
    get_class_paths,
    resolve_class,
)
from app.backtesting.composition_builder import build_strategy_composition
from app.backtesting.data_contract import DataContract, with_panel_declarations
from app.services.strategy_data_contract_service import resolve_contract

STANDALONE_CODES = [
    code
    for code, entry in STRATEGY_MANIFEST.items()
    if entry.strategy_form == "standalone"
]


class TestPanelSingleSource:
    """面板声明单源：契约派生结果必须与类方法声明一致."""

    def test_contract_panels_match_class_methods(self):
        assert len(STANDALONE_CODES) == 6, (
            f"standalone 策略数量变化（当前 {len(STANDALONE_CODES)}），"
            "请同步本测试的面板断言"
        )
        violations = []
        for code in STANDALONE_CODES:
            cls = resolve_class(code)
            contract = cls.get_data_contract()
            class_panels = [str(n) for n in (cls.get_extra_panels() or [])]
            class_datasets = {
                str(k): str(v) for k, v in dict(cls.get_panel_datasets() or {}).items()
            }

            # 双源矛盾：契约与类方法都声明面板，但集合不一致
            if contract.panels and class_panels and set(contract.panels) != set(class_panels):
                violations.append(
                    f"{code}: 契约面板 {sorted(contract.panels)} 与类方法面板 "
                    f"{sorted(class_panels)} 不一致"
                )

            derived = with_panel_declarations(contract, cls)
            expected_panels = set(contract.panels) if contract.panels else set(class_panels)
            if set(derived.panels) != expected_panels:
                violations.append(
                    f"{code}: 派生面板 {sorted(derived.panels)} 与声明 "
                    f"{sorted(expected_panels)} 不一致"
                )

            derived_datasets = {k: v for k, v in derived.panels.items() if v}
            expected_datasets = {k: v for k, v in class_datasets.items() if v}
            if derived_datasets != expected_datasets:
                violations.append(
                    f"{code}: 派生数据集 {derived_datasets} 与类方法声明 "
                    f"{expected_datasets} 不一致"
                )
        assert not violations, (
            "面板声明出现漂移（读取侧要求单源，见 with_panel_declarations）:\n"
            + "\n".join(violations)
        )

    def test_contract_derivation_is_pure(self):
        """派生不修改入参契约（frozen dataclass + replace）."""
        for code in STANDALONE_CODES:
            cls = resolve_class(code)
            contract = cls.get_data_contract()
            before = (dict(contract.panels), tuple(contract.datasets))
            with_panel_declarations(contract, cls)
            after = (dict(contract.panels), tuple(contract.datasets))
            assert before == after, f"{code}: 派生过程修改了原契约"


class TestAliasNotIndependentStrategy:
    """别名只做 code 归一，不是独立策略身份."""

    def test_alias_not_independent_strategy(self):
        assert LEGACY_ALIASES, "别名映射为空，本测试失去意义"
        paths = get_class_paths()
        for alias, target in LEGACY_ALIASES.items():
            assert alias not in STRATEGY_MANIFEST, (
                f"别名 {alias} 被注册成独立策略条目，会产生第二份档案"
            )
            assert canonical_code(alias) == target
            assert canonical_code(alias) in STRATEGY_MANIFEST
            assert paths[alias] == STRATEGY_MANIFEST[target].class_path
            # 解析别名与解析正式 code 必须拿到同一个类，否则是两条策略链
            assert resolve_class(alias) is resolve_class(target)

        # 类路径映射除正式 code 外只允许出现别名，不引入第三种身份
        assert set(paths) - set(STRATEGY_MANIFEST) == set(LEGACY_ALIASES), (
            "get_class_paths() 出现了既非正式 code 也非别名的条目"
        )

    def test_alias_not_expanded_into_template_codes(self):
        """模板派生只遍历正式条目，别名不会变成可选的第 19 个模板."""
        from app.allocation.builtin_templates import get_builtin_templates

        codes = {t["code"] for t in get_builtin_templates()}
        leaked = sorted(codes & set(LEGACY_ALIASES))
        assert not leaked, f"别名被当作独立模板暴露: {leaked}"


class TestSinglePointRegistration:
    """新增策略只改 STRATEGY_MANIFEST 一处，四条链路自动生效."""

    def test_add_19th_strategy_one_edit(self, monkeypatch):
        import app.allocation.strategy_manifest as manifest_mod

        fake_code = "test_19th_strategy"
        monkeypatch.setitem(
            manifest_mod.STRATEGY_MANIFEST,
            fake_code,
            manifest_mod.StrategyEntry(
                class_path="app.allocation.models.risk_parity.RiskParityStrategy",
                name="第十九个策略（测试）",
                description="monkeypatch 注入，仅用于验证单点注册派生链路",
            ),
        )

        # ① 模板派生：新策略自动出现在模板列表
        from app.allocation.builtin_templates import get_builtin_templates

        templates = {t["code"] for t in get_builtin_templates()}
        assert fake_code in templates, "新增条目未自动派生出模板"

        # ② 类解析：无需改 get_class_paths / resolve_class
        assert manifest_mod.resolve_class(fake_code).__name__ == "RiskParityStrategy"

        # ③ 契约门禁：已注册策略必须可解析（未声明契约返回空契约/None，不抛错）
        contract = resolve_contract(fake_code)
        assert contract is None or isinstance(contract, DataContract)
        assert fake_code in get_class_paths()

        # ④ 回测装配：composition 的 allocator 自动指向新 code
        spec = build_strategy_composition(fake_code, ["510300"], {})
        assert spec.composition["allocator"] == fake_code, (
            "未在 COMPOSITION_DEFAULTS 声明的新策略应走 fallback allocator=code"
        )
        assert spec.enable_selection is False


class TestParamSearchSpace:
    """参数搜索空间：派生网格必须落在 schema 声明之内."""

    def test_param_grid_keys_subset(self):
        from app.services.backtest_analysis_service import (
            _MAX_GRID_VALUES,
            get_param_grid,
        )

        violations = []
        for code in STRATEGY_MANIFEST:
            schema = resolve_class(code).get_param_schema()
            declared = {p.name for p in (getattr(schema, "params", None) or [])}
            hidden = {
                p.name
                for p in (getattr(schema, "params", None) or [])
                if getattr(p, "hidden", False)
            }
            grid = get_param_grid(code)

            extra = sorted(set(grid) - declared)
            if extra:
                violations.append(f"{code}: 网格键 {extra} 未在 schema 中声明")
            shown_hidden = sorted(set(grid) & hidden)
            if shown_hidden:
                violations.append(f"{code}: hidden 参数不应参与扫描 {shown_hidden}")
            empty = sorted(k for k, v in grid.items() if not v)
            if empty:
                violations.append(f"{code}: 网格值为空 {empty}")
            oversized = sorted(
                k for k, v in grid.items() if len(v) > _MAX_GRID_VALUES
            )
            if oversized:
                violations.append(
                    f"{code}: 取值数超过上限 {_MAX_GRID_VALUES} 的参数 {oversized}"
                )
        assert not violations, "参数搜索空间越界:\n" + "\n".join(violations)

    def test_alias_grid_matches_canonical(self):
        from app.services.backtest_analysis_service import get_param_grid

        for alias, target in LEGACY_ALIASES.items():
            assert get_param_grid(alias) == get_param_grid(target), (
                f"别名 {alias} 与正式 code {target} 的搜索空间不一致"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
