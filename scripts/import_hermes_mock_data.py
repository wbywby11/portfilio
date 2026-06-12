"""
Hermes Mock数据字段映射转换与导入脚本
- 读取 Hermes cache 目录下的所有JSON文件
- 对有标准Schema映射的集合进行字段转换
- 对无标准映射的集合直接导入（保留原始字段）
- 先清除asset_allocation数据库中之前导入的集合数据
- 重新导入转换后的数据
"""

import os
import json
from datetime import datetime
from pymongo import MongoClient

# ============================================================
# 配置
# ============================================================
MONGO_URI = 'mongodb://localhost:27017'
DB_NAME = 'asset_allocation'
DATA_DIR = r'C:\Users\wangb\.hermes\cache\mock_data'

# ============================================================
# 字段映射规则
# ============================================================

# 通用字段重命名规则（适用于大多数集合）
COMMON_RENAME = {
    'DATA_DT': 'BIZ_DT',
    'TRADE_DATE': 'BIZ_DT',
    'VALID_DATE': 'BIZ_DT',
    'AST_NAME': 'AST_NM',
    'PROD_CD': 'PORT_ID',
    'PROD_NAME': 'PORT_NM',
    'PROD_ABBR': 'PORT_SHORT_NM',
    'CUSTOMER_ID': 'ISR_ID',
    'CUSTOMER_NAME': 'ISR_NM',
    'CUSTOMER_ABBR': 'ISR_SHORT_NM',
    'CUR': 'CCY',
    'PUBLISH_DATE': 'LIST_DT',
    'MDATE': 'MATURITY_DT',
    'ESTABLISH_DATE': 'ESTAB_DT',
}

# 行情域特定字段映射
MARKET_RENAME = {
    'OPEN_PRICE': 'OPEN_PRC',
    'HIGH_PRICE': 'HIGH_PRC',
    'LOW_PRICE': 'LOW_PRC',
    'CLOSE_PRICE': 'CLOSE_PRC',
    'NET_PRICE': 'CLOSE_PRC',
    'VOLUME': 'VOL',
    'AMOUNT': 'AMT',
    'PE_RATIO': 'PE_TTM',
    'PB_RATIO': 'PB_LF',
    'YIELD': 'YTM',
}

# 估值域特定字段映射
VALUATION_RENAME = {
    'QUANTITY': 'HOLD_QTY',
    'COST_PRICE': 'COST_PRC',
    'MKT_PRICE': 'MKT_PRC',
    'UNREALIZED_PNL': 'UNREAL_PNL',
}

# 交易域特定字段映射
TRADE_RENAME = {
    'TRADE_DATE': 'TRADE_DT',
    'SETTLE_DATE': 'SETTLE_DT',
    'DIRECTION': 'TRADE_DIR',
    'QUANTITY': 'TRADE_QTY',
    'PRICE': 'TRADE_PRC',
    'AMOUNT': 'SETTLE_AMT',
    'COUNTERPARTY_ID': 'CNTP_ID',
    'COUNTERPARTY_NAME': 'CNTP_NM',
}

# 产品域特定字段映射
PRODUCT_RENAME = {
    'RISK_LEVEL': 'RISK_LVL',
    'NAV': 'SHR_NAV',
    'PROD_TYPE2': 'PORT_TYPE',
}

# 中债估值特定映射
CHINABOND_RENAME = {
    'NET_PRICE': 'VAL_NET_PRC',
    'FULL_PRICE': 'VAL_FULL_PRC',
    'YIELD': 'VAL_YIELD',
}

# 值域转换
VALUE_TRANSFORMS = {
    'TRADE_DIR': {'买入': 'BUY', '卖出': 'SELL'},
    'PORT_TYPE': {'债券型': 'BOND', '混合型': 'MIXED', '货币型': 'MMF', '指数型': 'INDEX'},
    'ISR_TYPE': {'国有企业': 'GOV', '民营企业': 'CORP', '中外合资': 'CORP', '外资企业': 'CORP'},
}

