"""
ZY 数据真实化 - 批次 4：交易流水 + 客户交易（含 60 个交易日时序）

目标表：
交易域 (6):
- dwd_trn_order (~300) / dwd_trn_trade_ast (500) / dwd_trn_trade_ptl (200)
- dwd_trn_trade_val / dwd_trn_trade_zg / dwd_trn_trade_jy
客户交易 (6):
- dwd_cust_trans_apply_info_s5 / _ta / _yh
- dwd_cust_trans_cfm_info / dwd_cust_trans_divd_info / dwd_cust_trans_srl_info
"""
from __future__ import annotations
import sys
import random
import math
from pathlib import Path
from datetime import datetime, timedelta
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).parent))

from zy_data_pools import (
    BIZ_DT, AST_CDS, PORT_IDS, ISR_IDS, CUSTOMER_IDS,
    BOND_TEMPLATES, STOCK_TEMPLATES, FUND_TEMPLATES,
    PORT_TEMPLATES, CNTP_TEMPLATES, CNTP_IDS, SELLER_IDS,
    is_bond, is_stock, is_fund, get_bond_template, get_port_template,
    SURNAMES, GIVEN_NAMES_M, GIVEN_NAMES_F,
)
from zy_data_helpers import (
    gen_trade_dates, shift_trade_dates, parse_dt, fmt_dt,
)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"
random.seed(20250401)

# 60 个交易日
TRADE_DATES = gen_trade_dates(BIZ_DT, 60)
BOND_AST = [t[0] for t in BOND_TEMPLATES]
STOCK_AST = [t[0] for t in STOCK_TEMPLATES]
FUND_AST = [t[0] for t in FUND_TEMPLATES]

# 交易员池
TRADERS = ['张磊', '李涛', '王勇', '陈军', '赵明', '周杰', '刘超', '黄亮']
PM_POOL = ['吴晓明', '孙建华', '周志强', '郑伟', '林红']


# ============== UTILS ==============
def gen_trade_id(prefix: str, idx: int) -> str:
    return f'{prefix}{idx:08d}'


def get_market_for_ast(ast_cd: str) -> str:
    if ast_cd.endswith('.SH'):
        return 'SSE'
    elif ast_cd.endswith('.SZ'):
        return 'SZSE'
    elif ast_cd.endswith('.IB'):
        return 'IB'
    return 'EXCH'


def get_base_price(ast_cd: str) -> float:
    """获取资产基础价格用于交易"""
    bt = get_bond_template(ast_cd)
    if bt:
        # 债券净价 ~100 附近
        return round(random.uniform(97.0, 103.0), 4)
    if is_stock(ast_cd):
        from zy_data_pools import get_stock_template
        st = get_stock_template(ast_cd)
        if st:
            cap = st[7]  # TOT_CAP 亿
            # 简单根据市值推测价格区间
            if cap > 5000:
                return round(random.uniform(3.0, 10.0), 2)
            elif cap > 1000:
                return round(random.uniform(10.0, 50.0), 2)
            else:
                return round(random.uniform(20.0, 200.0), 2)
    if is_fund(ast_cd):
        return round(random.uniform(0.8, 5.0), 4)
    return round(random.uniform(99.0, 101.0), 4)


def calc_fee(ast_cd: str, amt: float) -> float:
    """按品种和金额计算交易费用"""
    if is_bond(ast_cd):
        rate = 0.00005  # 债券万 0.5
    elif is_stock(ast_cd):
        rate = 0.0003   # 股票万 3
    elif is_fund(ast_cd):
        rate = 0.00015  # 基金万 1.5
    else:
        rate = 0.0001
    fee = abs(amt) * rate
    return round(max(fee, 0.01), 2)


