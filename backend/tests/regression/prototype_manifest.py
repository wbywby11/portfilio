"""原型验收清单（manifest）解析 —— 回归测试侧资产（非系统架构组件）.

清单文件位于 ``tests/regression/manifests/<name>.yaml``，结构见 gmsi2.yaml。
原型模型（GMAP/GCMI/母组合）是前端策略建模产出的配置实例，清单只按
名称引用库内模型做数值验收，不参与模型创建与运行时链路。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"


@dataclass
class ModelRef:
    """清单登记的策略模型引用（按模型名称定位库内文档）."""

    key: str
    name: str
    template_code: Optional[str] = None


@dataclass
class SubStrategyRef:
    """母组合子策略引用：ref 指向 models 段的 key."""

    ref: str
    weight: float


@dataclass
class PortfolioModelRef:
    """母组合模型引用."""

    name: str
    initial_nav: float = 1000.0
    rebalance_frequency: str = "monthly"
    sub_strategies: List[SubStrategyRef] = field(default_factory=list)


@dataclass
class PortfolioSpec:
    """母组合层控制口径（波动率控制等）."""

    vol_target: Optional[float] = None
    vol_lookback_short: Optional[int] = None
    vol_lookback_long: Optional[int] = None
    vol_method: Optional[str] = None
    vol_annualize_factor: Optional[int] = None


@dataclass
class ToleranceSpec:
    """验收容差：日收益相关系数下限与端点 NAV 相对误差上限."""

    corr_min: float
    end_err_max: float


@dataclass
class BaselineSpec:
    """原型基线 NAV 与验收口径."""

    nav_csv: str  # 相对项目根的 CSV 路径（首列为日期索引）
    series: Dict[str, str]  # 清单层 key → CSV 列名（含 "portfolio"）
    start_date: str  # YYYYMMDD
    end_date: str  # YYYYMMDD
    tolerance: ToleranceSpec


@dataclass
class Manifest:
    """原型验收清单."""

    prototype: str
    display_name: str
    description: str
    models: Dict[str, ModelRef]
    portfolio_model: Optional[PortfolioModelRef]
    portfolio: Optional[PortfolioSpec]
    baseline: Optional[BaselineSpec]

    def model_by_key(self, key: str) -> ModelRef:
        if key not in self.models:
            raise KeyError(f"清单 '{self.prototype}' 未登记模型 key: {key}")
        return self.models[key]


def load_manifest(name: str) -> Manifest:
    """加载 manifests/<name>.yaml 并解析为 Manifest（含结构校验）."""
    path = MANIFEST_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"原型清单不存在: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"清单格式无效（应为映射）: {path}")

    models = {
        key: ModelRef(
            key=key,
            name=spec["name"],
            template_code=spec.get("template_code"),
        )
        for key, spec in (raw.get("models") or {}).items()
    }

    pm_raw = raw.get("portfolio_model")
    portfolio_model = None
    if pm_raw:
        portfolio_model = PortfolioModelRef(
            name=pm_raw["name"],
            initial_nav=float(pm_raw.get("initial_nav", 1000.0)),
            rebalance_frequency=pm_raw.get("rebalance_frequency", "monthly"),
            sub_strategies=[
                SubStrategyRef(ref=s["ref"], weight=float(s["weight"]))
                for s in pm_raw.get("sub_strategies", [])
            ],
        )
        for sub in portfolio_model.sub_strategies:
            if sub.ref not in models:
                raise ValueError(
                    f"清单 '{name}' 母组合子策略引用了未登记的模型 key: {sub.ref}"
                )

    pf_raw = raw.get("portfolio")
    portfolio = PortfolioSpec(**pf_raw) if pf_raw else None

    bl_raw = raw.get("baseline")
    baseline = None
    if bl_raw:
        tol_raw = bl_raw["tolerance"]
        baseline = BaselineSpec(
            nav_csv=bl_raw["nav_csv"],
            series=dict(bl_raw["series"]),
            start_date=str(bl_raw["start_date"]),
            end_date=str(bl_raw["end_date"]),
            tolerance=ToleranceSpec(
                corr_min=float(tol_raw["corr_min"]),
                end_err_max=float(tol_raw["end_err_max"]),
            ),
        )

    return Manifest(
        prototype=raw.get("prototype", name),
        display_name=raw.get("display_name", name),
        description=raw.get("description", ""),
        models=models,
        portfolio_model=portfolio_model,
        portfolio=portfolio,
        baseline=baseline,
    )
