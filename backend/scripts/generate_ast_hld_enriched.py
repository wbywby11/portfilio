"""
Task 5: 生成 dwd_ptl_ast_hld 持仓穿透数据
50产品 x 平均8资产 x 多个BIZ_DT = 400+ 条
确保 AST_CD 关联 dwd_ast_info, PORT_ID 关联 dwd_ptl_info
"""
import sys
import random
from datetime import datetime, timedelta

sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

random.seed(44)

DB_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"

# 每种策略的持仓数量和权重分配逻辑
STRATEGY_HOLDING_CONFIG = {
    "纯债策略": {"count": (8, 15), "max_weight": 0.10},
    "固收+": {"count": (6, 12), "max_weight": 0.12},
    "混合策略": {"count": (5, 10), "max_weight": 0.15},
    "FOF配置": {"count": (4, 8), "max_weight": 0.25},
    "CTA趋势": {"count": (3, 6), "max_weight": 0.30},
    "指数增强": {"count": (10, 30), "max_weight": 0.08},
    "QDII海外": {"count": (5, 10), "max_weight": 0.20},
    "量化对冲": {"count": (6, 12), "max_weight": 0.15},
    "目标日期": {"count": (4, 8), "max_weight": 0.25},
}

BIZ_DATES = ["2025-12-31", "2026-03-31", "2026-05-26"]


def generate_weights(n, max_weight=0.15):
    """生成n个归一化权重，单个不超过max_weight"""
    raw = [random.uniform(0.5, 3.0) for _ in range(n)]
    total = sum(raw)
    weights = [r / total for r in raw]
    # 裁剪超限
    for _ in range(10):
        over = [i for i, w in enumerate(weights) if w > max_weight]
        if not over:
            break
        for i in over:
            excess = weights[i] - max_weight
            weights[i] = max_weight
            # 分摊到其他
            others = [j for j in range(n) if j != i and weights[j] < max_weight]
            if others:
                share = excess / len(others)
                for j in others:
                    weights[j] += share
    # 最终归一化
    s = sum(weights)
    weights = [w / s for w in weights]
    return weights


def main():
    client = MongoClient(DB_URI)
    db = client[DB_NAME]

    # 获取可用资产列表
    ast_codes = db["dwd_ast_info"].distinct("AST_CD")
    if not ast_codes:
        print("ERROR: dwd_ast_info 为空，无法生成持仓")
        return
    print(f"可用资产: {len(ast_codes)} 个")

    # 获取产品列表及策略类型
    products = list(db["zysc_ptl_info_records"].find({}, {"产品代码": 1, "策略类型": 1}))
    print(f"产品数: {len(products)}")

    # 获取 ISR 信息（用于关联高风险主体→资产→产品穿透）
    isr_ids = db["dwd_isr_institution"].distinct("ISR_ID")
    # 找到有 ISR_ID 的资产
    ast_with_isr = list(db["dwd_ast_info"].find({"ISR_ID": {"$exists": True, "$ne": ""}}, {"AST_CD": 1, "ISR_ID": 1}))
    ast_isr_map = {d["AST_CD"]: d.get("ISR_ID", "") for d in ast_with_isr}

    # 清除旧的扩充数据
    del_result = db["dwd_ptl_ast_hld"].delete_many({"src_sys": "hermes_enriched"})
    print(f"清除旧扩充数据: {del_result.deleted_count} 条")

    new_docs = []
    # 选择50个产品生成持仓
    selected_products = products[:50] if len(products) >= 50 else products

    for prod in selected_products:
        port_id = prod["产品代码"]
        strategy = prod.get("策略类型", "混合策略")
        cfg = STRATEGY_HOLDING_CONFIG.get(strategy, {"count": (5, 10), "max_weight": 0.15})

        n_holdings = random.randint(*cfg["count"])
        n_holdings = min(n_holdings, len(ast_codes))

        # 选择资产
        selected_asts = random.sample(ast_codes, n_holdings)
        weights = generate_weights(n_holdings, cfg["max_weight"])

        for biz_dt in BIZ_DATES:
            # 每期权重微调
            period_weights = [w * random.uniform(0.92, 1.08) for w in weights]
            s = sum(period_weights)
            period_weights = [w / s for w in period_weights]

            for i, ast_cd in enumerate(selected_asts):
                weight = period_weights[i]
                cost_prc = round(random.uniform(90, 110), 4)
                mkt_prc = round(cost_prc * random.uniform(0.95, 1.08), 4)
                hld_qty = random.randint(1000, 500000)
                mkt_val = round(mkt_prc * hld_qty, 2)
                cost_amt = round(cost_prc * hld_qty, 2)

                doc = {
                    "PORT_ID": port_id,
                    "AST_CD": ast_cd,
                    "BIZ_DT": biz_dt,
                    "WEIGHT": round(weight, 6),
                    "HLD_QTY": hld_qty,
                    "COST_PRC": cost_prc,
                    "COST_AMT": cost_amt,
                    "MKT_PRC": mkt_prc,
                    "MKT_VAL": mkt_val,
                    "ACI_AMT": round(random.uniform(0, mkt_val * 0.02), 2) if "债" in strategy or "固" in strategy else 0,
                    "ACCT_NO": f"ACCT_{port_id}",
                    "src_sys": "hermes_enriched",
                    "etl_dt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                new_docs.append(doc)

    print(f"生成持仓记录: {len(new_docs)} 条")
    if new_docs:
        # 分批插入
        batch_size = 1000
        for i in range(0, len(new_docs), batch_size):
            batch = new_docs[i:i + batch_size]
            db["dwd_ptl_ast_hld"].insert_many(batch)
        print(f"插入完成")

    final = db["dwd_ptl_ast_hld"].count_documents({})
    print(f"最终 dwd_ptl_ast_hld: {final} 条")

    # 统计
    port_count = len(db["dwd_ptl_ast_hld"].distinct("PORT_ID"))
    ast_count = len(db["dwd_ptl_ast_hld"].distinct("AST_CD"))
    print(f"覆盖产品: {port_count}, 覆盖资产: {ast_count}")

    client.close()


if __name__ == "__main__":
    main()
