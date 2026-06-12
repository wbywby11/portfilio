"""
ZY 数据域 API 快速部署脚本

功能:
1. 检查后端项目是否存在
2. 复制 API 文件到后端
3. 自动注册路由
4. 验证部署结果

使用方法:
  cd d:\portfilio
  python scripts/deploy_zy_data_api.py
"""
import os
import sys
from pathlib import Path
import shutil

# 路径配置
CURRENT_DIR = Path(__file__).parent.parent
BACKEND_DIR = Path("d:/portfilio-end")
API_SOURCE = CURRENT_DIR / "scripts" / "zy_data_api_implementation.py"

def print_step(step, message):
    """打印步骤信息"""
    print(f"\n{'='*60}")
    print(f"步骤 {step}: {message}")
    print(f"{'='*60}")

def check_backend_exists():
    """检查后端项目是否存在"""
    print_step(1, "检查后端项目")
    
    if not BACKEND_DIR.exists():
        print(f"❌ 后端项目不存在: {BACKEND_DIR}")
        print(f"\n请确认:")
        print(f"  1. 后端项目路径是否正确")
        print(f"  2. 如果路径不同,请修改此脚本中的 BACKEND_DIR 变量")
        print(f"  3. 或手动复制 API 文件到后端项目")
        return False
    
    print(f"✅ 后端项目存在: {BACKEND_DIR}")
    
    # 检查关键文件 - main.py 在项目根目录
    main_py = BACKEND_DIR / "main.py"
    if not main_py.exists():
        print(f"❌ 未找到 main.py: {main_py}")
        return False
    
    print(f"✅ 找到 main.py")
    return True

def create_api_directory():
    """创建 API 目录"""
    print_step(2, "创建 API 目录")
    
    api_dir = BACKEND_DIR / "app" / "api" / "v1"
    
    if api_dir.exists():
        print(f"✅ API 目录已存在: {api_dir}")
    else:
        print(f"创建目录: {api_dir}")
        api_dir.mkdir(parents=True, exist_ok=True)
        print(f"✅ 目录创建成功")
    
    return api_dir

def copy_api_file(api_dir):
    """复制 API 文件"""
    print_step(3, "复制 API 文件")
    
    if not API_SOURCE.exists():
        print(f"❌ API 源文件不存在: {API_SOURCE}")
        return False
    
    api_dest = api_dir / "zy_data.py"
    
    # 备份已存在的文件
    if api_dest.exists():
        backup = api_dest.with_suffix('.py.bak')
        print(f"备份现有文件: {backup}")
        shutil.copy2(api_dest, backup)
        print(f"✅ 备份完成")
    
    # 复制文件
    print(f"复制: {API_SOURCE} → {api_dest}")
    shutil.copy2(API_SOURCE, api_dest)
    print(f"✅ 复制成功")
    
    return True

def register_router():
    """注册路由到 main.py"""
    print_step(4, "注册路由")
    
    main_py = BACKEND_DIR / "main.py"  # main.py 在项目根目录
    
    # 读取 main.py
    with open(main_py, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否已注册
    if 'from app.api.v1 import zy_data' in content:
        print(f"✅ 路由已注册,跳过")
        return True
    
    # 添加导入
    import_line = "from app.api.v1 import zy_data\n"
    
    # 查找插入位置 (在其他 import 之后)
    lines = content.split('\n')
    insert_idx = 0
    
    for i, line in enumerate(lines):
        if line.startswith('from app') or line.startswith('import '):
            insert_idx = i + 1
    
    # 插入导入
    lines.insert(insert_idx, import_line)
    
    # 查找 app.include_router 插入位置
    router_line = "app.include_router(zy_data.router)\n"
    
    for i, line in enumerate(lines):
        if 'app.include_router' in line:
            lines.insert(i, router_line)
            break
    else:
        # 如果没找到 include_router,在 app 定义后添加
        for i, line in enumerate(lines):
            if 'app = FastAPI()' in line:
                lines.insert(i + 1, '')
                lines.insert(i + 2, '# ZY 数据域路由')
                lines.insert(i + 3, router_line)
                break
    
    # 写回文件
    with open(main_py, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"✅ 路由注册成功")
    print(f"   添加导入: from app.api.v1 import zy_data")
    print(f"   添加路由: app.include_router(zy_data.router)")
    
    return True

def verify_deployment():
    """验证部署"""
    print_step(5, "验证部署")
    
    api_file = BACKEND_DIR / "app" / "api" / "v1" / "zy_data.py"
    main_py = BACKEND_DIR / "main.py"  # main.py 在项目根目录
    
    checks = []
    
    # 检查 API 文件
    if api_file.exists():
        print(f"✅ API 文件存在: {api_file}")
        checks.append(True)
    else:
        print(f"❌ API 文件不存在")
        checks.append(False)
    
    # 检查路由注册
    with open(main_py, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'from app.api.v1 import zy_data' in content:
        print(f"✅ 导入语句已添加")
        checks.append(True)
    else:
        print(f"❌ 导入语句未找到")
        checks.append(False)
    
    if 'app.include_router(zy_data.router)' in content:
        print(f"✅ 路由注册已添加")
        checks.append(True)
    else:
        print(f"❌ 路由注册未找到")
        checks.append(False)
    
    return all(checks)

def print_next_steps():
    """打印后续步骤"""
    print_step("后续", "完成部署后的操作")
    
    print("""
✅ 部署完成! 接下来请执行:

1️⃣  导入 Mock 数据到 MongoDB:
   cd d:\\portfilio
   python scripts/import_zy_data_domain_mock.py

2️⃣  启动后端服务:
   cd d:\\portfilio-end
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

3️⃣  测试 API:
   cd d:\\portfilio
   python scripts/test_zy_data_api.py

4️⃣  访问 API 文档:
   http://localhost:8000/docs

5️⃣  验证前端智能对话:
   打开前端应用,智能对话应该可以查询 ZY 数据域了

📚 相关文档:
   - docs/ZY_DATA_API_INTEGRATION_GUIDE.md
   - docs/ZY_DATA_DOMAIN_MOCK_IMPORT_GUIDE.md
""")

def main():
    print("ZY 数据域 API 快速部署工具")
    print(f"后端项目: {BACKEND_DIR}")
    
    # 执行部署步骤
    if not check_backend_exists():
        print("\n❌ 部署失败: 后端项目不存在")
        sys.exit(1)
    
    api_dir = create_api_directory()
    
    if not copy_api_file(api_dir):
        print("\n❌ 部署失败: 文件复制失败")
        sys.exit(1)
    
    if not register_router():
        print("\n❌ 部署失败: 路由注册失败")
        sys.exit(1)
    
    if not verify_deployment():
        print("\n⚠️  部署完成但验证失败,请手动检查")
    else:
        print("\n✅ 部署成功! 所有检查通过")
    
    # 打印后续步骤
    print_next_steps()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 部署过程出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
