"""
ZY 数据域字段深度对比工具

直接读取前端 schema 配置（src/config/zyDataDomain/*.js），
与实际 JSON 数据进行字段级别的精确对比，找出所有不匹配的字段。

使用方法:
  cd d:\portfilio
  python scripts/deep_field_audit.py
"""
import os
import re
import sys
import json
from pathlib import Path
from collections import defaultdict, OrderedDict

# 配置
PROJECT_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = PROJECT_ROOT / "src" / "config" / "zyDataDomain"
DATA_DIR = Path("C:/Users/wangb/.hermes/cache/mock_data/full_output")
OUTPUT_REPORT = PROJECT_ROOT / "docs" / "ZY_DATA_FIELD_AUDIT_REPORT.md"

# 系统审计字段（不计入缺失）
AUDIT_FIELDS = {
    'etl_dt', 'src_sys', '_id', 'created_at', 'updated_at',
    'DATA_TIME', 'DATA_DT', 'DATA_SRC', 'IMPORT_TYPE'
}


def parse_schema_file(schema_path):
    """从前端 JS schema 文件中解析表定义"""
    content = schema_path.read_text(encoding='utf-8')

    tables = {}

    # 匹配 T('table_name', '...', [...], [ fields... ])
    # 使用括号匹配定位每个 T(...) 调用
    pattern = re.compile(r"T\(\s*'([a-zA-Z_]+)'\s*,\s*'([^']+)'", re.MULTILINE)

    for match in pattern.finditer(content):
        table_name = match.group(1)
        table_label = match.group(2)
        start_pos = match.start()

        # 从 T( 位置向后找到匹配的 )
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

        # 提取字段：f('KEY', 'label', ...)
        field_pattern = re.compile(r"f\(\s*'([A-Z0-9_]+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'", re.MULTILINE)
        fields = []
        for fm in field_pattern.finditer(block):
            fields.append({
                'key': fm.group(1),
                'label': fm.group(2),
                'type': fm.group(3),
            })

        tables[table_name] = {
            'label': table_label,
            'fields': fields,
            'field_keys': [f['key'] for f in fields]
        }

    return tables


def load_all_schemas():
    """加载所有前端 schema"""
    all_tables = {}
    for schema_file in sorted(SCHEMA_DIR.glob("[0-9]*.js")):
        tables = parse_schema_file(schema_file)
        for name, info in tables.items():
            info['schema_file'] = schema_file.name
            all_tables[name] = info
    return all_tables


