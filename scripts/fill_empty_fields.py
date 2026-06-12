"""
ZY 数据域空值字段二次填充优化
对修复后仍存在空字符串/null 的字段，按字段语义生成更真实的业务值。
"""
import re
import random
from pathlib import Path
from collections import OrderedDict
from pymongo import MongoClient

PROJECT_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = PROJECT_ROOT / "src" / "config" / "zyDataDomain"
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"


def parse_schema_file(p):
    content = p.read_text(encoding='utf-8')
    tables = OrderedDict()
    for m in re.finditer(r"T\(\s*'([a-zA-Z_]+)'\s*,\s*'([^']+)'", content):
        name, label = m.group(1), m.group(2)
        depth = 0; end = m.start()
        for i, ch in enumerate(content[m.start():], m.start()):
            if ch == '(': depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0: end = i + 1; break
        block = content[m.start():end]
        # 解析字段及类型
        fields = []
        for fm in re.finditer(r"f\(\s*'([A-Z0-9_]+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'", block):
            fields.append({'key': fm.group(1), 'label': fm.group(2), 'type': fm.group(3)})
        tables[name] = {'label': label, 'fields': fields}
    return tables


# 业务化默认值生成器（按字段名 + 类型）
def smart_value(field_key, field_type, idx=0):
    """按字段名语义和位置序号生成更真实的业务值"""
    fk = field_key.upper()

    # 日期类
    if field_type == 'date' or fk.endswith('_DT') or 'DATE' in fk:
        if 'BIRTH' in fk: return f'19{75 + idx % 25}-{(idx % 12) + 1:02d}-15'
        if any(k in fk for k in ['MATURITY', 'END', 'EXP']): return f'20{30 + idx % 10}-12-{15 + idx % 14:02d}'
        if 'SETT' in fk: return '2025-03-25'
        if 'CFM' in fk or 'CONFIRM' in fk: return '2025-03-25'
        if 'PAY' in fk: return f'2025-{(3 + idx % 9):02d}-15'
        if 'LIST' in fk or 'ESTAB' in fk: return f'20{15 + idx % 8}-{(1 + idx % 12):02d}-{1 + idx % 28:02d}'
        if 'OUT_DT' == fk: return ''  # 调出日合理可空
        return '2025-03-24'

    # 数值类
    if field_type == 'number':
        if any(k in fk for k in ['RATIO', 'WEIGHT', 'PCT', 'CHG_PCT']):
            return round(random.uniform(0.05, 0.95), 4)
        if any(k in fk for k in ['RATE', 'YIELD', 'COUPON']):
            return round(random.uniform(0.02, 0.06), 4)
        if any(k in fk for k in ['RTN', 'RETURN', 'ALPHA', 'BETA']):
            return round(random.uniform(-0.05, 0.15), 4)
        if any(k in fk for k in ['PRC', 'PRICE', 'NAV', 'VAL_NET', 'VAL_FULL', 'CLOSE', 'OPEN', 'HIGH', 'LOW']):
            return round(random.uniform(95.0, 110.0), 4)
        if 'BP' in fk: return random.randint(-30, 30)
        if 'STAGE' in fk: return random.choice([1, 2, 3])
        if 'DURATION' in fk or 'CONVEXITY' in fk:
            return round(random.uniform(1.0, 8.5), 3)
        if any(k in fk for k in ['SHARPE', 'SORTINO']):
            return round(random.uniform(0.5, 2.5), 3)
        if 'KEY_RATE' in fk: return round(random.uniform(-0.5, 0.5), 4)
        if any(k in fk for k in ['QTY', 'SHR', 'VOL', 'COUNT', 'CNT']):
            return random.randint(10000, 5000000)
        if any(k in fk for k in ['AMT', 'AMOUNT', 'CAP', 'AUM', 'BAL', 'VAL']):
            return round(random.uniform(1e6, 5e8), 2)
        if any(k in fk for k in ['FEE', 'TAX']):
            return round(random.uniform(100, 50000), 2)
        if 'PD' in fk or 'LGD' in fk or 'EAD' in fk:
            return round(random.uniform(0.001, 0.15), 4)
        if 'ECL' in fk: return round(random.uniform(1000, 1e6), 2)
        if 'TRACKING' in fk: return round(random.uniform(0.001, 0.05), 4)
        if 'TURNOVER' in fk: return round(random.uniform(0.5, 5.0), 3)
        if 'PE' in fk: return round(random.uniform(8, 50), 2)
        if 'PB' in fk: return round(random.uniform(0.5, 8), 2)
        return round(random.uniform(0, 1000), 2)

    # 字符串/枚举类（按字段名语义）
    enum_map = {
        'BS_DIR': ['B', 'S'],
        'CCY': ['CNY', 'USD', 'HKD'],
        'AST_TYPE': ['BOND', 'STOCK', 'FUND', 'CASH'],
        'AST_SUB_TYPE': ['CGB', 'CDB', 'NCD', 'CB', 'EB', 'POL'],
        'PORT_TYPE': ['MIXED', 'STOCK', 'BOND', 'MMF'],
        'RISK_LVL': ['R1', 'R2', 'R3', 'R4', 'R5'],
        'STATUS': ['ACTIVE', 'CONFIRMED', 'SETTLED'],
        'TRD_TYPE': ['SUBSCRIBE', 'REDEEM', 'BUY', 'SELL'],
        'BIZ_TYPE': ['SUBSCRIBE', 'REDEEM', 'INTEREST', 'DIVIDEND'],
        'TRADE_STATUS': ['FILLED', 'PARTIAL', 'PENDING'],
        'ORD_TYPE': ['LIMIT', 'MARKET'],
        'SETT_STATUS': ['SETTLED', 'PENDING'],
        'SETT_TYPE': ['DVP', 'PVP', 'FOP'],
        'MARKET': ['IB', 'SSE', 'SZSE'],
        'EXCH': ['SSE', 'SZSE', 'IB'],
        'CHANNEL': ['DIRECT', 'BANK', 'TA'],
        'CF_TYPE': ['INTEREST', 'PRINCIPAL', 'BOTH'],
        'EXE_TYPE': ['CALL', 'PUT', 'EXTEND'],
        'CLASS_LVL': ['NORMAL', 'CONCERN', 'SUBSTANDARD', 'DOUBTFUL', 'LOSS'],
        'LAST_LVL': ['NORMAL', 'CONCERN'],
        'ADJ_FLAG': ['Y', 'N'],
        'PLEDGE_FLAG': ['Y', 'N'],
        'GENDER': ['M', 'F'],
        'ID_TYPE': ['IDCARD', 'PASSPORT'],
        'CUST_TYPE': ['IND', 'INST'],
        'PARTY_ROLE': ['ISSUER', 'GUARANTOR', 'TRUSTEE', 'AUDITOR'],
        'CE_TYPE': ['SUB', 'RED', 'CONFIRM'],
        'FEE_TYPE': ['MGT', 'CUS', 'SUB', 'RED'],
        'OPEN_TYPE': ['SUB', 'RED', 'BOTH'],
        'AST_CLASS': ['STOCK', 'BOND', 'CASH', 'OTHER'],
        'BAL_TYPE': ['DEBIT', 'CREDIT'],
        'HOLDER_TYPE': ['IND', 'INST', 'INTERNAL'],
        'OUTLOOK': ['POSITIVE', 'STABLE', 'NEGATIVE'],
        'ACTION': ['UPGRADE', 'DOWNGRADE', 'AFFIRM'],
        'INDEX_TYPE': ['EQUITY', 'BOND', 'COMMODITY'],
        'FUND_TYPE': ['OPEN', 'CLOSE', 'ETF'],
        'CURVE_TYPE': ['TREASURY', 'POLICY', 'CREDIT'],
        'ACCT_TYPE': ['BANK', 'BROKER'],
        'IS_TRADE': ['Y', 'N'],
        'IS_MONTH_END': ['Y', 'N'],
        'IS_QUARTER_END': ['Y', 'N'],
        'IS_YEAR_END': ['Y', 'N'],
        'SHR_FLAG': ['Y', 'N'],
        'TENOR': ['1M', '3M', '6M', '1Y', '3Y', '5Y', '10Y'],
        'BOND_TERM': ['3Y', '5Y', '7Y', '10Y', '30Y'],
        'VAL_STATUS': ['VALUED', 'PENDING'],
        'DIV_TYPE': ['CASH', 'REINVEST'],
        'SUS_TYPE': ['NEW_YEAR', 'OTHER'],
        'CAL_TYPE': ['IB', 'SSE', 'SZSE'],
        'AGENCY': ['CHINA_LIANHE', 'CHINA_CHENGXIN', 'DAGONG'],
        'RATING_AGENCY': ['CHINA_LIANHE', 'CHINA_CHENGXIN', 'DAGONG'],
    }
    if fk in enum_map: return random.choice(enum_map[fk])

    # 名称类
    name_map = {
        'AST_NM': f'资产_{idx:04d}', 'PORT_NM': f'组合_{idx:04d}', 'PORT_SHORT_NM': f'PORT_{idx:04d}',
        'CUST_NM': f'客户_{idx:04d}', 'STOCK_NM': f'股票_{idx:04d}', 'INDEX_NM': f'指数_{idx:04d}',
        'FUND_NM': f'基金_{idx:04d}', 'CURVE_NM': f'曲线_{idx:04d}', 'RATE_NM': f'利率_{idx:04d}',
        'MANAGER_NM': f'经理_{idx % 50}', 'PARTY_NM': f'关联方_{idx:04d}', 'BTM_NM': f'底层_{idx:04d}',
        'RULE_NM': f'规则_{idx:04d}', 'ACCT_NM': f'账户_{idx:04d}', 'BR_NM': f'支行_{idx:04d}',
        'INDUSTRY_NM': random.choice(['银行', '证券', '保险', '能源', '化工', '医药', '消费', '科技']),
        'INDUSTRY_CD': f'IND{random.randint(100, 999)}',
        'BENCHMARK': '中债综合财富指数',
        'MGR_INST': random.choice(['博时基金', '华夏基金', '易方达基金', '汇添富基金', '南方基金']),
        'PUBLISHER': random.choice(['中证指数公司', '中债登', '上交所', '深交所']),
        'CUSTODY_BANK': random.choice(['工商银行', '建设银行', '招商银行', '中国银行']),
        'BANK': random.choice(['工商银行', '建设银行', '招商银行', '中国银行']),
        'SOURCE': random.choice(['CFETS', 'CHINABOND', 'WIND']),
        'SRC': random.choice(['CFETS', 'CHINABOND', 'WIND']),
        'FORMULA': 'SUM(QTY * PRC) / SUM(QTY)',
        'REASON': '常规调整',
        'NOTE': '系统填充',
        'REMARK': '系统填充',
        'PHONE': f'138{random.randint(10000000, 99999999)}',
        'EMAIL': f'user{idx}@example.com',
        'ADDR': f'北京市朝阳区{random.choice(["建国路", "国贸路", "大望路"])}{random.randint(1, 200)}号',
        'ID_NO': f'1101{random.randint(100000000000, 999999999999)}',
        'BOND_RATING': random.choice(['AAA', 'AA+', 'AA', 'AA-', 'A+']),
        'ISSUER_RATING': random.choice(['AAA', 'AA+', 'AA', 'AA-']),
        'RATING': random.choice(['AAA', 'AA+', 'AA', 'AA-', 'A+']),
        'PREV_RATING': random.choice(['AAA', 'AA+', 'AA', 'AA-']),
    }
    if fk in name_map: return name_map[fk]

    # 兜底：返回字段名作为占位符（避免空字符串）
    return f'{fk}_{idx:03d}'


