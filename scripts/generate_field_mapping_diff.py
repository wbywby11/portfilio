"""
前端配置与Mock数据字段差异对比脚本
- 从前端配置JS文件中提取表名和字段定义
- 从Mock JSON文件中提取实际字段
- 逐表对比，生成完整映射清单
"""

import os
import re
import json
from pathlib import Path
from difflib import SequenceMatcher

# ============ 配置 ============
CONFIG_DIR = r'd:\portfilio\src\config\zyDataDomain'
MOCK_DIR = r'C:\Users\wangb\.hermes\cache\mock_data_v2\output'
OUTPUT_FILE = r'd:\portfilio\scripts\field_mapping_diff.json'

# 审计字段 - 忽略
AUDIT_FIELDS = {'DATA_TIME', 'DATA_SRC', 'IMPORT_TYPE', '_id', 'etl_dt', 'src_sys'}

# ============ Step 1: 从前端配置提取字段 ============
def extract_tables_from_config(config_dir):
    """从01_asset.js ~ 09_market.js 提取表名和字段列表"""
    tables = {}
    
    # 读取所有01~09开头的JS文件
    js_files = sorted([
        f for f in os.listdir(config_dir) 
        if re.match(r'^0[1-9]_', f) and f.endswith('.js')
    ])
    
    for js_file in js_files:
        filepath = os.path.join(config_dir, js_file)
        with open(filepath, 'r', encoding='utf-8') as fh:
            content = fh.read()
        
        # 提取所有 T('table_name', ...) 调用中的表名和字段
        # 策略：找到所有 T( 调用，提取表名，然后在对应区域提取 f( 调用的第一个参数
        
        # 方法1：匹配 T('table_name', 'label', [...], [...]) 模式
        # 找所有 T( 起始位置
        t_pattern = re.compile(r"T\(\s*'([^']+)'\s*,\s*'[^']*'\s*,\s*\[")
        
        matches = list(t_pattern.finditer(content))
        
        for i, match in enumerate(matches):
            table_name = match.group(1)
            start_pos = match.end()
            
            # 找到这个T(...)调用的结束位置 - 寻找匹配的括号
            # 从 T( 的开始位置找到对应的闭合括号
            t_start = match.start()
            # 找到对应的整个T(...)块
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                end_pos = len(content)
            
            block = content[t_start:end_pos]
            
            # 在block中提取所有 f('FIELD_NAME', ...) 的第一个参数
            field_pattern = re.compile(r"f\(\s*'([^']+)'")
            fields = field_pattern.findall(block)
            
            if fields:
                tables[table_name] = fields
    
    return tables


# ============ Step 2: 从Mock数据提取字段 ============
def extract_fields_from_mock(mock_dir):
    """从mock JSON文件中提取字段列表"""
    tables = {}
    
    json_files = [f for f in os.listdir(mock_dir) if f.startswith('dwd_') and f.endswith('.json')]
    
    for json_file in json_files:
        table_name = json_file.replace('.json', '')
        filepath = os.path.join(mock_dir, json_file)
        
        try:
            with open(filepath, 'r', encoding='utf-8') as fh:
                # 只读取前面一部分来提取第一条记录的字段
                content = fh.read(50000)  # 读取前50KB足够获取第一条记录
            
            data = json.loads(content if content.rstrip().endswith(']') else content + ']')
            
            if isinstance(data, list) and len(data) > 0:
                # 合并前几条记录的字段（有些记录可能有可选字段）
                all_fields = set()
                for record in data[:5]:
                    if isinstance(record, dict):
                        all_fields.update(record.keys())
                tables[table_name] = list(all_fields)
            elif isinstance(data, dict):
                tables[table_name] = list(data.keys())
        except json.JSONDecodeError:
            # 文件可能太大，截断后无法解析，尝试逐行读取
            try:
                with open(filepath, 'r', encoding='utf-8') as fh:
                    first_chunk = fh.read(100000)
                # 找第一个完整的对象
                brace_start = first_chunk.find('{')
                if brace_start >= 0:
                    depth = 0
                    brace_end = -1
                    for idx in range(brace_start, len(first_chunk)):
                        if first_chunk[idx] == '{':
                            depth += 1
                        elif first_chunk[idx] == '}':
                            depth -= 1
                            if depth == 0:
                                brace_end = idx
                                break
                    if brace_end > 0:
                        obj_str = first_chunk[brace_start:brace_end + 1]
                        obj = json.loads(obj_str)
                        tables[table_name] = list(obj.keys())
            except Exception:
                print(f"  [WARN] 无法解析: {json_file}")
        except Exception as e:
            print(f"  [WARN] 读取失败 {json_file}: {e}")
    
    return tables


