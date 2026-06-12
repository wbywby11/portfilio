"""
ZY 数据真实化 - 批次 5：行情时序 + 风控/合规

行情域 (25 tables):
- dwd_mkt_bond / bond_market / bond_duration / bond_ecl / bond_creditrating / bond_amount
- dwd_mkt_stock / stock_yield
- dwd_mkt_index / index_quote / index_member
- dwd_mkt_fund / fund_market / fund_derive / fund_allocation / fund_structure / fund_suspension
- dwd_mkt_curve / curve_quote / rate / rate_quote / exrate / calendar / date / rating

风险域 (5 tables):
- dwd_rsk_sentiment / credit / credit_position / dwd_crdt_agme_info / dwd_crdt_main_rela_rela_info
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
    PORT_TEMPLATES, CNTP_TEMPLATES, CNTP_IDS,
    INDEX_TEMPLATES, INDEX_CDS, CURVE_TEMPLATES, CURVE_IDS,
    RATE_TEMPLATES, RATE_CDS,
    ISR_TEMPLATES, RATING_AGENCIES, CREDIT_RATINGS, RATING_OUTLOOKS,
    is_bond, get_bond_template,
    BONDS, STOCKS, FUNDS, TENORS,
)
from zy_data_helpers import (
    gen_trade_dates, gbm_path, vasicek_path, ohlc_from_close,
    parse_dt, fmt_dt,
)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"
random.seed(20250405)

TRADE_DATES = gen_trade_dates(BIZ_DT, 60)
N_DAYS = len(TRADE_DATES)


# ============ MARKET - BOND ============

def build_mkt_bond():
    """14 核心债券 × 60 日行情"""
    core_bonds = BONDS[:14]
    docs = []
    for b_cd in core_bonds:
        bt = get_bond_template(b_cd)
        coupon = bt[4] if bt else 0.03
        sub_type = bt[2] if bt else 'CGB'
        # YTM 中枢根据类型
        ytm_base = {'CGB': 0.022, 'POLICY': 0.025, 'MTN': 0.032,
                    'ENTERPRISE': 0.040, 'NCD': 0.022, 'CB': 0.015}.get(sub_type, 0.03)
        ytm_path = vasicek_path(ytm_base, N_DAYS, long_term=ytm_base,
                                kappa=0.10, sigma=0.003, seed=hash(b_cd) % 10000)
        for i, dt in enumerate(TRADE_DATES):
            ytm = ytm_path[i]
            # 净价 ≈ 100 + (coupon - ytm) * duration * 100
            dur_est = 3.0 if sub_type == 'NCD' else 5.0
            close_prc = round(100 + (coupon - ytm) * dur_est * 100 + random.uniform(-0.1, 0.1), 4)
            vol_range = random.uniform(0.002, 0.005)
            high = round(close_prc * (1 + vol_range), 4)
            low = round(close_prc * (1 - vol_range), 4)
            open_prc = round(random.uniform(low, high), 4)
            vol = random.randint(50000, 500000) * 10
            amt = round(vol * close_prc / 100, 2)
            prev_ytm = ytm_path[i - 1] if i > 0 else ytm_base
            chg_bp = round((ytm - prev_ytm) * 10000, 2)
            docs.append({
                'AST_CD': b_cd, 'BIZ_DT': dt,
                'OPEN_PRC': open_prc, 'HIGH_PRC': high, 'LOW_PRC': low,
                'CLOSE_PRC': close_prc, 'VOL': vol, 'AMT': amt,
                'YTM': round(ytm, 6), 'CHG_BP': chg_bp,
            })
    return docs


def build_mkt_bond_market():
    """债券逐日成交（与 dwd_mkt_bond 覆盖相同券但含加权信息）"""
    core_bonds = BONDS[:14]
    docs = []
    for b_cd in core_bonds:
        for dt in TRADE_DATES:
            vol = random.randint(10000, 300000) * 10
            avg_prc = round(random.uniform(98.5, 102.0), 4)
            amt = round(vol * avg_prc / 100, 2)
            bt = get_bond_template(b_cd)
            sub_type = bt[2] if bt else 'CGB'
            ytm_base = {'CGB': 0.022, 'POLICY': 0.025, 'MTN': 0.032,
                        'ENTERPRISE': 0.040, 'NCD': 0.022}.get(sub_type, 0.03)
            avg_ytm = round(ytm_base + random.uniform(-0.003, 0.003), 6)
            trade_cnt = random.randint(5, 80)
            docs.append({
                'AST_CD': b_cd, 'BIZ_DT': dt,
                'VOL': vol, 'AMT': amt, 'AVG_PRC': avg_prc,
                'AVG_YTM': avg_ytm, 'TRADE_CNT': trade_cnt,
            })
    return docs


def build_mkt_bond_duration():
    """债券久期凸性（每只债 1 条最新）"""
    docs = []
    for bt in BOND_TEMPLATES:
        b_cd, _, sub_type, _, coupon, mat_dt, _, _, term_str, _ = bt
        term_map = {'3M': 0.25, '6M': 0.5, '1Y': 1, '3Y': 3, '5Y': 5,
                    '7Y': 7, '10Y': 10, '20Y': 20, '30Y': 30}
        ytm = coupon + random.uniform(-0.005, 0.005)
        term_val = term_map.get(term_str, 5)
        mac_dur = round(term_val * (1 - 1 / (1 + ytm) ** term_val) / ytm if ytm > 0 else term_val, 4)
        mod_dur = round(mac_dur / (1 + ytm), 4)
        convexity = round(mac_dur ** 2 + mac_dur, 2)
        # Key rate durations (简化)
        kr_1y = round(max(0, mod_dur * 0.1 * random.uniform(0.8, 1.2)), 4) if term_val >= 1 else 0
        kr_3y = round(max(0, mod_dur * 0.2 * random.uniform(0.8, 1.2)), 4) if term_val >= 3 else 0
        kr_5y = round(max(0, mod_dur * 0.3 * random.uniform(0.8, 1.2)), 4) if term_val >= 5 else 0
        kr_10y = round(max(0, mod_dur * 0.4 * random.uniform(0.8, 1.2)), 4) if term_val >= 10 else 0
        docs.append({
            'AST_CD': b_cd, 'BIZ_DT': BIZ_DT,
            'MOD_DURATION': mod_dur, 'MAC_DURATION': mac_dur,
            'CONVEXITY': convexity,
            'KEY_RATE_1Y': kr_1y, 'KEY_RATE_3Y': kr_3y,
            'KEY_RATE_5Y': kr_5y, 'KEY_RATE_10Y': kr_10y,
        })
    return docs


def build_mkt_bond_ecl():
    """预期信用损失（非利率债 50 条）"""
    non_gov = [bt for bt in BOND_TEMPLATES if bt[2] not in ('CGB', 'POLICY')]
    docs = []
    for bt in non_gov[:50]:
        b_cd = bt[0]
        sub_type = bt[2]
        stage = random.choices([1, 2, 3], weights=[80, 15, 5])[0]
        pd_12m = round(random.uniform(0.0001, 0.03) if sub_type == 'MTN' else random.uniform(0.0005, 0.05), 6)
        pd_life = round(pd_12m * random.uniform(2, 8), 6)
        lgd = round(random.uniform(0.30, 0.60), 4)
        ead = round(random.uniform(1e6, 5e8), 2)
        ecl_amt = round(pd_12m * lgd * ead if stage == 1 else pd_life * lgd * ead, 2)
        docs.append({
            'AST_CD': b_cd, 'BIZ_DT': BIZ_DT,
            'STAGE': stage, 'PD_12M': pd_12m, 'PD_LIFE': pd_life,
            'LGD': lgd, 'EAD': ead, 'ECL_AMT': ecl_amt,
        })
    return docs


def build_mkt_bond_creditrating():
    """债项评级（60 条评级记录）"""
    docs = []
    for bt in BOND_TEMPLATES[:60]:
        b_cd = bt[0]
        sub_type = bt[2]
        if sub_type in ('CGB', 'POLICY'):
            bond_rating = 'AAA'
            issuer_rating = 'AAA'
        elif sub_type == 'MTN':
            bond_rating = random.choice(['AAA', 'AA+', 'AA'])
            issuer_rating = bond_rating
        else:
            bond_rating = random.choice(['AA+', 'AA', 'AA-', 'A+'])
            issuer_rating = random.choice(['AA+', 'AA', 'AA-'])
        agency = random.choice(RATING_AGENCIES)
        rating_dt = random.choice(TRADE_DATES[:30])
        docs.append({
            'AST_CD': b_cd, 'RATING_DT': rating_dt, 'AGENCY': agency,
            'BOND_RATING': bond_rating, 'ISSUER_RATING': issuer_rating,
            'OUTLOOK': random.choices(['STABLE', 'POSITIVE', 'NEGATIVE'], weights=[75, 15, 10])[0],
        })
    return docs


def build_mkt_bond_amount():
    """债券存量"""
    docs = []
    for bt in BOND_TEMPLATES:
        b_cd = bt[0]
        issue_amt = bt[5] if isinstance(bt[5], (int, float)) else 500
        # 实际上 bt[5] 是 MATURITY_DT (string), bt[6] 是 ISSUE_AMT
        issue_amt_v = bt[6]  # 亿
        outstanding = round(issue_amt_v * random.uniform(0.7, 1.0), 2)
        repaid = round(issue_amt_v - outstanding, 2)
        docs.append({
            'AST_CD': b_cd, 'BIZ_DT': BIZ_DT,
            'ISSUE_AMT': issue_amt_v, 'OUTSTANDING_AMT': outstanding,
            'REPAID_AMT': repaid,
        })
    return docs


# ============ MARKET - STOCK ============

def build_mkt_stock():
    """股票主数据（30 条）"""
    docs = []
    for st in STOCK_TEMPLATES:
        ast_cd, nm, exch, ind_cd, ind_nm, isr_idx, list_dt, tot_cap = st
        free_cap = round(tot_cap * random.uniform(0.65, 0.95), 2)
        docs.append({
            'AST_CD': ast_cd, 'STOCK_NM': nm, 'EXCH': exch,
            'INDUSTRY_CD': ind_cd, 'INDUSTRY_NM': ind_nm,
            'LIST_DT': list_dt, 'TOT_CAP': tot_cap, 'FREE_CAP': free_cap,
            'ISR_ID': ISR_IDS[isr_idx] if isr_idx < len(ISR_IDS) else ISR_IDS[0],
            'BIZ_DT': BIZ_DT,
        })
    return docs


def build_mkt_stock_yield():
    """股票 60 日行情时序"""
    docs = []
    for st in STOCK_TEMPLATES:
        ast_cd, nm, exch, _, _, _, _, tot_cap = st
        # 根据市值估算起始价
        start_prc = round(tot_cap * 1e8 / (random.uniform(5e9, 5e10)), 2)
        start_prc = max(3.0, min(start_prc, 300.0))
        # GBM 模拟
        mu = random.uniform(-0.05, 0.15)
        sigma = random.uniform(0.15, 0.40)
        close_path = gbm_path(start_prc, N_DAYS, mu_annual=mu,
                              sigma_annual=sigma, seed=hash(ast_cd) % 10000)
        ohlc = ohlc_from_close(close_path, intraday_vol=0.012)
        pe_base = random.uniform(8, 60)
        pb_base = random.uniform(0.5, 8)
        ytd_start = close_path[0]
        for i, dt in enumerate(TRADE_DATES):
            close_prc = round(close_path[i], 2)
            daily_rtn = round((close_path[i] / close_path[i - 1] - 1) if i > 0 else 0, 6)
            week_rtn = round((close_path[i] / close_path[max(0, i - 5)] - 1), 6)
            month_rtn = round((close_path[i] / close_path[max(0, i - 22)] - 1), 6)
            ytd_rtn = round((close_path[i] / ytd_start - 1), 6)
            vol = random.randint(100000, 5000000) * 100
            amt = round(vol * close_prc, 2)
            turnover = round(random.uniform(0.002, 0.08), 4)
            pe = round(pe_base * (1 + random.uniform(-0.1, 0.1)), 2)
            pb = round(pb_base * (1 + random.uniform(-0.05, 0.05)), 2)
            docs.append({
                'AST_CD': ast_cd, 'BIZ_DT': dt,
                'OPEN_PRC': ohlc[i][0], 'HIGH_PRC': ohlc[i][1],
                'LOW_PRC': ohlc[i][2], 'CLOSE_PRC': close_prc,
                'VOL': vol, 'AMT': amt, 'DAILY_RTN': daily_rtn,
                'WEEK_RTN': week_rtn, 'MONTH_RTN': month_rtn,
                'YTD_RTN': ytd_rtn, 'TURNOVER': turnover,
                'PE_TTM': pe, 'PB_LF': pb,
            })
    return docs


# ============ MARKET - INDEX ============

def build_mkt_index():
    """指数主数据（20 条）"""
    docs = []
    for idx_t in INDEX_TEMPLATES:
        cd, nm, publisher, base_dt, base_val, idx_type = idx_t
        docs.append({
            'INDEX_CD': cd, 'INDEX_NM': nm, 'PUBLISHER': publisher,
            'BASE_DT': base_dt, 'BASE_VAL': base_val,
            'INDEX_TYPE': idx_type, 'BIZ_DT': BIZ_DT,
        })
    return docs


def build_mkt_index_quote():
    """指数行情 60 日（5 核心权益指数 × 60）"""
    core_idx = INDEX_CDS[:5]
    docs = []
    for cd in core_idx:
        idx_t = next((t for t in INDEX_TEMPLATES if t[0] == cd), None)
        base_val = idx_t[4] if idx_t else 1000.0
        # 当前值
        start_val = base_val * random.uniform(2.5, 5.5) if base_val == 1000 else random.uniform(2800, 3500)
        path = gbm_path(start_val, N_DAYS, mu_annual=0.03, sigma_annual=0.18,
                        seed=hash(cd) % 10000)
        ohlc = ohlc_from_close(path, intraday_vol=0.008)
        ytd_start = path[0]
        for i, dt in enumerate(TRADE_DATES):
            close_val = round(path[i], 2)
            daily_rtn = round((path[i] / path[i - 1] - 1) if i > 0 else 0, 6)
            ytd_rtn = round((path[i] / ytd_start - 1), 6)
            vol = random.randint(int(1e8), int(5e9))
            amt = round(vol * random.uniform(8, 15), 2)
            docs.append({
                'INDEX_CD': cd, 'BIZ_DT': dt,
                'OPEN_VAL': ohlc[i][0], 'HIGH_VAL': ohlc[i][1],
                'LOW_VAL': ohlc[i][2], 'CLOSE_VAL': close_val,
                'VOL': vol, 'AMT': amt,
                'DAILY_RTN': daily_rtn, 'YTD_RTN': ytd_rtn,
            })
    return docs


def build_mkt_index_member():
    """指数成分（沪深 300 前 10 个成分示意）"""
    docs = []
    idx_cd = '000300.SH'
    members = STOCKS[:10]
    for ast_cd in members:
        weight = round(random.uniform(0.01, 0.06), 4)
        docs.append({
            'INDEX_CD': idx_cd, 'AST_CD': ast_cd, 'BIZ_DT': BIZ_DT,
            'WEIGHT': weight, 'IN_DT': '20200101', 'OUT_DT': '',
        })
    return docs


# ============ MARKET - FUND ============

def build_mkt_fund():
    """基金主数据（30 条）"""
    custody_banks = ['中国工商银行', '中国建设银行', '中国银行', '招商银行', '交通银行']
    benchmarks = {
        'ETF': '沪深300指数收益率×95%+银行活期存款利率×5%',
        'LOF': '中证500指数收益率×80%+中债总指数收益率×20%',
        'MMF': '七天通知存款利率(税后)',
        'OPEN': '中债综合全价指数收益率',
        'INDEX': '创业板指数收益率×95%+银行活期存款利率×5%',
        'FOF': '沪深300×40%+中债综合×40%+同业存款×20%',
    }
    docs = []
    for ft in FUND_TEMPLATES:
        ast_cd, fund_nm, fund_type, mgr_inst, estab_dt, aum = ft
        docs.append({
            'AST_CD': ast_cd, 'FUND_NM': fund_nm,
            'FUND_TYPE': fund_type, 'MGR_INST': mgr_inst,
            'CUSTODY_BANK': random.choice(custody_banks),
            'ESTAB_DT': estab_dt,
            'BENCHMARK': benchmarks.get(fund_type, '沪深300指数收益率'),
            'AUM': aum, 'BIZ_DT': BIZ_DT,
        })
    return docs


def build_mkt_fund_market():
    """基金净值 60 日时序"""
    docs = []
    for ft in FUND_TEMPLATES:
        ast_cd, _, fund_type, _, _, _ = ft
        if fund_type == 'MMF':
            start_nav = 1.0
            path = [round(1.0 + i * random.uniform(0.00005, 0.00012), 4) for i in range(N_DAYS)]
        else:
            start_nav = round(random.uniform(0.8, 3.5), 4)
            sigma = 0.05 if fund_type in ('OPEN',) else 0.15
            path = gbm_path(start_nav, N_DAYS, mu_annual=0.06,
                            sigma_annual=sigma, seed=hash(ast_cd) % 10000)
        for i, dt in enumerate(TRADE_DATES):
            unit_nav = round(path[i], 4)
            acc_nav = round(unit_nav + random.uniform(0, 1.5), 4)
            daily_rtn = round((path[i] / path[i - 1] - 1) if i > 0 else 0, 6)
            vol = random.randint(10000, 2000000) * 100
            amt = round(vol * unit_nav, 2)
            docs.append({
                'AST_CD': ast_cd, 'BIZ_DT': dt,
                'UNIT_NAV': unit_nav, 'ACC_NAV': acc_nav,
                'DAILY_RTN': daily_rtn, 'VOL': vol, 'AMT': amt,
            })
    return docs


def build_mkt_fund_derive():
    """基金衍生指标"""
    docs = []
    for ft in FUND_TEMPLATES:
        ast_cd, _, fund_type, _, _, _ = ft
        sharpe = round(random.uniform(-0.5, 2.5), 4)
        sortino = round(sharpe * random.uniform(1.0, 1.8), 4)
        max_dd = round(random.uniform(0.01, 0.30) if fund_type != 'MMF' else random.uniform(0, 0.002), 4)
        vol_1y = round(random.uniform(0.02, 0.25) if fund_type != 'MMF' else random.uniform(0.001, 0.005), 4)
        beta = round(random.uniform(0.5, 1.2), 4) if fund_type in ('ETF', 'INDEX') else round(random.uniform(0.1, 0.8), 4)
        alpha = round(random.uniform(-0.05, 0.10), 4)
        tracking_err = round(random.uniform(0.001, 0.05), 4)
        docs.append({
            'AST_CD': ast_cd, 'BIZ_DT': BIZ_DT,
            'SHARPE_1Y': sharpe, 'SORTINO_1Y': sortino,
            'MAX_DD_1Y': max_dd, 'VOL_1Y': vol_1y,
            'BETA_1Y': beta, 'ALPHA_1Y': alpha,
            'TRACKING_ERR': tracking_err,
        })
    return docs


def build_mkt_fund_allocation():
    """基金资产配置"""
    alloc_map = {
        'ETF': [('STOCK', 0.92), ('CASH', 0.05), ('OTHER', 0.03)],
        'LOF': [('STOCK', 0.80), ('BOND', 0.10), ('CASH', 0.08), ('OTHER', 0.02)],
        'MMF': [('CASH', 0.55), ('BOND', 0.40), ('OTHER', 0.05)],
        'OPEN': [('BOND', 0.85), ('CASH', 0.12), ('OTHER', 0.03)],
        'INDEX': [('STOCK', 0.95), ('CASH', 0.04), ('OTHER', 0.01)],
        'FOF': [('STOCK', 0.35), ('BOND', 0.35), ('CASH', 0.20), ('OTHER', 0.10)],
    }
    docs = []
    rpt_dt = '20241231'
    for ft in FUND_TEMPLATES:
        ast_cd, _, fund_type, _, _, aum = ft
        allocs = alloc_map.get(fund_type, [('BOND', 0.5), ('CASH', 0.5)])
        for cls, ratio in allocs:
            mkv = round(aum * 1e8 * ratio * random.uniform(0.9, 1.1), 2)
            docs.append({
                'AST_CD': ast_cd, 'RPT_DT': rpt_dt,
                'AST_CLASS': cls, 'MKT_VAL': mkv,
                'RATIO': round(ratio + random.uniform(-0.02, 0.02), 4),
            })
    return docs


def build_mkt_fund_structure():
    """基金份额结构"""
    docs = []
    holder_types = ['INST', 'IND', 'INSIDER']
    rpt_dt = '20241231'
    for ft in FUND_TEMPLATES:
        ast_cd, _, fund_type, _, _, aum = ft
        tot_shr = round(aum * 1e8 / random.uniform(0.8, 3.0), 2)
        if fund_type == 'MMF':
            ratios = [0.60, 0.38, 0.02]
        else:
            ratios = [random.uniform(0.3, 0.7), 0, 0]
            ratios[1] = round(1 - ratios[0] - 0.01, 4)
            ratios[2] = 0.01
        for ht, r in zip(holder_types, ratios):
            docs.append({
                'AST_CD': ast_cd, 'RPT_DT': rpt_dt,
                'HOLDER_TYPE': ht, 'TOT_SHR': round(tot_shr * r, 2),
                'RATIO': round(r, 4),
            })
    return docs


def build_mkt_fund_suspension():
    """基金停牌（少量 5 条）"""
    docs = []
    for i in range(5):
        ast_cd = random.choice(FUNDS)
        sus_dt = random.choice(TRADE_DATES[:20])
        from zy_data_helpers import shift_trade_dates
        res_dt = shift_trade_dates(sus_dt, random.randint(1, 5))
        reasons = ['大额申购限制', '年末集中估值', '净值偏离处理', '基金合同修改', '信息披露']
        docs.append({
            'AST_CD': ast_cd, 'SUS_DT': sus_dt,
            'RES_DT': res_dt,
            'SUS_TYPE': random.choice(['NEW_YEAR', 'BIG_SUB_LIMIT', 'OTHER']),
            'REASON': random.choice(reasons),
        })
    return docs


# ============ MARKET - CURVE / RATE / FX ============

def build_mkt_curve():
    """曲线主数据（12）"""
    docs = []
    for ct in CURVE_TEMPLATES:
        cd, nm, ccy, source, ctype = ct
        docs.append({
            'CURVE_ID': cd, 'CURVE_NM': nm, 'CCY': ccy,
            'SOURCE': source, 'CURVE_TYPE': ctype,
        })
    return docs


def build_mkt_curve_quote():
    """曲线节点报价 12×10期限×60日 (但为控制规模取 6 条曲线)"""
    tenors = ['ON', '1W', '1M', '3M', '6M', '1Y', '3Y', '5Y', '7Y', '10Y']
    core_curves = CURVE_IDS[:6]
    base_levels = {
        'CGB': [0.012, 0.013, 0.015, 0.017, 0.019, 0.021, 0.024, 0.026, 0.028, 0.030],
        'CDB': [0.014, 0.016, 0.018, 0.020, 0.022, 0.025, 0.028, 0.030, 0.032, 0.034],
        'IMP_EXP': [0.014, 0.016, 0.018, 0.020, 0.023, 0.026, 0.029, 0.031, 0.033, 0.035],
        'AGRI_DEV': [0.014, 0.016, 0.018, 0.021, 0.024, 0.027, 0.030, 0.032, 0.034, 0.036],
        'AAA_MTN': [0.018, 0.020, 0.022, 0.025, 0.028, 0.032, 0.038, 0.042, 0.045, 0.048],
        'AA+_MTN': [0.020, 0.022, 0.025, 0.028, 0.032, 0.036, 0.042, 0.048, 0.052, 0.055],
    }
    docs = []
    for cd in core_curves:
        bases = base_levels.get(cd, base_levels['CGB'])
        for t_idx, tenor in enumerate(tenors):
            base_yield = bases[t_idx]
            path = vasicek_path(base_yield, N_DAYS, long_term=base_yield,
                                kappa=0.08, sigma=0.002, seed=hash(cd + tenor) % 10000)
            for i, dt in enumerate(TRADE_DATES):
                yld = path[i]
                prev_yld = path[i - 1] if i > 0 else base_yield
                chg_bp = round((yld - prev_yld) * 10000, 2)
                docs.append({
                    'CURVE_ID': cd, 'BIZ_DT': dt, 'TENOR': tenor,
                    'YIELD': round(yld, 6), 'CHG_BP': chg_bp,
                })
    return docs


def build_mkt_rate():
    """利率主数据（15）"""
    return [{'RATE_CD': t[0], 'RATE_NM': t[1], 'SOURCE': t[2],
             'CCY': t[3], 'BIZ_DT': BIZ_DT} for t in RATE_TEMPLATES]


def build_mkt_rate_quote():
    """利率报价 15×60"""
    rate_bases = {
        'SHIBOR_ON': 0.015, 'SHIBOR_1W': 0.018, 'SHIBOR_2W': 0.019,
        'SHIBOR_1M': 0.020, 'SHIBOR_3M': 0.021, 'SHIBOR_6M': 0.022,
        'SHIBOR_9M': 0.023, 'SHIBOR_1Y': 0.024,
        'LPR_1Y': 0.031, 'LPR_5Y': 0.036,
        'DR001': 0.014, 'DR007': 0.018, 'R001': 0.015, 'R007': 0.019,
        'NCD_3M_AAA': 0.020,
    }
    docs = []
    for rt in RATE_TEMPLATES:
        cd = rt[0]
        base = rate_bases.get(cd, 0.02)
        path = vasicek_path(base, N_DAYS, long_term=base,
                            kappa=0.2, sigma=0.003, seed=hash(cd) % 10000)
        for i, dt in enumerate(TRADE_DATES):
            prev = path[i - 1] if i > 0 else base
            chg_bp = round((path[i] - prev) * 10000, 2)
            docs.append({
                'RATE_CD': cd, 'BIZ_DT': dt,
                'RATE_VAL': round(path[i], 6), 'CHG_BP': chg_bp,
            })
    return docs


def build_mkt_exrate():
    """汇率 5 pairs × 60 days"""
    pairs = [
        ('USDCNY', 7.25), ('EURCNY', 7.85), ('GBPCNY', 9.15),
        ('JPYCNY', 0.048), ('HKDCNY', 0.93),
    ]
    docs = []
    for pair, mid_base in pairs:
        path = gbm_path(mid_base, N_DAYS, mu_annual=0.0, sigma_annual=0.04,
                        seed=hash(pair) % 10000)
        for i, dt in enumerate(TRADE_DATES):
            mid = round(path[i], 4)
            spread = mid * 0.001
            docs.append({
                'CCY_PAIR': pair, 'BIZ_DT': dt,
                'MID': mid, 'BID': round(mid - spread, 4),
                'ASK': round(mid + spread, 4), 'SRC': 'CFETS',
            })
    return docs


def build_mkt_calendar():
    """交易日历 (60 日)"""
    docs = []
    for dt in TRADE_DATES:
        d = parse_dt(dt)
        for cal_type in ['IB', 'SSE', 'SZSE']:
            docs.append({
                'CAL_DT': dt, 'CAL_TYPE': cal_type,
                'IS_TRADE': 'Y', 'WEEK_DAY': d.isoweekday(),
            })
    return docs


def build_mkt_date():
    """日期维度"""
    docs = []
    for dt in TRADE_DATES:
        d = parse_dt(dt)
        docs.append({
            'DT': dt, 'YEAR': str(d.year), 'QUARTER': f'Q{(d.month-1)//3+1}',
            'MONTH': f'{d.month:02d}', 'DAY': f'{d.day:02d}',
            'WEEK_OF_YEAR': d.isocalendar()[1],
            'IS_MONTH_END': 'Y' if (d + timedelta(days=1)).month != d.month else 'N',
            'IS_QUARTER_END': 'Y' if d.month in (3, 6, 9, 12) and (d + timedelta(days=1)).month != d.month else 'N',
            'IS_YEAR_END': 'Y' if d.month == 12 and d.day == 31 else 'N',
        })
    return docs


def build_mkt_rating():
    """评级动作"""
    docs = []
    for i in range(40):
        isr_id = random.choice(ISR_IDS[5:])  # 排除主权/央行
        rating_dt = random.choice(TRADE_DATES)
        agency = random.choice(RATING_AGENCIES)
        actions = ['AFFIRM', 'UPGRADE', 'DOWNGRADE', 'WATCH']
        action = random.choices(actions, weights=[60, 15, 15, 10])[0]
        if action == 'UPGRADE':
            prev = random.choice(['AA', 'AA-', 'A+'])
            cur = 'AA+' if prev == 'AA' else 'AA'
        elif action == 'DOWNGRADE':
            prev = random.choice(['AAA', 'AA+', 'AA'])
            cur = 'AA+' if prev == 'AAA' else 'AA-'
        else:
            cur = random.choice(CREDIT_RATINGS[:4])
            prev = cur
        outlook = random.choices(RATING_OUTLOOKS, weights=[20, 70, 10])[0]
        docs.append({
            'ISR_ID': isr_id, 'RATING_DT': rating_dt, 'AGENCY': agency,
            'RATING': cur, 'PREV_RATING': prev, 'ACTION': action,
            'OUTLOOK': outlook, 'BIZ_DT': BIZ_DT,
        })
    return docs


# ============ RISK DOMAIN ============

def build_rsk_sentiment():
    """舆情 50 条"""
    titles_neg = [
        '{}债务违约风险升高', '{}季度业绩大幅下滑', '{}被监管部门约谈',
        '{}信用评级遭下调', '{}资金链断裂传闻', '{}高管涉嫌违规被查',
        '{}商票逾期引发市场关注', '{}大规模裁员计划曝光',
    ]
    titles_pos = [
        '{}获国资增持 市场信心提振', '{}年报超预期 营收同比增长30%',
        '{}获批发行绿色债券200亿', '{}战略重组方案获批',
        '{}入选新一批科创板候选', '{}季度利润创历史新高',
    ]
    titles_neu = [
        '{}公告拟发行中期票据', '{}召开股东大会审议分红方案',
        '{}发布2024年年度报告', '{}完成工商变更登记',
    ]
    sources = ['中国债券信息网', '新华财经', '证券时报', '财新网', '中国证券报',
               '上证报', '21世纪经济报道', 'Wind资讯']
    docs = []
    for i in range(50):
        sent_type = random.choices(['NEGATIVE', 'POSITIVE', 'NEUTRAL'],
                                   weights=[40, 30, 30])[0]
        isr = random.choice(ISR_TEMPLATES[5:])
        isr_short = isr[2]  # 简称
        if sent_type == 'NEGATIVE':
            title = random.choice(titles_neg).format(isr_short)
        elif sent_type == 'POSITIVE':
            title = random.choice(titles_pos).format(isr_short)
        else:
            title = random.choice(titles_neu).format(isr_short)
        dt = random.choice(TRADE_DATES)
        hour = random.randint(6, 22)
        minute = random.randint(0, 59)
        score = round(random.uniform(0.6, 0.95) if sent_type == 'POSITIVE' else
                      random.uniform(0.1, 0.4) if sent_type == 'NEGATIVE' else
                      random.uniform(0.4, 0.6), 2)
        docs.append({
            'SENT_ID': f'SENT{i + 1:05d}',
            'TARGET_TYPE': 'ISR',
            'TARGET_CD': isr[0],
            'PUB_DT': dt, 'PUB_TM': f'{hour:02d}:{minute:02d}:00',
            'SOURCE': random.choice(sources),
            'TITLE': title, 'SENT_TYPE': sent_type,
            'SCORE': score, 'SUMMARY': f'{title}，需持续关注后续发展。',
        })
    return docs


def build_rsk_credit():
    """主体信用风险（60 条）"""
    docs = []
    for isr_t in ISR_TEMPLATES:
        isr_id = isr_t[0]
        isr_type = isr_t[3]
        ext_rating = isr_t[4]
        if isr_type == 'SOVEREIGN':
            internal = 'AAA'
            pd = round(random.uniform(0.0001, 0.001), 6)
        elif isr_type in ('POLICY_BANK', 'COMMERCIAL_BANK') and ext_rating == 'AAA':
            internal = 'AAA'
            pd = round(random.uniform(0.0002, 0.002), 6)
        else:
            internal = random.choice(['AA+', 'AA', 'AA-', 'A+'])
            pd = round(random.uniform(0.002, 0.05), 6)
        lgd = round(random.uniform(0.30, 0.55), 4)
        ead = round(random.uniform(1e7, 1e10), 2)
        el = round(pd * lgd * ead, 2)
        watch = 'Y' if pd > 0.02 else 'N'
        last_dt = random.choice(TRADE_DATES[:30])
        docs.append({
            'ISR_ID': isr_id, 'BIZ_DT': BIZ_DT,
            'INTERNAL_RATING': internal, 'EXT_RATING': ext_rating,
            'PD_1Y': pd, 'LGD': lgd, 'EAD': ead,
            'EXPECTED_LOSS': el, 'WATCH_FLAG': watch,
            'LAST_RATING_DT': last_dt,
        })
    return docs


def build_rsk_credit_position():
    """信用风险敞口（100 条）"""
    docs = []
    # 读取持仓
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    hld_docs = list(db.dwd_ptl_ast_hld.find({}, {'PORT_ID': 1, 'AST_CD': 1, 'MKT_VAL': 1, '_id': 0}))
    client.close()
    # 选取债券持仓
    bond_hlds = [h for h in hld_docs if any(h['AST_CD'] == b for b in BONDS)]
    sample_hlds = random.sample(bond_hlds, k=min(100, len(bond_hlds)))
    for h in sample_hlds:
        bt = get_bond_template(h['AST_CD'])
        rating = bt[2] if bt else 'AA+'  # sub_type as proxy
        rating_map = {'CGB': 'AAA', 'POLICY': 'AAA', 'MTN': 'AA+',
                      'ENTERPRISE': 'AA', 'NCD': 'AA+', 'CB': 'AA'}
        rating_val = rating_map.get(rating, 'AA')
        exposure = h.get('MKT_VAL', random.uniform(1e6, 1e8))
        duration = round(random.uniform(0.5, 8), 2)
        el_amt = round(exposure * random.uniform(0.0001, 0.005), 2)
        var_99 = round(exposure * duration * 0.02, 2)
        limit_flag = 'BREACH' if var_99 > exposure * 0.1 else (
            'WARN' if var_99 > exposure * 0.05 else 'NORMAL')
        docs.append({
            'PORT_ID': h['PORT_ID'], 'AST_CD': h['AST_CD'], 'BIZ_DT': BIZ_DT,
            'EXPOSURE': round(exposure, 2), 'RATING': rating_val,
            'DURATION': duration, 'EL_AMT': el_amt,
            'VAR_99': var_99, 'LIMIT_FLAG': limit_flag,
        })
    return docs


def build_crdt_agme_info():
    """授信协议（20 条）"""
    docs = []
    for ct in CNTP_TEMPLATES:
        cntp_id, cntp_nm, cntp_type = ct
        agme_type = 'INTERBANK' if cntp_type == 'BANK' else random.choice(['NAFMII', 'ISDA'])
        limit_amt = round(random.uniform(1e8, 5e9), 2)
        used = round(limit_amt * random.uniform(0.2, 0.8), 2)
        remain = round(limit_amt - used, 2)
        eff_dt = '20240101'
        exp_dt = '20251231'
        risk_lvl = 'LOW' if used / limit_amt < 0.5 else ('MID' if used / limit_amt < 0.8 else 'HIGH')
        docs.append({
            'AGME_NO': f'AGME{cntp_id[-5:]}',
            'CNTP_ID': cntp_id, 'AGME_TYPE': agme_type,
            'EFF_DT': eff_dt, 'EXP_DT': exp_dt,
            'LIMIT_AMT': limit_amt, 'USED_AMT': used, 'REMAIN_AMT': remain,
            'RISK_LVL': risk_lvl, 'BIZ_DT': BIZ_DT,
        })
    return docs


def build_crdt_rela():
    """主体关联关系（30 条）"""
    rel_types = ['CMRC_PEER', 'POLICY_PEER', 'UNDERWRITER', 'BUSINESS', 'PARENT', 'SUBSIDIARY']
    docs = []
    # 银行间互相 peer
    bank_isrs = ISR_IDS[5:20]
    for i in range(15):
        src = bank_isrs[i % len(bank_isrs)]
        tgt = bank_isrs[(i + 1) % len(bank_isrs)]
        docs.append({
            'SRC_ISR_ID': src, 'TGT_ISR_ID': tgt,
            'REL_TYPE': 'CMRC_PEER', 'SHARE_RATIO': 0.0,
            'REMARK': '商业银行同业关系', 'BIZ_DT': BIZ_DT,
        })
    # 企业与银行关系
    corp_isrs = ISR_IDS[25:40]
    for i in range(10):
        src = corp_isrs[i % len(corp_isrs)]
        tgt = random.choice(bank_isrs)
        docs.append({
            'SRC_ISR_ID': src, 'TGT_ISR_ID': tgt,
            'REL_TYPE': random.choice(['UNDERWRITER', 'BUSINESS']),
            'SHARE_RATIO': 0.0,
            'REMARK': '业务合作关系', 'BIZ_DT': BIZ_DT,
        })
    # 集团关系
    for i in range(5):
        src = ISR_IDS[25 + i]
        tgt = ISR_IDS[30 + i] if 30 + i < len(ISR_IDS) else ISR_IDS[25]
        ratio = round(random.uniform(0.3, 1.0), 4)
        docs.append({
            'SRC_ISR_ID': src, 'TGT_ISR_ID': tgt,
            'REL_TYPE': random.choice(['PARENT', 'SUBSIDIARY']),
            'SHARE_RATIO': ratio,
            'REMARK': f'持股{ratio*100:.1f}%', 'BIZ_DT': BIZ_DT,
        })
    return docs


# ============ MAIN ============

def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    def upsert(coll_name, docs):
        coll = db[coll_name]
        old_cnt = coll.count_documents({})
        coll.delete_many({})
        if docs:
            coll.insert_many(docs)
        print(f'[B5] {coll_name:<36}: 清空 {old_cnt:>5} -> 写入 {len(docs):>5}')

    # 行情域 - 债券
    upsert('dwd_mkt_bond', build_mkt_bond())
    upsert('dwd_mkt_bond_market', build_mkt_bond_market())
    upsert('dwd_mkt_bond_duration', build_mkt_bond_duration())
    upsert('dwd_mkt_bond_ecl', build_mkt_bond_ecl())
    upsert('dwd_mkt_bond_creditrating', build_mkt_bond_creditrating())
    upsert('dwd_mkt_bond_amount', build_mkt_bond_amount())

    # 行情域 - 股票
    upsert('dwd_mkt_stock', build_mkt_stock())
    upsert('dwd_mkt_stock_yield', build_mkt_stock_yield())

    # 行情域 - 指数
    upsert('dwd_mkt_index', build_mkt_index())
    upsert('dwd_mkt_index_quote', build_mkt_index_quote())
    upsert('dwd_mkt_index_member', build_mkt_index_member())

    # 行情域 - 基金
    upsert('dwd_mkt_fund', build_mkt_fund())
    upsert('dwd_mkt_fund_market', build_mkt_fund_market())
    upsert('dwd_mkt_fund_derive', build_mkt_fund_derive())
    upsert('dwd_mkt_fund_allocation', build_mkt_fund_allocation())
    upsert('dwd_mkt_fund_structure', build_mkt_fund_structure())
    upsert('dwd_mkt_fund_suspension', build_mkt_fund_suspension())

    # 行情域 - 曲线/利率/汇率/日历
    upsert('dwd_mkt_curve', build_mkt_curve())
    upsert('dwd_mkt_curve_quote', build_mkt_curve_quote())
    upsert('dwd_mkt_rate', build_mkt_rate())
    upsert('dwd_mkt_rate_quote', build_mkt_rate_quote())
    upsert('dwd_mkt_exrate', build_mkt_exrate())
    upsert('dwd_mkt_calendar', build_mkt_calendar())
    upsert('dwd_mkt_date', build_mkt_date())
    upsert('dwd_mkt_rating', build_mkt_rating())

    # 风险域
    upsert('dwd_rsk_sentiment', build_rsk_sentiment())
    upsert('dwd_rsk_credit', build_rsk_credit())
    upsert('dwd_rsk_credit_position', build_rsk_credit_position())
    upsert('dwd_crdt_agme_info', build_crdt_agme_info())
    upsert('dwd_crdt_main_rela_rela_info', build_crdt_rela())

    # 抽样
    print('\n--- 数据抽样 ---')
    s = db.dwd_mkt_bond.find_one({'AST_CD': BONDS[0]}, {'_id': 0})
    print(f'dwd_mkt_bond: {s}')
    s = db.dwd_mkt_stock_yield.find_one({'AST_CD': STOCKS[0]}, {'_id': 0})
    print(f'dwd_mkt_stock_yield: {s}')
    s = db.dwd_mkt_rate_quote.find_one({'RATE_CD': 'DR007'}, {'_id': 0})
    print(f'dwd_mkt_rate_quote: {s}')
    s = db.dwd_rsk_sentiment.find_one({'SENT_TYPE': 'NEGATIVE'}, {'_id': 0})
    print(f'dwd_rsk_sentiment: {s}')
    s = db.dwd_crdt_agme_info.find_one({}, {'_id': 0})
    print(f'dwd_crdt_agme_info: {s}')

    print('\n[B5] ✅ 完成')
    client.close()


if __name__ == '__main__':
    main()
