"""
ZY 数据真实化 - 批次 1：资产域主表

目标表（每张 150 条）：
- dwd_ast_info        资产基础信息
- dwd_ast_info_ch     中债估值
- dwd_ast_info_zg     中证估值
- dwd_ast_yield_info  资产收益率

数据来源：scripts/zy_data_pools.py 中的 BOND/STOCK/FUND/OTHER 模板
执行：python scripts/gen_b1_keys_and_asset_master.py
"""
from __future__ import annotations
import sys
import random
from pathlib import Path
from datetime import datetime
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).parent))

from zy_data_pools import (
    BIZ_DT, AST_CDS,
    BOND_TEMPLATES, STOCK_TEMPLATES, FUND_TEMPLATES, OTHER_AST_TEMPLATES,
    ISR_TEMPLATES, RATING_AGENCIES,
)
from zy_data_helpers import (
    parse_dt, fmt_dt, years_between, calc_duration_convexity, calc_aci,
)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"

random.seed(20250324)


# =============== 1) dwd_ast_info ===============
def build_ast_info() -> list:
    """资产基础信息（150 条）"""
    docs = []

    # 债券
    for ast_cd, ast_nm, sub_type, isr_idx, coupon, maturity, issue_amt_yi, market, term, list_dt in BOND_TEMPLATES:
        isr_id = ISR_TEMPLATES[isr_idx][0] if isr_idx is not None else None
        docs.append({
            'AST_CD': ast_cd,
            'AST_NM': ast_nm,
            'AST_TYPE': 'BOND',
            'AST_SUB_TYPE': sub_type,
            'ISR_ID': isr_id,
            'CCY': 'CNY',
            'LIST_DT': list_dt,
            'MATURITY_DT': maturity,
            'COUPON_RATE': coupon,
            'ISSUE_AMT': issue_amt_yi * 1e8,   # 亿 -> 元
            'MARKET': market,
            'BOND_TERM': term,
            'BIZ_DT': BIZ_DT,
        })

    # 股票
    for ast_cd, stock_nm, exch, ind_cd, ind_nm, isr_idx, list_dt, tot_cap_yi in STOCK_TEMPLATES:
        isr_id = ISR_TEMPLATES[isr_idx][0] if isr_idx is not None else None
        docs.append({
            'AST_CD': ast_cd,
            'AST_NM': stock_nm,
            'AST_TYPE': 'STOCK',
            'AST_SUB_TYPE': 'A_SHARE',
            'ISR_ID': isr_id,
            'CCY': 'CNY',
            'LIST_DT': list_dt,
            'MATURITY_DT': None,
            'COUPON_RATE': None,
            'ISSUE_AMT': tot_cap_yi * 1e8,
            'MARKET': exch,
            'BOND_TERM': None,
            'BIZ_DT': BIZ_DT,
        })

    # 基金
    for ast_cd, fund_nm, fund_type, mgr, estab_dt, aum_yi in FUND_TEMPLATES:
        market = 'SSE' if ast_cd.endswith('.SH') else ('SZSE' if ast_cd.endswith('.SZ') else 'EXCH')
        docs.append({
            'AST_CD': ast_cd,
            'AST_NM': fund_nm,
            'AST_TYPE': 'FUND' if fund_type != 'MMF' else 'MMF',
            'AST_SUB_TYPE': fund_type,   # ETF / LOF / OPEN / MMF
            'ISR_ID': None,
            'CCY': 'CNY',
            'LIST_DT': estab_dt,
            'MATURITY_DT': None,
            'COUPON_RATE': None,
            'ISSUE_AMT': aum_yi * 1e8,
            'MARKET': market,
            'BOND_TERM': None,
            'BIZ_DT': BIZ_DT,
        })

    # 其他 (指数 + 回购)
    for ast_cd, ast_nm, sub_type, isr_idx, _c, _m, market, term, _ld in OTHER_AST_TEMPLATES:
        isr_id = ISR_TEMPLATES[isr_idx][0] if isr_idx is not None else None
        ast_type = 'INDEX' if sub_type == 'INDEX' else 'REPO'
        docs.append({
            'AST_CD': ast_cd,
            'AST_NM': ast_nm,
            'AST_TYPE': ast_type,
            'AST_SUB_TYPE': sub_type,
            'ISR_ID': isr_id,
            'CCY': 'CNY',
            'LIST_DT': None,
            'MATURITY_DT': None,
            'COUPON_RATE': None,
            'ISSUE_AMT': None,
            'MARKET': market,
            'BOND_TERM': term,
            'BIZ_DT': BIZ_DT,
        })

    return docs