# ============ Step 3: 字段相似度推测 ============
def compute_similarity(s1, s2):
    """计算两个字段名的相似度"""
    # 完全相同
    if s1 == s2:
        return 1.0
    
    s1_upper = s1.upper()
    s2_upper = s2.upper()
    
    if s1_upper == s2_upper:
        return 0.95
    
    # 使用 SequenceMatcher
    ratio = SequenceMatcher(None, s1_upper, s2_upper).ratio()
    
    # 额外启发式：缩写匹配
    # 如 AST_NAME -> AST_NM, LIST_DATE -> LIST_DT, MATURITY_DT -> MDATE
    abbreviation_pairs = {
        'NAME': 'NM', 'DATE': 'DT', 'NUMBER': 'NO', 'AMOUNT': 'AMT',
        'QUANTITY': 'QTY', 'PRICE': 'PRC', 'VOLUME': 'VOL',
        'INSTITUTION': 'INST', 'CUSTOMER': 'CUST', 'PRODUCT': 'PTL',
        'PORTFOLIO': 'PORT', 'DESCRIPTION': 'DESC', 'INDUSTRY': 'IND',
        'MATURITY': 'MAT', 'CURRENCY': 'CCY', 'RETURN': 'RTN',
        'EXCHANGE': 'EXCH', 'MARKET': 'MKT', 'RATING': 'RTG',
        'ACCOUNT': 'ACCT', 'BALANCE': 'BAL', 'ISSUER': 'ISR',
        'COUNTERPART': 'CNTP', 'TRANSACTION': 'TRN', 'VALUATION': 'VAL',
        'ABBREVIATION': 'ABBR', 'INFORMATION': 'INFO', 'MANAGER': 'MGR',
    }
    
    # 尝试替换缩写后再比较
    s1_expanded = s1_upper
    s2_expanded = s2_upper
    for full, abbr in abbreviation_pairs.items():
        s1_expanded = s1_expanded.replace(abbr, full)
        s2_expanded = s2_expanded.replace(abbr, full)
    
    expanded_ratio = SequenceMatcher(None, s1_expanded, s2_expanded).ratio()
    
    return max(ratio, expanded_ratio)


def find_possible_renames(only_in_config, only_in_mock, threshold=0.55):
    """在配置独有和mock独有字段之间寻找可能的重命名映射"""
    renames = {}
    used_config = set()
    
    # 计算所有对的相似度
    pairs = []
    for mock_field in only_in_mock:
        for config_field in only_in_config:
            sim = compute_similarity(mock_field, config_field)
            if sim >= threshold:
                pairs.append((sim, mock_field, config_field))
    
    # 按相似度从高到低排序，贪心匹配
    pairs.sort(reverse=True)
    used_mock = set()
    
    for sim, mock_field, config_field in pairs:
        if mock_field not in used_mock and config_field not in used_config:
            renames[mock_field] = config_field
            used_mock.add(mock_field)
            used_config.add(config_field)
    
    return renames


