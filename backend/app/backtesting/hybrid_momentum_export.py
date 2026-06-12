# -*- coding: utf-8 -*-
"""
risk_budget_target_vol 混合动量策略 - 编制规则输出文件导出

每次运行回测时生成以下文件（与 step1/step2/step3 格式一致）：
- 资产选择结果.xlsx
- 权重计算结果.xlsx
- 回测结果_汇率版_v1.xlsx
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import pandas as pd

from app.config.asset_cost_currency import ASSET_CURRENCY_BY_CODE, ASSET_CURRENCY_BY_NAME
from app.config.zy_document_max_weights import ZY_DOCUMENT_CODE_TO_NAME

_log = logging.getLogger(__name__)


def _get_asset_names(all_assets: List[str], asset_names: Optional[Dict[str, str]]) -> Dict[str, str]:
    """合并 API 资产名与编制规则默认映射"""
    out = dict(asset_names or {})
    for code in all_assets:
        if code not in out:
            out[code] = ZY_DOCUMENT_CODE_TO_NAME.get(code, code)
    return out


def _resolve_reference_weight_path() -> Optional[str]:
    """解析对照权重文件路径，尝试常见位置（动量策略相关资料 与 portfilio-end 同级）"""
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates = [
        os.path.join("动量策略相关资料", "对照_权重计算结果.xlsx"),
        os.path.join("..", "动量策略相关资料", "对照_权重计算结果.xlsx"),
        os.path.join(os.path.dirname(_root), "动量策略相关资料", "对照_权重计算结果.xlsx"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _safe_excel_path(path: str) -> str:
    """若文件被占用(PermissionError)，返回带时间戳的备用路径"""
    from datetime import datetime
    base, ext = os.path.splitext(path)
    return f"{base}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"


def export_selection_results(
    selection_records: List[Dict[str, Any]],
    all_assets: List[str],
    output_path: str,
    asset_names: Optional[Dict[str, str]] = None,
) -> str:
    """导出 资产选择结果.xlsx。asset_names 用于将代码转为中文名，与对照组格式一致"""
    if not selection_records:
        _log.warning("[混合动量导出] 无资产选择记录，跳过 资产选择结果.xlsx")
        return ""
    _ensure_dir(output_path)
    code_to_name = _get_asset_names(all_assets, asset_names or {})

    summary_rows = []
    matrix_rows = []
    status_rows = []
    momentum_details_list = []
    reversal_details_list = []

    for rec in selection_records:
        calc_date = rec.get("calc_date")
        valid_assets = rec.get("valid_assets", [])
        momentum_selected = rec.get("momentum_selected", [])
        reversal_selected = rec.get("reversal_selected", [])
        final_selected = rec.get("final_selected", [])
        ranking_df = rec.get("ranking_df")

        # 选择汇总（与对照组一致：有效资产/入选用中文名）
        summary_rows.append({
            "计算日期": calc_date,
            "有效资产数": len(valid_assets),
            "有效资产": ", ".join(code_to_name.get(a, a) for a in valid_assets) if valid_assets else "",
            "动量入选": ", ".join(code_to_name.get(a, a) for a in momentum_selected) if momentum_selected else "",
            "反转入选": ", ".join(code_to_name.get(a, a) for a in reversal_selected) if reversal_selected else "",
            "最终入选": ", ".join(code_to_name.get(a, a) for a in final_selected) if final_selected else "",
            "入选数量": len(final_selected),
        })

        # 入选矩阵 (0/1/2) 与 入选状态矩阵（列名用中文名，与对照组一致）
        matrix_row = {"计算日期": calc_date}
        status_row = {"计算日期": calc_date}
        for asset in all_assets:
            name = code_to_name.get(asset, asset)
            if asset in momentum_selected and asset in reversal_selected:
                matrix_row[name] = 2
                status_row[name] = "动量+反转"
            elif asset in momentum_selected:
                matrix_row[name] = 1
                status_row[name] = "动量"
            elif asset in reversal_selected:
                matrix_row[name] = 1
                status_row[name] = "反转"
            elif asset in valid_assets:
                matrix_row[name] = 0
                status_row[name] = "未入选"
            else:
                matrix_row[name] = 0
                status_row[name] = "无效"
        matrix_rows.append(matrix_row)
        status_rows.append(status_row)

        # 动量排名详情（从 ranking_df 提取，按动量得分降序，资产列用中文名与对照组一致）
        if ranking_df is not None and not ranking_df.empty:
            if "TotalMomentumScore" in ranking_df.columns:
                mom_rank = ranking_df[["TotalMomentumScore"]].copy()
                mom_rank = mom_rank.sort_values("TotalMomentumScore", ascending=False)
                mom_rank = mom_rank.rename(columns={"TotalMomentumScore": "动量得分"})
                mom_rank["计算日期"] = calc_date
                mom_rank["动量排名"] = range(1, len(mom_rank) + 1)
                mom_rank["动量入选"] = mom_rank.index.isin(momentum_selected)
                mom_rank = mom_rank.reset_index()
                code_col = next((c for c in ("asset", "index") if c in mom_rank.columns), None)
                if code_col:
                    mom_rank["资产"] = mom_rank[code_col].map(lambda x: code_to_name.get(x, x))
                    mom_rank = mom_rank.drop(columns=[code_col], errors="ignore")
                momentum_details_list.append(mom_rank)
        # 反转排名详情（优先用 reversal_ranking_df，含 10日/22日 偏度、排名、得分，资产列用中文名）
        rev_ranking_df = rec.get("reversal_ranking_df")
        if rev_ranking_df is not None and not rev_ranking_df.empty:
            rev_rank = rev_ranking_df.copy()
            rev_rank["计算日期"] = calc_date
            # 列名映射：Skew_10 -> 10日偏度 等
            col_map = {
                "Skew_10": "10日偏度", "Skew_10_rank": "10日排名", "Skew_10_score": "10日得分",
                "Skew_22": "22日偏度", "Skew_22_rank": "22日排名", "Skew_22_score": "22日得分",
            }
            rev_rank = rev_rank.rename(columns=col_map)
            # 资产列：若有则转为中文名
            if "资产" in rev_rank.columns:
                rev_rank["资产"] = rev_rank["资产"].map(lambda x: code_to_name.get(x, x))
            reversal_details_list.append(rev_rank)
        elif ranking_df is not None and not ranking_df.empty and "TotalReversalScore" in ranking_df.columns:
            rev_rank = ranking_df[["TotalReversalScore"]].copy()
            rev_rank = rev_rank.sort_values("TotalReversalScore", ascending=False)
            rev_rank = rev_rank.rename(columns={"TotalReversalScore": "反转综合得分"})
            rev_rank["计算日期"] = calc_date
            rev_rank["反转排名"] = range(1, len(rev_rank) + 1)
            rev_rank["反转入选"] = rev_rank.index.isin(reversal_selected)
            reversal_details_list.append(rev_rank.reset_index())

    def _write_selection(path: str) -> None:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame(summary_rows).to_excel(writer, sheet_name="选择汇总", index=False)
            pd.DataFrame(matrix_rows).to_excel(writer, sheet_name="入选矩阵", index=False)
            pd.DataFrame(status_rows).to_excel(writer, sheet_name="入选状态矩阵", index=False)
            if momentum_details_list:
                mom_all = pd.concat(momentum_details_list, ignore_index=True)
                cols = ["计算日期", "资产", "动量得分", "动量排名", "动量入选"]
                cols = [c for c in cols if c in mom_all.columns]
                mom_all[cols].to_excel(writer, sheet_name="动量排名详情", index=False)
            if reversal_details_list:
                rev_all = pd.concat(reversal_details_list, ignore_index=True)
                # 与对照文件一致：计算日期、资产、反转综合得分、反转排名、10日偏度、10日排名、10日得分、22日偏度、22日排名、22日得分、反转入选
                cols = ["计算日期", "资产", "asset", "反转综合得分", "反转排名",
                        "10日偏度", "10日排名", "10日得分", "22日偏度", "22日排名", "22日得分", "反转入选"]
                cols = [c for c in cols if c in rev_all.columns]
                # 若同时有 资产 和 asset，保留 资产 作为主列
                if "资产" in cols and "asset" in cols:
                    cols = [c for c in cols if c != "asset"]
                rev_all[cols].to_excel(writer, sheet_name="反转排名详情", index=False)

    try:
        _write_selection(output_path)
    except PermissionError:
        alt_path = _safe_excel_path(output_path)
        _log.warning("[混合动量导出] 原文件被占用，改用: %s", alt_path)
        _write_selection(alt_path)
        output_path = alt_path
    _log.info("[混合动量导出] 已保存 资产选择结果.xlsx -> %s", output_path)
    return output_path


def export_weight_results(
    weight_records: List[Dict[str, Any]],
    all_assets: List[str],
    output_path: str,
    asset_names: Optional[Dict[str, str]] = None,
) -> None:
    """导出 权重计算结果.xlsx，表头使用资产名"""
    if not weight_records:
        _log.warning("[混合动量导出] 无权重计算记录，跳过 权重计算结果.xlsx")
        return
    _ensure_dir(output_path)
    code_to_name = _get_asset_names(all_assets, asset_names or {})

    weight_matrix_rows = []
    weight_details_list = []

    for rec in weight_records:
        calc_date = rec.get("calc_date")
        final_weights = rec.get("final_weights", {})
        port_vol = rec.get("portfolio_vol", 0.0)
        scale = rec.get("scale", 1.0)
        total_leverage = rec.get("total_leverage", 0.0)
        risk_budgets = rec.get("risk_budgets", {})
        asset_vols = rec.get("asset_vols", {})
        initial_weights = rec.get("initial_weights", {})
        scaled_weights = rec.get("scaled_weights", {})

        # 权重矩阵（表头用资产名）
        row = {"计算日期": calc_date}
        for asset in all_assets:
            row[code_to_name.get(asset, asset)] = final_weights.get(asset, 0.0)
        row["总杠杆"] = total_leverage
        row["组合波动率"] = port_vol
        row["缩放系数"] = scale
        if rec.get("total_weight") is not None:
            row["初始权重和"] = rec["total_weight"]
        if rec.get("scale_vol") is not None:
            row["scale_vol"] = rec["scale_vol"]
        if rec.get("scale_leverage") is not None:
            row["scale_leverage"] = rec["scale_leverage"]
        if rec.get("scaled_sum") is not None:
            row["缩放后权重和"] = rec["scaled_sum"]
        weight_matrix_rows.append(row)

        # 权重详情（资产列用资产名）
        selection_status = rec.get("selection_status", {})
        for asset in all_assets:
            status = selection_status.get(asset, 0)
            detail = {
                "计算日期": calc_date,
                "资产": code_to_name.get(asset, asset),
                "入选状态": status,
                "风险预算": risk_budgets.get(asset, 0),
                "资产波动率": asset_vols.get(asset, float("nan")),
                "初始权重": initial_weights.get(asset, 0),
                "缩放后权重": scaled_weights.get(asset, 0),
                "最终权重": final_weights.get(asset, 0),
            }
            weight_details_list.append(detail)

    def _write_weight(path: str) -> None:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame(weight_matrix_rows).to_excel(writer, sheet_name="权重矩阵", index=False)
            pd.DataFrame(weight_details_list).to_excel(writer, sheet_name="权重详情", index=False)

    try:
        _write_weight(output_path)
    except PermissionError:
        alt_path = _safe_excel_path(output_path)
        _log.warning("[混合动量导出] 权重文件被占用，改用: %s", alt_path)
        _write_weight(alt_path)
        output_path = alt_path
    _log.info("[混合动量导出] 已保存 权重计算结果.xlsx -> %s", output_path)


def export_weight_comparison(
    weight_records: List[Dict[str, Any]],
    all_assets: List[str],
    asset_names: Dict[str, str],
    output_path: str,
    reference_path: str,
) -> Optional[str]:
    """
    生成权重对比文件，与对照_权重计算结果.xlsx 逐资产对比。
    若对照文件不存在或读取失败，返回 None。
    """
    if not weight_records or not os.path.isfile(reference_path):
        if not os.path.isfile(reference_path):
            _log.warning("[混合动量导出] 对照文件不存在，跳过权重对比: %s", reference_path)
        return None
    _ensure_dir(output_path)

    try:
        ref_df = pd.read_excel(reference_path, sheet_name="权重矩阵")
    except Exception as e:
        _log.warning("[混合动量导出] 读取对照文件失败: %s", e)
        return None

    code_to_name = {c: asset_names.get(c, ZY_DOCUMENT_CODE_TO_NAME.get(c, c)) for c in all_assets}

    # 对照文件列：计算日期 + 资产名 + 总杠杆/组合波动率/缩放系数
    ref_date_col = "计算日期"
    ref_asset_cols = [c for c in ref_df.columns if c not in (ref_date_col, "总杠杆", "组合波动率", "缩放系数")]

    ref_df[ref_date_col] = pd.to_datetime(ref_df[ref_date_col]).dt.normalize()

    comparison_rows = []
    matrix_diff_rows = []

    for rec in weight_records:
        calc_date = rec.get("calc_date")
        if hasattr(calc_date, "normalize"):
            calc_date = calc_date.normalize()
        final_weights = rec.get("final_weights", {})

        ref_row = ref_df[ref_df[ref_date_col] == pd.Timestamp(calc_date)]
        if ref_row.empty:
            continue

        ref_row = ref_row.iloc[0]
        row_diff = {"计算日期": calc_date}

        for asset in all_assets:
            name = code_to_name[asset]
            gen_w = final_weights.get(asset, 0.0)
            ref_w = ref_row.get(name, float("nan"))
            if pd.isna(ref_w):
                ref_w = 0.0
            diff = gen_w - ref_w
            diff_pct = (diff / ref_w * 100) if ref_w != 0 else (0.0 if diff == 0 else float("inf"))

            comparison_rows.append({
                "计算日期": calc_date,
                "资产": name,
                "生成权重": gen_w,
                "对照权重": ref_w,
                "差异": diff,
                "差异%": diff_pct if diff_pct != float("inf") else None,
            })
            row_diff[name] = diff

        matrix_diff_rows.append(row_diff)

    if not comparison_rows:
        _log.warning("[混合动量导出] 无重叠日期，跳过权重对比")
        return None

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        pd.DataFrame(comparison_rows).to_excel(writer, sheet_name="逐资产对比", index=False)
        pd.DataFrame(matrix_diff_rows).to_excel(writer, sheet_name="差异矩阵", index=False)

    _log.info("[混合动量导出] 已保存 权重对比结果.xlsx -> %s", output_path)
    return output_path


def export_backtest_results(
    snapshots: List[Any],
    vol_reset_events: List[Dict[str, Any]],
    performance: Dict[str, Any],
    all_assets: List[str],
    asset_names: Dict[str, str],
    output_path: str,
    trade_dates_set: Optional[set] = None,
) -> None:
    """导出 回测结果_汇率版_v1.xlsx

    非交易日（不在 trade_dates_set 中）仅计算净值，权重沿用上一交易日，与交易明细严格校准。
    """
    _ensure_dir(output_path)

    # 加载交易日历（用于判断非交易日，非交易日权重沿用上一交易日）
    if trade_dates_set is None:
        try:
            try:
                from app.data.trade_dates import load_trade_dates
            except ModuleNotFoundError:
                from data.trade_dates import load_trade_dates
            loaded = load_trade_dates()
            trade_dates_set = loaded[1] if loaded else set()
        except Exception:
            trade_dates_set = set()

    # 编制规则：2015-01-05 为元旦后第1个交易日，执行日=月末后第2个交易日，故该日永不调仓
    _DISPLAY_NO_REBALANCE_DATES = {pd.Timestamp("2015-01-05")}

    # 每日净值：非交易日及 2015-01-05 权重沿用上一交易日，确保净值与交易明细一致
    code_to_name = _get_asset_names(all_assets, asset_names)
    nav_rows = []
    prev_weights = {}
    last_trading_day_weights = {}
    for s in snapshots:
        t = getattr(s, "time", None)
        tv = getattr(s, "total_value", 0)
        w = getattr(s, "weights", {}) or {}
        is_reb = getattr(s, "is_rebalance_day", False)
        t_norm = pd.Timestamp(t).normalize() if t is not None else None
        is_trading_day = t_norm in trade_dates_set if (t_norm is not None and trade_dates_set) else True
        force_no_rebalance = t_norm in _DISPLAY_NO_REBALANCE_DATES if t_norm else False
        # 非交易日 或 2015-01-05：权重沿用上一交易日，仅计算净值不调仓
        if (not is_trading_day or force_no_rebalance) and last_trading_day_weights:
            w = last_trading_day_weights.copy()
            if is_reb or force_no_rebalance:
                _log.warning("[混合动量导出] %s 不调仓，权重已沿用上一交易日以与交易明细校准", t_norm)
        if is_trading_day and not force_no_rebalance:
            last_trading_day_weights = w.copy()
        nav_row = {"日期": t, "净值": tv}
        vol = getattr(s, "portfolio_volatility", None)
        nav_row["波动率"] = vol
        for asset in all_assets:
            nav_row[code_to_name.get(asset, asset)] = w.get(asset, 0)
        # 总杠杆
        total_w = sum(w.get(a, 0) or 0 for a in all_assets)
        nav_row["总杠杆"] = total_w
        # 调仓日（非交易日及 2015-01-05 永为否）
        nav_row["调仓日"] = "是" if (is_reb and is_trading_day and not force_no_rebalance) else "否"
        nav_rows.append(nav_row)
        prev_weights = w.copy()

    nav_df = pd.DataFrame(nav_rows)
    if "日期" in nav_df.columns:
        nav_df = nav_df.set_index("日期")

    # 资产货币映射
    asset_currency = {}
    for code in all_assets:
        name = asset_names.get(code, code)
        c = ASSET_CURRENCY_BY_CODE.get(code) or ASSET_CURRENCY_BY_NAME.get(name, "CNH")
        asset_currency[code] = c

    # 波动率重置事件：排除非交易日执行日（2015-01-01/02/05 等）
    _EXCLUDE_EXEC_DATES = {pd.Timestamp("2015-01-01"), pd.Timestamp("2015-01-02"), pd.Timestamp("2015-01-05")}
    vol_reset_filtered = []
    for e in vol_reset_events:
        ed = e.get("execute_date")
        if ed is None or ed == "":
            vol_reset_filtered.append(e)
        else:
            try:
                if pd.Timestamp(ed).normalize() not in _EXCLUDE_EXEC_DATES:
                    vol_reset_filtered.append(e)
            except Exception:
                vol_reset_filtered.append(e)
    if len(vol_reset_filtered) < len(vol_reset_events):
        _log.warning("[混合动量导出] 已排除非交易日波动率重置事件 %d 条", len(vol_reset_events) - len(vol_reset_filtered))

    def _write_backtest(path: str) -> None:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            nav_df.to_excel(writer, sheet_name="每日净值")
            if vol_reset_filtered:
                events_df = pd.DataFrame([{
                    "信号日期": e.get("signal_date"),
                    "执行日期": e.get("execute_date"),
                    "VolTrigger": e.get("vol_trigger"),
                    "触发阈值": e.get("threshold", 0.06),
                    "目标波动率": e.get("target_vol", 0.05),
                    "缩放因子": e.get("scale_factor"),
                } for e in vol_reset_filtered])
                events_df.to_excel(writer, sheet_name="波动率重置事件", index=False)
                weight_details = []
                code_to_name_bt = _get_asset_names(all_assets, asset_names)
                for i, e in enumerate(vol_reset_filtered):
                    row = {"序号": i + 1, "信号日期": e.get("signal_date"), "执行日期": e.get("execute_date")}
                    trigger_w = e.get("trigger_weights", {})
                    reset_w = e.get("reset_weights", {})
                    for asset in all_assets:
                        name = code_to_name_bt.get(asset, asset)
                        row[f"{name}_触发时"] = trigger_w.get(asset, 0)
                        row[f"{name}_重置后"] = reset_w.get(asset, 0)
                    weight_details.append(row)
                pd.DataFrame(weight_details).to_excel(writer, sheet_name="波动率触发权重详情", index=False)
            metrics_df = pd.DataFrame({
            "指标": ["起始日期", "结束日期", "起始净值", "结束净值", "累计收益率", "年化收益率",
                    "年化波动率", "最大回撤", "夏普比率", "波动率重置次数"],
            "值": [
                str(performance.get("start_date", "")),
                str(performance.get("end_date", "")),
                f"{performance.get('initial_nav', 0):.2f}",
                f"{performance.get('final_nav', 0):.2f}",
                f"{(performance.get('total_return', 0) or 0) * 100:.2f}%",
                f"{(performance.get('annual_return', 0) or 0) * 100:.2f}%",
                f"{(performance.get('volatility', 0) or 0) * 100:.2f}%",
                f"{(performance.get('max_drawdown', 0) or 0) * 100:.2f}%",
                f"{performance.get('sharpe_ratio', 0) or 0:.2f}",
                str(len(vol_reset_filtered)),
            ],
            })
            metrics_df.to_excel(writer, sheet_name="绩效指标", index=False)
            pd.DataFrame([
                {"资产": code_to_name.get(code, code), "计价货币": asset_currency.get(code, "CNH")}
                for code in all_assets
            ]).to_excel(writer, sheet_name="资产货币映射", index=False)

    try:
        _write_backtest(output_path)
    except PermissionError:
        alt_path = _safe_excel_path(output_path)
        _log.warning("[混合动量导出] 回测结果文件被占用，改用: %s", alt_path)
        _write_backtest(alt_path)
        output_path = alt_path
    _log.info("[混合动量导出] 已保存 回测结果_汇率版_v1.xlsx -> %s", output_path)


def export_all(
    output_dir: str,
    selection_records: List[Dict[str, Any]],
    weight_records: List[Dict[str, Any]],
    snapshots: List[Any],
    vol_reset_events: List[Dict[str, Any]],
    performance: Dict[str, Any],
    all_assets: List[str],
    asset_names: Dict[str, str],
    reference_weight_path: Optional[str] = None,
    trade_dates_set: Optional[set] = None,
) -> Dict[str, str]:
    """导出全部三个文件，返回生成的文件路径。若提供 reference_weight_path 则额外生成权重对比文件。"""
    os.makedirs(output_dir, exist_ok=True)
    paths = {}
    names = _get_asset_names(all_assets, asset_names)
    sel_path = export_selection_results(
        selection_records, all_assets,
        os.path.join(output_dir, "资产选择结果.xlsx"),
        asset_names=names,
    )
    if sel_path:
        paths["资产选择结果"] = sel_path
    export_weight_results(
        weight_records, all_assets,
        os.path.join(output_dir, "权重计算结果.xlsx"),
        asset_names=names,
    )
    paths["权重计算结果"] = os.path.join(output_dir, "权重计算结果.xlsx")
    if reference_weight_path:
        comp_path = export_weight_comparison(
            weight_records, all_assets, names,
            os.path.join(output_dir, "权重对比结果.xlsx"),
            reference_weight_path,
        )
        if comp_path:
            paths["权重对比结果"] = comp_path
    export_backtest_results(
        snapshots, vol_reset_events, performance,
        all_assets, names,
        os.path.join(output_dir, "回测结果_汇率版_v1.xlsx"),
        trade_dates_set=trade_dates_set,
    )
    paths["回测结果"] = os.path.join(output_dir, "回测结果_汇率版_v1.xlsx")
    return paths
