"""行业择时目标波动（industry_timing_target_vol）：目标波动打底 + 三形态时点行业 + DAR 成长控仓.

方法（信号日收盘计算，次一交易日收盘成交；三层逐日重算）：

1. **月末大类配置**（``base_alloc_mode`` 两选一，现金代理承接剩余、权重合计恒为 1）：
   ``risk_budget``（默认，原型口径）用最近 ``cov_window`` 日普通样本协方差
   （ddof=1、年化），先在权益内部（``equity_codes``）与债券内部（``bond_codes``）
   做等风险贡献（坐标下降解 ``x_i(Σx)_i = 1/n``），得到 10×4 大类映射矩阵，
   再在「股票/黄金/债券/现金」四桶上以目标波动等式约束求风险贡献最均衡的解
   （多起点 SLSQP，沿现金→候选线段 brentq 定标）；
   ``inverse_vol`` 不分组、不做风险平价，直接按各资产多窗口年化波动
   （``inv_vol_windows`` 取最大值）的倒数分配非现金资产，再整体缩放到
   ``vol_target``，剩余进现金代理；缩放后风险资产合计超过 1 时按 nous 同款
   压回满仓，实际波动低于目标，审计记 ``inv_vol_capped``。
   结果按自然月前向填充为日频 ``original``；
2. **风险复核**：``risk_anchor`` 把 ``original`` 沿「现金 → 中性组合」线段收缩到
   ``vol_max`` 以内（对 63/252/756 三个窗口的协方差同时可行），得 ``neutral``；
3. **三形态时点行业**：市场基准（``market_codes``）的下跌反弹 / 顶部切换 / 横盘突破
   三种形态识别事件日，事件日按「信号日超额动量」给候选行业打分，多个事件按
   距今天数 ``2^(-age/combo_half_life)``（``age ≤ combo_age``）加权合成综合分；
   事件后 ``timing_hold`` 个交易日内持有综合分前 ``timing_top`` 只行业（等权），
   空窗期回到权益风险平价；
4. **权益内部融合**：``raw`` = 中性权益的一半 + 事件候选的一半（无事件时同样用
   中性权益的组内配比），非权益部分保持中性配置；
5. **DAR 成长控仓**：31 个行业收益的指数加权（半衰期 ``dar_half_life``）滚动
   250 日协方差，取前 ``dar_components`` 个特征值占比为 AR；AR 的 5 日/125 日/
   250 日均值与标准差构成 DAR 长短信号，长短一致才给出 ±1，再由 AR 5 日变化
   确认单边信号；5 日均值 ≥ ``dar_trigger`` → 成长减到 0、≤ −``dar_trigger`` →
   保持满仓，``dar_hold_days`` 日锁定期。释放资金转入现金代理；
6. **约束投影**：沿 ``neutral → raw`` 线段求最大可行 α：主动风险（756 日协方差）
   不超过 ``te_ratio × vol_target``，总波动 63/252/756 三窗口均不超过 ``vol_max``。

成本：``transaction_cost`` 作为分资产费率由引擎在成交时按成交额扣除，与原型
``Σ|目标−调仓前实际权重| × 费率`` 同口径；监控通道成本参数取自同一份 params。

面板：``get_extra_panels`` 声明 ``asset_metrics``（``asset_prices`` 的
high/low/amount 截面）。价格矩阵只承载收盘价，而三形态的 ATR 与通道宽度依赖
日内高低点；**不声明** ``panel_event_dates``——面板是日频的，一旦被当作调仓
事件日会把日频调仓退化成面板驱动。

红线：``allocate`` 为纯函数，只消费注入的 prices 与 params（含 ``_as_of``、
``_panel_asset_metrics``），不读文件、不查库；分组、窗口、阈值、目标波动全部
来自参数，不写死资产代码与日期；历史不足、分组未覆盖全池、参数不自洽、面板
缺失一律报错，不兜底等权、不跳过资产、不放宽断言。
"""

from __future__ import annotations

import calendar
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import brentq, minimize

from app.allocation.models.base import BaseStrategyModel

_TAG = "industry_timing_target_vol"
_log = logging.getLogger(__name__)

# 面板名（与 data_feed.PANEL_LOADERS 注册键、get_extra_panels 声明一致）
_PANEL_NAME = "asset_metrics"

# 分组参数名 → 包内组键
GROUP_PARAM_TO_KEY: Dict[str, str] = {
    "equity_codes": "EQ",
    "commodity_codes": "GOLD",
    "bond_codes": "BOND",
    "cash_codes": "CASH",
    "industry_codes": "IND",
    "market_codes": "MKT",
}
GROUP_KEYS: Tuple[str, ...] = ("EQ", "GOLD", "BOND", "CASH", "IND", "MKT")
_GROUP_CONFIG_KEY: Dict[str, str] = {v: k for k, v in GROUP_PARAM_TO_KEY.items()}

# 三形态参数默认值（逐条对齐研究原型）
_FORM_DEFAULTS: Dict[str, float] = {
    # 下跌反弹
    "m_cap": 40.0,
    "decline_base": 0.08,
    "rebound_base": 0.005,
    "atr_window": 90.0,
    "atr_lag": 1.0,
    "min_peak_trough_gap": 3.0,
    "signal_cooldown": 5.0,
    # 顶部切换
    "high_window": 252.0,
    "high_band": 0.995,
    "min_previous_high_count": 3.0,
    "high_count_drop": 3.0,
    "atr_multiple": 1.5,
    "top_cooldown": 20.0,
    # 横盘突破
    "flat_days": 5.0,
    "contraction_limit": 0.01,
    "breakout_limit": 0.01,
    "channel_days": 5.0,
    "breakout_cooldown": 5.0,
}

TOL = 1e-9

# 月末大类配置的两种求解方式：
#   risk_budget —— 权益/债券组内等风险贡献 + 四桶目标波动等式（原型口径，默认）
#   inverse_vol —— 各资产多窗口年化波动取倒数分配，再整体缩放到目标波动（nous 口径）
_BASE_MODES: Tuple[str, ...] = ("risk_budget", "inverse_vol")
_DEFAULT_INV_VOL_WINDOWS = (22, 65, 130)


# ---------------------------------------------------------------------------
# 纯函数：参数解析
# ---------------------------------------------------------------------------


def _as_float(value: Any, default: float, name: str) -> float:
    """参数转浮点；None 取默认值，非数值报错（不做静默回退）."""
    if value is None or value == "":
        return float(default)
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"[{_TAG}] 参数 {name} 必须为数值，收到 {value!r}") from exc
    if not np.isfinite(out):
        raise ValueError(f"[{_TAG}] 参数 {name} 非有限值：{value!r}")
    return out


def _as_int(value: Any, default: int, name: str, minimum: int = 1) -> int:
    """参数转正整数；None 取默认值，越界报错."""
    if value is None or value == "":
        return int(default)
    try:
        out = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"[{_TAG}] 参数 {name} 必须为整数，收到 {value!r}") from exc
    if out < minimum:
        raise ValueError(f"[{_TAG}] 参数 {name} 必须不小于 {minimum}，收到 {out}")
    return out


def _parse_int_list(value: Any, default: Sequence[int], name: str) -> Tuple[int, ...]:
    """逗号分隔的整数列表参数（如协方差窗口 ``63,252,756``）."""
    if value is None or value == "":
        return tuple(int(v) for v in default)
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        parts = str(value).replace("，", ",").split(",")
    try:
        out = tuple(int(round(float(p))) for p in parts if str(p).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"[{_TAG}] 参数 {name} 必须是逗号分隔的整数，收到 {value!r}") from exc
    if not out or any(v <= 1 for v in out):
        raise ValueError(f"[{_TAG}] 参数 {name} 每个窗口都必须大于 1，收到 {out}")
    return out


def _model_level_params(execution_delay: int) -> List[Any]:
    """通用模型级参数组，并把 ``execution_delay`` 的默认值对齐本策略调度声明.

    通用组默认 0；本策略缺省 T+1 执行，若沿用 0 则前端按默认值提交后会把
    :meth:`get_execution_schedule` 声明的 1 覆盖成 0（Pipeline 以模型参数为准）。
    """
    from dataclasses import replace

    from app.allocation.models.param_schema import model_level_param_group

    out: List[Any] = []
    for param in model_level_param_group():
        if param.name == "execution_delay":
            param = replace(
                param,
                default=int(execution_delay),
                min_value=1,
                description=(
                    "信号日到成交日的交易日延迟；本策略为每日信号、次一交易日成交（T+1），"
                    "不得低于 1"
                ),
            )
        out.append(param)
    return out


# ---------------------------------------------------------------------------
# 纯函数：目标波动配置（逐行对齐研究原型 目标波动配置.py）
# ---------------------------------------------------------------------------


def _risk_parity(cov: np.ndarray) -> np.ndarray:
    """坐标下降求解正权重等风险贡献：x_i(Σx)_i = 1/n，再归一化."""
    c = cov / np.max(np.diag(cov))
    n = len(c)
    x = 1 / np.sqrt(np.diag(c))
    for _ in range(10000):
        old = x.copy()
        for i in range(n):
            cross = c[i] @ x - c[i, i] * x[i]
            x[i] = (-cross + np.sqrt(cross * cross + 4 * c[i, i] / n)) / (2 * c[i, i])
        if np.max(np.abs(x - old)) < 1e-12:
            break
    w = x / x.sum()
    rc = w * (c @ w)
    if np.max(np.abs(rc / rc.sum() - 1 / n)) > 1e-7:
        raise RuntimeError(f"[{_TAG}] 风险平价未收敛")
    return w


def _bucket_mapping(cov: np.ndarray) -> np.ndarray:
    """每一列是一类资产的内部组合（4 权益 / 黄金 / 4 债券 / 现金），10×4."""
    m = np.zeros((10, 4))
    m[:4, 0] = _risk_parity(cov[:4, :4])
    m[4, 1] = 1.0
    m[5:9, 2] = _risk_parity(cov[5:9, 5:9])
    m[9, 3] = 1.0
    return m


def _risk_balance_loss(w: np.ndarray, cov: np.ndarray) -> float:
    """现金作为剩余资金不给等风险预算；三类风险资产贡献归一化后比较."""
    rc = w[:3] * (cov @ w)[:3]
    total = rc.sum()
    if total <= 1e-14:
        return 1e6
    b = np.full(3, 1 / 3)
    return float(np.sum((rc / total - b) ** 2))