# ============ Step 4: 主逻辑 ============
def main():
    print("=" * 60)
    print("前端配置 vs Mock数据 字段差异对比")
    print("=" * 60)
    
    # Step 1: 提取前端配置
    print("\n[Step 1] 从前端配置提取字段定义...")
    config_tables = extract_tables_from_config(CONFIG_DIR)
    print(f"  已提取 {len(config_tables)} 张配置表")
    
    # Step 2: 提取Mock数据
    print("\n[Step 2] 从Mock数据提取字段...")
    mock_tables = extract_fields_from_mock(MOCK_DIR)
    print(f"  已提取 {len(mock_tables)} 个Mock文件")
    
    # Step 3: 逐表对比
    print("\n[Step 3] 逐表对比字段...")
    
    config_names = set(config_tables.keys())
    mock_names = set(mock_tables.keys())
    
    both = config_names & mock_names
    config_only = config_names - mock_names
    mock_only = mock_names - config_names
    
    result = {
        "summary": {
            "total_config_tables": len(config_tables),
            "total_mock_files": len(mock_tables),
            "tables_with_both": len(both),
            "tables_config_only": len(config_only),
            "tables_mock_only": len(mock_only),
            "config_only_list": sorted(list(config_only)),
            "mock_only_list": sorted(list(mock_only))
        },
        "tables": {}
    }
    
    tables_with_diff = 0
    all_renames = {}  # 全局重命名汇总
    
    for table_name in sorted(both):
        config_fields = config_tables[table_name]
        mock_fields_raw = mock_tables[table_name]
        
        # 过滤审计字段
        mock_fields = [f for f in mock_fields_raw if f not in AUDIT_FIELDS]
        
        config_set = set(config_fields)
        mock_set = set(mock_fields)
        
        matched = sorted(list(config_set & mock_set))
        only_config = sorted(list(config_set - mock_set))
        only_mock = sorted(list(mock_set - config_set))
        
        # 推测重命名
        possible_rename = find_possible_renames(only_config, only_mock)
        
        has_diff = bool(only_config) or bool(only_mock)
        if has_diff:
            tables_with_diff += 1
        
        # 收集全局重命名
        for mock_f, config_f in possible_rename.items():
            key = f"{mock_f} -> {config_f}"
            if key not in all_renames:
                all_renames[key] = []
            all_renames[key].append(table_name)
        
        result["tables"][table_name] = {
            "config_fields": config_fields,
            "mock_fields": mock_fields,
            "matched": matched,
            "only_in_config": only_config,
            "only_in_mock": only_mock,
            "possible_rename": possible_rename,
            "match_rate": f"{len(matched)}/{len(config_set)}" if config_set else "N/A"
        }
    
    result["summary"]["tables_with_field_diff"] = tables_with_diff
    result["summary"]["all_possible_renames"] = all_renames
    
    # Step 4: 保存结果
    print(f"\n[Step 4] 保存结果到: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("  保存完成!")
    
    # Step 5: 打印摘要
    print("\n" + "=" * 60)
    print("摘要")
    print("=" * 60)
    print(f"  配置表总数: {len(config_tables)}")
    print(f"  Mock文件总数: {len(mock_tables)}")
    print(f"  两边都有的表: {len(both)}")
    print(f"  仅配置中有的表: {len(config_only)}")
    if config_only:
        for t in sorted(config_only):
            print(f"    - {t}")
    print(f"  仅Mock中有的表: {len(mock_only)}")
    if mock_only:
        for t in sorted(mock_only):
            print(f"    - {t}")
    print(f"\n  有字段差异的表: {tables_with_diff}/{len(both)}")
    
    # 打印各表匹配率
    print("\n--- 各表字段匹配情况 ---")
    for table_name in sorted(both):
        info = result["tables"][table_name]
        matched_cnt = len(info["matched"])
        config_cnt = len(info["config_fields"])
        mock_cnt = len(info["mock_fields"])
        only_c = len(info["only_in_config"])
        only_m = len(info["only_in_mock"])
        if only_c > 0 or only_m > 0:
            print(f"  {table_name}: matched={matched_cnt}, only_config={only_c}, only_mock={only_m}")
    
    # 打印所有可能的重命名映射
    if all_renames:
        print(f"\n--- 可能的重命名映射 ({len(all_renames)}项) ---")
        for rename_key in sorted(all_renames.keys()):
            tables = all_renames[rename_key]
            print(f"  {rename_key}  (出现在: {', '.join(tables[:3])}{'...' if len(tables) > 3 else ''})")
    else:
        print("\n  没有发现可能的重命名映射")
    
    print(f"\n结果已保存至: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
