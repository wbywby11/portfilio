"""夏普风险平价（nous_low_vol）：打包独立形态的低波动多资产指数策略.

方法：夏普动量（22/65/260 三窗口 rank 求和，22 日 MOM tie-break）在资产池内
选样 → 朴素风险平价基础权重 (1/N)×(1/σ)，σ 取多窗口年化波动率最大值 →
目标波动率档缩放（Σw = min(Σw, 1)；目标波动率为 0 时直接归一化）→ 组约束顺序
投影 C0→C2→C1→C6→C4→C3→C7→C8→C5→现金回填→剩余回填→复检 C7/C8 → 权重末检。
日度风控写在包内：非月末信号日实现波动率超触发线时，目标权重按
w × target_vol / 信号日实现波动率 降仓；关闭后为纯月度调仓。

参数默认值对应 40% 档：QDII≤7.5%、非黄金商品≤4%、综合风险预算≤20%、
A股≥MAX(2.4%−QDII,0)、触发线 4%；40% / 50% / 40%拆分三档共用同一套参数，
改参数即可切换档位。同一套代码覆盖三类指数口径：

- FOF 档（V5 族）：黄金独立成组不设上限、C7 加权预算（商品/QDII 系数 2.5）、
  A股公式下限、日度波控；
- 直投档（V6 族）：池内含港股（``hk_eq_codes``）、15/16 选 11/12、
  仅 C0 + C8 混合预算（权益+黄金+商品 ≤20%），不设 A股/A债下限、无波控；
- 无商品 FOF 档（V7）：仅 C0 + C1（QDII≤3%）+ C8
  （A股+黄金+商品+3.75×QDII ≤20%），不设 A股/A债下限、无波控。

模式：打包独立形态（``strategy_form="standalone"``）。composition 三层全 None，
选样复用库内 :class:`~app.selection.selectors.sharpe.SharpeSelector`（禁止复制
算法），赋权/约束/风控全部在本模块内，对外只暴露参数与底层资产；同一份代码
供回测、日常监控、组合子策略三条通道使用。

红线：``allocate`` 为纯函数，只消费注入的 prices 与 params，不读文件、不查库；
资产分组、上限、窗口、阈值全部来自参数，不写死资产代码与日期；计算不可行时
报错，不兜底等权、不跳过资产、不放宽断言。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.allocation.models.base import BaseStrategyModel

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量：分组参数名 → 包内组名（组名与原型 config_versions.groups_of 一致）
# ---------------------------------------------------------------------------

GROUP_PARAM_TO_KEY: Dict[str, str] = {
    "a_bond_codes": "A_BOND",      # A 债（含可转债）
    "a_eq_codes": "A_EQ",          # A 股权益
    "hk_eq_codes": "HK_EQ",        # 港股权益（V6 直投版：恒生指数/港股通科技）
    "qdii_codes": "QDII3",         # 海外权益 QDII
    "qdii_usd_codes": "QDII_USD",  # 美债展期（无美债版为空）
    "comm_codes": "COMM",          # 非黄金商品（V6/V7 黄金留在本组）
    "gold_codes": "GOLD",          # 黄金（V5 从商品类移出，独立成组）
}
GROUP_KEYS: Tuple[str, ...] = ("A_BOND", "A_EQ", "HK_EQ", "COMM", "GOLD", "QDII3", "QDII_USD")

TOL = 1e-6
_DEFAULT_VOL_WINDOWS = (22, 65, 130)
_DEFAULT_ANN_FACTOR = float(np.sqrt(260))


# ---------------------------------------------------------------------------
# 纯函数：参数解析与波动率
# ---------------------------------------------------------------------------


def parse_int_list(value: Any, default: Sequence[int]) -> List[int]:
    """把窗口参数归一为正整数列表（逗号分隔字符串 / 列表 / 单值）."""
    if value is None:
        return list(default)
    if isinstance(value, (list, tuple, set)):
        raw: Sequence[Any] = list(value)
    else:
        raw = [p.strip() for p in str(value).split(",") if p.strip()]
    try:
        parsed = [int(float(x)) for x in raw]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"窗口参数格式错误：{value!r}（应为逗号分隔的正整数，如 '22,65,130'）：{exc}"
        ) from exc
    parsed = [w for w in parsed if w > 0]
    return parsed or list(default)


def optional_float(value: Any) -> Optional[float]:
    """把「0 / 空 / None」解释为不启用该约束，返回 None；否则返回浮点值."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num <= 0 or np.isnan(num):
        return None
    return num


def asset_volatility(
    prices: pd.DataFrame,
    date_idx: int,
    windows: Sequence[int] = _DEFAULT_VOL_WINDOWS,
    annualization_factor: float = _DEFAULT_ANN_FACTOR,
) -> pd.Series:
    """资产波动率：多窗口年化 vol 取最大值（窗口不足则该窗口不参与）."""
    returns = prices.pct_change(fill_method=None)
    vols: Dict[str, float] = {}
    for asset in prices.columns:
        collected = []
        for w in windows:
            if date_idx >= w:
                seg = returns[asset].iloc[date_idx - w + 1: date_idx + 1]
                vol = seg.std() * annualization_factor
                if not np.isnan(vol):
                    collected.append(float(vol))
        vols[asset] = max(collected) if collected else np.nan
    return pd.Series(vols)


def portfolio_volatility(
    prices: pd.DataFrame,
    weights: pd.Series,
    date_idx: int,
    windows: Sequence[int] = _DEFAULT_VOL_WINDOWS,
    annualization_factor: float = _DEFAULT_ANN_FACTOR,
) -> float:
    """组合波动率：权重加权组合收益的多窗口年化 vol 取最大值（缺失收益按 0）."""
    returns = prices.pct_change(fill_method=None)
    valid = [a for a in weights.index if weights.get(a, 0) > 0 and a in returns.columns]
    if not valid:
        return 0.0
    port_returns = pd.Series(0.0, index=returns.index)
    for asset in valid:
        port_returns = port_returns + float(weights[asset]) * returns[asset].fillna(0)
    collected = []
    for w in windows:
        if date_idx >= w:
            seg = port_returns.iloc[date_idx - w + 1: date_idx + 1]
            vol = seg.std() * annualization_factor
            if not np.isnan(vol):
                collected.append(float(vol))
    return max(collected) if collected else 0.0


# ---------------------------------------------------------------------------
# 纯函数：约束投影算子（与原型 step2_weight_calculation 逐条对齐）
# ---------------------------------------------------------------------------


def cap_group(w: pd.Series, idx: Sequence[str], cap: float) -> bool:
    """C2 类组上限：组内等比缩减，返回是否 binding."""
    members = [a for a in idx if a in w.index]
    if not members:
        return False
    total = float(w.loc[members].sum())
    if total > cap + TOL:
        w.loc[members] = w.loc[members] * (cap / total)
        return True
    return False


def cap_group_per_asset(w: pd.Series, idx: Sequence[str], cap: float) -> bool:
    """C2 变体（拆分版）：组内单资产上限，超限资产逐个 clip."""
    members = [a for a in idx if a in w.index]
    if not members:
        return False
    if bool((w.loc[members] > cap + TOL).any()):
        w.loc[members] = w.loc[members].clip(upper=cap)
        return True
    return False


def qdii_priority(
    w: pd.Series,
    idx_eq: Sequence[str],
    idx_usd: Sequence[str],
    cap: float,
) -> str:
    """C1 QDII 上限 + 内部优先级：权益 QDII 优先占额度，美债用余额.

    Returns:
        'none' 合计未超限 / 'a_ge_C' 权益 QDII 单独超限（美债清零）/
        'usd_cut' 权益 QDII 保持、美债按余额缩减
    """
    eq = [a for a in idx_eq if a in w.index]
    usd = [a for a in idx_usd if a in w.index]
    a = float(w.loc[eq].sum()) if eq else 0.0
    b = float(w.loc[usd].sum()) if usd else 0.0
    if a + b <= cap + TOL:
        return "none"
    if a >= cap:
        if a > 0 and eq:
            w.loc[eq] = w.loc[eq] * (cap / a)
        if usd:
            w.loc[usd] = 0.0
        return "a_ge_C"
    if b > 0 and usd:
        w.loc[usd] = w.loc[usd] * ((cap - a) / b)
    return "usd_cut"


