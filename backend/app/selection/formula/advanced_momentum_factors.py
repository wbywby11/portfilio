"""
高级动量与反转因子计算模块（与指数编制规则一致）

有效资产集合 SET：资产 c 自基日（不含）至 t 日（含）满 260 个净值计算日则属于 SET。

动量因子定义（n 为窗口参数）：
- MOM_t^c(n) = (TR_t^c/TR_{t-n}^c) - 1，n = 20, 60, 120, 250
- MACD_t^c(n) = k_short - k_long，k_short=price.rolling(win_short).mean()，k_long=price.rolling(win_long).mean()，win_short=n，win_long=250
- POSI_t^c(n) = rpos_t^c(n) + rneg_t^c(n)，rpos/rneg 为过去 n 日正/负收益之和，n = 20, 60, 120, 250
- σ_n^c = sqrt(250/60 * Σ(r_i - mean_n)^2)，60 日窗口，mean_n 为过去 n 日收益均值
- SMOM_t^c(n) = MOM_t^c(n) * (4.5% / σ_n^c)，n = 20, 60, 120, 250

单动量因子交易信号：S_t^c(F,n) = 1 若 F_t^c(n) > -0.02，否则 0。
动量因子综合打分：Score_t^c = ΣS_t^c(MOM,n) + ΣS_t^c(MACD,n) + ΣS_t^c(POSI,n) + ΣS_t^c(SMOM,n)

反转因子：SKEW（窗长 10、22 天），从低到高排序、得分高者优先。
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple

# 交易信号阈值：因子值 > THRESHOLD 则 S=1
SIGNAL_THRESHOLD = -0.02
# SMOM 目标波动率 4.5%
TARGET_VOLATILITY = 0.045
# 波动率计算窗口（日）
VOLATILITY_WINDOW = 60
# 年化系数（波动率公式中的 250/60）
VOL_ANNUALIZATION = 250 / 60


def _max_available_days(prices: pd.DataFrame) -> int:
    """各列非 NaN 长度的最大值。"""
    if prices.empty or len(prices.columns) == 0:
        return 0
    return int(max(prices[c].dropna().shape[0] for c in prices.columns))


def _daily_returns(prices: pd.Series) -> pd.Series:
    """日收益率 r_t = (TR_t / TR_{t-1}) - 1"""
    return prices.pct_change().dropna()


def compute_volatility_sigma_n(
    prices: pd.Series,
    n: int,
    vol_window: int = VOLATILITY_WINDOW,
) -> float:
    """计算波动率 σ_n^c.
    
    公式: σ_n^c = sqrt(250/60 * Σ_{i=t-60+1}^{t} (r_i - mean_n)^2)
    - r_i = (TR_i/TR_{i-1}) - 1
    - mean_n = (1/n) * Σ_{i=t-n+1}^{t} r_i
    需要至少 max(60, n) 个交易日数据。
    """
    returns = _daily_returns(prices)
    need = max(vol_window, n)
    if len(returns) < need:
        return 0.0
    r_last = returns.iloc[-vol_window:]
    mean_n = returns.iloc[-n:].mean()
    if isinstance(mean_n, pd.Series):
        mean_n = mean_n.iloc[0] if len(mean_n) > 0 else 0.0
    deviations = r_last - mean_n
    sum_sq = (deviations ** 2).sum()
    if isinstance(sum_sq, pd.Series):
        sum_sq = sum_sq.iloc[0] if len(sum_sq) > 0 else 0.0
    sigma = np.sqrt(VOL_ANNUALIZATION * float(sum_sq))
    return float(sigma)


def compute_simple_momentum(prices: pd.Series, window: int) -> float:
    """简单时序动量 MOMc(n) = (TR_t / TR_{t-n}) - 1"""
    if len(prices) < window + 1:
        return 0.0
    return float((prices.iloc[-1] / prices.iloc[-window - 1]) - 1)


def f_macd(
    price: pd.Series,
    win_short: int,
    win_long: int,
) -> pd.Series:
    """MACD 线：价格的短长期简单均线之差.
    
    macd = k_short - k_long
    k_short = price.rolling(win_short).mean()
    k_long = price.rolling(win_long).mean()
    """
    k_short = price.rolling(win_short).mean()
    k_long = price.rolling(win_long).mean()
    macd = k_short - k_long
    return macd


def f_macd_rank(
    price: pd.DataFrame,
    win_short: int,
    win_long: int,
) -> pd.DataFrame:
    """MACD 橫截面排名（每行/每日期按列/资产排名，ascending=True 小值排名低）."""
    macd = f_macd(price, win_short, win_long)
    return macd.rank(ascending=True, axis=1)


def f_macd_signal(
    price: pd.Series,
    win_short: int,
    win_long: int,
    th: float,
) -> pd.Series:
    """MACD 交易信号：macd > th 则为 1，否则 0."""
    macd = f_macd(price, win_short, win_long)
    macd_signal = macd.copy()
    macd_signal[macd > th] = 1
    macd_signal[macd <= th] = 0
    return macd_signal


def compute_macd_momentum_new(
    prices: pd.Series,
    window: int,
    long_window: int = 250,
) -> float:
    """双均线动量（收益率比值）MACD_t^c(n) = ((TR_t^c/TR_{t-n}^c)-1) / ((TR_t^c/TR_{t-250}^c)-1).
    
    编制规则：n 期动量 / 250 期动量，n = 40, 80, 120, 160。
    """
    if len(prices) < long_window + 1 or window < 1:
        return 0.0
    mom_n = (prices.iloc[-1] / prices.iloc[-window - 1]) - 1
    mom_250 = (prices.iloc[-1] / prices.iloc[-long_window - 1]) - 1
    if abs(mom_250) < 1e-12:
        return 0.0
    return float(mom_n / mom_250)


def compute_posi_momentum_new(prices: pd.Series, window: int) -> float:
    """收益正负差因子（新定义）POSIc(n) = rpos^c(n) + rneg^c(n).
    
    rpos = Σ r_i * I_{r_i>0}, rneg = Σ r_i * I_{r_i<0}，均为过去 n 日。
    """
    if len(prices) < window + 1:
        return 0.0
    returns = _daily_returns(prices).iloc[-window:]
    rpos = returns[returns > 0].sum()
    rneg = returns[returns < 0].sum()
    if isinstance(rpos, pd.Series):
        rpos = rpos.iloc[0] if len(rpos) > 0 else 0.0
    if isinstance(rneg, pd.Series):
        rneg = rneg.iloc[0] if len(rneg) > 0 else 0.0
    return float(rpos + rneg)


def compute_smom_momentum_new(
    prices: pd.Series,
    window: int,
    target_vol: float = TARGET_VOLATILITY,
) -> float:
    """缩放动量（新定义）SMOMc(n) = MOMc(n) * (4.5% / σ_n^c)"""
    if len(prices) < window + 1:
        return 0.0
    mom = compute_simple_momentum(prices, window)
    sigma = compute_volatility_sigma_n(prices, window)
    if sigma <= 0:
        return 0.0
    return float(mom * (target_vol / sigma))


def trading_signal(factor_value: float, threshold: float = SIGNAL_THRESHOLD) -> int:
    """单动量因子交易信号 S_c(F,n)：F > threshold 则为 1，否则 0"""
    return 1 if factor_value > threshold else 0


def compute_skew_factor(prices: pd.Series, window: int, use_price: bool = True) -> float:
    """偏度因子 SKEW（反转因子）.
    
    编制规则 B.1.2：计算对象为价格序列(非收益率)。
    use_price=True 时对价格计算偏度；use_price=False 时对收益率计算（兼容旧逻辑）。
    """
    if len(prices) < window + 1:
        return 0.0
    data = prices.iloc[-window:] if use_price else prices.pct_change().iloc[-window:]
    s = data.skew()
    return 0.0 if pd.isna(s) else float(s)


# 新定义默认窗口
DEFAULT_MOM_WINDOWS = [20, 60, 120, 250]
DEFAULT_MACD_WINDOWS = [40, 80, 120, 160]
DEFAULT_POSI_WINDOWS = [20, 60, 120, 250]
DEFAULT_SMOM_WINDOWS = [20, 60, 120, 250]
DEFAULT_REVERSAL_WINDOWS = [10, 22]

# 动量总分上限：等于所有 S_c(F,n) 的个数（MOM+MACD+POSI+SMOM 各周期数之和）
MAX_MOMENTUM_SCORE = (
    len(DEFAULT_MOM_WINDOWS)
    + len(DEFAULT_MACD_WINDOWS)
    + len(DEFAULT_POSI_WINDOWS)
    + len(DEFAULT_SMOM_WINDOWS)
)


def compute_advanced_momentum_scores(
    prices: pd.DataFrame,
    momentum_windows: Dict[str, List[int]] = None,
    reversal_windows: List[int] = None,
    min_history_days: int = 260,
    min_history_reversal: int = 22,
    use_price_skew: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """计算所有资产的高级动量与反转因子得分.
    
    编制规则：动量有效资产需260天，反转有效资产需22天（差异化处理）。
    动量综合打分 = Σ S_c(MOM,n) + Σ S_c(MACD,n) + Σ S_c(POSI,n) + Σ S_c(SMOM,n)，
    其中 S_c(F,n) = 1 若 F_c(n) > -0.02 否则 0。
    反转：偏度计算对象为价格序列(非收益率)，排名 method='average'。
    """
    if momentum_windows is None:
        momentum_windows = {
            "MOM": DEFAULT_MOM_WINDOWS,
            "MACD": DEFAULT_MACD_WINDOWS,
            "POSI": DEFAULT_POSI_WINDOWS,
            "SMOM": DEFAULT_SMOM_WINDOWS,
        }
    if reversal_windows is None:
        reversal_windows = DEFAULT_REVERSAL_WINDOWS

    # 编制规则：动量有效资产 260 天，反转有效资产 22 天（独立有效池）
    max_avail = _max_available_days(prices)
    effective_mom = min_history_days if max_avail >= min_history_days else min(260, max(60, max_avail - 10))
    effective_mom = max(effective_mom, 26)
    effective_rev = max(min_history_reversal, 22)
    momentum_valid = [c for c in prices.columns if prices[c].dropna().shape[0] >= effective_mom]
    reversal_valid = [c for c in prices.columns if prices[c].dropna().shape[0] >= effective_rev]
    valid = list(set(momentum_valid) | set(reversal_valid))
    if not valid:
        raise ValueError(
            f"没有资产满足最小历史数据要求(动量需≥{effective_mom}天，反转需≥{effective_rev}天)。"
            f"各资产可用天数不足，请检查数据或放宽回测起始日期。"
        )

    mom_rows = []
    for c in momentum_valid:
        p = prices[c].dropna()
        r = {"asset": c}
        for w in momentum_windows.get("MOM", DEFAULT_MOM_WINDOWS):
            val = compute_simple_momentum(p, w)
            r[f"MOM_{w}"] = val
            r[f"S_MOM_{w}"] = trading_signal(val)
        for w in momentum_windows.get("MACD", DEFAULT_MACD_WINDOWS):
            win_short, win_long = w, 250
            if len(p) >= win_long:
                macd_s = f_macd(p, win_short, win_long)
                macd_dropped = macd_s.dropna()
                val = float(macd_dropped.iloc[-1]) if len(macd_dropped) > 0 else 0.0
            else:
                val = 0.0
            r[f"MACD_{w}"] = val
            r[f"S_MACD_{w}"] = trading_signal(val)
        for w in momentum_windows.get("POSI", DEFAULT_POSI_WINDOWS):
            val = compute_posi_momentum_new(p, w)
            r[f"POSI_{w}"] = val
            r[f"S_POSI_{w}"] = trading_signal(val)
        for w in momentum_windows.get("SMOM", DEFAULT_SMOM_WINDOWS):
            val = compute_smom_momentum_new(p, w)
            r[f"SMOM_{w}"] = val
            r[f"S_SMOM_{w}"] = trading_signal(val)
        mom_rows.append(r)

    mom_df = pd.DataFrame(mom_rows).set_index("asset") if mom_rows else pd.DataFrame()

    # 综合打分 = 所有 S_c(F,n) 信号列之和
    if not mom_df.empty:
        s_cols = [c for c in mom_df.columns if c.startswith("S_") and any(x in c for x in ("MOM_", "MACD_", "POSI_", "SMOM_"))]
        mom_df["TotalMomentumScore"] = mom_df[s_cols].sum(axis=1)
        for col in s_cols:
            mom_df[f"Score_{col[2:]}"] = mom_df[col]
        n_mom = len(momentum_valid)
        mom_df["Rank_Total"] = mom_df["TotalMomentumScore"].rank(ascending=False, method="min")
        mom_df["Score_Total"] = n_mom - mom_df["Rank_Total"] + 1
        mom_df = mom_df.sort_values("TotalMomentumScore", ascending=False)

    # 反转因子：SKEW，编制规则 B.1.2 价格序列(非收益率)，排名 method='average'
    rev_rows = []
    for c in reversal_valid:
        p = prices[c].dropna()
        r = {"asset": c}
        for w in reversal_windows:
            r[f"SKEW_{w}"] = compute_skew_factor(p, w, use_price=use_price_skew)
        rev_rows.append(r)
    rev_df = pd.DataFrame(rev_rows).set_index("asset") if rev_rows else pd.DataFrame()
    if not rev_df.empty:
        n_rev = len(reversal_valid)
        for col in rev_df.columns:
            if not col.startswith(("Rank_", "Score_")):
                rev_df[f"Rank_{col}"] = rev_df[col].rank(ascending=True, method="average")
                rev_df[f"Score_{col}"] = n_rev - rev_df[f"Rank_{col}"] + 1
        rc = [f"Score_{x}" for x in rev_df.columns if not x.startswith(("Rank_", "Score_"))]
        rev_df["TotalReversalScore"] = rev_df[rc].sum(axis=1)
        rev_df = rev_df.sort_values("TotalReversalScore", ascending=False)

    return mom_df, rev_df


def _select_top_exclude_ties_at_cutoff(
    df: pd.DataFrame, score_col: str, n: int
) -> List[str]:
    """取前 n 名，并列最低的都不入选。"""
    if len(df) == 0 or n <= 0:
        return []
    if n >= len(df):
        return df.index.tolist()
    cutoff_score = df[score_col].iloc[n - 1]
    return df[df[score_col] > cutoff_score].index.tolist()


def _select_reversal_unique_max(
    df: pd.DataFrame, score_col: str, n: int = 1
) -> List[str]:
    """编制规则：选取综合得分最高的 n 个；若最高分存在并列，则全部不入选。"""
    if len(df) == 0 or n <= 0:
        return []
    df = df.sort_values(score_col, ascending=False)
    max_score = df[score_col].iloc[0]
    top_assets = df[df[score_col] == max_score].index.tolist()
    if len(top_assets) == 1:
        return top_assets[:n]
    return []  # 并列则都不入选


def _select_strict_top_k(
    df: pd.DataFrame, score_col: str, n: int
) -> List[str]:
    """严格取综合得分前 n 名，同分时按排序结果截断（不做并列扩张/剔除）。

    该规则与四象限策略原型一致：``scores.sort_values(ascending=False).index[:n]``。
    编制规则的平均排名口径会让入选数在 n 附近波动（同分整组入选或整组剔除），
    使 tag_based 预算的实际占用槽位数与 ``n_momentum + n_reversal`` 不符。
    """
    if len(df) == 0 or n <= 0:
        return []
    return df.sort_values(score_col, ascending=False).index[:n].tolist()


def _select_top_by_average_rank(
    df: pd.DataFrame, score_col: str, n: int
) -> List[str]:
    """动量入选规则：同分资产共享「平均排名」；平均排名<=n 则整组入选，>n 则整组不入选。
    例：第7、8名同分 → 平均排名 7.5 > 7 → 都不入选；第6、7、8名同分 → 平均排名 7 <= 7 → 都入选。
    """
    if len(df) == 0 or n <= 0:
        return []
    if n >= len(df):
        return df.index.tolist()
    df = df.sort_values(score_col, ascending=False)
    ranks = np.arange(1, len(df) + 1, dtype=float)
    scores = df[score_col].values
    avg_rank = np.zeros(len(df))
    i = 0
    while i < len(df):
        j = i
        while j < len(df) and scores[j] == scores[i]:
            j += 1
        group_avg = ranks[i:j].sum() / (j - i)
        avg_rank[i:j] = group_avg
        i = j
    selected = df.index[avg_rank <= n].tolist()
    return selected


def select_momentum_and_reversal_assets(
    prices: pd.DataFrame,
    n_momentum: int = 7,
    n_reversal: int = 1,
    momentum_windows: Dict[str, List[int]] = None,
    reversal_windows: List[int] = None,
    min_history_days: int = 260,
    min_history_reversal: int = 22,
    use_price_skew: bool = True,
    tie_rule: str = "index_rule",
) -> Tuple[List[str], List[str], pd.DataFrame, pd.DataFrame]:
    """基于动量与反转双模型选择资产.

    Args:
        tie_rule: 同分处理口径。
            ``index_rule``（默认，指数编制规则）动量按平均排名整组入选/剔除，
            反转最高分并列时全部不入选，入选数会在 n 附近浮动；
            ``strict`` 严格取前 n 名，动量与反转各自恒为 n 个，槽位数与预算分母一致。
    """
    mom_df, rev_df = compute_advanced_momentum_scores(
        prices=prices,
        momentum_windows=momentum_windows,
        reversal_windows=reversal_windows,
        min_history_days=min_history_days,
        min_history_reversal=min_history_reversal,
        use_price_skew=use_price_skew,
    )
    if str(tie_rule).lower() == "strict":
        mom_sel = _select_strict_top_k(mom_df, "TotalMomentumScore", n_momentum) if not mom_df.empty else []
        rev_sel = _select_strict_top_k(rev_df, "TotalReversalScore", n_reversal) if not rev_df.empty else []
        return mom_sel, rev_sel, mom_df, rev_df
    mom_sel = _select_top_by_average_rank(mom_df, "TotalMomentumScore", n_momentum) if not mom_df.empty else []
    rev_sel = _select_reversal_unique_max(rev_df, "TotalReversalScore", n_reversal) if not rev_df.empty else []
    return mom_sel, rev_sel, mom_df, rev_df
