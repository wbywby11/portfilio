"""
ZY 数据真实化 - 批次 3：资产派生表 + 估值/现金流

目标表：
- dwd_ast_pledge / dwd_ast_party / dwd_ast_exe_plan / dwd_ast_cf_plan
- dwd_ast_fund_manager / dwd_ast_bottom_raito / dwd_ast_fiveclass / dwd_ast_calc_rule
- dwd_val_detail / dwd_val_summary / dwd_val_bal / dwd_val_valtable
- dwd_val_voucher / dwd_val_notice / dwd_val_acc / dwd_val_rpt_bs / dwd_val_rpt_is / dwd_val_rpt_cf
"""
from __future__ import annotations
import sys
import random
from pathlib import Path
from datetime import datetime, timedelta
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).parent))

from zy_data_pools import (
    BIZ_DT, AST_CDS, PORT_IDS, ISR_IDS,
    BOND_TEMPLATES, STOCK_TEMPLATES, FUND_TEMPLATES, OTHER_AST_TEMPLATES,
    ISR_TEMPLATES, PORT_TEMPLATES, RATING_AGENCIES,
    SURNAMES, GIVEN_NAMES_M, GIVEN_NAMES_F, BANK_POOL,
    is_bond, is_stock, is_fund,
)
from zy_data_helpers import (
    parse_dt, fmt_dt, years_between, calc_aci,
)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"
random.seed(20250324)

BOND_AST = [t[0] for t in BOND_TEMPLATES]
STOCK_AST = [t[0] for t in STOCK_TEMPLATES]
FUND_AST = [t[0] for t in FUND_TEMPLATES]


# ============= 1) dwd_ast_pledge =============
def build_ast_pledge():
    """仅债券，30 条质押状态"""
    docs = []
    candidates = random.sample(BOND_AST, k=30)
    for ast_cd in candidates:
        flag = random.choices(['Y', 'N'], weights=[0.6, 0.4])[0]
        if flag == 'Y':
            ratio = round(random.uniform(0.40, 0.95), 4)
            std_bond = round(ratio * random.uniform(0.95, 1.0), 4)
            pledge_bond = random.choice([a for a in BOND_AST if a != ast_cd])
            note = f'质押融资，回购利率 {random.uniform(2.0, 3.5):.2f}%'
        else:
            ratio = 0.0
            std_bond = 0.0
            pledge_bond = None
            note = '未质押'
        docs.append({
            'AST_CD': ast_cd,
            'BIZ_DT': BIZ_DT,
            'PLEDGE_FLAG': flag,
            'PLEDGE_RATIO': ratio,
            'PLEDGE_STD_BOND': std_bond,
            'PLEDGE_BOND_CD': pledge_bond,
            'PLEDGE_NOTE': note,
        })
    return docs


# ============= 2) dwd_ast_party =============
def build_ast_party():
    """每债券 1-3 个关联方"""
    docs = []
    # 担保人/受托人池
    trustee_pool = ['中国建设银行股份有限公司', '中国工商银行股份有限公司', '中国银行股份有限公司',
                    '招商银行股份有限公司', '兴业银行股份有限公司']
    auditor_pool = ['普华永道中天会计师事务所', '安永华明会计师事务所', '德勤华永会计师事务所',
                    '毕马威华振会计师事务所', '立信会计师事务所']
    underwriter_pool = ['中信证券股份有限公司', '中金公司股份有限公司', '招商证券股份有限公司',
                        '海通证券股份有限公司', '国泰君安证券股份有限公司']

    party_seq = [0]
    def next_pid():
        party_seq[0] += 1
        return f'PARTY{party_seq[0]:05d}'

    for ast_cd, ast_nm, _sub, isr_idx, _c, _m, _amt, _mkt, _term, _ld in BOND_TEMPLATES:
        # 发行人
        isr = ISR_TEMPLATES[isr_idx]
        docs.append({
            'AST_CD': ast_cd, 'PARTY_ID': next_pid(), 'PARTY_NM': isr[1],
            'PARTY_ROLE': 'ISSUER', 'BIZ_DT': BIZ_DT,
        })
        # 受托人
        if random.random() > 0.3:
            docs.append({
                'AST_CD': ast_cd, 'PARTY_ID': next_pid(), 'PARTY_NM': random.choice(trustee_pool),
                'PARTY_ROLE': 'TRUSTEE', 'BIZ_DT': BIZ_DT,
            })
        # 主承销商
        if random.random() > 0.4:
            docs.append({
                'AST_CD': ast_cd, 'PARTY_ID': next_pid(), 'PARTY_NM': random.choice(underwriter_pool),
                'PARTY_ROLE': 'UNDERWRITER', 'BIZ_DT': BIZ_DT,
            })
    return docs


