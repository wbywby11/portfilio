# -*- coding: utf-8 -*-
"""
混合动量12策略回测验证脚本 — 从 MongoDB 读取数据

从 MongoDB 读取 asset_prices / fx_rates / trade_dates，
运行完整 step1(资产选择) → step2(权重计算) → step3(净值回测) 流程，
输出最终 NAV 及绩效指标。

用法：
  cd portfilio-end
  python scripts/test_hybrid12_backtest.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from pymongo import MongoClient

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"

# 12 资产代码 → 中文名
HYBRID_CODE_TO_NAME = {
    '000300.SH': '沪深300',
    'SZ399006': '创业板指',
    'ZZ000001': '红利低波',
    'HSTECH': '恒生科技',
    'SPX': '标普500',
    'GDAXI': '德国DAX',
    'ZQGZ10': '中国10年国债',
    'ZQGZ2': '中国2年国债',
    'B00Y': '布伦特原油',
    'GLD': '黄金',
    'IRON': '铁矿石',
    'YSJS': '中国有色金属',
}
HYBRID_NAME_TO_CODE = {v: k for k, v in HYBRID_CODE_TO_NAME.items()}
ASSET_NAMES = list(HYBRID_CODE_TO_NAME.values())

# 资产计价货币
ASSET_CURRENCY = {
    '沪深300': 'CNH', '创业板指': 'CNH', '红利低波': 'CNH',
    '恒生科技': 'HKD', '标普500': 'USD', '德国DAX': 'EUR',
    '中国10年国债': 'CNH', '中国2年国债': 'CNH',
    '布伦特原油': 'USD', '黄金': 'CNH', '铁矿石': 'CNH', '中国有色金属': 'CNH',
}

# 费率
TRADING_COST = {
    '沪深300': 0.0003, '创业板指': 0.0003, '红利低波': 0.0003,
    '恒生科技': 0.0005, '标普500': 0.0002, '德国DAX': 0.0002,
    '中国10年国债': 0.0003, '中国2年国债': 0.0003,
    '布伦特原油': 0.0001, '黄金': 0.0003, '铁矿石': 0.0003, '中国有色金属': 0.0003,
}
REPLICATION_COST = {
    '沪深300': 0.004, '创业板指': 0.030, '红利低波': 0.030,
    '恒生科技': 0.020, '标普500': 0.006, '德国DAX': 0.007,
    '中国10年国债': 0.003, '中国2年国债': 0.003,
    '布伦特原油': 0.006, '黄金': 0.006, '铁矿石': 0.006, '中国有色金属': 0.006,
}

# 权重上限
WEIGHT_CAPS = {
    '沪深300': 0.10, '创业板指': 0.10, '红利低波': 0.10,
    '恒生科技': 0.10, '标普500': 0.15, '德国DAX': 0.10,
    '中国10年国债': 0.60, '中国2年国债': 0.90,
    '布伦特原油': 0.10, '黄金': 0.10, '铁矿石': 0.10, '中国有色金属': 0.10,
}

# 回测参数
BASE_DATE = pd.Timestamp('2014-02-10')
BASE_VALUE = 1000.0
TARGET_VOL = 0.05
MAX_LEVERAGE = 4.0
VOL_WINDOWS = [22, 65, 130]
VOL_TRIGGER_THRESHOLD = 0.06
MONITOR_START_DAYS = 60
ANNUALIZE_FACTOR = np.sqrt(260)

SKIP_EXCLUDED_DATES = {
    pd.Timestamp("2015-01-01"),
    pd.Timestamp("2015-01-02"),
    pd.Timestamp("2015-01-05"),
}


# ===========================================================================
# 数据加载（从 MongoDB）
# ===========================================================================
def load_data_from_mongo() -> tuple:
    """从 MongoDB 加载价格、汇率、交易日历数据。"""
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    asset_codes = list(HYBRID_CODE_TO_NAME.keys())

    # 1. 加载价格
    print("  加载 asset_prices ...")
    cursor = db["asset_prices"].find(
        {"asset_code": {"$in": asset_codes}},
        {"_id": 0, "date": 1, "asset_code": 1, "close": 1}
    )
    price_records = list(cursor)
    print(f"    原始记录数: {len(price_records)}")

    # 构建 DataFrame
    price_data = {}
    for rec in price_records:
        code = rec["asset_code"]
        cn_name = HYBRID_CODE_TO_NAME.get(code)
        if not cn_name:
            continue
        d = pd.Timestamp(rec["date"])
        close = rec.get("close")
        if close is not None and close > 0:
            if cn_name not in price_data:
                price_data[cn_name] = {}
            price_data[cn_name][d] = close

    prices = pd.DataFrame(price_data)
    prices = prices.sort_index()
    prices.index = pd.to_datetime(prices.index).normalize()
    # 去重
    prices = prices[~prices.index.duplicated(keep='first')]
    # 按 ASSET_NAMES 顺序排列列
    cols = [c for c in ASSET_NAMES if c in prices.columns]
    prices = prices[cols]
    print(f"    价格矩阵: {prices.shape[0]} 行 × {prices.shape[1]} 列")
    print(f"    日期范围: {prices.index.min().date()} ~ {prices.index.max().date()}")

    # 2. 加载汇率
    print("  加载 fx_rates ...")
    fx_cursor = db["fx_rates"].find({}, {"_id": 0})
    fx_records = list(fx_cursor)
    print(f"    汇率记录数: {len(fx_records)}")

    fx_data = {}
    for rec in fx_records:
        d = pd.Timestamp(rec["date"])
        row = {}
        for col in ["USD", "EUR", "HKD", "JPY", "CNH"]:
            if col in rec and rec[col] is not None:
                row[col] = float(rec[col])
        if row:
            fx_data[d] = row

    fx_df = pd.DataFrame.from_dict(fx_data, orient='index')
    fx_df = fx_df.sort_index()
    fx_df.index = pd.to_datetime(fx_df.index).normalize()
    fx_df = fx_df[~fx_df.index.duplicated(keep='first')]
    print(f"    汇率矩阵: {fx_df.shape[0]} 行, 列: {list(fx_df.columns)}")

    # 3. 加载交易日历
    print("  加载 trade_dates ...")
    td_cursor = db["trade_dates"].find({}, {"_id": 0, "date": 1})
    trade_dates_list = sorted([pd.Timestamp(doc["date"]) for doc in td_cursor])
    print(f"    交易日数: {len(trade_dates_list)}")

    client.close()
    return prices, fx_df, trade_dates_list


# ===========================================================================
# Step 1: 资产选择（动量 + 反转）
# ===========================================================================
def calc_mom(prices, n):
    return prices / prices.shift(n) - 1

def calc_macd(prices, win_short, win_long=250):
    return prices.rolling(win_short).mean() - prices.rolling(win_long).mean()

def calc_posi(prices, n):
    returns = prices.pct_change()
    pos_ret = returns.where(returns > 0, 0)
    neg_ret = returns.where(returns < 0, 0)
    return pos_ret.rolling(window=n).sum() + neg_ret.rolling(window=n).sum()

def calc_smom(prices, win, vol_target=0.045, n_annual=260):
    vol = prices.pct_change().rolling(win).std() * np.sqrt(n_annual)
    mom = prices / prices.shift(win) - 1
    smom = mom * (vol_target / (vol * np.sqrt(n_annual)))
    return smom.replace([np.inf, -np.inf], np.nan)


def calc_momentum_scores(prices, date_idx):
    """动量因子综合打分（满分16分）"""
    threshold = -0.02
    price_data = prices.iloc[:date_idx + 1]
    scores = pd.Series(0.0, index=prices.columns)

    for n in [20, 60, 120, 250]:
        if len(price_data) > n:
            factor = calc_mom(price_data, n).iloc[-1]
            scores += (factor > threshold).astype(int).fillna(0)

    if len(price_data) > 250:
        for n in [40, 80, 120, 160]:
            factor = calc_macd(price_data, n).iloc[-1]
            scores += (factor > threshold).astype(int).fillna(0)

    for n in [20, 60, 120, 250]:
        if len(price_data) > n:
            factor = calc_posi(price_data, n).iloc[-1]
            scores += (factor > threshold).astype(int).fillna(0)

    for n in [20, 60, 120, 250]:
        if len(price_data) > n:
            factor = calc_smom(price_data, n).iloc[-1]
            scores += (factor > threshold).astype(int).fillna(0)

    return scores


def calc_reversal_scores(prices, date_idx, windows=[10, 22]):
    """反转因子综合打分（双窗口偏度）"""
    price_data = prices.iloc[:date_idx + 1]
    total_scores = pd.Series(0.0, index=prices.columns)

    for win in windows:
        if len(price_data) > win:
            skew = price_data.rolling(win).skew().iloc[-1]
            rank = skew.rank(ascending=True, method='average')
            valid_count = skew.notna().sum()
            score = (valid_count - rank + 1).fillna(0)
            total_scores += score

    return total_scores


def select_assets_for_date(nav, date_idx, min_history_momentum=260,
                           min_history_reversal=22, top_momentum=7):
    """单次调仓的资产选择"""
    momentum_valid = []
    reversal_valid = []

    for col in nav.columns:
        valid_count = nav[col].iloc[:date_idx + 1].notna().sum()
        if valid_count >= min_history_momentum:
            momentum_valid.append(col)
        if valid_count >= min_history_reversal:
            reversal_valid.append(col)

    # 动量打分
    momentum_selected = []
    if momentum_valid:
        mom_scores = calc_momentum_scores(nav[momentum_valid], date_idx)
        mom_ranking = mom_scores.sort_values(ascending=False)

        # 处理并列
        current_rank = 0
        score_groups = mom_ranking.groupby(mom_ranking).groups
        unique_scores = sorted(score_groups.keys(), reverse=True)
        for score in unique_scores:
            assets_with_score = list(score_groups[score])
            n_assets = len(assets_with_score)
            start_rank = current_rank + 1
            end_rank = current_rank + n_assets
            avg_rank = (start_rank + end_rank) / 2
            if avg_rank <= top_momentum:
                momentum_selected.extend(assets_with_score)
            else:
                break
            current_rank = end_rank

    # 反转打分
    reversal_selected = []
    if reversal_valid:
        rev_scores = calc_reversal_scores(nav[reversal_valid], date_idx)
        rev_ranking = rev_scores.sort_values(ascending=False)
        max_score = rev_ranking.max()
        top_assets = rev_ranking[rev_ranking == max_score].index.tolist()
        if len(top_assets) == 1:
            reversal_selected = top_assets

    final_selected = list(set(momentum_selected + reversal_selected))

    # 构建入选状态（0/1/2）
    selection_status = {}
    for asset in nav.columns:
        is_mom = asset in momentum_selected
        is_rev = asset in reversal_selected
        if is_mom and is_rev:
            selection_status[asset] = 2
        elif is_mom or is_rev:
            selection_status[asset] = 1
        else:
            selection_status[asset] = 0

    return final_selected, selection_status


# ===========================================================================
# Step 2: 权重计算
# ===========================================================================
def calc_asset_volatility(prices, date_idx, windows=VOL_WINDOWS):
    returns = prices.pct_change()
    vols = {}
    for asset in prices.columns:
        asset_vols = []
        for w in windows:
            if date_idx >= w:
                ret_window = returns[asset].iloc[date_idx - w + 1:date_idx + 1]
                vol = ret_window.std() * ANNUALIZE_FACTOR
                if not np.isnan(vol):
                    asset_vols.append(vol)
        vols[asset] = max(asset_vols) if asset_vols else np.nan
    return pd.Series(vols)


def calc_portfolio_volatility(prices, weights, date_idx, windows=VOL_WINDOWS):
    returns = prices.pct_change()
    valid_assets = [a for a in weights.index if weights[a] > 0 and a in returns.columns]
    if not valid_assets:
        return 0.0

    port_vols = []
    for w in windows:
        if date_idx >= w:
            port_returns = pd.Series(0.0, index=returns.index)
            for asset in valid_assets:
                port_returns += weights[asset] * returns[asset].fillna(0)
            ret_window = port_returns.iloc[date_idx - w + 1:date_idx + 1]
            vol = ret_window.std() * ANNUALIZE_FACTOR
            if not np.isnan(vol):
                port_vols.append(vol)
    return max(port_vols) if port_vols else 0.0


def calc_weights_for_date(nav, date_idx, selection_status):
    """计算单个调仓日的权重"""
    all_assets = nav.columns.tolist()

    # 风险预算
    budgets = {}
    for asset in all_assets:
        status = selection_status.get(asset, 0)
        if status == 2:
            budgets[asset] = 2 / 8
        elif status == 1:
            budgets[asset] = 1 / 8
        else:
            budgets[asset] = 0
    risk_budgets = pd.Series(budgets)

    # 资产波动率
    asset_vols = calc_asset_volatility(nav, date_idx)

    # 初始权重: w = b × (target_vol / σ)
    weights = {}
    for asset in all_assets:
        b = risk_budgets[asset]
        sigma = asset_vols.get(asset, np.nan)
        if b > 0 and sigma > 0 and not np.isnan(sigma):
            weights[asset] = b * (TARGET_VOL / sigma)
        else:
            weights[asset] = 0.0
    initial_weights = pd.Series(weights)

    # 组合波动率
    port_vol = calc_portfolio_volatility(nav, initial_weights, date_idx)

    # 缩放约束
    total_weight = initial_weights.sum()
    if total_weight > 0:
        scale_vol = TARGET_VOL / port_vol if port_vol > 0 else 1.0
        scale_lev = MAX_LEVERAGE / total_weight
        scale = min(scale_vol, scale_lev)
        scaled_weights = initial_weights * scale
    else:
        scaled_weights = initial_weights

    # 权重上限截断
    final_weights = scaled_weights.copy()
    for asset in final_weights.index:
        cap = WEIGHT_CAPS.get(asset, 1.0)
        if final_weights[asset] > cap:
            final_weights[asset] = cap

    return final_weights.to_dict()


# ===========================================================================
# Step 3: 净值回测
# ===========================================================================
def get_fx_rate(fx_df, date, currency):
    if currency == 'CNH':
        return 1.0
    if currency not in fx_df.columns:
        return 1.0
    if date in fx_df.index:
        rate = fx_df.loc[date, currency]
        if not np.isnan(rate):
            return rate
    valid_dates = fx_df.index[fx_df.index <= date]
    for d in reversed(valid_dates):
        rate = fx_df.loc[d, currency]
        if not np.isnan(rate):
            return rate
    return 1.0


def get_fx_rates(fx_df, date, assets):
    return {asset: get_fx_rate(fx_df, date, ASSET_CURRENCY.get(asset, 'CNH'))
            for asset in assets}


def calc_realized_vol(weights, daily_ret_df, windows=VOL_WINDOWS):
    vol_values = []
    w = pd.Series(weights)
    for n in windows:
        if len(daily_ret_df) >= n:
            ret_window = daily_ret_df.iloc[-n:]
            weighted_ret = (ret_window * w).sum(axis=1)
            vol = weighted_ret.std() * np.sqrt(260)
            vol_values.append(vol)
    return max(vol_values) if vol_values else 0.0


def run_backtest(prices, fx_df, trade_dates_list):
    """运行完整回测"""
    assets = prices.columns.tolist()
    trade_dates_set = set(trade_dates_list)

    # 确定月末调仓日
    prices_tmp = prices.copy()
    prices_tmp['year_month'] = prices_tmp.index.to_period('M')
    month_end_dates = prices_tmp.groupby('year_month').tail(1).index.tolist()
    prices_tmp = None

    selection_start_date = pd.Timestamp('2014-01-31')
    valid_month_ends = [d for d in month_end_dates if d >= selection_start_date]

    print(f"\n  月末调仓日数: {len(valid_month_ends)}")
    print(f"  首个调仓日: {valid_month_ends[0].date()}")
    print(f"  最后调仓日: {valid_month_ends[-1].date()}")

    # Step 1+2: 计算每月权重
    print("\n  计算月度权重 (step1+step2) ...")
    weights_df_rows = []
    for i, calc_date in enumerate(valid_month_ends):
        date_idx = prices.index.get_loc(calc_date)
        _, selection_status = select_assets_for_date(prices, date_idx)
        weights = calc_weights_for_date(prices, date_idx, selection_status)
        row = {'计算日期': calc_date}
        row.update(weights)
        weights_df_rows.append(row)
        if (i + 1) % 24 == 0:
            print(f"    进度: {i + 1}/{len(valid_month_ends)}")

    weights_df = pd.DataFrame(weights_df_rows)
    print(f"  权重计算完成: {len(weights_df)} 个调仓日")

    # 构建月度调仓映射（T+2执行）
    monthly_rebalance_map = {}
    for _, row in weights_df.iterrows():
        calc_date = row['计算日期']
        future_dates = [d for d in trade_dates_list if d > calc_date]
        if len(future_dates) >= 2:
            execute_date = future_dates[1]
        elif len(future_dates) == 1:
            execute_date = future_dates[0]
        else:
            continue
        while execute_date in SKIP_EXCLUDED_DATES:
            idx = trade_dates_list.index(execute_date)
            if idx + 1 < len(trade_dates_list):
                execute_date = trade_dates_list[idx + 1]
            else:
                break
        weight_dict = {asset: row.get(asset, 0.0) for asset in assets}
        monthly_rebalance_map[execute_date] = weight_dict

    rebalance_dates_set = set(monthly_rebalance_map.keys())

    # 初始权重
    initial_weights = {asset: weights_df.iloc[0].get(asset, 0.0) for asset in assets}

    # Step 3: 逐日回测
    print("\n  运行逐日回测 (step3) ...")
    backtest_dates = prices.index[prices.index >= BASE_DATE].tolist()
    daily_ret_df = prices[assets].pct_change().fillna(0)

    # 状态变量
    nav = BASE_VALUE
    nav_base = BASE_VALUE
    positions_cny = {a: 0.0 for a in assets}
    positions_local = {a: 0.0 for a in assets}
    apl_local = {a: 0.0 for a in assets}
    target_weights = {a: 0.0 for a in assets}
    last_rebalance_fx = {a: 1.0 for a in assets}
    pending_rebalance = None
    vol_reset_dates_set = set()
    total_trading_cost = 0.0
    total_replication_cost = 0.0
    vol_events = []
    nav_history = []

    prev_date = None
    prev_nav = None

    for date_idx, date in enumerate(backtest_dates):
        fx_rates = get_fx_rates(fx_df, date, assets)

        # A: 指数起始日
        if date == BASE_DATE:
            nav = BASE_VALUE
            nav_base = BASE_VALUE
            for asset in assets:
                w = initial_weights.get(asset, 0.0)
                positions_cny[asset] = nav * w
                positions_local[asset] = positions_cny[asset] / fx_rates[asset]
                apl_local[asset] = 0.0
                target_weights[asset] = w
            last_rebalance_fx = fx_rates.copy()
            nav_history.append({'日期': date, '净值': nav})
            prev_date = date
            prev_nav = nav
            continue

        # B: 每日损益
        days_between = (date - prev_date).days
        daily_replication_cost = 0.0
        for asset in assets:
            if positions_cny[asset] == 0:
                continue
            p1 = prices.loc[date, asset] if asset in prices.columns else np.nan
            p0 = prices.loc[prev_date, asset] if asset in prices.columns else np.nan

            if not np.isnan(p1) and not np.isnan(p0) and p0 > 0:
                r_local = p1 / p0 - 1
            else:
                r_local = 0.0

            currency = ASSET_CURRENCY.get(asset, 'CNH')
            fx_curr = get_fx_rate(fx_df, date, currency)
            fx_prev = get_fx_rate(fx_df, prev_date, currency)
            p1_cny = p1 * fx_curr if not np.isnan(p1) else 0
            p0_cny = p0 * fx_prev if not np.isnan(p0) else 0
            r_cny = (p1_cny / p0_cny - 1) if p0_cny > 0 else 0.0

            pnl_local = positions_local[asset] * r_local
            rc_cost_local = 0.0
            rc = REPLICATION_COST.get(asset, 0.005)
            rc_cost_local = positions_local[asset] * (rc / 365.0) * days_between
            daily_replication_cost += rc_cost_local * fx_rates[asset]

            apl_local[asset] += pnl_local - rc_cost_local
            positions_local[asset] *= (1 + r_local)
            positions_cny[asset] *= (1 + r_cny)

        total_apl_cny = sum(apl_local[a] * fx_rates[a] for a in assets)
        nav = nav_base + total_apl_cny
        total_replication_cost += daily_replication_cost

        # C: 调仓执行（波动率重置优先）
        is_rebalance_day = False
        if pending_rebalance is not None and date == pending_rebalance['execute_date']:
            pr = pending_rebalance
            new_weights = pr['weights']
            # 交易费用
            trading_cost = 0.0
            for asset in assets:
                target_pos = prev_nav * new_weights.get(asset, 0) / fx_rates[asset]
                current_pos = positions_local[asset]
                trade_amount = abs(target_pos - current_pos)
                tc = TRADING_COST.get(asset, 0.001)
                trading_cost += trade_amount * tc * fx_rates[asset]
            nav -= trading_cost
            total_trading_cost += trading_cost

            for asset in assets:
                w = new_weights.get(asset, 0.0)
                positions_cny[asset] = prev_nav * w
                positions_local[asset] = positions_cny[asset] / fx_rates[asset]
                apl_local[asset] = 0.0
                target_weights[asset] = w
            nav_base = nav
            last_rebalance_fx = fx_rates.copy()
            pending_rebalance = None
            is_rebalance_day = True

            if pr.get('type') == 'vol_reset':
                vol_events.append(pr)

        # D: 月度调仓
        if date in rebalance_dates_set and not is_rebalance_day:
            new_weights = monthly_rebalance_map[date]
            trading_cost = 0.0
            for asset in assets:
                target_pos = prev_nav * new_weights.get(asset, 0) / fx_rates[asset]
                current_pos = positions_local[asset]
                trade_amount = abs(target_pos - current_pos)
                tc = TRADING_COST.get(asset, 0.001)
                trading_cost += trade_amount * tc * fx_rates[asset]
            nav -= trading_cost
            total_trading_cost += trading_cost

            for asset in assets:
                w = new_weights.get(asset, 0.0)
                positions_cny[asset] = prev_nav * w
                positions_local[asset] = positions_cny[asset] / fx_rates[asset]
                apl_local[asset] = 0.0
                target_weights[asset] = w
            nav_base = nav
            last_rebalance_fx = fx_rates.copy()
            is_rebalance_day = True
            pending_rebalance = None

        # E: 波动率监测
        if not is_rebalance_day and pending_rebalance is None and date_idx >= MONITOR_START_DAYS:
            if nav > 0:
                w_cny = {a: positions_local[a] * last_rebalance_fx[a] / nav for a in assets}
                ytd_ret = daily_ret_df.loc[:date, assets]
                vol_trigger = calc_realized_vol(w_cny, ytd_ret)

                if vol_trigger > VOL_TRIGGER_THRESHOLD:
                    future_dates = [d for d in trade_dates_list if d > date]
                    if len(future_dates) >= 2:
                        exec_date = future_dates[1]
                        while exec_date in SKIP_EXCLUDED_DATES:
                            idx_td = trade_dates_list.index(exec_date)
                            if idx_td + 1 < len(trade_dates_list):
                                exec_date = trade_dates_list[idx_td + 1]
                            else:
                                exec_date = None
                                break

                        if exec_date:
                            t_plus_1 = future_dates[0]
                            has_conflict = False
                            if date in rebalance_dates_set or date in vol_reset_dates_set:
                                has_conflict = True
                            if t_plus_1 in rebalance_dates_set or t_plus_1 in vol_reset_dates_set:
                                has_conflict = True
                            if exec_date in rebalance_dates_set or exec_date in vol_reset_dates_set:
                                has_conflict = True

                            if not has_conflict:
                                scale_factor = TARGET_VOL / vol_trigger
                                vw_weights = {a: np.trunc(w * scale_factor * 1000) / 1000
                                              for a, w in w_cny.items()}
                                pending_rebalance = {
                                    'execute_date': exec_date,
                                    'weights': vw_weights,
                                    'type': 'vol_reset',
                                    'signal_date': date,
                                    'vol_trigger': vol_trigger,
                                    'scale_factor': scale_factor,
                                }
                                vol_reset_dates_set.add(exec_date)

        # F: 记录
        nav_history.append({'日期': date, '净值': nav})
        prev_date = date
        prev_nav = nav

    nav_df = pd.DataFrame(nav_history).set_index('日期')
    costs = {
        'trading_cost': total_trading_cost,
        'replication_cost': total_replication_cost,
        'total_cost': total_trading_cost + total_replication_cost,
    }
    return nav_df, vol_events, costs


# ===========================================================================
# 绩效指标
# ===========================================================================
def calc_annual_return(nav_series):
    total_return = nav_series.iloc[-1] / nav_series.iloc[0] - 1
    days = (nav_series.index[-1] - nav_series.index[0]).days
    years = days / 365.0
    return (1 + total_return) ** (1 / years) - 1

def calc_annual_volatility(nav_series):
    return nav_series.pct_change().dropna().std() * np.sqrt(260)

def calc_max_drawdown(nav_series):
    cummax = nav_series.cummax()
    drawdown = (nav_series - cummax) / cummax
    return drawdown.min(), drawdown.idxmin()

def calc_sharpe_ratio(nav_series, rf=0.02):
    ar = calc_annual_return(nav_series)
    av = calc_annual_volatility(nav_series)
    return (ar - rf) / av if av > 0 else 0.0


# ===========================================================================
# 主程序
# ===========================================================================
def main():
    print("=" * 70)
    print("混合动量12策略回测验证（从 MongoDB 读取数据）")
    print("=" * 70)

    # 加载数据
    print("\n[1] 从 MongoDB 加载数据...")
    prices, fx_df, trade_dates_list = load_data_from_mongo()

    # 运行回测
    print("\n[2] 运行回测...")
    nav_df, vol_events, costs = run_backtest(prices, fx_df, trade_dates_list)
    nav_series = nav_df['净值']

    # 绩效指标
    annual_return = calc_annual_return(nav_series)
    annual_vol = calc_annual_volatility(nav_series)
    max_dd, max_dd_date = calc_max_drawdown(nav_series)
    sharpe = calc_sharpe_ratio(nav_series)

    print("\n" + "=" * 70)
    print("绩效指标")
    print("=" * 70)
    print(f"  起始日期: {nav_series.index[0].date()}")
    print(f"  结束日期: {nav_series.index[-1].date()}")
    print(f"  起始净值: {nav_series.iloc[0]:.2f}")
    print(f"  结束净值: {nav_series.iloc[-1]:.2f}")
    print(f"  累计收益率: {(nav_series.iloc[-1] / nav_series.iloc[0] - 1) * 100:.2f}%")
    print(f"  年化收益率: {annual_return * 100:.2f}%")
    print(f"  年化波动率: {annual_vol * 100:.2f}%")
    print(f"  最大回撤: {max_dd * 100:.2f}% ({max_dd_date.date()})")
    print(f"  夏普比率: {sharpe:.2f}")
    print("-" * 70)
    print(f"  累计交易费用: {costs['trading_cost']:.2f}")
    print(f"  累计复制费用: {costs['replication_cost']:.2f}")
    print(f"  费用合计: {costs['total_cost']:.2f}")
    print("-" * 70)
    print(f"  波动率重置次数: {len(vol_events)}")
    print("=" * 70)

    # 波动率重置事件
    if vol_events:
        print(f"\n波动率重置事件:")
        print(f"{'信号日期':<12} {'执行日期':<12} {'VolTrigger':>12} {'缩放因子':>10}")
        print("-" * 50)
        for event in vol_events:
            print(f"{str(event['signal_date'].date()):<12} "
                  f"{str(event['execute_date'].date()):<12} "
                  f"{event['vol_trigger']*100:>11.2f}% "
                  f"{event['scale_factor']:>10.4f}")

    print(f"\n最终 NAV = {nav_series.iloc[-1]:.6f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
