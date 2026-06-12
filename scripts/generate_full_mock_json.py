#!/usr/bin/env python3
"""
从 zyDataDomain.mock.js 提取完整的 REALISTIC_SEEDS 数据

读取第 73-897 行的内容，转换为 JSON 格式
"""

import json
import re
from pathlib import Path

MOCK_JS_PATH = Path("d:/portfilio/src/api/zyDataDomain.mock.js")
OUTPUT_PATH = Path("d:/portfilio/scripts/zy_data_domain_seeds_full.json")

def main():
    print("读取 mock.js 文件...")
    
    with open(MOCK_JS_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # 提取第 73-897 行（索引 72-896）
    js_content = ''.join(lines[72:897])
    
    print(f"提取 JS 内容（{len(js_content)} 字符）")
    
    # 转换 JS 对象为 JSON
    # 1. 移除注释
    js_content = re.sub(r'//.*$', '', js_content, flags=re.MULTILINE)
    
    # 2. 移除尾随逗号
    js_content = re.sub(r',\s*}', '}', js_content)
    js_content = re.sub(r',\s*\]', ']', js_content)
    
    # 3. 转换单引号为双引号
    # 属性名
    js_content = re.sub(r'(\w+):', r'"\1":', js_content)
    # 字符串值
    js_content = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', js_content)
    
    print("转换 JS 语法为 JSON...")
    
    # 解析 JSON
    data = json.loads(js_content)
    
    print(f"\n✓ JSON 解析成功！")
    print(f"集合数量: {len(data)}")
    
    total = 0
    for name, records in data.items():
        count = len(records) if isinstance(records, list) else 0
        total += count
        print(f"  {name}: {count} 条")
    
    print(f"\n总记录数: {total}")
    
    # 保存
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ 已保存到: {OUTPUT_PATH}")
    print(f"文件大小: {OUTPUT_PATH.stat().st_size / 1024:.2f} KB")


if __name__ == "__main__":
    main()