# ============= 3) dwd_ast_exe_plan =============
def build_ast_exe_plan():
    """可赎回/可回售的部分债券（约 12 条）"""
    docs = []
    callable_bonds = [t for t in BOND_TEMPLATES if t[2] in ('MTN', 'ENTERPRISE') and random.random() > 0.4][:12]
    for ast_cd, _nm, _sub, _isr, coupon, maturity, _amt, _mkt, _term, list_dt in callable_bonds:
        try:
            list_d = parse_dt(list_dt)
            mat_d = parse_dt(maturity)
            mid_d = list_d + (mat_d - list_d) / 2
            exe_dt = fmt_dt(mid_d)
        except Exception:
            exe_dt = '20280101'
        exe_type = random.choice(['CALL', 'PUT', 'EXTENSION'])
        prc = round(100.0 + (random.uniform(0, 5) if exe_type == 'CALL' else random.uniform(-2, 2)), 4)
        note = {
            'CALL': f'发行人可在 {exe_dt} 选择赎回',
            'PUT': f'投资者可在 {exe_dt} 选择回售',
            'EXTENSION': f'发行人可在 {exe_dt} 延长 1 年',
        }[exe_type]
        docs.append({
            'AST_CD': ast_cd, 'EXE_DT': exe_dt, 'EXE_TYPE': exe_type,
            'EXE_PRC': prc, 'NOTE': note,
        })
    return docs


# ============= 4) dwd_ast_cf_plan =============
def build_ast_cf_plan():
    """每债券完整现金流（仅债券）"""
    docs = []
    biz_d = parse_dt(BIZ_DT)
    for ast_cd, _nm, sub_type, _isr, coupon, maturity, _amt, _mkt, _term, list_dt in BOND_TEMPLATES:
        if coupon is None or coupon == 0:
            continue
        try:
            list_d = parse_dt(list_dt)
            mat_d = parse_dt(maturity)
        except Exception:
            continue
        # 付息频率
        freq = 1 if sub_type in ('CGB', 'POLICY') else random.choice([1, 2])
        years = max(1, int(round((mat_d - list_d).days / 365)))
        n_periods = years * freq
        period_days = 365 // freq

        for k in range(1, n_periods + 1):
            cf_d = list_d + timedelta(days=k * period_days)
            cf_amt_per_100 = coupon / freq * 100   # 利息（元/百元面值）
            if k == n_periods:
                cf_amt_per_100 += 100   # 加上本金
                cf_type = 'BOTH'
            else:
                cf_type = 'INTEREST'
            docs.append({
                'AST_CD': ast_cd,
                'CF_DT': fmt_dt(cf_d),
                'CF_TYPE': cf_type,
                'CF_AMT': round(cf_amt_per_100, 4),
                'CCY': 'CNY',
            })
    return docs