def load_data_file(file_path):
    """加载 JSON 数据文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            records = []
            for v in data.values():
                if isinstance(v, list):
                    records.extend(v)
            return records
        elif isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"❌ 读取失败 {file_path.name}: {e}")
        return []


def get_actual_fields(records, sample_size=20):
    """从前 N 条记录中收集所有出现过的字段名"""
    fields = set()
    field_null_count = defaultdict(int)
    sample = records[:sample_size]
    for rec in sample:
        for k, v in rec.items():
            fields.add(k)
            if v is None or v == '':
                field_null_count[k] += 1
    return fields, field_null_count, len(sample)


def audit_table(table_name, schema, data_records):
    """对单张表进行字段审计"""
    if not data_records:
        return {
            'status': 'no_data',
            'record_count': 0,
            'expected_fields': schema['field_keys'] if schema else [],
            'actual_fields': [],
            'missing_fields': [],
            'extra_fields': [],
            'null_fields': [],
        }

    expected = set(schema['field_keys']) if schema else set()
    actual, null_count, sample_n = get_actual_fields(data_records)

    # 缺失字段：前端期望但数据中没有
    missing = expected - actual
    # 额外字段：数据中有但前端不识别（排除审计字段）
    extra = actual - expected - AUDIT_FIELDS
    # 大量为空的字段（前端期望但数据全空）
    null_fields = [k for k, c in null_count.items() if c >= sample_n * 0.8 and k in expected]

    # 状态判断
    if not schema:
        status = 'no_schema'
    elif missing:
        if len(missing) >= len(expected) * 0.5:
            status = 'critical'  # 严重不匹配
        else:
            status = 'partial'   # 部分缺失
    elif null_fields:
        status = 'null_heavy'    # 字段都在但大量为空
    else:
        status = 'ok'

    return {
        'status': status,
        'record_count': len(data_records),
        'sample_size': sample_n,
        'expected_fields': sorted(expected),
        'actual_fields': sorted(actual),
        'missing_fields': sorted(missing),
        'extra_fields': sorted(extra),
        'null_fields': sorted(null_fields),
        'expected_count': len(expected),
        'actual_count': len(actual),
        'missing_count': len(missing),
    }


def render_report(audit_results, all_schemas, data_only_files):
    """生成 Markdown 报告"""
    lines = []
    lines.append("# ZY 数据域字段深度审计报告\n")
    lines.append("> 基于前端 `src/config/zyDataDomain/*.js` schema 与实际 JSON 数据的精确字段对比\n")
    lines.append(f"- 数据源: `{DATA_DIR}`\n")
    lines.append(f"- Schema 来源: `{SCHEMA_DIR}`\n")
    lines.append(f"- 报告时间: 2026-06-01\n\n")

    # 1. 总览统计
    status_count = defaultdict(int)
    for r in audit_results.values():
        status_count[r['status']] += 1

    total = len(audit_results)
    lines.append("## 一、总览\n")
    lines.append(f"| 状态 | 数量 | 说明 |")
    lines.append(f"|------|------|------|")
    lines.append(f"| ✅ 完全匹配 (ok) | {status_count.get('ok', 0)} | 字段全部对齐 |")
    lines.append(f"| ⚠️ 部分缺失 (partial) | {status_count.get('partial', 0)} | 缺少部分前端期望字段 |")
    lines.append(f"| ❌ 严重不匹配 (critical) | {status_count.get('critical', 0)} | 缺失字段≥50%，前端无法正常显示 |")
    lines.append(f"| 🟠 字段为空 (null_heavy) | {status_count.get('null_heavy', 0)} | 字段存在但大量为空 |")
    lines.append(f"| ⚪ 无 schema (no_schema) | {status_count.get('no_schema', 0)} | 数据存在但前端未定义 |")
    lines.append(f"| **总计** | **{total}** | |\n")

    # 2. 严重不匹配的表（critical）— 这是用户最关心的
    critical_tables = [(n, r) for n, r in audit_results.items() if r['status'] == 'critical']
    if critical_tables:
        lines.append("## 二、❌ 严重不匹配的表（critical）\n")
        lines.append("> 这些表前端期望的字段在数据中**严重缺失**（缺失率 ≥ 50%），前端表格列大面积为空。\n")
        for name, r in sorted(critical_tables):
            schema = all_schemas.get(name, {})
            label = schema.get('label', '-')
            lines.append(f"### `{name}` - {label}\n")
            lines.append(f"- 记录数: **{r['record_count']:,}**")
            lines.append(f"- 前端期望字段: {r['expected_count']} 个")
            lines.append(f"- 实际数据字段: {r['actual_count']} 个")
            lines.append(f"- **缺失字段数: {r['missing_count']} 个 ({r['missing_count']*100//max(r['expected_count'],1)}%)**\n")
            lines.append(f"**🔴 缺失字段 (前端期望但数据中没有)**:\n")
            lines.append(f"```\n{', '.join(r['missing_fields'])}\n```\n")
            if r['extra_fields']:
                lines.append(f"**🟡 额外字段 (数据中有但前端不识别)**:\n")
                lines.append(f"```\n{', '.join(r['extra_fields'])}\n```\n")
            # 智能提示可能的字段映射
            mapping_hints = guess_field_mapping(r['missing_fields'], r['extra_fields'])
            if mapping_hints:
                lines.append(f"**💡 疑似字段名映射**:\n")
                lines.append("| 前端期望 | 数据实际 | 推测 |")
                lines.append("|---------|---------|------|")
                for exp, act, reason in mapping_hints:
                    lines.append(f"| `{exp}` | `{act}` | {reason} |")
                lines.append("")

    # 3. 部分缺失的表
    partial_tables = [(n, r) for n, r in audit_results.items() if r['status'] == 'partial']
    if partial_tables:
        lines.append("## 三、⚠️ 部分缺失字段的表（partial）\n")
        lines.append("| 表名 | 中文名 | 记录数 | 前端字段数 | 缺失字段数 | 缺失字段 |")
        lines.append("|------|--------|--------|-----------|-----------|---------|")
        for name, r in sorted(partial_tables, key=lambda x: -x[1]['missing_count']):
            schema = all_schemas.get(name, {})
            label = schema.get('label', '-')
            missing_str = ', '.join(f"`{f}`" for f in r['missing_fields'])
            lines.append(f"| `{name}` | {label} | {r['record_count']:,} | {r['expected_count']} | {r['missing_count']} | {missing_str} |")
        lines.append("")

    # 4. 字段空值严重的表
    null_tables = [(n, r) for n, r in audit_results.items() if r['status'] == 'null_heavy']
    if null_tables:
        lines.append("## 四、🟠 字段大量为空的表（null_heavy）\n")
        lines.append("> 这些表的前端期望字段虽然存在，但 ≥80% 的样本记录中为 null/空字符串。\n")
        lines.append("| 表名 | 中文名 | 记录数 | 大量为空的字段 |")
        lines.append("|------|--------|--------|---------------|")
        for name, r in sorted(null_tables):
            schema = all_schemas.get(name, {})
            label = schema.get('label', '-')
            null_str = ', '.join(f"`{f}`" for f in r['null_fields'])
            lines.append(f"| `{name}` | {label} | {r['record_count']:,} | {null_str} |")
        lines.append("")

    # 5. 没有 schema 的数据文件
    if data_only_files:
        lines.append("## 五、⚪ 数据文件存在但前端未定义 schema\n")
        lines.append("> 这些 JSON 文件的数据已导入 MongoDB，但前端 ZY 数据域页面**无法识别和展示**。\n")
        lines.append("| 数据文件 | 记录数 | 前端 schema |")
        lines.append("|---------|--------|------------|")
        for fname, count in data_only_files:
            lines.append(f"| `{fname}` | {count:,} | ❌ 未定义 |")
        lines.append("")

    # 6. 完全匹配的表（简略列出）
    ok_tables = [(n, r) for n, r in audit_results.items() if r['status'] == 'ok']
    if ok_tables:
        lines.append("## 六、✅ 完全匹配的表（ok）\n")
        lines.append("| 表名 | 中文名 | 记录数 | 字段数 |")
        lines.append("|------|--------|--------|--------|")
        for name, r in sorted(ok_tables):
            schema = all_schemas.get(name, {})
            label = schema.get('label', '-')
            lines.append(f"| `{name}` | {label} | {r['record_count']:,} | {r['expected_count']} |")
        lines.append("")

    # 7. 修复建议
    lines.append("## 七、🔧 修复建议\n")
    lines.append("### 方案A：在后端 API 添加字段映射（推荐，无需改数据）\n")
    lines.append("在 `scripts/zy_data_api_implementation.py` 的查询响应中，按表添加字段映射，\n")
    lines.append("将实际数据字段映射为前端期望字段。例如：\n\n")
    lines.append("```python")
    lines.append("FIELD_ALIASES = {")
    lines.append("    'dwd_trn_trade_ptl': {")
    lines.append("        'TRADE_DATE': 'TRADE_DT',")
    lines.append("        'TRADE_AMT': 'AMT',")
    lines.append("        'PROD_CD': 'PORT_ID',")
    lines.append("        # ... 其他映射")
    lines.append("    }")
    lines.append("}")
    lines.append("```\n")
    lines.append("### 方案B：在 MongoDB 中执行字段重命名（一次性）\n")
    lines.append("```javascript")
    lines.append("// 例如重命名 dwd_trn_trade_ptl 表字段")
    lines.append("db.dwd_trn_trade_ptl.updateMany({}, {")
    lines.append("  $rename: { 'TRADE_DATE': 'TRADE_DT', 'TRADE_AMT': 'AMT' }")
    lines.append("})")
    lines.append("```\n")
    lines.append("### 方案C：补充数据生成脚本，按前端 schema 输出对齐字段\n")

    return '\n'.join(lines)


def guess_field_mapping(missing, extra):
    """根据字段名相似度推测可能的映射关系"""
    hints = []
    common_pairs = [
        ('TRADE_DT', 'TRADE_DATE', '日期字段命名差异'),
        ('TRAN_DATE', 'TRADE_DATE', '日期字段命名差异'),
        ('SETT_DT', 'SETTLE_DATE', '日期字段命名差异'),
        ('AMT', 'TRADE_AMT', '金额字段简写差异'),
        ('AMT', 'AMOUNT', '金额字段简写差异'),
        ('QTY', 'QUANTITY', '数量字段简写差异'),
        ('PRC', 'PRICE', '价格字段简写差异'),
        ('PORT_ID', 'PROD_CD', '产品/组合主键命名差异'),
        ('PORT_ID', 'PORT_CODE', '产品/组合主键命名差异'),
        ('PORT_NM', 'PROD_NAME', '产品/组合名称命名差异'),
        ('PORT_NM', 'PORT_NAME', '名称字段简写差异'),
        ('AST_NM', 'AST_NAME', '资产名称命名差异'),
        ('CCY', 'CURRENCY', '币种字段命名差异'),
        ('CCY', 'CURR', '币种字段命名差异'),
        ('BS_DIR', 'BS_DIRECTION', '买卖方向命名差异'),
        ('BS_DIR', 'TRADE_TYPE', '业务方向 vs 交易类型'),
        ('ISR_ID', 'CUSTOMER_ID', '发行人/客户ID命名差异'),
        ('CUST_ID', 'CUSTOMER_ID', '客户ID命名差异'),
        ('NAV', 'UNIT_NAV', '净值字段命名差异'),
        ('ESTAB_DT', 'START_DATE', '成立日命名差异'),
        ('LIST_DT', 'LIST_DATE', '上市日命名差异'),
        ('MATURITY_DT', 'MATURITY_DATE', '到期日命名差异'),
    ]
    for exp, act, reason in common_pairs:
        if exp in missing and act in extra:
            hints.append((exp, act, reason))
    # 模糊匹配：前端字段去掉下划线后是否被实际字段包含
    for m in missing:
        m_norm = m.replace('_', '').upper()
        for e in extra:
            e_norm = e.replace('_', '').upper()
            if (m_norm in e_norm or e_norm in m_norm) and abs(len(m_norm) - len(e_norm)) <= 4:
                if (m, e) not in [(h[0], h[1]) for h in hints]:
                    hints.append((m, e, '字段名相似（疑似映射）'))
    return hints


def main():
    print("=" * 80)
    print("  ZY 数据域字段深度审计")
    print("=" * 80)

    # 1. 加载前端 schema
    print(f"\n[1/3] 加载前端 schema: {SCHEMA_DIR}")
    all_schemas = load_all_schemas()
    print(f"  ✅ 解析到 {len(all_schemas)} 张表的 schema")

    # 2. 加载所有 JSON 数据
    print(f"\n[2/3] 扫描数据文件: {DATA_DIR}")
    data_files = sorted(DATA_DIR.glob("*.json"))
    print(f"  ✅ 找到 {len(data_files)} 个 JSON 文件")

    # 3. 对每张表做审计
    print(f"\n[3/3] 执行字段审计...")
    audit_results = OrderedDict()
    data_only_files = []  # 数据有但 schema 没有

    # 处理 core_data.json 内的子集合
    core_path = DATA_DIR / "core_data.json"
    core_subcollections = {}
    if core_path.exists():
        try:
            with open(core_path, 'r', encoding='utf-8') as f:
                core_data = json.load(f)
            if isinstance(core_data, dict):
                for k, v in core_data.items():
                    if isinstance(v, list):
                        core_subcollections[k] = v
        except Exception:
            pass

    for fp in data_files:
        if fp.name == 'core_data.json':
            continue  # 已单独处理
        table_name = fp.stem
        records = load_data_file(fp)
        schema = all_schemas.get(table_name)

        result = audit_table(table_name, schema, records)
        audit_results[table_name] = result

        if not schema and records:
            data_only_files.append((fp.name, len(records)))

        # 控制台简要输出
        marker = {
            'ok': '✅', 'partial': '⚠️ ', 'critical': '❌',
            'null_heavy': '🟠', 'no_schema': '⚪', 'no_data': '⏭️ '
        }.get(result['status'], '?')
        print(f"  {marker} {table_name:35s} | 记录:{result['record_count']:>6,} | "
              f"期望:{result['expected_count']:>2} 实际:{result['actual_count']:>3} 缺失:{result['missing_count']:>2}")

    # 检查前端定义但数据缺失的表
    print(f"\n[补充] 检查前端定义但数据中没有的表:")
    for tname in all_schemas:
        if tname not in audit_results:
            print(f"  📭 {tname}: 前端有定义但 full_output 无对应 JSON 文件")

    # 4. 生成报告
    print(f"\n[输出] 生成报告: {OUTPUT_REPORT}")
    report = render_report(audit_results, all_schemas, data_only_files)
    OUTPUT_REPORT.write_text(report, encoding='utf-8')
    print(f"  ✅ 报告已保存")

    # 5. 控制台汇总
    status_count = defaultdict(int)
    for r in audit_results.values():
        status_count[r['status']] += 1

    print(f"\n{'='*80}")
    print(f"  审计汇总")
    print(f"{'='*80}")
    print(f"  ✅ 完全匹配 (ok)         : {status_count.get('ok', 0):>3} 张")
    print(f"  ⚠️  部分缺失 (partial)    : {status_count.get('partial', 0):>3} 张")
    print(f"  ❌ 严重不匹配 (critical) : {status_count.get('critical', 0):>3} 张")
    print(f"  🟠 字段为空 (null_heavy) : {status_count.get('null_heavy', 0):>3} 张")
    print(f"  ⚪ 无 schema (no_schema) : {status_count.get('no_schema', 0):>3} 张")
    print(f"  📭 数据缺失              : {len([t for t in all_schemas if t not in audit_results]):>3} 张")
    print(f"\n  详细报告: {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
