"""
ZY 数据真实化 - 批次 2：发行人/产品/客户/销售域主表

目标表：
- dwd_isr_institution / dwd_isr_institution_finance / dwd_isr_trd_cntp
- dwd_ptl_info / tag_ptl_info / dwd_ptl_acc / dwd_ptl_acct_bal
- dwd_ptl_managers / dwd_ptl_fee / dwd_ptl_open_plan / dwd_ptl_asset_config_info
- dwd_ptl_holder_summary / dwd_ptl_ast_hld / dwd_ptl_cedetail / dwd_cash_acc
- dwd_cust_info / dwd_cust_make_pstn_info / dwd_cust_trans_acct_info
- dwd_seller_info
"""
from __future__ import annotations
import sys
import random
from pathlib import Path
from datetime import datetime, timedelta
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).parent))

from zy_data_pools import (
    BIZ_DT, AST_CDS, PORT_IDS, ISR_IDS, CUSTOMER_IDS, SELLER_IDS, CNTP_IDS,
    BOND_TEMPLATES, STOCK_TEMPLATES, FUND_TEMPLATES,
    ISR_TEMPLATES, PORT_TEMPLATES, CNTP_TEMPLATES,
    SURNAMES, GIVEN_NAMES_M, GIVEN_NAMES_F, BANK_POOL,
    SELLER_BRANCHES, INST_TYPES, INST_PREFIXES,
    CHANNEL_DIST, RISK_LVL_DIST, RATING_AGENCIES,
)
from zy_data_helpers import (
    parse_dt, fmt_dt, gen_id_no, gen_credit_code, gen_phone, gen_email,
    gen_bank_acct, shift_trade_dates,
)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"
random.seed(20250324)

# ============= 主体域 =============
def build_isr_institution():
    """60 个真实发行人主体"""
    docs = []
    province_pool = ['北京', '上海', '深圳', '广州', '杭州', '南京', '苏州', '宁波', '天津',
                     '成都', '重庆', '武汉', '长沙', '青岛', '厦门', '福州', '济南', '西安']
    industry_map = {
        'SOVEREIGN': '财政', 'POLICY_BANK': '银行', 'COMMERCIAL_BANK': '银行',
        'CORPORATE': '工业', 'SECURITIES': '非银金融',
    }
    for isr_id, full_nm, short_nm, isr_type, credit_rating, industry, prov, list_flag, reg_cap, est_dt in ISR_TEMPLATES:
        docs.append({
            'ISR_ID': isr_id,
            'ISR_NM': full_nm,
            'ISR_SHORT_NM': short_nm,
            'ISR_TYPE': isr_type,
            'CREDIT_CD': gen_credit_code(seed=hash(isr_id) & 0xFFFFFFFF),
            'INDUSTRY_CD': industry,
            'INDUSTRY_NM': industry,
            'REG_PROV': prov,
            'LIST_FLAG': list_flag,
            'REG_CAP_AMT': reg_cap,
            'EST_DT': est_dt,
            'BIZ_DT': BIZ_DT,
        })
    return docs


def build_isr_finance():
    """每发行人 2 个报告期（年报 + 半年报）"""
    docs = []
    rpt_dts = ['20231231', '20240630']
    for isr_id, _full, _short, isr_type, _rating, _ind, _prov, _list, reg_cap, _est in ISR_TEMPLATES:
        if isr_type == 'SOVEREIGN':
            continue   # 部委不出财报
        # 总资产 ≈ 注册资本 × (5 ~ 30)
        for rpt_dt in rpt_dts:
            mult = random.uniform(5, 30) if isr_type in ('COMMERCIAL_BANK', 'POLICY_BANK') else random.uniform(2, 10)
            tot_ast = reg_cap * mult
            tot_lia = tot_ast * random.uniform(0.65, 0.92)
            equity = tot_ast - tot_lia
            revenue = tot_ast * random.uniform(0.04, 0.18)
            net_prft = revenue * random.uniform(0.10, 0.32)
            roe = round(net_prft / max(equity, 1e6), 6)
            roa = round(net_prft / max(tot_ast, 1e6), 6)
            debt_ratio = round(tot_lia / max(tot_ast, 1e6), 6)
            docs.append({
                'ISR_ID': isr_id,
                'RPT_DT': rpt_dt,
                'RPT_TYPE': 'A' if rpt_dt.endswith('1231') else 'H',
                'TOT_AST': round(tot_ast, 2),
                'TOT_LIA': round(tot_lia, 2),
                'EQUITY': round(equity, 2),
                'REVENUE': round(revenue, 2),
                'NET_PRFT': round(net_prft, 2),
                'ROE': roe,
                'ROA': roa,
                'DEBT_RATIO': debt_ratio,
            })
    return docs


