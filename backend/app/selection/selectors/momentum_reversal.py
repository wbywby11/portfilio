"""
动量与反转组合选择器（7+1）

与浙银理财/申万宏源《大类资产指数编制规则》附件一 第279、295-299行一致：
- 基于 MOM/MACD/POSI/SMOM 选 7 个资产
- 基于 SKEW 选 1 个资产
- 合并得 7～8 个资产，其余权重为 0
"""

from __future__ import annotations

import logging
import pandas as pd

from app.selection.selectors.base import BaseAssetSelector
from app.selection.types import SelectionResult
from app.selection.formula.advanced_momentum_factors import (
    DEFAULT_MACD_WINDOWS,
    DEFAULT_MOM_WINDOWS,
    DEFAULT_REVERSAL_WINDOWS,
    select_momentum_and_reversal_assets,
)

logger = logging.getLogger(__name__)


def _diag_enabled() -> bool:
    """选资过程的明细诊断表是否输出到标准输出。

    表格量很大（每个调仓日上百行），仅在本模块日志开到 DEBUG 时输出，
    避免污染服务端日志与脚本输出。
    """
    return logger.isEnabledFor(logging.DEBUG)


class MomentumReversalSelector(BaseAssetSelector):
    """动量+反转双模型选择器（7+1），与指数编制规则一致。"""

    @classmethod
    def get_param_schema(cls):
        return {
            "selector_type": "momentum_reversal",
            "display_name": "动量+反转(7+1)",
            "description": "基于动量因子选7个、反转因子选1个，合并为7～8个资产（浙银理财/申万宏源指数编制规则）",
            "params": [
                {
                    "name": "min_history_days",
                    "label": "最小历史数据要求",
                    "type": "number",
                    "default": 260,
                    "min_value": 60,
                    "max_value": 1000,
                    "step": 10,
                    "description": "资产进入候选池的最小交易日数（默认260天约1年）",
                },
                {
                    "name": "n_momentum",
                    "label": "动量选择数量",
                    "type": "number",
                    "default": 7,
                    "min_value": 1,
                    "max_value": 20,
                    "step": 1,
                    "description": "动量因子选择的资产数量（默认7个）",
                },
                {
                    "name": "n_reversal",
                    "label": "反转选择数量",
                    "type": "number",
                    "default": 1,
                    "min_value": 0,
                    "max_value": 10,
                    "step": 1,
                    "description": "反转因子选择的资产数量（默认1个）",
                },
                {
                    "name": "momentum_windows",
                    "label": "动量计算窗口",
                    "type": "text",
                    "default": "20,60,120,250",
                    "description": "动量因子计算窗口（交易日），逗号分隔，如 20,60,120,250",
                    "group": "advanced",
                },
                {
                    "name": "macd_windows",
                    "label": "MACD计算窗口",
                    "type": "text",
                    "default": "40,80,120,160",
                    "description": "MACD因子计算窗口（交易日），逗号分隔，如 40,80,120,160",
                    "group": "advanced",
                },
                {
                    "name": "reversal_windows",
                    "label": "反转计算窗口",
                    "type": "text",
                    "default": "10,22",
                    "description": "反转因子计算窗口（交易日），逗号分隔，如 10,22",
                    "group": "advanced",
                },
                {
                    "name": "tie_rule",
                    "label": "同分处理规则",
                    "type": "select",
                    "default": "index_rule",
                    "options": [
                        {"label": "编制规则（平均排名）", "value": "index_rule"},
                        {"label": "严格前N名", "value": "strict"},
                    ],
                    "description": "编制规则：同分整组入选/剔除，入选数在N附近浮动；严格前N名：动量与反转各恒选N个",
                    "group": "advanced",
                },
            ],
        }

    def select(
        self,
        prices: pd.DataFrame,
        n_assets: int,
        **params
    ) -> SelectionResult:
        """执行 7+1 双模型选择。n_assets 被 n_momentum + n_reversal 覆盖。"""
        if prices.empty:
            raise ValueError("prices DataFrame 为空")

        min_history_days = int(params.get("min_history_days", 260))
        n_momentum = int(params.get("n_momentum", 7))
        n_reversal = int(params.get("n_reversal", 1))
        momentum_windows_str = params.get("momentum_windows", "20,60,120,250")
        macd_windows_str = params.get("macd_windows", "40,80,120,160")
        reversal_windows_str = params.get("reversal_windows", "10,22")

        try:
            windows = [int(x.strip()) for x in momentum_windows_str.split(",")]
        except Exception as e:
            raise ValueError(f"动量窗口格式错误: {momentum_windows_str}") from e
        try:
            macd_windows = [int(x.strip()) for x in macd_windows_str.split(",")]
        except Exception as e:
            raise ValueError(f"MACD窗口格式错误: {macd_windows_str}") from e
        # 兼容旧参数：若为旧默认窗口则自动替换为新因子周期，保证计算与打印一致
        if windows == [22, 65, 260]:
            windows = list(DEFAULT_MOM_WINDOWS)
        if macd_windows == [26]:
            macd_windows = list(DEFAULT_MACD_WINDOWS)
        momentum_windows_dict = {
            "MOM": windows,
            "MACD": macd_windows,
            "POSI": windows,
            "SMOM": windows,
        }

        try:
            reversal_windows = [int(x.strip()) for x in reversal_windows_str.split(",")]
        except Exception as e:
            raise ValueError(f"反转窗口格式错误: {reversal_windows_str}") from e

        rebalance_date = params.get("_rebalance_date")
        if rebalance_date is not None and hasattr(rebalance_date, "strftime"):
            rebalance_date_str = rebalance_date.strftime("%Y-%m-%d")
        elif rebalance_date is not None:
            rebalance_date_str = str(rebalance_date)[:10]
        else:
            rebalance_date_str = "—"

        # 打印本次资产选择接收到的参数
        self._log_selection_params(
            n_assets=n_assets,
            prices=prices,
            min_history_days=min_history_days,
            n_momentum=n_momentum,
            n_reversal=n_reversal,
            momentum_windows_dict=momentum_windows_dict,
            macd_windows=macd_windows,
            reversal_windows=reversal_windows,
            raw_params=params,
            rebalance_date_str=rebalance_date_str,
        )

        min_history_reversal = int(params.get("min_history_reversal", 22))
        use_price_skew = params.get("use_price_skew", True)
        tie_rule = str(params.get("tie_rule") or "index_rule")

        momentum_selected, reversal_selected, momentum_df, reversal_df = (
            select_momentum_and_reversal_assets(
                prices=prices,
                n_momentum=n_momentum,
                n_reversal=n_reversal,
                momentum_windows=momentum_windows_dict,
                reversal_windows=reversal_windows,
                min_history_days=min_history_days,
                min_history_reversal=min_history_reversal,
                use_price_skew=use_price_skew,
                tie_rule=tie_rule,
            )
        )

        # ===== 打印完整排名信息（便于调试） =====
        self._log_ranking_info(
            momentum_df, reversal_df, momentum_selected, reversal_selected, n_momentum, n_reversal, rebalance_date_str
        )

        mom_set = set(momentum_selected)
        rev_set = set(reversal_selected)
        all_selected = list(mom_set | rev_set)

        tags = {}
        for a in all_selected:
            if a in (mom_set & rev_set):
                tags[a] = "both"
            elif a in mom_set:
                tags[a] = "momentum"
            else:
                tags[a] = "reversal"

        scores = {}
        for a in all_selected:
            ms = momentum_df.loc[a, "TotalMomentumScore"] if a in momentum_df.index else 0
            rs = reversal_df.loc[a, "TotalReversalScore"] if a in reversal_df.index else 0
            scores[a] = ms + rs

        # 全量排名表：所有有效资产 + 细分得分 + 排名与入选情况
        all_assets = (
            momentum_df.index.union(reversal_df.index).unique()
            if not momentum_df.empty or not reversal_df.empty
            else pd.Index([])
        )
        mom_breakdown = [c for c in (momentum_df.columns if not momentum_df.empty else []) if c.startswith("Score_") and c != "Score_Total" and not c.startswith("Score_Rank")]
        rev_breakdown = [c for c in (reversal_df.columns if not reversal_df.empty else []) if c.startswith("Score_") and c != "TotalReversalScore" and not c.startswith("Rank_")]

        ranking_parts = []
        for a in all_assets:
            ms = momentum_df.loc[a, "TotalMomentumScore"] if a in momentum_df.index else 0.0
            rs = reversal_df.loc[a, "TotalReversalScore"] if a in reversal_df.index else 0.0
            combined = ms + rs
            row = {
                "asset": a,
                "TotalMomentumScore": ms,
                "TotalReversalScore": rs,
                "combined_score": combined,
                "动量排名": int(momentum_df.loc[a, "Rank_Total"]) if a in momentum_df.index and "Rank_Total" in momentum_df.columns else 0,
                "是否入选动量": a in mom_set,
                "是否入选反转": a in rev_set,
                "是否最终入选": a in (mom_set | rev_set),
                "tag": tags.get(a, ""),
            }
            for c in mom_breakdown:
                row[c] = momentum_df.loc[a, c] if a in momentum_df.index and c in momentum_df.columns else 0
            for c in rev_breakdown:
                row[c] = reversal_df.loc[a, c] if a in reversal_df.index and c in reversal_df.columns else 0
            ranking_parts.append(row)

        ranking_df = pd.DataFrame(ranking_parts).set_index("asset")
        ranking_df["反转排名"] = ranking_df["TotalReversalScore"].rank(ascending=False, method="min").astype(int)
        ranking_df = ranking_df.sort_values("combined_score", ascending=False)

        return SelectionResult(
            selected_assets=all_selected,
            scores=scores,
            ranking=ranking_df,
            timestamp=pd.Timestamp.now().isoformat(),
            selector_type="momentum_reversal",
            params=params,
            tags=tags,
        )

    def _log_selection_params(
        self,
        n_assets: int,
        prices: pd.DataFrame,
        min_history_days: int,
        n_momentum: int,
        n_reversal: int,
        momentum_windows_dict: dict,
        macd_windows: list,
        reversal_windows: list,
        raw_params: dict,
        rebalance_date_str: str = "—",
    ):
        """打印接收参数、执行参数、默认参数（新因子定义），便于核对前后端与文档一致性."""
        if not _diag_enabled():
            return
        # 默认参数（advanced_momentum_factors 新定义）
        default_min_history_days = 260
        default_n_momentum = 7
        default_n_reversal = 1
        default_momentum_windows_str = ",".join(map(str, DEFAULT_MOM_WINDOWS))
        default_macd_windows_str = ",".join(map(str, DEFAULT_MACD_WINDOWS))
        default_reversal_windows_str = ",".join(map(str, DEFAULT_REVERSAL_WINDOWS))
        default_momentum_windows_dict = {
            "MOM": DEFAULT_MOM_WINDOWS,
            "MACD": DEFAULT_MACD_WINDOWS,
            "POSI": DEFAULT_MOM_WINDOWS,
            "SMOM": DEFAULT_MOM_WINDOWS,
        }
        default_reversal_windows = DEFAULT_REVERSAL_WINDOWS

        print("\n" + "=" * 80)
        print(f"【资产选择器 参数一览】 调仓日期: {rebalance_date_str}")
        print("=" * 80)

        print("\n  ■ 1. 接收参数（本次调用传入）")
        print("  " + "-" * 60)
        print(f"    传入 n_assets:        {n_assets}")
        print(f"    候选资产数(列数):     {len(prices.columns)}")
        print(f"    价格序列长度(行数):   {len(prices)}")
        print(f"    原始 params 全文:     {raw_params}")

        print("\n  ■ 2. 执行参数（解析后实际用于计算）")
        print("  " + "-" * 60)
        print(f"    min_history_days:     {min_history_days}")
        print(f"    n_momentum:           {n_momentum}")
        print(f"    n_reversal:          {n_reversal}")
        print(f"    momentum_windows:    {momentum_windows_dict}")
        print(f"    macd_windows:        {macd_windows}")
        print(f"    reversal_windows:    {reversal_windows}")

        print("\n  ■ 3. 默认参数（新因子定义 advanced_momentum_factors）")
        print("  " + "-" * 60)
        print(f"    min_history_days:     {default_min_history_days}")
        print(f"    n_momentum:           {default_n_momentum}")
        print(f"    n_reversal:           {default_n_reversal}")
        print(f"    momentum_windows:    {default_momentum_windows_dict}")
        print(f"    reversal_windows:    {default_reversal_windows}")
        print(f"    (momentum_windows 字符串: {default_momentum_windows_str})")
        print(f"    (macd_windows 字符串: {default_macd_windows_str})")
        print(f"    (reversal_windows 字符串: {default_reversal_windows_str})")

        # 与默认是否一致
        same_min = min_history_days == default_min_history_days
        same_mom_n = n_momentum == default_n_momentum and n_reversal == default_n_reversal
        same_mom_w = momentum_windows_dict == default_momentum_windows_dict
        same_rev_w = reversal_windows == default_reversal_windows
        if same_min and same_mom_n and same_mom_w and same_rev_w:
            print("\n  ▶ 执行参数与默认参数一致")
        else:
            print("\n  ▶ 与默认不一致项:")
            if not same_min:
                print(f"      min_history_days: 执行={min_history_days} vs 默认={default_min_history_days}")
            if not same_mom_n:
                print(f"      n_momentum/n_reversal: 执行=({n_momentum},{n_reversal}) vs 默认=({default_n_momentum},{default_n_reversal})")
            if not same_mom_w:
                print(f"      momentum_windows: 执行与默认不同")
            if not same_rev_w:
                print(f"      reversal_windows: 执行={reversal_windows} vs 默认={default_reversal_windows}")

        print("=" * 80 + "\n")

    # 终端 ANSI：中国两年期/十年期国债 加粗+颜色（亮青）
    _ANSI_BOLD_CYAN = "\033[1;96m"
    _ANSI_RESET = "\033[0m"

    def _fmt_cn_treasury_2y_10y(self, asset_name: str, width: int = 20) -> str:
        """中国两年期、十年期国债在打印时加粗+颜色，并保证显示宽度一致。"""
        s = str(asset_name)
        padded = (s[:width] if len(s) >= width else s.ljust(width))
        if ("两年期" in s or "十年期" in s or "10年期" in s) and "国债" in s:
            return f"{self._ANSI_BOLD_CYAN}{padded}{self._ANSI_RESET}"
        return padded

    def _log_ranking_info(
        self,
        momentum_df: pd.DataFrame,
        reversal_df: pd.DataFrame,
        momentum_selected: list,
        reversal_selected: list,
        n_momentum: int,
        n_reversal: int,
        rebalance_date_str: str = "—",
    ):
        """打印动量/反转因子完整排名信息及各项指标得分贡献，便于调试。因子与周期采用新定义。"""
        if not _diag_enabled():
            return
        if momentum_df.empty and reversal_df.empty:
            return
        # 国债关键词（用于高亮显示）
        bond_keywords = ["国债", "债券", "bond", "treasury"]

        def is_bond(asset_name: str) -> bool:
            return any(kw in asset_name.lower() for kw in bond_keywords)

        def asset_col(name: str, w: int = 20) -> str:
            return self._fmt_cn_treasury_2y_10y(name, w)

        # 动量：仅各因子信号列（Score_因子_周期），排除 Score_Total / Score_Rank，按 因子顺序(MOM,MACD,POSI,SMOM)+周期 排序
        _mom_raw = [c for c in (momentum_df.columns if not momentum_df.empty else []) if c.startswith("Score_") and c != "Score_Total" and not c.startswith("Score_Rank")]
        _factor_order = {"MOM": 0, "MACD": 1, "POSI": 2, "SMOM": 3}

        def _mom_key(c):
            label = c.replace("Score_", "")
            parts = label.split("_")
            factor = parts[0] if parts else ""
            period = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            return (_factor_order.get(factor, 99), period)

        mom_score_cols = sorted(_mom_raw, key=_mom_key)
        # 反转：各因子得分列（Score_SKEW_周期）
        rev_score_cols = [c for c in (reversal_df.columns if not reversal_df.empty else []) if c.startswith("Score_") and not c.startswith("Score_Rank") and "SKEW" in c]
        rev_score_cols = sorted(rev_score_cols, key=lambda c: int(c.split("_")[-1]) if c.split("_")[-1].isdigit() else 0)

        # 表头列宽；数据列宽需容纳「得分(阈值化前原始值)」便于调试
        col_w = 9
        rev_col_w = 10
        mom_cell_w = 14   # 如 1(0.0523) 或 0(-0.0123)
        rev_cell_w = 18   # 如 15.00(-0.3245)

        def _mom_cell(score_col: str, row: pd.Series, df: pd.DataFrame) -> str:
            """动量单格：阈值化得分 + 括号内原始因子值。"""
            raw_col = score_col.replace("Score_", "", 1)
            if raw_col in df.columns:
                return f"{row[score_col]:.0f}({row[raw_col]:.4f})"
            return f"{row[score_col]:.0f}"

        def _rev_cell(score_col: str, row: pd.Series, df: pd.DataFrame) -> str:
            """反转单格：排名得分 + 括号内原始 SKEW 值。"""
            raw_col = score_col.replace("Score_", "", 1)
            if raw_col in df.columns:
                return f"{row[score_col]:.2f}({row[raw_col]:.4f})"
            return f"{row[score_col]:.2f}"

        print("\n" + "=" * 80)
        print(f"【混合动量选择器排名】 调仓日期: {rebalance_date_str} | n_momentum={n_momentum}, n_reversal={n_reversal}")
        print("=" * 80)
        # 时间窗口参数（与编制规则一致）：便于核对打印得分与文档
        print("  时间窗口(n): MOM=20,60,120,250 | MACD=40,80,120,160 | POSI=20,60,120,250 | SMOM=20,60,120,250 | 波动率=60日")

        # 动量排名
        print(f"\n📈 动量因子排名 (选中前 {n_momentum} 名，含并列):")
        print("-" * 60)
        # 动量总分上限 = 因子×周期个数（0/1 信号个数），用于百分制展示
        max_mom_score = len(mom_score_cols) if mom_score_cols else 16
        mom_rank = momentum_df[["TotalMomentumScore"]].copy() if not momentum_df.empty and "TotalMomentumScore" in momentum_df.columns else pd.DataFrame()
        if not mom_rank.empty:
            mom_rank["排名"] = range(1, len(mom_rank) + 1)
            mom_rank["选中"] = mom_rank.index.isin(momentum_selected)
        for idx, row in mom_rank.iterrows():
            marker = "✅" if row["选中"] else "  "
            bond_flag = " 🔷国债" if is_bond(str(idx)) else ""
            raw = row["TotalMomentumScore"]
            pct = (raw / max_mom_score * 100) if max_mom_score else 0
            print(f"  {marker} 第{int(row['排名']):2d}名: {asset_col(idx)} | 动量总分: {raw:.0f}/{max_mom_score} (百分制: {pct:.1f}){bond_flag}")

        # 动量：因子与周期说明 + 各指标得分（新定义：MOM/MACD/POSI/SMOM，周期见下表头）；括号内为阈值化前原始值
        print(f"\n📈 动量各因子得分贡献 (选中资产)，新定义 因子(周期): MOM(20,60,120,250) MACD(40,80,120,160) POSI(20,60,120,250) SMOM(20,60,120,250)，S=1 若 F>-0.02，格式: 得分(原始值):")
        print("-" * 120)
        header = "资产".ljust(22) + " | " + " | ".join(f"{c.replace('Score_',''):>{mom_cell_w}}" for c in mom_score_cols) + " | 总分"
        print(f"  {header}")
        print("  " + "-" * (len(header) + 2))
        for asset in momentum_selected:
            if asset not in momentum_df.index:
                continue
            row = momentum_df.loc[asset]
            contribs = " | ".join(f"{_mom_cell(c, row, momentum_df):>{mom_cell_w}}" for c in mom_score_cols)
            bond_flag = " 🔷" if is_bond(str(asset)) else ""
            print(f"  {asset_col(asset)} | {contribs} | {row['TotalMomentumScore']:8.2f}{bond_flag}")

        # 反转排名
        print(f"\n📉 反转因子排名 (选中前 {n_reversal} 名，含并列)，因子: SKEW(周期 10,22):")
        print("-" * 60)
        rev_rank = reversal_df[["TotalReversalScore"]].copy() if not reversal_df.empty and "TotalReversalScore" in reversal_df.columns else pd.DataFrame()
        if not rev_rank.empty:
            rev_rank["排名"] = range(1, len(rev_rank) + 1)
            rev_rank["选中"] = rev_rank.index.isin(reversal_selected)
        for idx, row in rev_rank.iterrows():
            marker = "✅" if row["选中"] else "  "
            bond_flag = " 🔷国债" if is_bond(str(idx)) else ""
            print(f"  {marker} 第{int(row['排名']):2d}名: {asset_col(idx)} | 反转总分: {row['TotalReversalScore']:8.2f}{bond_flag}")

        # 反转：各周期得分（SKEW_10, SKEW_22）；括号内为排名前原始 SKEW 值
        print(f"\n📉 反转各因子得分贡献 (选中资产)，因子(周期): SKEW(10,22)，格式: 得分(原始值):")
        print("-" * 80)
        rev_header = "资产".ljust(22) + " | " + " | ".join(f"{c.replace('Score_',''):>{rev_cell_w}}" for c in rev_score_cols) + " | 总分"
        print(f"  {rev_header}")
        print("  " + "-" * (len(rev_header) + 2))
        for asset in reversal_selected:
            if asset not in reversal_df.index:
                continue
            row = reversal_df.loc[asset]
            contribs = " | ".join(f"{_rev_cell(c, row, reversal_df):>{rev_cell_w}}" for c in rev_score_cols)
            bond_flag = " 🔷" if is_bond(str(asset)) else ""
            print(f"  {asset_col(asset)} | {contribs} | {row['TotalReversalScore']:8.2f}{bond_flag}")

        # 全资产动量得分贡献（因子+周期见表头）；括号内为阈值化前原始值
        print(f"\n📈 动量各因子得分贡献 (全资产)，因子与周期见下表头，格式: 得分(原始值):")
        print("-" * 120)
        print(f"  {header}")
        print("  " + "-" * (len(header) + 2))
        for idx, row in momentum_df.iterrows():
            contribs = " | ".join(f"{_mom_cell(c, row, momentum_df):>{mom_cell_w}}" for c in mom_score_cols)
            sel = "✅" if idx in momentum_selected else "  "
            bond_flag = " 🔷" if is_bond(str(idx)) else ""
            print(f"  {sel} {asset_col(idx, 18)} | {contribs} | {row['TotalMomentumScore']:8.2f}{bond_flag}")

        # 全资产反转得分贡献；括号内为排名前原始 SKEW 值
        print(f"\n📉 反转各因子得分贡献 (全资产)，因子与周期见下表头，格式: 得分(原始值):")
        print("-" * 80)
        print(f"  {rev_header}")
        print("  " + "-" * (len(rev_header) + 2))
        for idx, row in reversal_df.iterrows():
            contribs = " | ".join(f"{_rev_cell(c, row, reversal_df):>{rev_cell_w}}" for c in rev_score_cols)
            sel = "✅" if idx in reversal_selected else "  "
            bond_flag = " 🔷" if is_bond(str(idx)) else ""
            print(f"  {sel} {asset_col(idx, 18)} | {contribs} | {row['TotalReversalScore']:8.2f}{bond_flag}")

        # 最终选中汇总
        all_selected = set(momentum_selected) | set(reversal_selected)
        print(f"\n🎯 最终选中资产 ({len(all_selected)} 个):")
        print("-" * 60)
        for asset in all_selected:
            source = []
            if asset in momentum_selected:
                source.append("动量")
            if asset in reversal_selected:
                source.append("反转")
            bond_flag = " 🔷国债" if is_bond(str(asset)) else ""
            print(f"  • {asset_col(asset)} | 来源: {'+'.join(source)}{bond_flag}")

        print("=" * 80 + "\n")
