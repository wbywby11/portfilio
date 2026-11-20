"""目标波动率预算策略 (Target Volatility Budget, TVB)

统一的波动率定标模型，核心公式：w_i = b_i × σ_target / σ_realized

通过 budget_source 参数切换三种预算来源：
  - tag_based:         按上游 _asset_tags（动量/反转槽位）动态等分预算
  - selection_equal:   选中资产等权预算 1/N
  - inverse_variance:  反方差预算 1/σ²

三重约束缩放：组合波动率 + 杠杆 + 单资产权重上限。

整合自以下三个历史策略：
  - risk_budget_target_vol（tag_based）
  - sharpe_risk_budget（selection_equal）
  - momentum_risk_parity（inverse_variance）
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from typing import Any, Dict

from app.formula.returns import compute_simple_returns
from app.formula.rolling_volatility import (
    compute_asset_rolling_volatility,
    compute_portfolio_volatility,
)
from app.allocation.models.base import BaseStrategyModel
from app.allocation.runtime_params import resolve_weight_caps

_log = logging.getLogger(__name__)

ANNUALIZE_FACTOR = np.sqrt(260)


# ---------------------------------------------------------------------------
# 辅助：与原型 step2 完全一致的波动率计算
# ---------------------------------------------------------------------------

def _pct_change(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change(fill_method=None)


def _calc_asset_volatility_max(
    prices: pd.DataFrame,
    date_idx: int,
    windows=(22, 65, 130),
) -> pd.Series:
    """资产波动率：取多窗口年化 vol 的最大值（与 sharpe_risk_budget 原型一致）。"""
    returns = _pct_change(prices)
    vols = {}
    for asset in prices.columns:
        asset_vols = []
        for w in windows:
            if date_idx >= w:
                ret_window = returns[asset].iloc[date_idx - w + 1: date_idx + 1]
                vol = ret_window.std() * ANNUALIZE_FACTOR
                if not np.isnan(vol):
                    asset_vols.append(vol)
        vols[asset] = max(asset_vols) if asset_vols else np.nan
    return pd.Series(vols)


def _calc_portfolio_volatility_max(
    prices: pd.DataFrame,
    weights: pd.Series,
    date_idx: int,
    windows=(22, 65, 130),
) -> float:
    """组合波动率：取多窗口年化 vol 的最大值。"""
    returns = _pct_change(prices)
    valid_assets = [a for a in weights.index if weights[a] > 0 and a in returns.columns]
    if not valid_assets:
        return 0.0
    port_vols = []
    for w in windows:
        if date_idx >= w:
            port_returns = pd.Series(0.0, index=returns.index)
            for asset in valid_assets:
                port_returns += weights[asset] * returns[asset].fillna(0)
            ret_window = port_returns.iloc[date_idx - w + 1: date_idx + 1]
            vol = ret_window.std() * ANNUALIZE_FACTOR
            if not np.isnan(vol):
                port_vols.append(vol)
    return max(port_vols) if port_vols else 0.0




class VolScaledBudgetStrategy(BaseStrategyModel):
    """目标波动率预算策略 (TVB)。

    统一 w = b × σ_target / σ 公式，通过 budget_source 切换预算来源。
    """

    @staticmethod
    def _parse_json_or_dict(value, default=None):
        if default is None:
            default = {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                import json
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else default
            except Exception:
                return default
        return default

    @staticmethod
    def _resolve_vol_windows(params):
        """从参数中解析波动率窗口列表.

        优先读取三个独立字段 vol_window_short/medium/long（新版前端），
        回退到旧版 vol_windows 逗号分隔字符串/列表格式，均失败时默认 [22, 65, 130]。
        """
        default = [22, 65, 130]
        short = params.get("vol_window_short")
        medium = params.get("vol_window_medium")
        long_ = params.get("vol_window_long")
        if short is not None or medium is not None or long_ is not None:
            try:
                raw = [int(x) for x in [short or 22, medium or 65, long_ or 130]]
                return sorted(set(raw))
            except (ValueError, TypeError):
                return default
        # 回退：旧 vol_windows 字符串/列表
        value = params.get("vol_windows")
        if value is None:
            return default
        if isinstance(value, str):
            try:
                parsed = [int(w.strip()) for w in value.split(",") if w.strip()]
            except ValueError:
                return default
            return parsed or default
        if isinstance(value, (list, tuple)):
            try:
                parsed = [int(w) for w in value]
            except (ValueError, TypeError):
                return default
            return parsed or default
        return default

    @classmethod
    def get_param_schema(cls):
        from app.allocation.models.param_schema import (
            StrategyParamSchema, ParamSchema, vol_targeting_param_group,
            model_level_param_group,
        )

        return StrategyParamSchema(
            strategy_type="vol_scaled_budget",
            display_name="目标波动率预算",
            description=(
                "闭式波动率定标 w = b × σ_target / σ_asset，"
                "支持标签等分 / 选中资产等权 / 反方差三种预算源，"
                "组合波动率 + 杠杆 + 资产权重三重约束缩放"
            ),
            composition={
                "selector": None,
                "allocator": "vol_scaled_budget",
                "controller": "rolling_vol",
                "schedule": {"rebalance_freq": "month_end", "execution_delay": 2},
            },
            internal_leverage=True,
            # 杠杆策略：w = b × σ_target / σ 的权重和可 >1，快照需用目标权重展示
            snapshot_weight_source="target",
            params=[
                # ━━━ 核心配置 ━━━
                ParamSchema(
                    name="budget_source",
                    label="风险预算来源",
                    type="select",
                    default="tag_based",
                    options=[
                        ("tag_based", "标签等分预算（动量/反转槽位均分）"),
                        ("selection_equal", "选中资产等权预算（1/N）"),
                        ("inverse_variance", "反方差预算（1/σ²）"),
                    ],
                    description="风险预算 b 的计算方式",
                ),
                ParamSchema(
                    name="target_vol",
                    label="目标波动率",
                    type="number",
                    default=0.05,
                    min_value=0.005,
                    max_value=0.50,
                    step=0.005,
                    description="组合年化目标波动率 σ_target",
                ),
                ParamSchema(
                    name="max_total_leverage",
                    label="最大杠杆",
                    type="number",
                    default=4.0,
                    min_value=1.0,
                    max_value=10.0,
                    step=0.5,
                    description="组合权重绝对值之和的上限",
                ),
                ParamSchema(
                    name="vol_window_short",
                    label="短期窗口",
                    type="number",
                    default=22,
                    min_value=5,
                    max_value=60,
                    step=1,
                    description="短期波动率估计窗口（交易日）",
                ),
                ParamSchema(
                    name="vol_window_medium",
                    label="中期窗口",
                    type="number",
                    default=65,
                    min_value=20,
                    max_value=130,
                    step=5,
                    description="中期波动率估计窗口（交易日）",
                ),
                ParamSchema(
                    name="vol_window_long",
                    label="长期窗口",
                    type="number",
                    default=130,
                    min_value=60,
                    max_value=260,
                    step=10,
                    description="长期波动率估计窗口（交易日），多窗口取最大值作为 σ_asset",
                ),
                ParamSchema(
                    name="weight_caps",
                    label="资产权重约束",
                    type="max_weight_dict",
                    default={},
                    description="为入围资产设置单资产权重上限，超出截断。留空=不限制",
                ),
                # ━━━ 反方差模式专属 ━━━
                ParamSchema(
                    name="vol_window_inv_var",
                    label="反方差估计窗口",
                    type="number",
                    default=60,
                    min_value=10,
                    max_value=252,
                    step=5,
                    description="1/σ² 的滚动估计窗口（交易日）",
                    condition={"field": "budget_source", "value": "inverse_variance"},
                ),
                ParamSchema(
                    name="vol_method_inv_var",
                    label="反方差波动率方法",
                    type="select",
                    default="rolling",
                    options=[
                        ("rolling", "滚动标准差"),
                        ("ewma", "EWMA 指数加权"),
                    ],
                    description="1/σ² 的波动率估计方法；ewma 口径 span=窗口、min_periods=窗口一半（对齐 GMAP 原型）",
                    condition={"field": "budget_source", "value": "inverse_variance"},
                ),
                ParamSchema(
                    name="single_cap",
                    label="单品种权重上限",
                    type="number",
                    default=1.0,
                    min_value=0.05,
                    max_value=1.0,
                    step=0.05,
                    description="反方差权重逐品种截断上限，截断后重新归一化；1.0=不截断（GMAP 场景配 0.30）",
                    condition={"field": "budget_source", "value": "inverse_variance"},
                ),
                # ━━━ 数据与风控（高级参数） ━━━
                ParamSchema(
                    name="min_history_days",
                    label="最小样本量",
                    type="number",
                    default=260,
                    min_value=30,
                    max_value=1000,
                    step=10,
                    description="资产纳入计算所需的最小交易日数",
                    group="advanced",
                ),
                ParamSchema(
                    name="lookback_days",
                    label="回看期",
                    type="number",
                    default=260,
                    min_value=30,
                    max_value=1000,
                    step=10,
                    description="波动率计算使用的历史数据长度（交易日）",
                    group="advanced",
                ),
                ParamSchema(
                    name="enable_vol_reset",
                    label="波动率重置",
                    type="boolean",
                    default=True,
                    description="组合波动率突破阈值时触发紧急降杠杆",
                    group="advanced",
                ),
                ParamSchema(
                    name="vol_reset_threshold",
                    label="重置阈值",
                    type="number",
                    default=0.06,
                    min_value=0.01,
                    max_value=0.20,
                    step=0.005,
                    description="触发波动率重置的年化阈值",
                    condition={"field": "enable_vol_reset", "value": True},
                    group="advanced",
                ),
                # ━━━ 波动率定标（引擎收益层，vol_targeting_enabled 触发） ━━━
                *vol_targeting_param_group(),
                # ━━━ 模型级通用执行参数（调度/数据源/引擎层消费） ━━━
                *model_level_param_group(),
            ],
        )

    def get_execution_schedule(self):
        return {
            "rebalance_freq": "month_end",
            "execution_delay": 2,
            "skip_dates": {"2015-01-01", "2015-01-02", "2015-01-05"},
            "selection_start_date": "2014-01-31",
        }

    # ------------------------------------------------------------------
    # allocate 入口
    # ------------------------------------------------------------------

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """根据 budget_source 分发到三种预算模式，统一波动率定标。"""
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        budget_source = params.get("budget_source", "tag_based")

        if budget_source == "inverse_variance":
            return self._allocate_inverse_variance(prices, **params)
        elif budget_source == "selection_equal":
            return self._allocate_selection_equal(prices, **params)
        else:
            return self._allocate_tag_based(prices, **params)

    # ------------------------------------------------------------------
    # tag_based: 原 risk_budget_target_vol 逻辑
    # ------------------------------------------------------------------

    def _allocate_tag_based(self, prices: pd.DataFrame, **params) -> pd.Series:
        """标签差异化预算（动态等分）。

        每个选择槽位预算 = 1 / (n_momentum + n_reversal)。
        - 仅动量选中 → 1 个槽位预算
        - 仅反转选中 → 1 个槽位预算
        - 两者都选中 → 2 个槽位预算（叠加）
        """
        target_vol = float(params.get("target_vol", 0.05))
        max_total_leverage = float(params.get("max_total_leverage", 4.0))
        min_history_days = int(params.get("min_history_days", 260))
        lookback_days = int(params.get("lookback_days", 260))
        vol_windows = self._resolve_vol_windows(params)

        weight_caps = resolve_weight_caps(params)
        # 单资产权重上限默认 1.0（不限制），与原型一致；仅用户显式配置的 cap 才生效
        default_max_weight = 1.0
        asset_tags = self._parse_json_or_dict(params.get("_asset_tags", {}))

        # 动态等分预算
        has_tags = any(
            t in ("both", "momentum", "reversal")
            for t in asset_tags.values()
        )
        if not has_tags:
            # 无标签选择器时退化为等权 1/N
            valid_count = max(len([a for a in prices.columns if len(prices[a].dropna()) >= min_history_days]), 1)
            budget_per_slot = 1.0 / valid_count
        else:
            n_momentum = int(params.get("_n_momentum", 7))
            n_reversal = int(params.get("_n_reversal", 1))
            total_slots = n_momentum + n_reversal
            budget_per_slot = 1.0 / max(total_slots, 1)

        if lookback_days > 0 and len(prices) > lookback_days:
            prices = prices.iloc[-lookback_days:]

        valid_assets = [a for a in prices.columns if len(prices[a].dropna()) >= min_history_days]
        if not valid_assets:
            raise ValueError(f"没有资产满足最小历史数据要求（{min_history_days}天）")
        prices = prices[valid_assets]

        # 风险预算分配（动态等分，与原型 calc_risk_budget 一致）：
        # - both → 2 个槽位预算；单侧选中 → 1 个槽位；未选中 → 0
        # - 无标签选择器时退化为全资产等分 1/N
        risk_budgets = {}
        for asset in valid_assets:
            tag = asset_tags.get(asset, "none")
            if not has_tags:
                risk_budgets[asset] = budget_per_slot
            elif tag == "both":
                risk_budgets[asset] = 2 * budget_per_slot
            elif tag in ("momentum", "reversal"):
                risk_budgets[asset] = budget_per_slot
            else:
                # 未被选择器选中的资产不分配预算（原型：未入选 → 0）
                risk_budgets[asset] = 0.0

        returns = compute_simple_returns(prices)
        if returns.empty or len(returns) < max(vol_windows):
            raise ValueError(f"收益率数据不足以计算波动率（需要至少{max(vol_windows)}天）")

        asset_vols = compute_asset_rolling_volatility(
            prices, windows=vol_windows, annualization_factor=260
        )
        # 波动率为0的资产分配权重0（与原型行为一致：sigma=0 → w=0，不阻断回测）
        zero_vol_mask = (asset_vols == 0) | asset_vols.isna()
        if zero_vol_mask.any():
            zero_vol = asset_vols[zero_vol_mask].index.tolist()
            _log.warning(
                f"[vol_scaled_budget/tag_based] 以下资产波动率为0或NaN，将分配权重0: {zero_vol}"
            )
            valid_assets = [a for a in valid_assets if a not in set(zero_vol)]
            if not valid_assets:
                raise ValueError(
                    "所有资产波动率为0或NaN，无法计算权重。"
                    "请检查价格数据完整性或回测起始日期。"
                )

        # w_init = budget * target_vol / vol
        weights_init = pd.Series(index=valid_assets, dtype=float)
        for asset in valid_assets:
            weights_init[asset] = risk_budgets[asset] * target_vol / asset_vols[asset]

        portfolio_vol = compute_portfolio_volatility(
            returns=returns, weights=weights_init, windows=vol_windows,
            annualization_factor=260, fillna_zero=True,
        )

        return self._apply_triple_constraint(
            weights_init, portfolio_vol, target_vol,
            max_total_leverage, weight_caps, default_max_weight, valid_assets,
        )

    # ------------------------------------------------------------------
    # selection_equal: 原 sharpe_risk_budget 逻辑
    # ------------------------------------------------------------------

    def _allocate_selection_equal(self, prices: pd.DataFrame, **params) -> pd.Series:
        """选中资产等权预算（1/N），N 由上游选择结果动态确定。"""
        target_vol = float(params.get("target_vol", 0.05))
        max_leverage = float(params.get("max_total_leverage", 4.0))
        min_history_days = int(params.get("min_history_days", 260))
        lookback_days = int(params.get("lookback_days", 0))
        # 单资产权重上限（用户配置，留空不限制）；历史名 max_weight_dict 由
        # resolve_weight_caps 统一回退，JSON 字符串形态也在此解析
        weight_caps = resolve_weight_caps(params)

        vol_windows = self._resolve_vol_windows(params)

        selection_row = params.get("_selection_row", {})
        all_assets = list(prices.columns)

        if lookback_days > 0 and len(prices) > lookback_days:
            prices = prices.iloc[-lookback_days:]

        date_idx = len(prices) - 1

        valid_assets = [a for a in all_assets if prices[a].notna().sum() >= min_history_days]
        if not valid_assets:
            raise ValueError(
                f"[vol_scaled_budget/selection_equal] 无资产满足最小历史数据要求 "
                f"{min_history_days} 天，请降低 min_history_days 或拉长回测区间。"
            )

        # Step 1: 风险预算（N = 实际选中资产数，由上游选择器/用户勾选决定）
        selected_assets = [a for a in all_assets if selection_row.get(a, 0) == 1]
        select_count = len(selected_assets)
        if select_count == 0:
            raise ValueError(
                "[vol_scaled_budget/selection_equal] 无资产被选中，"
                "请检查上游选择器结果或用户勾选的资产列表。"
            )
        risk_budgets = {}
        for asset in all_assets:
            if asset in selected_assets:
                risk_budgets[asset] = 1.0 / select_count
            else:
                risk_budgets[asset] = 0.0

        # Step 2: 资产波动率
        asset_vols = _calc_asset_volatility_max(prices, date_idx, windows=vol_windows)

        # Step 3: 初始权重
        weights_init = pd.Series(0.0, index=all_assets)
        for asset in all_assets:
            b = risk_budgets.get(asset, 0.0)
            sigma = asset_vols.get(asset, np.nan)
            if b > 0 and sigma > 0 and not np.isnan(sigma):
                weights_init[asset] = b * (target_vol / sigma)

        # Step 4: 组合波动率
        port_vol = _calc_portfolio_volatility_max(prices, weights_init, date_idx, windows=vol_windows)

        # Step 5: 缩放约束
        total_weight = weights_init.sum()
        if total_weight <= 0:
            raise ValueError(
                f"[vol_scaled_budget/selection_equal] 初始权重总和 <= 0，"
                f"可能原因: 选中资产数=0、波动率全为 NaN/0、或 risk_budget 全为 0。"
                f"请检查上游选择结果和价格数据完整性。"
            )

        scale_vol = target_vol / port_vol if port_vol > 0 else 1.0
        scale_leverage = max_leverage / total_weight if total_weight > 0 else 1.0
        scale = min(scale_vol, scale_leverage)
        weights_scaled = weights_init * scale

        # Step 6: 资产权重约束截断
        weights_final = weights_scaled.copy()
        if weight_caps:
            for asset in all_assets:
                cap = weight_caps.get(asset)
                if cap is not None and weights_final[asset] > cap:
                    weights_final[asset] = cap

        return weights_final

    # ------------------------------------------------------------------
    # inverse_variance: 原 momentum_risk_parity 逻辑
    # ------------------------------------------------------------------

    def _allocate_inverse_variance(self, prices: pd.DataFrame, **params) -> pd.Series:
        """反方差预算（1/σ²）。"""
        if prices.empty or len(prices) < 30:
            raise ValueError(
                f"反方差预算模式数据不足: 价格矩阵仅 {len(prices)} 行，至少需要 30 行。"
                "请拉长回测区间或增加预热期。"
            )

        vol_window = int(params.get("vol_window_inv_var", 60))
        # 波动率估计方法：rolling（默认，等权滚动）/ ewma（指数加权，对齐 GMAP 原型）
        vol_method = str(params.get("vol_method_inv_var", "rolling")).lower()
        # 资产权重约束（兼容旧参数 single_cap）
        weight_caps = resolve_weight_caps(params)
        single_cap_fallback = float(params.get("single_cap", 1.0))  # 旧版均匀上限，默认不截断
        selection_mask = params.get("selection_mask", None)
        # Pipeline 未注入 selection_mask 时，从 _selection_row 字典构建
        if selection_mask is None:
            selection_row = params.get("_selection_row", {})
            if selection_row:
                selection_mask = pd.Series(
                    [float(selection_row.get(c, 0)) for c in prices.columns],
                    index=prices.columns,
                )

        returns = prices.pct_change(fill_method=None).iloc[1:]
        n_assets = len(prices.columns)

        if vol_method == "ewma":
            # 口径与 GMSI 2.0 原型 compute_vol(ewma) 一致：
            # span=窗口，min_periods=max(5, 窗口一半)
            vol = returns.ewm(
                span=vol_window, min_periods=max(5, vol_window // 2)
            ).std() * np.sqrt(260)
        else:
            vol = returns.rolling(vol_window, min_periods=vol_window // 2).std() * np.sqrt(260)
        inv_var = 1.0 / (vol ** 2)
        latest_inv_var = inv_var.iloc[-1]
        # 容错：波动率为 0/NaN（如停牌、未上市区间）时 1/σ² 为 inf/NaN，
        # 一律视为不可配置（权重 0），避免 inf 污染归一化导致全零权重
        latest_inv_var = latest_inv_var.replace([np.inf, -np.inf], np.nan).fillna(0.0)

        if selection_mask is not None:
            latest_inv_var = latest_inv_var * selection_mask

        row_sum = latest_inv_var.sum()
        if row_sum <= 0:
            # 波动率全部不可估（如回测早期/新品种密集上市）：对齐原型
            # fillna(1/n_assets) 语义，回退为可配资产等权，而非报错空仓
            if selection_mask is not None and float(selection_mask.sum()) > 0:
                sel = selection_mask.astype(float)
                fallback = sel / float(sel.sum())
            else:
                fallback = pd.Series(1.0 / n_assets, index=prices.columns)
            _log.warning(
                "[vol_scaled_budget/inverse_variance] 波动率全部不可估，回退等权 1/N（对齐原型 fillna(1/n) 语义）"
            )
            return fallback
        weights = latest_inv_var / row_sum

        # 资产权重约束截断
        if weight_caps:
            for asset in weights.index:
                cap = weight_caps.get(asset)
                if cap is not None:
                    weights[asset] = min(weights[asset], cap)
        elif single_cap_fallback < 1.0:
            weights = weights.clip(upper=single_cap_fallback)

        total = weights.sum()
        if total <= 0:
            raise ValueError(
                "反方差预算失败: 截断后权重总和 <= 0，"
                "权重约束可能过严或波动率数据异常。"
            )
        weights = weights / total

        return weights

    # ------------------------------------------------------------------
    # 三重约束缩放（tag_based 使用）
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_triple_constraint(
        weights_init: pd.Series,
        portfolio_vol: float,
        target_vol: float,
        max_total_leverage: float,
        max_weight_dict: dict,
        default_max_weight: float,
        valid_assets: list,
    ) -> pd.Series:
        """三重约束（与原型 allocate_weights 一致）。

        1. 组合波动率缩放: scale_vol = target_vol / σ_port
        2. 杠杆缩放: scale_lev = max_leverage / Σw
        3. 单资产上限: 逐资产截断（默认 1.0 不限制），而非全局最小比例缩放
        """
        vol_scale = target_vol / portfolio_vol if portfolio_vol > 0 else 1.0
        total_leverage = weights_init.sum()
        leverage_scale = max_total_leverage / total_leverage if total_leverage > 0 else 1.0

        final_scale = min(vol_scale, leverage_scale)
        weights_final = weights_init * final_scale

        # 单资产上限逐资产截断（与原型一致：cap 仅作用于超限资产本身）
        for asset in weights_final.index:
            cap = max_weight_dict.get(asset, default_max_weight)
            if weights_final[asset] > cap:
                weights_final[asset] = cap

        if weights_final.sum() > max_total_leverage:
            weights_final = weights_final * (max_total_leverage / weights_final.sum())

        return weights_final