def build_isr_trd_cntp():
    """20 个交易对手"""
    docs = []
    for cntp_id, full_nm, cntp_type in CNTP_TEMPLATES:
        bank = random.choice(BANK_POOL)
        docs.append({
            'CNTP_ID': cntp_id,
            'CNTP_NM': full_nm,
            'CNTP_TYPE': cntp_type,
            'CREDIT_CD': gen_credit_code(seed=hash(cntp_id) & 0xFFFFFFFF),
            'CONTACT_PHONE': gen_phone(seed=hash(cntp_id)),
            'SETT_BANK': bank,
            'SETT_ACCT': gen_bank_acct(seed=hash(cntp_id)),
            'STATUS': 'ACTIVE',
            'BIZ_DT': BIZ_DT,
        })
    return docs


# ============= 产品域 =============
def build_ptl_info():
    """30 个组合"""
    docs = []
    custody_banks = ['中国工商银行', '中国建设银行', '招商银行', '中国银行', '交通银行',
                     '中信银行', '兴业银行', '浦发银行']
    for port_id, port_nm, port_type, risk_lvl, benchmark, mgr_inst, aum_yi in PORT_TEMPLATES:
        # 成立日 2010~2024
        estab_year = random.randint(2010, 2024)
        estab_dt = f'{estab_year}{random.randint(1, 12):02d}{random.randint(1, 28):02d}'
        # 净值
        if port_type == 'MMF':
            shr_nav = 1.0
        elif port_type == 'BOND':
            shr_nav = round(random.uniform(1.05, 1.45), 4)
        elif port_type == 'EQUITY':
            shr_nav = round(random.uniform(0.85, 3.20), 4)
        else:
            shr_nav = round(random.uniform(0.95, 2.10), 4)
        # 短称
        short_nm = port_nm.replace('股份有限公司', '').replace('混合', '').replace('股票', '')[:8]
        docs.append({
            'PORT_ID': port_id,
            'PORT_NM': port_nm,
            'PORT_SHORT_NM': short_nm,
            'PORT_TYPE': port_type,
            'RISK_LVL': risk_lvl,
            'ESTAB_DT': estab_dt,
            'CCY': 'CNY',
            'BENCHMARK': benchmark,
            'SHR_NAV': shr_nav,
            'AUM': round(aum_yi * 1e8, 2),
            'MGR_INST': mgr_inst,
            'CUSTODY_BANK': random.choice(custody_banks),
            'STATUS': 'ACTIVE',
        })
    return docs


def build_tag_ptl_info():
    """每组合 3-5 个标签"""
    docs = []
    tag_pool = {
        '投资风格': ['价值投资', '成长投资', '量化对冲', '指数增强', '主动管理', '被动跟踪'],
        '主题': ['ESG', '低碳', '科技创新', '消费升级', '高股息', '红利策略', '医药健康'],
        '运作方式': ['开放式', '定期开放', '封闭式', '分级'],
        '风险等级': ['低风险', '中低风险', '中风险', '中高风险', '高风险'],
    }
    for port_id, _nm, port_type, risk_lvl, _bm, _mgr, _aum in PORT_TEMPLATES:
        # 风险等级映射
        risk_tag = {'R1': '低风险', 'R2': '中低风险', 'R3': '中风险', 'R4': '中高风险', 'R5': '高风险'}.get(risk_lvl, '中风险')
        docs.append({'PORT_ID': port_id, 'TAG_GROUP': '风险等级', 'TAG_VAL': risk_tag})
        # 运作方式
        op_tag = '开放式' if port_type in ('MMF', 'EQUITY') else random.choice(['开放式', '定期开放', '封闭式'])
        docs.append({'PORT_ID': port_id, 'TAG_GROUP': '运作方式', 'TAG_VAL': op_tag})
        # 投资风格
        docs.append({'PORT_ID': port_id, 'TAG_GROUP': '投资风格', 'TAG_VAL': random.choice(tag_pool['投资风格'])})
        # 主题
        if random.random() > 0.5:
            docs.append({'PORT_ID': port_id, 'TAG_GROUP': '主题', 'TAG_VAL': random.choice(tag_pool['主题'])})
    return docs


