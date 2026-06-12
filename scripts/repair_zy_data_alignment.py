"""
ZY 数据域字段对齐修复脚本（方案A + 数据填充）

功能:
1. 解析前端 schema，构建每张表的"前端期望字段集"
2. 读取 MongoDB 实际字段，自动 + 规则推测字段映射
3. 在 MongoDB 中执行字段重命名（$rename）
4. 对缺失的关键字段，根据字段类型/上下文生成合理默认值并填充（$set）
5. 输出后端 API 字段别名模块（双保险）
6. 输出修复明细报告

使用方法:
  cd d:\portfilio
  python scripts/repair_zy_data_alignment.py
"""
import os
import re
import sys
import json
import random
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict

from pymongo import MongoClient

# ===== 配置 =====
PROJECT_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = PROJECT_ROOT / "src" / "config" / "zyDataDomain"
KEYS_FILE = SCHEMA_DIR / "keys.js"
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"

OUTPUT_ALIASES_PY = PROJECT_ROOT / "scripts" / "zy_data_field_aliases.py"
OUTPUT_REPORT = PROJECT_ROOT / "docs" / "ZY_DATA_REPAIR_REPORT.md"
OUTPUT_MAPPING_JSON = PROJECT_ROOT / "scripts" / "zy_field_mapping.json"

BIZ_DT = "20250324"

# 系统审计字段
AUDIT_FIELDS = {
    'etl_dt', 'src_sys', '_id', 'created_at', 'updated_at',
    'DATA_TIME', 'DATA_DT', 'DATA_SRC', 'IMPORT_TYPE'
}

