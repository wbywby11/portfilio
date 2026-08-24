"""夏普率综合打分资产选择器 (Sharpe Score Asset Selector)

与原型 step1_asset_selection.py 完全一致：
1. 3窗口夏普率综合打分（22/65/260日）
   - SHARP_n = (P_t / P_{t-n} - 1) / std(daily_ret, n)
   - daily_ret = prices.pct_change(fill_method=None)
2. rank(ascending=True, method='average') → 各窗口rank之和=综合打分
3. tie-breaker: 22日MOM动量（P_t/P_{t-22}-1）
4. 从有效资产（≥min_history天）中选择 top N
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.selection.selectors.base import BaseAssetSelector
from app.selection.types import SelectionResult


def _calc_sharp_ratio(prices: pd.DataFrame, n: int) -> pd.DataFrame:
    """
    计算 SHARP 动量因子（与原型 calc_sharp_ratio 完全一致）

    SHARP_n = (P_t / P_{t-n} - 1) / std(daily_ret, n)

    Parameters
    ----------
    prices : pd.DataFrame
        价格矩阵，index=日期，columns=资产
    n : int
        回望窗口天数

    Returns
    -------
    pd.DataFrame
        与 prices 同形状的 SHARP 因子矩阵
    """
    cum_ret = prices / prices.shift(n) - 1
    daily_ret = prices.pct_change(fill_method=None)
    vol = daily_ret.rolling(n).std()
    sharp = cum_ret / vol
    return sharp.replace([np.inf, -np.inf], np.nan)


def _calc_mom_22(prices: pd.DataFrame) -> pd.DataFrame:
    """
    计算 22 日 MOM 动量（tie-breaker）

    MOM_22 = P_t / P_{t-22} - 1
    """
    return prices / prices.shift(22) - 1


class SharpeSelector(BaseAssetSelector):
    """夏普率综合打分资产选择器

    与原型 step1_asset_selection.py 完全一致。
    在所有资产上计算排名，仅从有效资产（≥min_history天）中选择 top N。
    """

    @classmethod
    def get_param_schema(cls):
        """返回夏普率选择器的参数 Schema."""
        return {
            "selector_type": "sharpe",
            "display_name": "夏普率综合打分",
            "description": (
                "3窗口夏普率综合打分，选 top N 资产。"
                "并列时用22日MOM动量决胜。"
                "与大类资产配置指数编制规则完全一致。"
            ),
            "params": [
                {
                    "name": "min_history_days",
                    "label": "最小历史数据要求",
                    "type": "number",
                    "default": 260,
                    "min_value": 100,
                    "max_value": 500,
                    "step": 10,
                    "description": "资产进入候选池的最小交易日数（默认260天）",
                },
                {
                    "name": "sharp_windows",
                    "label": "夏普率窗口",
                    "type": "text",
                    "default": "22,65,260",
                    "description": "夏普率计算窗口（交易日），逗号分隔，默认22/65/260",
                    "group": "advanced",
                },
                {
                    "name": "tie_break_window",
                    "label": "并列决胜窗口",
                    "type": "number",
                    "default": 22,
                    "min_value": 5,
                    "max_value": 260,
                    "step": 1,
                    "description": "综合打分相同时，优先选择该窗口MOM更高的资产（默认22天）",
                    "group": "advanced",
                },
            ],
        }

    def select(
        self,
        prices: pd.DataFrame,
        n_assets: int,
        **params,
    ) -> SelectionResult:
        """执行夏普率综合打分资产选择.

        Args:
            prices: 候选资产价格矩阵（index: 日期，columns: 资产代码）
            n_assets: 选择资产数量（默认13）
            **params:
                - min_history_days: 最小历史数据要求（默认260）
                - sharp_windows: 夏普率窗口（默认"22,65,260"）
                - tie_break_window: 并列决胜窗口（默认22）

        Returns:
            SelectionResult: 选择结果
        """
        if prices.empty:
            raise ValueError("prices DataFrame 为空")
        if n_assets <= 0:
            raise ValueError(f"n_assets 必须大于0，当前值：{n_assets}")

        # ---- 参数 ----
        min_history = int(params.get("min_history_days", 260))
        # 兼容：优先 sharp_windows，回退到 momentum_windows（回测 API 统一传 momentum_windows）
        windows_str = params.get("sharp_windows") or params.get("momentum_windows", "22,65,260")
        tie_break_win = int(params.get("tie_break_window", 22))

        try:
            windows = [int(w.strip()) for w in str(windows_str).split(",")]
        except Exception as e:
            raise ValueError(f"sharp_windows 参数格式错误：{windows_str}，错误：{e}")

        # ---- 第一步：确定有效资产池 ----
        all_assets = list(prices.columns)
        valid_assets = []
        for col in all_assets:
            valid_count = prices[col].notna().sum()
            if valid_count >= min_history:
                valid_assets.append(col)

        if not valid_assets:
            return SelectionResult(
                selected_assets=[],
                scores={a: 0.0 for a in all_assets},
                ranking=pd.DataFrame(),
                timestamp=pd.Timestamp.now().isoformat(),
                selector_type="sharpe",
                params=params,
            )

        # ---- 第二步：夏普率综合打分 ----
        # 在所有资产上计算 SHARP 和排名
        price_all = prices.copy()
        total_score = pd.Series(0.0, index=all_assets)
        details = {}

        for n in windows:
            if len(price_all) > n:
                factor = _calc_sharp_ratio(price_all, n).iloc[-1]
                # 排名：ascending=True，Sharpe 越大 rank 数值越大
                rank = factor.rank(ascending=True, method="average")
                # NaN 资产不参与排名，fillna(0) 贡献 0
                total_score += rank.fillna(0)
                details[f"SHARP_{n}"] = factor
                details[f"SHARP_{n}_rank"] = rank

        details["综合打分"] = total_score

        # ---- 计算 MOM tie-breaker ----
        mom_22 = _calc_mom_22(price_all).iloc[-1]

        # ---- 仅对有效资产排序 ----
        ranking_data = pd.DataFrame(
            {
                "综合打分": total_score.loc[valid_assets],
                "MOM_22_tiebreak": mom_22.loc[valid_assets],
            }
        )

        # 排序：先按综合打分降序（大的在前），再按 MOM_22 降序（大的在前）
        ranking_data = ranking_data.sort_values(
            by=["综合打分", "MOM_22_tiebreak"],
            ascending=[False, False],
        )

        # 构建排名详情 DataFrame
        ranking_df = pd.DataFrame(
            {
                "Asset": ranking_data.index,
                "TotalScore": ranking_data["综合打分"].values,
                "MOM_22": ranking_data["MOM_22_tiebreak"].values,
                "Rank": range(1, len(ranking_data) + 1),
            }
        )
        ranking_df["Selected"] = ranking_df["Rank"] <= n_assets

        # 添加各窗口详细信息
        for asset in ranking_df["Asset"]:
            if asset in details.get("综合打分", pd.Series()).index:
                for col_name, series in details.items():
                    if isinstance(series, pd.Series) and asset in series.index:
                        ranking_df.loc[ranking_df["Asset"] == asset, col_name] = (
                            series.loc[asset]
                        )

        # ---- 选择 top n_assets 个 ----
        selected_assets = ranking_data.index[:n_assets].tolist()

        # 构建 scores 字典（所有资产的综合打分）
        scores = {a: float(total_score.get(a, 0.0)) for a in all_assets}

        return SelectionResult(
            selected_assets=selected_assets,
            scores=scores,
            ranking=ranking_df,
            timestamp=pd.Timestamp.now().isoformat(),
            selector_type="sharpe",
            params=params,
        )
