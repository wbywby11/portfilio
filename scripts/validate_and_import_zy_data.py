"""
ZY 数据域真实业务数据校验与导入工具

功能:
1. 校验数据目录下的数据文件
2. 验证字段完整性、数据格式、数据真实性
3. 检查与前端 schema 配置的兼容性
4. 导入到 MongoDB 数据库
5. 验证导入结果

使用方法:
  cd d:\portfilio
  python scripts/validate_and_import_zy_data.py
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime
from pymongo import MongoClient, ASCENDING
from collections import defaultdict

# 配置
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"
DATA_DIR = Path("C:/Users/wangb/.hermes/cache/mock_data/full_output")

# 前端期望的字段映射（基于 schema 配置）
EXPECTED_FIELDS = {
    'dwd_ast_info': ['AST_CD', 'AST_NM', 'AST_TYPE', 'AST_SUB_TYPE', 'ISR_ID', 'CCY', 'LIST_DT', 'MATURITY_DT', 'COUPON_RATE', 'ISSUE_AMT', 'MARKET', 'BOND_TERM'],
    'dwd_ast_info_ch': ['AST_CD', 'BIZ_DT', 'VAL_NET_PRC', 'VAL_FULL_PRC', 'VAL_YIELD', 'DURATION', 'CONVEXITY'],
    'dwd_ast_info_zg': ['AST_CD', 'BIZ_DT', 'VAL_NET_PRC', 'VAL_FULL_PRC', 'VAL_YIELD', 'DURATION', 'CONVEXITY'],
    'dwd_ast_yield_info': ['AST_CD', 'BIZ_DT', 'YIELD_TM', 'YIELD_EX', 'DAILY_RTN', 'WEEK_RTN', 'MONTH_RTN'],
    'dwd_ast_cf_plan': ['AST_CD', 'CF_DT', 'CF_TYPE', 'CF_AMT', 'CCY'],
    'dwd_ast_pledge': ['AST_CD', 'BIZ_DT', 'PLEDGE_FLAG', 'PLEDGE_RATIO'],
    'dwd_ast_party': ['AST_CD', 'PARTY_ID', 'PARTY_NM', 'PARTY_ROLE'],
    'dwd_ast_exe_plan': ['AST_CD', 'EXE_DT', 'EXE_TYPE', 'EXE_PRC'],
    'dwd_ast_fund_manager': ['AST_CD', 'MANAGER_ID', 'MANAGER_NM', 'START_DT'],
    'dwd_ast_bottom_raito': ['AST_CD', 'BTM_AST_CD', 'RATIO', 'BTM_NM'],
    'dwd_ast_fiveclass': ['AST_CD', 'BIZ_DT', 'CLASS_LVL', 'CLASS_REASON'],
    'dwd_ast_calc_rule': ['AST_TYPE', 'RULE_CD', 'RULE_NM', 'FORMULA'],
    'dwd_cust_info': ['CUST_ID', 'CUST_NAME', 'CUST_TYPE', 'ID_TYPE', 'ID_NO', 'RISK_LEVEL', 'RISK_TYPE'],
    'dwd_cust_contact': ['CUST_ID', 'CONTACT_TYPE', 'CONTACT_INFO'],
    'dwd_cust_risk': ['CUST_ID', 'BIZ_DT', 'RISK_LEVEL', 'RISK_SCORE'],
    'dwd_cust_tag': ['CUST_ID', 'TAG_CODE', 'TAG_NAME'],
    'dwd_cust_intention': ['CUST_ID', 'INTENTION_TYPE', 'INTENTION_LEVEL'],
    'dwd_cust_belong': ['CUST_ID', 'MANAGER', 'DEPT'],
    'dwd_cust_make_pstn_info': ['CUST_ID', 'PSTN_CD', 'HOLD_RATIO'],
    'dwd_cust_trade': ['CUST_ID', 'TRADE_ID', 'TRADE_DATE', 'AMOUNT'],
    'dwd_cust_asset_summary': ['CUST_ID', 'BIZ_DT', 'TOTAL_ASSET', 'AVAILABLE_ASSET'],
    'dwd_isr_institution': ['ISR_ID', 'ISR_NAME', 'ISR_TYPE', 'CREDIT_RATING'],
    'dwd_isr_institution_finance': ['ISR_ID', 'BIZ_DT', 'TOTAL_ASSET', 'NET_PROFIT'],
    'dwd_isr_rating': ['ISR_ID', 'BIZ_DT', 'RATING_AGENCY', 'CREDIT_RATING'],
    'dwd_isr_trd_cntp': ['ISR_ID', 'CNTP_ID', 'TRADE_DATE'],
    'dwd_mkt_stock': ['AST_CD', 'TRADE_DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME', 'AMOUNT'],
    'dwd_mkt_bond': ['AST_CD', 'TRADE_DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME', 'YIELD'],
    'dwd_mkt_fund': ['AST_CD', 'TRADE_DATE', 'NAV', 'ACC_NAV', 'DAILY_RTN'],
    'dwd_mkt_index': ['AST_CD', 'TRADE_DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME'],
    'dwd_mkt_fx': ['CCY_PAIR', 'TRADE_DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE'],
    'dwd_mkt_commodity': ['AST_CD', 'TRADE_DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME'],
    'dwd_mkt_repo_rate': ['RATE_CD', 'TRADE_DATE', 'RATE', 'VOLUME'],
    'dwd_mkt_credit_spread': ['RATING', 'TENOR', 'BIZ_DT', 'SPREAD'],
    'dwd_mkt_yield_curve': ['CURVE_ID', 'TENOR', 'BIZ_DT', 'RATE'],
    'dwd_mkt_industry_index': ['INDEX_CD', 'TRADE_DATE', 'CLOSE', 'PCT_CHANGE'],
    'dwd_ptl_info': ['PORT_ID', 'PORT_NM', 'PORT_TYPE', 'RISK_LEVEL', 'INCEPTION_DT'],
    'dwd_ptl_nav': ['PORT_ID', 'BIZ_DT', 'NAV', 'ACC_NAV', 'DAILY_RTN'],
    'dwd_ptl_pstn_detail': ['PORT_ID', 'AST_CD', 'BIZ_DT', 'MKT_VAL', 'HOLD_QTY'],
    'dwd_ptl_sub_red': ['PORT_ID', 'TRADE_DATE', 'TRD_TYPE', 'AMOUNT', 'STATUS'],
    'dwd_ptl_contract': ['PORT_ID', 'CONTRACT_ID', 'CONTRACT_TYPE'],
    'dwd_ptl_channel': ['PORT_ID', 'CHANNEL', 'SALES_AMT'],
    'dwd_ptl_attribution': ['PORT_ID', 'BIZ_DT', 'ATTR_TYPE', 'VALUE'],
    'dwd_ptl_manager': ['PORT_ID', 'MANAGER_ID', 'MANAGER_NM', 'START_DT'],
    'dwd_ptl_fee': ['PORT_ID', 'FEE_TYPE', 'FEE_RATE'],
    'dwd_ptl_risk': ['PORT_ID', 'BIZ_DT', 'RISK_METRIC', 'VALUE'],
    'dwd_ptl_class_map': ['PORT_ID', 'CLASS_TYPE', 'CLASS_VALUE'],
    'dwd_val_detail': ['PORT_ID', 'AST_CD', 'BIZ_DT', 'VAL_AMT', 'VAL_METHOD'],
    'dwd_val_summary': ['PORT_ID', 'BIZ_DT', 'TOTAL_VAL', 'NET_VAL'],
    'dwd_val_bal': ['PORT_ID', 'BIZ_DT', 'BAL_TYPE', 'BAL_AMT'],
    'dwd_val_method': ['AST_TYPE', 'VAL_METHOD', 'DESCRIPTION'],
    'dwd_val_receivable_payable': ['PORT_ID', 'BIZ_DT', 'RCV_PAY_TYPE', 'AMOUNT'],
    'dwd_val_adjustment': ['PORT_ID', 'BIZ_DT', 'ADJ_TYPE', 'ADJ_AMT'],
    'dwd_val_impairment': ['PORT_ID', 'AST_CD', 'BIZ_DT', 'IMPAIR_AMT'],
    'dwd_val_review': ['PORT_ID', 'BIZ_DT', 'REVIEW_STATUS', 'REVIEWER'],
    'dwd_val_exception': ['PORT_ID', 'BIZ_DT', 'EXCEPTION_TYPE', 'DESCRIPTION'],
    'dwd_val_diff': ['PORT_ID', 'BIZ_DT', 'DIFF_TYPE', 'DIFF_AMT'],
    'dwd_rsk_limit': ['PORT_ID', 'LIMIT_TYPE', 'LIMIT_VALUE', 'CURRENT_VALUE'],
    'dwd_rsk_compliance': ['PORT_ID', 'BIZ_DT', 'COMPLIANCE_TYPE', 'STATUS'],
    'dwd_rsk_stress_test': ['PORT_ID', 'BIZ_DT', 'SCENARIO', 'RESULT'],
    'dwd_rsk_alert': ['PORT_ID', 'ALERT_TYPE', 'ALERT_LEVEL', 'MESSAGE'],
    'dwd_rsk_report': ['PORT_ID', 'RPT_TYPE', 'RPT_DATE', 'CONTENT'],
    'dwd_sls_sales': ['SELLER_ID', 'PORT_ID', 'SALES_DATE', 'SALES_AMT'],
    'dwd_trn_trade_ast': ['TRADE_ID', 'AST_CD', 'TRAN_DATE', 'TRADE_MARKET', 'NET_PRICE', 'LONG_QUANTITY'],
    'dwd_trn_trade_ptl': ['TRADE_ID', 'PORT_ID', 'AST_CD', 'TRAN_DATE', 'BS_DIR', 'QTY'],
}

def print_section(title):
    """打印分隔线"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")

