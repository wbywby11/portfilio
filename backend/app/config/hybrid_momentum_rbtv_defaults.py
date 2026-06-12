# -*- coding: utf-8 -*-
"""
risk_budget_target_vol 混合动量策略默认配置

依据浙银理财-申万指数编制规则 B.1 关键参数精确值初始化。
新建 risk_budget_target_vol 策略并启用混合动量时，可据此预填参数。
"""
from __future__ import annotations

from typing import Any, Dict

# B.1.1 动量因子参数
MOMENTUM_WINDOWS = "20,60,120,250"  # MOM/POSI/SMOM 窗口
MACD_SHORT_WINDOWS = "40,80,120,160"
MACD_LONG_WINDOW = 250  # 固定
MOMENTUM_THRESHOLD = -0.02  # 因子值 > -2% 则信号=1
SMOM_VOL_TARGET = 0.045  # 4.5%
SMOM_N_ANNUAL = 260

# B.1.2 反转因子参数
REVERSAL_WINDOWS = "10,22"  # 偏度窗口
REVERSAL_N_SELECTED = 1  # 入选数量
# 计算对象：价格序列(非收益率)；排名：ascending=True, method='average'

# B.1.3 权重计算参数
TARGET_VOL = 0.05  # 目标波动率 5%
MAX_TOTAL_LEVERAGE = 4.0  # 杠杆上限
VOL_WINDOWS = [22, 65, 130]  # 波动率窗口
ANNUALIZATION_FACTOR = 260  # 年化因子

# B.1.4 单资产权重上限（按资产名称，与 zy_document_max_weights 一致）
WEIGHT_CAPS_BY_NAME: Dict[str, float] = {
    "沪深300": 0.10,
    "创业板指": 0.10,
    "红利低波": 0.10,
    "恒生科技": 0.10,
    "标普500": 0.15,
    "德国DAX": 0.10,
    "中国10年国债": 0.60,
    "中国2年国债": 0.90,
    "布伦特原油": 0.10,
    "黄金": 0.10,
    "铁矿石": 0.10,
    "中国有色金属": 0.10,
}

# B.1.6 波动率监控参数
VOL_RESET_THRESHOLD = 0.06  # 触发阈值 6%
VOL_MONITOR_WINDOWS = [22, 65, 130]  # 计算窗口
MONITOR_START_DAYS = 130  # 监控起始：第130个交易日起
EXECUTION_DELAY_DAYS = 2  # 执行延迟：信号日后第2个交易日
CONFLICT_CHECK_DAYS = 2  # 冲突检查天数

# 7+1 混合动量选择
N_MOMENTUM = 7
N_REVERSAL = 1
MIN_HISTORY_DAYS = 260


def get_hybrid_momentum_rbtv_defaults(asset_codes: list[str] | None = None) -> Dict[str, Any]:
    """
    获取 risk_budget_target_vol 混合动量策略的默认参数，供新建策略时初始化使用。

    Args:
        asset_codes: 资产代码列表，用于构建 max_weight_dict（可选，未提供时 max_weight_dict 为空，
                     回测时由后端按 zy_document 自动填充）

    Returns:
        可直接作为 strategy_params / model.parameters 的默认参数字典
    """
    from app.config.zy_document_max_weights import (
        ZY_DOCUMENT_MAX_WEIGHT_BY_CODE,
        ZY_DOCUMENT_CODE_TO_NAME,
        ZY_DOCUMENT_MAX_WEIGHT_ALIASES,
        ZY_DOCUMENT_DEFAULT_MAX_WEIGHT,
    )

    params: Dict[str, Any] = {
        # 策略层
        "target_vol": TARGET_VOL,
        "max_total_leverage": MAX_TOTAL_LEVERAGE,
        "enable_vol_reset": False,
        "vol_reset_threshold": VOL_RESET_THRESHOLD,
        "min_history_days": MIN_HISTORY_DAYS,
        "lookback_days": 260,
        # 混合动量选择
        "enable_momentum_selection": True,
        "selector_type": "momentum_reversal",
        "n_momentum": N_MOMENTUM,
        "n_reversal": N_REVERSAL,
        "momentum_windows": MOMENTUM_WINDOWS,
        "mom_windows": MOMENTUM_WINDOWS,
        "posi_windows": MOMENTUM_WINDOWS,
        "smom_windows": MOMENTUM_WINDOWS,
        "macd_windows": MACD_SHORT_WINDOWS,
        "macd_long_window": MACD_LONG_WINDOW,
        "reversal_windows": REVERSAL_WINDOWS,
    }

    # max_weight_dict：若提供 asset_codes，按编制规则预填
    if asset_codes:
        max_weight_dict = {}
        for code in asset_codes:
            w = (
                ZY_DOCUMENT_MAX_WEIGHT_BY_CODE.get(code)
                or ZY_DOCUMENT_MAX_WEIGHT_ALIASES.get(ZY_DOCUMENT_CODE_TO_NAME.get(code, code))
                or ZY_DOCUMENT_DEFAULT_MAX_WEIGHT
            )
            max_weight_dict[code] = w
        params["max_weight_dict"] = max_weight_dict
    else:
        params["max_weight_dict"] = {}

    return params