def build_ptl_acc():
    """每组合 2 个账户（资金 + 证券）"""
    docs = []
    for port_id, port_nm, _t, _r, _bm, _mgr, _aum in PORT_TEMPLATES:
        bank = random.choice(BANK_POOL)
        docs.append({
            'PORT_ID': port_id,
            'ACCT_NO': gen_bank_acct(seed=hash(port_id + 'CASH')),
            'ACCT_TYPE': 'CASH',
            'ACCT_NM': f'{port_nm}-资金账户',
            'BANK_BR': f'{bank}总行营业部',
            'CCY': 'CNY',
        })
        docs.append({
            'PORT_ID': port_id,
            'ACCT_NO': '0899' + ''.join(str(random.randint(0, 9)) for _ in range(15)),
            'ACCT_TYPE': 'BOND',
            'ACCT_NM': f'{port_nm}-债券账户',
            'BANK_BR': '中央国债登记结算公司',
            'CCY': 'CNY',
        })
    return docs


def build_ptl_acct_bal():
    """每组合 3 类余额"""
    docs = []
    for port_id, _nm, _t, _r, _bm, _mgr, aum_yi in PORT_TEMPLATES:
        cash_amt = aum_yi * 1e8 * random.uniform(0.02, 0.08)
        avail = cash_amt * random.uniform(0.85, 0.99)
        frozen = cash_amt - avail
        docs.append({'PORT_ID': port_id, 'BIZ_DT': BIZ_DT, 'BAL_TYPE': 'TOTAL', 'AMT': round(cash_amt, 2), 'CCY': 'CNY'})
        docs.append({'PORT_ID': port_id, 'BIZ_DT': BIZ_DT, 'BAL_TYPE': 'AVAIL', 'AMT': round(avail, 2), 'CCY': 'CNY'})
        docs.append({'PORT_ID': port_id, 'BIZ_DT': BIZ_DT, 'BAL_TYPE': 'FROZEN', 'AMT': round(frozen, 2), 'CCY': 'CNY'})
    return docs


def build_ptl_managers():
    """每组合 1-2 个经理"""
    docs = []
    used = set()
    for port_id, _nm, _t, _r, _bm, _mgr, _aum in PORT_TEMPLATES:
        n = random.choice([1, 1, 2])  # 多数 1 人，少数 2 人
        for i in range(n):
            mgr_id = f'MGR{random.randint(10000, 99999)}'
            while mgr_id in used:
                mgr_id = f'MGR{random.randint(10000, 99999)}'
            used.add(mgr_id)
            gender = random.choice(['M', 'F'])
            sn = random.choice(SURNAMES)
            given = random.choice(GIVEN_NAMES_M if gender == 'M' else GIVEN_NAMES_F)
            start_year = random.randint(2015, 2023)
            docs.append({
                'PORT_ID': port_id,
                'MANAGER_ID': mgr_id,
                'MANAGER_NM': sn + given,
                'ROLE': 'LEAD' if i == 0 else 'CO',
                'START_DT': f'{start_year}{random.randint(1, 12):02d}{random.randint(1, 28):02d}',
                'END_DT': None,
            })
    return docs