def check_file_structure():
    """检查文件结构"""
    print_section("1. 文件结构检查")
    
    if not DATA_DIR.exists():
        print(f"❌ 数据目录不存在: {DATA_DIR}")
        return False
    
    json_files = list(DATA_DIR.glob("*.json"))
    print(f"✅ 找到 {len(json_files)} 个 JSON 文件")
    
    # 检查核心文件
    core_files = ['core_data.json', 'dwd_ast_info.json', 'dwd_cust_info.json', 'dwd_mkt_stock.json']
    missing_files = [f for f in core_files if not (DATA_DIR / f).exists()]
    
    if missing_files:
        print(f"⚠️  缺少核心文件: {missing_files}")
    else:
        print(f"✅ 核心文件完整")
    
    return True

def validate_data_file(file_path):
    """验证单个数据文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 处理不同格式
        if isinstance(data, dict):
            # core_data.json 格式: {"issuers": [...], "assets": [...]}
            records = []
            for key, value in data.items():
                if isinstance(value, list):
                    records.extend(value)
        elif isinstance(data, list):
            # 直接是数组
            records = data
        else:
            print(f"❌ 未知数据格式: {file_path.name}")
            return None
        
        return records
    except Exception as e:
        print(f"❌ 读取文件失败 {file_path.name}: {e}")
        return None

def validate_fields(collection_name, records):
    """验证字段完整性"""
    if not records:
        return {'status': 'empty', 'issues': []}
    
    expected = EXPECTED_FIELDS.get(collection_name, [])
    if not expected:
        return {'status': 'no_schema', 'issues': [f"前端未定义 {collection_name} 的字段 schema"]}
    
    # 检查第一条记录的字段
    first_record = records[0]
    actual_fields = set(first_record.keys())
    expected_fields = set(expected)
    
    missing_fields = expected_fields - actual_fields
    extra_fields = actual_fields - expected_fields - {'_id', 'etl_dt', 'src_sys', 'created_at', 'updated_at', 'DATA_TIME', 'DATA_DT', 'DATA_SRC', 'IMPORT_TYPE'}
    
    issues = []
    if missing_fields:
        issues.append(f"缺少关键字段: {missing_fields}")
    if extra_fields:
        issues.append(f"包含额外字段: {extra_fields}")
    
    # 检查数据类型
    type_issues = []
    for field in expected:
        if field in first_record:
            val = first_record[field]
            if val is not None:
                # 检查日期字段
                if 'DT' in field or 'DATE' in field:
                    if not isinstance(val, str) or len(val) < 8:
                        type_issues.append(f"字段 {field} 日期格式异常: {val}")
                # 检查数值字段
                elif field in ['COUPON_RATE', 'ISSUE_AMT', 'NAV', 'CLOSE', 'VOLUME', 'AMOUNT']:
                    if not isinstance(val, (int, float)):
                        type_issues.append(f"字段 {field} 应为数值类型: {type(val)}")
    
    status = 'ok' if not issues and not type_issues else 'warning'
    return {
        'status': status,
        'total_records': len(records),
        'fields_count': len(actual_fields),
        'missing_fields': list(missing_fields),
        'extra_fields': list(extra_fields),
        'type_issues': type_issues,
        'issues': issues + type_issues
    }

def check_data_quality(collection_name, records):
    """检查数据质量"""
    if not records or len(records) == 0:
        return {'status': 'empty'}
    
    quality_issues = []
    
    # 检查空值比例
    sample_size = min(10, len(records))
    for i in range(sample_size):
        record = records[i]
        empty_fields = [k for k, v in record.items() if v is None or v == '']
        if len(empty_fields) > len(record) * 0.5:
            quality_issues.append(f"记录 {i} 空值过多: {len(empty_fields)}/{len(record)}")
    
    # 检查重复记录
    if len(records) > 1:
        pk_fields = ['AST_CD', 'CUST_ID', 'PORT_ID', 'ISR_ID', 'TRADE_ID']
        pk = None
        for field in pk_fields:
            if field in records[0]:
                pk = field
                break
        
        if pk:
            pk_values = [r.get(pk) for r in records]
            duplicates = len(pk_values) - len(set(pk_values))
            if duplicates > 0:
                quality_issues.append(f"主键 {pk} 重复: {duplicates} 条")
    
    # 检查业务逻辑
    if 'dwd_ast_info' in collection_name:
        # 检查资产代码格式
        for record in records[:5]:
            ast_cd = record.get('AST_CD', '')
            if ast_cd and '.' not in ast_cd and not ast_cd.startswith('BOND_') and not ast_cd.startswith('STOCK_'):
                quality_issues.append(f"资产代码格式不规范: {ast_cd}")
    
    status = 'ok' if not quality_issues else 'warning'
    return {
        'status': status,
        'sample_size': sample_size,
        'quality_issues': quality_issues
    }

def validate_all_data():
    """验证所有数据文件"""
    print_section("2. 数据验证")
    
    json_files = sorted(DATA_DIR.glob("*.json"))
    validation_results = {}
    
    total_files = 0
    total_records = 0
    valid_files = 0
    warning_files = 0
    
    for file_path in json_files:
        collection_name = file_path.stem
        total_files += 1
        
        print(f"\n📄 验证: {file_path.name}")
        
        # 验证数据结构
        records = validate_data_file(file_path)
        if records is None:
            validation_results[collection_name] = {'status': 'error'}
            continue
        
        print(f"  📊 记录数: {len(records)}")
        total_records += len(records)
        
        # 验证字段
        field_validation = validate_fields(collection_name, records)
        print(f"  🔍 字段状态: {field_validation['status']}")
        if field_validation['issues']:
            for issue in field_validation['issues']:
                print(f"    ⚠️  {issue}")
        
        # 检查数据质量
        quality_check = check_data_quality(collection_name, records)
        print(f"  ✨ 数据质量: {quality_check['status']}")
        if quality_check.get('quality_issues'):
            for issue in quality_check['quality_issues']:
                print(f"    ⚠️  {issue}")
        
        # 综合状态
        overall_status = 'ok'
        if field_validation['status'] == 'warning' or quality_check['status'] == 'warning':
            overall_status = 'warning'
            warning_files += 1
        else:
            valid_files += 1
        
        validation_results[collection_name] = {
            'status': overall_status,
            'record_count': len(records),
            'field_validation': field_validation,
            'quality_check': quality_check,
            'file_path': file_path
        }
    
    print_section("验证结果汇总")
    print(f"📊 总文件数: {total_files}")
    print(f"📈 总记录数: {total_records:,}")
    print(f"✅ 有效文件: {valid_files}")
    print(f"⚠️  警告文件: {warning_files}")
    print(f"❌ 错误文件: {total_files - valid_files - warning_files}")
    
    return validation_results

def import_to_mongodb(validation_results):
    """导入数据到MongoDB"""
    print_section("3. 导入 MongoDB")
    
    # 连接 MongoDB
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client[DB_NAME]
        print(f"✅ MongoDB 连接成功: {MONGO_URI}/{DB_NAME}")
    except Exception as e:
        print(f"❌ MongoDB 连接失败: {e}")
        print(f"   请确保 MongoDB 服务已启动")
        return False
    
    # 导入数据
    total_imported = 0
    success_collections = 0
    failed_collections = 0
    
    for collection_name, result in validation_results.items():
        if result['status'] == 'error':
            print(f"\n⏭️  跳过 {collection_name} (验证失败)")
            failed_collections += 1
            continue
        
        file_path = result['file_path']
        records = validate_data_file(file_path)
        
        if not records:
            print(f"\n⏭️  跳过 {collection_name} (无数据)")
            continue
        
        print(f"\n📦 导入: {collection_name} ({len(records)} 条记录)")
        
        try:
            # 删除已存在的数据（避免重复）
            old_count = db[collection_name].count_documents({})
            if old_count > 0:
                db[collection_name].delete_many({})
                print(f"   🗑️  删除旧数据: {old_count} 条")
            
            # 添加审计字段
            for record in records:
                record['etl_dt'] = datetime.now().strftime('%Y-%m-%d')
                record['src_sys'] = 'HERMES_GENERATED'
                record['created_at'] = datetime.now()
                record['updated_at'] = datetime.now()
            
            # 批量插入
            result = db[collection_name].insert_many(records, ordered=False)
            count = len(result.inserted_ids)
            total_imported += count
            success_collections += 1
            print(f"   ✅ 导入成功: {count} 条")
            
            # 创建索引
            if collection_name in EXPECTED_FIELDS:
                # 为常见查询字段创建索引
                pk_fields = ['AST_CD', 'CUST_ID', 'PORT_ID', 'ISR_ID', 'TRADE_ID']
                for field in pk_fields:
                    if field in records[0]:
                        try:
                            db[collection_name].create_index([(field, ASCENDING)])
                        except:
                            pass  # 索引可能已存在
                
        except Exception as e:
            print(f"   ❌ 导入失败: {e}")
            failed_collections += 1
    
    print_section("导入结果汇总")
    print(f"✅ 成功导入: {success_collections} 个集合")
    print(f"❌ 导入失败: {failed_collections} 个集合")
    print(f"📈 总记录数: {total_imported:,} 条")
    
    client.close()
    return True

def verify_import():
    """验证导入结果"""
    print_section("4. 导入验证")
    
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        
        collections = db.list_collection_names()
        print(f"✅ 数据库中共有 {len(collections)} 个集合")
        
        # 按域统计
        domain_stats = defaultdict(list)
        for coll_name in sorted(collections):
            if coll_name.startswith('dwd_'):
                count = db[coll_name].count_documents({})
                
                # 判断域
                if 'ast' in coll_name:
                    domain_stats['资产域'].append((coll_name, count))
                elif 'cust' in coll_name:
                    domain_stats['客户域'].append((coll_name, count))
                elif 'isr' in coll_name:
                    domain_stats['主体域'].append((coll_name, count))
                elif 'mkt' in coll_name:
                    domain_stats['行情域'].append((coll_name, count))
                elif 'ptl' in coll_name:
                    domain_stats['产品域'].append((coll_name, count))
                elif 'val' in coll_name:
                    domain_stats['估值域'].append((coll_name, count))
                elif 'trn' in coll_name:
                    domain_stats['交易域'].append((coll_name, count))
                elif 'rsk' in coll_name:
                    domain_stats['风险域'].append((coll_name, count))
                elif 'sls' in coll_name:
                    domain_stats['销售域'].append((coll_name, count))
        
        for domain, tables in domain_stats.items():
            if tables:
                print(f"\n{domain}:")
                domain_total = 0
                for table_name, count in tables:
                    print(f"  - {table_name}: {count:,} 条")
                    domain_total += count
                print(f"  小计: {domain_total:,} 条")
        
        # 样例查询
        print_section("样例数据查询")
        sample_collections = ['dwd_ast_info', 'dwd_cust_info', 'dwd_mkt_stock', 'dwd_ptl_info']
        
        for coll_name in sample_collections:
            if coll_name in collections:
                doc = db[coll_name].find_one()
                if doc:
                    # 移除内部字段
                    display_doc = {k: v for k, v in doc.items() if not k.startswith('_') and k not in ['etl_dt', 'src_sys', 'created_at', 'updated_at']}
                    print(f"\n{coll_name} 样例:")
                    print(f"  {json.dumps(display_doc, ensure_ascii=False, indent=2)[:200]}...")
        
        client.close()
        return True
        
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        return False

def main():
    print("="*80)
    print("  ZY 数据域真实业务数据校验与导入工具")
    print(f"  数据源: {DATA_DIR}")
    print(f"  目标库: {MONGO_URI}/{DB_NAME}")
    print("="*80)
    
    # 1. 检查文件结构
    if not check_file_structure():
        print("\n❌ 文件结构检查失败，终止执行")
        return
    
    # 2. 验证数据
    validation_results = validate_all_data()
    
    # 3. 导入到 MongoDB
    if not import_to_mongodb(validation_results):
        print("\n❌ 导入失败，终止执行")
        return
    
    # 4. 验证导入结果
    verify_import()
    
    print_section("✅ 全部完成")
    print("数据已导入 MongoDB，前端应可正常访问")
    print("前端 API: GET /api/v1/zy-data/{collection}?page=1&pageSize=20")
    print("示例: GET /api/v1/zy-data/dwd_ast_info?page=1&pageSize=10")

if __name__ == "__main__":
    main()
