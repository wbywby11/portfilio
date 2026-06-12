# -*- coding: utf-8 -*-
"""
大类资产配置监测系统 - 策略引擎
独立实现资产选择和权重计算的完整策略逻辑

本模块实现：
1. 动量因子计算（4因子×4窗口：MOM/MACD/POSI/SMOM，满分16分）
2. 反转因子计算（双窗口偏度：10天+22天）
3. 资产选择（动量选7个 + 反转选1个，取并集）
4. 权重计算（风险预算、波动率、缩放约束、权重上限）

注意：核心计算逻辑与 monitor_vs 完全一致，不做任何算法修改
"""

import logging
from typing import Dict, List, Tuple, Optional, TYPE_CHECKING
import numpy as np
import pandas as pd

from app.monitor import config

logger = logging.getLogger(__name__)

# 月度调仓预计算会高频调用 run_weight_calculation(rt=None)，避免每次 dict(config.WEIGHT_CAPS) 分配
_DEFAULT_MONITOR_WEIGHT_CAPS: Dict[str, float] = {
    k: float(v) for k, v in config.WEIGHT_CAPS.items()
}

if TYPE_CHECKING:
    from app.monitor.monitor_runtime import MonitorRuntimeConfig
from app.monitor.types import AssetSelectionResult, WeightResult


