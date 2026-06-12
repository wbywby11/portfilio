"""一键修复所有错误的模块导入路径"""
import os
import re
from pathlib import Path

def fix_imports_in_file(file_path):
    """修复单个文件中的导入路径"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # 修复规则
        replacements = [
            # strategies 模块
            (r'^from strategies\.', 'from app.strategies.'),
            (r'^import strategies\.', 'import app.strategies.'),
            
            # backtesting 模块
            (r'^from backtesting\.', 'from app.backtesting.'),
            (r'^import backtesting\.', 'import app.backtesting.'),
            
            # analysis 模块
            (r'^from analysis\.', 'from app.analysis.'),
            (r'^import analysis\.', 'import app.analysis.'),
        ]
        
        for pattern, replacement in replacements:
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        
        # 如果内容有变化，写回文件
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(content)
            return True
        
        return False
        
    except Exception as e:
        print(f"❌ 处理失败 {file_path}: {e}")
        return False

def scan_and_fix_directory(directory):
    """扫描并修复目录下所有 Python 文件"""
    fixed = 0
    total = 0
    
    for root, dirs, files in os.walk(directory):
        # 跳过特定目录
        if '__pycache__' in root or '.git' in root or 'venv' in root:
            continue
            
        for file in files:
            if file.endswith('.py'):
                total += 1
                file_path = os.path.join(root, file)
                
                if fix_imports_in_file(file_path):
                    fixed += 1
                    print(f"✅ 修复: {file_path}")
    
    return fixed, total

if __name__ == "__main__":
    # 获取项目根目录
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    print("=" * 60)
    print("开始修复所有导入路径...")
    print("=" * 60)
    print()
    
    # 修复整个 app 目录
    app_dir = project_root / "app"
    if app_dir.exists():
        print(f"🔍 扫描目录: {app_dir}\n")
        fixed, total = scan_and_fix_directory(str(app_dir))
        
        print()
        print("=" * 60)
        print(f"修复完成:")
        print(f"  总文件数: {total}")
        print(f"  修复文件数: {fixed}")
        print(f"  未修改: {total - fixed}")
        print("=" * 60)
    else:
        print(f"❌ 目录不存在: {app_dir}")
    
    print("\n✅ 所有导入路径修复完成！")