# ===== 通用字段映射规则（按命名规律） =====
# 高频字段命名差异（前端期望 -> 实际数据可能的字段名）
COMMON_ALIASES = {
    # 日期类
    'TRADE_DT': ['TRADE_DATE', 'TRAN_DATE', 'TRD_DT'],
    'TRAN_DATE': ['TRADE_DATE', 'TRADE_DT'],
    'SETT_DT': ['SETTLE_DATE', 'SETTLEMENT_DATE', 'SETT_DATE'],
    'BIZ_DT': ['DATA_DT', 'BUSINESS_DATE', 'BIZ_DATE'],
    'EXE_DT': ['EXE_DATE', 'EXERCISE_DATE'],
    'CF_DT': ['CF_DATE', 'CASHFLOW_DATE'],
    'OPEN_DT': ['OPEN_DATE'],
    'LIST_DT': ['LIST_DATE', 'ISSUE_DATE', 'VDATE'],
    'MATURITY_DT': ['MATURITY_DATE', 'MDATE'],
    'ESTAB_DT': ['ESTABLISH_DATE', 'START_DATE'],
    'BIRTH_DT': ['BIRTH_DATE'],
    'EFF_DT': ['EFFECTIVE_DATE', 'EFFECT_DATE'],
    'EXP_DT': ['EXPIRE_DATE'],
    'START_DT': ['START_DATE', 'BEGIN_DATE'],
    'END_DT': ['END_DATE', 'STOP_DATE'],
    'CFM_DT': ['CONFIRM_DATE'],
    'DIV_DT': ['DIVIDEND_DATE'],
    'EX_DIV_DT': ['EX_DIVIDEND_DATE'],
    'PAY_DT': ['PAY_DATE', 'PAYMENT_DATE'],
    'SUBMIT_DT': ['SUBMIT_DATE'],
    'IN_DT': ['IN_DATE'],
    'OUT_DT': ['OUT_DATE'],
    'BASE_DT': ['BASE_DATE'],
    'RATING_DT': ['RATING_DATE'],
    'RPT_DT': ['REPORT_DATE'],
    'SUS_DT': ['SUSPEND_DATE'],
    'RES_DT': ['RESUME_DATE'],
    'CAL_DT': ['CALENDAR_DATE'],
    'FIRST_BUY_DT': ['FIRST_BUY_DATE'],
    'CLASS_DT': ['CLASS_DATE'],

    # 金额/价格
    'AMT': ['AMOUNT', 'TRADE_AMT', 'TRD_AMT', 'TRAN_AMT'],
    'PRC': ['PRICE', 'PRC_VAL'],
    'NET_PRC': ['NET_PRICE'],
    'FULL_PRC': ['FULL_PRICE'],
    'EXE_PRC': ['EXE_PRICE', 'EXERCISE_PRICE'],
    'OPEN_PRC': ['OPEN', 'OPEN_PRICE'],
    'CLOSE_PRC': ['CLOSE', 'CLOSE_PRICE'],
    'HIGH_PRC': ['HIGH', 'HIGH_PRICE'],
    'LOW_PRC': ['LOW', 'LOW_PRICE'],
    'AVG_PRC': ['AVG_PRICE', 'AVERAGE_PRICE'],
    'COST_PRC': ['COST_PRICE'],
    'MKT_PRC': ['MKT_PRICE', 'MARKET_PRICE'],
    'CF_AMT': ['CF_AMOUNT', 'CASHFLOW_AMT'],
    'NET_AMT': ['NET_AMOUNT'],
    'CFM_AMT': ['CONFIRM_AMOUNT'],
    'DIV_AMT': ['DIVIDEND_AMOUNT'],
    'NET_DIV_AMT': ['NET_DIVIDEND_AMOUNT'],
    'BAL_BEFORE': ['BALANCE_BEFORE'],
    'BAL_AFTER': ['BALANCE_AFTER'],
    'COST_AMT': ['COST_AMOUNT'],
    'MKT_VAL': ['MARKET_VALUE', 'MKT_VALUE'],
    'TOT_AMT': ['TOTAL_AMOUNT'],
    'ISSUE_AMT': ['ISSUE_AMOUNT'],
    'TGT_RATIO': ['TARGET_RATIO'],
    'COUPON_RATE': ['OUPON_RATE', 'COUPON'],
    'FEE_RATE': ['FEE_RATIO'],

    # 数量
    'QTY': ['QUANTITY', 'TRADE_QTY', 'LONG_QUANTITY'],
    'SHR': ['SHARE', 'SHARES'],
    'TOT_SHR': ['TOTAL_SHARES', 'TOTAL_SHR'],
    'HLD_SHR': ['HOLD_SHARES', 'HOLDING_SHARES'],
    'AVAIL_SHR': ['AVAILABLE_SHARES'],
    'FROZEN_SHR': ['FROZEN_SHARES'],
    'CFM_SHR': ['CONFIRM_SHARES'],
    'HLD_QTY': ['HOLD_QTY', 'HOLDING_QTY'],
    'FILL_QTY': ['FILLED_QTY'],
    'SETT_QTY': ['SETTLE_QUANTITY'],
    'ORD_QTY': ['ORDER_QTY', 'ORDER_QUANTITY'],

    # 主键/标识
    'PORT_ID': ['PROD_CD', 'PORT_CODE', 'PRD_CD', 'PRODUCT_CD', 'PRODUCT_ID'],
    'PORT_NM': ['PROD_ABBR', 'PROD_NAME', 'PORT_NAME', 'PRODUCT_NAME'],
    'PORT_SHORT_NM': ['PROD_ABBR', 'PORT_ABBR', 'SHORT_NAME'],
    'AST_NM': ['AST_NAME', 'ASSET_NAME', 'AST_ABBR'],
    'CUST_NM': ['CUST_NAME', 'CUSTOMER_NAME'],
    'CUSTOMER_ID': ['CUST_ID'],
    'ISR_ID': ['CUSTOMER_ID', 'ISSUER_ID', 'ISSUE_ID'],
    'CNTP_ID': ['COUNTERPARTY_ID', 'COUNTER_PARTY_ID'],
    'CFM_NO': ['CFM_NUM', 'CONFIRM_NUM'],
    'APPLY_NO': ['APPLY_NUM'],
    'SRL_NO': ['SERIAL_NO'],
    'ACCT_NO': ['ACCOUNT_NO'],
    'BOND_ACCT_NO': ['BOND_ACCOUNT'],
    'CASH_ACCT_NO': ['CASH_ACCOUNT'],

    # 枚举/类型
    'BS_DIR': ['BS_DIRECTION', 'TRD_SIDE', 'TRAN_SIDE', 'BUY_SELL'],
    'TRD_TYPE': ['TRADE_TYPE', 'TRAN_TYPE'],
    'CCY': ['CURRENCY', 'CURR', 'LONG_CURRENCY'],
    'AST_CLASS': ['ASSET_CLASS'],
    'AST_TYPE': ['ASSET_TYPE'],
    'PORT_TYPE': ['PROD_TYPE', 'PRODUCT_TYPE'],
    'RISK_LVL': ['RISK_LEVEL'],
    'CLASS_LVL': ['CLASS_LEVEL', 'FIVE_CLASS'],
    'LAST_LVL': ['LAST_LEVEL', 'PREV_CLASS'],
    'ADJ_FLAG': ['ADJUST_FLAG'],
    'CE_TYPE': ['EVENT_TYPE'],
    'INDEX_TYPE': ['IDX_TYPE'],
    'FUND_TYPE': ['FUND_CATEGORY'],
    'BIZ_TYPE': ['BUSINESS_TYPE'],

    # 收益率/利率
    'YTM': ['YIELD_TO_MATURITY', 'PRICE_YIELD'],
    'YIELD_TM': ['YIELD_MATURITY', 'YIELD_TO_MATURITY'],
    'YIELD_EX': ['YIELD_EXERCISE'],
    'DAILY_RTN': ['DAILY_RETURN', 'PCT_CHANGE'],
    'WEEK_RTN': ['WEEK_RETURN'],
    'MONTH_RTN': ['MONTH_RETURN'],
    'YTD_RTN': ['YTD_RETURN'],
    'CHG_BP': ['CHANGE_BP'],
    'RATE_VAL': ['RATE_VALUE', 'RATE'],

    # 估值
    'VAL_NET_PRC': ['VAL_NET_PRICE'],
    'VAL_FULL_PRC': ['VAL_FULL_PRICE'],
    'VAL_YIELD': ['VALUATION_YIELD'],
    'VAL_SRC': ['VAL_SOURCE'],
    'RATING_AGENCY': ['AGENCY', 'CRD_AGENCY'],

    # 其他
    'VOL': ['VOLUME', 'TRADE_VOLUME'],
    'WEIGHT': ['WGT'],
    'RATIO': ['RATE', 'PCT'],
    'PLEDGE_FLAG': ['PLEDGE_STATUS', 'IS_PLEDGE'],
    'PLEDGE_RATIO': ['PLEDGE_RATE'],
    'PLEDGE_BOND_CD': ['PLEDGE_BOND'],
    'PLEDGE_NOTE': ['REMARK', 'NOTE'],
    'PLEDGE_STD_BOND': ['STD_BOND'],
    'CLASS_REASON': ['REASON'],
    'NOTE': ['REMARK'],
    'MANAGER_ID': ['FM_ID', 'MGR_ID'],
    'MANAGER_NM': ['FM_NAME', 'MGR_NAME', 'MANAGER_NAME'],
    'PARTY_ID': ['RELATED_PARTY_ID'],
    'PARTY_NM': ['PARTY_NAME', 'RELATED_PARTY_NAME'],
    'PARTY_ROLE': ['ROLE'],
    'BTM_AST_CD': ['BTM_ASSET_CD', 'UNDERLYING_CD'],
    'BTM_NM': ['BTM_NAME', 'UNDERLYING_NM'],
    'RULE_CD': ['RULE_CODE'],
    'RULE_NM': ['RULE_NAME'],
    'FORMULA': ['CALC_RULE', 'CALC_FORMULA'],
    'SHR_FLAG': ['SHARE_FLAG'],
    'EXE_TYPE': ['EXERCISE_TYPE'],
    'CF_TYPE': ['CASHFLOW_TYPE', 'PAY_FREQ'],
    'AUM': ['TOTAL_ASSET', 'NET_ASSET'],
    'BENCHMARK': ['PERF_BENCHMARK'],
    'MGR_INST': ['MANAGER_INST', 'MANAGER'],
    'CUSTODY_BANK': ['CUSTODY'],
    'SHR_NAV': ['UNIT_NAV', 'NAV_PER_SHARE'],
    'STATUS': ['STATE'],
    'STOCK_NM': ['STOCK_NAME', 'AST_NAME'],
    'INDEX_NM': ['INDEX_NAME'],
    'INDEX_CD': ['INDEX_CODE'],
    'FUND_NM': ['FUND_NAME'],
    'CURVE_NM': ['CURVE_NAME'],
    'RATE_NM': ['RATE_NAME'],
    'EXCH': ['EXCHANGE', 'MARKET', 'MKT_CD'],
    'INDUSTRY_CD': ['INDUSTRY_CODE', 'INDUSTRY_GB'],
    'INDUSTRY_NM': ['INDUSTRY_NAME'],
    'TOT_CAP': ['TOTAL_CAP', 'MARKET_CAP'],
    'FREE_CAP': ['FREE_FLOAT_CAP'],
    'TURNOVER': ['TURNOVER_RATE'],
    'PB_LF': ['PB'],
    'BANK_BR': ['BRANCH', 'BANK_BRANCH'],
    'ACCT_NM': ['ACCOUNT_NAME'],
    'ACCT_TYPE': ['ACCOUNT_TYPE'],
    'BR_NM': ['BRANCH_NAME'],
    'CHANNEL': ['CHN'],
    'SELLER_ID': ['SALES_ID'],
    'CONVEXITY': ['CONVX'],
    'DURATION': ['DUR'],
}