def floor_group(
    w: pd.Series,
    idx: Sequence[str],
    floor: float,
    comp_idx: Sequence[str],
) -> str:
    """C3/C4 类组下限：抬升组权重到 floor，Σ>1 时等比压缩 comp 组.

    Returns:
        'none' / 'raised' / 'raised+compressed' / 'raised_no_comp' / 'infeasible'
    """
    members = [a for a in idx if a in w.index]
    comp = [a for a in comp_idx if a in w.index]
    if not members:
        return "infeasible"
    total = float(w.loc[members].sum())
    if total <= TOL:
        return "infeasible"          # 入选集无该类资产
    if total >= floor - TOL:
        return "none"
    w.loc[members] = w.loc[members] * (floor / total)
    if float(w.sum()) > 1 + TOL:
        cs = float(w.loc[comp].sum()) if comp else 0.0
        target = 1.0 - (float(w.sum()) - cs)
        if cs <= TOL or target <= TOL:
            if cs > TOL:
                w.loc[comp] = 0.0
            return "raised_no_comp"
        w.loc[comp] = w.loc[comp] * (target / cs)
        return "raised+compressed"
    return "raised"


def cap_bond_usd(
    w: pd.Series,
    bond_idx: Sequence[str],
    usd_idx: Sequence[str],
    cap: float,
) -> str:
    """C5 类：A 债 + 美债合计上限。先压美债，美债清零仍超再压 A 债."""
    bonds = [a for a in bond_idx if a in w.index]
    usd = [a for a in usd_idx if a in w.index]
    bs = float(w.loc[bonds].sum()) if bonds else 0.0
    us = float(w.loc[usd].sum()) if usd else 0.0
    total = bs + us
    if total <= cap + TOL:
        return "none"
    excess = total - cap
    if us >= excess - TOL:
        if us > TOL:
            w.loc[usd] = w.loc[usd] * ((us - excess) / us)
        return "usd_cut"
    if usd:
        w.loc[usd] = 0.0
    remaining = excess - us
    if bs > TOL and remaining > TOL:
        w.loc[bonds] = w.loc[bonds] * ((bs - remaining) / bs)
    return "bond_cut"


def cap_risk_budget(
    w: pd.Series,
    groups: Dict[str, List[str]],
    qdii_idx: Sequence[str],
    cap: float,
    aq_floor: Optional[float] = None,
    w_comm: float = 2.5,
    w_qdii: float = 2.5,
) -> Tuple[bool, float, bool]:
    """C7 综合风险预算：A股 + 黄金 + w_comm×商品 + w_qdii×QDII ≤ cap.

    超出时四组同比缩减；``aq_floor`` 不为 None 时缩减后 A股+QDII 权重合计
    不低于 aq_floor，差额由黄金与非黄金商品承担。

    Returns:
        (是否 binding, 缩减后综合预算值, AQ 保护是否生效)
    """
    eq = [a for a in groups.get("A_EQ", []) if a in w.index]
    gold = [a for a in groups.get("GOLD", []) if a in w.index]
    comm = [a for a in groups.get("COMM", []) if a in w.index]
    qdii = [a for a in qdii_idx if a in w.index]
    idx = eq + gold + comm + qdii
    if not idx:
        return False, 0.0, False

    aq_w = (float(w.loc[eq].sum()) if eq else 0.0) + (float(w.loc[qdii].sum()) if qdii else 0.0)
    aq_b = (float(w.loc[eq].sum()) if eq else 0.0) + w_qdii * (float(w.loc[qdii].sum()) if qdii else 0.0)
    rest = (float(w.loc[gold].sum()) if gold else 0.0) + w_comm * (float(w.loc[comm].sum()) if comm else 0.0)
    total = aq_b + rest
    if total <= cap + TOL:
        return False, total, False

    k = cap / total
    if aq_floor is None or aq_w <= TOL:
        w.loc[idx] = w.loc[idx] * k
        return True, cap, False

    k_aq = max(k, aq_floor / aq_w)
    if k >= k_aq - TOL:
        w.loc[idx] = w.loc[idx] * k
        return True, cap, False

    # A股+QDII 只缩到下限，剩余超额由黄金 + 非黄金商品承担
    if eq:
        w.loc[eq] = w.loc[eq] * k_aq
    if qdii:
        w.loc[qdii] = w.loc[qdii] * k_aq
    remain = cap - aq_b * k_aq
    if rest > TOL:
        k_rest = min(1.0, max(remain, 0.0) / rest)
        if gold:
            w.loc[gold] = w.loc[gold] * k_rest
        if comm:
            w.loc[comm] = w.loc[comm] * k_rest
    after = (aq_b * k_aq
             + (float(w.loc[gold].sum()) if gold else 0.0)
             + w_comm * (float(w.loc[comm].sum()) if comm else 0.0))
    if after > cap + TOL:            # 黄金/商品清零后仍超：A股+QDII 压到预算
        k2 = cap / after
        if eq:
            w.loc[eq] = w.loc[eq] * k2
        if qdii:
            w.loc[qdii] = w.loc[qdii] * k2
        return True, cap, False
    return True, after, True


def mix_budget_value(
    w: pd.Series,
    groups: Dict[str, List[str]],
    qdii_idx: Sequence[str],
    spec: Dict[str, Any],
) -> float:
    """C8 混合风险预算当前值：权益 × w_eq + 黄金 × w_gold + 商品 × w_comm + QDII × w_qdii.

    「权益」= A_EQ + HK_EQ（V6 直投版含 2 只港股）；黄金留在 COMM 组时
    GOLD 为空，按商品系数计入，与原型 ``groups_of`` 口径一致。
    """
    eq = [a for a in list(groups.get("A_EQ", [])) + list(groups.get("HK_EQ", [])) if a in w.index]
    gold = [a for a in groups.get("GOLD", []) if a in w.index]
    comm = [a for a in groups.get("COMM", []) if a in w.index]
    qdii = [a for a in qdii_idx if a in w.index]
    return (
        float(spec.get("w_eq", 1.0)) * (float(w.loc[eq].sum()) if eq else 0.0)
        + float(spec.get("w_gold", 1.0)) * (float(w.loc[gold].sum()) if gold else 0.0)
        + float(spec.get("w_comm", 1.0)) * (float(w.loc[comm].sum()) if comm else 0.0)
        + float(spec.get("w_qdii", 1.0)) * (float(w.loc[qdii].sum()) if qdii else 0.0)
    )


def cap_mix_budget(
    w: pd.Series,
    groups: Dict[str, List[str]],
    qdii_idx: Sequence[str],
    spec: Dict[str, Any],
) -> Tuple[bool, float, float]:
    """C8 混合风险预算：超出上限时非 A 债四组同比例缩减，缺口由 A 债回填.

    V6 直投版：权益 + 黄金 + 商品 ≤ 20%（系数全 1）；
    V7：A股 + 黄金 + 商品 + 3.75×QDII ≤ 20%。

    Returns:
        (是否 binding, 缩减前预算值, 缩减后预算值)
    """
    cap = float(spec["cap"])
    idx: List[str] = []
    for key in ("A_EQ", "HK_EQ", "GOLD", "COMM"):
        idx += [a for a in groups.get(key, []) if a in w.index]
    idx += [a for a in qdii_idx if a in w.index]
    if not idx:
        return False, 0.0, 0.0
    before = mix_budget_value(w, groups, qdii_idx, spec)
    if before <= cap + TOL:
        return False, before, before
    w.loc[idx] = w.loc[idx] * (cap / before)
    return True, before, mix_budget_value(w, groups, qdii_idx, spec)


