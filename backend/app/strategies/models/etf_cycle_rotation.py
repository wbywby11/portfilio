"""ETF周期轮动策略 - 四种子策略通过参数切换

支持四种轮动子策略：
- volatility: 波动率轮动 - 剔除收益率后20%，选波动率最高的N只
- return_bias: 收益+乖离率 - 剔除收益率后20%，选收益率前N且乖离率<阈值，风控空仓
- mixed: 混合因子 - 波动率前3 + 收益率前2(乖离率<阈值)，风控时仅选波动率前3
- breakthrough: 强势突破 - 涨幅前30剔除乖离率过高，选前N，风控空仓

所有子策略使用周频调仓，等权分配。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategies.models.base import BaseStrategyModel


class ETFCycleRotationStrategy(BaseStrategyModel):
    """ETF周期轮动策略 - 四种子策略通过参数切换"""

    @classmethod
    def get_param_schema(cls):
        """返回ETF周期轮动策略的参数Schema."""
        from app.strategies.models.param_schema import StrategyParamSchema, ParamSchema

        return StrategyParamSchema(
            strategy_type="etf_cycle_rotation",
            display_name="ETF周期轮动策略",
            description="基于ETF的周频轮动策略，支持波动率轮动、收益+乖离率、混合因子、强势突破四种子策略",
            params=[
                ParamSchema(
                    name="sub_strategy",
                    label="子策略类型",
                    type="select",
                    default="volatility",
                    options=[
                        ("volatility", "波动率轮动"),
                        ("return_bias", "收益+乖离率"),
                        ("mixed", "混合因子"),
                        ("breakthrough", "强势突破"),
                    ],
                    description="选择轮动子策略",
                ),
                ParamSchema(
                    name="lookback_days",
                    label="回看天数",
                    type="number",
                    default=20,
                    min_value=10,
                    max_value=60,
                    step=1,
                    description="计算收益率、波动率、乖离率的回看天数",
                ),
                ParamSchema(
                    name="top_n",
                    label="持仓ETF数量",
                    type="number",
                    default=5,
                    min_value=1,
                    max_value=20,
                    step=1,
                    description="每期选出的ETF数量",
                ),
                ParamSchema(
                    name="return_cutoff_pct",
                    label="收益率剔除比例",
                    type="slider",
                    default=0.2,
                    min_value=0.0,
                    max_value=0.5,
                    step=0.05,
                    description="剔除收益率排名后X%的ETF",
                ),
                ParamSchema(
                    name="bias_threshold",
                    label="乖离率阈值(%)",
                    type="number",
                    default=10.0,
                    min_value=0.0,
                    max_value=50.0,
                    step=1.0,
                    description="乖离率超过此阈值的ETF将被剔除",
                ),
                ParamSchema(
                    name="risk_index_code",
                    label="风控指数代码",
                    type="text",
                    default="000001.SH",
                    description="用于风控判断的指数代码（需加入资产列表），如上证指数 000001.SH",
                ),
                ParamSchema(
                    name="risk_drop_threshold",
                    label="风控跌幅阈值",
                    type="number",
                    default=-0.02,
                    min_value=-0.1,
                    max_value=0.0,
                    step=0.005,
                    description="风控指数周跌幅低于此值时触发风控（如 -0.02 表示跌幅超2%）",
                ),
            ],
        )

    # ------------------------------------------------------------------
    # 公共计算函数
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_return(prices: pd.DataFrame, lookback: int) -> pd.Series:
        """计算各资产的 N 日收益率.

        Args:
            prices: 收盘价矩阵 (index=日期, columns=资产)
            lookback: 回看天数

        Returns:
            Series, index=资产代码, value=收益率
        """
        if len(prices) < lookback + 1:
            return pd.Series(dtype=float)
        current = prices.iloc[-1]
        past = prices.iloc[-(lookback + 1)]
        ret = current / past - 1
        return ret.dropna()

    @staticmethod
    def _calc_volatility(prices: pd.DataFrame, lookback: int) -> pd.Series:
        """计算各资产的 N 日波动率（日收益率标准差）.

        Args:
            prices: 收盘价矩阵
            lookback: 回看天数

        Returns:
            Series, index=资产代码, value=波动率
        """
        if len(prices) < lookback + 1:
            return pd.Series(dtype=float)
        recent = prices.iloc[-(lookback + 1):]
        daily_returns = recent.pct_change().iloc[1:]
        return daily_returns.std().dropna()

    @staticmethod
    def _calc_bias(prices: pd.DataFrame, lookback: int) -> pd.Series:
        """计算各资产的乖离率 = (close - MA) / MA * 100 (%).

        Args:
            prices: 收盘价矩阵
            lookback: 回看天数

        Returns:
            Series, index=资产代码, value=乖离率(%)
        """
        if len(prices) < lookback:
            return pd.Series(dtype=float)
        recent = prices.iloc[-lookback:]
        ma = recent.mean()
        current = prices.iloc[-1]
        bias = (current - ma) / ma * 100
        return bias.dropna()

    @staticmethod
    def _calc_risk_index_weekly_change(prices: pd.DataFrame, risk_col: str) -> float:
        """计算风控指数的近一周跌幅（用最近5个交易日的首尾收盘价估算）.

        Args:
            prices: 收盘价矩阵
            risk_col: 风控指数所在列名

        Returns:
            float: 周涨跌幅（负数表示下跌）
        """
        if risk_col not in prices.columns:
            return 0.0
        risk_prices = prices[risk_col].dropna()
        if len(risk_prices) < 5:
            return 0.0
        # 用最近5个交易日的首尾收盘价近似周涨跌幅
        recent = risk_prices.iloc[-5:]
        first_price = recent.iloc[0]
        last_price = recent.iloc[-1]
        if first_price == 0 or pd.isna(first_price):
            return 0.0
        return float(last_price / first_price - 1)

    def _remove_bottom_return(
        self, returns: pd.Series, cutoff_pct: float
    ) -> list[str]:
        """剔除收益率排名后 cutoff_pct 的资产，返回剩余资产代码列表."""
        if len(returns) == 0:
            return []
        cutoff = int(len(returns) * cutoff_pct)
        if cutoff > 0:
            sorted_ret = returns.sort_values(ascending=True)
            bottom = set(sorted_ret.index[:cutoff].tolist())
            return [e for e in returns.index if e not in bottom]
        return returns.index.tolist()

    @staticmethod
    def _equal_weight(selected: list[str], all_assets: pd.Index) -> pd.Series:
        """对选中资产返回等权权重，未选中返回 0."""
        weights = pd.Series(0.0, index=all_assets)
        if len(selected) == 0:
            return weights
        w = 1.0 / len(selected)
        for code in selected:
            if code in weights.index:
                weights[code] = w
        return weights

    # ------------------------------------------------------------------
    # 四种子策略选股逻辑
    # ------------------------------------------------------------------

    def _select_volatility(
        self,
        prices: pd.DataFrame,
        etf_pool: list[str],
        lookback: int,
        top_n: int,
        cutoff_pct: float,
        **_extra,
    ) -> list[str]:
        """波动率轮动：剔除收益率后20% -> 选波动率最高的 N 只."""
        returns = self._calc_return(prices, lookback)
        returns = returns.reindex(etf_pool).dropna()
        remaining = self._remove_bottom_return(returns, cutoff_pct)
        if not remaining:
            return []
        vol = self._calc_volatility(prices, lookback)
        vol = vol.reindex(remaining).dropna()
        if vol.empty:
            return []
        return vol.sort_values(ascending=False).head(top_n).index.tolist()

    def _select_return_bias(
        self,
        prices: pd.DataFrame,
        etf_pool: list[str],
        lookback: int,
        top_n: int,
        cutoff_pct: float,
        bias_threshold: float,
        risk_triggered: bool,
        **_extra,
    ) -> list[str]:
        """收益+乖离率：风控触发空仓；否则剔除收益率后20% -> 选收益率前N且乖离率<阈值."""
        if risk_triggered:
            return []
        returns = self._calc_return(prices, lookback)
        returns = returns.reindex(etf_pool).dropna()
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

    def _select_mixed(
        self,
        prices: pd.DataFrame,
        etf_pool: list[str],
        lookback: int,
        top_n: int,
        cutoff_pct: float,
        bias_threshold: float,
        risk_triggered: bool,
        **_extra,
    ) -> list[str]:
        """混合因子：波动率前3 + 收益率前2(乖离率<阈值)；风控时仅波动率前3."""
        returns = self._calc_return(prices, lookback)
        returns = returns.reindex(etf_pool).dropna()
        remaining = self._remove_bottom_return(returns, cutoff_pct)
        if not remaining:
            return []

        selected: set[str] = set()

        # 波动率前3
        vol = self._calc_volatility(prices, lookback)
        vol = vol.reindex(remaining).dropna()
        vol_count = min(3, top_n)
        if not vol.empty:
            top_vol = vol.sort_values(ascending=False).head(vol_count).index.tolist()
            selected.update(top_vol)

        # 风控未触发时加入收益率前2且乖离率<阈值
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

    def _select_breakthrough(
        self,
        prices: pd.DataFrame,
        etf_pool: list[str],
        lookback: int,
        top_n: int,
        bias_threshold: float,
        risk_triggered: bool,
        **_extra,
    ) -> list[str]:
        """强势突破：风控空仓；否则选涨幅前30 -> 剔除乖离率>阈值 -> 选前N."""
        if risk_triggered:
            return []
        returns = self._calc_return(prices, lookback)
        returns = returns.reindex(etf_pool).dropna()
        if returns.empty:
            return []
        top30 = returns.sort_values(ascending=False).head(30)
        bias = self._calc_bias(prices, lookback)
        remaining = [
            etf for etf in top30.index
            if etf in bias.index and not pd.isna(bias[etf]) and bias[etf] <= bias_threshold
        ]
        if not remaining:
            return []
        return returns.reindex(remaining).sort_values(ascending=False).head(top_n).index.tolist()

    # ------------------------------------------------------------------
    # allocate 入口
    # ------------------------------------------------------------------

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """根据 sub_strategy 参数分发到对应子策略.

        Args:
            prices: 收盘价矩阵 (index=日期, columns=资产代码)，
                    其中可能包含 risk_index_code 对应的风控指数列。
            **params: 策略参数

        Returns:
            Series, 各资产权重（等权或全零）
        """
        if prices.empty:
            return pd.Series(dtype=float)

        sub = params.get("sub_strategy", "volatility")
        lookback = int(params.get("lookback_days", 20))
        top_n = int(params.get("top_n", 5))
        cutoff_pct = float(params.get("return_cutoff_pct", 0.2))
        bias_threshold = float(params.get("bias_threshold", 10.0))
        risk_index_code = str(params.get("risk_index_code", "000001.SH"))
        risk_drop_threshold = float(params.get("risk_drop_threshold", -0.02))

        # 分离风控指数和ETF候选池
        all_cols = prices.columns.tolist()
        etf_pool = [c for c in all_cols if str(c) != risk_index_code]

        # 计算风控指数周跌幅
        risk_triggered = False
        if risk_index_code in all_cols:
            weekly_change = self._calc_risk_index_weekly_change(prices, risk_index_code)
            risk_triggered = weekly_change < risk_drop_threshold

        # 公共参数
        kw = dict(
            prices=prices,
            etf_pool=etf_pool,
            lookback=lookback,
            top_n=top_n,
            cutoff_pct=cutoff_pct,
            bias_threshold=bias_threshold,
            risk_triggered=risk_triggered,
        )

        # 分发子策略
        dispatch = {
            "volatility": self._select_volatility,
            "return_bias": self._select_return_bias,
            "mixed": self._select_mixed,
            "breakthrough": self._select_breakthrough,
        }
        select_fn = dispatch.get(sub)
        if select_fn is None:
            raise ValueError(f"未知的子策略类型: {sub}，可选: {list(dispatch.keys())}")

        selected = select_fn(**kw)

        # 返回等权权重（风控指数权重始终为 0）
        return self._equal_weight(selected, prices.columns)