def build_ptl_fee():
    """每组合 4 类费率"""
    docs = []
    fee_rates = {
        'MMF':    {'MGT': 0.0025, 'CUSTODY': 0.0008, 'SALES': 0.0005, 'PERF': 0.0},
        'BOND':   {'MGT': 0.0050, 'CUSTODY': 0.0012, 'SALES': 0.0010, 'PERF': 0.0},
        'MIXED':  {'MGT': 0.0120, 'CUSTODY': 0.0025, 'SALES': 0.0040, 'PERF': 0.0},
        'EQUITY': {'MGT': 0.0150, 'CUSTODY': 0.0025, 'SALES': 0.0050, 'PERF': 0.10},
        'FOF':    {'MGT': 0.0080, 'CUSTODY': 0.0020, 'SALES': 0.0030, 'PERF': 0.0},
        'INDEX':  {'MGT': 0.0050, 'CUSTODY': 0.0010, 'SALES': 0.0020, 'PERF': 0.0},
    }
    for port_id, _nm, port_type, _r, _bm, _mgr, _aum in PORT_TEMPLATES:
        rates = fee_rates.get(port_type, fee_rates['MIXED'])
        for fee_type, base_rate in rates.items():
            jitter = base_rate * random.uniform(0.85, 1.15)
            docs.append({
                'PORT_ID': port_id,
                'FEE_TYPE': fee_type,
                'FEE_RATE': round(jitter, 6),
                'FEE_BASE': '净资产' if fee_type in ('MGT', 'CUSTODY') else '认申购金额',
                'EFF_DT': '20200101',
                'EXP_DT': '20991231',
            })
    return docs


def build_ptl_open_plan():
    """每组合 2-4 个开放日"""
    docs = []
    base = parse_dt('20250101')
    for port_id, _nm, port_type, _r, _bm, _mgr, _aum in PORT_TEMPLATES:
        if port_type == 'MMF':  # 货基每日开放，仅生成 4 个代表
            for i in range(4):
                d = base + timedelta(days=20 * i)
                docs.append({
                    'PORT_ID': port_id, 'OPEN_DT': fmt_dt(d), 'OPEN_TYPE': 'BOTH',
                    'CLOSE_DT': fmt_dt(d + timedelta(days=1)),
                    'QUOTA_AMT': round(random.uniform(1e8, 5e9), 2),
                })
        else:
            n = random.randint(2, 4)
            for i in range(n):
                d = base + timedelta(days=random.randint(0, 80) + 30 * i)
                docs.append({
                    'PORT_ID': port_id, 'OPEN_DT': fmt_dt(d),
                    'OPEN_TYPE': random.choice(['SUB', 'RDM', 'BOTH']),
                    'CLOSE_DT': fmt_dt(d + timedelta(days=random.randint(1, 5))),
                    'QUOTA_AMT': round(random.uniform(5e7, 2e9), 2),
                })
    return docs


def build_ptl_asset_config():
    """每组合按类型配置"""
    docs = []
    config_map = {
        'MMF':    [('CASH', 0.95, 0.85, 1.0), ('BOND', 0.05, 0.0, 0.20)],
        'BOND':   [('BOND', 0.85, 0.70, 0.95), ('CASH', 0.10, 0.05, 0.30), ('STOCK', 0.05, 0.0, 0.20)],
        'MIXED':  [('STOCK', 0.55, 0.40, 0.75), ('BOND', 0.35, 0.20, 0.50), ('CASH', 0.10, 0.05, 0.30)],
        'EQUITY': [('STOCK', 0.85, 0.80, 0.95), ('BOND', 0.05, 0.0, 0.20), ('CASH', 0.10, 0.05, 0.20)],
        'FOF':    [('FUND', 0.85, 0.80, 0.95), ('CASH', 0.15, 0.05, 0.20)],
        'INDEX':  [('STOCK', 0.95, 0.90, 1.0), ('CASH', 0.05, 0.0, 0.10)],
    }
    for port_id, _nm, port_type, _r, _bm, _mgr, _aum in PORT_TEMPLATES:
        for ast_class, tgt, lo, hi in config_map.get(port_type, config_map['MIXED']):
            docs.append({
                'PORT_ID': port_id,
                'AST_CLASS': ast_class,
                'TGT_RATIO': tgt,
                'MIN_RATIO': lo,
                'MAX_RATIO': hi,
            })
    return docs