# ============= 5) dwd_ast_fund_manager =============
def build_ast_fund_manager():
    """基金经理：每基金 1-2 个"""
    docs = []
    used_mgr = set()

    def gen_mgr():
        while True:
            mid = f'FMGR{random.randint(10000, 99999)}'
            if mid not in used_mgr:
                used_mgr.add(mid)
                return mid

    for ast_cd, _nm, fund_type, mgr_inst, estab_dt, _aum in FUND_TEMPLATES:
        n = random.choice([1, 1, 2])
        for i in range(n):
            mid = gen_mgr()
            gender = random.choice(['M', 'F'])
            sn = random.choice(SURNAMES)
            given = random.choice(GIVEN_NAMES_M if gender == 'M' else GIVEN_NAMES_F)
            try:
                start_d = parse_dt(estab_dt) + timedelta(days=random.randint(0, 1000))
                start_dt = fmt_dt(start_d)
            except Exception:
                start_dt = '20180101'
            docs.append({
                'AST_CD': ast_cd,
                'MANAGER_ID': mid,
                'MANAGER_NM': sn + given,
                'START_DT': start_dt,
                'END_DT': None,
                'SHR_FLAG': 'Y' if n > 1 else 'N',
            })
    return docs


# ============= 6) dwd_ast_bottom_raito =============
def build_ast_bottom_raito():
    """基金穿透底层（每基金 5-10 个底层债券/股票，权重和 = 1）"""
    docs = []
    for ast_cd, fund_nm, fund_type, _mgr, _est, _aum in FUND_TEMPLATES:
        if fund_type == 'MMF':
            # 货币基金底层主要是短期债券
            btm_pool = [a for a in BOND_AST if any(x in a for x in ['NCD', '019', '188888', '220003'])]
            n = random.randint(5, 8)
        elif fund_type == 'ETF':
            # ETF 跟踪指数底层为股票
            btm_pool = STOCK_AST
            n = random.randint(8, 12)
        else:
            # 其他混合
            btm_pool = STOCK_AST + BOND_AST
            n = random.randint(5, 10)
        n = min(n, len(btm_pool))
        chosen = random.sample(btm_pool, k=n)
        weights = [random.uniform(0.5, 2.0) for _ in chosen]
        ws = sum(weights)
        weights = [w / ws for w in weights]
        # 找到底层名称
        for btm_cd, w in zip(chosen, weights):
            btm_nm = None
            for t in BOND_TEMPLATES:
                if t[0] == btm_cd:
                    btm_nm = t[1]; break
            if not btm_nm:
                for t in STOCK_TEMPLATES:
                    if t[0] == btm_cd:
                        btm_nm = t[1]; break
            docs.append({
                'AST_CD': ast_cd,
                'BTM_AST_CD': btm_cd,
                'RATIO': round(w, 6),
                'BTM_NM': btm_nm or btm_cd,
            })
    return docs


# ============= 7) dwd_ast_fiveclass =============
def build_ast_fiveclass():
    """债券 + 部分股票 五级分类（NORMAL 70% / WATCH 20% / 其余 10%）"""
    docs = []
    bonds = BOND_AST
    chosen = random.sample(bonds, k=min(50, len(bonds)))
    levels = ['NORMAL'] * 35 + ['WATCH'] * 10 + ['SUBSTANDARD'] * 3 + ['DOUBTFUL'] * 1 + ['LOSS'] * 1
    random.shuffle(levels)
    reasons = {
        'NORMAL': '资产质量良好，主体经营稳定',
        'WATCH': '主体行业景气下行，需持续关注',
        'SUBSTANDARD': '主体出现资金紧张迹象',
        'DOUBTFUL': '主体偿付能力存疑',
        'LOSS': '主体已发生违约',
    }
    for ast_cd, lvl in zip(chosen, levels):
        last_lvl = lvl if random.random() > 0.15 else random.choice(['NORMAL', 'WATCH', 'SUBSTANDARD'])
        adj_flag = 'Y' if last_lvl != lvl else 'N'
        docs.append({
            'AST_CD': ast_cd,
            'BIZ_DT': BIZ_DT,
            'CLASS_LVL': lvl,
            'CLASS_REASON': reasons[lvl],
            'ADJ_FLAG': adj_flag,
            'LAST_LVL': last_lvl,
        })
    return docs


