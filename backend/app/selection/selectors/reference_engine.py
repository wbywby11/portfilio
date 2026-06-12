# -*- coding: utf-8 -*-
"""
参考引擎选择器 - 以 step1_asset_selection.py 为核心计算逻辑

与 动量策略相关资料/step1_asset_selection.py 完全一致：
- 动量：MOM/MACD/POSI/SMOM，4因子×4窗口，阈值>-2%得1分，满分16分
- 反转：10天、22天价格偏度，升序排名，得分 N-k+1
- 动量选7个、反转选1个，取并集
- 并列处理：平均排名≤7则都入选，>7则都不入选；反转最高分并列则都不入选
"""

from __future__ import annotations

import logging
import pandas as pd

from app.selection.selectors.base import BaseAssetSelector
from app.selection.types import SelectionResult
from app.selection.engine_reference import select_assets_for_date

logger = logging.getLogger(__name__)


class ReferenceEngineSelector(BaseAssetSelector):
    """以 step1 为核心计算引擎的资产选择器（7+1 逻辑）。"""

    @classmethod
    def get_param_schema(cls):
        return {
            "selector_type": "reference_engine",
            "display_name": "参考引擎选择器（step1 标准）",
            "description": "以 step1_asset_selection.py 为核心，动量7个+反转1个，与对照文件完全一致",
            "params": [
                {"name": "min_history_days", "type": "number", "default": 260},
                {"name": "n_momentum", "type": "number", "default": 7},
                {"name": "n_reversal", "type": "number", "default": 1},
            ],
        }

    def select(
        self,
        prices: pd.DataFrame,
        n_assets: int,
        **params
    ) -> SelectionResult:
        """执行 step1 标准资产选择。"""
        if prices.empty:
            raise ValueError("prices DataFrame 为空")

        min_history = int(params.get("min_history_days", 260))
        top_momentum = int(params.get("n_momentum", 7))

        # 确定计算日与 date_idx
        rebalance_date = params.get("_rebalance_date")
        if rebalance_date is not None:
            if hasattr(rebalance_date, "tz_localize"):
                rebalance_date = pd.Timestamp(rebalance_date)
            elif not isinstance(rebalance_date, pd.Timestamp):
                rebalance_date = pd.Timestamp(rebalance_date)
        else:
            rebalance_date = prices.index[-1]

        # 找到 <= rebalance_date 的最后一个交易日
        mask = prices.index <= rebalance_date
        if not mask.any():
            raise ValueError(f"价格数据中无日期 <= {rebalance_date}")
        calc_date = prices.index[mask][-1]
        date_idx = prices.index.get_loc(calc_date)
        if isinstance(date_idx, (list, slice)):
            date_idx = date_idx.stop - 1 if hasattr(date_idx, "stop") else len(prices) - 1

        result = select_assets_for_date(
            nav=prices,
            date_idx=date_idx,
            calc_date=calc_date,
            min_history=min_history,
            top_momentum=top_momentum,
        )

        final_selected = result["最终入选"]
        mom_selected = set(result["动量入选"])
        rev_selected = set(result["反转入选"])

        tags = {}
        for a in final_selected:
            if a in mom_selected and a in rev_selected:
                tags[a] = "both"
            elif a in mom_selected:
                tags[a] = "momentum"
            else:
                tags[a] = "reversal"

        # 构建 ranking DataFrame（与 MomentumReversalSelector 格式兼容）
        mom_df = result.get("动量排名")
        rev_df = result.get("反转排名")
        valid_assets = result.get("有效资产", final_selected)

        def _get_mom_score(asset):
            if mom_df is None or mom_df.empty or "资产" not in mom_df.columns:
                return 0.0
            row = mom_df[mom_df["资产"] == asset]
            return float(row["动量得分"].iloc[0]) if not row.empty and "动量得分" in row.columns else 0.0

        def _get_rev_score(asset):
            if rev_df is None or rev_df.empty or "资产" not in rev_df.columns:
                return 0.0
            row = rev_df[rev_df["资产"] == asset]
            return float(row["反转综合得分"].iloc[0]) if not row.empty and "反转综合得分" in row.columns else 0.0

        rows = []
        for asset in valid_assets:
            mom_score = _get_mom_score(asset)
            rev_score = _get_rev_score(asset)
            rows.append({
                "asset": asset,
                "TotalMomentumScore": mom_score,
                "TotalReversalScore": rev_score,
                "combined_score": mom_score + rev_score,
                "tag": tags.get(asset, ""),
            })

        ranking_df = pd.DataFrame(rows).set_index("asset") if rows else pd.DataFrame()
        scores = {a: ranking_df.loc[a, "combined_score"] for a in ranking_df.index} if not ranking_df.empty else {}

        return SelectionResult(
            selected_assets=final_selected,
            scores=scores,
            ranking=ranking_df,
            timestamp=pd.Timestamp.now().isoformat(),
            selector_type="reference_engine",
            params=params,
            tags=tags,
        )
