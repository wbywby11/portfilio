"""风险预算+目标波动率策略 (Risk Budget + Target Volatility Strategy)

基于文档标准的风险预算分配:
- 同时被动量和反转选中的资产: 风险预算 2/8
- 仅被单一模型选中的资产: 风险预算 1/8  
- 未选中的资产: 风险预算 0

结合目标波动率控制和三重约束,实现风险均衡的资产配置

作者: System
日期: 2026-01-08
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from typing import Any
from typing import Dict

from app.strategies.formula.returns import compute_simple_returns

_log = logging.getLogger(__name__)
from app.strategies.formula.rolling_volatility import (
    compute_asset_rolling_volatility,
    compute_portfolio_volatility
)
from app.strategies.models.base import BaseStrategyModel


class RiskBudgetTargetVolStrategy(BaseStrategyModel):
    """风险预算+目标波动率策略.
    
    核心思想:
    1. 根据资产来源(动量/反转/交集)分配差异化风险预算
    2. 计算初始权重: w_init = risk_budget * target_vol / realized_vol
    3. 应用三重约束缩放: 组合波动率、总杠杆、单资产上限
    """

    @staticmethod
    def _parse_json_or_dict(value, default=None):
        """安全解析 JSON 字符串或字典参数"""
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
    
    @classmethod
    def get_param_schema(cls):
        """返回风险预算+目标波动率策略的参数Schema."""
        from app.strategies.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="risk_budget_target_vol",
            display_name="风险预算+目标波动率策略",
            description="基于动量+反转双模型的风险预算分配,结合目标波动率控制的资产配置策略(文档标准版)",
            monitoring_metrics=[
                {"name": "portfolio_volatility", "label": "组合波动率", "threshold_param": "vol_reset_threshold"}
            ],
            # 默认值与范围与 investmentA 一致，供新增/修改策略时使用
            params=[
                ParamSchema(
                    name="target_vol",
                    label="目标年化波动率",
                    type="number",
                    default=0.05,
                    min_value=0.01,
                    max_value=0.15,
                    step=0.005,
                    description="组合目标波动率(默认5%),较低值更保守"
                ),
                ParamSchema(
                    name="risk_budget_both",
                    label="交集资产风险预算",
                    type="number",
                    default=0.25,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.05,
                    description="同时被动量和反转选中的资产的风险预算(默认2/8=0.25)"
                ),
                ParamSchema(
                    name="risk_budget_single",
                    label="单一模型资产风险预算",
                    type="number",
                    default=0.125,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.025,
                    description="仅被动量或反转选中的资产的风险预算(默认1/8=0.125)"
                ),
                ParamSchema(
                    name="max_total_leverage",
                    label="最大杠杆倍数",
                    type="number",
                    default=4.0,
                    min_value=1.0,
                    max_value=10.0,
                    step=0.5,
                    description="组合最大杠杆限制,权重和不超过此倍数"
                ),
                ParamSchema(
                    name="max_weight_dict",
                    label="单资产最大权重配置",
                    type="max_weight_dict",
                    default={},
                    description="根据底层资产池自动列出资产，为每个资产设置单资产最大权重(0-1之间的小数)"
                ),
                ParamSchema(
                    name="min_history_days",
                    label="最小历史数据要求",
                    type="number",
                    default=260,
                    min_value=100,
                    max_value=500,
                    step=10,
                    description="资产进入计算的最小交易日数要求(文档要求≥260)。如果数据不足，建议降低此值或调整回测起始日期"
                ),
                ParamSchema(
                    name="enable_vol_reset",
                    label="启用波动率阈值重置",
                    type="boolean",
                    default=True,  # 改为 True，与模型实际保存行为一致
                    description="是否启用波动率重置功能（当波动率超过阈值时自动降仓）。风险预算+目标波动率策略默认开启。"
                ),
                ParamSchema(
                    name="vol_reset_threshold",
                    label="波动率重置阈值",
                    type="number",
                    default=0.06,
                    min_value=0.03,
                    max_value=0.10,
                    step=0.005,
                    description="触发波动率重置的阈值(默认6%),当组合波动率超过此值时触发权重缩放"
                ),
                ParamSchema(
                    name="lookback_days",
                    label="历史数据回看期",
                    type="number",
                    default=260,
                    min_value=130,
                    max_value=520,
                    step=10,
                    description="计算波动率使用的历史数据长度(交易日)"
                ),
            ]
        )
    
    def _allocate_via_reference_engine(self, prices: pd.DataFrame, **params) -> pd.Series:
        """以 step2_weight_calculation.py 为核心计算权重（与对照文件完全一致）"""
        from app.selection.engine_reference import calc_weights_for_date

        target_vol = float(params.get("target_vol", 0.05))
        max_leverage = float(params.get("max_total_leverage", 4.0))
        selection_row = params["_selection_row"]
        all_assets = list(prices.columns)

        raw_max = params.get("max_weight_dict", {})
        weight_caps = raw_max if isinstance(raw_max, dict) else {}

        lookback = int(params.get("lookback_days", 260))
        if lookback > 0 and len(prices) > lookback:
            prices = prices.iloc[-lookback:]

        date_idx = len(prices) - 1
        result = calc_weights_for_date(
            nav=prices,
            date_idx=date_idx,
            selection_row=selection_row,
            all_assets=all_assets,
            target_vol=target_vol,
            max_leverage=max_leverage,
            weight_caps=weight_caps,
            fillna_zero=True,
        )
        final_dict = result["最终权重"]
        out = pd.Series(0.0, index=all_assets)
        for a in all_assets:
            out[a] = final_dict.get(a, 0.0)

        # 填充 trace 供混合动量导出
        trace = params.get("_trace_output")
        if isinstance(trace, dict):
            trace["_portfolio_vol"] = result.get("组合波动率", 0.0)
            trace["_final_scale"] = result.get("缩放系数", 1.0)
            trace["_weights_init"] = result.get("初始权重", {})
            trace["_weights_scaled"] = result.get("缩放后权重", {})
            for a in all_assets:
                trace[a] = {
                    "risk_budget": result.get("风险预算", {}).get(a, 0),
                    "vol": result.get("资产波动率", {}).get(a, float("nan")),
                }
        return out

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """计算风险预算+目标波动率策略的资产配置权重.
        
        流程:
        1. 筛选有效资产(满足最小历史数据要求)
        2. 根据资产标签(tags)分配风险预算
        3. 计算每个资产的已实现波动率
        4. 计算初始权重: w_init = risk_budget * target_vol / realized_vol
        5. 计算模拟组合波动率
        6. 应用三重约束缩放
        
        Args:
            prices: 资产价格历史数据,行为日期,列为资产代码
            **params: 策略参数
                - target_vol: 目标年化波动率(默认0.05)
                - risk_budget_both: 交集资产风险预算(默认0.25)
                - risk_budget_single: 单一模型资产风险预算(默认0.125)
                - max_total_leverage: 最大杠杆倍数(默认4.0)
                - max_weight_dict: 单资产最大权重配置(资产代码->最大权重的字典)
                - min_history_days: 最小历史数据要求(默认260)
                - lookback_days: 历史数据回看期(默认260)
                - _asset_tags: 资产标签字典(可选,来自selection)
        
        Returns:
            pd.Series: 资产配置权重,索引为资产代码,值为权重
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        # 以 step2 为核心计算引擎（与对照文件完全一致）
        if params.get("_use_reference_engine") and params.get("_selection_row") is not None:
            return self._allocate_via_reference_engine(prices, **params)

        # 1. 获取参数
        target_vol = float(params.get("target_vol", 0.05))
        risk_budget_both = float(params.get("risk_budget_both", 0.25))
        risk_budget_single = float(params.get("risk_budget_single", 0.125))
        max_total_leverage = float(params.get("max_total_leverage", 4.0))
        min_history_days = int(params.get("min_history_days", 260))
        lookback_days = int(params.get("lookback_days", 260))
        
        max_weight_dict = self._parse_json_or_dict(params.get("max_weight_dict", {}))
        default_max_weight = 0.1  # 编制规则默认上限
        asset_tags = self._parse_json_or_dict(params.get("_asset_tags", {}))
        vol_windows = [22, 65, 130]
        
        # 2. 处理lookback_days
        enable_trace = params.get("_enable_weight_trace", False)
        if lookback_days > 0 and len(prices) > lookback_days:
            prices = prices.iloc[-lookback_days:]

        def _trace(title: str, lines: list) -> None:
            if enable_trace:
                _log.info("[权重计算-步骤] %s\n%s", title, "\n".join(lines))
                print(f"\n[权重计算-步骤] {title}")
                for ln in lines:
                    print(f"  {ln}")

        # 权重计算公式：w_init=rb*σ_t/σ_i → 三重约束缩放(vol/leverage/weight) → final_w=w_init*min(scales)
        if enable_trace:
            _trace("公式概览", [
                "w_init = risk_budget * target_vol / realized_vol",
                "final_scale = min(vol_scale, leverage_scale, weight_scale)",
                f"当前 max_weight_dict: {{{', '.join(f'{k}:{v}' for k, v in max_weight_dict.items() if k in list(prices.columns))}}}",
            ])

        # 步骤0: 输入概览
        date_range = f"{prices.index[0]} ~ {prices.index[-1]}" if len(prices) > 0 else "空"
        _trace("输入概览", [
            f"  资产列: {list(prices.columns)}",
            f"  日期范围: {date_range}",
            f"  行数: {len(prices)}",
            f"  lookback_days: {lookback_days}, min_history_days(参数): {min_history_days}",
        ])

        # 3. 筛选有效资产
        all_input_assets = list(prices.columns)
        total_available_days = len(prices)
        if total_available_days == 0 or len(prices.columns) == 0:
            raise ValueError("价格数据为空或没有资产列，无法计算权重")
        
        # 计算每个资产的实际可用数据天数
        max_asset_data_days = max(len(prices[a].dropna()) for a in prices.columns)
        
        # 与动量选择器联用时数据可能较短，按实际数据放宽要求
        min_vol_window, min_vol_short = max(vol_windows), min(vol_windows)
        if max_asset_data_days >= min_vol_window:
            effective_min_history_days = min(
                min_history_days,
                max(min_vol_window, max_asset_data_days - 10)
            )
        else:
            effective_min_history_days = max(min_vol_short, max_asset_data_days - 10)
        # 保证至少能让"数据最多的资产"通过
        if max_asset_data_days > 0:
            effective_min_history_days = min(effective_min_history_days, max_asset_data_days)
        
        if min_history_days > max_asset_data_days:
            import warnings
            warnings.warn(
                f"策略要求最小历史数据{min_history_days}天，但实际最大可用数据只有{max_asset_data_days}天。"
                f"已自动调整为{effective_min_history_days}天。"
            )
        
        valid_assets = []
        asset_data_info = {}
        excluded_assets = []
        for asset in prices.columns:
            data_days = len(prices[asset].dropna())
            asset_data_info[asset] = data_days
            if data_days >= effective_min_history_days:
                valid_assets.append(asset)
            else:
                excluded_assets.append((asset, data_days))

        _trace("步骤1-资产筛选", [
            f"  effective_min_history_days={effective_min_history_days}, max_asset_data_days={max_asset_data_days}",
            f"  valid_assets: {valid_assets}",
            f"  excluded({len(excluded_assets)}): {[a for a,_ in excluded_assets]}",
        ] + [f"    {a}: {asset_data_info.get(a,0)}天 → {'通过' if a in valid_assets else f'排除(差{effective_min_history_days - asset_data_info.get(a,0)}天)'}" for a in prices.columns])

        # 若有资产因数据不足被排除，记录警告
        if excluded_assets:
            exc_lines = [f"  ・ {a}: 有效数据 {d} 天，需≥{effective_min_history_days} 天，差 {effective_min_history_days - d} 天" for a, d in excluded_assets]
            _log.warning(
                "[风险预算策略] 以下资产未配置权重:\n%s\n"
                "  原因: 按 prices[asset].dropna() 统计有效交易日数，NaN/缺失日不计数。"
                "  建议: 检查历史数据导入是否完整，或适当降低「最小历史数据要求」。",
                "\n".join(exc_lines)
            )

        if not valid_assets:
            asset_info_str = ", ".join([f"{a}({d}天)" for a, d in asset_data_info.items()])
            raise ValueError(
                f"没有资产满足最小历史数据要求(调整后为{effective_min_history_days}天，原始要求{min_history_days}天)。\n"
                f"可用数据: {total_available_days}天, {len(all_input_assets)}个资产, {asset_info_str}\n"
                f"建议: 1)检查资产数据导入 2)降低最小历史数据要求至{max(100, total_available_days - 10)}天以下 3)调整回测起始日期"
            )

        # 只保留有效资产
        prices = prices[valid_assets]
        n_assets = len(valid_assets)

        # 4. 分配风险预算
        risk_budgets = {}
        for asset in valid_assets:
            tag = asset_tags.get(asset, "none")
            if tag == "both":
                risk_budgets[asset] = risk_budget_both
            elif tag in ["momentum", "reversal"]:
                risk_budgets[asset] = risk_budget_single
            else:
                # 如果没有标签或标签为none,默认等权风险预算
                risk_budgets[asset] = 1.0 / n_assets

        _trace("步骤3-风险预算", [
            f"  asset_tags: {asset_tags}",
        ] + [f"    {a}: tag={asset_tags.get(a,'none')} → risk_budget={risk_budgets[a]:.4f}" for a in valid_assets])

        # 5. 计算收益率
        returns = compute_simple_returns(prices)
        
        if returns.empty or len(returns) < max(vol_windows):
            raise ValueError(
                f"收益率数据不足以计算波动率(需要至少{max(vol_windows)}天)"
            )
        
        # 6. 计算每个资产的已实现波动率
        asset_vols = compute_asset_rolling_volatility(
            prices,
            windows=vol_windows,
            annualization_factor=260
        )
        
        # 检查零波动率
        if (asset_vols == 0).any():
            zero_vol_assets = asset_vols[asset_vols == 0].index.tolist()
            raise ValueError(
                f"以下资产波动率为0,无法计算权重:{zero_vol_assets}"
            )

        _trace("步骤4-资产波动率", [f"    {a}: {asset_vols[a]:.6f}" for a in valid_assets])

        # 7. 计算初始权重: w_init = risk_budget * target_vol / realized_vol
        weights_init = pd.Series(index=valid_assets, dtype=float)
        for asset in valid_assets:
            risk_budget = risk_budgets[asset]
            vol = asset_vols[asset]
            weights_init[asset] = risk_budget * target_vol / vol

        _trace("步骤5-初始权重(w_init=risk_budget*target_vol/vol)", [
            f"  target_vol={target_vol}",
        ] + [f"    {a}: {weights_init[a]:.4f} = {risk_budgets[a]:.4f}*{target_vol}/{asset_vols[a]:.4f}" for a in valid_assets])

        # 8. 计算模拟组合波动率（编制规则：缺失收益率 fillna(0)，与 step2/外部系统一致）
        portfolio_vol = compute_portfolio_volatility(
            returns=returns,
            weights=weights_init,
            windows=vol_windows,
            annualization_factor=260,
            fillna_zero=True,
        )
        
        # 9. 应用三重约束缩放
        # 约束1: 组合波动率约束
        vol_scale = target_vol / portfolio_vol if portfolio_vol > 0 else 1.0
        
        # 约束2: 总杠杆约束
        total_leverage = weights_init.sum()
        leverage_scale = max_total_leverage / total_leverage if total_leverage > 0 else 1.0
        
        # 约束3: 单资产权重约束
        weight_scales = []
        scale_details = {}
        for asset in valid_assets:
            max_w = max_weight_dict.get(asset, default_max_weight)
            wi = weights_init[asset]
            if wi > 0:
                scale = max_w / wi
                if scale <= 0:
                    _log.warning(
                        "[风险预算] 资产 %s 的 max_weight=%s 导致 scale=0，最终权重将全为0。"
                        "编制规则 ZQGZ10=60%%/ZQGZ2=90%%，请检查 max_weight_dict 配置。",
                        asset, max_w
                    )
                weight_scales.append(scale)
                scale_details[asset] = {'max_w': float(max_w), 'w_init': float(wi), 'scale': float(scale)}
            else:
                scale_details[asset] = {'max_w': float(max_w), 'w_init': float(wi), 'scale': float('inf')}
        weight_scale = min(weight_scales) if weight_scales else 1.0

        # 取三个约束的最小值
        final_scale = min(vol_scale, leverage_scale, weight_scale)

        # 步骤6 trace：含每资产 scale 明细，便于排查 final_scale=0
        step6_lines = [
            f"  portfolio_vol={portfolio_vol:.6f} → vol_scale={vol_scale:.4f}",
            f"  total_leverage={total_leverage:.4f} → leverage_scale={leverage_scale:.4f}",
            f"  weight_scale(单资产上限约束)={weight_scale:.4f}",
            f"  final_scale=min(vol_scale,leverage_scale,weight_scale)={final_scale:.4f}",
        ]
        if final_scale <= 0:
            which = [s for s, v in [("vol_scale=0", vol_scale), ("leverage_scale=0", leverage_scale), ("weight_scale=0", weight_scale)] if v <= 0]
            step6_lines.append(f"  【final_scale=0 原因】 ← {' '.join(which)}")
        step6_lines.append("  每资产 scale=max_w/w_init:")
        for a, d in scale_details.items():
            step6_lines.append(f"    {a}: max_w={d['max_w']:.4f} w_init={d['w_init']:.4f} → scale={d['scale']:.4f}")
        if weight_scale <= 0:
            culprits = [a for a, d in scale_details.items() if d['w_init'] > 0 and d['max_w'] <= 0]
            if culprits:
                step6_lines.append(f"  【weight_scale=0 根因】 以下资产 max_weight_dict≤0: {culprits}")
        _trace("步骤6-三重约束缩放", step6_lines)

        # 填充 final_scale=0 的具体原因，供 strategy_api 在「每个资产结果说明」中展示
        _zero_reason = None
        if final_scale <= 0:
            parts = []
            if vol_scale <= 0:
                parts.append(f"vol_scale=0(portfolio_vol={portfolio_vol:.4f})")
            if leverage_scale <= 0:
                parts.append(f"leverage_scale=0(total_leverage={total_leverage:.4f})")
            if weight_scale <= 0:
                culprits_mw0 = [a for a, d in scale_details.items() if d['w_init'] > 0 and d['max_w'] <= 0]
                if culprits_mw0:
                    parts.append(f"weight_scale=0(资产{culprits_mw0}的max_weight_dict≤0)")
                else:
                    per_asset = "; ".join([f"{a}:max_w={d['max_w']},w_init={d['w_init']:.4f}" for a, d in list(scale_details.items())[:8]])
                    parts.append(f"weight_scale=0(明细:{per_asset})")
            _zero_reason = " | ".join(parts)

        # 应用缩放
        weights_final = weights_init * final_scale

        # 10. 归一化(可选,确保权重和≤max_total_leverage)
        if weights_final.sum() > max_total_leverage:
            weights_final = weights_final * (max_total_leverage / weights_final.sum())

        _trace("步骤7-最终权重", [
            f"  权重和: {weights_final.sum():.4f}",
        ] + [f"    {a}: {weights_final[a]:.6f} ({weights_final[a]*100:.2f}%)" for a in valid_assets])

        # 填充 _trace_output 供 strategy_api 打印每个资产结果说明（含权重计算过程）
        # 同时供混合动量导出：_portfolio_vol, _final_scale, _weights_init, _weights_scaled
        trace_output = params.get("_trace_output")
        excluded_set = {a for a, _ in excluded_assets}
        if trace_output is not None and isinstance(trace_output, dict):
            if _zero_reason:
                trace_output["_final_scale_zero_reason"] = _zero_reason
            trace_output["_portfolio_vol"] = portfolio_vol
            trace_output["_final_scale"] = final_scale
            trace_output["_weights_init"] = weights_init.to_dict()
            trace_output["_weights_scaled"] = (weights_init * final_scale).to_dict()
            for asset in all_input_assets:
                dd = asset_data_info.get(asset, 0)
                if asset in excluded_set:
                    short = effective_min_history_days - dd
                    trace_output[asset] = {
                        "status": "excluded",
                        "data_days": dd,
                        "effective_min": effective_min_history_days,
                        "reason": f"有效数据{dd}天 < 需≥{effective_min_history_days}天，差{short}天",
                    }
                else:
                    tag = asset_tags.get(asset, "none")
                    rb = risk_budgets.get(asset, 0)
                    vol_val = float(asset_vols[asset]) if asset in asset_vols.index else 0
                    wi = float(weights_init[asset]) if asset in weights_init.index else 0
                    wf = float(weights_final[asset]) if asset in weights_final.index else 0
                    max_w = max_weight_dict.get(asset, default_max_weight)
                    trace_output[asset] = {
                        "status": "valid",
                        "data_days": dd,
                        "tag": tag,
                        "risk_budget": rb,
                        "vol": vol_val,
                        "w_init": wi,
                        "final_scale": final_scale,
                        "weight": wf,
                        "target_vol": target_vol,
                        "max_weight": max_w,
                    }

        return weights_final
    
    def compute_volatility_reset_weights(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> pd.Series:
        """计算波动率重置后的权重.
        
        当组合波动率超过阈值时,按比例缩放所有资产权重。
        编制规则 4.3.4：w_VW^c = w_signal^c × (σ_target / VolTrigger)，其中 VolTrigger 为**信号日**的已实现波动率。
        若调用方传入 _vol_trigger（信号日触发值），则直接使用该值做等比例缩放，确保执行日必定降仓至目标波动率水平；
        否则在本地重算当前波动率，仅当仍大于阈值时才缩放（兼容旧逻辑）。
        
        Args:
            current_weights: 当前持仓权重
            prices: 资产价格历史数据
            **params: 策略参数
                - target_vol: 目标年化波动率(默认0.05)
                - vol_reset_threshold: 重置阈值(默认0.06)
                - _vol_trigger: （可选）信号日已实现波动率，由引擎传入时优先使用
        
        Returns:
            pd.Series: 重置后的权重
        """
        if not params.get("enable_vol_reset", False):
            return current_weights
        target_vol = float(params.get("target_vol", 0.05))
        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))
        # 优先使用引擎传入的信号日 VolTrigger（编制规则：用信号日波动率做缩放）
        vol_trigger = params.get("_vol_trigger") or params.get("vol_trigger")
        if vol_trigger is not None and vol_trigger > 0:
            scale_factor = target_vol / float(vol_trigger)
            return current_weights * scale_factor
        # 兼容：未传入时在本地重算，仅当仍 > 阈值时才缩放
        weights = current_weights.copy()
        weights.index = weights.index.astype(str)
        price_cols_str = {str(c): c for c in prices.columns}
        common = [price_cols_str[k] for k in weights.index if k in price_cols_str]
        if not common:
            return current_weights
        prices_sub = prices[common].copy()
        weights_aligned = weights.reindex([str(c) for c in common]).dropna()
        if weights_aligned.empty:
            return current_weights
        weights_aligned.index = [price_cols_str[k] for k in weights_aligned.index]
        returns = compute_simple_returns(prices_sub)
        vol_windows = [22, 65, 130]
        current_vol = compute_portfolio_volatility(
            returns=returns,
            weights=weights_aligned,
            windows=vol_windows,
            annualization_factor=260,
            fillna_zero=True,
        )
        # 编制规则 step3：触发条件为严格大于 >（非 >=）
        if current_vol > vol_reset_threshold:
            scale_factor = target_vol / current_vol
            return current_weights * scale_factor
        return current_weights
    
    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> dict[str, Any]:
        """计算策略监控指标（与 check_volatility_trigger 使用相同对齐逻辑）。"""
        weights = current_weights.copy()
        weights.index = weights.index.astype(str)
        price_cols_str = {str(c): c for c in prices.columns}
        common = [price_cols_str[k] for k in weights.index if k in price_cols_str]
        if not common:
            return {"portfolio_volatility": None}
        prices_sub = prices[common].copy()
        weights_aligned = weights.reindex([str(c) for c in common]).dropna()
        if weights_aligned.empty:
            return {"portfolio_volatility": None}
        weights_aligned.index = [price_cols_str[k] for k in weights_aligned.index]
        returns = compute_simple_returns(prices_sub)
        vol_windows = [22, 65, 130]
        # 编制规则 step3：波动率监控从第 130 天起；fillna(0) 与 step2/step3 一致
        if len(prices_sub) < 130:
            return {"portfolio_volatility": None}
        current_vol = compute_portfolio_volatility(
            returns=returns,
            weights=weights_aligned,
            windows=vol_windows,
            annualization_factor=260,
            fillna_zero=True,
        )
        return {"portfolio_volatility": current_vol}

    def check_volatility_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> tuple[bool, float]:
        """检查是否触发波动率重置.
        
        Args:
            current_weights: 当前持仓权重
            prices: 资产价格历史数据
            **params: 策略参数
        
        Returns:
            tuple: (是否触发, 当前波动率信号值)
                - 是否触发: bool
                - 波动率信号值: float（年化波动率）
        """
        if not params.get("enable_vol_reset", False):
            return False, 0.0
        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))
        
        # 对齐权重与价格列（避免 index/columns 类型不一致导致交集为空、波动率恒为 0）
        weights = current_weights.copy()
        weights.index = weights.index.astype(str)
        price_cols_str = {str(c): c for c in prices.columns}
        common = [price_cols_str[k] for k in weights.index if k in price_cols_str]
        if not common:
            return False, 0.0
        prices_sub = prices[common].copy()
        weights_aligned = weights.reindex([str(c) for c in common]).dropna()
        if weights_aligned.empty:
            return False, 0.0
        weights_aligned.index = [price_cols_str[k] for k in weights_aligned.index]
        
        returns = compute_simple_returns(prices_sub)
        vol_windows = [22, 65, 130]
        # 编制规则 step3：波动率监控从第 130 天起；fillna(0) 与 step2/step3 一致
        if len(prices_sub) < 130:
            return False, 0.0
        current_vol = compute_portfolio_volatility(
            returns=returns,
            weights=weights_aligned,
            windows=vol_windows,
            annualization_factor=260,
            fillna_zero=True,
        )
        # 编制规则 step3：触发条件为严格大于 >（非 >=）
        triggered = current_vol > vol_reset_threshold
        return triggered, current_vol