def main():
    schemas = OrderedDict()
    for p in sorted(SCHEMA_DIR.glob("[0-9]*.js")):
        schemas.update(parse_schema_file(p))

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[DB_NAME]
    existing = set(db.list_collection_names())

    print('=' * 60)
    print('  ZY 数据域空值字段二次填充优化')
    print('=' * 60)

    total_updated = 0
    total_fields_filled = 0
    table_stats = []

    for tname, info in schemas.items():
        if tname not in existing:
            continue
        coll = db[tname]
        total_docs = coll.count_documents({})
        if total_docs == 0:
            continue

        field_types = {f['key']: f['type'] for f in info['fields']}
        expected_keys = list(field_types.keys())

        # 找出"空值率高"的字段
        sample_n = 0
        null_count = {k: 0 for k in expected_keys}
        for doc in coll.find({}, limit=80):
            sample_n += 1
            for k in expected_keys:
                v = doc.get(k)
                if v is None or v == '':
                    null_count[k] += 1
        if sample_n == 0:
            continue

        target_fields = [k for k in expected_keys if null_count[k] / sample_n > 0.5]
        if not target_fields:
            continue

        # 对每个目标字段，按业务语义生成默认值；为了多样性，按文档下标生成不同值
        modified = 0
        docs = list(coll.find({}, {'_id': 1}, limit=total_docs))
        for idx, d in enumerate(docs):
            updates = {}
            # 重新读完整文档以判断当前字段是否真的为空
            full = coll.find_one({'_id': d['_id']})
            for fk in target_fields:
                cur = full.get(fk)
                if cur is None or cur == '':
                    updates[fk] = smart_value(fk, field_types.get(fk, 'string'), idx)
            if updates:
                coll.update_one({'_id': d['_id']}, {'$set': updates})
                modified += 1

        total_updated += modified
        total_fields_filled += len(target_fields) * modified
        marker = '✅' if modified > 0 else '⚪'
        print(f"  {marker} {tname:40s} | 优化字段:{len(target_fields):>2} | 影响文档:{modified:>5}")
        table_stats.append((tname, len(target_fields), modified))

    print(f'\n{"="*60}')
    print(f'  总优化文档数: {total_updated:,}')
    print(f'  总字段填充次数: {total_fields_filled:,}')
    print(f'  涉及表数: {len(table_stats)}')
    client.close()


if __name__ == '__main__':
    random.seed(42)
    main()