# ============== 1) dwd_trn_order ==============
def build_trn_order():
    """~300 条交易指令，每日 4~6 笔"""
    docs = []
    idx = 0
    for dt in TRADE_DATES:
        n_orders = random.randint(4, 6)
        for _ in range(n_orders):
            idx += 1
            port_id = random.choice(PORT_IDS)
            pt = get_port_template(port_id)
            ptype = pt[2] if pt else 'BOND'
            # 根据组合类型选择资产
            if ptype == 'MMF':
                ast_cd = random.choice(BOND_AST[:20])
            elif ptype == 'EQUITY' or ptype == 'INDEX':
                ast_cd = random.choice(STOCK_AST)
            elif ptype == 'FOF':
                ast_cd = random.choice(FUND_AST)
            else:
                ast_cd = random.choice(BOND_AST + STOCK_AST[:5])
            bs_dir = random.choices(['B', 'S'], weights=[0.55, 0.45])[0]
            prc = get_base_price(ast_cd)
            # 指令数量
            if is_bond(ast_cd):
                qty = random.randint(100, 5000) * 10  # 面值万
            elif is_stock(ast_cd):
                qty = random.randint(1, 50) * 100  # 手
            else:
                qty = random.randint(1000, 100000)
            # 时间
            hour = random.randint(9, 15)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            submit_tm = f'{hour:02d}:{minute:02d}:{second:02d}'
            # 状态
            status = random.choices(
                ['FILLED', 'PARTIAL', 'CANCELLED', 'REJECTED', 'NEW'],
                weights=[65, 15, 10, 5, 5]
            )[0]
            fill_qty = qty if status == 'FILLED' else (
                int(qty * random.uniform(0.3, 0.8)) if status == 'PARTIAL' else 0
            )
            avg_prc = round(prc * random.uniform(0.997, 1.003), 4) if fill_qty > 0 else 0
            trade_id = gen_trade_id('TRD', idx) if fill_qty > 0 else ''
            docs.append({
                'ORDER_ID': gen_trade_id('ORD', idx),
                'PORT_ID': port_id,
                'AST_CD': ast_cd,
                'SUBMIT_DT': dt,
                'SUBMIT_TM': submit_tm,
                'BS_DIR': bs_dir,
                'ORD_QTY': qty,
                'ORD_PRC': prc,
                'ORD_TYPE': random.choice(['LIMIT', 'MARKET', 'LIMIT', 'LIMIT']),
                'TRADER': random.choice(TRADERS),
                'PM_APPROVER': random.choice(PM_POOL),
                'STATUS': status,
                'FILL_QTY': fill_qty,
                'AVG_PRC': avg_prc,
                'LINK_TRADE_ID': trade_id,
            })
    return docs


# ============== 2) dwd_trn_trade_ast ==============
def build_trn_trade_ast():
    """500 条资产维度成交"""
    docs = []
    idx = 0
    for dt in TRADE_DATES:
        n_trades = random.randint(7, 10)
        for _ in range(n_trades):
            idx += 1
            ast_cd = random.choice(AST_CDS)
            bs_dir = random.choices(['B', 'S'], weights=[0.55, 0.45])[0]
            prc = get_base_price(ast_cd)
            # 加点偏差 ±0.5%
            prc = round(prc * random.uniform(0.995, 1.005), 4)
            if is_bond(ast_cd):
                qty = random.randint(100, 5000) * 10
            elif is_stock(ast_cd):
                qty = random.randint(1, 50) * 100
            else:
                qty = random.randint(1000, 100000)
            amt = round(prc * qty, 2)
            market = get_market_for_ast(ast_cd)
            cntp = random.choice(CNTP_IDS)
            docs.append({
                'TRADE_ID': gen_trade_id('TRD', 10000 + idx),
                'AST_CD': ast_cd,
                'TRADE_DT': dt,
                'SETT_DT': shift_trade_dates(dt, 1),
                'BS_DIR': bs_dir,
                'QTY': qty,
                'PRC': prc,
                'AMT': amt,
                'CCY': 'CNY',
                'CNTP_ID': cntp,
                'MARKET': market,
                'TRADER': random.choice(TRADERS),
                'STATUS': random.choices(['FILLED', 'PARTIAL'], weights=[90, 10])[0],
            })
            if idx >= 500:
                return docs
    return docs