def _solve_buckets(cov: np.ndarray, target: float) -> Tuple[np.ndarray, float]:
    """长仓、无杠杆、权重和为 1；目标波动率等式下尽量均衡大类风险贡献."""
    c = cov / target**2
    cash = np.array([0.0, 0.0, 0.0, 1.0])
    min_result = minimize(
        lambda w: w @ c @ w,
        np.full(4, 0.25),
        jac=lambda w: 2 * c @ w,
        method="SLSQP",
        bounds=[(0, 1)] * 4,
        constraints=[
            {"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(4)}
        ],
        options={"ftol": 1e-12, "maxiter": 500},
    )
    if not min_result.success:
        raise RuntimeError(f"[{_TAG}] 最小波动组合未收敛")
    if min_result.fun > 1 + 1e-7 or np.max(np.diag(c)) < 1 - 1e-7:
        raise ValueError(
            f"[{_TAG}] 目标波动率 {target:.4%} 在无杠杆可行范围之外（请调整 vol_target）"
        )
    anchor = cash if cash @ c @ cash < 1 else min_result.x
    seeds: List[np.ndarray] = []
    mixes = [_np_append(_risk_parity(cov[:3, :3])), np.array([1 / 3, 1 / 3, 1 / 3, 0.0])]
    mixes += list(np.eye(4)[:3])
    # 非凸约束下保留债券占比较高的可行起点，覆盖分散组合与现金缩放组合
    mixes += [
        np.array([i / 20, j / 20, 1 - (i + j) / 20, 0.0])
        for i in range(21)
        for j in range(21 - i)
    ]
    for mix in mixes:
        if mix @ c @ mix >= 1 and anchor @ c @ anchor <= 1:
            q = brentq(
                lambda a: (anchor + a * (mix - anchor)) @ c @ (anchor + a * (mix - anchor)) - 1,
                0,
                1,
            )
            seeds.append(anchor + q * (mix - anchor))
    seeds.sort(key=lambda w: _risk_balance_loss(w, c))
    chosen: List[np.ndarray] = []
    for s in seeds:
        if all(np.linalg.norm(s - old) > 0.025 for old in chosen):
            chosen.append(s)
        if len(chosen) == 8:
            break
    constraints = [
        {"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(4)},
        {"type": "eq", "fun": lambda w: w @ c @ w - 1, "jac": lambda w: 2 * c @ w},
    ]
    feasible: List[Tuple[float, np.ndarray]] = []
    for x0 in chosen:
        sol = minimize(
            _risk_balance_loss,
            x0,
            args=(c,),
            method="SLSQP",
            bounds=[(0, 1)] * 4,
            constraints=constraints,
            options={"ftol": 1e-11, "maxiter": 500},
        )
        w = sol.x
        if (
            sol.success
            and abs(w.sum() - 1) < 1e-7
            and abs(w @ c @ w - 1) < 1e-7
            and w.min() >= -1e-9
        ):
            feasible.append((sol.fun, w))
    if not feasible:
        raise RuntimeError(f"[{_TAG}] 目标波动配置无收敛解，不沿用失效仓位")
    _, w = min(feasible, key=lambda item: item[0])
    w = np.maximum(w, 0)
    w[w < 1e-14] = 0
    w /= w.sum()
    return w, _risk_balance_loss(w, c)


def _np_append(vec: np.ndarray) -> np.ndarray:
    """把 3 维风险平价权重补成 4 维桶向量（第四桶为现金，权重 0）."""
    return np.r_[np.asarray(vec, dtype=float), 0.0]


def _constrain_alpha(
    base: np.ndarray,
    raw: np.ndarray,
    covs: Sequence[np.ndarray],
    upper: float,
    te_cap: Optional[float],
) -> Tuple[np.ndarray, float]:
    """沿中性→候选持仓的线段收缩：优先总波动上限，主动风险以最长窗口协方差计.

    ``covs`` 必须按窗口升序给出（63/252/756），与原型 dict 的迭代顺序一致——
    α 逐窗口取 min，顺序会影响被裁剪到的中间值。
    """
    diff = raw - base
    alpha = 1.0
    if te_cap is not None:
        te = float(np.sqrt(max(diff @ covs[-1] @ diff, 0.0)))
        alpha = min(alpha, float(te_cap / max(te, 1e-15)))
    for c in covs:
        aa = float(diff @ c @ diff)
        bb = float(2.0 * (base @ c @ diff))
        cc = float(base @ c @ base - upper**2)
        trial = aa * alpha**2 + bb * alpha + cc
        if trial > 1e-12:
            disc = max(bb**2 - 4 * aa * cc, 0.0)
            if aa > 1e-15:
                root = (-bb + np.sqrt(disc)) / (2 * aa)
            elif bb > 1e-15:
                root = -cc / bb
            else:
                root = 1.0
            alpha = min(alpha, float(np.clip(root, 0.0, 1.0)))
    return base + diff * alpha, alpha


def _risk_anchor(base: np.ndarray, covs: Sequence[np.ndarray], upper: float) -> np.ndarray:
    """中性组合超波动上限时，向现金收缩到可行（现金风险同样来自普通协方差）."""
    cash = np.zeros_like(base)
    cash[-1] = 1.0
    return _constrain_alpha(cash, base, covs, upper, None)[0]


# ---------------------------------------------------------------------------
# 纯函数：波动率倒数风险预算（nous_low_vol 的 asset_volatility /
# portfolio_volatility / _raw_inverse_vol_weights 三条口径）
# ---------------------------------------------------------------------------


def _multi_window_vol(
    prices: pd.DataFrame, windows: Sequence[int], ann_days: int
) -> pd.Series:
    """各资产多窗口年化波动率取最大值（nous 的 asset_volatility 口径）.

    每个窗口用最近 ``w`` 个日收益率算样本标准差（ddof=1）再年化；历史不足的
    窗口跳过；全部窗口都不足时该资产记 NaN，由调用方报错，不做兜底。
    """
    rets = prices.pct_change(fill_method=None).iloc[1:]
    factor = float(np.sqrt(float(ann_days)))
    out: Dict[str, float] = {}
    for col in prices.columns:
        collected: List[float] = []
        for w in windows:
            if len(rets) < w:
                continue
            vol = float(rets[col].iloc[-w:].std()) * factor
            if np.isfinite(vol):
                collected.append(vol)
        out[str(col)] = max(collected) if collected else float("nan")
    return pd.Series(out)


def _weighted_port_vol(
    prices: pd.DataFrame,
    weights: pd.Series,
    windows: Sequence[int],
    ann_days: int,
) -> float:
    """加权组合收益的多窗口年化波动取最大值（nous 的 portfolio_volatility 口径）."""
    rets = prices.pct_change(fill_method=None).iloc[1:]
    port = pd.Series(0.0, index=rets.index, dtype=float)
    for asset in weights.index:
        w = float(weights.get(asset, 0.0))
        if w > 0 and asset in rets.columns:
            port = port + w * rets[asset].fillna(0.0)
    factor = float(np.sqrt(float(ann_days)))
    biggest = 0.0
    for w in windows:
        if len(port) < w:
            continue
        vol = float(port.iloc[-w:].std()) * factor
        if np.isfinite(vol):
            biggest = max(biggest, vol)
    return biggest


def _inverse_vol_config(
    px: pd.DataFrame, assets: Sequence[str], cfg: Dict[str, Any]
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """波动率倒数风险预算（nous 口径）的月末大类配置，返回 (权重, 审计).

    ``assets`` 顺序与四桶模式一致（权益 → 黄金 → 债券 → 现金），最后一位是现金
    代理。不做组内等风险贡献、不解非线性约束：非现金资产按 ``(1/N)×(1/σ)``
    分配后整体缩放到 ``vol_target``，现金代理承接剩余权重，与四桶模式「现金桶
    承接残余、权重合计恒为 1」的约定一致。

    缩放规则与 nous 的 ``_vol_scale`` 逐条对齐：缩放后风险资产合计超过 1（目标
    波动在无杠杆前提下不可达）时按比例压回满仓，实际波动因此低于 ``vol_target``。
    这是常态分支而非异常：默认池（4 权益 + 黄金 + 4 中债）的 1/σ 组合事前波动
    只有约 33bp，而 ``vol_target`` 默认 125bp，需要 3.8 倍权重才够。
    故这里必须与 nous 同款处理，但把事实记进返回的审计（``capped`` / ``scale`` /
    ``normalized_vol``），供监控页与验收对账，不静默。
    """
    risky = [a for a in assets[:-1] if a]
    if not risky:
        raise ValueError(f"[{_TAG}] 波动率倒数模式没有非现金资产可配置")
    windows = tuple(int(w) for w in cfg["inv_vol_windows"])
    target = float(cfg["vol_target"])
    sub = px[list(risky)]
    vols = _multi_window_vol(sub, windows, int(cfg["ann_days"]))
    bad = [a for a in risky if not np.isfinite(vols.get(a, np.nan)) or vols[a] <= 0]
    if bad:
        raise ValueError(
            f"[{_TAG}] 波动率倒数模式无法估计以下资产的波动率：{bad}。"
            f"请把回测起始日推后到覆盖 {max(windows)} 个交易日，或缩短 inv_vol_windows"
        )
    n = len(risky)
    raw = pd.Series(0.0, index=list(risky), dtype=float)
    for asset in risky:
        raw[asset] = (1.0 / n) * (1.0 / float(vols[asset]))
    port_vol = _weighted_port_vol(sub, raw, windows, int(cfg["ann_days"]))
    if port_vol <= 0:
        raise ValueError(f"[{_TAG}] 波动率倒数模式的组合波动率为 0，无法缩放到目标波动")
    scale = target / port_vol
    scaled = raw * scale
    total = float(scaled.sum())
    capped = total > 1.0 + 1e-9
    if capped:
        scaled = scaled / total
        total = 1.0
    info: Dict[str, Any] = {
        "vol_target": target,
        "scale": float(scale),
        "capped": bool(capped),
        "normalized_vol": float(port_vol / float(raw.sum())),
        "risky_weight": float(total),
        "cash_weight": float(max(1.0 - total, 0.0)),
    }
    out = np.zeros(len(assets), dtype=float)
    out[: len(risky)] = scaled.to_numpy(dtype=float)
    out[-1] = info["cash_weight"]
    return out, info


# ---------------------------------------------------------------------------
# 纯函数：DAR 成长控仓（逐行对齐研究原型 DAR风险控制.py）
# ---------------------------------------------------------------------------


def _exponential_weights(window: int, half_life: float) -> np.ndarray:
    """按观测距今交易日数生成半衰期归一化权重."""
    if window < 2 or half_life <= 0:
        raise ValueError(f"[{_TAG}] DAR 窗口须 ≥ 2 且半衰期须为正")
    lags = np.arange(window - 1, -1, -1, dtype=float)
    weights = np.power(0.5, lags / half_life)
    return weights / weights.sum()


def _weighted_covariance(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """加权协方差（对称化）."""
    mean = np.sum(values * weights[:, None], axis=0)
    centered = values - mean
    covariance = (centered * weights[:, None]).T @ centered
    return (covariance + covariance.T) / 2.0


def _ar_value_at(
    x: np.ndarray, end: int, weights: np.ndarray, n_components: int
) -> Optional[float]:
    """单个窗口末端的 AR：指数加权协方差前 n_components 个特征值占比.

    ``end`` 是窗口最后一个观测的下标，窗口为 ``x[end-len(weights)+1 : end+1]``。
    总方差为 0 时返回 None（该末端不计入序列）。
    """
    window = len(weights)
    covariance = _weighted_covariance(x[end - window + 1 : end + 1], weights)
    eigenvalues = np.clip(np.linalg.eigvalsh(covariance)[::-1], 0.0, None)
    total = float(eigenvalues.sum())
    if total <= 0:
        return None
    return float((eigenvalues / total)[:n_components].sum())


def _ar_series(
    returns: pd.DataFrame, window: int, half_life: float, n_components: int
) -> pd.Series:
    """滚动 AR：指数加权协方差前 n_components 个特征值占全部方差的比例."""
    if returns.shape[1] < n_components:
        raise ValueError(
            f"[{_TAG}] DAR 的主成分个数 {n_components} 不得超过行业数量 {returns.shape[1]}"
        )
    if len(returns) < window:
        raise ValueError(
            f"[{_TAG}] DAR 需要至少 {window} 个行业收益观测，当前 {len(returns)} 个"
        )
    weights = _exponential_weights(window, half_life)
    x = returns.to_numpy(dtype=float)
    dates: List[pd.Timestamp] = []
    values: List[float] = []
    for end in range(window - 1, len(returns)):
        value = _ar_value_at(x, end, weights, n_components)
        if value is None:
            continue
        dates.append(returns.index[end])
        values.append(value)
    if not values:
        raise ValueError(f"[{_TAG}] DAR 的 AR 序列为空（行业收益窗口内方差为 0）")
    return pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float)


def _three_state(values: pd.Series, threshold: float) -> pd.Series:
    """> +阈值 → 1，< −阈值 → −1，其余 0；缺失保持缺失."""
    out = pd.Series(
        np.select([values > threshold, values < -threshold], [1, -1], default=0),
        index=values.index,
        dtype="Int64",
    )
    out.loc[values.isna()] = pd.NA
    return out


def _fuse_signals(long_signal: pd.Series, short_signal: pd.Series, ar5_change: pd.Series) -> pd.Series:
    """长短信号对称融合：一致取该值；相反取 0；单边非零由 AR 5 日变化同向确认."""
    fused = pd.Series(pd.NA, index=long_signal.index, dtype="Int64")
    for dt in fused.index:
        a = long_signal.at[dt]
        b = short_signal.at[dt]
        if pd.isna(a) or pd.isna(b):
            continue
        a, b = int(a), int(b)
        if a == b:
            fused.at[dt] = a
            continue
        if a != 0 and b != 0:
            fused.at[dt] = 0
            continue
        active = a if a != 0 else b
        change = ar5_change.at[dt]
        if pd.isna(change):
            fused.at[dt] = 0
        elif active == 1 and change > 0:
            fused.at[dt] = 1
        elif active == -1 and change < 0:
            fused.at[dt] = -1
        else:
            fused.at[dt] = 0
    return fused


def _locked_position(
    signal: pd.Series, mean_window: int, trigger: float, hold_days: int
) -> pd.Series:
    """信号均值 + 锁定期状态机：>=trigger 减到 0，<=-trigger 保持 1，其余 0.5."""
    signal_mean = signal.rolling(mean_window, min_periods=mean_window).mean()
    target = pd.Series(0.5, index=signal.index, dtype=float)
    target.loc[signal_mean.ge(trigger)] = 0.0
    target.loc[signal_mean.le(-trigger)] = 1.0
    decision = pd.Series(np.nan, index=signal.index, dtype=float)
    current = 0.5
    remaining = 0
    for date in signal.index:
        if pd.isna(signal_mean.at[date]):
            continue
        if remaining > 0:
            decision.at[date] = current
            remaining -= 1
            continue
        desired = float(target.at[date])
        if desired in (0.0, 1.0):
            current = desired
            remaining = hold_days - 1
        else:
            current = 0.5
        decision.at[date] = current
    return decision


# ---------------------------------------------------------------------------
# 纯函数：三形态识别与打分（逐行对齐研究原型 时点动量策略）
# ---------------------------------------------------------------------------


def _atr_ratio(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    """真实波幅除以前收盘后取滚动均值，结果为可与日收益比较的比例."""
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return (tr / prev).rolling(window, min_periods=window).mean()


def _threshold_scale(atr_value: float, rule: str) -> float:
    """按 ATR 规则调整下跌/反弹阈值；所有规则均只使用滞后 ATR."""
    if rule == "fixed":
        return 1.0
    if not np.isfinite(atr_value):
        return float("nan")
    if atr_value < 0.01:
        ratio = atr_value / 0.01
    elif atr_value > 0.02:
        ratio = atr_value / 0.02
    else:
        ratio = 1.0
    if rule == "piecewise_sqrt_1_2_both":
        scale = float(np.sqrt(ratio))
    elif rule == "piecewise_linear_1_2_both":
        scale = float(ratio)
    else:
        raise ValueError(f"[{_TAG}] 未知 ATR 阈值调整规则：{rule}")
    return float(np.clip(scale, 0.5, 2.0))


def _find_max_drawdown(
    values: np.ndarray, start: int, end: int, min_gap: int
) -> Optional[Tuple[int, int, float]]:
    """在区间内寻找先高后低的最大跌幅."""
    peak = start
    best: Optional[Tuple[int, int, float]] = None
    for i in range(start + 1, end + 1):
        if not np.isfinite(values[i]):
            continue
        if values[i] > values[peak]:
            peak = i
        if i - peak >= min_gap and values[peak] > 0:
            decline = 1 - values[i] / values[peak]
            if best is None or decline > best[2]:
                best = (peak, i, float(decline))
    return best


def _detect_rebound(
    close: np.ndarray,
    high: pd.Series,
    low: pd.Series,
    close_series: pd.Series,
    cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """下跌反弹：无明显反弹的下跌段后出现单日显著反弹（第 0 个返回值）."""
    daily = close_series.pct_change()
    atr = _atr_ratio(high, low, close_series, int(cfg["atr_window"]))
    atr_lag = int(cfg["atr_lag"])
    m_cap = int(cfg["m_cap"])
    gap = int(cfg["min_peak_trough_gap"])
    cooldown = int(cfg["signal_cooldown"])
    atr_np = atr.to_numpy(dtype=float)
    daily_np = daily.to_numpy(dtype=float)
    first_t = max(2, gap + 1) if cfg["atr_rule"] == "fixed" else int(cfg["atr_window"]) + atr_lag
    records: List[Dict[str, Any]] = []
    for t in range(first_t, len(close)):
        scale = _threshold_scale(float(atr_np[t - atr_lag]), str(cfg["atr_rule"]))
        if not np.isfinite(scale) or not np.isfinite(daily_np[t]):
            continue
        d_threshold = float(cfg["decline_base"]) * scale
        u_threshold = float(cfg["rebound_base"]) * scale
        if daily_np[t] <= u_threshold:
            continue
        lower = max(0, t - m_cap)
        start = t - 1
        future_max = close[t - 1]
        for i in range(t - 2, lower - 1, -1):
            if not np.isfinite(close[i]) or close[i] <= 0:
                break
            if future_max / close[i] - 1 > u_threshold:
                break
            start = i
            future_max = max(future_max, close[i])
        end = t - 1
        if end - start < gap:
            continue
        shape = _find_max_drawdown(close, start, end, gap)
        if shape is None:
            continue
        high_pos, low_pos, decline = shape
        if decline <= d_threshold:
            continue
        records.append({"signal_pos": t, "low_pos": low_pos})
    keep: List[Dict[str, Any]] = []
    last_low, last_signal = None, -10000
    for row in records:
        same = row["low_pos"] == last_low and row["signal_pos"] - last_signal <= cooldown
        if not same:
            keep.append(row)
            last_low, last_signal = row["low_pos"], row["signal_pos"]
    return keep


def _detect_top_switch(
    close_series: pd.Series,
    high: pd.Series,
    low: pd.Series,
    industry_close: pd.DataFrame,
    cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """顶部切换：高位广度骤降，同时市场出现显著单日下跌."""
    high_window = int(cfg["high_window"])
    prices = industry_close
    rolling_high = prices.rolling(high_window, min_periods=high_window).max()
    complete = prices.rolling(high_window, min_periods=high_window).count().ge(high_window)
    high_count = (
        prices.ge(rolling_high * float(cfg["high_band"])) & complete
    ).sum(axis=1)
    market_return = close_series.pct_change()
    atr = _atr_ratio(high, low, close_series, int(cfg["atr_window"])).shift(int(cfg["atr_lag"]))
    raw = (
        (high_count.shift(1) >= float(cfg["min_previous_high_count"]))
        & (high_count.shift(1) - high_count >= float(cfg["high_count_drop"]))
        & (market_return < -float(cfg["atr_multiple"]) * atr)
    )
    positions: List[int] = []
    cooldown = int(cfg["top_cooldown"])
    for position in np.flatnonzero(raw.fillna(False).to_numpy()):
        if not positions or int(position) - positions[-1] > cooldown:
            positions.append(int(position))
    return [{"signal_pos": p} for p in positions]


def _detect_breakout(
    close_series: pd.Series, high: pd.Series, low: pd.Series, cfg: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """横盘突破：前 N 日窄幅、通道继续收缩、T 日向上突破."""
    market_return = close_series.pct_change(fill_method=None)
    channel_days = int(cfg["channel_days"])
    flat_days = int(cfg["flat_days"])
    channel_width = (
        high.rolling(channel_days, min_periods=channel_days).max()
        - low.rolling(channel_days, min_periods=channel_days).min()
    ) / close_series
    prior_max_abs_return = (
        market_return.abs().shift(1).rolling(flat_days, min_periods=flat_days).max()
    )
    raw = (
        (prior_max_abs_return <= float(cfg["contraction_limit"]))
        & (channel_width.shift(1) < channel_width.shift(2))
        & (market_return > float(cfg["breakout_limit"]))
    )
    positions: List[int] = []
    cooldown = int(cfg["breakout_cooldown"])
    for position in np.flatnonzero(raw.fillna(False).to_numpy()):
        if not positions or int(position) - positions[-1] > cooldown:
            positions.append(int(position))
    return [{"signal_pos": p} for p in positions]


def _event_scores(
    form: str,
    events: Sequence[Dict[str, Any]],
    ind_ret: np.ndarray,
    ind_px: np.ndarray,
    codes: Sequence[str],
    min_history: int,
    lookback: int,
) -> Dict[pd.Timestamp, pd.Series]:
    """按形态给候选行业打分（逐条对齐原型的三种打分口径）."""
    out: Dict[pd.Timestamp, pd.Series] = {}
    for event in events:
        pos = int(event["signal_pos"])
        values: Dict[str, float] = {}
        for j, code in enumerate(codes):
            ri = ind_ret[:, j]
            if np.count_nonzero(np.isfinite(ind_px[: pos + 1, j])) < min_history:
                continue
            if not np.isfinite(ri[pos]):
                continue
            if form == "rebound":
                low_pos = int(event["low_pos"])
                pre_start = low_pos - lookback + 1
                if pre_start < 1 or pos < 1:
                    continue
                pre = ri[pre_start : low_pos + 1]
                if np.count_nonzero(np.isfinite(pre)) != lookback:
                    continue
                score = ri[pos] - float(pre.mean())
            elif form == "top":
                prior = ri[pos - 60 : pos]
                if len(prior) != 60 or not np.all(np.isfinite(prior)):
                    continue
                sd = float(np.std(prior, ddof=1))
                if not sd > 0:
                    continue
                score = ri[pos] / sd
            else:
                prior = ri[pos - 20 : pos]
                if len(prior) != 20 or not np.all(np.isfinite(prior)):
                    continue
                score = ri[pos] - float(prior.mean())
            if np.isfinite(score):
                values[code] = float(score)
        if len(values) >= 5:
            out[pd.Timestamp(event["signal_date"])] = pd.Series(values, dtype=float)
    return out


def _combine_forms(
    form_scores: Dict[str, Dict[pd.Timestamp, pd.Series]],
    axis: pd.DatetimeIndex,
    dates: Sequence[pd.Timestamp],
    codes: Sequence[str],
    combo_age: int,
    half_life: float,
) -> Dict[pd.Timestamp, pd.Series]:
    """多形态按距今交易日数指数加权合成综合分（只算指定日期）."""
    out: Dict[pd.Timestamp, pd.Series] = {}
    for d in dates:
        pos = axis.get_loc(d)
        numerator = pd.Series(0.0, index=list(codes))
        denom = pd.Series(0.0, index=list(codes))
        for scores in form_scores.values():
            for date, s in scores.items():
                age = pos - axis.get_loc(date)
                if 0 <= age <= combo_age:
                    rank = s.rank(method="average", pct=True)
                    weight = 2 ** (-age / half_life)
                    numerator.loc[s.index] += rank * weight
                    denom.loc[s.index] += weight
        combined = (numerator / denom.replace(0, np.nan)).dropna()
        if not combined.empty:
            out[d] = combined
    return out


def _event_weights(
    scores: pd.Series, columns: Sequence[str], top: int
) -> Dict[str, float]:
    """综合分前 top 只等权；可选不足 top 只时全进现金（空仓，等价于无事件）."""
    score = (
        scores.replace([np.inf, -np.inf], np.nan)
        .dropna()
        .sort_index()
        .sort_values(ascending=False, kind="stable")
    )
    out: Dict[str, float] = {c: 0.0 for c in columns}
    if len(score) >= top:
        for code in score.index[:top]:
            out[str(code)] = 1.0 / top
    return out


class IndustryTimingTargetVolStrategy(BaseStrategyModel):
    """目标波动打底 + 三形态时点行业 + DAR 成长控仓（打包独立形态）."""

    # ------------------------------------------------------------------
    # 参数 Schema
    # ------------------------------------------------------------------

    @classmethod
    def get_param_schema(cls):
        from app.allocation.models.param_schema import ParamSchema, StrategyParamSchema

        return StrategyParamSchema(
            strategy_type=_TAG,
            display_name="行业择时目标波动",
            description=(
                "每日信号、次一交易日成交：月末按 base_alloc_mode 给出大类配置——默认用 756 日"
                "普通协方差解「股票/黄金/债券/现金」四桶的目标波动配置，也可改为按资产多窗口"
                "波动率倒数分配后整体缩放到目标波动；日频向现金收缩到波动上限得中性组合；"
                "市场出现下跌反弹、"
                "顶部切换、横盘突破三形态事件时，事件后 20 个交易日内权益的一半换成综合分"
                "前 5 只行业，空窗期回到权益风险平价；DAR 用行业收益的主成分占比决定成长端"
                "仓位（减到 0 / 保持满仓 / 中性 50%，20 日锁定）；最后沿中性→候选线段投影，"
                "同时满足主动风险与总波动上限。选样/赋权/约束/成本全部在策略包内"
            ),
            composition={
                "selector": None,
                "allocator": _TAG,
                "controller": None,
                "schedule": {"rebalance_freq": "daily", "execution_delay": 1},
            },
            # 权重合计恒为 1（现金代理承接剩余），Pipeline 不再做杠杆缩放
            internal_leverage=True,
            params=[
                # ━━━ 资产分组（core）━━━
                ParamSchema(
                    name="equity_codes", label="权益资产", type="text", default="",
                    description=(
                        "权益四只，逗号分隔，**顺序即风险平价的分母口径**："
                        "小盘、成长、红利、价值（成长端是 DAR 唯一控仓对象）"
                    ),
                ),
                ParamSchema(
                    name="commodity_codes", label="商品资产", type="text", default="",
                    description="黄金（单独构成一个风险桶，组内只有一只）",
                ),
                ParamSchema(
                    name="bond_codes", label="债券资产", type="text", default="",
                    description="国债 1-3 年、国债 7-10 年、信用 1-3 年、信用 3-5 年，组内风险平价",
                ),
                ParamSchema(
                    name="cash_codes", label="现金代理", type="text", default="",
                    description="货币基金指数，承接约束收缩与 DAR 释放的资金（只允许一只）",
                ),
                ParamSchema(
                    name="industry_codes", label="行业资产", type="text", default="",
                    description=(
                        "申万一级行业全部代码，逗号分隔。既是时点选股的候选池，"
                        "也是 DAR 计算主成分占比与顶部切换统计广度所用的面板"
                    ),
                ),
                ParamSchema(
                    name="market_codes", label="市场基准", type="text", default="",
                    description=(
                        "三形态识别的市场基准（中证全指），只用于信号识别、不参与持仓，"
                        "必须已在行情库导入 high/low（ATR 与通道宽度依赖日内高低点）"
                    ),
                ),
                ParamSchema(
                    name="industry_candidates", label="选股候选行业", type="text", default="",
                    description=(
                        "参与三形态打分的行业，必须取自「行业资产」；原型排除综合行业，"
                        "留空则用「行业资产」全量"
                    ),
                ),
                # ━━━ 目标波动配置（core）━━━
                ParamSchema(
                    name="base_alloc_mode", label="月末配置方式", type="select",
                    default="risk_budget",
                    options=[
                        ("risk_budget", "四桶目标波动（风险预算）"),
                        ("inverse_vol", "波动率倒数（nous 口径）"),
                    ],
                    description=(
                        "月末大类配置的求解方式。四桶目标波动：权益与债券组内等风险贡献，"
                        "再在四桶上解目标波动等式（原型口径，波动恰等于目标）；波动率倒数："
                        "不分组、不做风险平价，按各资产多窗口年化波动倒数的 (1/N)×(1/σ) "
                        "分配后整体缩放到目标波动，剩余进现金代理（nous_low_vol 口径）。"
                        "1/σ 组合本身波动很低（默认池约 33bp），目标波动高于它时需要超过 "
                        "100% 的权重，此时按 nous 同款压回满仓，实际波动低于目标，"
                        "审计字段 inv_vol_capped=true"
                    ),
                ),
                ParamSchema(
                    name="inv_vol_windows", label="倒数波动窗口", type="text",
                    default="22,65,130", group="advanced",
                    condition={"field": "base_alloc_mode", "value": "inverse_vol"},
                    description=(
                        "波动率倒数模式使用的波动率窗口（交易日，逗号分隔升序）；"
                        "各窗口年化波动取最大值作为 σ，默认值与 nous_low_vol 一致"
                    ),
                ),
                ParamSchema(
                    name="vol_target", label="目标年化波动", type="number", default=0.0125,
                    min_value=0.0001, max_value=0.5, step=0.0005,
                    description="月末大类配置的目标波动率（无杠杆等式约束），也是主动风险上限的基准",
                ),
                ParamSchema(
                    name="vol_max", label="年化波动上限", type="number", default=0.015,
                    min_value=0.0001, max_value=0.5, step=0.0005,
                    description="中性组合与最终权重的总波动上限（63/252/756 三个窗口都要满足）",
                ),
                ParamSchema(
                    name="vol_min", label="年化波动下限", type="number", default=0.01,
                    min_value=0.0, max_value=0.5, step=0.0005, group="advanced",
                    description="仅用于目标波动可行性判定与监控对照，不参与权重计算",
                ),
                ParamSchema(
                    name="cov_window", label="月末协方差窗口", type="number", default=756,
                    min_value=60, max_value=2500, step=1, group="advanced",
                    description="月末大类配置使用的普通样本协方差窗口（交易日，ddof=1）",
                ),
                ParamSchema(
                    name="cov_windows", label="日频协方差窗口", type="text",
                    default="63,252,756", group="advanced",
                    description=(
                        "日频风险复核与约束投影使用的协方差窗口（交易日，逗号分隔、升序）；"
                        "最长窗口同时用于主动风险计量"
                    ),
                ),
                ParamSchema(
                    name="te_ratio", label="主动风险占比", type="number", default=0.2,
                    min_value=0.0, max_value=1.0, step=0.05, group="advanced",
                    description="主动风险上限 = te_ratio × 目标波动，沿中性→候选线段收缩",
                ),
                # ━━━ 三形态时点（core）━━━
                ParamSchema(
                    name="timing_hold", label="事件持有交易日", type="number", default=20,
                    min_value=1, max_value=250, step=1,
                    description="事件后持有选中行业的交易日数（到期回到权益风险平价）",
                ),
                ParamSchema(
                    name="timing_top", label="事件选股数量", type="number", default=5,
                    min_value=1, max_value=30, step=1,
                    description="事件后持有综合分前 top 只行业，等权",
                ),
                ParamSchema(
                    name="combo_age", label="形态合成回看", type="number", default=10,
                    min_value=1, max_value=60, step=1, group="advanced",
                    description="合成综合分时纳入近多少交易日的形态信号",
                ),
                ParamSchema(
                    name="combo_half_life", label="形态合成半衰期", type="number", default=10,
                    min_value=1.0, max_value=60.0, step=1.0, group="advanced",
                    description="形态合成的时间权重 2^(-age/半衰期)",
                ),
                ParamSchema(
                    name="min_industry_history", label="行业最少历史", type="number", default=120,
                    min_value=20, max_value=2000, step=1, group="advanced",
                    description="事件日要求行业至少有该交易日数的有效价格，不足则不参与打分",
                ),
                # ━━━ DAR 成长控仓（core）━━━
                ParamSchema(
                    name="dar_trigger", label="DAR 触发阈值", type="number", default=0.5,
                    min_value=0.0, max_value=1.0, step=0.05,
                    description="融合信号 5 日均值 ≥ 该值 → 成长减到 0；≤ 负值 → 保持满仓；其余 50%",
                ),
                ParamSchema(
                    name="dar_hold_days", label="DAR 锁定交易日", type="number", default=20,
                    min_value=1, max_value=250, step=1,
                    description="触发后的锁定期，期间维持仓位并逐日递减",
                ),
                ParamSchema(
                    name="dar_signal_threshold", label="DAR 三态阈值", type="number", default=1.0,
                    min_value=0.0, max_value=10.0, step=0.1, group="advanced",
                    description="DAR 标准化偏离超过该倍数才给出 ±1 信号",
                ),
                ParamSchema(
                    name="dar_ar_window", label="AR 窗口", type="number", default=250,
                    min_value=20, max_value=1000, step=1, group="advanced",
                    description="主成分占比（AR）的指数加权协方差窗口",
                ),
                ParamSchema(
                    name="dar_half_life", label="AR 半衰期", type="number", default=125.0,
                    min_value=1.0, max_value=1000.0, step=1.0, group="advanced",
                    description="AR 指数加权协方差的半衰期（交易日）",
                ),
                ParamSchema(
                    name="dar_components", label="AR 主成分数", type="number", default=3,
                    min_value=1, max_value=10, step=1, group="advanced",
                    description="AR = 前 N 个特征值占比之和",
                ),
                ParamSchema(
                    name="dar_state_window", label="AR 短期均线", type="number", default=5,
                    min_value=2, max_value=60, step=1, group="advanced",
                    description="AR 的短均线窗口（也是信号平滑窗口）",
                ),
                ParamSchema(
                    name="dar_long_window", label="AR 长期均线", type="number", default=250,
                    min_value=20, max_value=1000, step=1, group="advanced",
                    description="AR 长均线与长波动窗口（DAR 长期偏离的分母）",
                ),
                ParamSchema(
                    name="dar_short_window", label="AR 中期均线", type="number", default=125,
                    min_value=10, max_value=1000, step=1, group="advanced",
                    description="AR 中期均线与中期波动窗口（DAR 短期偏离的分母）",
                ),
                ParamSchema(
                    name="dar_std_ddof", label="DAR 波动自由度", type="number", default=0,
                    min_value=0, max_value=1, step=1, group="advanced",
                    description="DAR 标准差自由度（0=总体，1=样本）",
                ),
                ParamSchema(
                    name="dar_signal_mean_window", label="信号平滑窗口", type="number", default=5,
                    min_value=1, max_value=30, step=1, group="advanced",
                    description="融合信号的均值窗口，决定触发判定的平滑度",
                ),
                # ━━━ 形态参数（advanced）━━━
                ParamSchema(
                    name="atr_window", label="ATR 窗口", type="number", default=90,
                    min_value=5, max_value=500, step=1, group="advanced",
                    description="真实波幅比例的滚动均值窗口（下跌反弹与顶部切换共用）",
                ),
                ParamSchema(
                    name="atr_lag", label="ATR 滞后", type="number", default=1,
                    min_value=0, max_value=10, step=1, group="advanced",
                    description="阈值使用的 ATR 滞后交易日数（只用已实现信息）",
                ),
                ParamSchema(
                    name="atr_rule", label="ATR 调整规则", type="select", default="piecewise_linear_1_2_both",
                    options=[
                        ("piecewise_linear_1_2_both", "分段线性（1%/2% 双侧）"),
                        ("piecewise_sqrt_1_2_both", "分段开方（1%/2% 双侧）"),
                        ("fixed", "不调整"),
                    ],
                    group="advanced",
                    description="按 ATR 大小调整下跌/反弹阈值的规则",
                ),
                ParamSchema(
                    name="m_cap", label="下跌段最长回看", type="number", default=40,
                    min_value=5, max_value=250, step=1, group="advanced",
                    description="下跌反弹形态里向前扩展下跌段的交易日上限",
                ),
                ParamSchema(
                    name="decline_base", label="下跌阈值", type="number", default=0.08,
                    min_value=0.0, max_value=1.0, step=0.005, group="advanced",
                    description="构成信号的最小跌幅（再乘以 ATR 调整系数）",
                ),
                ParamSchema(
                    name="rebound_base", label="反弹阈值", type="number", default=0.005,
                    min_value=0.0, max_value=1.0, step=0.001, group="advanced",
                    description="触发日的单日最小涨幅（再乘以 ATR 调整系数）",
                ),
                ParamSchema(
                    name="min_peak_trough_gap", label="峰谷最短间隔", type="number", default=3,
                    min_value=1, max_value=60, step=1, group="advanced",
                    description="下跌段内高点与低点的最短交易日间隔",
                ),
                ParamSchema(
                    name="signal_cooldown", label="反弹信号冷却", type="number", default=5,
                    min_value=1, max_value=60, step=1, group="advanced",
                    description="同一低点在该交易日数内只保留一次反弹信号",
                ),
                ParamSchema(
                    name="high_window", label="高位广度窗口", type="number", default=252,
                    min_value=20, max_value=1000, step=1, group="advanced",
                    description="顶部切换统计「接近一年新高」的行业数所用窗口",
                ),
                ParamSchema(
                    name="high_band", label="新高判定带", type="number", default=0.995,
                    min_value=0.5, max_value=1.0, step=0.005, group="advanced",
                    description="收盘价 ≥ 滚动最高价 × 该比例即计为高位行业",
                ),
                ParamSchema(
                    name="min_previous_high_count", label="前日高位行业数下限", type="number",
                    default=3, min_value=1, max_value=31, step=1, group="advanced",
                    description="顶部切换要求前一交易日至少有多少个行业处于高位",
                ),
                ParamSchema(
                    name="high_count_drop", label="高位行业数降幅", type="number", default=3,
                    min_value=1, max_value=31, step=1, group="advanced",
                    description="高位行业数在单日内至少要减少多少个",
                ),
                ParamSchema(
                    name="atr_multiple", label="市场跌幅倍数", type="number", default=1.5,
                    min_value=0.1, max_value=10.0, step=0.1, group="advanced",
                    description="顶部切换要求市场单日跌幅超过 ATR 比例的该倍数",
                ),
                ParamSchema(
                    name="top_cooldown", label="顶部信号冷却", type="number", default=20,
                    min_value=1, max_value=250, step=1, group="advanced",
                    description="两次顶部切换信号之间的最小交易日间隔",
                ),
                ParamSchema(
                    name="flat_days", label="横盘观察窗口", type="number", default=5,
                    min_value=1, max_value=60, step=1, group="advanced",
                    description="横盘突破要求前 N 日单日涨跌绝对值都不超过收缩阈值",
                ),
                ParamSchema(
                    name="contraction_limit", label="横盘涨跌上限", type="number", default=0.01,
                    min_value=0.0, max_value=0.2, step=0.001, group="advanced",
                    description="横盘判定中单日涨跌绝对值上限",
                ),
                ParamSchema(
                    name="breakout_limit", label="突破涨幅下限", type="number", default=0.01,
                    min_value=0.0, max_value=0.2, step=0.001, group="advanced",
                    description="触发日的市场最小涨幅",
                ),
                ParamSchema(
                    name="channel_days", label="通道宽度窗口", type="number", default=5,
                    min_value=2, max_value=60, step=1, group="advanced",
                    description="(最高-最低)/收盘 的通道宽度计算窗口",
                ),
                ParamSchema(
                    name="breakout_cooldown", label="突破信号冷却", type="number", default=5,
                    min_value=1, max_value=60, step=1, group="advanced",
                    description="两次横盘突破信号之间的最小交易日间隔",
                ),
                # ━━━ 成本与校验 ━━━
                ParamSchema(
                    name="transaction_cost", label="单边交易费率", type="number", default=0.0005,
                    min_value=0.0, max_value=0.05, step=0.0001,
                    description="按成交额计提的单边费率（原型 5bp），回测与监控共用同一份参数",
                ),
                ParamSchema(
                    name="ann_days", label="年化交易日数", type="number", default=252,
                    min_value=100, max_value=400, step=1, group="advanced",
                    description="协方差年化与 DAR 口径使用的年化基数（原型 252，与系统指标口径无关）",
                ),
                ParamSchema(
                    name="min_history_days", label="最小历史交易日", type="number", default=760,
                    min_value=300, max_value=2500, step=1, group="advanced",
                    description=(
                        "价格矩阵至少需要的交易日数：需覆盖月末协方差窗口 + DAR 的 AR/均线窗口，"
                        "不足即报错（不缩短窗口）"
                    ),
                ),
                ParamSchema(
                    name="strict_validate", label="严格校验", type="boolean", default=True,
                    group="advanced",
                    description=(
                        "开启时：资产池内有资产未归组、分组含池外代码、权重越界即报错；"
                        "关闭只降级为告警（不建议）"
                    ),
                ),
                *_model_level_params(1),
            ],
        )

    # ------------------------------------------------------------------
    # 调度、面板与数据契约
    # ------------------------------------------------------------------

    @classmethod
    def get_extra_panels(cls) -> list:
        """声明需要 asset_metrics 面板（三形态的 ATR 与通道宽度依赖日内高低点）."""
        return [_PANEL_NAME]

    def get_data_feed_options(self) -> Dict[str, Any]:
        """加载 asset_metrics 面板，**不**用面板期日驱动调仓.

        ``panel_event_dates`` 保持缺省（False）：面板是日频的，一旦把它当调仓事件日，
        调仓日会被面板期日（每个交易日）覆盖，与调度声明脱钩。
        """
        return {"extra_panels": [_PANEL_NAME]}

    def get_execution_schedule(self) -> Optional[dict]:
        """每日信号、次一交易日成交；不写 selection_start_date / skip_dates 等日期常量.

        原型的 ``risk_anchor`` 与 ``constrain`` 逐日重算，目标权重在 44.1% 的交易日
        发生变化（实测 2190 日里 965 日），周频或月末调仓都无法复现逐日净值。

        ``natural_frequency=True`` 是监控通道的必需声明：监控侧
        ``_build_event_driven_rebalance_map`` 默认关闭自然频率路径（存量
        ``trend_cross_sectional`` / ``snowball_delta_hedge`` 声明 daily 但监控
        一直按月末推演，默认开启会让它们漂移），只有策略显式声明才走逐日映射。
        缺这一项时监控会回退月末路径，实测 35 个交易日的监控区间只出 2 个调仓日，
        与回测的逐日调仓不同源。
        """
        return {
            "rebalance_freq": "daily",
            "execution_delay": 1,
            "natural_frequency": True,
        }

    def get_trading_costs(self, params: Dict[str, Any]) -> Dict[str, float]:
        """把 ``transaction_cost`` 声明为全池统一费率，现金代理腿为 0.

        原型按 ``Σ|目标−调仓前实际权重| × 费率`` 计提，但求和**排除了现金腿**
        （``simulate`` 里 ``w[:-1] / old[:-1]``）——现金是残余账户，申赎不计费。
        系统引擎的费率表按逐资产 code 取值，把现金代理报成 0 才能复现同一基数：
        否则多计 ``|Δ现金| × 费率``，日频调仓下 ``Δ现金`` 与其它腿同量级，
        会形成每年数十 bp 的额外成本拖累（实测半年累计 0.095% 净值偏差）。
        货币基金申购/赎回本身也不收费，与原型口径一致。
        """
        cfg = self._parse_config(params)
        from app.backtesting.data_contract import parse_asset_codes

        if cfg["transaction_cost"] <= 0:
            return {}
        rate = float(cfg["transaction_cost"])
        no_cost = set(parse_asset_codes(params.get("cash_codes")))
        codes: List[str] = []
        for param_name in GROUP_PARAM_TO_KEY:
            for code in parse_asset_codes(params.get(param_name)):
                if code not in codes:
                    codes.append(code)
        return {code: (0.0 if code in no_cost else rate) for code in codes}

    def has_native_vol_control(self) -> bool:
        """波动率控制写在包内（目标波动配置 + 风险复核 + 约束投影），放行 Pipeline 代理."""
        return True

    @classmethod
    def get_data_contract(cls):
        """声明数据契约：分组覆盖全池 + 资产大类匹配 + 参数自洽 + 价格跳变上限.

        ``max_single_day_jump`` 取 0.20：池内 42 只资产 2010-2026 实测最大单日跳变
        13.53%（801980.SL 于 2024-09-30），留 1.48 倍余量。
        ``min_history_days`` 取 760：超过 756 日协方差窗口，且短于 DAR 的 AR 暖机需求
        时策略会显式报错，不缩短窗口。
        """
        from app.backtesting.data_contract import DataContract, GroupSpec

        return DataContract(
            max_single_day_jump=0.20,
            min_history_days=760,
            group_params={
                "equity_codes": GroupSpec(required=True, cover_pool=True),
                "commodity_codes": GroupSpec(required=True, cover_pool=True),
                "bond_codes": GroupSpec(required=True, cover_pool=True),
                "cash_codes": GroupSpec(required=True, cover_pool=True),
                "industry_codes": GroupSpec(required=True, cover_pool=True),
                "market_codes": GroupSpec(required=True, cover_pool=True),
            },
            expected_asset_class={
                "equity_codes": "权益",
                "commodity_codes": "商品",
                "bond_codes": "固收",
                "cash_codes": "货币",
                "industry_codes": "权益",
                "market_codes": "权益",
            },
            custom_checks=("param_consistency",),
        )

    def _check_param_consistency(self, prices: pd.DataFrame, params: Dict[str, Any]) -> Optional[str]:
        """参数自洽检查（契约门禁）：不自洽时返回失败原因，由门禁统一拒绝运行."""
        try:
            cfg = self._parse_config(params)
        except ValueError as exc:
            return str(exc)
        from app.backtesting.data_contract import parse_asset_codes

        if cfg["vol_target"] > cfg["vol_max"] + TOL:
            return (
                f"目标波动 {cfg['vol_target']:.4%} 高于波动上限 {cfg['vol_max']:.4%}，"
                "月末配置与风险复核会互相冲突（请降低目标波动或提高上限）"
            )
        if cfg["vol_min"] > cfg["vol_max"] + TOL:
            return f"波动下限 {cfg['vol_min']:.4%} 高于波动上限 {cfg['vol_max']:.4%}"
        # 倒数波动窗口只在 inverse_vol 模式下参与计算；risk_budget 下即便留了
        # 历史遗留的窗口值也不应拦截运行
        if (
            cfg["base_alloc_mode"] == "inverse_vol"
            and max(cfg["inv_vol_windows"]) > cfg["min_history_days"]
        ):
            return (
                f"倒数波动窗口最大 {max(cfg['inv_vol_windows'])} 个交易日超过最少历史 "
                f"{cfg['min_history_days']}，波动率估不出来（请缩短 inv_vol_windows 或提高 min_history_days）"
            )
        equity = parse_asset_codes(params.get("equity_codes"))
        if len(equity) != 4:
            return (
                f"权益资产必须恰好 4 只（小盘/成长/红利/价值，决定内部风险平价与 DAR 控仓对象），"
                f"当前 {len(equity)} 只：{equity}"
            )
        if len(parse_asset_codes(params.get("cash_codes"))) != 1:
            return "现金代理必须恰好 1 只"
        if len(parse_asset_codes(params.get("market_codes"))) != 1:
            return "市场基准必须恰好 1 只"
        industries = parse_asset_codes(params.get("industry_codes"))
        candidates = parse_asset_codes(params.get("industry_candidates"))
        if candidates:
            extra = [c for c in candidates if c not in set(industries)]
            if extra:
                return f"选股候选行业必须取自「行业资产」，以下代码不在其中：{extra}"
            if len(candidates) < cfg["timing_top"]:
                return (
                    f"选股候选行业 {len(candidates)} 只少于事件选股数量 {cfg['timing_top']}，"
                    "事件将永远只能空仓"
                )
        if len(industries) < 5:
            return f"行业资产只有 {len(industries)} 只，三形态打分要求至少 5 只"
        if cfg["combo_age"] > cfg["timing_hold"] + 60:
            return "形态合成回看窗口不得显著超过事件持有期（会导致事件结束后仍被反复计入）"
        return None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """信号日收盘计算目标权重（纯函数；无跨期状态，只有月末解的缓存）."""
        if prices is None or not isinstance(prices, pd.DataFrame) or prices.empty:
            raise ValueError(f"[{_TAG}] 价格矩阵为空，无法计算")
        pool = list(prices.columns)
        cfg = self._parse_config(params)
        groups = self._resolve_groups(params, pool)
        px, market_close, high, low = self._build_inputs(prices, groups, params, cfg)

        covs = self._daily_covs(px, groups, cfg)
        assets = groups["EQ"] + groups["GOLD"] + groups["BOND"] + groups["CASH"]
        orig10 = self._orig_weights(px, assets, cfg, params)
        orig = self._expand_orig(orig10, groups)
        neutral = _risk_anchor(orig, covs, cfg["vol_max"])

        dar = self._dar_position(px, groups, cfg)
        active, event_w, event_date = self._timing_state(
            px, market_close, high, low, groups, cfg
        )
        final, alpha = self._blend(neutral, groups, active, event_w, dar, covs, cfg)

        weights = pd.Series(0.0, index=pool, dtype=float)
        risk_cols = self._risk_columns(groups)
        for idx, code in enumerate(risk_cols):
            weights.at[code] = float(final[idx])
        self._audit(
            cfg=cfg,
            groups=groups,
            neutral=neutral,
            final=final,
            alpha=alpha,
            dar=dar,
            active=active,
            event_date=event_date,
            event_w=event_w,
            signal_date=px.index[-1],
        )
        self._final_check(weights, cfg)
        return weights

    # ------------------------------------------------------------------
    # 分步实现（每步可单测）
    # ------------------------------------------------------------------

    def _parse_config(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """把 params 归一为本期计算所需配置（一次性解析，避免散落在各步）."""
        cfg: Dict[str, Any] = {
            "ann_days": _as_int(params.get("ann_days"), 252, "ann_days", minimum=100),
            "cov_window": _as_int(params.get("cov_window"), 756, "cov_window", minimum=60),
            "cov_windows": tuple(
                sorted(_parse_int_list(params.get("cov_windows"), (63, 252, 756), "cov_windows"))
            ),
            "base_alloc_mode": str(params.get("base_alloc_mode") or "risk_budget").strip(),
            "inv_vol_windows": tuple(
                sorted(
                    _parse_int_list(
                        params.get("inv_vol_windows"),
                        _DEFAULT_INV_VOL_WINDOWS,
                        "inv_vol_windows",
                    )
                )
            ),
            "vol_min": _as_float(params.get("vol_min"), 0.01, "vol_min"),
            "vol_target": _as_float(params.get("vol_target"), 0.0125, "vol_target"),
            "vol_max": _as_float(params.get("vol_max"), 0.015, "vol_max"),
            "te_ratio": _as_float(params.get("te_ratio"), 0.2, "te_ratio"),
            "timing_hold": _as_int(params.get("timing_hold"), 20, "timing_hold"),
            "timing_top": _as_int(params.get("timing_top"), 5, "timing_top"),
            "combo_age": _as_int(params.get("combo_age"), 10, "combo_age"),
            "combo_half_life": _as_float(params.get("combo_half_life"), 10.0, "combo_half_life"),
            "min_industry_history": _as_int(
                params.get("min_industry_history"), 120, "min_industry_history", minimum=20
            ),
            "dar_trigger": _as_float(params.get("dar_trigger"), 0.5, "dar_trigger"),
            "dar_hold_days": _as_int(params.get("dar_hold_days"), 20, "dar_hold_days"),
            "dar_signal_threshold": _as_float(
                params.get("dar_signal_threshold"), 1.0, "dar_signal_threshold"
            ),
            "dar_ar_window": _as_int(params.get("dar_ar_window"), 250, "dar_ar_window", minimum=20),
            "dar_half_life": _as_float(params.get("dar_half_life"), 125.0, "dar_half_life"),
            "dar_components": _as_int(params.get("dar_components"), 3, "dar_components"),
            "dar_state_window": _as_int(
                params.get("dar_state_window"), 5, "dar_state_window", minimum=2
            ),
            "dar_long_window": _as_int(
                params.get("dar_long_window"), 250, "dar_long_window", minimum=20
            ),
            "dar_short_window": _as_int(
                params.get("dar_short_window"), 125, "dar_short_window", minimum=10
            ),
            "dar_std_ddof": _as_int(params.get("dar_std_ddof"), 0, "dar_std_ddof", minimum=0),
            "dar_signal_mean_window": _as_int(
                params.get("dar_signal_mean_window"), 5, "dar_signal_mean_window"
            ),
            "transaction_cost": _as_float(
                params.get("transaction_cost"), 0.0005, "transaction_cost"
            ),
            "min_history_days": _as_int(
                params.get("min_history_days"), 760, "min_history_days", minimum=300
            ),
            "strict_validate": bool(params.get("strict_validate", True)),
        }
        from app.backtesting.data_contract import parse_asset_codes

        cfg["industry_candidates"] = parse_asset_codes(params.get("industry_candidates"))
        cfg["atr_rule"] = str(params.get("atr_rule") or "piecewise_linear_1_2_both").strip()
        for key, default in _FORM_DEFAULTS.items():
            if key in {
                "atr_window", "atr_lag", "m_cap", "min_peak_trough_gap", "signal_cooldown",
                "high_window", "min_previous_high_count", "high_count_drop", "top_cooldown",
                "flat_days", "channel_days", "breakout_cooldown",
            }:
                cfg[key] = _as_int(params.get(key), int(default), key)
            else:
                cfg[key] = _as_float(params.get(key), float(default), key)
        if cfg["vol_target"] <= 0:
            raise ValueError(f"[{_TAG}] 目标波动率必须为正")
        if cfg["vol_max"] <= 0:
            raise ValueError(f"[{_TAG}] 波动上限必须为正")
        if cfg["base_alloc_mode"] not in _BASE_MODES:
            raise ValueError(
                f"[{_TAG}] 参数 base_alloc_mode 只能是 {' / '.join(_BASE_MODES)}，"
                f"收到 {cfg['base_alloc_mode']!r}"
            )
        return cfg

    def _resolve_groups(
        self, params: Dict[str, Any], pool: Sequence[str]
    ) -> Dict[str, List[str]]:
        """解析六个分组参数；``strict_validate`` 下池内有资产未归组即报错."""
        from app.backtesting.data_contract import parse_asset_codes

        pool_set = set(pool)
        groups: Dict[str, List[str]] = {key: [] for key in GROUP_KEYS}
        unknown: Dict[str, List[str]] = {}
        for param_name, group_key in GROUP_PARAM_TO_KEY.items():
            codes = parse_asset_codes(params.get(param_name))
            inside = [c for c in codes if c in pool_set]
            outside = [c for c in codes if c not in pool_set]
            if outside:
                unknown[param_name] = outside
            groups[group_key] = inside

        strict = bool(params.get("strict_validate", True))
        if unknown:
            detail = "; ".join(f"{k}={v}" for k, v in unknown.items())
            if strict:
                raise ValueError(
                    f"[{_TAG}] 分组参数含资产池之外的代码：{detail}。"
                    "分组参数必须与模型资产池同步维护"
                )
            _log.warning("[%s] 分组参数含池外代码（已忽略）：%s", _TAG, detail)

        empty = [p for p, k in GROUP_PARAM_TO_KEY.items() if not groups[k]]
        if empty and strict:
            raise ValueError(
                f"[{_TAG}] 分组为空：{empty}。本策略需要权益、商品、债券、现金代理、"
                "行业、市场基准六组各自至少一只资产"
            )
        if strict:
            covered = {c for members in groups.values() for c in members}
            missing = [c for c in pool if c not in covered]
            if missing:
                raise ValueError(
                    f"[{_TAG}] 资产池内 {len(missing)} 只资产未归入任何分组：{missing}。"
                    "请补齐六个分组参数，或关闭 strict_validate"
                )
            seen: Dict[str, str] = {}
            duplicated: Dict[str, List[str]] = {}
            for group_key in GROUP_KEYS:
                for code in groups[group_key]:
                    if code in seen:
                        duplicated.setdefault(code, [seen[code], group_key])
                    else:
                        seen[code] = group_key
            if duplicated:
                raise ValueError(f"[{_TAG}] 同一资产被重复归组：{duplicated}")
        return groups

    def _risk_columns(self, groups: Dict[str, List[str]]) -> List[str]:
        """风险矩阵列顺序：9 个风险资产 + 31 行业 + 现金代理（市场基准不参与）."""
        assets = groups["EQ"] + groups["GOLD"] + groups["BOND"] + groups["CASH"]
        return assets[:-1] + list(groups["IND"]) + [assets[-1]]

    def _build_inputs(
        self,
        prices: pd.DataFrame,
        groups: Dict[str, List[str]],
        params: Dict[str, Any],
        cfg: Dict[str, Any],
    ) -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
        """抽取池内资产、取共同有效区间、校验价格为正，并取市场基准的日内高低点.

        不启用前向填充：原型在共同收益样本上显式断言无缺失，缺日会让收益率跨日
        计算（等于把两日收益当一日），故整行剔除并在行数缩水时告警。
        """
        assets = groups["EQ"] + groups["GOLD"] + groups["BOND"] + groups["CASH"]
        ind = list(groups["IND"])
        market = groups["MKT"][0]
        need: List[str] = []
        for code in assets + ind + [market]:
            if code not in need:
                need.append(code)
        missing = [c for c in need if c not in prices.columns]
        if missing:
            raise ValueError(
                f"[{_TAG}] 以下资产在当前价格矩阵中无行情：{missing}。"
                "请检查回测区间与行情入库情况"
            )
        raw = prices[need].apply(pd.to_numeric, errors="coerce")
        px = raw.dropna(how="any")
        dropped = int(len(raw) - len(px))
        if dropped:
            _log.warning(
                "[%s] 价格矩阵剔除 %d 行含缺失的交易日（策略要求共同有效区间）：%s ~ %s",
                _TAG, dropped, raw.index[0].date(), raw.index[dropped].date(),
            )
        if len(px) < 2:
            raise ValueError(f"[{_TAG}] 有效价格行数 {len(px)} 不足 2 行，无法计算收益")
        if (px <= 0).any().any():
            bad = [c for c in px.columns if bool((px[c] <= 0).any())]
            raise ValueError(f"[{_TAG}] 以下资产存在非正价格：{bad}，请核查行情数据")
        high, low = self._market_extremes(params, market, px.index)
        return px, px[market], high, low

    def _market_extremes(
        self, params: Dict[str, Any], code: str, index: pd.DatetimeIndex
    ) -> Tuple[pd.Series, pd.Series]:
        """从 asset_metrics 面板取市场基准的日内高低点（面板整份注入，此处按需取一列）.

        面板不按日期裁剪（策略需要长回看），故这里只物化一次并按需重索引；
        同一份面板对象在回测内不变，结果缓存在 ``self._state`` 避免逐日重建。
        """
        panels = params.get(f"_panel_{_PANEL_NAME}")
        if not panels:
            raise ValueError(
                f"[{_TAG}] 未注入 {_PANEL_NAME} 面板，无法计算三形态的 ATR 与通道宽度。"
                "请确认已在「资产行情」导入市场基准的 high/low，"
                "且策略经 get_extra_panels 声明的面板加载通道生效"
            )
        state = self._ensure_state()
        cache = state.get("_metrics_cache")
        key = (id(panels), len(panels), max(panels.keys()), code)
        if cache is None or cache[0] != key:
            highs: Dict[pd.Timestamp, Any] = {}
            lows: Dict[pd.Timestamp, Any] = {}
            for dt, frame in panels.items():
                if code not in frame.index:
                    continue
                row = frame.loc[code]
                highs[dt] = row.get("high")
                lows[dt] = row.get("low")
            high_s = pd.Series(highs, dtype=float).sort_index()
            low_s = pd.Series(lows, dtype=float).sort_index()
            if high_s.empty:
                raise ValueError(
                    f"[{_TAG}] asset_metrics 面板中找不到市场基准 {code} 的 high/low。"
                    "三形态识别依赖日内高低点，缺失时不能用地量替代"
                )
            cache = (key, high_s, low_s)
            state["_metrics_cache"] = cache
        _, high_s, low_s = cache
        high = high_s.reindex(index)
        low = low_s.reindex(index)
        if high.isna().any() or low.isna().any():
            raise ValueError(
                f"[{_TAG}] 市场基准 {code} 在回测区间内缺少 high/low（缺 "
                f"{int(high.isna().sum())} 个交易日）。请补齐「资产行情」的日内高低点"
            )
        if (high <= 0).any() or (low <= 0).any():
            raise ValueError(f"[{_TAG}] 市场基准 {code} 存在非正的最高价/最低价，请核查数据")
        return high, low

    def _daily_covs(
        self, px: pd.DataFrame, groups: Dict[str, List[str]], cfg: Dict[str, Any]
    ) -> List[np.ndarray]:
        """按窗口升序计算日频协方差（年化，ddof=1），与原型 dict 迭代顺序一致."""
        cols = self._risk_columns(groups)
        rets = px[cols].pct_change(fill_method=None).iloc[1:]
        longest = max(cfg["cov_windows"])
        if len(rets) < longest:
            raise ValueError(
                f"[{_TAG}] 日频风险计算需要至少 {longest} 个交易日收益，当前 {len(rets)} 个。"
                "请把回测起始日推后（价格矩阵需覆盖全部协方差窗口），不要缩短窗口"
            )
        return [
            rets.tail(n).cov().to_numpy() * float(cfg["ann_days"])
            for n in cfg["cov_windows"]
        ]

    def _is_month_end(self, idx: pd.DatetimeIndex, pos: int, as_of: Any) -> bool:
        """判断 idx[pos] 是否为该月的最后一个交易日.

        除最后一行外可直接用「下一行是否换月」判定；最后一行没有下一行，用执行日
        （``_as_of`` = 信号日 + 1 个交易日）辅助：执行日已进入新月份即说明信号日是
        月末。两者都拿不到时退化为「该月最后一个工作日」，遇到月末节假日会判成
        非月末（只影响当日一天）。
        """
        if pos + 1 < len(idx):
            return idx[pos].month != idx[pos + 1].month
        ts = pd.Timestamp(idx[pos])
        if as_of is not None:
            try:
                as_of_ts = pd.Timestamp(as_of).normalize()
            except (TypeError, ValueError):
                as_of_ts = None
            if as_of_ts is not None and as_of_ts > ts:
                return as_of_ts.month != ts.month
        last_bd = pd.Timestamp(
            year=ts.year, month=ts.month, day=calendar.monthrange(ts.year, ts.month)[1]
        )
        while last_bd.weekday() >= 5:
            last_bd -= pd.Timedelta(days=1)
        return bool(ts.normalize() == last_bd)

    def _orig_weights(
        self,
        px: pd.DataFrame,
        assets: Sequence[str],
        cfg: Dict[str, Any],
        params: Dict[str, Any],
    ) -> np.ndarray:
        """最近一个已完成月末的大类配置（10 维，按 ASSETS 顺序），按信号日缓存.

        求解方式由 ``cfg["base_alloc_mode"]`` 决定：``risk_budget`` 走四桶目标波动，
        ``inverse_vol`` 走波动率倒数。两种模式的解都只依赖该月末及之前的数据，
        故可跨日复用；缓存键含月末日与全部影响结果的参数（包括模式与窗口），
        参数变更不会命中旧解。
        """
        idx = px.index
        pos = len(idx) - 1
        if not self._is_month_end(idx, pos, params.get("_as_of")):
            pos -= 1
            while pos >= 0 and idx[pos].month == idx[pos + 1].month:
                pos -= 1
        if pos < 0:
            raise ValueError(
                f"[{_TAG}] 回测窗口内找不到已完成的月末，无法得到目标波动配置。"
                "请把回测起始日推后至少一个月"
            )
        month_end = idx[pos]
        key = (
            month_end,
            cfg["base_alloc_mode"],
            cfg["cov_window"],
            cfg["ann_days"],
            round(cfg["vol_target"], 12),
            tuple(cfg["inv_vol_windows"]),
        )
        state = self._ensure_state()
        cache: Dict[Any, Tuple[np.ndarray, Optional[Dict[str, Any]]]] = state.setdefault(
            "bucket_cache", {}
        )
        if key in cache:
            cached, info = cache[key]
            if info is not None:
                state["inv_vol_info"] = info
            return cached

        if cfg["base_alloc_mode"] == "inverse_vol":
            w, info = _inverse_vol_config(px.loc[:month_end], assets, cfg)
            state["inv_vol_info"] = info
            cache[key] = (w, info)
            return w
        # 四桶模式与逆波动率模式共用一份 state，切回时清掉上一模式的缩放记录，
        # 否则审计会把旧口径的 capped 记到本期
        state.pop("inv_vol_info", None)

        rets = px[list(assets)].pct_change(fill_method=None).iloc[1:]
        hist = rets.loc[:month_end].tail(int(cfg["cov_window"]))
        if len(hist) < cfg["cov_window"]:
            raise ValueError(
                f"[{_TAG}] 月末 {month_end.date()} 的协方差需要 {cfg['cov_window']} 个交易日收益，"
                f"当前只有 {len(hist)} 个；请把回测起始日推后"
            )
        cov = hist.cov().to_numpy() * float(cfg["ann_days"])
        if np.linalg.eigvalsh(cov).min() <= 0:
            raise ValueError(
                f"[{_TAG}] 月末 {month_end.date()} 的样本协方差不是正定矩阵，"
                "请检查是否有重复资产或样本过短"
            )
        m = _bucket_mapping(cov)
        buckets, _loss = _solve_buckets(m.T @ cov @ m, float(cfg["vol_target"]))
        w = m @ buckets
        cache[key] = (w, None)
        return w

    def _expand_orig(self, orig10: np.ndarray, groups: Dict[str, List[str]]) -> np.ndarray:
        """10 维月末配置展开到风险矩阵列（行业与市场基准为 0）."""
        n = len(groups["EQ"]) + len(groups["GOLD"]) + len(groups["BOND"]) + len(groups["CASH"])
        if len(orig10) != n:
            raise ValueError(f"[{_TAG}] 月末配置维度 {len(orig10)} 与分组资产数 {n} 不一致")
        risk_n = len(self._risk_columns(groups))
        out = np.zeros(risk_n)
        out[: n - 1] = orig10[: n - 1]
        out[-1] = orig10[-1]
        return out

    def _dar_ar_series(
        self, rets: pd.DataFrame, cfg: Dict[str, Any]
    ) -> pd.Series:
        """行业收益 → 滚动 AR 序列（从矩阵最早一天算起，已算过的末端不重算）.

        **不能截断历史**：``_locked_position`` 的 20 日锁定状态机记着
        ``remaining`` 计数，它在目标持续为 0/1 时每 20 个交易日重新上锁，
        相位取决于序列从哪天开始。实测把输入截到 565 个观测时，锁定相位与
        原型错开，2026-03-31 ~ 04-17 的成长仓位提前一档变成 50%，与原型
        （满仓）相差 3.1e-3 权重、逐日净值差 1.4e-4。

        代价是每日一次特征分解；已算过的末端缓存在 ``self._state``，
        回测逐日推进时每次只新增一日。
        """
        window = int(cfg["dar_ar_window"])
        half_life = float(cfg["dar_half_life"])
        n_components = int(cfg["dar_components"])
        if rets.shape[1] < n_components:
            raise ValueError(
                f"[{_TAG}] DAR 的主成分个数 {n_components} 不得超过行业数量 {rets.shape[1]}"
            )
        if len(rets) < window:
            raise ValueError(
                f"[{_TAG}] DAR 需要至少 {window} 个行业收益观测，当前 {len(rets)} 个"
            )
        weights = _exponential_weights(window, half_life)
        x = rets.to_numpy(dtype=float)
        index = rets.index
        state = self._ensure_state()
        key = (window, half_life, n_components)
        cache = state.get("dar_ar_cache")
        reusable = (
            cache is not None
            and cache["key"] == key
            and cache["first"] == index[0]
            and cache["end"] < len(index)
            and index[cache["end"]] == cache["dates"][-1]
        )
        if reusable:
            start = cache["end"] + 1
            dates = list(cache["dates"])
            values = list(cache["values"])
        else:
            start = window - 1
            dates = []
            values = []
        for end in range(start, len(index)):
            value = _ar_value_at(x, end, weights, n_components)
            if value is None:
                continue
            dates.append(index[end])
            values.append(value)
        if not values:
            raise ValueError(f"[{_TAG}] DAR 的 AR 序列为空（行业收益窗口内方差为 0））")
        state["dar_ar_cache"] = {
            "key": key,
            "first": index[0],
            "end": len(index) - 1,
            "dates": dates,
            "values": values,
        }
        return pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float)

    def _dar_position(
        self, px: pd.DataFrame, groups: Dict[str, List[str]], cfg: Dict[str, Any]
    ) -> float:
        """DAR 决定的成长端仓位（0 / 0.5 / 1），取自信号日当天.

        输入是整段价格矩阵（不再截断）：20 日锁定的相位依赖序列起点，
        截断会与原型错位，详见 ``_dar_ar_series``。
        """
        ind = list(groups["IND"])
        rets = px[ind].pct_change(fill_method=None).iloc[1:]
        if len(rets) < int(cfg["dar_ar_window"]) + int(cfg["dar_long_window"]):
            raise ValueError(
                f"[{_TAG}] DAR 需要至少 "
                f"{int(cfg['dar_ar_window']) + int(cfg['dar_long_window'])} 个行业收益观测，"
                f"当前 {len(rets)} 个；请把回测起始日推后"
            )
        ar = self._dar_ar_series(rets, cfg)
        state_w = int(cfg["dar_state_window"])
        long_w = int(cfg["dar_long_window"])
        short_w = int(cfg["dar_short_window"])
        ddof = int(cfg["dar_std_ddof"])
        ar_5d = ar.rolling(state_w, min_periods=state_w).mean()
        ar_long = ar.rolling(long_w, min_periods=long_w).mean()
        ar_short = ar.rolling(short_w, min_periods=short_w).mean()
        sigma_long = ar.rolling(long_w, min_periods=long_w).std(ddof=ddof)
        sigma_short = ar.rolling(short_w, min_periods=short_w).std(ddof=ddof)
        dar_long = (ar_5d - ar_long) / sigma_long.replace(0, np.nan)
        dar_short = (ar_5d - ar_short) / sigma_short.replace(0, np.nan)
        signal_long = _three_state(dar_long, float(cfg["dar_signal_threshold"]))
        signal_short = _three_state(dar_short, float(cfg["dar_signal_threshold"]))
        fused = _fuse_signals(signal_long, signal_short, ar_5d.diff())
        position = _locked_position(
            fused,
            int(cfg["dar_signal_mean_window"]),
            float(cfg["dar_trigger"]),
            int(cfg["dar_hold_days"]),
        ).dropna()
        if position.empty:
            raise ValueError(
                f"[{_TAG}] DAR 仓位序列为空（AR 暖机不足），请把回测起始日推后或缩小 DAR 窗口"
            )
        return float(position.iloc[-1])

    def _timing_state(
        self,
        px: pd.DataFrame,
        market_close: pd.Series,
        high: pd.Series,
        low: pd.Series,
        groups: Dict[str, List[str]],
        cfg: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, float], Optional[pd.Timestamp]]:
        """信号日的三形态事件状态：(是否有事件, 选中行业权重, 事件日).

        形态识别只在信号日之前的一段尾部上扫描：三种形态的判定只依赖各自窗口
        （252 日广度、90 日 ATR、40 日下跌段、最长 20 日冷却），尾部 ``scan`` 行
        已足够让冷却状态收敛；再往前的事件不可能落在 ``timing_hold`` 窗口内。
        """
        ind = list(groups["IND"])
        ind_set = set(ind)
        candidates = [c for c in (cfg.get("industry_candidates") or ind) if c in ind_set]
        if len(candidates) < int(cfg["timing_top"]):
            raise ValueError(
                f"[{_TAG}] 选股候选行业 {len(candidates)} 只少于事件选股数量 "
                f"{int(cfg['timing_top'])}，事件将永远只能空仓"
            )
        scan = int(
            max(int(cfg["high_window"]), int(cfg["atr_window"]))
            + int(cfg["timing_hold"])
            + int(cfg["combo_age"])
            + int(cfg["top_cooldown"])
            + 60
        )
        start = max(0, len(px) - scan)
        sub = px.iloc[start:]
        axis = sub.index
        if len(sub) < max(int(cfg["high_window"]), int(cfg["atr_window"])) + 3:
            raise ValueError(
                f"[{_TAG}] 三形态识别需要至少 "
                f"{max(int(cfg['high_window']), int(cfg['atr_window'])) + 3} 个交易日，"
                f"当前 {len(sub)} 个；请把回测起始日推后"
            )
        mkt_close = market_close.iloc[start:]
        hi = high.iloc[start:]
        lo = low.iloc[start:]
        ind_close = sub[ind]
        cand_close = sub[candidates]
        ind_ret = cand_close.pct_change(fill_method=None).to_numpy(dtype=float)
        ind_px = cand_close.to_numpy(dtype=float)
        mkt_np = mkt_close.to_numpy(dtype=float)

        rebound = _detect_rebound(mkt_np, hi, lo, mkt_close, cfg)
        top = _detect_top_switch(mkt_close, hi, lo, ind_close, cfg)
        breakout = _detect_breakout(mkt_close, hi, lo, cfg)
        for recs in (rebound, top, breakout):
            for rec in recs:
                rec["signal_date"] = axis[int(rec["signal_pos"])]
        form_scores = {
            "rebound": _event_scores(
                "rebound", rebound, ind_ret, ind_px, candidates,
                int(cfg["min_industry_history"]), int(cfg["m_cap"]),
            ),
            "top": _event_scores(
                "top", top, ind_ret, ind_px, candidates,
                int(cfg["min_industry_history"]), 0,
            ),
            "breakout": _event_scores(
                "breakout", breakout, ind_ret, ind_px, candidates,
                int(cfg["min_industry_history"]), 0,
            ),
        }
        event_dates = set()
        for scores in form_scores.values():
            event_dates.update(scores.keys())
        if not event_dates:
            return False, {}, None

        i = len(axis) - 1
        lo_k = max(0, i - int(cfg["combo_age"]) - int(cfg["timing_hold"]) + 1)
        cand_dates = [axis[k] for k in range(lo_k, i + 1) if axis[k] in event_dates]
        combined = _combine_forms(
            form_scores,
            axis,
            cand_dates,
            candidates,
            int(cfg["combo_age"]),
            float(cfg["combo_half_life"]),
        )
        active_pos: Optional[int] = None
        for k in range(i, -1, -1):
            if axis[k] in combined and 0 <= i - k < int(cfg["timing_hold"]):
                active_pos = k
                break
        if active_pos is None:
            return False, {}, None
        event_date = axis[active_pos]
        weights = _event_weights(combined[event_date], candidates, int(cfg["timing_top"]))
        if not any(v > 0 for v in weights.values()):
            # 综合分可用行业不足 timing_top 只：原型同样退化为全现金（等价于无事件）
            return False, weights, event_date
        return True, weights, event_date

    def _blend(
        self,
        neutral: np.ndarray,
        groups: Dict[str, List[str]],
        active: bool,
        event_w: Dict[str, float],
        dar: float,
        covs: Sequence[np.ndarray],
        cfg: Dict[str, Any],
    ) -> Tuple[np.ndarray, float]:
        """权益内部融合 + DAR 控仓 + 约束投影，返回 (目标权重, 保留比例 α)."""
        eq_n = len(groups["EQ"])
        ind = list(groups["IND"])
        ind_start = eq_n + len(groups["GOLD"]) + len(groups["BOND"])
        eq_total = float(neutral[:eq_n].sum())
        if eq_total <= TOL:
            raise ValueError(
                f"[{_TAG}] 风险复核后的权益合计为 {eq_total:.6f}，无法做事件融合；"
                "请放宽 vol_max 或调整月末配置"
            )
        filler = np.zeros(len(neutral))
        if active:
            for j, code in enumerate(ind):
                filler[ind_start + j] = float(event_w.get(code, 0.0))
        else:
            filler[:eq_n] = neutral[:eq_n] / eq_total
        raw = neutral.copy()
        raw[:eq_n] *= 0.5
        raw += filler * (eq_total * 0.5)
        # DAR 只压成长（权益第二只），释放资金转入现金代理
        growth_idx = 1
        if eq_n > growth_idx:
            freed = float(raw[growth_idx]) * (1.0 - dar)
            raw[growth_idx] *= dar
            raw[-1] += freed
        final, alpha = _constrain_alpha(
            neutral, raw, covs, float(cfg["vol_max"]),
            float(cfg["te_ratio"]) * float(cfg["vol_target"]),
        )
        return final, float(alpha)

    def _audit(
        self,
        cfg: Dict[str, Any],
        groups: Dict[str, List[str]],
        neutral: np.ndarray,
        final: np.ndarray,
        alpha: float,
        dar: float,
        active: bool,
        event_date: Optional[pd.Timestamp],
        event_w: Dict[str, float],
        signal_date: pd.Timestamp,
    ) -> Dict[str, Any]:
        """记录本期审计并累计跨期计数（供 compute_monitoring_metrics 暴露到前端）."""
        eq_n = len(groups["EQ"])
        ind_start = eq_n + len(groups["GOLD"]) + len(groups["BOND"])
        ind_n = len(groups["IND"])
        risk_cols = self._risk_columns(groups)
        cov = None
        state = self._ensure_state()
        inv = state.get("inv_vol_info") if cfg["base_alloc_mode"] == "inverse_vol" else None
        audit: Dict[str, Any] = {
            "signal_date": str(pd.Timestamp(signal_date).date()),
            "alpha": float(alpha),
            "dar_position": float(dar),
            "event_active": bool(active),
            "event_date": str(event_date.date()) if event_date is not None else None,
            "event_industries": [c for c, w in event_w.items() if w > 0],
            "equity_total": float(final[:eq_n].sum()),
            "industry_total": float(final[ind_start : ind_start + ind_n].sum()),
            "cash_total": float(final[-1]),
            "neutral_equity_total": float(neutral[:eq_n].sum()),
            "vol_target": float(cfg["vol_target"]),
            "vol_max": float(cfg["vol_max"]),
            "base_alloc_mode": str(cfg["base_alloc_mode"]),
            "inv_vol_windows": [int(w) for w in cfg["inv_vol_windows"]],
            # 逆波动率模式：目标波动是否在无杠杆下不可达（压回满仓）与缩放倍数
            "inv_vol_capped": bool(inv.get("capped")) if inv else False,
            "inv_vol_scale": float(inv["scale"]) if inv else None,
            "inv_vol_normalized_vol": float(inv["normalized_vol"]) if inv else None,
            "group_detail": {k: list(v) for k, v in groups.items()},
            "weights": {c: float(final[j]) for j, c in enumerate(risk_cols)},
        }
        state["last_audit"] = audit
        state["rebalance_count"] = int(state.get("rebalance_count", 0)) + 1
        counts: Dict[str, int] = state.setdefault("trigger_counts", {})
        if alpha < 1.0 - 1e-12:
            counts["constraint_shrink"] = int(counts.get("constraint_shrink", 0)) + 1
        if active:
            counts["event_active"] = int(counts.get("event_active", 0)) + 1
        if dar < 1.0 - TOL:
            counts["dar_cut"] = int(counts.get("dar_cut", 0)) + 1
        return audit

    def _final_check(self, weights: pd.Series, cfg: Dict[str, Any]) -> None:
        """归一化与越界末检；``strict_validate`` 下报错，不静默裁剪."""
        if (weights < -TOL).any():
            bad = {k: float(v) for k, v in weights.items() if float(v) < -TOL}
            if cfg["strict_validate"]:
                raise ValueError(f"[{_TAG}] 目标权重出现负值：{bad}")
            weights.clip(lower=0.0, inplace=True)
        total = float(weights.sum())
        if total <= TOL:
            raise ValueError(f"[{_TAG}] 目标权重合计为 0，约束投影后无可配置权重")
        if abs(total - 1.0) > 1e-6:
            if cfg["strict_validate"]:
                raise ValueError(
                    f"[{_TAG}] 目标权重合计 {total:.10f} 偏离 1（容差 1e-6），"
                    "请检查目标波动、波动上限与主动风险参数组合"
                )
            weights *= 1.0 / total

    # ------------------------------------------------------------------
    # 日度风控与监控指标
    # ------------------------------------------------------------------

    def check_volatility_trigger(
        self, current_weights: pd.Series, prices: pd.DataFrame, **params: Any
    ) -> Tuple[bool, Optional[float]]:
        """不启用日度波动率重置.

        本策略的波动率控制全部在包内完成：月末目标波动配置给出大类比例，
        ``risk_anchor`` 逐日把中性组合收缩到 ``vol_max``，``constrain`` 再做主动风险
        与多窗口总波动投影。引擎或监控的日度「按 target_vol/实现波动率」重置会与
        包内缩放重复，且 ``vol_target`` 是目标而非触发阈值。
        """
        return False, None

    def compute_monitoring_metrics(
        self, current_weights: pd.Series, prices: pd.DataFrame, **params
    ) -> Dict[str, Any]:
        """暴露本期风格层取值、约束触发次数与权重分布（前端监控页指标区）.

        只回读 ``allocate`` 记录下来的审计值，不重算模型——监控指标每个交易日都会
        被调用一次，重算会把整段行情再跑一遍。
        """
        state = self._ensure_state()
        audit: Dict[str, Any] = state.get("last_audit") or {}
        return {
            "rebalance_count": int(state.get("rebalance_count", 0)),
            "constraint_trigger_counts": dict(state.get("trigger_counts") or {}),
            "last_signal_date": audit.get("signal_date"),
            "alpha": audit.get("alpha"),
            "dar_position": audit.get("dar_position"),
            "event_active": audit.get("event_active"),
            "event_date": audit.get("event_date"),
            "event_industries": audit.get("event_industries"),
            "equity_total": audit.get("equity_total"),
            "industry_total": audit.get("industry_total"),
            "cash_total": audit.get("cash_total"),
            "neutral_equity_total": audit.get("neutral_equity_total"),
            "vol_target": audit.get("vol_target"),
            "vol_max": audit.get("vol_max"),
            "base_alloc_mode": audit.get("base_alloc_mode"),
            "inv_vol_capped": audit.get("inv_vol_capped"),
            "inv_vol_scale": audit.get("inv_vol_scale"),
            "inv_vol_normalized_vol": audit.get("inv_vol_normalized_vol"),
        }

    def _ensure_state(self) -> Dict[str, Any]:
        """跨期状态容器（月末解缓存、审计与计数）；首次访问时惰性创建."""
        state = getattr(self, "_state", None)
        if not isinstance(state, dict):
            state = {}
            self._state = state
        return state