# ===== 工具函数 =====
def parse_schema_file(schema_path):
    """解析单个 schema JS 文件"""
    content = schema_path.read_text(encoding='utf-8')
    tables = OrderedDict()

    pattern = re.compile(r"T\(\s*'([a-zA-Z_]+)'\s*,\s*'([^']+)'", re.MULTILINE)
    for match in pattern.finditer(content):
        table_name = match.group(1)
        table_label = match.group(2)
        start_pos = match.start()
        depth = 0
        end_pos = start_pos
        for i, ch in enumerate(content[start_pos:], start_pos):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break
        block = content[start_pos:end_pos]

        field_pattern = re.compile(r"f\(\s*'([A-Z0-9_]+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'", re.MULTILINE)
        fields = []
        for fm in field_pattern.finditer(block):
            fkey = fm.group(1)
            flabel = fm.group(2)
            ftype = fm.group(3)
            fields.append({'key': fkey, 'label': flabel, 'type': ftype})

        tables[table_name] = {
            'label': table_label,
            'fields': fields,
            'field_keys': [f['key'] for f in fields],
            'field_types': {f['key']: f['type'] for f in fields},
        }
    return tables


def load_all_schemas():
    all_tables = OrderedDict()
    for schema_file in sorted(SCHEMA_DIR.glob("[0-9]*.js")):
        for name, info in parse_schema_file(schema_file).items():
            info['schema_file'] = schema_file.name
            all_tables[name] = info
    return all_tables