# ============= 8) dwd_ast_calc_rule =============
def build_ast_calc_rule():
    """估值/计算规则池（按资产类型）"""
    rules = [
        ('BOND', 'BOND_AC',     '债券摊余成本法',     '按摊余成本对持有至到期债券估值',                '20200101'),
        ('BOND', 'BOND_FV',     '债券公允价值法',     '按中债估值净价 + 应计利息估值',                  '20200101'),
        ('BOND', 'BOND_FULL',   '债券全价法',         '价格按全价计算，不单独列示应计利息',              '20200101'),
        ('BOND', 'BOND_NET',    '债券净价法',         '价格按净价计算，应计利息单独列示',                '20200101'),
        ('STOCK', 'STK_CLOSE',  '股票收盘价估值',     '按当日收盘价估值',                              '20200101'),
        ('STOCK', 'STK_VWAP',   '股票成交均价',       '按当日成交量加权均价估值',                       '20200101'),
        ('FUND',  'FUND_NAV',   '基金单位净值',       '按当日单位净值估值',                            '20200101'),
        ('FUND',  'FUND_T1',    '基金 T+1 净值',      '按 T+1 日确认的单位净值估值',                   '20200101'),
        ('MMF',   'MMF_AMORT',  '货币基金摊余',       '按摊余成本法估值，单位净值固定 1.0000',           '20200101'),
        ('REPO',  'REPO_LINEAR','回购利息直线法',     '按回购利率与回购天数线性计算应收利息',            '20200101'),
        ('INDEX', 'IDX_CLOSE',  '指数收盘价',         '按指数当日收盘点数计算',                         '20200101'),
        # 重复一些规则使数据丰富
        ('BOND', 'BOND_AC_2',   '债券摊余成本法-持有至到期', '专用于 HTM 分类的债券',                       '20200101'),
        ('BOND', 'BOND_TPA',    '债券交易性金融资产', '按公允价值估值，变动计入当期损益',                '20200101'),
        ('STOCK', 'STK_OTC',    '场外股票估值',       '按最近一次估值倍数法或交易价',                   '20200101'),
        ('FUND',  'FUND_LP',    '私募基金估值',       '按 LP 份额公允价值估值',                        '20200101'),
    ]
    return [
        {'AST_TYPE': at, 'RULE_CD': rc, 'RULE_NM': nm, 'FORMULA': fmla, 'EFF_DT': eff}
        for at, rc, nm, fmla, eff in rules
    ]


# ============= 9) dwd_val_detail =============
def build_val_detail(ptl_ast_hld_docs):
    """估值明细：基于 ptl_ast_hld 反算"""
    docs = []
    for h in ptl_ast_hld_docs:
        mkt_val = h['MKT_VAL']
        cost_amt = h['COST_AMT']
        unreal = round(mkt_val - cost_amt, 2)
        # 当日盈亏 ≈ 市值 × 日收益率
        daily_pnl = round(mkt_val * random.gauss(0.0003, 0.005), 2)
        # 实现盈亏（部分卖出后）
        real_pnl = round(unreal * random.uniform(-0.05, 0.05), 2)
        # 摊销金额（仅债券）
        ast_cd = h['AST_CD']
        amort = round(mkt_val * random.uniform(0.0001, 0.0008), 2) if ast_cd in BOND_AST else 0.0
        docs.append({
            'PORT_ID': h['PORT_ID'],
            'AST_CD': ast_cd,
            'BIZ_DT': h['BIZ_DT'],
            'HLD_QTY': h['HLD_QTY'],
            'COST_PRC': h['COST_PRC'],
            'MKT_PRC': h['MKT_PRC'],
            'COST_AMT': cost_amt,
            'MKT_VAL': mkt_val,
            'ACI_AMT': h['ACI_AMT'],
            'UNREAL_PNL': unreal,
            'REAL_PNL': real_pnl,
            'DAILY_PNL': daily_pnl,
            'AMORT_AMT': amort,
        })
    return docs


