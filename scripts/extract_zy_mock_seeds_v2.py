#!/usr/bin/env python3
"""
提取 ZY 数据域 Mock 数据并保存为 JSON 文件

使用方法:
  cd d:\portfilio
  python scripts/extract_zy_mock_seeds_v2.py
"""

import json
import re
from pathlib import Path

# 文件路径
MOCK_JS_PATH = Path(__file__).parent.parent / "src" / "api" / "zyDataDomain.mock.js"
OUTPUT_JSON_PATH = Path(__file__).parent / "zy_data_domain_seeds.json"

def extract_seeds():
    """从 JS 文件中提取 REALISTIC_SEEDS 数据"""
    
    print("="*60)
    print("ZY 数据域 Mock 数据提取工具")
    print("="*60)
    print(f"\n读取文件: {MOCK_JS_PATH}")
    
    with open(MOCK_JS_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 查找 REALISTIC_SEEDS = { ... }; 的范围
    start_marker = 'const REALISTIC_SEEDS = {'
    start_idx = content.find(start_marker)
    
    if start_idx == -1:
        print("✗ 未找到 REALISTIC_SEEDS 定义")
        return None
    
    print(f"✓ 找到 REALISTIC_SEEDS 定义（位置: {start_idx}）")
    
    # 找到对应的结束位置
    # 从 start_idx 开始，计算 { 和 } 的匹配
    brace_count = 0
    in_string = False
    string_char = None
    end_idx = None
    
    for i in range(start_idx, len(content)):
        char = content[i]
        
        # 处理字符串
        if char in ('"', "'") and (i == 0 or content[i-1] != '\\'):
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False
        
        # 计算括号（仅在非字符串中）
        if not in_string:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i + 1
                    break
    
    if end_idx is None:
        print("✗ 无法找到匹配的结束括号")
        return None
    
    # 提取 JS 对象字符串
    js_object = content[start_idx + len(start_marker) - 1:end_idx]
    
    print(f"✓ 提取 JS 对象（长度: {len(js_object)} 字符）")
    
    # 转换为 JSON
    # 1. 移除注释
    js_object = re.sub(r'//.*$', '', js_object, flags=re.MULTILINE)
    js_object = re.sub(r'/\*.*?\*/', '', js_object, flags=re.DOTALL)
    
    # 2. 移除尾随逗号（对象和数组）
    js_object = re.sub(r',\s*}', '}', js_object)
    js_object = re.sub(r',\s*\]', ']', js_object)
    
    # 3. 将属性名和字符串值从单引号转为双引号
    # 属性名: { key:  →  { "key":
    js_object = re.sub(r'(\w+):', r'"\1":', js_object)
    
    # 字符串值: 'value' → "value"
    # 需要小心处理嵌套引号
    def replace_quotes(match):
        return match.group(0).replace("'", '"')
    
    # 匹配所有单引号字符串
    js_object = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', js_object)
    
    # 4. 移除多余的空白（可选）
    # js_object = re.sub(r'\s+', ' ', js_object)  # 这会破坏可读性，不使用
    
    print(f"✓ JS 语法转换完成")
    print(f"  正在解析为 JSON...")
    
    try:
        data = json.loads(js_object)
        print(f"✓ JSON 解析成功！")
        print(f"\n集合统计:")
        print(f"  集合数量: {len(data)}")
        
        total_records = 0
        for collection_name, records in data.items():
            count = len(records) if isinstance(records, list) else 0
            total_records += count
            print(f"  {collection_name}: {count} 条")
        
        print(f"\n  总记录数: {total_records}")
        
        return data
        
    except json.JSONDecodeError as e:
        print(f"✗ JSON 解析失败: {e}")
        print(f"\n错误位置: 第 {e.lineno} 行, 第 {e.colno} 列")
        print(f"错误上下文:")
        lines = js_object.split('\n')
        if e.lineno <= len(lines):
            for i in range(max(0, e.lineno - 3), min(len(lines), e.lineno + 2)):
                marker = ">>>" if i + 1 == e.lineno else "   "
                print(f"  {marker} {i+1}: {lines[i][:80]}")
        
        return None


def save_json(data, output_path):
    """保存为 JSON 文件"""
    
    print(f"\n保存到: {output_path}")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    file_size = output_path.stat().st_size
    print(f"✓ 保存成功！文件大小: {file_size / 1024:.2f} KB")
    
    return output_path


def main():
    # 提取数据
    data = extract_seeds()
    
    if data is None:
        print("\n✗ 提取失败")
        return
    
    # 保存文件
    save_json(data, OUTPUT_JSON_PATH)
    
    print(f"\n{'='*60}")
    print(f"✅ 完成！")
    print(f"输出文件: {OUTPUT_JSON_PATH}")
    print(f"{'='*60}")
    
    print(f"\n后续使用:")
    print(f"  1. 查看数据: cat {OUTPUT_JSON_PATH}")
    print(f"  2. 导入 MongoDB: python scripts/import_zy_data_domain_mock.py")
    print(f"  3. 提供给其他 AI 分析")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ 出错: {e}")
        import traceback
        traceback.print_exc()
