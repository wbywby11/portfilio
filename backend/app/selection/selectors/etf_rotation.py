"""ETF轮动资产选择器.

从 etf_cycle_rotation.py 提取的 ETF 轮动选择逻辑，
支持四种子策略通过参数切换：
- volatility: 波动率轮动
- return_bias: 收益+乖离率
- mixed: 混合因子
- breakthrough: 强势突破
"""

from __future__ import annotations

import pandas as pd

from app.selection.selectors.base import BaseAssetSelector
from app.selection.types import SelectionResult


class ETFRotationSelector(BaseAssetSelector):
    """ETF轮动选择器：因子打分排序.

    支持四种子策略：
    - volatility: 剔除收益率后20%，选波动率最高的 N 只
    - return_bias: 剔除收益率后20%，选收益率前N且乖离率<阈值
    - mixed: 波动率前3 + 收益率前2(乖离率<阈值)
    - breakthrough: 涨幅前30剔除乖离率过高，选前N
    """

    @classmethod
    def get_param_schema(cls):
        return {
            "selector_type": "etf_rotation",
            "display_name": "ETF轮动",
            "description": "ETF轮动选择器，支持波动率轮动、收益+乖离率、混合因子、强势突破四种子策略。与ETF轮动等权策略逻辑一致。",
            "params": [
                {
                    "name": "sub_strategy",
                    "label": "子策略类型",
                    "type": "select",
                    "default": "volatility",
                    "options": [
                        ("volatility", "波动率轮动"),
                        ("return_bias", "收益+乖离率"),
                        ("mixed", "混合因子"),
                        ("breakthrough", "强势突破"),
                    ],
                    "description": "选择轮动子策略",
                },
                {
                    "name": "lookback_days",
                    "label": "回看天数",
                    "type": "number",
                    "default": 20,
                    "min_value": 10,
                    "max_value": 60,
                    "step": 1,
                    "description": "计算收益率、波动率、乖离率的回看天数",
                },
                {
                    "name": "return_cutoff_pct",
                    "label": "收益率剔除比例",
                    "type": "slider",
                    "default": 0.2,
                    "min_value": 0.0,
                    "max_value": 0.5,
                    "step": 0.05,
                    "description": "剔除收益率排名后X%的ETF",
                },
                {
                    "name": "bias_threshold",
                    "label": "乖离率阈值(%)",
                    "type": "number",
                    "default": 10.0,
                    "min_value": 0.0,
                    "max_value": 50.0,
                    "step": 1.0,
                    "description": "乖离率超过此阈值的ETF将被剔除",
                },
                {
                    "name": "risk_index_code",
                    "label": "风控指数代码",
                    "type": "text",
                    "default": "000001.SH",
                    "description": "用于风控判断的指数代码（需加入资产列表），如上证指数 000001.SH",
                },
                {
                    "name": "risk_drop_threshold",
                    "label": "风控跌幅阈值",
                    "type": "number",
                    "default": -0.02,
                    "min_value": -0.1,
                    "max_value": 0.0,
                    "step": 0.005,
                    "description": "风控指数周跌幅低于此值时触发风控（如 -0.02 表示跌幅超2%）",
                },
            ],
        }

    # ------------------------------------------------------------------
    # 辅助计算方法
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_return(prices: pd.DataFrame, lookback: int) -> pd.Series:
        if len(prices) < lookback + 1:
            return pd.Series(dtype=float)
        current = prices.iloc[-1]
        past = prices.iloc[-(lookback + 1)]
        ret = current / past - 1
        return ret.dropna()

    @staticmethod
    def _calc_volatility(prices: pd.DataFrame, lookback: int) -> pd.Series:
        if len(prices) < lookback + 1:
            return pd.Series(dtype=float)
        recent = prices.iloc[-(lookback + 1):]
        daily_returns = recent.pct_change(fill_method=None).iloc[1:]
        return daily_returns.std().dropna()

    @staticmethod
    def _calc_bias(prices: pd.DataFrame, lookback: int) -> pd.Series:
        if len(prices) < lookback:
            return pd.Series(dtype=float)
        recent = prices.iloc[-lookback:]
        ma = recent.mean()
        current = prices.iloc[-1]
        bias = (current - ma) / ma * 100
        return bias.dropna()

    @staticmethod
    def _remove_bottom_return(returns: pd.Series, cutoff_pct: float) -> list:
        if len(returns) == 0:
            return []
        cutoff = int(len(returns) * cutoff_pct)
        if cutoff > 0:
            sorted_ret = returns.sort_values(ascending=True)
            bottom = set(sorted_ret.index[:cutoff].tolist())
            return [e for e in returns.index if e not in bottom]
        return returns.index.tolist()

    # ------------------------------------------------------------------
    # 四种子策略
    # ------------------------------------------------------------------

    def _select_volatility(self, prices, etf_pool, lookback, top_n, cutoff_pct, **_):
        returns = self._calc_return(prices, lookback).reindex(etf_pool).dropna()
        remaining = self._remove_bottom_return(returns, cutoff_pct)
        if not remaining:
            return []
        vol = self._calc_volatility(prices, lookback).reindex(remaining).dropna()
        if vol.empty:
            return []
        return vol.sort_values(ascending=False).head(top_n).index.tolist()

    def _select_return_bias(self, prices, etf_pool, lookback, top_n, cutoff_pct, bias_threshold, risk_triggered=False, **_):
        if risk_triggered:
            return []
        returns = self._calc_return(prices, lookback).reindex(etf_pool).dropna()
        remaining = self._remove_bottom_return(returns, cutoff_pct)
        if not remaining:
            return []
        bias = self._calc_bias(prices, lookback)
        returns_sorted = returns.reindex(remaining).sort_values(ascending=False)
        selected = []
        for etf in returns_sorted.index:
            if etf in bias.index and bias[etf] < bias_threshold:
                selected.append(etf)
                if len(selected) >= top_n:
                    break
        return selected

    def _select_mixed(self, prices, etf_pool, lookback, top_n, cutoff_pct, bias_threshold, risk_triggered=False, **_):
        returns = self._calc_return(prices, lookback).reindex(etf_pool).dropna()
        remaining = self._remove_bottom_return(returns, cutoff_pct)
        if not remaining:
            return []
        selected = set()
        vol = self._calc_volatility(prices, lookback).reindex(remaining).dropna()
        vol_count = min(3, top_n)
        if not vol.empty:
            selected.update(vol.sort_values(ascending=False).head(vol_count).index.tolist())
        if not risk_triggered:
            bias = self._calc_bias(prices, lookback)
            returns_sorted = returns.reindex(remaining).sort_values(ascending=False)
            ret_count = max(top_n - vol_count, 2)
            count = 0
            for etf in returns_sorted.index:
                if etf not in selected and etf in bias.index and bias[etf] < bias_threshold:
                    selected.add(etf)
                    count += 1
                    if count >= ret_count:
                        break
        return list(selected)[:top_n]

    def _select_breakthrough(self, prices, etf_pool, lookback, top_n, bias_threshold, risk_triggered=False, **_):
        if risk_triggered:
            return []
        returns = self._calc_return(prices, lookback).reindex(etf_pool).dropna()
        if returns.empty:
            return []
        top30 = returns.sort_values(ascending=False).head(30)
        bias = self._calc_bias(prices, lookback)
        remaining = [etf for etf in top30.index if etf in bias.index and not pd.isna(bias[etf]) and bias[etf] <= bias_threshold]
        if not remaining:
            return []
        return returns.reindex(remaining).sort_values(ascending=False).head(top_n).index.tolist()

    # ------------------------------------------------------------------
    # 风控指数计算
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_risk_index_weekly_change(prices: pd.DataFrame, risk_col: str) -> float:
        """计算风控指数的近一周跌幅."""
        if risk_col not in prices.columns:
            return 0.0
        risk_prices = prices[risk_col].dropna()
        if len(risk_prices) < 5:
            return 0.0
        recent = risk_prices.iloc[-5:]
        first_price = recent.iloc[0]
        last_price = recent.iloc[-1]
        if first_price == 0 or pd.isna(first_price):
            return 0.0
        return float(last_price / first_price - 1)

    # ------------------------------------------------------------------
    # select 入口
    # ------------------------------------------------------------------

    def select(
        self,
        prices: pd.DataFrame,
        n_assets: int,
        **params,
    ) -> SelectionResult:
        """执行 ETF 轮动选择.

        Args:
            prices: ETF 价格矩阵（可能包含 risk_index_code）
            n_assets: 选择数量 (top_n)
            **params: 子策略参数

        Returns:
            SelectionResult
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        sub = params.get("sub_strategy", "volatility")
        lookback = int(params.get("lookback_days", 20))
        top_n = n_assets if n_assets > 0 else int(params.get("top_n", 5))
        cutoff_pct = float(params.get("return_cutoff_pct", 0.2))
        bias_threshold = float(params.get("bias_threshold", 10.0))
        risk_triggered = bool(params.get("risk_triggered", False))

        # 提取风控指数并自动计算 risk_triggered
        risk_index_code = str(params.get("risk_index_code", ""))
        risk_drop_threshold = float(params.get("risk_drop_threshold", -0.02))
        if risk_index_code and risk_index_code in prices.columns:
            weekly_change = self._calc_risk_index_weekly_change(prices, risk_index_code)
            risk_triggered = risk_triggered or (weekly_change < risk_drop_threshold)

        # ETF候选池 = 全部资产 - 风控指数
        etf_pool = [str(c) for c in prices.columns if str(c) != risk_index_code]

        dispatch = {
            "volatility": self._select_volatility,
            "return_bias": self._select_return_bias,
            "mixed": self._select_mixed,
            "breakthrough": self._select_breakthrough,
        }
        select_fn = dispatch.get(sub)
        if select_fn is None:
            raise ValueError(f"未知子策略: {sub}")

        selected = select_fn(
            prices=prices,
            etf_pool=etf_pool,
            lookback=lookback,
            top_n=top_n,
            cutoff_pct=cutoff_pct,
            bias_threshold=bias_threshold,
            risk_triggered=risk_triggered,
        )

        scores = {a: (1.0 if a in selected else 0.0) for a in etf_pool}
        ranking = pd.DataFrame({
            "Asset": etf_pool,
            "Selected": [a in selected for a in etf_pool],
        }).set_index("Asset")

        return SelectionResult(
            selected_assets=selected,
            scores=scores,
            ranking=ranking,
            timestamp=pd.Timestamp.now().isoformat(),
            selector_type="etf_rotation",
            params=params,
        )
