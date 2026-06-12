"""
ZY 数据域字段别名映射（后端 API 双保险层）

由 scripts/repair_zy_data_alignment.py 自动生成。
在 zy_data_api_implementation.py 的查询响应中调用 apply_field_aliases() 可保证
即使 MongoDB 中字段名未对齐，前端依然能拿到 schema 期望的字段名。
"""

# {table: {actual_field: expected_field}}
FIELD_ALIASES = {
    'dwd_ast_calc_rule': {
        'CALC_RULE': 'FORMULA',
    },
    'dwd_ast_cf_plan': {
        'CF_DATE': 'CF_DT',
    },
    'dwd_ast_exe_plan': {
        'EXE_DATE': 'EXE_DT',
        'EXE_PRICE': 'EXE_PRC',
    },
    'dwd_ast_fiveclass': {
        'DATA_DT': 'BIZ_DT',
        'FIVE_CLASS': 'CLASS_LVL',
    },
    'dwd_ast_fund_manager': {
        'FM_ID': 'MANAGER_ID',
        'FM_NAME': 'MANAGER_NM',
    },
    'dwd_ast_info': {
        'AST_NAME': 'AST_NM',
        'CUSTOMER_ID': 'ISR_ID',
        'LIST_DATE': 'LIST_DT',
        'MDATE': 'MATURITY_DT',
    },
    'dwd_ast_info_ch': {
        'DATA_DT': 'BIZ_DT',
    },
    'dwd_ast_info_zg': {
        'DATA_DT': 'BIZ_DT',
    },
    'dwd_ast_party': {
        'DATA_DT': 'BIZ_DT',
        'PARTY_NAME': 'PARTY_NM',
    },
    'dwd_ast_pledge': {
        'DATA_DT': 'BIZ_DT',
        'PLEDGE_RATE': 'PLEDGE_RATIO',
    },
    'dwd_ast_yield_info': {
        'DATA_DT': 'BIZ_DT',
    },
    'dwd_cust_info': {
        'CUST_ID': 'CUSTOMER_ID',
        'CUST_NAME': 'CUST_NM',
        'DATA_DT': 'BIZ_DT',
        'OPEN_DATE': 'OPEN_DT',
        'RISK_LEVEL': 'RISK_LVL',
    },
    'dwd_cust_make_pstn_info': {
        'CUST_ID': 'CUSTOMER_ID',
        'DATA_DT': 'BIZ_DT',
    },
    'dwd_isr_institution': {
        'CUSTOMER_ID': 'ISR_ID',
        'DATA_DT': 'BIZ_DT',
        'INDUSTRY_GB': 'INDUSTRY_CD',
    },
    'dwd_isr_institution_finance': {
        'CUSTOMER_ID': 'ISR_ID',
        'REPORT_DATE': 'RPT_DT',
    },
    'dwd_isr_trd_cntp': {
        'DATA_DT': 'BIZ_DT',
    },
    'dwd_mkt_bond': {
        'AMOUNT': 'AMT',
        'CLOSE_PRICE': 'CLOSE_PRC',
        'DATA_DT': 'BIZ_DT',
        'HIGH_PRICE': 'HIGH_PRC',
        'LOW_PRICE': 'LOW_PRC',
        'OPEN_PRICE': 'OPEN_PRC',
        'VOLUME': 'VOL',
    },
    'dwd_mkt_fund': {
        'DATA_DT': 'BIZ_DT',
    },
    'dwd_mkt_index': {
        'BASE_DATE': 'BASE_DT',
        'DATA_DT': 'BIZ_DT',
        'INDEX_NAME': 'INDEX_NM',
    },
    'dwd_mkt_stock': {
        'AST_NAME': 'STOCK_NM',
        'DATA_DT': 'BIZ_DT',
        'MARKET_CAP': 'TOT_CAP',
        'MKT_CD': 'EXCH',
    },
    'dwd_ptl_fee': {
        'PROD_CD': 'PORT_ID',
    },
    'dwd_ptl_info': {
        'CURR': 'CCY',
        'INT_BENCHMARK': 'BENCHMARK',
        'PROD_ABBR': 'PORT_NM',
        'PROD_CD': 'PORT_ID',
        'START_DATE': 'ESTAB_DT',
    },
    'dwd_trn_trade_ast': {
        'LONG_CURRENCY': 'CCY',
        'LONG_QUANTITY': 'QTY',
        'SETTLE_DATE': 'SETT_DT',
        'TRAN_DATE': 'TRADE_DT',
        'TRAN_SIDE': 'BS_DIR',
    },
    'dwd_trn_trade_ptl': {
        'PROD_CD': 'PORT_ID',
        'TRADE_AMT': 'AMT',
        'TRADE_DATE': 'TRADE_DT',
        'TRADE_QTY': 'QTY',
    },
    'dwd_val_bal': {
        'DATA_DT': 'BIZ_DT',
        'PROD_CD': 'PORT_ID',
    },
    'dwd_val_detail': {
        'DATA_DT': 'BIZ_DT',
        'PROD_CD': 'PORT_ID',
    },
    'dwd_val_summary': {
        'DATA_DT': 'BIZ_DT',
        'PROD_CD': 'PORT_ID',
    },
}


def apply_field_aliases(collection, record):
    """对单条 MongoDB 记录应用字段别名（保留原字段，新增别名字段）"""
    if collection not in FIELD_ALIASES:
        return record
    aliases = FIELD_ALIASES[collection]
    for src, tgt in aliases.items():
        if src in record and tgt not in record:
            record[tgt] = record[src]
    return record
