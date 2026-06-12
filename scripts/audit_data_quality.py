"""
ZY 数据真实度审计 - 识别占位数据与空字段
判定规则:
1. 字符串字段值匹配占位模式 (如 "经理_05", "资产_0088", "IND123" 等) 视为占位
2. 字符串字段为空 ('') 视为空值
3. 同一字段所有记录值相同 (如全部 'Y' 或全部 0) 视为可疑均一值
"""
import re
from pathlib import Path
from collections import OrderedDict, Counter
from pymongo import MongoClient

PROJECT_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = PROJECT_ROOT / "src" / "config" / "zyDataDomain"
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"
OUTPUT_REPORT = PROJECT_ROOT / "docs" / "ZY_DATA_QUALITY_AUDIT.md"

# 占位字符串模式 (我们之前 fill_empty_fields 用的拼接格式)
PLACEHOLDER_PATTERNS = [
    re.compile(r'^[\u4e00-\u9fa5]+_\d{3,4}$'),       # 资产_0001, 经理_05
    re.compile(r'^[A-Z_]+_\d{3,}$'),                  # AST_NM_001, FOO_001
    re.compile(r'^IND\d{3}$'),                        # IND123
    re.compile(r'^user\d+@example\.com$'),            # user1@example.com
    re.compile(r'^138\d{8}$'),                        # 138xxxxxxxx 假手机
    re.compile(r'^1101\d{12}$'),                      # 假身份证
    re.compile(r'^系统填充$'),
    re.compile(r'^常规调整$'),
    re.compile(r'^MOCK'),
]


def parse_schema_file(p):
    content = p.read_text(encoding='utf-8')
    tables = OrderedDict()
    for m in re.finditer(r"T\(\s*'([a-zA-Z_]+)'\s*,\s*'([^']+)'", content):
        name, label = m.group(1), m.group(2)
        depth = 0
        end = m.start()
        for i, ch in enumerate(content[m.start():], m.start()):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        block = content[m.start():end]
        fields = []
        for fm in re.finditer(r"f\(\s*'([A-Z0-9_]+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'", block):
            fields.append({'key': fm.group(1), 'label': fm.group(2), 'type': fm.group(3)})
        tables[name] = {'label': label, 'fields': fields}
    return tables


def is_placeholder(v):
    if not isinstance(v, str):
        return False
    s = v.strip()
    if not s:
        return False
    for p in PLACEHOLDER_PATTERNS:
        if p.match(s):
            return True
    return False