# ============== 3) dwd_trn_trade_ptl ==============
def build_trn_trade_ptl():
    """200 条组合维度交易"""
    docs = []
    idx = 0
    for dt in TRADE_DATES:
        n = random.randint(2, 5)
        for _ in range(n):
            idx += 1
            port_id = random.choice(PORT_IDS)
            pt = get_port_template(port_id)
            ptype = pt[2] if pt else 'BOND'
            if ptype == 'MMF':
                ast_cd = random.choice(BOND_AST[:20])
            elif ptype in ('EQUITY', 'INDEX'):
                ast_cd = random.choice(STOCK_AST)
            elif ptype == 'FOF':
                ast_cd = random.choice(FUND_AST)
            else:
                ast_cd = random.choice(BOND_AST + STOCK_AST[:5])
            bs_dir = random.choices(['B', 'S'], weights=[0.55, 0.45])[0]
            prc = get_base_price(ast_cd)
            prc = round(prc * random.uniform(0.995, 1.005), 4)
            if is_bond(ast_cd):
                qty = random.randint(100, 3000) * 10
            elif is_stock(ast_cd):
                qty = random.randint(1, 30) * 100
            else:
                qty = random.randint(1000, 50000)
            amt = round(prc * qty, 2)
            fee = calc_fee(ast_cd, amt)
            # 结算日：债券 T+1，股票 T+1，基金 T+2
            sett_n = 2 if is_fund(ast_cd) else 1
            docs.append({
                'TRADE_ID': gen_trade_id('TRD', 20000 + idx),
                'PORT_ID': port_id,
                'AST_CD': ast_cd,
                'TRADE_DT': dt,
                'SETT_DT': shift_trade_dates(dt, sett_n),
                'BS_DIR': bs_dir,
                'QTY': qty,
                'PRC': prc,
                'AMT': amt,
                'FEE': fee,
                'CCY': 'CNY',
            })
            if idx >= 200:
                return docs
    return docs


# ============== 4) dwd_trn_trade_val ==============
def build_trn_trade_val(ptl_docs: list):
    """从 trade_ptl 派生估值维度，仅债券交易"""
    docs = []
    for d in ptl_docs:
        ast_cd = d['AST_CD']
        if not is_bond(ast_cd):
            continue
        bt = get_bond_template(ast_cd)
        coupon = bt[4] if bt else 0.03
        # 模拟应计利息
        days_since = random.randint(10, 180)
        aci_amt = round(100 * coupon * days_since / 365.0, 4)
        net_prc = d['PRC']
        full_prc = round(net_prc + aci_amt, 4)
        real_pnl = round(random.uniform(-0.5, 0.5) * d['QTY'] / 100, 2)
        amort = round(random.uniform(0.001, 0.02) * d['QTY'], 2)
        docs.append({
            'TRADE_ID': d['TRADE_ID'],
            'PORT_ID': d['PORT_ID'],
            'AST_CD': ast_cd,
            'BIZ_DT': d['TRADE_DT'],
            'BS_DIR': d['BS_DIR'],
            'NET_PRC': net_prc,
            'FULL_PRC': full_prc,
            'ACI_AMT': aci_amt,
            'REAL_PNL': real_pnl,
            'FEE_AMT': d['FEE'],
            'AMORT_AMT': amort,
            'VAL_STATUS': random.choices(['VALUED', 'UNVAL', 'ADJUSTED'], weights=[80, 10, 10])[0],
        })
    return docs


