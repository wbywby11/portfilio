# -*- coding: utf-8 -*-
"""
产品层（Product Layer）— 组合之上的最终产品配置

对齐原型 四象限策略/control/vol_target.py 的 VolTargetController：
  配置维度：策略组合 + 短债专户 + 现金
  权重分配（二元一次方程）：
    已知: w_cash = cash_fixed（固定，默认15%）
    求解: w_strategy, w_bond
      方程1: w_strategy + w_bond = 1 - cash_fixed
      方程2: w_strategy × σ_strategy + w_bond × σ_bond = vol_target
      解: w_strategy = (vol_target - risk_budget × σ_bond) / (σ_strategy - σ_bond)
    约束: w_strategy ∈ [0, risk_budget]
  月度调仓，权重 shift(1) 避免前视偏差。

配置方式（不改前端）：在组合模型的 weight_model_params 中增加 product_layer 字段，例如：
  {
    "product_layer": {
      "enabled": true,
      "controller": "vol_target",
      "vol_target": 0.02,
      "cash_fixed": 0.15,
      "vol_window": 60,
      "annualize_factor": 252,
      "bond_code": "CBA11321.CS",
      "cash_code": "511360.SH"
    }
  }
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 与原型一致的默认参数
DEFAULT_PARAMS = {
    "vol_target": 0.02,
    "cash_fixed": 0.15,
    "vol_window": 60,
    "annualize_factor": 252,
}

# 默认底层资产（原型口径：短债专户净值 + 短融ETF现金代理）
DEFAULT_BOND_CODE = "CBA11321.CS"
DEFAULT_CASH_CODE = "511360.SH"


def _realized_vol(returns: pd.Series, window: int = 60, n_annual: int = 252) -> pd.Series:
    """滚动年化波动率（与原型一致：min_periods = max(20, window // 2)）"""
    min_periods = max(20, window // 2)
    return returns.rolling(window, min_periods=min_periods).std() * np.sqrt(n_annual)


def vol_target_apply(
    strategy_nav: pd.Series,
    bond_nav: pd.Series,
    cash_nav: Optional[pd.Series] = None,
    **params,
) -> pd.DataFrame:
    """
    产品层波动率目标配置（逐行对齐原型 VolTargetController.apply）。

    Args:
        strategy_nav: 策略组合日度净值
        bond_nav: 短债日度净值（CBA11321.CS）
        cash_nav: 现金代理日度净值（511360.SH），未提供时现金收益按 0 处理
        **params: vol_target / cash_fixed / vol_window / annualize_factor

    Returns:
        DataFrame: columns = [nav, daily_ret, strategy_weight, bond_weight, cash_weight]
    """
    p = {**DEFAULT_PARAMS, **{k: v for k, v in params.items() if v is not None}}
    vol_target = float(p.get("vol_target", 0.02))
    cash_fixed = float(p.get("cash_fixed", 0.15))
    vol_window = int(p.get("vol_window", 60))
    n_annual = int(p.get("annualize_factor", 252))

    risk_budget = 1.0 - cash_fixed

    # 对齐日期
    common_dates = strategy_nav.index.intersection(bond_nav.dropna().index)
    if len(common_dates) == 0:
        common_dates = strategy_nav.index

    combo_ret = strategy_nav.reindex(common_dates).pct_change(fill_method=None).fillna(0)
    bond_prices = bond_nav.reindex(common_dates).ffill()
    bond_ret = bond_prices.pct_change(fill_method=None).fillna(0)

    if cash_nav is not None:
        cash_prices = cash_nav.reindex(common_dates).ffill()
        cash_daily_ret = cash_prices.pct_change(fill_method=None).fillna(0)
    else:
        logger.warning("[product_layer] 未提供现金代理净值，现金收益按 0 处理")
        cash_daily_ret = pd.Series(0.0, index=common_dates)

    vol_combo = _realized_vol(combo_ret, vol_window, n_annual)
    vol_bond = _realized_vol(bond_ret, vol_window, n_annual)

    # 月度调仓：每月第一个交易日
    monthly_first = common_dates.to_series().groupby(
        [common_dates.year, common_dates.month]
    ).first().values
    monthly_first_set = set(pd.DatetimeIndex(monthly_first))

    w_strategy_series = pd.Series(np.nan, index=common_dates)
    w_bond_series = pd.Series(np.nan, index=common_dates)

    for date in common_dates:
        if date not in monthly_first_set:
            continue

        sigma_s = vol_combo.loc[date]
        sigma_b = vol_bond.loc[date]

        if pd.isna(sigma_s) or pd.isna(sigma_b) or sigma_s <= 0 or sigma_b <= 0:
            w_strategy_series.loc[date] = risk_budget * 0.3
            w_bond_series.loc[date] = risk_budget * 0.7
            continue

        if abs(sigma_s - sigma_b) < 1e-8:
            w_strategy_series.loc[date] = risk_budget / 2
            w_bond_series.loc[date] = risk_budget / 2
            continue

        w_s = (vol_target - risk_budget * sigma_b) / (sigma_s - sigma_b)
        w_s = max(0.0, min(risk_budget, w_s))
        w_b = risk_budget - w_s

        w_strategy_series.loc[date] = w_s
        w_bond_series.loc[date] = w_b

    strategy_weight = w_strategy_series.ffill().fillna(risk_budget * 0.3)
    bond_weight = w_bond_series.ffill().fillna(risk_budget * 0.7)
    cash_weight = cash_fixed

    # 产品日收益率（权重 shift(1) 避免前视偏差）
    product_ret = (
        strategy_weight.shift(1).fillna(strategy_weight.iloc[0]) * combo_ret
        + bond_weight.shift(1).fillna(bond_weight.iloc[0]) * bond_ret
        + cash_weight * cash_daily_ret
    )

    product_nav = (1 + product_ret).cumprod()

    return pd.DataFrame({
        "nav": product_nav,
        "daily_ret": product_ret,
        "strategy_weight": strategy_weight,
        "bond_weight": bond_weight,
        "cash_weight": cash_weight,
    })


# =============================================================================
# 配置解析与数据加载
# =============================================================================

def resolve_product_layer_config(weight_model_params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """从 weight_model_params 中解析产品层配置；未启用返回 None。

    兼容两种写法：
      1. weight_model_params["product_layer"] = {...}
      2. weight_model_params 顶层直接含 product_layer 平铺字段（不推荐）
    """
    wmp = weight_model_params or {}
    cfg = wmp.get("product_layer")
    if not isinstance(cfg, dict):
        return None
    if not cfg.get("enabled", False):
        return None
    merged = {**DEFAULT_PARAMS}
    for key in ("vol_target", "cash_fixed", "vol_window", "annualize_factor"):
        if cfg.get(key) is not None:
            merged[key] = cfg[key]
    merged["bond_code"] = str(cfg.get("bond_code") or DEFAULT_BOND_CODE)
    merged["cash_code"] = str(cfg.get("cash_code") or DEFAULT_CASH_CODE)
    merged["controller"] = str(cfg.get("controller") or "vol_target")
    return merged


async def load_product_layer_assets(
    bond_code: str,
    cash_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, pd.Series]:
    """从 MongoDB asset_prices 加载短债/现金代理净值序列。

    Returns: {"bond": Series, "cash": Series|None}（index=DatetimeIndex，值为收盘价/净值）
    """
    from app.config.database import Database

    db = Database.get_database()
    collection = db["asset_prices"]

    codes = [bond_code, cash_code]
    query: Dict[str, Any] = {"asset_code": {"$in": codes}}
    if start_date or end_date:
        query["date"] = {}
        if start_date:
            query["date"]["$gte"] = str(start_date)[:10]
        if end_date:
            query["date"]["$lte"] = str(end_date)[:10]

    cursor = collection.find(query).sort("date", 1)
    records = await cursor.to_list(length=None)
    if not records:
        return {"bond": pd.Series(dtype=float), "cash": None}

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    out: Dict[str, pd.Series] = {"bond": pd.Series(dtype=float), "cash": None}
    for label, code in (("bond", bond_code), ("cash", cash_code)):
        sub = df[df["asset_code"] == code]
        if sub.empty:
            if label == "bond":
                logger.warning(f"[product_layer] 短债资产 {code} 无行情数据")
            else:
                logger.warning(f"[product_layer] 现金代理 {code} 无行情数据，现金收益按 0 处理")
            continue
        series = (
            sub.groupby("date")["close"].last().sort_index().astype(float)
        )
        out[label] = series
    return out


async def run_product_layer_for_nav(
    portfolio_nav: pd.Series,
    config: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """对组合 NAV 叠加产品层，返回产品结果字典；数据缺失时返回 None（回退为不启用）。

    Returns:
        {
          "nav": pd.Series（产品净值，起点=1.0，调用方负责归一化）,
          "daily_ret": pd.Series,
          "strategy_weight"/"bond_weight"/"cash_weight": pd.Series/float,
          "config": dict,
        }
    """
    if config.get("controller", "vol_target") != "vol_target":
        logger.warning(f"[product_layer] 未知控制器: {config.get('controller')}，跳过产品层")
        return None

    start_date = portfolio_nav.index[0].strftime("%Y-%m-%d") if len(portfolio_nav) else None
    end_date = portfolio_nav.index[-1].strftime("%Y-%m-%d") if len(portfolio_nav) else None
    assets = await load_product_layer_assets(
        config["bond_code"], config["cash_code"],
        start_date=start_date, end_date=end_date,
    )
    bond_nav = assets["bond"]
    if bond_nav is None or bond_nav.empty:
        logger.warning("[product_layer] 短债净值缺失，产品层不启用")
        return None

    result_df = vol_target_apply(
        portfolio_nav, bond_nav, assets.get("cash"),
        vol_target=config["vol_target"],
        cash_fixed=config["cash_fixed"],
        vol_window=config["vol_window"],
        annualize_factor=config["annualize_factor"],
    )

    return {
        "nav": result_df["nav"],
        "daily_ret": result_df["daily_ret"],
        "strategy_weight": result_df["strategy_weight"],
        "bond_weight": result_df["bond_weight"],
        "cash_weight": result_df["cash_weight"],
        "config": config,
    }


def summarize_product_layer(product_out: Dict[str, Any]) -> Dict[str, Any]:
    """产品层摘要（用于 API 输出 product_layer 字段）。"""
    cfg = product_out.get("config", {})
    sw = product_out["strategy_weight"]
    bw = product_out["bond_weight"]
    cw = product_out["cash_weight"]
    return {
        "controller": cfg.get("controller", "vol_target"),
        "vol_target": cfg.get("vol_target"),
        "cash_fixed": cfg.get("cash_fixed"),
        "vol_window": cfg.get("vol_window"),
        "bond_code": cfg.get("bond_code"),
        "cash_code": cfg.get("cash_code"),
        "avg_weights": {
            "strategy": round(float(sw.mean()), 4),
            "bond": round(float(bw.mean()), 4),
            "cash": round(float(cw), 4) if isinstance(cw, float) else round(float(cw.mean()), 4),
        },
        "final_weights": {
            "strategy": round(float(sw.iloc[-1]), 4),
            "bond": round(float(bw.iloc[-1]), 4),
            "cash": round(float(cw), 4) if isinstance(cw, float) else round(float(cw.iloc[-1]), 4),
        },
    }