# =============== 2) dwd_ast_info_ch / dwd_ast_info_zg ===============
def build_val_info(src: str = 'CCDC') -> list:
    """中债 / 中证估值（仅债券资产，~80 条）"""
    docs = []
    biz_d = parse_dt(BIZ_DT)
    for ast_cd, _nm, sub_type, _isr, coupon, maturity, _amt, _mkt, _term, list_dt in BOND_TEMPLATES:
        # 剩余期限
        try:
            yrs = years_between(BIZ_DT, maturity)
        except Exception:
            yrs = 5.0
        yrs = max(0.1, yrs)

        # 估值收益率 = 类型基准利率 + 期限调整 + 微小波动
        base = {
            'CGB': 0.020, 'POLICY': 0.024, 'MTN': 0.030, 'NCD': 0.024,
            'ENTERPRISE': 0.045, 'CB': 0.020,
        }.get(sub_type, 0.030)
        # 中证比中债略高 1~3 bp
        spread = 0.0001 + random.random() * 0.0002 if src == 'CSI' else 0.0
        val_yield = round(base + 0.0008 * yrs + random.uniform(-0.0015, 0.0015) + spread, 6)

        # 久期凸性
        mac, mod, cnv = calc_duration_convexity(coupon, val_yield, yrs)

        # 净价 ≈ 100 + (票面-估值收益率) × 修正久期 × 100
        spread_diff = coupon - val_yield
        net_prc = round(100.0 + spread_diff * mod * 100.0 + random.uniform(-0.3, 0.3), 4)
        net_prc = max(85.0, min(115.0, net_prc))

        # 应计利息（假设上次付息 90~180 天前）
        days_since = random.randint(30, 360)
        aci = calc_aci(coupon, days_since)
        full_prc = round(net_prc + aci, 4)

        agency = random.choice(RATING_AGENCIES)

        docs.append({
            'AST_CD': ast_cd,
            'BIZ_DT': BIZ_DT,
            'VAL_NET_PRC': net_prc,
            'VAL_FULL_PRC': full_prc,
            'VAL_YIELD': val_yield,
            'DURATION': mod,
            'CONVEXITY': cnv,
            'RATING_AGENCY': agency,
            'VAL_SRC': src,
        })

    return docs