# ============== 5) dwd_trn_trade_zg ==============
def build_trn_trade_zg(ptl_docs: list):
    """中证登结算：IB 市场债券"""
    docs = []
    for d in ptl_docs:
        ast_cd = d['AST_CD']
        if not ast_cd.endswith('.IB'):
            continue
        docs.append({
            'TRADE_ID': d['TRADE_ID'],
            'SETT_DT': d['SETT_DT'],
            'SETT_AMT': d['AMT'],
            'SETT_QTY': d['QTY'],
            'SETT_TYPE': random.choices(['DVP', 'NETTING', 'CASH'], weights=[70, 20, 10])[0],
            'BOND_ACCT_NO': f'B{random.randint(1000000000, 9999999999)}',
            'CASH_ACCT_NO': f'C{random.randint(1000000000, 9999999999)}',
            'SETT_STATUS': random.choices(
                ['SETTLED', 'UNSETTLED', 'PARTIAL', 'FAILED'],
                weights=[80, 10, 7, 3]
            )[0],
        })
    return docs


# ============== 6) dwd_trn_trade_jy ==============
def build_trn_trade_jy(ptl_docs: list):
    """交易所结算：SSE/SZSE"""
    docs = []
    for d in ptl_docs:
        ast_cd = d['AST_CD']
        mkt = get_market_for_ast(ast_cd)
        if mkt not in ('SSE', 'SZSE'):
            continue
        amt = d['AMT']
        commission = round(amt * 0.0003, 2)
        # 印花税仅卖方
        stamp_tax = round(amt * 0.001, 2) if d['BS_DIR'] == 'S' else 0.0
        docs.append({
            'TRADE_ID': d['TRADE_ID'],
            'SETT_DT': d['SETT_DT'],
            'EXCH': mkt,
            'SETT_AMT': amt,
            'SETT_QTY': d['QTY'],
            'COMMISSION': commission,
            'STAMP_TAX': stamp_tax,
            'SETT_STATUS': random.choices(
                ['SETTLED', 'UNSETTLED', 'PARTIAL', 'FAILED'],
                weights=[85, 8, 5, 2]
            )[0],
        })
    return docs


# ============== 7) dwd_cust_trans_apply_info_* ==============
def build_cust_apply(channel: str, count: int):
    """构建申请单"""
    docs = []
    prefix = {'S5': 'S5', 'TA': 'TA', 'YH': 'YH'}[channel]
    for i in range(1, count + 1):
        dt = random.choice(TRADE_DATES)
        cust_id = random.choice(CUSTOMER_IDS)
        port_id = random.choice(PORT_IDS)
        trd_type = random.choices(['SUBSCRIBE', 'REDEEM', 'DIVIDEND'], weights=[50, 40, 10])[0]
        amt = round(random.uniform(1000, 500000), 2)
        pt = get_port_template(port_id)
        nav = pt[6] if pt else 1.0  # AUM as placeholder, use random nav
        nav_val = round(random.uniform(0.95, 3.5), 4)
        shr = round(amt / nav_val, 2) if trd_type != 'DIVIDEND' else 0
        status = random.choices(['CONFIRMED', 'PENDING', 'CANCELLED'], weights=[75, 15, 10])[0]
        cfm_dt = shift_trade_dates(dt, 1) if status == 'CONFIRMED' else ''
        docs.append({
            'APPLY_NO': f'{prefix}{dt}{i:04d}',
            'CUSTOMER_ID': cust_id,
            'PORT_ID': port_id,
            'TRADE_DT': dt,
            'TRD_TYPE': trd_type,
            'AMT': amt,
            'SHR': shr,
            'CHANNEL': channel,
            'STATUS': status,
            'CFM_DT': cfm_dt,
        })
    return docs


