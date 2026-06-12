"""
刷新 ZY 数据域集合注册表

由于 MongoDB 中的数据是通过外部脚本导入的，
后端启动时可能未扫描到这些集合，需要手动刷新注册表。

使用方法:
  cd d:\portfilio-end
  python scripts/refresh_registry.py
"""
import sys
import os
import asyncio

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.collection_registry import CollectionRegistry


def main():
    print("=" * 70)
    print("  ZY 数据域 - 刷新集合注册表")
    print("=" * 70)
    
    # 创建注册表实例
    registry = CollectionRegistry()
    
    print("\n开始刷新集合注册表...")
    print("这将扫描 MongoDB 中的所有业务集合并更新注册表")
    
    # 执行刷新
    async def run_refresh():
        nonlocal registry
        
        try:
            count = await registry.refresh()
            print(f"\n✅ 刷新完成!")
            print(f"   发现集合数: {count}")
            
            # 列出已注册的集合
            collections = await registry.list_collections()
            print(f"\n已注册集合数: {len(collections)}")
            
            # 按域分组显示
            domain_groups = {}
            for coll in collections:
                domain = coll.get('domain', 'unknown')
                if domain not in domain_groups:
                    domain_groups[domain] = []
                domain_groups[domain].append(coll['collection_name'])
            
            print("\n按域分组:")
            for domain, colls in sorted(domain_groups.items()):
                print(f"  {domain}: {len(colls)} 张表")
                for c in sorted(colls)[:5]:
                    print(f"    - {c}")
                if len(colls) > 5:
                    print(f"    ... 还有 {len(colls) - 5} 张")
            
            # 测试查询
            print("\n测试查询:")
            test_collections = ['dwd_ast_info', 'dwd_ptl_info', 'dwd_isr_institution']
            
            for coll_name in test_collections:
                try:
                    count = registry.db[coll_name].count_documents({})
                    print(f"  ✅ {coll_name}: {count} 条记录")
                except Exception as e:
                    print(f"  ❌ {coll_name}: {e}")
            
        except Exception as e:
            print(f"\n❌ 刷新失败: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    # 运行异步代码
    asyncio.run(run_refresh())
    
    print("\n" + "=" * 70)
    print("  刷新完成!")
    print("=" * 70)
    print("\n现在可以通过 API 查询数据了:")
    print("  GET http://localhost:8000/api/v1/zy-data/collections")
    print("  GET http://localhost:8000/api/v1/zy-data/dwd_ast_info")


if __name__ == "__main__":
    main()