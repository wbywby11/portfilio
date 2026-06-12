# -*- coding: utf-8 -*-
"""
直接调用 动量策略相关资料 中的 step1/step2/step3 核心步骤

使用 risk_budget_target_vol + 动量策略时，核心逻辑委托给：
- step1_asset_selection.py: 资产选择（7+1 动量/反转）
- step2_weight_calculation.py: 权重计算（风险预算+目标波动率）
- step3_backtest_fx_v1.py: 波动率计算等工具函数（可选）

路径解析：动量策略相关资料 与 portfilio-end 为同级目录
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Any

import pandas as pd


def _ensure_step_path() -> str:
    """确保 动量策略相关资料 在 sys.path 中，返回其绝对路径"""
    # 从 app/selection/step_reference.py 向上找到 portfilio-end 的父目录
    _here = os.path.abspath(os.path.dirname(__file__))
    _app = os.path.dirname(_here)
    _root = os.path.dirname(_app)  # portfilio-end
    _parent = os.path.dirname(_root)  # d:\
    step_dir = os.path.join(_parent, "动量策略相关资料")
    if os.path.isdir(step_dir) and step_dir not in sys.path:
        sys.path.insert(0, step_dir)
    return step_dir


def _import_step1():
    """导入 step1_asset_selection 模块"""
    _ensure_step_path()
    import step1_asset_selection as m
    return m


def _import_step2():
    """导入 step2_weight_calculation 模块"""
    _ensure_step_path()
    import step2_weight_calculation as m
    return m


def _import_step3():
    """导入 step3_backtest_fx_v1 模块"""
    _ensure_step_path()
    import step3_backtest_fx_v1 as m
    return m


def select_assets_for_date(
    nav: pd.DataFrame,
    date_idx: int,
    calc_date: pd.Timestamp,
    min_history: int = 260,
    top_momentum: int = 7,
    reversal_tie_all_select: bool = True,
) -> Dict[str, Any]:
    """
    直接调用 step1_asset_selection.select_assets_for_date

    reversal_tie_all_select: 反转平局时都入选（与编制规则扩展一致）
    """
    step1 = _import_step1()
    return step1.select_assets_for_date(
        nav=nav,
        date_idx=date_idx,
        calc_date=calc_date,
        min_history=min_history,
        top_momentum=top_momentum,
        reversal_tie_all_select=reversal_tie_all_select,
    )


def calc_weights_for_date(
    nav: pd.DataFrame,
    date_idx: int,
    selection_row: Dict[str, int],
    all_assets: List[str],
    target_vol: float = 0.05,
    max_leverage: float = 4.0,
    weight_caps: Optional[Dict[str, float]] = None,
    fillna_zero: bool = True,
) -> Dict[str, Any]:
    """
    直接调用 step2_weight_calculation.calc_weights_for_date

    weight_caps: 单资产上限，未提供时使用 step2 默认 WEIGHT_CAPS
    fillna_zero: step2 的 pct_change 不显式 fillna，此处仅作接口兼容
    """
    step2 = _import_step2()
    result = step2.calc_weights_for_date(
        nav=nav,
        date_idx=date_idx,
        selection_row=selection_row,
        all_assets=all_assets,
        target_vol=target_vol,
        max_leverage=max_leverage,
        weight_caps=weight_caps,
    )
    return result


def calc_realized_vol_v1(weights: Dict[str, float], daily_ret: pd.DataFrame,
                        assets: List[str], windows: Optional[List[int]] = None) -> float:
    """直接调用 step3 的 calc_realized_vol_v1（波动率监控用）"""
    step3 = _import_step3()
    w = pd.Series(weights)
    return step3.calc_realized_vol_v1(w, daily_ret, windows=windows or step3.VOL_WINDOWS)


def calc_vw_weights(current_weights: Dict[str, float], vol_trigger: float,
                    target_vol: float = 0.05) -> tuple:
    """直接调用 step3 的 calc_vw_weights（波动率重置用）"""
    step3 = _import_step3()
    return step3.calc_vw_weights(current_weights, vol_trigger, target_vol=target_vol)