# ============= 10) dwd_val_summary =============
def build_val_summary(ptl_info_docs, ptl_ast_hld_docs):
    """估值汇总：每组合按资产类别"""
    aum_map = {p['PORT_ID']: p['AUM'] for p in ptl_info_docs}
    # 聚合
    agg = {}  # (port_id, ast_class) -> mkt_val
    for h in ptl_ast_hld_docs:
        ast_cd = h['AST_CD']
        if ast_cd in BOND_AST:
            ac = 'BOND'
        elif ast_cd in STOCK_AST:
            ac = 'STOCK'
        elif ast_cd in FUND_AST:
            ac = 'FUND'
        else:
            ac = 'OTHER'
        key = (h['PORT_ID'], ac)
        agg[key] = agg.get(key, 0.0) + h['MKT_VAL']

    # 加现金
    for port_id, aum in aum_map.items():
        cash = aum * random.uniform(0.03, 0.10)
        agg[(port_id, 'CASH')] = cash

    docs = []
    for (port_id, ac), mv in agg.items():
        aum = aum_map.get(port_id, 1.0)
        weight = round(mv / max(aum, 1.0), 6)
        aci = round(mv * random.uniform(0.001, 0.008), 2) if ac == 'BOND' else 0.0
        docs.append({
            'PORT_ID': port_id,
            'BIZ_DT': BIZ_DT,
            'AST_CLASS': ac,
            'MKT_VAL': round(mv, 2),
            'WEIGHT': weight,
            'ACI_AMT': aci,
        })
    return docs


# ============= 11) dwd_val_bal =============
def build_val_bal(ptl_info_docs):
    """估值科目余额：每组合 6 个核心科目"""
    accounts = [
        ('1002', '银行存款', 'D'),
        ('1101', '交易性金融资产', 'D'),
        ('1108', '应收利息',     'D'),
        ('1109', '应收申购款',   'D'),
        ('2202', '应付赎回款',   'C'),
        ('6101', '管理费',       'D'),
    ]
    docs = []
    for p in ptl_info_docs:
        port_id = p['PORT_ID']
        aum = p['AUM']
        for acc_cd, acc_nm, direction in accounts:
            if acc_cd == '1002':
                bal = aum * random.uniform(0.03, 0.08)
            elif acc_cd == '1101':
                bal = aum * random.uniform(0.85, 0.95)
            elif acc_cd == '1108':
                bal = aum * random.uniform(0.005, 0.015)
            elif acc_cd == '1109':
                bal = aum * random.uniform(0.001, 0.008)
            elif acc_cd == '2202':
                bal = aum * random.uniform(0.001, 0.005)
            else:
                bal = aum * random.uniform(0.0005, 0.002)
            dr_bal = round(bal, 2) if direction == 'D' else 0.0
            cr_bal = round(bal, 2) if direction == 'C' else 0.0
            docs.append({
                'PORT_ID': port_id, 'BIZ_DT': BIZ_DT, 'ACC_CD': acc_cd, 'ACC_NM': acc_nm,
                'DR_BAL': dr_bal, 'CR_BAL': cr_bal, 'BAL': round(bal, 2), 'CCY': 'CNY',
            })
    return docs