def apply_constraints(
    w: pd.Series,
    groups: Dict[str, List[str]],
    cons: Dict[str, Any],
) -> Tuple[pd.Series, Dict[str, Any]]:
    """约束投影流水线：C0→C2→C1→C6→C4→C3→C7→C8→C5→现金回填→剩余回填→复检 C7/C8.

    每一步返回 (权重, 状态)，状态写进审计字典，供 ``compute_monitoring_metrics``
    暴露到前端监控页与验收对账。

    Args:
        w: 基础权重（已做目标波动率缩放），index 为资产池
        groups: 组名 → 资产代码列表
        cons: 约束规格，键见 :meth:`NousLowVolStrategy._build_constraints`

    Returns:
        (投影后权重, 审计字典)
    """
    w = w.copy()
    pool = list(w.index)
    audit: Dict[str, Any] = {"warnings": []}
    qdii_all = list(groups.get("QDII3", [])) + list(groups.get("QDII_USD", []))

    def g_sum(keys: Sequence[str]) -> float:
        members = [a for a in keys if a in w.index]
        return float(w.loc[members].sum()) if members else 0.0

    # ---- C0 杠杆 ≤ 100%（先归一，再由下限抬升）----
    if float(w.sum()) > 1 + TOL:
        w = w / float(w.sum())

    for key, value in (
        ("pre_QDII", g_sum(qdii_all)),
        ("pre_COMM", g_sum(groups.get("COMM", []))),
        ("pre_GOLD", g_sum(groups.get("GOLD", []))),
        ("pre_AEQ", g_sum(groups.get("A_EQ", []))),
        ("pre_ABOND", g_sum(groups.get("A_BOND", []))),
        ("pre_LEV", float(w.sum())),
    ):
        audit[key] = value
    for name in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"):
        audit[name] = "skip"
    audit["aeq_floor_used"] = 0.0
    audit["aeq_cap_used"] = None
    audit["现金回填"] = 0.0
    audit["剩余回填"] = 0.0

    qdii_cap = cons.get("qdii_cap")
    comm_cap = cons.get("comm_cap")
    comm_cap_per = cons.get("comm_cap_per")
    risk_cap = cons.get("risk_cap")
    risk_budget = cons.get("risk_budget")
    mix_budget = cons.get("mix_budget")
    aq_floor = cons.get("aq_floor")
    aeq_floor_spec = cons.get("aeq_floor_spec")
    abond_floor = cons.get("abond_floor")
    abond_cap = cons.get("abond_cap")
    abond_usd_cap = cons.get("abond_usd_cap")
    w_comm = float(cons.get("risk_budget_w_comm", 2.5))
    w_qdii = float(cons.get("risk_budget_w_qdii", 2.5))

    # ---- C2 商品上限（组等比缩减 或 拆分版单资产上限；均 None = 无限制）----
    if comm_cap_per is not None:
        audit["C2"] = "binding" if cap_group_per_asset(w, groups.get("COMM", []), comm_cap_per) else "none"
    elif comm_cap is not None:
        audit["C2"] = "binding" if cap_group(w, groups.get("COMM", []), comm_cap) else "none"

    # ---- C1 QDII 上限 + 优先级（None = 无限制，跳过）----
    if qdii_cap is not None:
        audit["C1"] = qdii_priority(w, groups.get("QDII3", []), groups.get("QDII_USD", []), qdii_cap)

    # ---- C6 A股封顶：A股 ≤ cap − QDII（− 商品）----
    if risk_cap is not None:
        cap_total, inc_comm = risk_cap if isinstance(risk_cap, tuple) else (risk_cap, True)
        budget = cap_total - g_sum(qdii_all)
        if inc_comm:
            budget -= g_sum(groups.get("COMM", []))
        budget = max(0.0, budget)
        audit["aeq_cap_used"] = budget
        audit["C6"] = "binding" if cap_group(w, groups.get("A_EQ", []), budget) else "none"

    # ---- C4 A债下限（comp = 非债）----
    if abond_floor is not None:
        comp_nonbond = [c for c in pool if c not in set(groups.get("A_BOND", []))]
        st = floor_group(w, groups.get("A_BOND", []), abond_floor, comp_nonbond)
        audit["C4"] = st
        if st == "infeasible":
            audit["warnings"].append("入选集无 A 债资产，A 债下限不可行")

    # ---- C3 A股下限：公式型 MAX(offset − QDII, 0) 或静态型 ----
    comm_tot = g_sum(groups.get("COMM", []))
    qdii_tot = g_sum(qdii_all)
    floor_val = 0.0
    if aeq_floor_spec is not None:
        kind, val = aeq_floor_spec
        floor_val = max(val - qdii_tot, 0.0) if kind == "qdii_offset" else float(val)
    if floor_val > TOL:
        audit["aeq_floor_used"] = floor_val
        # 压缩对象 = A债：抬升致 Σ>1 时等比压缩 A债（A股下限优先，允许牺牲 A债下限并记警告）
        st = floor_group(w, groups.get("A_EQ", []), floor_val, groups.get("A_BOND", []))
        audit["C3"] = st
        if st == "infeasible":
            audit["warnings"].append("入选集无 A 股权益资产，A 股下限不可行")
        elif st == "raised_no_comp":
            audit["warnings"].append("A 债清零仍 Σ>1，终检整体缩放兜底")
        elif abond_floor is not None:
            bs_now = g_sum(groups.get("A_BOND", []))
            if bs_now < abond_floor - TOL:
                audit["warnings"].append(
                    f"C3 压缩 A 债至 {bs_now:.2%}，牺牲 A 债 {abond_floor:.0%} 下限"
                )
    audit["aeq_floor_comm_ref"] = comm_tot

    # ---- C7 综合风险预算 ----
    if risk_budget is not None:
        bind, after, guard = cap_risk_budget(
            w, groups, qdii_all, risk_budget, aq_floor, w_comm, w_qdii
        )
        audit["C7"] = "binding" if bind else "none"
        audit["C7_after"] = after
        audit["C7_aq_guard"] = guard

    # ---- C8 混合风险预算（V6/V7）：权益+黄金+商品+系数×QDII ≤ cap ----
    #      超出时非 A 债四组同比例缩减，缺口由后续现金回填到 A 债
    if mix_budget is not None:
        audit["mix_cap_used"] = float(mix_budget["cap"])
        bind8, pre8, post8 = cap_mix_budget(w, groups, qdii_all, mix_budget)
        audit["C8"] = "binding" if bind8 else "none"
        audit["C8_pre"] = pre8
        audit["C8_post"] = post8

    # ---- C5 A债上限（A债+美债 ≤ cap 或 A债 ≤ cap）----
    if abond_usd_cap is not None:
        audit["C5"] = cap_bond_usd(w, groups.get("A_BOND", []), groups.get("QDII_USD", []), abond_usd_cap)
    elif abond_cap is not None:
        audit["C5"] = "binding" if cap_group(w, groups.get("A_BOND", []), abond_cap) else "none"

    # ---- 数值清理 + C0 终检 ----
    w = w.clip(lower=0)
    if float(w.sum()) > 1 + TOL:
        audit["warnings"].append(f"终检杠杆 {float(w.sum()):.4f}>1，整体缩放")
        w = w / float(w.sum())

    # ---- 现金回填：剩余权重按现有 A 债权重同比例补回，不突破 A债/A债+美债上限 ----
    resid = 1.0 - float(w.sum())
    bond = [a for a in groups.get("A_BOND", []) if a in w.index]
    bs = float(w.loc[bond].sum()) if bond else 0.0
    if resid > TOL and bs > TOL:
        if abond_usd_cap is not None:
            headroom = abond_usd_cap - (bs + g_sum(groups.get("QDII_USD", [])))
        elif abond_cap is not None:
            headroom = abond_cap - bs
        else:
            headroom = resid
        add = min(resid, max(0.0, headroom))
        if add > TOL:
            w.loc[bond] = w.loc[bond] * (1 + add / bs)
            audit["现金回填"] = add

    # ---- 剩余回填：A债到顶仍有剩余时等比放大 A股+海外权益+商品吸收，到顶后 A股兜底 ----
    resid2 = 1.0 - float(w.sum())
    if resid2 > TOL:
        eq_idx = [a for a in groups.get("A_EQ", []) if a in w.index]
        q3_idx = [a for a in groups.get("QDII3", []) if a in w.index]
        cm_idx = [a for a in groups.get("COMM", []) if a in w.index]
        us_sum = g_sum(groups.get("QDII_USD", []))
        se = float(w.loc[eq_idx].sum()) if eq_idx else 0.0
        sq3 = float(w.loc[q3_idx].sum()) if q3_idx else 0.0
        sc = float(w.loc[cm_idx].sum()) if cm_idx else 0.0
        s3 = se + sq3 + sc
        if s3 > TOL:
            k = (s3 + resid2) / s3
            if risk_cap is not None:
                cap_total, inc_comm = risk_cap if isinstance(risk_cap, tuple) else (risk_cap, True)
                denom = s3 if inc_comm else (se + sq3)
                if denom > TOL:
                    k = min(k, cap_total / denom)
            new_sc = sc * k
            if comm_cap is not None:
                new_sc = min(new_sc, comm_cap)
            new_q3 = sq3 * k
            if qdii_cap is not None:      # QDII 额度需扣除美债已占部分
                new_q3 = min(new_q3, max(0.0, qdii_cap - us_sum))
            if sc > TOL:
                w.loc[cm_idx] = w.loc[cm_idx] * (new_sc / sc)
                if comm_cap_per is not None:
                    w.loc[cm_idx] = w.loc[cm_idx].clip(upper=comm_cap_per)
            if sq3 > TOL:
                w.loc[q3_idx] = w.loc[q3_idx] * (new_q3 / sq3)
            rest = resid2 - (new_sc - sc) - (new_q3 - sq3) - se * (k - 1)
            if se > TOL:
                if risk_cap is not None:
                    w.loc[eq_idx] = w.loc[eq_idx] * k
                    if rest > TOL:
                        audit["warnings"].append("风险预算到顶，剩余回填留现金")
                else:
                    w.loc[eq_idx] = w.loc[eq_idx] * ((se * k + max(rest, 0.0)) / se)
            else:
                audit["warnings"].append("无 A 股吸收剩余回填，留现金")
            audit["剩余回填"] = resid2 - max(0.0, 1.0 - float(w.sum()))
        else:
            audit["warnings"].append("无 A 股/海外权益/商品吸收剩余回填，留现金")

    # ---- 复检 C7：剩余回填可能放大预算项 ----
    if risk_budget is not None and audit["剩余回填"] > TOL:
        bind2, _, guard2 = cap_risk_budget(
            w, groups, qdii_all, risk_budget, aq_floor, w_comm, w_qdii
        )
        if bind2:
            audit["C7"] = "binding"
        audit["C7_aq_guard"] = bool(audit.get("C7_aq_guard", False)) or guard2

    # ---- 复检 C8：剩余回填可能放大预算项，超限则缩回并回填 A 债 ----
    if mix_budget is not None and audit["剩余回填"] > TOL:
        bind8b, pre8b, post8b = cap_mix_budget(w, groups, qdii_all, mix_budget)
        if bind8b:
            audit["C8"] = "binding"
            audit["C8_pre"] = pre8b
            audit["C8_post"] = post8b
            resid8 = 1.0 - float(w.sum())
            bs8 = g_sum(groups.get("A_BOND", []))
            if resid8 > TOL and bs8 > TOL:
                w.loc[bond] = w.loc[bond] * ((bs8 + resid8) / bs8)
                audit["现金回填"] = float(audit.get("现金回填", 0.0)) + resid8

    audit["post_QDII"] = g_sum(qdii_all)
    audit["post_COMM"] = g_sum(groups.get("COMM", []))
    audit["post_GOLD"] = g_sum(groups.get("GOLD", []))
    audit["post_AEQ"] = g_sum(groups.get("A_EQ", []))
    audit["post_EQUITY"] = audit["post_AEQ"] + g_sum(groups.get("HK_EQ", []))
    audit["post_AQ"] = audit["post_AEQ"] + audit["post_QDII"]
    audit["post_ABOND"] = g_sum(groups.get("A_BOND", []))
    if risk_budget is not None:
        audit["post_RISK_BUDGET"] = (
            audit["post_AEQ"] + audit["post_GOLD"]
            + w_comm * audit["post_COMM"] + w_qdii * audit["post_QDII"]
        )
    if mix_budget is not None:
        audit["post_MIX"] = mix_budget_value(w, groups, qdii_all, mix_budget)
    audit["post_LEV"] = float(w.sum())
    audit["cash"] = 1.0 - float(w.sum())
    return w, audit