class StrategyEngine:
    """策略引擎 - 实现资产选择和权重计算"""
    
    def __init__(self):
        """初始化策略引擎"""
        # 年化因子
        self._annualize_factor = np.sqrt(config.ANNUALIZE_FACTOR)
    
    # =========================================================================
    # 动量因子计算
    # =========================================================================
    
    def _calc_mom(self, prices: pd.DataFrame, n: int) -> pd.Series:
        """
        简单时序动量 MOM
        公式：MOM_t(n) = P_t / P_{t-n} - 1
        """
        return prices / prices.shift(n) - 1
    
    def _calc_macd(self, prices: pd.DataFrame, win_short: int, win_long: int = 250) -> pd.Series:
        """
        双均线动量 MACD
        公式：MACD = MA_short - MA_long
        注：使用固定的 win_long=250
        """
        ma_short = prices.rolling(win_short).mean()
        ma_long = prices.rolling(win_long).mean()
        return ma_short - ma_long
    
    def _calc_posi(self, prices: pd.DataFrame, n: int) -> pd.Series:
        """
        收益正负差因子 POSI
        公式：POSI = sum(正收益) + sum(负收益)
        即过去n日正收益之和 + 负收益之和
        """
        returns = prices.pct_change()
        pos_ret = returns.where(returns > 0, 0)
        neg_ret = returns.where(returns < 0, 0)
        return pos_ret.rolling(window=n).sum() + neg_ret.rolling(window=n).sum()
    
    def _calc_smom(self, prices: pd.DataFrame, win: int, 
                   vol_target: float = 0.045, n_annual: int = 260) -> pd.Series:
        """
        缩放动量因子 SMOM
        公式：SMOM = MOM × (vol_target / (vol × sqrt(n_annual)))
        注：使用 vol_target=0.045
        """
        vol = prices.pct_change().rolling(win).std() * np.sqrt(n_annual)
        mom = prices / prices.shift(win) - 1
        smom = mom * (vol_target / (vol * np.sqrt(n_annual)))
        return smom.replace([np.inf, -np.inf], np.nan)
    
    def _resolve_momentum_dict(self, rt: Optional["MonitorRuntimeConfig"]) -> Dict[str, List[int]]:
        if rt is None or rt.mom_windows is None:
            return {k: list(v) for k, v in config.MOMENTUM_WINDOWS.items()}
        return {
            "MOM": list(rt.mom_windows),
            "POSI": list(rt.posi_windows or ()),
            "SMOM": list(rt.smom_windows or ()),
            "MACD": list(rt.macd_windows or ()),
        }

    def _macd_long(self, rt: Optional["MonitorRuntimeConfig"]) -> int:
        if rt is None or rt.macd_long_window is None:
            return 250
        return int(rt.macd_long_window)

    def _calc_momentum_scores(
        self,
        prices_df: pd.DataFrame,
        calc_date,
        rt: Optional["MonitorRuntimeConfig"] = None,
    ) -> Tuple[Dict[str, int], pd.DataFrame]:
        """
        计算所有资产的动量综合得分
        
        规则：
        - 4个因子类型：MOM、MACD、POSI、SMOM
        - 各因子窗口由策略参数 / 全局 config 决定（通常各 4 档）
        - MACD 长期均线窗口由 macd_long_window 决定（默认 250）
        - 阈值：> -2% 得1分，否则得0分
        
        Returns:
            scores: 各资产得分字典
            details: 详细因子值DataFrame
        """
        threshold = config.MOMENTUM_THRESHOLD  # -0.02
        mw = self._resolve_momentum_dict(rt)
        macd_long = self._macd_long(rt)
        
        # 获取截止到计算日的数据
        date_idx = prices_df.index.get_loc(calc_date)
        price_data = prices_df.iloc[:date_idx + 1]
        
        # 存储详细结果
        details = {}
        scores = pd.Series(0.0, index=prices_df.columns)
        
        mom_windows = mw["MOM"]
        for n in mom_windows:
            if len(price_data) > n:
                factor = self._calc_mom(price_data, n).iloc[-1]
                signal = (factor > threshold).astype(int)
                scores += signal.fillna(0)
                details[f'MOM_{n}'] = factor
                details[f'MOM_{n}_signal'] = signal
        
        macd_windows = mw["MACD"]
        if len(price_data) > macd_long:
            for n in macd_windows:
                factor = self._calc_macd(price_data, n, win_long=macd_long).iloc[-1]
                signal = (factor > threshold).astype(int)
                scores += signal.fillna(0)
                details[f'MACD_{n}'] = factor
                details[f'MACD_{n}_signal'] = signal
        
        posi_windows = mw["POSI"]
        for n in posi_windows:
            if len(price_data) > n:
                factor = self._calc_posi(price_data, n).iloc[-1]
                signal = (factor > threshold).astype(int)
                scores += signal.fillna(0)
                details[f'POSI_{n}'] = factor
                details[f'POSI_{n}_signal'] = signal
        
        smom_windows = mw["SMOM"]
        for n in smom_windows:
            if len(price_data) > n:
                factor = self._calc_smom(price_data, n).iloc[-1]
                signal = (factor > threshold).astype(int)
                scores += signal.fillna(0)
                details[f'SMOM_{n}'] = factor
                details[f'SMOM_{n}_signal'] = signal
        
        details['总分'] = scores
        return scores.to_dict(), pd.DataFrame(details)
    
    def _select_momentum_assets(self, scores: Dict[str, int], 
                                 valid_assets: List[str]) -> List[str]:
        """
        动量资产选择（含并列处理）
        
        规则：
        - 按动量总分降序排名
        - 选择前7名资产
        - 并列处理：按得分从高到低分组，计算每组的平均排名
          - 平均排名 ≤ 7 的组全部入选
          - 平均排名 > 7 的组全部不入选
        """
        # 只考虑有效资产
        valid_scores = {k: v for k, v in scores.items() if k in valid_assets}
        if not valid_scores:
            return []
        
        # 转为Series并排序
        score_series = pd.Series(valid_scores).sort_values(ascending=False)
        
        # 按分数分组
        score_groups = score_series.groupby(score_series).groups
        unique_scores = sorted(score_groups.keys(), reverse=True)  # 降序
        
        momentum_selected = []
        current_rank = 0  # 当前已处理到的排名
        top_n = config.MOMENTUM_TOP_N  # 7
        
        for score in unique_scores:
            assets_with_score = list(score_groups[score])
            n_assets = len(assets_with_score)
            
            # 计算这组并列资产的排名范围
            start_rank = current_rank + 1
            end_rank = current_rank + n_assets
            
            # 计算平均排名
            avg_rank = (start_rank + end_rank) / 2
            
            if avg_rank <= top_n:
                # 平均排名 <= 7，都入选
                momentum_selected.extend(assets_with_score)
            else:
                # 平均排名 > 7，都不入选，结束
                break
            
            current_rank = end_rank
        
        return momentum_selected
    
    # =========================================================================
    # 反转因子计算
    # =========================================================================
    
    def _calc_reversal_scores(
        self,
        prices_df: pd.DataFrame,
        calc_date,
        rt: Optional["MonitorRuntimeConfig"] = None,
    ) -> Tuple[Dict[str, float], pd.DataFrame]:
        """
        计算所有资产的反转综合得分
        
        规则：
        - 双窗口偏度（默认 10、22 交易日，可由策略参数 reversal_windows 配置）
        - 偏度从低到高排序（负偏度优先，ascending=True）
        - 打分：排名第k → 得 N-k+1 分（N为有效资产数）
        - 综合得分 = 各窗口得分之和
        - 并列处理：使用平均排名（method='average'）
        
        Returns:
            scores: 各资产综合得分字典
            details: 详细信息DataFrame
        """
        if rt is None or rt.reversal_windows is None:
            windows = list(config.REVERSAL_WINDOWS)
        else:
            windows = list(rt.reversal_windows)
            if len(windows) != 2:
                windows = list(config.REVERSAL_WINDOWS)
        
        # 获取截止到计算日的数据
        date_idx = prices_df.index.get_loc(calc_date)
        price_data = prices_df.iloc[:date_idx + 1]
        
        details = {}
        total_scores = pd.Series(0.0, index=prices_df.columns)
        
        for win in windows:
            if len(price_data) > win:
                # 计算偏度
                skew = price_data.rolling(win).skew().iloc[-1]
                
                # 排名（升序，偏度小的排前面，使用平均排名处理并列）
                rank = skew.rank(ascending=True, method='average')
                
                # 打分：排名第k → 得 N-k+1 分
                # 有效资产数（非NaN的数量）
                valid_count = skew.notna().sum()
                score = (valid_count - rank + 1).fillna(0)
                
                total_scores += score
                
                details[f'Skew_{win}'] = skew
                details[f'Skew_{win}_rank'] = rank
                details[f'Skew_{win}_score'] = score
        
        details['反转综合得分'] = total_scores
        return total_scores.to_dict(), pd.DataFrame(details)
    
    def _select_reversal_assets(self, scores: Dict[str, float], 
                                 valid_assets: List[str]) -> List[str]:
        """
        反转资产选择
        
        规则：
        - 选择综合得分最高的1个资产
        - 并列处理：最高分有多个并列时全部不入选
        """
        # 只考虑有效资产
        valid_scores = {k: v for k, v in scores.items() if k in valid_assets}
        if not valid_scores:
            return []
        
        # 转为Series并排序
        score_series = pd.Series(valid_scores).sort_values(ascending=False)
        
        # 检查最高分是否有并列
        max_score = score_series.max()
        top_assets = score_series[score_series == max_score].index.tolist()
        
        if len(top_assets) == 1:
            # 唯一最高分，入选
            return top_assets
        else:
            # 并列最高分，都不入选
            return []
    
    # =========================================================================
    # 资产选择主逻辑
    # =========================================================================
    
    def run_asset_selection(
        self,
        prices_df: pd.DataFrame,
        calc_date,
        rt: Optional["MonitorRuntimeConfig"] = None,
    ) -> AssetSelectionResult:
        """
        对指定计算日执行资产选择
        
        Parameters:
            prices_df: 价格数据DataFrame，index为日期，columns为资产名
            calc_date: 计算日期（Timestamp或str）
            rt: 实盘监控运行时配置（含动量/反转窗口）；未传则使用 app.monitor.config 默认
            
        Returns:
            AssetSelectionResult: 资产选择结果
        """
        calc_date = pd.Timestamp(calc_date)
        date_idx = prices_df.index.get_loc(calc_date)
        
        if rt is None or rt.min_history_momentum is None:
            min_history_momentum = int(config.MIN_HISTORY_MOMENTUM)
        else:
            min_history_momentum = int(rt.min_history_momentum)
        if rt is None or rt.min_history_reversal is None:
            min_history_reversal = int(config.MIN_HISTORY_REVERSAL)
        else:
            min_history_reversal = int(rt.min_history_reversal)
        
        # 第一步：分别确定动量和反转的有效候选池
        momentum_valid_assets = []  # 动量有效资产（需260天历史数据）
        reversal_valid_assets = []  # 反转有效资产（需22天历史数据）
        
        for col in prices_df.columns:
            # 计算该资产到计算日为止的有效数据天数
            asset_data = prices_df[col].iloc[:date_idx + 1]
            valid_count = asset_data.notna().sum()
            
            # 动量有效资产：需要260天历史数据
            if valid_count >= min_history_momentum:
                momentum_valid_assets.append(col)
            
            # 反转有效资产：需要22天历史数据
            if valid_count >= min_history_reversal:
                reversal_valid_assets.append(col)
        
        # 第二步：动量模型打分（仅对动量有效资产）
        momentum_scores = {}
        momentum_selected = []
        
        if momentum_valid_assets:
            price_data_momentum = prices_df[momentum_valid_assets].iloc[:date_idx + 1]
            # 使用有效资产的价格数据重新计算得分
            mom_scores, _ = self._calc_momentum_scores(price_data_momentum, calc_date, rt=rt)
            momentum_scores = mom_scores
            momentum_selected = self._select_momentum_assets(mom_scores, momentum_valid_assets)
        
        # 第三步：反转模型（双窗口偏度）
        reversal_scores = {}
        reversal_selected = []
        
        if reversal_valid_assets:
            price_data_reversal = prices_df[reversal_valid_assets].iloc[:date_idx + 1]
            rev_scores, _ = self._calc_reversal_scores(price_data_reversal, calc_date, rt=rt)
            reversal_scores = rev_scores
            reversal_selected = self._select_reversal_assets(rev_scores, reversal_valid_assets)
        
        # 第四步：取并集（动量7 + 反转1）
        final_selected = list(set(momentum_selected + reversal_selected))
        
        # 构建入选状态
        selection_status = {}
        for asset in prices_df.columns:
            is_momentum = asset in momentum_selected
            is_reversal = asset in reversal_selected
            
            if is_momentum and is_reversal:
                selection_status[asset] = '动量+反转'
            elif is_momentum:
                selection_status[asset] = '动量'
            elif is_reversal:
                selection_status[asset] = '反转'
            else:
                selection_status[asset] = '未入选'
        
        # 转换得分为int类型（动量得分本质是整数）
        momentum_scores_int = {k: int(v) for k, v in momentum_scores.items()}
        
        return AssetSelectionResult(
            calc_date=str(calc_date.date()),
            momentum_selected=momentum_selected,
            reversal_selected=reversal_selected,
            final_selected=final_selected,
            selection_status=selection_status,
            momentum_scores=momentum_scores_int,
            reversal_scores=reversal_scores
        )
    
    # =========================================================================
    # 权重计算
    # =========================================================================
    
    def _calc_asset_volatility(self, prices_df: pd.DataFrame, 
                                calc_date) -> Dict[str, float]:
        """
        计算各资产波动率
        取22、65、130日年化波动率的最大值
        """
        date_idx = prices_df.index.get_loc(calc_date)
        returns = prices_df.pct_change()
        windows = config.VOL_WINDOWS  # [22, 65, 130]
        
        vols = {}
        for asset in prices_df.columns:
            asset_vols = []
            for w in windows:
                if date_idx >= w:
                    ret_window = returns[asset].iloc[date_idx - w + 1:date_idx + 1]
                    vol = ret_window.std() * self._annualize_factor
                    if not np.isnan(vol):
                        asset_vols.append(vol)
            
            if asset_vols:
                vols[asset] = max(asset_vols)
            else:
                vols[asset] = np.nan
        
        return vols
    
    def _calc_portfolio_volatility(self, prices_df: pd.DataFrame,
                                    weights: Dict[str, float],
                                    calc_date) -> float:
        """
        计算组合波动率
        使用权重加权的组合收益率，取22、65、130日年化波动率的最大值
        
        注意：对缺失的收益率数据使用fillna(0)处理
        """
        date_idx = prices_df.index.get_loc(calc_date)
        returns = prices_df.pct_change()
        windows = config.VOL_WINDOWS  # [22, 65, 130]
        
        # 只计算有权重的资产
        valid_assets = [a for a in weights.keys() if weights[a] > 0 and a in returns.columns]
        if not valid_assets:
            return 0.0
        
        port_vols = []
        for w in windows:
            if date_idx >= w:
                # 计算组合收益率
                # 对缺失的收益率使用fillna(0)，假设该资产当天无变动
                port_returns = pd.Series(0.0, index=returns.index)
                for asset in valid_assets:
                    port_returns += weights[asset] * returns[asset].fillna(0)
                
                ret_window = port_returns.iloc[date_idx - w + 1:date_idx + 1]
                vol = ret_window.std() * self._annualize_factor
                if not np.isnan(vol):
                    port_vols.append(vol)
        
        return max(port_vols) if port_vols else 0.0
    
    def _calc_risk_budgets(
        self,
        selection_result: AssetSelectionResult,
        risk_budget_both: float,
        risk_budget_single: float,
    ) -> Dict[str, float]:
        """
        根据入选情况分配风险预算
        - 仅动量入选：risk_budget_single
        - 仅反转入选：risk_budget_single
        - 两者都入选：risk_budget_both
        - 未入选：0
        """
        budgets = {}
        for asset, status in selection_result.selection_status.items():
            if status == '动量+反转':
                budgets[asset] = risk_budget_both
            elif status in ('动量', '反转'):
                budgets[asset] = risk_budget_single
            else:
                budgets[asset] = 0.0
        return budgets
    
    def _calc_initial_weights(self, risk_budgets: Dict[str, float], 
                               asset_vols: Dict[str, float],
                               target_vol: float) -> Dict[str, float]:
        """
        计算初始权重
        w_init = b × (target_vol / σ)
        """
        weights = {}
        
        for asset in risk_budgets.keys():
            b = risk_budgets[asset]
            sigma = asset_vols.get(asset, np.nan)
            
            if b > 0 and sigma > 0 and not np.isnan(sigma):
                weights[asset] = b * (target_vol / sigma)
            else:
                weights[asset] = 0.0
        
        return weights
    
    def _apply_scale_constraint(self, weights: Dict[str, float], 
                                 port_vol: float,
                                 target_vol: float,
                                 max_leverage: float) -> Tuple[Dict[str, float], float]:
        """
        应用组合波动率与杠杆约束
        scale = min(target_vol / σ_port, max_leverage / Σw)
        """
        total_weight = sum(weights.values())
        
        if total_weight <= 0:
            return weights, 1.0
        
        # 计算缩放系数
        scale_vol = target_vol / port_vol if port_vol > 0 else 1.0
        scale_leverage = max_leverage / total_weight
        scale = min(scale_vol, scale_leverage)
        
        # 缩放后权重
        scaled_weights = {k: v * scale for k, v in weights.items()}
        
        return scaled_weights, scale
    
    def _apply_weight_caps(self, weights: Dict[str, float],
                           weight_caps: Dict[str, float]) -> Dict[str, float]:
        """
        应用权重上限截断
        只截断超限权重，不做再分配
        """
        if sum(weights.values()) <= 0:
            return weights
        
        capped_weights = weights.copy()
        
        for asset in capped_weights.keys():
            cap = weight_caps.get(asset, 1.0)
            if capped_weights[asset] > cap:
                capped_weights[asset] = cap
        
        return capped_weights
    
    def run_weight_calculation(self, prices_df: pd.DataFrame, 
                                selection_result: AssetSelectionResult,
                                calc_date,
                                rt: Optional["MonitorRuntimeConfig"] = None) -> WeightResult:
        """
        对指定计算日执行权重计算
        
        Parameters:
            prices_df: 价格数据DataFrame
            selection_result: 资产选择结果
            calc_date: 计算日期
            
        Returns:
            WeightResult: 权重计算结果
        """
        calc_date = pd.Timestamp(calc_date)

        risk_budget_both = rt.risk_budget_both if rt else (2 / 8)
        risk_budget_single = rt.risk_budget_single if rt else (1 / 8)
        target_vol = rt.target_vol if rt else float(config.TARGET_VOL)
        max_leverage = rt.max_leverage if rt else float(config.MAX_LEVERAGE)
        caps = rt.weight_caps if rt else _DEFAULT_MONITOR_WEIGHT_CAPS
        
        # 1. 计算风险预算
        risk_budgets = self._calc_risk_budgets(
            selection_result, risk_budget_both, risk_budget_single
        )
        
        # 2. 计算资产波动率
        asset_vols = self._calc_asset_volatility(prices_df, calc_date)
        
        # 3. 计算初始权重
        initial_weights = self._calc_initial_weights(risk_budgets, asset_vols, target_vol)
        
        # 4. 计算组合波动率（使用初始权重）
        port_vol = self._calc_portfolio_volatility(prices_df, initial_weights, calc_date)
        
        # 5. 应用缩放约束
        scaled_weights, scale_factor = self._apply_scale_constraint(
            initial_weights, port_vol, target_vol, max_leverage
        )
        
        # 6. 应用权重上限截断
        final_weights = self._apply_weight_caps(scaled_weights, caps)
        
        # 计算总杠杆
        total_leverage = sum(final_weights.values())
        
        return WeightResult(
            calc_date=str(calc_date.date()),
            weights=final_weights,
            risk_budgets=risk_budgets,
            asset_vols=asset_vols,
            initial_weights=initial_weights,
            scaled_weights=scaled_weights,
            portfolio_vol=port_vol,
            scale_factor=scale_factor,
            total_leverage=total_leverage
        )

    # =========================================================================
    # 纯权重分配型策略（etf_cycle_rotation / risk_parity）
    # =========================================================================

    # template_code → 策略实现类的映射表（避免每次调用时动态导入）
    _ALLOCATION_STRATEGY_MAP = {
        "etf_cycle_rotation": "app.strategies.models.etf_cycle_rotation.ETFCycleRotationStrategy",
        "risk_parity": "app.strategies.models.risk_parity.RiskParityStrategy",
    }

    def _load_allocation_strategy_class(self, template_code: str):
        """根据 template_code 加载策略实现类。"""
        qualified = self._ALLOCATION_STRATEGY_MAP.get(template_code)
        if qualified is None:
            raise ValueError(f"不支持的纯权重分配策略: {template_code}")
        module_path, cls_name = qualified.rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, cls_name)

    def run_weight_calculation_for_allocation_strategy(
        self,
        prices_df: pd.DataFrame,
        calc_date,
        rt: "MonitorRuntimeConfig",
    ) -> WeightResult:
        """
        纯权重分配型策略的权重计算（etf_cycle_rotation / risk_parity）。
        直接调用策略的 allocate() 方法，不需要资产选择步骤。

        Args:
            prices_df: 价格数据 DataFrame，index 为日期，columns 为资产代码
            calc_date: 计算日期
            rt: 运行时配置（必须包含 template_code 和 strategy_params）

        Returns:
            WeightResult 权重计算结果
        """
        calc_date = pd.Timestamp(calc_date)
        calc_date_str = str(calc_date.date()) if hasattr(calc_date, 'date') else str(calc_date)
        empty_weights: Dict[str, float] = {a: 0.0 for a in rt.asset_list}

        try:
            # 1. 加载策略实现类并实例化
            strategy_cls = self._load_allocation_strategy_class(rt.template_code)
            strategy_impl = strategy_cls()

            # 2. 截取 rt.asset_list 中存在于 prices_df 的列
            use_cols = [c for c in rt.asset_list if c in prices_df.columns]
            if not use_cols:
                logger.warning("[allocation] 资产列表与价格列无交集，返回空权重")
                return self._empty_weight_result(calc_date_str, empty_weights)

            asset_prices = prices_df.loc[:calc_date, use_cols]
            if asset_prices.empty:
                logger.warning("[allocation] 截取后价格数据为空，返回空权重")
                return self._empty_weight_result(calc_date_str, empty_weights)

            # 3. 调用 allocate()
            params = dict(rt.strategy_params) if rt.strategy_params else {}
            weights_series = strategy_impl.allocate(asset_prices, **params)

            # 4. 转为字典
            if hasattr(weights_series, 'to_dict'):
                weights_dict: Dict[str, float] = weights_series.to_dict()
            else:
                weights_dict = dict(weights_series)

            # 5. 补齐 asset_list 中缺失的资产（权重=0）
            for a in rt.asset_list:
                if a not in weights_dict:
                    weights_dict[a] = 0.0

            # 6. 应用权重上限
            caps = rt.weight_caps or {}
            for asset, w in weights_dict.items():
                cap = caps.get(asset, 1.0)
                if w > cap:
                    weights_dict[asset] = cap

            total_leverage = sum(weights_dict.values())

            logger.info(
                "[allocation] template=%s calc_date=%s total_leverage=%.4f",
                rt.template_code, calc_date_str, total_leverage,
            )

            return WeightResult(
                calc_date=calc_date_str,
                weights=weights_dict,
                risk_budgets={a: 0.0 for a in weights_dict},
                asset_vols={a: 0.0 for a in weights_dict},
                initial_weights=dict(weights_dict),
                scaled_weights=dict(weights_dict),
                portfolio_vol=0.0,
                scale_factor=1.0,
                total_leverage=total_leverage,
            )

        except Exception as exc:
            logger.error(
                "[allocation] 策略 %s 权重计算异常: %s",
                rt.template_code, exc, exc_info=True,
            )
            return self._empty_weight_result(calc_date_str, empty_weights)

    @staticmethod
    def _empty_weight_result(calc_date_str: str, weights: Dict[str, float]) -> WeightResult:
        """构建全零的 WeightResult（用于异常兜底）。"""
        return WeightResult(
            calc_date=calc_date_str,
            weights=weights,
            risk_budgets={a: 0.0 for a in weights},
            asset_vols={a: 0.0 for a in weights},
            initial_weights={a: 0.0 for a in weights},
            scaled_weights={a: 0.0 for a in weights},
            portfolio_vol=0.0,
            scale_factor=1.0,
            total_leverage=0.0,
        )