def build_ptl_holder_summary():
    """每组合 2-3 类持有人"""
    docs = []
    for port_id, _nm, port_type, _r, _bm, _mgr, aum_yi in PORT_TEMPLATES:
        tot_amt = aum_yi * 1e8
        # 不同类型分布
        if port_type == 'MMF':
            ratios = [('IND', 0.35), ('INST', 0.60), ('INTERNAL', 0.05)]
        elif port_type in ('EQUITY', 'MIXED'):
            ratios = [('IND', 0.65), ('INST', 0.30), ('INTERNAL', 0.05)]
        else:
            ratios = [('IND', 0.45), ('INST', 0.50), ('INTERNAL', 0.05)]
        for holder_type, ratio in ratios:
            amt = tot_amt * ratio
            cnt = int(amt / random.uniform(20000, 200000)) if holder_type == 'IND' else random.randint(2, 30)
            docs.append({
                'PORT_ID': port_id,
                'BIZ_DT': BIZ_DT,
                'HOLDER_TYPE': holder_type,
                'HOLDER_CNT': cnt,
                'TOT_SHR': round(amt / random.uniform(0.95, 1.50), 2),
                'TOT_AMT': round(amt, 2),
                'RATIO': ratio,
            })
    return docs


def build_ptl_ast_hld():
    """每组合 5-15 个持仓（按类型选择资产）"""
    docs = []
    bond_ast = [t[0] for t in BOND_TEMPLATES]
    stock_ast = [t[0] for t in STOCK_TEMPLATES]
    fund_ast = [t[0] for t in FUND_TEMPLATES]

    for port_id, _nm, port_type, _r, _bm, _mgr, aum_yi in PORT_TEMPLATES:
        tot_aum = aum_yi * 1e8
        if port_type == 'MMF':
            short_bonds = [a for a in bond_ast if 'NCD' in a or a.startswith('019') or a.startswith('220003') or '188888' in a]
            ast_pool = random.sample(bond_ast, k=10) + random.sample(short_bonds, k=min(3, len(short_bonds)))
        elif port_type == 'BOND':
            ast_pool = random.sample(bond_ast, k=12)
        elif port_type == 'EQUITY':
            ast_pool = random.sample(stock_ast, k=15)
        elif port_type == 'FOF':
            ast_pool = random.sample(fund_ast, k=8)
        elif port_type == 'INDEX':
            ast_pool = random.sample(stock_ast, k=18)
        else:  # MIXED
            ast_pool = random.sample(stock_ast, k=8) + random.sample(bond_ast, k=5)
        # 去重
        ast_pool = list(dict.fromkeys(ast_pool))

        # 权重归一
        weights = [random.uniform(0.5, 2.0) for _ in ast_pool]
        ws = sum(weights)
        weights = [w / ws for w in weights]

        port_acct = '0899' + ''.join(str(random.randint(0, 9)) for _ in range(15))
        for ast_cd, w in zip(ast_pool, weights):
            mkt_val = round(tot_aum * w * random.uniform(0.95, 1.05), 2)
            cost_amt = round(mkt_val * random.uniform(0.92, 1.05), 2)
            # 价格区间
            if ast_cd in stock_ast:
                mkt_prc = round(random.uniform(8.0, 280.0), 2)
                qty = round(mkt_val / mkt_prc, 0)
                aci = 0.0
            elif ast_cd in bond_ast:
                mkt_prc = round(random.uniform(96.0, 105.0), 4)
                qty = round(mkt_val / mkt_prc * 100.0, 0)
                aci = round(mkt_val * 0.005, 2)
            else:
                mkt_prc = round(random.uniform(0.9, 4.0), 4)
                qty = round(mkt_val / mkt_prc, 0)
                aci = 0.0
            cost_prc = round(cost_amt / max(qty, 1) * (100 if ast_cd in bond_ast else 1), 4)
            docs.append({
                'PORT_ID': port_id,
                'AST_CD': ast_cd,
                'BIZ_DT': BIZ_DT,
                'HLD_QTY': qty,
                'COST_PRC': cost_prc,
                'MKT_PRC': mkt_prc,
                'COST_AMT': cost_amt,
                'MKT_VAL': mkt_val,
                'ACI_AMT': aci,
                'WEIGHT': round(w, 6),
                'ACCT_NO': port_acct,
            })
    return docs