# 需要跳过的字段（不导入）
SKIP_FIELDS = {'DATA_TIME', 'DATA_SRC', 'IMPORT_TYPE', 'EFFECTFLAG', 'IS_MODIFY'}

# 集合级别的映射配置：key=Hermes文件名(不含.json), value=应用的额外映射
COLLECTION_CONFIG = {
    'dwd_ast_info': {'rename': {**COMMON_RENAME}},
    'dwd_ast_info_ch': {'rename': {**COMMON_RENAME, **CHINABOND_RENAME}},
    'dwd_ast_info_zg': {'rename': {**COMMON_RENAME, **CHINABOND_RENAME}},
    'dwd_ast_yield_info': {'rename': {**COMMON_RENAME}},
    'dwd_mkt_stock': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_bond': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_fund': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_abs': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_etf': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_index': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_lof': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_industry_index': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_commodity': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_fx': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_option': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_swap': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_repo_rate': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_yield_curve': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_credit_spread': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_mkt_bond_issue': {'rename': {**COMMON_RENAME, **MARKET_RENAME}},
    'dwd_ptl_info': {'rename': {**COMMON_RENAME, **PRODUCT_RENAME}},
    'dwd_ptl_nav': {'rename': {**COMMON_RENAME, **PRODUCT_RENAME}},
    'dwd_ptl_pstn_detail': {'rename': {**COMMON_RENAME, **VALUATION_RENAME}},
    'dwd_ptl_attribution': {'rename': {**COMMON_RENAME}},
    'dwd_ptl_fee': {'rename': {**COMMON_RENAME}},
    'dwd_ptl_risk': {'rename': {**COMMON_RENAME}},
    'dwd_ptl_sub_red': {'rename': {**COMMON_RENAME}},
    'dwd_val_detail': {'rename': {**COMMON_RENAME, **VALUATION_RENAME}},
    'dwd_val_bal': {'rename': {**COMMON_RENAME}},
    'dwd_val_summary': {'rename': {**COMMON_RENAME}},
    'dwd_trn_trade_ast': {'rename': {**COMMON_RENAME, **TRADE_RENAME}},
    'dwd_trn_trade_fund': {'rename': {**COMMON_RENAME, **TRADE_RENAME}},
    'dwd_isr_institution': {'rename': {**COMMON_RENAME}},
    'dwd_isr_financial': {'rename': {**COMMON_RENAME}},
    'dwd_isr_rating': {'rename': {**COMMON_RENAME}},
    'dwd_cust_info': {'rename': {**COMMON_RENAME}},
    'dwd_cust_trade': {'rename': {**COMMON_RENAME, **TRADE_RENAME}},
    'dwd_cust_contact': {'rename': {**COMMON_RENAME}},
    'dwd_cust_risk': {'rename': {**COMMON_RENAME}},
    'dwd_rsk_alert': {'rename': {**COMMON_RENAME}},
    'dwd_rsk_compliance': {'rename': {**COMMON_RENAME}},
    'dwd_rsk_limit': {'rename': {**COMMON_RENAME}},
    'dwd_rsk_report': {'rename': {**COMMON_RENAME}},
    'dwd_rsk_stress_test': {'rename': {**COMMON_RENAME}},
    'dwd_sls_sales': {'rename': {**COMMON_RENAME}},
}


# ============================================================
# 转换逻辑
# ============================================================