# =============== 3) dwd_ast_yield_info ===============
def build_yield_info() -> list:
    """资产收益率（150 条；股票/基金真实收益区间，债券小幅波动）"""
    docs = []
    for ast_cd in AST_CDS:
        # 类型识别
        if any(t[0] == ast_cd for t in BOND_TEMPLATES):
            t = next(x for x in BOND_TEMPLATES if x[0] == ast_cd)
            coupon, maturity, sub_type = t[4], t[5], t[2]
            try:
                yrs = max(0.1, years_between(BIZ_DT, maturity))
            except Exception:
                yrs = 3.0
            base = {
                'CGB': 0.020, 'POLICY': 0.024, 'MTN': 0.030, 'NCD': 0.024,
                'ENTERPRISE': 0.045, 'CB': 0.020,
            }.get(sub_type, 0.030)
            ytm = round(base + 0.0008 * yrs + random.uniform(-0.001, 0.001), 6)
            yield_ex = round(ytm + random.uniform(-0.0005, 0.0005), 6) if sub_type == 'CB' else None
            daily_rtn = round(random.gauss(0.0001, 0.0008), 6)   # ±0.08%
            week_rtn = round(daily_rtn * 5 + random.gauss(0, 0.0015), 6)
            month_rtn = round(daily_rtn * 22 + random.gauss(0, 0.003), 6)
            ytd_rtn = round(month_rtn * 3 + random.gauss(0, 0.005), 6)
            settle_prc = round(100.0 + random.uniform(-3.0, 3.0), 4)
        elif any(t[0] == ast_cd for t in STOCK_TEMPLATES):
            ytm = None
            yield_ex = None
            daily_rtn = round(random.gauss(0.0005, 0.018), 6)    # ±1.8%
            week_rtn = round(daily_rtn + random.gauss(0.001, 0.03), 6)
            month_rtn = round(daily_rtn * 4 + random.gauss(0.005, 0.06), 6)
            ytd_rtn = round(month_rtn * 3 + random.gauss(0.02, 0.12), 6)
            settle_prc = round(random.uniform(8.0, 280.0), 2)
        elif any(t[0] == ast_cd for t in FUND_TEMPLATES):
            t = next(x for x in FUND_TEMPLATES if x[0] == ast_cd)
            fund_type = t[2]
            ytm = None
            yield_ex = None
            if fund_type == 'MMF':
                daily_rtn = round(random.gauss(0.00006, 0.00002), 7)   # 货币基金：~0.006%/日
                week_rtn = round(daily_rtn * 7, 7)
                month_rtn = round(daily_rtn * 30, 7)
                ytd_rtn = round(daily_rtn * 60, 7)
                settle_prc = 1.0
            elif fund_type == 'ETF':
                daily_rtn = round(random.gauss(0.0003, 0.012), 6)
                week_rtn = round(daily_rtn + random.gauss(0.001, 0.025), 6)
                month_rtn = round(daily_rtn * 4 + random.gauss(0.005, 0.05), 6)
                ytd_rtn = round(month_rtn * 3 + random.gauss(0.01, 0.10), 6)
                settle_prc = round(random.uniform(0.8, 6.5), 4)
            else:
                daily_rtn = round(random.gauss(0.0003, 0.010), 6)
                week_rtn = round(daily_rtn + random.gauss(0.001, 0.020), 6)
                month_rtn = round(daily_rtn * 4 + random.gauss(0.005, 0.04), 6)
                ytd_rtn = round(month_rtn * 3 + random.gauss(0.01, 0.08), 6)
                settle_prc = round(random.uniform(0.9, 3.5), 4)
        else:
            # 指数/回购
            ytm = round(random.uniform(0.018, 0.030), 6)
            yield_ex = None
            daily_rtn = round(random.gauss(0.0002, 0.005), 6)
            week_rtn = round(daily_rtn * 5, 6)
            month_rtn = round(daily_rtn * 22, 6)
            ytd_rtn = round(daily_rtn * 60, 6)
            settle_prc = None

        docs.append({
            'AST_CD': ast_cd,
            'BIZ_DT': BIZ_DT,
            'YIELD_TM': ytm,
            'YIELD_EX': yield_ex,
            'DAILY_RTN': daily_rtn,
            'WEEK_RTN': week_rtn,
            'MONTH_RTN': month_rtn,
            'YTD_RTN': ytd_rtn,
            'SETTLE_PRC': settle_prc,
        })

    return docs


# =============== 主流程 ===============
def main():
    print(f'[B1] 资产域主表生成')
    print(f'[B1] 数据库: {MONGO_URI}/{DB_NAME}')

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[DB_NAME]

    targets = [
        ('dwd_ast_info', build_ast_info()),
        ('dwd_ast_info_ch', build_val_info('CCDC')),
        ('dwd_ast_info_zg', build_val_info('CSI')),
        ('dwd_ast_yield_info', build_yield_info()),
    ]

    for coll_name, docs in targets:
        coll = db[coll_name]
        deleted = coll.delete_many({}).deleted_count
        if docs:
            coll.insert_many(docs)
        print(f'[B1] {coll_name:25s}: 清空 {deleted} 条 -> 写入 {len(docs)} 条')

    # 校验
    print(f'\n[B1] 校验：')
    print(f'  dwd_ast_info        样本: {db.dwd_ast_info.find_one({"AST_CD": "019601.IB"}, {"_id": 0})}')
    print(f'  dwd_ast_info_ch     样本: {db.dwd_ast_info_ch.find_one({"AST_CD": "019601.IB"}, {"_id": 0})}')
    print(f'  dwd_ast_yield_info  样本(股票): {db.dwd_ast_yield_info.find_one({"AST_CD": "600036.SH"}, {"_id": 0})}')

    print('\n[B1] ✅ 完成')


if __name__ == '__main__':
    main()