def build_ptl_cedetail():
    """每组合 5-12 条申赎记录（最近 60 天）"""
    docs = []
    end = parse_dt('20250324')
    for port_id, port_nm, _t, _r, _bm, _mgr, _aum in PORT_TEMPLATES:
        n = random.randint(5, 12)
        for _ in range(n):
            d = end - timedelta(days=random.randint(1, 60))
            ce_type = random.choices(['SUB', 'RDM', 'DIV'], weights=[5, 4, 1])[0]
            amt = round(random.uniform(1e5, 5e7), 2)
            summary = {'SUB': '客户申购', 'RDM': '客户赎回', 'DIV': '现金分红'}[ce_type]
            docs.append({
                'PORT_ID': port_id,
                'TRADE_DT': fmt_dt(d),
                'CE_TYPE': ce_type,
                'AMT': amt,
                'CCY': 'CNY',
                'SUMMARY': f'{port_nm}-{summary}',
            })
    return docs


def build_cash_acc():
    """每组合 1 个现金账户"""
    docs = []
    for port_id, _nm, _t, _r, _bm, _mgr, aum_yi in PORT_TEMPLATES:
        bal = round(aum_yi * 1e8 * random.uniform(0.03, 0.08), 2)
        avail = round(bal * random.uniform(0.92, 0.99), 2)
        frozen = round(bal - avail, 2)
        bank = random.choice(BANK_POOL)
        docs.append({
            'PORT_ID': port_id,
            'ACCT_NO': gen_bank_acct(seed=hash(port_id + 'CASH2')),
            'BIZ_DT': BIZ_DT,
            'CCY': 'CNY',
            'BAL': bal,
            'AVAIL_BAL': avail,
            'FROZEN_BAL': frozen,
            'BANK': bank,
            'RATE': round(random.uniform(0.0030, 0.0145), 6),
        })
    return docs


# ============= 客户域 =============
def build_cust_info():
    """200 客户：150 个人 + 50 机构"""
    docs = []
    rng = random.Random(20250324)
    # 150 个人
    for i in range(150):
        cust_id = CUSTOMER_IDS[i]
        gender = rng.choice(['M', 'F'])
        sn = rng.choice(SURNAMES)
        given = rng.choice(GIVEN_NAMES_M if gender == 'M' else GIVEN_NAMES_F)
        # 生日 1950~2000
        birth_year = rng.randint(1950, 2000)
        birth_dt = f'{birth_year}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}'
        # 开户日
        open_year = rng.randint(2015, 2024)
        open_dt = f'{open_year}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}'
        risk_lvl = rng.choice(RISK_LVL_DIST)
        channel = rng.choice(CHANNEL_DIST)
        seller_id = rng.choice(SELLER_IDS) if channel != 'DIRECT' else None
        addr_city = rng.choice(['北京市朝阳区', '上海市浦东新区', '深圳市福田区', '广州市天河区',
                                '杭州市西湖区', '南京市鼓楼区', '成都市武侯区', '武汉市江汉区'])
        docs.append({
            'CUSTOMER_ID': cust_id,
            'CUST_NM': sn + given,
            'CUST_TYPE': 'IND',
            'GENDER': gender,
            'BIRTH_DT': birth_dt,
            'ID_TYPE': 'IDCARD',
            'ID_NO': gen_id_no(birth_dt, gender, seed=hash(cust_id) & 0xFFFFFFFF),
            'PHONE': gen_phone(seed=hash(cust_id)),
            'EMAIL': gen_email(seed=hash(cust_id)),
            'ADDR': f'{addr_city}{rng.randint(1, 200)}号{rng.randint(1, 50)}室',
            'RISK_LVL': risk_lvl,
            'OPEN_DT': open_dt,
            'CHANNEL': channel,
            'SELLER_ID': seller_id,
            'BIZ_DT': BIZ_DT,
        })
    # 50 机构
    for i in range(150, 200):
        cust_id = CUSTOMER_IDS[i]
        prefix = rng.choice(INST_PREFIXES)
        suffix = rng.choice(INST_TYPES)
        inst_nm = f'{prefix}{suffix}'
        open_year = rng.randint(2010, 2023)
        open_dt = f'{open_year}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}'
        risk_lvl = rng.choice(['R3', 'R4', 'R4', 'R5'])
        addr_city = rng.choice(['北京市', '上海市', '深圳市', '广州市', '杭州市', '南京市'])
        docs.append({
            'CUSTOMER_ID': cust_id,
            'CUST_NM': inst_nm,
            'CUST_TYPE': 'INST',
            'GENDER': None,
            'BIRTH_DT': None,
            'ID_TYPE': 'CREDIT',
            'ID_NO': gen_credit_code(seed=hash(cust_id) & 0xFFFFFFFF),
            'PHONE': gen_phone(seed=hash(cust_id)),
            'EMAIL': gen_email(seed=hash(cust_id)),
            'ADDR': f'{addr_city}{prefix}总部',
            'RISK_LVL': risk_lvl,
            'OPEN_DT': open_dt,
            'CHANNEL': rng.choice(['DIRECT', 'BANK', 'BROKER']),
            'SELLER_ID': rng.choice(SELLER_IDS),
            'BIZ_DT': BIZ_DT,
        })
    return docs