def collect_actual_fields(coll, sample=50):
    """从 MongoDB 集合采样收集实际出现的字段名"""
    fields = set()
    for doc in coll.find({}, limit=sample):
        fields.update(doc.keys())
    fields -= {'_id'}
    return fields


def build_rename_map(expected_keys, actual_keys):
    """
    构建 {actual_field: expected_field} 的重命名映射
    优先级：
      1. 完全相同（无需映射）
      2. 通用别名表
      3. 命名相似度推测（去下划线后包含关系）
    """
    expected = set(expected_keys)
    actual = set(actual_keys)
    rename = {}  # actual -> expected
    used_actual = set()

    # Pass 1: 完全相同的字段无需映射
    matched = expected & actual
    used_actual |= matched

    # Pass 2: 通用别名表
    for exp_key in sorted(expected - matched):
        candidates = COMMON_ALIASES.get(exp_key, [])
        for cand in candidates:
            if cand in actual and cand not in used_actual and cand != exp_key:
                rename[cand] = exp_key
                used_actual.add(cand)
                break

    # Pass 3: 命名相似度（去下划线后子串包含）
    not_matched = expected - matched - set(rename.values())
    free_actual = actual - used_actual - AUDIT_FIELDS
    for exp_key in sorted(not_matched):
        exp_norm = exp_key.replace('_', '').upper()
        best_cand = None
        best_score = 0
        for cand in free_actual:
            if cand in used_actual:
                continue
            cand_norm = cand.replace('_', '').upper()
            # 双向包含 + 长度差异 ≤ 3
            if exp_norm in cand_norm or cand_norm in exp_norm:
                score = min(len(exp_norm), len(cand_norm)) / max(len(exp_norm), len(cand_norm))
                if abs(len(exp_norm) - len(cand_norm)) <= 3 and score > best_score:
                    best_score = score
                    best_cand = cand
        if best_cand and best_score >= 0.6:
            rename[best_cand] = exp_key
            used_actual.add(best_cand)

    return rename