def main():
    schemas = OrderedDict()
    for p in sorted(SCHEMA_DIR.glob("[0-9]*.js")):
        schemas.update(parse_schema_file(p))

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    existing = set(db.list_collection_names())

    table_issues = OrderedDict()
    domain_summary = Counter()

    for tname, info in schemas.items():
        if tname not in existing:
            continue
        coll = db[tname]
        total = coll.count_documents({})
        if total == 0:
            continue

        sample_n = min(total, 100)
        docs = list(coll.find({}, limit=sample_n))

        issues = {
            'total_docs': total,
            'sample': sample_n,
            'placeholder_fields': {},   # field -> count
            'empty_fields': {},          # field -> count
            'uniform_fields': {},        # field -> single_value
            'missing_fields': [],
        }

        expected_keys = [f['key'] for f in info['fields']]
        actual_keys_seen = set()
        for d in docs:
            actual_keys_seen.update(d.keys())

        # 缺失字段
        for k in expected_keys:
            if k not in actual_keys_seen:
                issues['missing_fields'].append(k)

        # 逐字段检测占位/空/均一
        for k in expected_keys:
            if k not in actual_keys_seen:
                continue
            values = [d.get(k) for d in docs]
            ph_cnt = sum(1 for v in values if is_placeholder(v))
            empty_cnt = sum(1 for v in values if v is None or v == '')
            unique_vals = set(str(v) for v in values if v is not None and v != '')

            if ph_cnt / sample_n > 0.5:
                issues['placeholder_fields'][k] = ph_cnt
            if empty_cnt / sample_n > 0.5:
                issues['empty_fields'][k] = empty_cnt
            if len(unique_vals) == 1 and sample_n >= 5 and empty_cnt == 0:
                only = list(unique_vals)[0]
                # 排除合理的均一值 (主键池里的固定值/Y/N 这些)
                if only not in ('Y', 'N', 'CNY', 'ACTIVE', '20250324', '2025-03-24'):
                    issues['uniform_fields'][k] = only

        if issues['placeholder_fields'] or issues['empty_fields'] or issues['missing_fields']:
            table_issues[tname] = issues
            # 域统计 (前缀提取)
            domain_key = tname.split('_')[1] if '_' in tname else 'other'
            domain_summary[domain_key] += 1

    # ===== 生成报告 =====
    lines = ['# ZY 数据域数据真实度审计报告\n']
    lines.append('## 一、判定规则\n')
    lines.append('- **占位字段**: 字段值匹配 `资产_0001` / `经理_05` / `IND123` / `138xxxxxxxx` 等模式，>50% 记录命中视为占位字段')
    lines.append('- **空字段**: 字段值为 `null`/`""`，>50% 记录视为空字段')
    lines.append('- **均一字段**: 所有非空记录值完全一致（排除合理常量），可能是占位\n')

    lines.append('## 二、按业务域问题分布\n')
    lines.append('| 域 | 问题表数 |')
    lines.append('|------|------|')
    for k, v in sorted(domain_summary.items(), key=lambda x: -x[1]):
        lines.append(f'| {k} | {v} |')
    lines.append('')

    lines.append(f'## 三、问题表清单（共 {len(table_issues)} 张）\n')
    lines.append('| 表名 | 中文 | 占位字段 | 空字段 | 缺失字段 | 均一字段 |')
    lines.append('|------|------|--------|------|--------|--------|')
    for tname, iss in table_issues.items():
        label = schemas.get(tname, {}).get('label', '')
        ph = ', '.join(f'`{k}`' for k in iss['placeholder_fields']) or '—'
        em = ', '.join(f'`{k}`' for k in iss['empty_fields']) or '—'
        ms = ', '.join(f'`{k}`' for k in iss['missing_fields']) or '—'
        un = ', '.join(f'`{k}`' for k in iss['uniform_fields']) or '—'
        lines.append(f'| `{tname}` | {label} | {ph} | {em} | {ms} | {un} |')
    lines.append('')

    lines.append('## 四、各表详细字段问题\n')
    for tname, iss in table_issues.items():
        if not (iss['placeholder_fields'] or iss['empty_fields'] or iss['uniform_fields']):
            continue
        label = schemas.get(tname, {}).get('label', '')
        lines.append(f'### `{tname}` - {label} (共 {iss["total_docs"]} 条)\n')
        if iss['placeholder_fields']:
            lines.append('**占位字段:**')
            for k, c in iss['placeholder_fields'].items():
                lines.append(f'- `{k}`: {c}/{iss["sample"]} 条命中占位模式')
            lines.append('')
        if iss['empty_fields']:
            lines.append('**空字段:**')
            for k, c in iss['empty_fields'].items():
                lines.append(f'- `{k}`: {c}/{iss["sample"]} 条为空')
            lines.append('')
        if iss['uniform_fields']:
            lines.append('**均一值字段:**')
            for k, v in iss['uniform_fields'].items():
                lines.append(f'- `{k}`: 全部为 `{v}`')
            lines.append('')

    OUTPUT_REPORT.write_text('\n'.join(lines), encoding='utf-8')

    print('=' * 60)
    print(f'  问题表数: {len(table_issues)}')
    print(f'  报告: {OUTPUT_REPORT}')
    print('=' * 60)
    print('  按问题类型分布:')
    ph_total = sum(len(i['placeholder_fields']) for i in table_issues.values())
    em_total = sum(len(i['empty_fields']) for i in table_issues.values())
    ms_total = sum(len(i['missing_fields']) for i in table_issues.values())
    un_total = sum(len(i['uniform_fields']) for i in table_issues.values())
    print(f'    占位字段总数: {ph_total}')
    print(f'    空字段总数: {em_total}')
    print(f'    缺失字段总数: {ms_total}')
    print(f'    均一字段总数: {un_total}')
    print()
    print('  按域分布:')
    for k, v in sorted(domain_summary.items(), key=lambda x: -x[1]):
        print(f'    {k}: {v} 张表有问题')

    client.close()


if __name__ == '__main__':
    main()
