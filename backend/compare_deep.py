# -*- coding: utf-8 -*-
"""深度对比：当前回测结果 vs 对照组"""
import pandas as pd
import numpy as np
import os
import sys

# 强制 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

GEN = "backtest_exports"
CTRL = "d:/动量策略相关资料"

FILES = [
    ("资产选择结果_20260306_101942", "对照_资产选择结果"),
    ("权重计算结果_20260306_101942", "对照_权重计算结果"),
    ("回测结果_汇率版_v1_20260306_101943", "对照_回测结果_汇率版_v1"),
]

def main():
    out = []
    def log(s):
        out.append(s)
        print(s)

    log("=" * 80)
    log("深度对比分析：当前系统 vs 对照组")
    log("=" * 80)

    for gen_suffix, ctrl_suffix in FILES:
        gen_path = os.path.join(GEN, gen_suffix + ".xlsx")
        ctrl_path = os.path.join(CTRL, ctrl_suffix + ".xlsx")
        if not os.path.isfile(gen_path):
            log(f"\n[跳过] 生成文件不存在: {gen_path}")
            continue
        if not os.path.isfile(ctrl_path):
            log(f"\n[跳过] 对照文件不存在: {ctrl_path}")
            continue

        gen_sheets = pd.read_excel(gen_path, sheet_name=None)
        ctrl_sheets = pd.read_excel(ctrl_path, sheet_name=None)

        log(f"\n{'='*80}")
        log(f"文件: {gen_suffix}")
        log("=" * 80)

        for sheet_name in sorted(set(gen_sheets.keys()) | set(ctrl_sheets.keys())):
            g = gen_sheets.get(sheet_name)
            c = ctrl_sheets.get(sheet_name)
            log(f"\n--- Sheet: {sheet_name} ---")
            if g is None:
                log("  生成: 无")
            else:
                log(f"  生成: {g.shape}, 列: {list(g.columns)[:6]}...")
            if c is None:
                log("  对照: 无")
            else:
                log(f"  对照: {c.shape}, 列: {list(c.columns)[:6]}...")

            if g is not None and c is not None and sheet_name == "选择汇总":
                # 选择汇总：逐行对比有效资产数、入选数量
                log("\n  选择汇总 - 差异行（有效资产数 或 入选数量 不同）:")
                min_len = min(len(g), len(c))
                diff_rows = []
                for i in range(min_len):
                    gv = g.iloc[i].get("有效资产数", None)
                    cv = c.iloc[i].get("有效资产数", None)
                    gn = g.iloc[i].get("入选数量", None)
                    cn = c.iloc[i].get("入选数量", None)
                    gd = g.iloc[i].get("计算日期", None)
                    cd = c.iloc[i].get("计算日期", None)
                    if gv != cv or gn != cn or (gd != cd and pd.notna(gd) and pd.notna(cd)):
                        diff_rows.append((i, gd, gv, gn, cd, cv, cn))
                for r in diff_rows[:15]:
                    log(f"    行{r[0]}: 日期 gen={r[1]} ctrl={r[4]} | 有效数 gen={r[2]} ctrl={r[5]} | 入选数 gen={r[3]} ctrl={r[6]}")
                if len(diff_rows) > 15:
                    log(f"    ... 共 {len(diff_rows)} 行有差异")

            if g is not None and c is not None and sheet_name == "权重矩阵":
                # 权重矩阵：按日期对齐，对比同日期权重差异
                gd = g["计算日期"].drop_duplicates()
                cd = c["计算日期"].drop_duplicates()
                common_dates = set(pd.Timestamp(d).date() for d in gd) & set(pd.Timestamp(d).date() for d in cd)
                log(f"\n  权重矩阵: 共同日期数 {len(common_dates)}")
                # 找第一个有差异的日期
                for d in sorted(common_dates)[:3]:
                    gr = g[pd.to_datetime(g["计算日期"]).dt.date == d].iloc[0]
                    cr = c[pd.to_datetime(c["计算日期"]).dt.date == d].iloc[0]
                    asset_cols = [x for x in g.columns if x not in ("计算日期","总杠杆","组合波动率","缩放系数")]
                    diffs = []
                    for ac in asset_cols:
                        if ac in cr.index:
                            gv, cv = gr.get(ac, 0), cr.get(ac, 0)
                            if abs(float(gv or 0) - float(cv or 0)) > 1e-6:
                                diffs.append((ac, gv, cv))
                    if diffs:
                        log(f"    日期 {d}: {len(diffs)} 个资产权重不同, 示例: {diffs[:3]}")

        # 绩效指标
        if "回测结果" in gen_suffix and "绩效指标" in gen_sheets and "绩效指标" in ctrl_sheets:
            gm = gen_sheets["绩效指标"]
            cm = ctrl_sheets["绩效指标"]
            log("\n--- 绩效指标对比 ---")
            if "指标" in gm.columns and "值" in gm.columns:
                for ind in ["年化收益率", "年化波动率", "最大回撤", "夏普比率", "累计收益率"]:
                    gr = gm[gm["指标"] == ind] if "指标" in gm.columns else gm[gm.iloc[:,0] == ind]
                    cr = cm[cm["指标"] == ind] if "指标" in cm.columns else cm[cm.iloc[:,0] == ind]
                    if not gr.empty and not cr.empty:
                        gv = gr["值"].iloc[0] if "值" in gr.columns else gr.iloc[0, 1]
                        cv = cr["值"].iloc[0] if "值" in cr.columns else cr.iloc[0, 1]
                        log(f"  {ind}: gen={gv} | ctrl={cv}")

    log("\n" + "=" * 80)
    log("对比完成")
    log("=" * 80)

    # 写入报告
    with open("backtest_exports/compare_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    log("\n报告已保存: backtest_exports/compare_report.txt")

if __name__ == "__main__":
    main()