def gen_default_value(field_key, field_type, ast_cds, port_ids, isr_ids, customer_ids):
    """根据字段名/类型生成合理默认值"""
    # 日期类
    if field_type == 'date' or 'DT' in field_key or 'DATE' in field_key:
        # 不同语义日期：交易日/结算日/到期日略有偏移
        if 'MATURITY' in field_key or 'END' in field_key or 'EXP' in field_key:
            return '2030-12-31'
        if 'BIRTH' in field_key:
            return '1985-06-15'
        if 'SETT' in field_key:
            return '2025-03-25'
        if 'CFM' in field_key or 'CONFIRM' in field_key:
            return '2025-03-25'
        if 'PAY' in field_key:
            return '2025-04-15'
        if 'IN_DT' == field_key:
            return '2024-01-01'
        if 'OUT_DT' == field_key:
            return ''
        return '2025-03-24'

    # 数值类
    if field_type == 'number':
        if any(k in field_key for k in ['RATIO', 'WEIGHT', 'RTN', 'YIELD', 'RATE', 'PCT', 'CHG']):
            return round(random.uniform(0.01, 0.05), 4)
        if any(k in field_key for k in ['PRC', 'PRICE', 'NAV', 'VAL']):
            return round(random.uniform(95.0, 110.0), 4)
        if 'QTY' in field_key or 'SHR' in field_key or 'VOL' in field_key:
            return random.randint(10000, 1000000)
        if 'AMT' in field_key or 'AMOUNT' in field_key or 'CAP' in field_key:
            return round(random.uniform(1e6, 1e9), 2)
        if 'FEE' in field_key or 'TAX' in field_key:
            return round(random.uniform(10, 5000), 2)
        if 'DURATION' in field_key:
            return round(random.uniform(1, 10), 2)
        if 'CONVEXITY' in field_key:
            return round(random.uniform(10, 200), 2)
        if 'BP' in field_key:
            return random.randint(-50, 50)
        if 'SHARPE' in field_key or 'SORTINO' in field_key:
            return round(random.uniform(0.5, 2.0), 3)
        if 'BETA' in field_key or 'ALPHA' in field_key:
            return round(random.uniform(-0.5, 1.5), 3)
        if 'PD' in field_key or 'LGD' in field_key:
            return round(random.uniform(0.001, 0.1), 4)
        if 'COUNT' in field_key or 'CNT' in field_key:
            return random.randint(1, 100)
        if 'STAGE' in field_key:
            return random.choice([1, 2, 3])
        return round(random.uniform(0, 1000), 2)

    # 枚举/字符串类（按字段名语义）
    enum_defaults = {
        'BS_DIR': 'B', 'CCY': 'CNY', 'AST_TYPE': 'BOND', 'AST_SUB_TYPE': 'CGB',
        'PORT_TYPE': 'MIXED', 'RISK_LVL': 'R3', 'STATUS': 'ACTIVE',
        'TRD_TYPE': 'SUBSCRIBE', 'BIZ_TYPE': 'SUBSCRIBE', 'TRADE_STATUS': 'FILLED',
        'ORD_TYPE': 'LIMIT', 'SETT_STATUS': 'SETTLED', 'SETT_TYPE': 'DVP',
        'MARKET': 'IB', 'EXCH': 'SSE', 'CHANNEL': 'DIRECT',
        'CF_TYPE': 'INTEREST', 'EXE_TYPE': 'CALL', 'CLASS_LVL': 'NORMAL',
        'LAST_LVL': 'NORMAL', 'ADJ_FLAG': 'N', 'PLEDGE_FLAG': 'N',
        'GENDER': 'M', 'ID_TYPE': 'IDCARD', 'CUST_TYPE': 'IND',
        'PARTY_ROLE': 'ISSUER', 'CE_TYPE': 'SUB', 'FEE_TYPE': 'MGT',
        'ROLE': 'LEAD', 'OPEN_TYPE': 'BOTH', 'AST_CLASS': 'BOND',
        'BAL_TYPE': 'TOTAL', 'HOLDER_TYPE': 'INST', 'OUTLOOK': 'STABLE',
        'ACTION': 'AFFIRM', 'INDEX_TYPE': 'EQUITY', 'FUND_TYPE': 'OPEN',
        'CURVE_TYPE': 'TREASURY', 'ACCT_TYPE': 'BANK',
        'IS_TRADE': 'Y', 'IS_MONTH_END': 'N', 'IS_QUARTER_END': 'N', 'IS_YEAR_END': 'N',
        'SHR_FLAG': 'N', 'TENOR': '1Y', 'BOND_TERM': '10Y',
        'VAL_STATUS': 'VALUED', 'DIV_TYPE': 'CASH', 'SUS_TYPE': 'OTHER',
    }
    if field_key in enum_defaults:
        return enum_defaults[field_key]

    # 主键池
    if field_key in ('AST_CD', 'INT_AST_CD'):
        return ast_cds[0] if ast_cds else 'BOND_001'
    if field_key in ('PORT_ID',):
        return port_ids[0] if port_ids else 'PORT001'
    if field_key in ('ISR_ID',):
        return isr_ids[0] if isr_ids else 'ISR000001'
    if field_key in ('CUSTOMER_ID', 'CUST_ID'):
        return customer_ids[0] if customer_ids else 'CUS0000001'

    # 名称类
    name_defaults = {
        'AST_NM': '资产名称', 'PORT_NM': '产品名称', 'PORT_SHORT_NM': '产品简称',
        'CUST_NM': '客户名称', 'STOCK_NM': '股票名称', 'INDEX_NM': '指数名称',
        'FUND_NM': '基金名称', 'CURVE_NM': '收益率曲线', 'RATE_NM': '利率名称',
        'MANAGER_NM': '经理', 'PARTY_NM': '关联方', 'BTM_NM': '底层资产',
        'RULE_NM': '计算规则', 'ACCT_NM': '账户名称', 'BR_NM': '支行',
        'INDUSTRY_NM': '行业', 'CUST_TYPE': 'IND',
    }
    if field_key in name_defaults:
        return name_defaults[field_key]

    return ''


