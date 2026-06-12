"""修复 PowerShell 批量替换破坏的 UTF-8 编码问题"""
import os
import sys
from pathlib import Path

def fix_file_encoding(file_path):
    """修复单个文件的编码问题"""
    try:
        # 尝试以多种编码读取文件
        content = None
        encodings = ['utf-8', 'gbk', 'gb2312', 'latin1']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        
        if content is None:
            print(f"❌ 无法读取文件: {file_path}")
            return False
        
        # 检查是否有乱码字符
        if '�' in content or '\ufffd' in content:
            print(f"🔧 修复文件: {file_path}")
            # 尝试修复常见的乱码模式
            content = content.replace('�?', '。')
            content = content.replace('�', '')
            
            # 以 UTF-8 重新写入
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(content)
            return True
        else:
            # 即使没有乱码，也确保以 UTF-8 保存
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(content)
            return True
            
    except Exception as e:
        print(f"❌ 处理文件失败 {file_path}: {e}")
        return False

def scan_and_fix(directory):
    """扫描并修复目录下所有 Python 文件"""
    fixed = 0
    failed = 0
    total = 0
    
    for root, dirs, files in os.walk(directory):
        # 跳过 __pycache__ 目录
        if '__pycache__' in root:
            continue
            
        for file in files:
            if file.endswith('.py'):
                total += 1
                file_path = os.path.join(root, file)
                
                if fix_file_encoding(file_path):
                    fixed += 1
                else:
                    failed += 1
    
    print(f"\n{'='*60}")
    print(f"扫描完成:")
    print(f"  总文件数: {total}")
    print(f"  成功修复: {fixed}")
    print(f"  失败: {failed}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    # 获取项目根目录
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # 修复 app/analysis 目录
    analysis_dir = project_root / "app" / "analysis"
    if analysis_dir.exists():
        print(f"🔍 扫描目录: {analysis_dir}\n")
        scan_and_fix(str(analysis_dir))
    
    # 可选：修复其他目录
    # strategies_dir = project_root / "app" / "strategies"
    # if strategies_dir.exists():
    #     print(f"🔍 扫描目录: {strategies_dir}\n")
    #     scan_and_fix(str(strategies_dir))
    
    print("✅ 编码修复完成！")
