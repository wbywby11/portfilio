"""
MongoDB 字段对齐验证脚本 - 验证修复后的实际数据库状态
（与 deep_field_audit.py 不同，本脚本直接审计 MongoDB 而非源 JSON 文件）
"""
import re
from pathlib import Path
from collections import OrderedDict
from pymongo import MongoClient

PROJECT_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = PROJECT_ROOT / "src" / "config" / "zyDataDomain"
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"
OUTPUT_REPORT = PROJECT_ROOT / "docs" / "ZY_DATA_MONGO_AUDIT_REPORT.md"

AUDIT_FIELDS = {'etl_dt', 'src_sys', '_id', 'created_at', 'updated_at',
                'DATA_TIME', 'DATA_DT', 'DATA_SRC', 'IMPORT_TYPE'}


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
                if depth == 0: end = i+1; break
        block = content[m.start():end]
        keys = re.findall(r"f\(\s*'([A-Z0-9_]+)'", block)
        tables[name] = {'label': label, 'keys': keys}
    return tables


def main():
    schemas = OrderedDict()
    for p in sorted(SCHEMA_DIR.glob("[0-9]*.js")):
        schemas.update(parse_schema_file(p))

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[DB_NAME]
    existing = set(db.list_collection_names())

    stats = {'ok': [], 'partial': [], 'critical': [], 'no_data': [], 'empty_field': []}
    rows = []

    for tname, info in schemas.items():
        expected = set(info['keys'])
        if tname not in existing:
            stats['no_data'].append(tname)
            rows.append((tname, info['label'], '📭 无数据', len(expected), 0, [], 0))
            continue
        coll = db[tname]
        if coll.count_documents({}) == 0:
            stats['no_data'].append(tname)
            rows.append((tname, info['label'], '📭 集合为空', len(expected), 0, [], 0))
            continue

        # 采样字段
        actual = set()
        sample_n = 0
        null_count = {}
        for doc in coll.find({}, limit=80):
            sample_n += 1
            for k, v in doc.items():
                if k == '_id': continue
                actual.add(k)
                if v is None or v == '':
                    null_count[k] = null_count.get(k, 0) + 1

        missing = expected - actual
        # 高 null 率字段（>80%）
        high_null = [k for k in expected if null_count.get(k, 0) / sample_n > 0.8] if sample_n else []

        if not missing and not high_null:
            stats['ok'].append(tname); status = '✅ 对齐'
        elif not missing and high_null:
            stats['empty_field'].append(tname); status = '🟠 字段空值'
        elif len(missing) / max(len(expected), 1) >= 0.5:
            stats['critical'].append(tname); status = '❌ 严重缺失'
        else:
            stats['partial'].append(tname); status = '⚠️ 部分缺失'

        rows.append((tname, info['label'], status, len(expected), len(actual), sorted(missing), len(high_null)))

    # 生成报告
    lines = ['# ZY 数据域 MongoDB 字段对齐审计报告（修复后）\n']
    lines.append(f'- 审计时间: 2026-06-01')
    lines.append(f'- 数据库: `{MONGO_URI}/{DB_NAME}`\n')

    lines.append('## 一、对齐状态总览\n')
    lines.append('| 状态 | 数量 |')
    lines.append('|------|------|')
    lines.append(f'| ✅ 完全对齐 (ok) | **{len(stats["ok"])}** |')
    lines.append(f'| ⚠️ 部分缺失 (partial) | {len(stats["partial"])} |')
    lines.append(f'| ❌ 严重缺失 (critical) | {len(stats["critical"])} |')
    lines.append(f'| 🟠 字段空值率高 | {len(stats["empty_field"])} |')
    lines.append(f'| 📭 无数据 | {len(stats["no_data"])} |')
    lines.append(f'| **总计** | **{len(schemas)}** |\n')

    lines.append('## 二、各表详细\n')
    lines.append('| 表名 | 中文 | 状态 | 期望字段数 | 实际字段数 | 缺失字段 |')
    lines.append('|------|------|------|----------|----------|---------|')
    for r in rows:
        miss_str = ', '.join(f'`{k}`' for k in r[5][:6])
        if len(r[5]) > 6: miss_str += f', ... 等{len(r[5])}个'
        lines.append(f'| `{r[0]}` | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {miss_str or "—"} |')

    OUTPUT_REPORT.write_text('\n'.join(lines), encoding='utf-8')

    print('=' * 60)
    print(f'  ✅ 完全对齐: {len(stats["ok"])}')
    print(f'  ⚠️  部分缺失: {len(stats["partial"])}')
    print(f'  ❌ 严重缺失: {len(stats["critical"])}')
    print(f'  🟠 字段空值率高: {len(stats["empty_field"])}')
    print(f'  📭 无数据: {len(stats["no_data"])}')
    print(f'  共 {len(schemas)} 张表')
    print(f'\n  报告: {OUTPUT_REPORT}')
    if stats['critical']:
        print(f'\n  ❌ 严重缺失表: {stats["critical"][:5]}{"..." if len(stats["critical"])>5 else ""}')
    if stats['partial']:
        print(f'  ⚠️  部分缺失表: {stats["partial"]}')
    client.close()


if __name__ == '__main__':
    main()