# ============== 8) dwd_cust_trans_cfm_info ==============
def build_cust_cfm(apply_docs_all: list):
    """从已确认的申请单派生确认记录"""
    docs = []
    cfm_idx = 0
    for d in apply_docs_all:
        if d['STATUS'] != 'CONFIRMED':
            continue
        cfm_idx += 1
        nav_val = round(random.uniform(0.95, 3.5), 4)
        cfm_amt = d['AMT']
        cfm_shr = round(cfm_amt / nav_val, 2)
        fee = round(cfm_amt * random.uniform(0.001, 0.015), 2)
        net_amt = round(cfm_amt - fee, 2) if d['TRD_TYPE'] == 'SUBSCRIBE' else round(cfm_amt + fee, 2)
        docs.append({
            'CFM_NO': f'CFM{cfm_idx:08d}',
            'APPLY_NO': d['APPLY_NO'],
            'CUSTOMER_ID': d['CUSTOMER_ID'],
            'PORT_ID': d['PORT_ID'],
            'CFM_DT': d['CFM_DT'],
            'TRD_TYPE': d['TRD_TYPE'],
            'CFM_AMT': cfm_amt,
            'CFM_SHR': cfm_shr,
            'CFM_NAV': nav_val,
            'FEE': fee,
            'NET_AMT': net_amt,
            'STATUS': 'SUCCESS',
        })
    return docs


# ============== 9) dwd_cust_trans_divd_info ==============
def build_cust_divd():
    """分红记录：每个月 1~2 个组合分红"""
    docs = []
    # 取最近 3 个月的分红日（每月 15 日附近）
    divd_dates = [d for d in TRADE_DATES if int(d[6:8]) in (14, 15, 16)]
    if len(divd_dates) < 3:
        divd_dates = random.sample(TRADE_DATES, k=min(5, len(TRADE_DATES)))
    for dt in divd_dates:
        # 每次 3~5 个客户×组合分红
        n = random.randint(3, 5)
        custs = random.sample(CUSTOMER_IDS, k=n)
        port_id = random.choice(PORT_IDS[:18])  # 货币/债券型更常分红
        div_per_shr = round(random.uniform(0.005, 0.05), 4)
        ex_div_dt = shift_trade_dates(dt, 1)
        pay_dt = shift_trade_dates(dt, 3)
        for cust_id in custs:
            hld_shr = round(random.uniform(5000, 500000), 2)
            div_amt = round(hld_shr * div_per_shr, 2)
            tax = round(div_amt * 0.2, 2) if random.random() < 0.3 else 0.0
            net_div = round(div_amt - tax, 2)
            docs.append({
                'CUSTOMER_ID': cust_id,
                'PORT_ID': port_id,
                'DIV_DT': dt,
                'EX_DIV_DT': ex_div_dt,
                'PAY_DT': pay_dt,
                'DIV_PER_SHR': div_per_shr,
                'HLD_SHR': hld_shr,
                'DIV_AMT': div_amt,
                'DIV_TYPE': random.choices(['CASH', 'REINVEST'], weights=[70, 30])[0],
                'TAX': tax,
                'NET_DIV_AMT': net_div,
            })
    return docs