def load_keys_pools():
    """从 keys.js 解析主键池"""
    try:
        content = KEYS_FILE.read_text(encoding='utf-8')
        def extract(name):
            m = re.search(rf"export\s+const\s+{name}\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
            if not m:
                return []
            return re.findall(r"'([^']+)'", m.group(1))
        return {
            'ast_cds': extract('AST_CDS'),
            'port_ids': extract('PORT_IDS'),
            'isr_ids': extract('ISR_IDS'),
            'customer_ids': extract('CUSTOMER_IDS'),
        }
    except Exception:
        return {'ast_cds': [], 'port_ids': [], 'isr_ids': [], 'customer_ids': []}


# ===== 主流程 =====
def repair_collection(coll, schema, pools, dry_run=False):
    """对单个集合执行字段对齐 + 缺失填充"""
    expected_keys = schema['field_keys']
    field_types = schema['field_types']
    actual_keys = collect_actual_fields(coll)

    # 1. 构建重命名映射（actual -> expected）
    rename_map = build_rename_map(expected_keys, actual_keys)

    # 2. 执行重命名（注意：避免源字段与目标字段同名导致冲突）
    rename_result = {'renamed': 0, 'mapping': rename_map}
    if rename_map and not dry_run:
        # 过滤掉目标字段已存在的项（防止覆盖现有数据）
        safe_rename = {src: tgt for src, tgt in rename_map.items()
                       if src != tgt and tgt not in (actual_keys - {src})}
        if safe_rename:
            try:
                res = coll.update_many({}, {'$rename': safe_rename})
                rename_result['renamed'] = res.modified_count
            except Exception as e:
                rename_result['error'] = str(e)
        rename_result['mapping'] = safe_rename

    # 3. 重新统计字段并识别仍缺失的字段
    actual_keys_after = collect_actual_fields(coll) if not dry_run else (actual_keys | set(rename_map.values()))
    still_missing = set(expected_keys) - actual_keys_after

    # 4. 为缺失字段生成默认值并填充
    fill_result = {'filled': 0, 'fields': {}}
    if still_missing and not dry_run:
        # 为每条记录单独生成（部分字段可基于已有字段计算，这里用稳定默认值）
        defaults = {}
        for fk in still_missing:
            ftype = field_types.get(fk, 'string')
            defaults[fk] = gen_default_value(fk, ftype, pools['ast_cds'], pools['port_ids'],
                                             pools['isr_ids'], pools['customer_ids'])
        try:
            res = coll.update_many(
                {},
                {'$set': defaults}
            )
            fill_result['filled'] = res.modified_count
            fill_result['fields'] = defaults
        except Exception as e:
            fill_result['error'] = str(e)

    return {
        'expected': len(expected_keys),
        'actual_before': len(actual_keys),
        'actual_after': len(actual_keys_after),
        'rename': rename_result,
        'fill': fill_result,
        'still_missing_count': len(still_missing),
    }


def write_aliases_module(all_results, all_schemas):
    """生成后端 API 字段别名模块"""
    lines = [
        '"""',
        'ZY 数据域字段别名映射（后端 API 双保险层）',
        '',
        '由 scripts/repair_zy_data_alignment.py 自动生成。',
        '在 zy_data_api_implementation.py 的查询响应中调用 apply_field_aliases() 可保证',
        '即使 MongoDB 中字段名未对齐，前端依然能拿到 schema 期望的字段名。',
        '"""',
        '',
        '# {table: {actual_field: expected_field}}',
        'FIELD_ALIASES = {',
    ]
    for table, res in sorted(all_results.items()):
        mapping = res.get('rename', {}).get('mapping', {})
        if not mapping:
            continue
        lines.append(f"    '{table}': {{")
        for src, tgt in sorted(mapping.items()):
            lines.append(f"        '{src}': '{tgt}',")
        lines.append('    },')
    lines.append('}')
    lines.append('')
    lines.append('')
    lines.append('def apply_field_aliases(collection, record):')
    lines.append('    """对单条 MongoDB 记录应用字段别名（保留原字段，新增别名字段）"""')
    lines.append('    if collection not in FIELD_ALIASES:')
    lines.append('        return record')
    lines.append('    aliases = FIELD_ALIASES[collection]')
    lines.append('    for src, tgt in aliases.items():')
    lines.append('        if src in record and tgt not in record:')
    lines.append('            record[tgt] = record[src]')
    lines.append('    return record')
    lines.append('')

    OUTPUT_ALIASES_PY.write_text('\n'.join(lines), encoding='utf-8')


def write_repair_report(all_results, all_schemas, no_data_tables):
    lines = []
    lines.append('# ZY 数据域字段对齐与填充修复报告\n')
    lines.append(f'- 修复时间: 2026-06-01')
    lines.append(f'- 数据库: `{MONGO_URI}/{DB_NAME}`')
    lines.append(f'- 修复范围: MongoDB 现有集合（执行 $rename + 缺失字段 $set 填充）\n')

    total_renamed = sum(r['rename'].get('renamed', 0) for r in all_results.values())
    total_filled = sum(r['fill'].get('filled', 0) for r in all_results.values())
    total_rename_fields = sum(len(r['rename'].get('mapping', {})) for r in all_results.values())

    lines.append('## 一、修复总览\n')
    lines.append('| 指标 | 数值 |')
    lines.append('|------|------|')
    lines.append(f'| 处理表数 | {len(all_results)} |')
    lines.append(f'| 字段重命名（对齐前端 schema）总条数 | {total_rename_fields} |')
    lines.append(f'| 重命名影响的文档数 | {total_renamed:,} |')
    lines.append(f'| 缺失字段填充影响的文档数 | {total_filled:,} |\n')

    lines.append('## 二、各表修复明细\n')
    lines.append('| 表名 | 中文名 | 期望字段 | 重命名映射 | 填充字段 | 修复后剩余缺失 |')
    lines.append('|------|--------|---------|-----------|---------|-------------|')
    for table, res in sorted(all_results.items()):
        schema = all_schemas.get(table, {})
        label = schema.get('label', '-')
        rename_count = len(res['rename'].get('mapping', {}))
        fill_count = len(res['fill'].get('fields', {}))
        lines.append(
            f"| `{table}` | {label} | {res['expected']} | "
            f"{rename_count} | {fill_count} | {res['still_missing_count']} |"
        )
    lines.append('')

    lines.append('## 三、字段重命名详细映射\n')
    for table, res in sorted(all_results.items()):
        mapping = res['rename'].get('mapping', {})
        if not mapping:
            continue
        schema = all_schemas.get(table, {})
        label = schema.get('label', '-')
        lines.append(f'### `{table}` - {label}\n')
        lines.append('| 原字段（实际）| → | 新字段（前端期望）|')
        lines.append('|------|------|------|')
        for src, tgt in sorted(mapping.items()):
            lines.append(f'| `{src}` | → | `{tgt}` |')
        lines.append('')

    lines.append('## 四、字段填充详细\n')
    for table, res in sorted(all_results.items()):
        fields = res['fill'].get('fields', {})
        if not fields:
            continue
        schema = all_schemas.get(table, {})
        label = schema.get('label', '-')
        lines.append(f'### `{table}` - {label}\n')
        lines.append('| 字段 | 默认值（示例） |')
        lines.append('|------|---------------|')
        for fk, fv in sorted(fields.items()):
            v_str = json.dumps(fv, ensure_ascii=False) if not isinstance(fv, str) else f"'{fv}'"
            lines.append(f'| `{fk}` | `{v_str}` |')
        lines.append('')

    if no_data_tables:
        lines.append('## 五、前端有 schema 但 MongoDB 中无数据的表\n')
        lines.append('> 这些表无法通过本次修复得到数据，需要后续单独补齐 mock 数据。\n')
        for t in sorted(no_data_tables):
            schema = all_schemas.get(t, {})
            lines.append(f'- `{t}` - {schema.get("label", "-")}')
        lines.append('')

    lines.append('## 六、后续操作建议\n')
    lines.append('1. **后端集成**: 将 `scripts/zy_data_field_aliases.py` 引入后端 API；')
    lines.append('   在 `zy_data_api_implementation.py` 的列表查询响应中调用 `apply_field_aliases(collection, record)`。')
    lines.append('2. **前端验证**: 重启前端，访问 `/zy-data` 模块查看 `dwd_trn_trade_ptl` 等表，')
    lines.append('   确认"交易日/买卖方向/数量/价格/金额/币种"等字段不再为空。')
    lines.append('3. **重复运行安全**: 脚本可重入；MongoDB 已对齐字段不会被反复重命名。')
    lines.append('4. **缺失数据补齐**: 第五节列出的表需后续单独生成。')

    OUTPUT_REPORT.write_text('\n'.join(lines), encoding='utf-8')


def main():
    print('=' * 80)
    print('  ZY 数据域字段对齐与填充修复（方案A）')
    print('=' * 80)

    # 1. 加载 schema + 主键池
    print(f'\n[1/4] 加载前端 schema 与主键池...')
    schemas = load_all_schemas()
    pools = load_keys_pools()
    print(f'  ✅ schema: {len(schemas)} 张表')
    print(f'  ✅ 主键池: AST_CDS={len(pools["ast_cds"])}, PORT_IDS={len(pools["port_ids"])}, '
          f'ISR_IDS={len(pools["isr_ids"])}, CUSTOMER_IDS={len(pools["customer_ids"])}')

    # 2. 连接 MongoDB
    print(f'\n[2/4] 连接 MongoDB: {MONGO_URI}')
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[DB_NAME]
    existing_collections = set(db.list_collection_names())
    print(f'  ✅ 已连接，现有集合: {len(existing_collections)} 个')

    # 3. 逐表修复
    print(f'\n[3/4] 执行字段对齐 + 缺失填充...')
    all_results = OrderedDict()
    no_data_tables = []
    for tname, schema in schemas.items():
        if tname not in existing_collections:
            no_data_tables.append(tname)
            continue
        coll = db[tname]
        if coll.count_documents({}) == 0:
            no_data_tables.append(tname)
            continue

        result = repair_collection(coll, schema, pools, dry_run=False)
        all_results[tname] = result

        rename_n = len(result['rename'].get('mapping', {}))
        fill_n = len(result['fill'].get('fields', {}))
        marker = '✅' if result['still_missing_count'] == 0 else '⚠️ '
        print(f"  {marker} {tname:40s} | 重命名:{rename_n:>2} 填充:{fill_n:>2} "
              f"残缺:{result['still_missing_count']:>2}")

    # 4. 输出别名模块 + 修复报告
    print(f'\n[4/4] 生成产出文件...')
    write_aliases_module(all_results, schemas)
    write_repair_report(all_results, schemas, no_data_tables)
    OUTPUT_MAPPING_JSON.write_text(json.dumps(
        {t: {'rename': r['rename'].get('mapping', {}),
             'fill': r['fill'].get('fields', {})}
         for t, r in all_results.items()},
        ensure_ascii=False, indent=2, default=str
    ), encoding='utf-8')
    print(f'  ✅ 后端别名模块: {OUTPUT_ALIASES_PY}')
    print(f'  ✅ 修复明细报告: {OUTPUT_REPORT}')
    print(f'  ✅ 字段映射JSON: {OUTPUT_MAPPING_JSON}')

    # 汇总
    total_renamed = sum(r['rename'].get('renamed', 0) for r in all_results.values())
    total_filled = sum(r['fill'].get('filled', 0) for r in all_results.values())
    total_rename_fields = sum(len(r['rename'].get('mapping', {})) for r in all_results.values())
    fully_aligned = sum(1 for r in all_results.values() if r['still_missing_count'] == 0)

    print(f'\n{"="*80}')
    print(f'  修复汇总')
    print(f'{"="*80}')
    print(f'  处理表数         : {len(all_results)}')
    print(f'  完全对齐表数      : {fully_aligned}')
    print(f'  字段重命名映射条数 : {total_rename_fields}')
    print(f'  重命名影响文档数   : {total_renamed:,}')
    print(f'  填充影响文档数    : {total_filled:,}')
    print(f'  无数据待补齐表数   : {len(no_data_tables)}')

    client.close()


if __name__ == '__main__':
    random.seed(42)  # 确定性默认值
    main()