# ============= 12) dwd_val_acc =============
def build_val_acc():
    """估值科目主数据"""
    accounts = [
        ('1002', '银行存款',           None,  1, 'D'),
        ('1101', '交易性金融资产',     None,  1, 'D'),
        ('110101', '债券-成本',       '1101', 2, 'D'),
        ('110102', '债券-应计利息',   '1101', 2, 'D'),
        ('110103', '债券-公允价值变动','1101', 2, 'D'),
        ('110201', '股票-成本',       '1101', 2, 'D'),
        ('110202', '股票-公允价值变动','1101', 2, 'D'),
        ('1108', '应收利息',           None,  1, 'D'),
        ('1109', '应收申购款',         None,  1, 'D'),
        ('2202', '应付赎回款',         None,  1, 'C'),
        ('220201', '应付管理费',      '2202', 2, 'C'),
        ('220202', '应付托管费',      '2202', 2, 'C'),
        ('3101', '实收基金',           None,  1, 'C'),
        ('3201', '未分配利润',         None,  1, 'C'),
        ('6101', '管理费',             None,  1, 'D'),
        ('6102', '托管费',             None,  1, 'D'),
        ('6103', '销售服务费',         None,  1, 'D'),
        ('6201', '利息收入',           None,  1, 'C'),
        ('6202', '股息收入',           None,  1, 'C'),
        ('6301', '公允价值变动损益',   None,  1, 'C'),
        ('6401', '投资收益',           None,  1, 'C'),
    ]
    return [
        {'ACC_CD': cd, 'ACC_NM': nm, 'PARENT_CD': par, 'ACC_LVL': lvl, 'DIRECTION': dr}
        for cd, nm, par, lvl, dr in accounts
    ]


# ============= 13) dwd_val_voucher =============
def build_val_voucher(ptl_info_docs):
    """每组合 3-6 张凭证"""
    docs = []
    voucher_types = [
        ('NORMAL', '管理费计提'),   ('NORMAL', '托管费计提'),
        ('NORMAL', '利息收入'),     ('NORMAL', '股息收入'),
        ('NORMAL', '公允价值变动'), ('ADJUST', '科目调整'),
    ]
    for p in ptl_info_docs:
        port_id = p['PORT_ID']
        aum = p['AUM']
        n = random.randint(3, 6)
        for i in range(n):
            v_type, desc = random.choice(voucher_types)
            amt = round(aum * random.uniform(0.0001, 0.0008), 2)
            docs.append({
                'PORT_ID': port_id, 'BIZ_DT': BIZ_DT,
                'VOUCHER_NO': f'V{port_id}{BIZ_DT}{i+1:03d}',
                'VOUCHER_TYPE': v_type, 'DESCRIPTION': desc,
                'DR_AMT': amt, 'CR_AMT': amt, 'CCY': 'CNY',
            })
    return docs


# ============= 14) dwd_val_notice =============
def build_val_notice(ptl_info_docs):
    """每组合 1-2 条通知"""
    docs = []
    notice_pool = {
        'NAV': ('单位净值公告', '本基金于 {dt} 单位净值为 {nav:.4f}'),
        'DIVIDEND': ('分红公告', '本基金拟于 {dt} 派发现金分红，每份额 {div:.4f} 元'),
        'EVENT': ('运作公告', '本基金 {dt} 召开持有人大会，审议 {topic}'),
    }
    topics = ['基金合同修订', '管理人变更', '托管人变更', '费率调整', '投资范围扩展']
    for p in ptl_info_docs:
        for nt, (title_t, content_t) in notice_pool.items():
            if random.random() > 0.4:
                if nt == 'NAV':
                    content = content_t.format(dt=BIZ_DT, nav=p['SHR_NAV'])
                elif nt == 'DIVIDEND':
                    content = content_t.format(dt=BIZ_DT, div=random.uniform(0.005, 0.05))
                else:
                    content = content_t.format(dt=BIZ_DT, topic=random.choice(topics))
                docs.append({
                    'PORT_ID': p['PORT_ID'], 'BIZ_DT': BIZ_DT, 'NOTICE_TYPE': nt,
                    'TITLE': f'{p["PORT_NM"]}{title_t}',
                    'CONTENT': content, 'PUB_DT': BIZ_DT,
                })
    return docs