# ============== 10) dwd_cust_trans_srl_info ==============
def build_cust_srl(apply_docs_all: list, divd_docs: list):
    """客户流水：从申请单 + 分红派生"""
    docs = []
    srl_idx = 0
    # 从申请单派生
    for d in apply_docs_all:
        if d['STATUS'] == 'CANCELLED':
            continue
        srl_idx += 1
        amt = d['AMT'] if d['TRD_TYPE'] == 'SUBSCRIBE' else -d['AMT']
        bal_before = round(random.uniform(10000, 2000000), 2)
        bal_after = round(bal_before + amt, 2)
        docs.append({
            'SRL_NO': f'SRL{srl_idx:08d}',
            'CUSTOMER_ID': d['CUSTOMER_ID'],
            'PORT_ID': d['PORT_ID'],
            'REL_NO': d['APPLY_NO'],
            'BIZ_DT': d['TRADE_DT'],
            'BIZ_TYPE': d['TRD_TYPE'],
            'AMT': round(abs(amt), 2),
            'BAL_BEFORE': bal_before,
            'BAL_AFTER': bal_after,
            'CCY': 'CNY',
            'REMARK': f'{d["TRD_TYPE"]}交易 {d["CHANNEL"]}渠道',
        })
    # 从分红派生
    for d in divd_docs:
        srl_idx += 1
        bal_before = round(random.uniform(10000, 2000000), 2)
        bal_after = round(bal_before + d['NET_DIV_AMT'], 2)
        docs.append({
            'SRL_NO': f'SRL{srl_idx:08d}',
            'CUSTOMER_ID': d['CUSTOMER_ID'],
            'PORT_ID': d['PORT_ID'],
            'REL_NO': '',
            'BIZ_DT': d['PAY_DT'],
            'BIZ_TYPE': 'DIVIDEND',
            'AMT': d['NET_DIV_AMT'],
            'BAL_BEFORE': bal_before,
            'BAL_AFTER': bal_after,
            'CCY': 'CNY',
            'REMARK': f'分红到账 每份{d["DIV_PER_SHR"]:.4f}元',
        })
    return docs


# ============== MAIN ==============
def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    def upsert(coll_name, docs):
        coll = db[coll_name]
        old_cnt = coll.count_documents({})
        coll.delete_many({})
        if docs:
            coll.insert_many(docs)
        print(f'[B4] {coll_name:<36}: 清空 {old_cnt:>5} -> 写入 {len(docs):>5}')

    # 交易域
    orders = build_trn_order()
    upsert('dwd_trn_order', orders)

    trade_ast = build_trn_trade_ast()
    upsert('dwd_trn_trade_ast', trade_ast)

    trade_ptl = build_trn_trade_ptl()
    upsert('dwd_trn_trade_ptl', trade_ptl)

    trade_val = build_trn_trade_val(trade_ptl)
    upsert('dwd_trn_trade_val', trade_val)

    trade_zg = build_trn_trade_zg(trade_ptl)
    upsert('dwd_trn_trade_zg', trade_zg)

    trade_jy = build_trn_trade_jy(trade_ptl)
    upsert('dwd_trn_trade_jy', trade_jy)

    # 客户交易域
    apply_s5 = build_cust_apply('S5', 30)
    upsert('dwd_cust_trans_apply_info_s5', apply_s5)

    apply_ta = build_cust_apply('TA', 50)
    upsert('dwd_cust_trans_apply_info_ta', apply_ta)

    apply_yh = build_cust_apply('YH', 100)
    upsert('dwd_cust_trans_apply_info_yh', apply_yh)

    all_applies = apply_s5 + apply_ta + apply_yh
    cfm_docs = build_cust_cfm(all_applies)
    upsert('dwd_cust_trans_cfm_info', cfm_docs)

    divd_docs = build_cust_divd()
    upsert('dwd_cust_trans_divd_info', divd_docs)

    srl_docs = build_cust_srl(all_applies, divd_docs)
    upsert('dwd_cust_trans_srl_info', srl_docs)

    # 数据质量抽样
    print('\n--- 数据抽样 ---')
    sample = db.dwd_trn_order.find_one({'STATUS': 'FILLED'}, {'_id': 0})
    print(f'dwd_trn_order 样本: {sample}')
    sample = db.dwd_trn_trade_ptl.find_one({}, {'_id': 0})
    print(f'dwd_trn_trade_ptl 样本: {sample}')
    sample = db.dwd_cust_trans_cfm_info.find_one({}, {'_id': 0})
    print(f'dwd_cust_trans_cfm_info 样本: {sample}')
    sample = db.dwd_cust_trans_divd_info.find_one({}, {'_id': 0})
    print(f'dwd_cust_trans_divd_info 样本: {sample}')

    print('\n[B4] ✅ 完成')
    client.close()


if __name__ == '__main__':
    main()
