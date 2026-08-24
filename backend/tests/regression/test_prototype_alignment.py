# -*- coding: utf-8 -*-
"""GMSI 2.0 原型数值验收（清单驱动）.

验收标准来自原型清单 ``tests/regression/manifests/gmsi2.yaml`` 的 ``baseline`` 段：
逐层对比系统回测 NAV 与原型基线 NAV，日收益相关系数与端点误差须在容差内。

窗口终点从清单读取（固定日期），不使用 ``datetime.now()`` —— 验收结果
必须可复现，否则同一份代码在不同日期跑出不同结论。

用法：
  py -m pytest tests/regression/test_prototype_alignment.py -s
  py tests/regression/test_prototype_alignment.py          # 直接运行，打印对账表
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (PROJECT_ROOT, PROJECT_ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# 已验收的原型清单（新增原型只需追加清单名）
PROTOTYPES = ["gmsi2"]


def _compare(name: str, sys_nav: pd.Series, proto_nav: pd.Series) -> dict:
    """对齐两条 NAV（各自归一到公共区间首日=1），输出 corr / 端点误差 / 最大偏差."""
    sys_nav = sys_nav.dropna().sort_index()
    proto_nav = proto_nav.dropna().sort_index()
    common = sys_nav.index.intersection(proto_nav.index)
    if len(common) < 2:
        raise AssertionError(f"{name}: 系统与原型公共交易日不足（{len(common)} 天）")
    s = sys_nav.loc[common] / sys_nav.loc[common].iloc[0]
    p = proto_nav.loc[common] / proto_nav.loc[common].iloc[0]
    rs = s.pct_change(fill_method=None).dropna()
    rp = p.pct_change(fill_method=None).dropna()
    both = rs.index.intersection(rp.index)
    return {
        "name": name,
        "days": len(common),
        "corr": float(np.corrcoef(rs.loc[both].values, rp.loc[both].values)[0, 1]),
        "end_err": abs(float(s.iloc[-1]) - float(p.iloc[-1])) / float(p.iloc[-1]),
        "max_dev": float((s - p).abs().max()),
        "sys_end": float(s.iloc[-1]),
        "proto_end": float(p.iloc[-1]),
    }


async def _run_prototype(name: str) -> List[dict]:
    """按清单跑完原型各层回测，返回对账行。"""
    os.chdir(PROJECT_ROOT)  # 保证 pydantic settings 读到 .env

    from app.config.database import Database
    from app.models.strategy_model import StrategyModel
    from app.portfolio.portfolio_service import PortfolioService

    from regression.prototype_manifest import load_manifest

    manifest = load_manifest(name)
    baseline = manifest.baseline
    if baseline is None:
        pytest.skip(f"原型 '{name}' 清单未声明 baseline")

    Database.connect()
    pf_svc = PortfolioService()
    svc = pf_svc.strategy_model_service

    proto = pd.read_csv(
        PROJECT_ROOT / baseline.nav_csv, index_col=0, parse_dates=True
    )
    initial_nav = (
        manifest.portfolio_model.initial_nav if manifest.portfolio_model else 1000.0
    )

    # ── 子策略逐层回测 ────────────────────────────────────────────────
    sub_nav: Dict[str, pd.Series] = {}
    model_ids: Dict[str, str] = {}
    rows: List[dict] = []
    for key, column in baseline.series.items():
        if key == "portfolio":
            continue
        spec = manifest.model_by_key(key)
        doc = await svc.collection.find_one({"name": spec.name})
        assert doc, (
            f"模型未入库: {spec.name}；"
            f"请先经前端策略建模（StrategyModelForm / PortfolioCreate）创建同名模型"
        )
        doc["_id"] = str(doc["_id"])
        model = StrategyModel(**doc)
        model_ids[key] = model.id
        nav = await pf_svc._run_sub_strategy_backtest(
            model, baseline.start_date, baseline.end_date, initial_nav
        )
        assert nav is not None and len(nav) > 0, f"{spec.name} 回测未返回 NAV"
        sub_nav[key] = nav
        rows.append(_compare(key.upper(), nav, proto[column]))

    # ── 母组合复合 ────────────────────────────────────────────────────
    pm = manifest.portfolio_model
    if "portfolio" in baseline.series and pm:
        from app.portfolio.composite_runner import run_composite_unified as run_portfolio_backtest

        pf_spec = manifest.portfolio
        mother = run_portfolio_backtest(
            sub_nav_series={model_ids[r.ref]: sub_nav[r.ref] for r in pm.sub_strategies},
            sub_weights={model_ids[r.ref]: r.weight for r in pm.sub_strategies},
            initial_nav=pm.initial_nav,
            rebalance_freq=pm.rebalance_frequency,
            mother_vol_target=pf_spec.vol_target if pf_spec else None,
            mother_vol_short=pf_spec.vol_lookback_short if pf_spec else None,
            mother_vol_long=pf_spec.vol_lookback_long if pf_spec else None,
            mother_vol_method=pf_spec.vol_method if pf_spec else None,
            mother_annualize_factor=pf_spec.vol_annualize_factor if pf_spec else None,
        )
        rows.append(
            _compare("PORTFOLIO", mother.portfolio_nav, proto[baseline.series["portfolio"]])
        )
    return rows


def _print_report(name: str, rows: List[dict], tol) -> None:
    print(f"\n原型 '{name}' 对账（corr>{tol.corr_min} 且 端点误差<{tol.end_err_max:.0%}）")
    print(f"{'层级':<12}{'天数':>7}{'收益相关':>10}{'端点误差':>10}{'最大偏差':>10}   结果")
    for r in rows:
        ok = r["corr"] > tol.corr_min and r["end_err"] < tol.end_err_max
        print(
            f"{r['name']:<14}{r['days']:>7}{r['corr']:>10.4f}"
            f"{r['end_err']:>10.2%}{r['max_dev']:>10.4f}   {'PASS' if ok else 'FAIL'}"
        )
        print(f"    系统端点={r['sys_end']:.4f}  原型端点={r['proto_end']:.4f}")


@pytest.mark.parametrize("prototype", PROTOTYPES)
def test_prototype_alignment(prototype: str) -> None:
    """原型各层系统回测须与基线 NAV 在容差内对齐。"""
    from regression.prototype_manifest import load_manifest

    tol = load_manifest(prototype).baseline.tolerance
    rows = asyncio.run(_run_prototype(prototype))
    _print_report(prototype, rows, tol)

    failed = [
        f"{r['name']}: corr={r['corr']:.4f} 端点误差={r['end_err']:.2%}"
        for r in rows
        if not (r["corr"] > tol.corr_min and r["end_err"] < tol.end_err_max)
    ]
    assert not failed, (
        f"原型 '{prototype}' 未对齐层级: " + "; ".join(failed)
    )


if __name__ == "__main__":
    from regression.prototype_manifest import load_manifest

    for _name in PROTOTYPES:
        _tol = load_manifest(_name).baseline.tolerance
        _print_report(_name, asyncio.run(_run_prototype(_name)), _tol)