def transform_record(record, collection_name):
    """转换单条记录的字段名"""
    config = COLLECTION_CONFIG.get(collection_name)
    if not config:
        # 无映射配置的集合，仅做通用清理（移除SKIP_FIELDS）
        result = {k: v for k, v in record.items() if k not in SKIP_FIELDS and k != '_id'}
        result['src_sys'] = 'HERMES'
        result['etl_dt'] = datetime.now().strftime('%Y-%m-%d')
        return result

    rename_map = config.get('rename', {})
    result = {}

    for key, value in record.items():
        if key in SKIP_FIELDS:
            continue
        if key == '_id':
            continue  # MongoDB自动生成_id

        # 获取目标字段名
        new_key = rename_map.get(key, key)  # 有映射用映射名，无映射保留原名

        # 值域转换
        if new_key in VALUE_TRANSFORMS and value in VALUE_TRANSFORMS[new_key]:
            value = VALUE_TRANSFORMS[new_key][value]

        result[new_key] = value

    # 添加元数据
    result['src_sys'] = 'HERMES'
    result['etl_dt'] = datetime.now().strftime('%Y-%m-%d')

    return result


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("Hermes Mock数据字段映射转换与导入")
    print("=" * 60)
    print(f"数据源目录: {DATA_DIR}")
    print(f"目标数据库: {DB_NAME}")
    print()

    # 1. 检查数据目录是否存在
    if not os.path.isdir(DATA_DIR):
        print(f"[错误] 数据目录不存在: {DATA_DIR}")
        return

    # 2. 连接MongoDB
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    print("已连接MongoDB")

    # 3. 获取文件列表
    files = sorted([f for f in os.listdir(DATA_DIR)
                    if f.endswith('.json') and not f.startswith('generate_')])

    if not files:
        print("[警告] 数据目录下未找到JSON文件")
        client.close()
        return

    print(f"找到 {len(files)} 个JSON文件")
    print()

    # 4. 先删除之前导入的集合（根据文件名列表）
    print("正在清除之前导入的数据...")
    for filename in files:
        coll_name = filename.replace('.json', '')
        if coll_name == 'core_data':
            for sub_coll in ['issuers', 'assets', 'products', 'customers']:
                count = db[sub_coll].count_documents({})
                if count > 0:
                    db[sub_coll].delete_many({})
                    print(f"  已清除 {sub_coll}: {count} 条")
        else:
            count = db[coll_name].count_documents({})
            if count > 0:
                db[coll_name].delete_many({})
                print(f"  已清除 {coll_name}: {count} 条")

    print("清除完成")
    print()

    # 5. 重新导入（带字段映射）
    print("正在导入转换后的数据...")
    total_collections = 0
    total_records = 0
    errors = []

    for filename in files:
        filepath = os.path.join(DATA_DIR, filename)
        collection_name = filename.replace('.json', '')

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            errors.append(f"{filename}: 读取失败 - {e}")
            continue

        # core_data.json 需要拆分为子集合
        if collection_name == 'core_data' and isinstance(data, dict):
            for key, records in data.items():
                if isinstance(records, list) and len(records) > 0:
                    transformed = [transform_record(r, key) for r in records]
                    db[key].insert_many(transformed)
                    print(f"  \u2713 {key}: {len(transformed)} 条")
                    total_collections += 1
                    total_records += len(transformed)
        elif isinstance(data, list) and len(data) > 0:
            transformed = [transform_record(r, collection_name) for r in data]
            db[collection_name].insert_many(transformed)
            print(f"  \u2713 {collection_name}: {len(transformed)} 条")
            total_collections += 1
            total_records += len(transformed)
        elif isinstance(data, dict) and collection_name != 'core_data':
            # 某些文件可能是 dict 结构但不是 core_data，按子集合处理
            for key, records in data.items():
                if isinstance(records, list) and len(records) > 0:
                    transformed = [transform_record(r, key) for r in records]
                    db[key].insert_many(transformed)
                    print(f"  \u2713 {key}: {len(transformed)} 条")
                    total_collections += 1
                    total_records += len(transformed)
        else:
            print(f"  - {collection_name}: 跳过（空数据）")

    print()
    print("=" * 60)
    print(f"导入完成！共 {total_collections} 个集合，{total_records} 条记录")

    if errors:
        print(f"\n以下文件处理出错:")
        for err in errors:
            print(f"  [!] {err}")

    client.close()
    print("已断开MongoDB连接")


if __name__ == '__main__':
    main()