def validate_final_weights(
    w: pd.Series,
    groups: Dict[str, List[str]],
    cons: Dict[str, Any],
    label: str,
) -> None:
    """权重末检：非负 / 合计 / QDII 上限 / 商品上限 / A股下限 / 风险预算 / C8.

    任一不满足直接抛错，不静默裁剪、不放宽断言。``require_full_invest``
    为 True 时要求合计恰为 100%；为 False 时允许因 A 债未入选而留现金。
    """
    errs: List[str] = []
    qdii_all = [a for a in list(groups.get("QDII3", [])) + list(groups.get("QDII_USD", [])) if a in w.index]
    eq = [a for a in groups.get("A_EQ", []) if a in w.index]
    comm = [a for a in groups.get("COMM", []) if a in w.index]
    gold = [a for a in groups.get("GOLD", []) if a in w.index]
    qdii_sum = float(w.loc[qdii_all].sum()) if qdii_all else 0.0
    aeq_sum = float(w.loc[eq].sum()) if eq else 0.0

    if bool((w < -TOL).any()):
        errs.append(f"负权重 {dict(w[w < -TOL].round(6))}")
    total = float(w.sum())
    if cons.get("require_full_invest", True):
        if abs(total - 1.0) > 1e-9:
            errs.append(f"合计 {total:.10f} ≠ 100%")
    elif total > 1.0 + 1e-9:
        errs.append(f"合计 {total:.10f} > 100%")

    qdii_cap = cons.get("qdii_cap")
    if qdii_cap is not None and qdii_sum > qdii_cap + 1e-9:
        errs.append(f"QDII {qdii_sum:.4%} > 上限 {qdii_cap:.2%}")

    comm_cap = cons.get("comm_cap")
    if comm_cap is not None and comm and float(w.loc[comm].sum()) > comm_cap + 1e-9:
        errs.append(f"非黄金商品 {float(w.loc[comm].sum()):.4%} > 上限 {comm_cap:.2%}")
    comm_cap_per = cons.get("comm_cap_per")
    if comm_cap_per is not None and comm:
        mx = float(w.loc[comm].max())
        if mx > comm_cap_per + 1e-9:
            errs.append(f"单商品 {mx:.4%} > 单资产上限 {comm_cap_per:.2%}")

    aeq_floor_spec = cons.get("aeq_floor_spec")
    if aeq_floor_spec is not None and aeq_floor_spec[0] == "qdii_offset":
        floor = max(aeq_floor_spec[1] - qdii_sum, 0.0)
        if aeq_sum < floor - 1e-9:
            errs.append(f"A 股 {aeq_sum:.4%} < 下限 {floor:.4%}")

    aq_floor = cons.get("aq_floor")
    if aq_floor is not None and aeq_sum + qdii_sum < aq_floor - 1e-9:
        errs.append(f"A 股+QDII {aeq_sum + qdii_sum:.4%} < 下限 {aq_floor:.2%}")

    risk_budget = cons.get("risk_budget")
    if risk_budget is not None:
        w_comm = float(cons.get("risk_budget_w_comm", 2.5))
        w_qdii = float(cons.get("risk_budget_w_qdii", 2.5))
        s = (aeq_sum
             + (float(w.loc[gold].sum()) if gold else 0.0)
             + w_comm * (float(w.loc[comm].sum()) if comm else 0.0)
             + w_qdii * qdii_sum)
        if s > risk_budget + 1e-9:
            errs.append(f"加权风险敞口 {s:.4%} > 预算 {risk_budget:.2%}")

    mix_budget = cons.get("mix_budget")
    if mix_budget is not None:
        v = mix_budget_value(w, groups, qdii_all, mix_budget)
        if v > float(mix_budget["cap"]) + 1e-9:
            errs.append(f"C8 混合风险敞口 {v:.4%} > 预算 {mix_budget['cap']:.2%}")

    if errs:
        raise ValueError(f"[nous_low_vol] {label} 权重末检失败: " + "; ".join(errs))


# ---------------------------------------------------------------------------
# 策略类
# ---------------------------------------------------------------------------


