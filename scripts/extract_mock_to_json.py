#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZY 数据域 Mock 数据提取工具
从 zyDataDomain.mock.js 提取 REALISTIC_SEEDS 并保存为 JSON
"""

import json
import re
from pathlib import Path

def extract_mock_data():
    js_path = Path("d:/portfilio/src/api/zyDataDomain.mock.js")
    output_path = Path("d:/portfilio/scripts/zy_data_domain_seeds_complete.json")
    
    print("读取 mock.js 文件...")
    with open(js_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 找到 REALISTIC_SEEDS = { 开始位置
    start_marker = "const REALISTIC_SEEDS = {"
    start = content.find(start_marker)
    if start == -1:
        print("错误：未找到 REALISTIC_SEEDS")
        return
    
    # 匹配对应的 };
    brace_count = 0
    in_string = False
    string_char = None
    end = None
    
    for i in range(start, len(content)):
        c = content[i]
        if c in ('"', "'") and (i == 0 or content[i-1] != '\\'):
            if not in_string:
                in_string = True
                string_char = c
            elif c == string_char:
                in_string = False
        
        if not in_string:
            if c == '{':
                brace_count += 1
            elif c == '}':
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break
    
    if end is None:
        print("错误：无法匹配结束括号")
        return
    
    js_code = content[start:end]
    print(f"提取到 JS 代码 ({len(js_code)} 字符)")
    
    # 转换为 JSON
    # 移除注释
    js_code = re.sub(r'//.*?$', '', js_code, flags=re.MULTILINE)
    # 移除尾随逗号
    js_code = re.sub(r',(\s*[}\]])', r'\1', js_code)
    # 转换单引号为双引号 - 属性名
    js_code = re.sub(r'(\w+)\s*:', r'"\1":', js_code)
    # 转换单引号字符串值
    js_code = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', js_code)
    
    print("转换 JS 语法为 JSON...")
    
    try:
        data = json.loads(js_code)
        print(f"\n✓ JSON 解析成功！")
        print(f"集合数量: {len(data)}")
        
        total_records = 0
        for name, records in data.items():
            count = len(records) if isinstance(records, list) else 0
            total_records += count
            print(f"  {name}: {count} 条")
        
        print(f"\n总记录数: {total_records}")
        
        # 保存
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        file_size = output_path.stat().st_size
        print(f"\n✓ 已保存到: {output_path}")
        print(f"文件大小: {file_size / 1024:.2f} KB ({file_size / 1024 / 1024:.2f} MB)")
        
    except json.JSONDecodeError as e:
        print(f"✗ JSON 解析失败: {e}")
        print(f"位置: 第 {e.lineno} 行, 第 {e.colno} 列")


if __name__ == "__main__":
    extract_mock_data()