# ============= 15) dwd_val_valtable =============
def build_val_valtable(ptl_info_docs):
    """估值表：每组合 1 条"""
    docs = []
    for p in ptl_info_docs:
        aum = p['AUM']
        nav = p['SHR_NAV']
        tot_lia = aum * random.uniform(0.005, 0.025)
        net_ast = aum - tot_lia
        tot_shr = round(net_ast / max(nav, 0.5), 2)
        acc_nav = round(nav + random.uniform(0.05, 1.5), 4)
        daily_rtn = round(random.gauss(0.0003, 0.008), 6)
        docs.append({
            'PORT_ID': p['PORT_ID'], 'BIZ_DT': BIZ_DT,
            'TOT_AST': round(aum, 2), 'TOT_LIA': round(tot_lia, 2),
            'NET_AST': round(net_ast, 2), 'SHR_NAV': nav, 'ACC_NAV': acc_nav,
            'TOT_SHR': tot_shr, 'DAILY_RTN': daily_rtn,
            'VAL_STATUS': 'CONFIRMED', 'VAL_VER': 'V1.0',
        })
    return docs


# ============= 16-18) 报告 =============
def build_val_rpt_bs(ptl_info_docs):
    docs = []
    rpt_dts = ['20231231', '20240630', '20241231']
    for p in ptl_info_docs:
        for rpt_dt in rpt_dts:
            aum = p['AUM']
            cash = aum * random.uniform(0.03, 0.08)
            bond = aum * random.uniform(0.30, 0.70)
            stock = aum * random.uniform(0.10, 0.55)
            fund = aum * random.uniform(0.0, 0.15)
            int_rcv = aum * random.uniform(0.005, 0.015)
            tot_ast = cash + bond + stock + fund + int_rcv
            pay_redeem = aum * random.uniform(0.001, 0.005)
            mgt_pay = aum * random.uniform(0.0005, 0.002)
            tot_lia = pay_redeem + mgt_pay
            equity = tot_ast - tot_lia
            docs.append({
                'PORT_ID': p['PORT_ID'], 'RPT_DT': rpt_dt,
                'CASH': round(cash, 2), 'BOND_HLD': round(bond, 2),
                'STOCK_HLD': round(stock, 2), 'FUND_HLD': round(fund, 2),
                'INT_RCV': round(int_rcv, 2), 'TOT_AST': round(tot_ast, 2),
                'PAY_REDEEM': round(pay_redeem, 2), 'MGT_FEE_PAY': round(mgt_pay, 2),
                'TOT_LIA': round(tot_lia, 2), 'EQUITY': round(equity, 2),
            })
    return docs


def build_val_rpt_is(ptl_info_docs):
    docs = []
    rpt_dts = ['20231231', '20240630', '20241231']
    for p in ptl_info_docs:
        for rpt_dt in rpt_dts:
            aum = p['AUM']
            int_inc = aum * random.uniform(0.015, 0.040)
            div_inc = aum * random.uniform(0.005, 0.025)
            trd_pnl = aum * random.uniform(-0.02, 0.05)
            fv_chg = aum * random.uniform(-0.04, 0.06)
            mgt_fee = aum * random.uniform(0.005, 0.015)
            cust_fee = aum * random.uniform(0.001, 0.0025)
            sales_fee = aum * random.uniform(0.001, 0.005)
            other_fee = aum * random.uniform(0.0002, 0.001)
            net_inc = int_inc + div_inc + trd_pnl + fv_chg - mgt_fee - cust_fee - sales_fee - other_fee
            docs.append({
                'PORT_ID': p['PORT_ID'], 'RPT_DT': rpt_dt,
                'INT_INC': round(int_inc, 2), 'DIV_INC': round(div_inc, 2),
                'TRD_PNL': round(trd_pnl, 2), 'FV_CHG_PNL': round(fv_chg, 2),
                'MGT_FEE': round(mgt_fee, 2), 'CUSTODY_FEE': round(cust_fee, 2),
                'SALES_FEE': round(sales_fee, 2), 'OTHER_FEE': round(other_fee, 2),
                'NET_INC': round(net_inc, 2),
            })
    return docs