class NousLowVolStrategy(BaseStrategyModel):
    """夏普风险平价：夏普动量选样 + 风险平价赋权 + 组约束顺序投影 + 包内日度波控."""

    # ------------------------------------------------------------------
    # 元信息声明
    # ------------------------------------------------------------------

    @classmethod
    def get_param_schema(cls):
        from app.allocation.models.param_schema import (
            ParamSchema,
            StrategyParamSchema,
            model_level_param_group,
        )

        return StrategyParamSchema(
            strategy_type="nous_low_vol",
            display_name="夏普风险平价",
            description=(
                "夏普动量选样 + 朴素风险平价赋权 + 组约束顺序投影"
                "（C0→C2→C1→C6→C4→C3→C7→C8→C5→回填→复检C7/C8）+ 包内日度波动率风控。"
                "选样/赋权/约束/风控全部在策略包内，前端只需配置资产分组与上限参数。"
                "支持范围：V5 FOF40 / FOF50 / FOF40S 三档、V6 直投版 3（16 选 12，含港股、C8 混合预算）、"
                "V7 无商品 FOF15%（QDII≤3% + QDII 系数 3.75）；V6 直投版 1/2 与直投版 3 仅资产池与选样数不同，"
                "改分组与 select_count 即可复现；V2~V4 暂不支持（静态 A 股下限模式与强制替换口径未实现）"
            ),
            composition={
                "selector": None,
                "allocator": "nous_low_vol",
                "controller": None,
                "schedule": {"rebalance_freq": "month_end", "execution_delay": 2},
            },
            # 杠杆与现金在包内处理（Σw = min(Σw, 1)，回填后满仓），Pipeline 不再二次缩放
            internal_leverage=True,
            params=[
                # ━━━ 资产分组（core）：底层资产自由命名，替换资产须与 asset_codes 同步 ━━━
                ParamSchema(
                    name="a_bond_codes", label="A 债组资产", type="text", default="",
                    description="国内债券（含可转债）资产代码，逗号分隔。参与 A 债下限/上限与现金回填",
                ),
                ParamSchema(
                    name="a_eq_codes", label="A 股组资产", type="text", default="",
                    description="A 股权益资产代码，逗号分隔。参与 A 股下限与综合风险预算",
                ),
                ParamSchema(
                    name="hk_eq_codes", label="港股组资产", type="text", default="",
                    description=(
                        "港股权益资产代码，逗号分隔；仅 V6 直投版需要，无港股时留空。"
                        "计入 C8 混合风险预算的权益项，不参与 A 股下限"
                    ),
                ),
                ParamSchema(
                    name="qdii_codes", label="海外权益 QDII 组", type="text", default="",
                    description="海外权益 QDII 资产代码，逗号分隔。QDII 额度内优先占用",
                ),
                ParamSchema(
                    name="qdii_usd_codes", label="美债 QDII 组", type="text", default="",
                    description="美债展期类资产代码，逗号分隔；无美债版留空。占用 QDII 剩余额度",
                ),
                ParamSchema(
                    name="comm_codes", label="商品组（不含黄金）", type="text", default="",
                    description="非黄金商品资产代码，逗号分隔。参与商品上限与综合风险预算（系数 2.5）",
                ),
                ParamSchema(
                    name="gold_codes", label="黄金组", type="text", default="",
                    description="黄金资产代码，逗号分隔。V5 口径下黄金独立成组、不受商品上限约束，仅进综合风险预算",
                ),
                # ━━━ 算法核心（core） ━━━
                ParamSchema(
                    name="select_count", label="选样数量", type="number", default=11,
                    min_value=1, max_value=50, step=1,
                    description="夏普动量排名后入选的资产只数（15 选 11 为 V5 基准）",
                ),
                ParamSchema(
                    name="qdii_cap", label="QDII 合计上限", type="number", default=0.075,
                    min_value=0.0, max_value=1.0, step=0.005,
                    description="权益 QDII + 美债 QDII 合计权重上限；0 = 不限制",
                ),
                ParamSchema(
                    name="comm_cap", label="商品合计上限", type="number", default=0.04,
                    min_value=0.0, max_value=1.0, step=0.005,
                    description="非黄金商品合计权重上限；0 = 不限制",
                ),
                ParamSchema(
                    name="risk_budget_cap", label="综合风险预算上限（C7·V5 口径）", type="number", default=0.20,
                    min_value=0.0, max_value=2.0, step=0.01,
                    description=(
                        "A股 + 黄金 + 2.5×商品 + 2.5×QDII 的上限；0 = 不启用（C7）。"
                        "仅 V5 FOF 口径使用；V6/V7 走 C8 混合风险预算，本项填 0"
                    ),
                ),
                ParamSchema(
                    name="mix_budget_cap", label="混合风险预算上限（C8·V6/V7 口径）", type="number", default=0.0,
                    min_value=0.0, max_value=2.0, step=0.01,
                    description=(
                        "权益(A股+港股)×w_eq + 黄金×w_gold + 商品×w_comm + QDII×w_qdii"
                        " 的上限，超出时非A债同比例缩减、缺口回填A债；0 = 不启用（C8）。"
                        "V6/V7 使用本项（V7：A股+黄金+商品+3.75×QDII ≤ 20%，3.75 见高级参数"
                        "「混合预算 QDII 系数」）；V5 走 C7 综合风险预算，本项填 0"
                    ),
                ),
                ParamSchema(
                    name="target_vol", label="目标波动率", type="number", default=0.02,
                    min_value=0.0, max_value=0.30, step=0.005,
                    description=(
                        "月度调仓的事前组合波动率目标；日度波控触发后按此值降仓；"
                        "0 = 不做波动率缩放，基础权重直接归一化（无波控档）"
                    ),
                ),
                # ━━━ 风控（core） ━━━
                ParamSchema(
                    name="enable_daily_vol_control", label="启用日度波动率风控",
                    type="boolean", default=True,
                    description="非月末信号日实现波动率超触发线时降仓（月度调仓优先，T+2 执行）",
                ),
                ParamSchema(
                    name="daily_vol_trigger", label="日度波动率触发线", type="number", default=0.04,
                    min_value=0.005, max_value=0.50, step=0.005,
                    description="实现波动率（多窗口取大）超过该年化阈值即触发降仓",
                    condition={"field": "enable_daily_vol_control", "value": True},
                ),
                # ━━━ 约束细节（advanced） ━━━
                ParamSchema(
                    name="aeq_floor_offset", label="A 股下限偏移", type="number", default=0.024,
                    min_value=0.0, max_value=0.5, step=0.001,
                    description="A 股下限 = MAX(该值 − QDII 合计, 0)；0 = 不设 A 股下限（C3）",
                    group="advanced",
                ),
                ParamSchema(
                    name="aq_floor", label="A 股+QDII 合计下限", type="number", default=0.024,
                    min_value=0.0, max_value=0.5, step=0.001,
                    description="C7 风险敞口缩减后 A股+QDII 权重合计的下限，差额由黄金与商品承担；0 = 不保护",
                    group="advanced",
                ),
                ParamSchema(
                    name="risk_budget_w_comm", label="风险预算商品系数", type="number", default=2.5,
                    min_value=0.0, max_value=10.0, step=0.1,
                    description="综合风险预算中非黄金商品的放大系数",
                    group="advanced",
                ),
                ParamSchema(
                    name="risk_budget_w_qdii", label="风险预算 QDII 系数", type="number", default=2.5,
                    min_value=0.0, max_value=10.0, step=0.1,
                    description="综合风险预算中 QDII 的放大系数",
                    group="advanced",
                ),
                ParamSchema(
                    name="mix_budget_w_eq", label="混合预算权益系数", type="number", default=1.0,
                    min_value=0.0, max_value=10.0, step=0.05,
                    description="C8 混合风险预算中权益（A股+港股）的放大系数",
                    group="advanced",
                ),
                ParamSchema(
                    name="mix_budget_w_gold", label="混合预算黄金系数", type="number", default=1.0,
                    min_value=0.0, max_value=10.0, step=0.05,
                    description="C8 混合风险预算中黄金的放大系数（黄金留在商品组时本项不生效）",
                    group="advanced",
                ),
                ParamSchema(
                    name="mix_budget_w_comm", label="混合预算商品系数", type="number", default=1.0,
                    min_value=0.0, max_value=10.0, step=0.05,
                    description="C8 混合风险预算中商品的放大系数（黄金在商品组内时一并计入）",
                    group="advanced",
                ),
                ParamSchema(
                    name="mix_budget_w_qdii", label="混合预算 QDII 系数", type="number", default=1.0,
                    min_value=0.0, max_value=10.0, step=0.05,
                    description="C8 混合风险预算中 QDII 的放大系数（V7 填 3.75）",
                    group="advanced",
                ),
                ParamSchema(
                    name="comm_cap_per", label="单商品权重上限", type="number", default=0.0,
                    min_value=0.0, max_value=1.0, step=0.005,
                    description="拆分版口径：组内每只商品各自的权重上限；0 = 不启用（启用时优先于商品合计上限）",
                    group="advanced",
                ),
                ParamSchema(
                    name="abond_floor", label="A 债下限", type="number", default=0.0,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="A 债合计权重下限；0 = 不设下限（V5 三版本均不设，C4）",
                    group="advanced",
                ),
                ParamSchema(
                    name="abond_cap", label="A 债上限", type="number", default=0.0,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="A 债合计权重上限；0 = 不限制（C5）",
                    group="advanced",
                ),
                ParamSchema(
                    name="abond_usd_cap", label="A 债+美债上限", type="number", default=0.0,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="A 债与美债 QDII 合计上限，先压美债再压 A 债；0 = 不限制（优先于 A 债上限）",
                    group="advanced",
                ),
                ParamSchema(
                    name="aeq_risk_cap", label="A 股三类风险合计上限", type="number", default=0.0,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="A股 ≤ 该值 − QDII − 商品（V4 兼容口径）；0 = 不启用（C6）",
                    group="advanced",
                ),
                ParamSchema(
                    name="enable_aeq_backfill", label="启用 A 股补选", type="boolean", default=True,
                    description=(
                        "选样后 A 股全部落选且 QDII 低于 A 股下限偏移时，用排名最高的 A 股"
                        "换出全部已选资产中排名最低的一项，保持选择数不变"
                    ),
                    group="advanced",
                ),
                # ━━━ 技术细节（advanced） ━━━
                ParamSchema(
                    name="vol_windows", label="波动率窗口", type="text", default="22,65,130",
                    description="资产/组合波动率估计窗口（逗号分隔），多窗口年化后取最大值",
                    group="advanced",
                ),
                ParamSchema(
                    name="sharp_windows", label="夏普动量窗口", type="text", default="22,65,260",
                    description="选样打分窗口（逗号分隔），各窗口 rank 求和",
                    group="advanced",
                ),
                ParamSchema(
                    name="min_history_days", label="最小样本量", type="number", default=260,
                    min_value=30, max_value=2000, step=10,
                    description="资产纳入选样与波动率计算所需的最小有效价格条数",
                    group="advanced",
                ),
                ParamSchema(
                    name="tie_break_window", label="并列决胜窗口", type="number", default=22,
                    min_value=5, max_value=120, step=1,
                    description="综合打分相同时，优先选择该窗口动量更高的资产",
                    group="advanced",
                ),
                ParamSchema(
                    name="annualization_factor", label="年化因子", type="number",
                    default=round(float(np.sqrt(260)), 10),
                    min_value=1.0, max_value=365.0, step=0.1,
                    description="波动率年化因子，默认 √260（工作日日历口径）",
                    group="advanced",
                ),
                ParamSchema(
                    name="strict_validate", label="严格校验", type="boolean", default=True,
                    description="开启后：池内资产未归组、权重末检不通过均直接报错，不静默裁剪",
                    group="advanced",
                ),
                ParamSchema(
                    name="require_full_invest", label="强制满仓", type="boolean", default=True,
                    description=(
                        "开启后权重末检要求合计恰为 100%；关闭后允许因 A 债未入选无法回填"
                        "而留现金（V6/V7 口径）"
                    ),
                    group="advanced",
                ),
                # ━━━ 模型级通用执行参数（调度/数据源/引擎层消费） ━━━
                *model_level_param_group(),
            ],
        )

    def get_execution_schedule(self) -> Optional[dict]:
        """月末信号、T+2 执行；日度波控按原型规则裁决.

        不声明 ``selection_start_date`` / ``skip_dates`` 等日期常量：调仓起点
        由回测区间与价格矩阵决定，什么日期范围的数据进来都能跑。

        ``vol_reset_policy`` 是日度波控的唯一声明位：回测引擎直接读取；
        监控侧按 ``schedule.resolve_vol_reset_policy`` 的默认值执行，两侧同一套判定键。
        规则：同一执行日月度优先、信号日本身是常规调仓执行日不记日度信号、
        信号日到执行日之间存在常规调仓执行日时不记日度信号。
        """
        return {
            "rebalance_freq": "month_end",
            "execution_delay": 2,
            "vol_reset_policy": {
                "monthly_priority": True,
                "skip_on_rebalance_day": True,
                "skip_interval_conflict": True,
            },
        }

    def has_native_vol_control(self) -> bool:
        """日度波动率风控写在包内，放行 Pipeline 代理（composition.controller 为 None）."""
        return True

    @classmethod
    def get_data_contract(cls):
        """声明数据契约：运行前门禁据此校验，不满足即拒绝运行.

        只声明**算法逻辑必需**的约束（分组必须覆盖全池、资产大类必须对得上、
        组上限与风险预算必须可行、价格必须为正且无拼接跳变）。
        **不约束日期与数据规模**：``min_assets`` / ``min_history_days`` /
        ``require_continuous`` / ``calendar`` 均不声明，底层资产可自由命名与替换、
        任意日期范围与日历口径的数据都能跑：

        - 选样最小样本量由模型参数 ``min_history_days`` 控制（前端可调），
          选不出资产时 :meth:`allocate` 报明确错误并给出修复建议，不用契约卡死；
        - 日历口径由模型参数 ``calendar_source`` 控制（前端可调），策略不代用户声明。
        """
        from app.backtesting.data_contract import DataContract, GroupSpec

        return DataContract(
            max_single_day_jump=0.25,
            group_params={
                "a_bond_codes": GroupSpec(required=True, cover_pool=True),
                "a_eq_codes": GroupSpec(required=True, cover_pool=True),
                # 无港股版（V5/V7）该组为空，故非必填；仍参与全池覆盖检查
                "hk_eq_codes": GroupSpec(required=False, cover_pool=True),
                # 无 QDII / 无商品 / 黄金归商品组的版本（V6/V7）对应分组为空
                "qdii_codes": GroupSpec(required=False, cover_pool=True),
                "qdii_usd_codes": GroupSpec(required=False, cover_pool=True),
                "comm_codes": GroupSpec(required=False, cover_pool=True),
                "gold_codes": GroupSpec(required=False, cover_pool=True),
            },
            expected_asset_class={
                "a_bond_codes": "固收",
                "a_eq_codes": "权益",
                "hk_eq_codes": "权益",
                "qdii_codes": "权益",
                "qdii_usd_codes": "固收",
                "comm_codes": "商品",
                "gold_codes": "商品",
            },
            custom_checks=("group_caps_feasible",),
        )

    # ------------------------------------------------------------------
    # allocate 主流程
    # ------------------------------------------------------------------

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """一次调仓的全部计算：选样 → 赋权 → 波控缩放 → 约束投影 → 末检."""
        if prices is None or prices.empty:
            raise ValueError("[nous_low_vol] 价格矩阵为空，无法计算权重")

        pool = list(prices.columns)
        groups = self._resolve_groups(params, pool)
        cons = self._build_constraints(params)
        date_idx = len(prices) - 1
        label = str(prices.index[-1].date()) if len(prices) else "unknown"

        selected, ranked, swap_note = self._select(prices, params)
        if not selected:
            raise ValueError(
                f"[nous_low_vol] {label} 未选出任何资产（select_count="
                f"{params.get('select_count')}，min_history_days="
                f"{params.get('min_history_days', 260)}）。"
                "请检查资产池历史长度或降低最小样本量要求"
            )

        w = self._base_weights(prices, date_idx, selected, params)
        if float(w.sum()) <= 0:
            raise ValueError(
                f"[nous_low_vol] {label} 基础权重合计为 0（选中资产波动率全部不可估）。"
                "请检查价格数据完整性"
            )
        w = self._vol_scale(prices, date_idx, w, params)
        w, audit = self._apply_constraints(w, groups, cons)
        audit["selected_count"] = len(selected)
        audit["selected"] = list(selected)
        audit["swap_note"] = swap_note
        audit["ranked"] = list(ranked)
        audit["signal_date"] = label
        self._audit(audit, groups, cons)
        self._final_check(w, groups, cons, label)
        return w.reindex(pool).fillna(0.0)

    # ------------------------------------------------------------------
    # 分步实现（每步可单测）
    # ------------------------------------------------------------------

    def _resolve_groups(
        self, params: Dict[str, Any], pool: Sequence[str]
    ) -> Dict[str, List[str]]:
        """解析 7 个分组参数；``strict_validate`` 下池内有资产未归组即报错."""
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
                    f"[nous_low_vol] 分组参数含资产池之外的代码：{detail}。"
                    "分组参数必须与模型 asset_codes 同步维护"
                )
            _log.warning("[nous_low_vol] 分组参数含池外代码（已忽略）：%s", detail)

        if strict:
            covered = {c for members in groups.values() for c in members}
            missing = [c for c in pool if c not in covered]
            if missing:
                raise ValueError(
                    f"[nous_low_vol] 资产池内 {len(missing)} 只资产未归入任何分组：{missing}。"
                    "请补齐 a_bond_codes / a_eq_codes / hk_eq_codes / qdii_codes / "
                    "qdii_usd_codes / comm_codes / gold_codes，或关闭 strict_validate"
                )
            duplicated: Dict[str, List[str]] = {}
            seen: Dict[str, str] = {}
            for param_name, group_key in GROUP_PARAM_TO_KEY.items():
                for code in groups[group_key]:
                    if code in seen:
                        duplicated.setdefault(seen[code], []).append(param_name)
                    seen[code] = param_name
            if duplicated:
                raise ValueError(
                    f"[nous_low_vol] 资产重复归组：{duplicated}。每只资产只能属于一个分组"
                )
        return groups

    def _build_constraints(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """把前端参数翻译成约束规格（0 / 空 = 不启用该约束）."""
        aeq_offset = optional_float(params.get("aeq_floor_offset"))
        mix_cap = optional_float(params.get("mix_budget_cap"))
        return {
            "qdii_cap": optional_float(params.get("qdii_cap")),
            "comm_cap": optional_float(params.get("comm_cap")),
            "comm_cap_per": optional_float(params.get("comm_cap_per")),
            "risk_cap": optional_float(params.get("aeq_risk_cap")),
            "risk_budget": optional_float(params.get("risk_budget_cap")),
            "mix_budget": (
                {
                    "cap": mix_cap,
                    "w_eq": float(params.get("mix_budget_w_eq", 1.0) or 1.0),
                    "w_gold": float(params.get("mix_budget_w_gold", 1.0) or 1.0),
                    "w_comm": float(params.get("mix_budget_w_comm", 1.0) or 1.0),
                    "w_qdii": float(params.get("mix_budget_w_qdii", 1.0) or 1.0),
                }
                if mix_cap is not None else None
            ),
            "aq_floor": optional_float(params.get("aq_floor")),
            "aeq_floor_spec": ("qdii_offset", aeq_offset) if aeq_offset is not None else None,
            "abond_floor": optional_float(params.get("abond_floor")),
            "abond_cap": optional_float(params.get("abond_cap")),
            "abond_usd_cap": optional_float(params.get("abond_usd_cap")),
            "risk_budget_w_comm": float(params.get("risk_budget_w_comm", 2.5) or 2.5),
            "risk_budget_w_qdii": float(params.get("risk_budget_w_qdii", 2.5) or 2.5),
            "require_full_invest": bool(params.get("require_full_invest", True)),
            "strict_validate": bool(params.get("strict_validate", True)),
        }

    def _select(
        self, prices: pd.DataFrame, params: Dict[str, Any]
    ) -> Tuple[List[str], List[str], str]:
        """选样：复用库内 SharpeSelector（禁止复制算法），再做 A 股补选.

        Returns:
            (最终入选列表, 全池排名（优在前）, 补选说明)
        """
        from app.selection import create_selector

        select_count = int(params.get("select_count", 11))
        if select_count <= 0:
            raise ValueError(f"[nous_low_vol] select_count 必须大于 0，当前值：{select_count}")

        selector = create_selector("sharpe")
        result = selector.select(
            prices,
            select_count,
            min_history_days=int(params.get("min_history_days", 260)),
            sharp_windows=params.get("sharp_windows", "22,65,260"),
            tie_break_window=int(params.get("tie_break_window", 22)),
        )
        ranking = getattr(result, "ranking", None)
        ranked: List[str] = []
        if ranking is not None and not ranking.empty and "Asset" in ranking.columns:
            ranked = [str(a) for a in ranking["Asset"].tolist()]
        chosen = [str(a) for a in (result.selected_assets or [])]
        if not ranked:
            ranked = list(chosen)

        if not params.get("enable_aeq_backfill", True):
            return chosen, ranked, ""
        return self._backfill_a_eq(prices, params, chosen, ranked)

    def _backfill_a_eq(
        self,
        prices: pd.DataFrame,
        params: Dict[str, Any],
        chosen: List[str],
        ranked: List[str],
    ) -> Tuple[List[str], List[str], str]:
        """A 股补选：QDII 权重低于 A 股下限偏移且 A 股全部落选时换入最优 A 股.

        换出对象为「全部已选资产中排名最低」的一项（不分组排除），保持选择数不变。
        """
        from app.backtesting.data_contract import parse_asset_codes

        offset = optional_float(params.get("aeq_floor_offset"))
        if offset is None:
            return chosen, ranked, ""
        pool = list(prices.columns)
        aeq_pool = [c for c in parse_asset_codes(params.get("a_eq_codes")) if c in set(pool)]
        chosen_set = set(chosen)
        if not aeq_pool or any(a in chosen_set for a in aeq_pool):
            return chosen, ranked, ""

        groups = self._resolve_groups(params, pool)
        cons = self._build_constraints(params)
        date_idx = len(prices) - 1
        qdii_w = self._pre_floor_qdii(prices, date_idx, chosen, groups, cons, params)
        if qdii_w >= offset - TOL:
            return chosen, ranked, ""

        cands = [a for a in ranked if a in set(aeq_pool) and a not in chosen_set]
        if not cands:
            raise ValueError(
                f"[nous_low_vol] {prices.index[date_idx].date()} 需补选 A 股但池内无可选 A 股"
                f"（a_eq_codes={aeq_pool}）。请检查 A 股组资产的历史长度"
            )
        victims = [a for a in reversed(ranked) if a in chosen_set]
        if not victims:
            raise ValueError(
                f"[nous_low_vol] {prices.index[date_idx].date()} 需补选 A 股但入选集无可剔资产"
            )
        pick, drop = cands[0], victims[0]
        chosen_set.discard(drop)
        chosen_set.add(pick)
        note = f"QDII {qdii_w:.2%} < {offset:.2%}，补 A 股：{drop} → {pick}"
        return [a for a in pool if a in chosen_set], ranked, note

    def _pre_floor_qdii(
        self,
        prices: pd.DataFrame,
        date_idx: int,
        selected: Sequence[str],
        groups: Dict[str, List[str]],
        cons: Dict[str, Any],
        params: Dict[str, Any],
    ) -> float:
        """C0→C2→C1 后的 QDII 合计权重（补选判定用，不含抬底/预算/回填）."""
        w = self._raw_inverse_vol_weights(prices, date_idx, selected, params)
        if float(w.sum()) <= 0:
            return 0.0
        w = w / float(w.sum())
        comm_cap_per = cons.get("comm_cap_per")
        comm_cap = cons.get("comm_cap")
        if comm_cap_per is not None:
            cap_group_per_asset(w, groups.get("COMM", []), comm_cap_per)
        elif comm_cap is not None:
            cap_group(w, groups.get("COMM", []), comm_cap)
        qdii_cap = cons.get("qdii_cap")
        if qdii_cap is not None:
            qdii_priority(w, groups.get("QDII3", []), groups.get("QDII_USD", []), qdii_cap)
        qdii_all = [a for a in list(groups.get("QDII3", [])) + list(groups.get("QDII_USD", []))
                    if a in w.index]
        return float(w.loc[qdii_all].sum()) if qdii_all else 0.0

    def _raw_inverse_vol_weights(
        self,
        prices: pd.DataFrame,
        date_idx: int,
        selected: Sequence[str],
        params: Dict[str, Any],
    ) -> pd.Series:
        """未归一化的 (1/N)×(1/σ) 原始权重（σ 不可估的资产权重为 0）."""
        windows = parse_int_list(params.get("vol_windows"), _DEFAULT_VOL_WINDOWS)
        annualize = float(params.get("annualization_factor") or _DEFAULT_ANN_FACTOR)
        vols = asset_volatility(prices, date_idx, windows, annualize)
        n = max(len(selected), 1)
        w = pd.Series(0.0, index=list(prices.columns))
        for asset in selected:
            if asset not in w.index:
                continue
            sigma = vols.get(asset, np.nan)
            if sigma is not None and not np.isnan(sigma) and sigma > 0:
                w[asset] = (1.0 / n) * (1.0 / float(sigma))
        return w

    def _base_weights(
        self,
        prices: pd.DataFrame,
        date_idx: int,
        selected: Sequence[str],
        params: Dict[str, Any],
    ) -> pd.Series:
        """基础权重：(1/N)×(1/σ)，σ = 多窗口年化波动率最大值."""
        return self._raw_inverse_vol_weights(prices, date_idx, selected, params)

    def _vol_scale(
        self,
        prices: pd.DataFrame,
        date_idx: int,
        w: pd.Series,
        params: Dict[str, Any],
    ) -> pd.Series:
        """C0 + 目标波动率档缩放：缩放到事前组合波动率 = target_vol，再 Σw = min(Σw, 1)."""
        target_vol = optional_float(params.get("target_vol"))
        if target_vol is None:
            return w / float(w.sum())
        windows = parse_int_list(params.get("vol_windows"), _DEFAULT_VOL_WINDOWS)
        annualize = float(params.get("annualization_factor") or _DEFAULT_ANN_FACTOR)
        port_vol = portfolio_volatility(prices, w, date_idx, windows, annualize)
        scale = target_vol / port_vol if port_vol > 0 else 1.0
        scaled = w * scale
        if float(scaled.sum()) > 1:
            scaled = scaled / float(scaled.sum())
        return scaled

    def _apply_constraints(
        self,
        w: pd.Series,
        groups: Dict[str, List[str]],
        cons: Dict[str, Any],
    ) -> Tuple[pd.Series, Dict[str, Any]]:
        """顺序约束投影，返回 (权重, 审计)."""
        return apply_constraints(w, groups, cons)

    def _audit(
        self,
        audit: Dict[str, Any],
        groups: Dict[str, List[str]],
        cons: Dict[str, Any],
    ) -> Dict[str, Any]:
        """记录本期审计并累计跨期计数（供 compute_monitoring_metrics 暴露到前端）."""
        state = self._ensure_state()
        state["last_audit"] = audit
        state["rebalance_count"] = int(state.get("rebalance_count", 0)) + 1
        counts: Dict[str, int] = state.setdefault("trigger_counts", {})
        for name in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"):
            status = audit.get(name)
            if status in ("binding", "raised", "raised+compressed", "raised_no_comp",
                          "a_ge_C", "usd_cut", "bond_cut"):
                counts[name] = int(counts.get(name, 0)) + 1
        if audit.get("C7_aq_guard"):
            counts["C7_aq_guard"] = int(counts.get("C7_aq_guard", 0)) + 1
        if audit.get("现金回填", 0.0) > TOL:
            counts["cash_backfill"] = int(counts.get("cash_backfill", 0)) + 1
        if audit.get("剩余回填", 0.0) > TOL:
            counts["residual_backfill"] = int(counts.get("residual_backfill", 0)) + 1
        if audit.get("swap_note"):
            counts["aeq_backfill"] = int(counts.get("aeq_backfill", 0)) + 1
        warnings = audit.get("warnings") or []
        if warnings:
            counts["warning_rebalances"] = int(counts.get("warning_rebalances", 0)) + 1
            state["last_warnings"] = list(warnings)
        return audit

    def _final_check(
        self,
        w: pd.Series,
        groups: Dict[str, List[str]],
        cons: Dict[str, Any],
        label: str,
    ) -> None:
        """归一化与越界末检；``strict_validate`` 下报错，不静默裁剪."""
        if (w < -TOL).any():
            w.clip(lower=0, inplace=True)
        params_strict = bool(cons.get("strict_validate", True))
        require_full = bool(cons.get("require_full_invest", True))
        total = float(w.sum())
        if total <= TOL:
            raise ValueError(f"[nous_low_vol] {label} 最终权重合计为 0，约束投影后无可配置权重")
        # 满仓口径：约束投影 + 回填后合计应恰为 1；数值漂移在容差内就地归一。
        # require_full_invest=False 时允许因 A 债未入选无法回填而留现金（V6/V7）
        if total > 1.0 + 1e-9:
            if total <= 1.0 + 1e-6 or not params_strict:
                w *= 1.0 / total
        elif require_full and abs(total - 1.0) > 1e-9:
            if abs(total - 1.0) <= 1e-6 or not params_strict:
                w *= 1.0 / total
        if params_strict:
            validate_final_weights(w, groups, cons, label)

    # ------------------------------------------------------------------
    # 包内日度波动率风控
    # ------------------------------------------------------------------

    def check_volatility_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> Tuple[bool, Optional[float]]:
        """实现波动率（多窗口取大）> 触发线时报触发.

        本方法只回答「是否触发 + 触发时实现波动率」；非信号日、月度优先、
        区间冲突跳过由执行层按调度声明的 ``vol_reset_policy`` 统一裁决
        （回测 ``BacktestEngine`` 读策略声明，监控 ``daily_stepper`` 读同一套判定键）。
        """
        if not params.get("enable_daily_vol_control", True):
            return False, None
        trigger = optional_float(params.get("daily_vol_trigger"))
        if trigger is None:
            return False, None
        if current_weights is None or prices is None or prices.empty:
            return False, None
        vol = self._realized_vol(current_weights, prices, params)
        if vol is None or vol <= 0:
            return False, None
        return (vol > trigger, float(vol))

    def compute_volatility_reset_weights(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> pd.Series:
        """触发后目标权重 = 当前权重 × target_vol / 信号日实现波动率."""
        if current_weights is None:
            return pd.Series(dtype=float)
        target_vol = optional_float(params.get("target_vol"))
        if target_vol is None:
            return current_weights
        vol_trigger = params.get("_vol_trigger") or params.get("vol_trigger")
        try:
            vol = float(vol_trigger) if vol_trigger is not None else None
        except (TypeError, ValueError):
            vol = None
        if vol is None or vol <= 0:
            vol = self._realized_vol(current_weights, prices, params)
        if not vol or vol <= 0:
            return current_weights
        return current_weights * (target_vol / vol)

    def _realized_vol(
        self, current_weights: pd.Series, prices: pd.DataFrame, params: Dict[str, Any]
    ) -> Optional[float]:
        """当前权重的实现波动率（多窗口年化取大）；权重与价格无交集时返回 None."""
        if prices is None or prices.empty:
            return None
        weights = current_weights.copy()
        weights.index = [str(i) for i in weights.index]
        col_map = {str(c): c for c in prices.columns}
        common = [col_map[k] for k in weights.index if k in col_map and float(weights[k]) > 0]
        if not common:
            return None
        aligned = weights.reindex([str(c) for c in common]).fillna(0.0)
        aligned.index = [col_map[k] for k in aligned.index]
        windows = parse_int_list(params.get("vol_windows"), _DEFAULT_VOL_WINDOWS)
        annualize = float(params.get("annualization_factor") or _DEFAULT_ANN_FACTOR)
        vol = portfolio_volatility(
            prices[common], aligned, len(prices) - 1, windows, annualize
        )
        return float(vol) if vol else None

    # ------------------------------------------------------------------
    # 自定义契约检查（DataContract.custom_checks）
    # ------------------------------------------------------------------

    def _check_group_caps_feasible(
        self, prices: Optional[pd.DataFrame], params: Dict[str, Any]
    ) -> Optional[str]:
        """校验上限/下限/预算三者可同时满足；返回 None 表示通过，否则返回原因.

        运行前门禁调用（不依赖价格数据），拦住「QDII 上限 × 预算系数已超预算」
        这类配置错误，避免调仓日才在权重末检抛错。
        """
        cons = self._build_constraints(params)
        problems: List[str] = []
        budget = cons.get("risk_budget")
        w_comm = cons["risk_budget_w_comm"]
        w_qdii = cons["risk_budget_w_qdii"]
        if budget is not None:
            qdii_cap = cons.get("qdii_cap")
            if qdii_cap is not None and qdii_cap * w_qdii > budget + TOL:
                problems.append(
                    f"QDII 上限 {qdii_cap:.2%} × 预算系数 {w_qdii} = "
                    f"{qdii_cap * w_qdii:.2%} 已超综合风险预算 {budget:.2%}"
                )
            comm_cap = cons.get("comm_cap")
            if comm_cap is not None and comm_cap * w_comm > budget + TOL:
                problems.append(
                    f"商品上限 {comm_cap:.2%} × 预算系数 {w_comm} = "
                    f"{comm_cap * w_comm:.2%} 已超综合风险预算 {budget:.2%}"
                )
            aq_floor = cons.get("aq_floor")
            if aq_floor is not None and aq_floor > budget + TOL:
                problems.append(
                    f"A股+QDII 下限 {aq_floor:.2%} 高于综合风险预算 {budget:.2%}，"
                    "缩减后无法同时满足"
                )
        mix = cons.get("mix_budget")
        if mix is not None:
            cap8 = float(mix["cap"])
            qdii_cap = cons.get("qdii_cap")
            if qdii_cap is not None and qdii_cap * float(mix["w_qdii"]) > cap8 + TOL:
                problems.append(
                    f"QDII 上限 {qdii_cap:.2%} × C8 系数 {mix['w_qdii']} = "
                    f"{qdii_cap * float(mix['w_qdii']):.2%} 已超混合风险预算 {cap8:.2%}"
                )
            comm_cap = cons.get("comm_cap")
            if comm_cap is not None and comm_cap * float(mix["w_comm"]) > cap8 + TOL:
                problems.append(
                    f"商品上限 {comm_cap:.2%} × C8 系数 {mix['w_comm']} = "
                    f"{comm_cap * float(mix['w_comm']):.2%} 已超混合风险预算 {cap8:.2%}"
                )
        aeq_spec = cons.get("aeq_floor_spec")
        aq_floor = cons.get("aq_floor")
        if aeq_spec is not None and aq_floor is not None:
            if aeq_spec[1] > aq_floor + TOL:
                problems.append(
                    f"A 股下限偏移 {aeq_spec[1]:.2%} 高于 A股+QDII 合计下限 "
                    f"{aq_floor:.2%}，QDII 为 0 时两者冲突"
                )
        select_count = int(params.get("select_count", 11) or 0)
        if select_count <= 0:
            problems.append(f"选样数量 {select_count} 非法，必须为正整数")
        if problems:
            return "[nous_low_vol] 约束配置不可行：" + "；".join(problems)
        return None

    # ------------------------------------------------------------------
    # 监控指标
    # ------------------------------------------------------------------

    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> Dict[str, Any]:
        """暴露约束触发次数、补选次数、风险敞口与距触发阈值（前端监控页指标区）."""
        state = self._ensure_state()
        audit: Dict[str, Any] = state.get("last_audit") or {}
        metrics: Dict[str, Any] = {
            "rebalance_count": int(state.get("rebalance_count", 0)),
            "constraint_trigger_counts": dict(state.get("trigger_counts") or {}),
            "last_signal_date": audit.get("signal_date"),
            "last_selected_count": audit.get("selected_count"),
            "last_aeq_backfill": audit.get("swap_note") or "",
            "last_warnings": list(state.get("last_warnings") or []),
            "cash_backfill": audit.get("现金回填", 0.0),
            "residual_backfill": audit.get("剩余回填", 0.0),
        }
        for key in ("post_QDII", "post_COMM", "post_GOLD", "post_AEQ", "post_EQUITY",
                    "post_AQ", "post_ABOND", "post_RISK_BUDGET", "post_MIX", "post_LEV",
                    "cash", "aeq_floor_used"):
            if key in audit:
                metrics[key] = audit[key]

        vol = self._realized_vol(current_weights, prices, params)
        if vol is not None:
            metrics["realized_volatility"] = vol
            trigger = optional_float(params.get("daily_vol_trigger"))
            if trigger is not None:
                metrics["vol_trigger_threshold"] = trigger
                metrics["vol_trigger_distance"] = trigger - vol
        target_vol = optional_float(params.get("target_vol"))
        if target_vol is not None:
            metrics["target_vol"] = target_vol
        return metrics

    # ------------------------------------------------------------------
    # 跨期状态（不用模块级变量）
    # ------------------------------------------------------------------

    def _ensure_state(self) -> Dict[str, Any]:
        state = getattr(self, "_state", None)
        if not isinstance(state, dict):
            state = {}
            self._state = state
        return state