def build_cust_make_pstn(ptl_info_docs):
    """客户持仓 - 每客户 1-4 组合，按净值反算"""
    docs = []
    nav_map = {p['PORT_ID']: p['SHR_NAV'] for p in ptl_info_docs}
    rng = random.Random(20250325)
    for cust_id in CUSTOMER_IDS:
        n_ports = rng.choice([1, 1, 2, 2, 3, 4])
        ports_chosen = rng.sample(PORT_IDS, k=n_ports)
        for port_id in ports_chosen:
            shr_nav = nav_map.get(port_id, 1.0)
            hld_amt = round(rng.uniform(1000, 1_000_000), 2)
            hld_shr = round(hld_amt / max(shr_nav, 0.5), 2)
            cost_amt = round(hld_amt * rng.uniform(0.92, 1.06), 2)
            unreal_pnl = round(hld_amt - cost_amt, 2)
            avail_shr = round(hld_shr * rng.uniform(0.95, 1.0), 2)
            frozen_shr = round(hld_shr - avail_shr, 2)
            # 首次申购日
            first_buy = parse_dt(BIZ_DT) - timedelta(days=rng.randint(30, 1500))
            docs.append({
                'CUSTOMER_ID': cust_id,
                'PORT_ID': port_id,
                'BIZ_DT': BIZ_DT,
                'HLD_SHR': hld_shr,
                'HLD_AMT': hld_amt,
                'COST_AMT': cost_amt,
                'UNREAL_PNL': unreal_pnl,
                'AVAIL_SHR': avail_shr,
                'FROZEN_SHR': frozen_shr,
                'FIRST_BUY_DT': fmt_dt(first_buy),
            })
    return docs


def build_cust_trans_acct():
    """客户交易账户：每客户 1-2 个"""
    docs = []
    rng = random.Random(20250326)
    for cust_id in CUSTOMER_IDS:
        n = rng.choice([1, 1, 2])
        for i in range(n):
            bank = rng.choice(BANK_POOL)
            acct_type = rng.choice(['BANK', 'CASH'])
            open_year = rng.randint(2015, 2024)
            open_dt = f'{open_year}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}'
            docs.append({
                'CUSTOMER_ID': cust_id,
                'ACCT_NO': gen_bank_acct(seed=hash(cust_id + str(i))),
                'ACCT_TYPE': acct_type,
                'BANK': bank,
                'BR_NM': f'{bank}{rng.choice(["北京", "上海", "深圳", "广州"])}分行',
                'CCY': 'CNY',
                'OPEN_DT': open_dt,
                'STATUS': 'ACTIVE',
                'BIZ_DT': BIZ_DT,
            })
    return docs