def build_val_rpt_cf(ptl_info_docs):
    docs = []
    rpt_dts = ['20231231', '20240630', '20241231']
    for p in ptl_info_docs:
        for rpt_dt in rpt_dts:
            aum = p['AUM']
            inv_in = aum * random.uniform(0.20, 0.80)
            inv_out = aum * random.uniform(0.18, 0.78)
            inv_net = inv_in - inv_out
            sub = aum * random.uniform(0.05, 0.30)
            rdm = aum * random.uniform(0.04, 0.28)
            fin_net = sub - rdm
            docs.append({
                'PORT_ID': p['PORT_ID'], 'RPT_DT': rpt_dt,
                'CF_FROM_INV_INFLOW': round(inv_in, 2),
                'CF_FROM_INV_OUTFLOW': round(inv_out, 2),
                'CF_FROM_INV_NET': round(inv_net, 2),
                'CF_FROM_FIN_SUB': round(sub, 2),
                'CF_FROM_FIN_RDM': round(rdm, 2),
                'CF_FROM_FIN_NET': round(fin_net, 2),
                'CASH_NET_CHG': round(inv_net + fin_net, 2),
            })
    return docs


# ============= 主流程 =============
def main():
    print(f'[B3] 资产派生 + 估值/现金流生成')
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[DB_NAME]

    # 依赖前面写入的数据
    ptl_info_docs = list(db.dwd_ptl_info.find({}, {'_id': 0}))
    ptl_ast_hld_docs = list(db.dwd_ptl_ast_hld.find({}, {'_id': 0}))

    targets = [
        ('dwd_ast_pledge',         build_ast_pledge()),
        ('dwd_ast_party',          build_ast_party()),
        ('dwd_ast_exe_plan',       build_ast_exe_plan()),
        ('dwd_ast_cf_plan',        build_ast_cf_plan()),
        ('dwd_ast_fund_manager',   build_ast_fund_manager()),
        ('dwd_ast_bottom_raito',   build_ast_bottom_raito()),
        ('dwd_ast_fiveclass',      build_ast_fiveclass()),
        ('dwd_ast_calc_rule',      build_ast_calc_rule()),
        ('dwd_val_detail',         build_val_detail(ptl_ast_hld_docs)),
        ('dwd_val_summary',        build_val_summary(ptl_info_docs, ptl_ast_hld_docs)),
        ('dwd_val_bal',            build_val_bal(ptl_info_docs)),
        ('dwd_val_acc',            build_val_acc()),
        ('dwd_val_voucher',        build_val_voucher(ptl_info_docs)),
        ('dwd_val_notice',         build_val_notice(ptl_info_docs)),
        ('dwd_val_valtable',       build_val_valtable(ptl_info_docs)),
        ('dwd_val_rpt_bs',         build_val_rpt_bs(ptl_info_docs)),
        ('dwd_val_rpt_is',         build_val_rpt_is(ptl_info_docs)),
        ('dwd_val_rpt_cf',         build_val_rpt_cf(ptl_info_docs)),
    ]
    for coll_name, docs in targets:
        coll = db[coll_name]
        deleted = coll.delete_many({}).deleted_count
        if docs:
            coll.insert_many(docs)
        print(f'[B3] {coll_name:28s}: 清空 {deleted:5d} -> 写入 {len(docs):5d}')

    print('\n[B3] 校验：')
    print(f"  dwd_ast_pledge 样本: {db.dwd_ast_pledge.find_one({'PLEDGE_FLAG': 'Y'}, {'_id': 0})}")
    print(f"  dwd_ast_cf_plan 样本: {db.dwd_ast_cf_plan.find_one({'AST_CD': '019601.IB'}, {'_id': 0})}")
    print(f"  dwd_val_detail 样本: {db.dwd_val_detail.find_one({}, {'_id': 0})}")

    print('\n[B3] ✅ 完成')


if __name__ == '__main__':
    main()