# ============= 销售域 =============
def build_seller_info():
    """30 个销售人员"""
    docs = []
    for i, branch in enumerate(SELLER_BRANCHES[:30]):
        seller_id = SELLER_IDS[i]
        gender = random.choice(['M', 'F'])
        sn = random.choice(SURNAMES)
        given = random.choice(GIVEN_NAMES_M if gender == 'M' else GIVEN_NAMES_F)
        # 渠道类型
        if '银行' in branch or '支行' in branch:
            channel_type, seller_type = 'BANK', 'EXTERNAL'
        elif '证券' in branch or '分公司' in branch:
            channel_type, seller_type = 'BROKER', 'EXTERNAL'
        elif '直销' in branch:
            channel_type, seller_type = 'DIRECT', 'INTERNAL'
        else:
            channel_type, seller_type = 'BANK', 'EXTERNAL'
        entry_year = random.randint(2015, 2023)
        entry_dt = f'{entry_year}{random.randint(1, 12):02d}{random.randint(1, 28):02d}'
        docs.append({
            'SELLER_ID': seller_id,
            'SELLER_NM': sn + given,
            'SELLER_TYPE': seller_type,
            'CHANNEL_TYPE': channel_type,
            'ORG': branch,
            'CERT_NO': f'{random.randint(100000, 999999)}{random.randint(1000, 9999)}',
            'CERT_TYPE': '基金从业资格',
            'PHONE': gen_phone(seed=hash(seller_id)),
            'EMAIL': gen_email(seed=hash(seller_id)),
            'ENTRY_DT': entry_dt,
            'STATUS': 'ACTIVE',
            'BIZ_DT': BIZ_DT,
        })
    return docs


def main():
    print(f'[B2] 主体/产品/客户/销售域生成')
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[DB_NAME]

    ptl_info_docs = build_ptl_info()

    targets = [
        ('dwd_isr_institution',         build_isr_institution()),
        ('dwd_isr_institution_finance', build_isr_finance()),
        ('dwd_isr_trd_cntp',            build_isr_trd_cntp()),
        ('dwd_ptl_info',                ptl_info_docs),
        ('tag_ptl_info',                build_tag_ptl_info()),
        ('dwd_ptl_acc',                 build_ptl_acc()),
        ('dwd_ptl_acct_bal',            build_ptl_acct_bal()),
        ('dwd_ptl_managers',            build_ptl_managers()),
        ('dwd_ptl_fee',                 build_ptl_fee()),
        ('dwd_ptl_open_plan',           build_ptl_open_plan()),
        ('dwd_ptl_asset_config_info',   build_ptl_asset_config()),
        ('dwd_ptl_holder_summary',      build_ptl_holder_summary()),
        ('dwd_ptl_ast_hld',             build_ptl_ast_hld()),
        ('dwd_ptl_cedetail',            build_ptl_cedetail()),
        ('dwd_cash_acc',                build_cash_acc()),
        ('dwd_cust_info',               build_cust_info()),
        ('dwd_cust_make_pstn_info',     build_cust_make_pstn(ptl_info_docs)),
        ('dwd_cust_trans_acct_info',    build_cust_trans_acct()),
        ('dwd_seller_info',             build_seller_info()),
    ]

    for coll_name, docs in targets:
        coll = db[coll_name]
        deleted = coll.delete_many({}).deleted_count
        if docs:
            coll.insert_many(docs)
        print(f'[B2] {coll_name:32s}: 清空 {deleted:5d} -> 写入 {len(docs):5d}')

    print('\n[B2] 校验：')
    print(f"  dwd_isr_institution 样本: {db.dwd_isr_institution.find_one({'ISR_ID': 'ISR000006'}, {'_id': 0})}")
    print(f"  dwd_ptl_info  样本: {db.dwd_ptl_info.find_one({'PORT_ID': 'PORT001'}, {'_id': 0})}")
    print(f"  dwd_cust_info 样本: {db.dwd_cust_info.find_one({'CUST_TYPE': 'IND'}, {'_id': 0})}")

    print('\n[B2] ✅ 完成')


if __name__ == '__main__':
    main()
