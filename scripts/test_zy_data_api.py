"""
ZY 数据域 API 测试脚本

测试所有 API 接口的功能

使用方法:
  cd d:\portfilio
  python scripts/test_zy_data_api.py
"""
import requests
import json
import sys

BASE_URL = "http://localhost:8000/api/v1/zy-data"

def print_section(title):
    """打印分隔线"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def test_health():
    """测试 1: 健康检查"""
    print_section("测试 1: 健康检查")
    
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"状态码: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ 状态: {data.get('status')}")
            print(f"   数据库: {data.get('database')}")
            print(f"   集合数: {data.get('collections')}")
            return True
        else:
            print(f"❌ 响应: {resp.text}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"❌ 连接失败: 后端服务未启动或地址错误")
        print(f"   请确保: uvicorn app.main:app --reload --port 8000")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def test_list_collections():
    """测试 2: 列出集合"""
    print_section("测试 2: 列出所有集合")
    
    try:
        resp = requests.get(f"{BASE_URL}/collections", timeout=5)
        print(f"状态码: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            collections = data.get('collections', [])
            print(f"✅ 集合数量: {len(collections)}")
            print(f"   前 5 个: {collections[:5]}")
            
            # 检查关键集合是否存在
            expected = ['dwd_ast_info', 'dwd_ptl_info', 'dwd_isr_institution']
            missing = [c for c in expected if c not in collections]
            if missing:
                print(f"   ⚠️  缺少关键集合: {missing}")
                print(f"   请先运行: python scripts/import_zy_data_domain_mock.py")
            else:
                print(f"   ✅ 关键集合已就绪")
            
            return True
        else:
            print(f"❌ 响应: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def test_query_assets():
    """测试 3: 查询资产信息"""
    print_section("测试 3: 查询资产信息")
    
    try:
        resp = requests.get(
            f"{BASE_URL}/dwd_ast_info",
            params={"page": 1, "pageSize": 5},
            timeout=5
        )
        print(f"状态码: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ 总数: {data['total']}")
            print(f"   返回: {len(data['records'])} 条")
            print(f"   页码: {data['page']}")
            
            if data['records']:
                rec = data['records'][0]
                print(f"   样例:")
                print(f"     代码: {rec.get('AST_CD')}")
                print(f"     名称: {rec.get('AST_NM')}")
                print(f"     类型: {rec.get('AST_TYPE')}")
            
            return True
        else:
            print(f"❌ 响应: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def test_query_with_filter():
    """测试 4: 带过滤条件查询"""
    print_section("测试 4: 带过滤条件查询")
    
    try:
        filters = {"AST_TYPE": "BOND"}
        resp = requests.get(
            f"{BASE_URL}/dwd_ast_info",
            params={
                "page": 1,
                "pageSize": 10,
                "filters_json": json.dumps(filters)
            },
            timeout=5
        )
        print(f"状态码: {resp.status_code}")
        print(f"过滤条件: {filters}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ 匹配记录: {data['total']} 条")
            
            # 验证过滤结果
            for rec in data['records']:
                if rec.get('AST_TYPE') != 'BOND':
                    print(f"❌ 过滤失败: 返回了非 BOND 类型记录")
                    return False
            
            print(f"   ✅ 过滤正确")
            return True
        else:
            print(f"❌ 响应: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def test_query_products():
    """测试 5: 查询产品信息"""
    print_section("测试 5: 查询产品信息")
    
    try:
        resp = requests.get(
            f"{BASE_URL}/dwd_ptl_info",
            params={"page": 1, "pageSize": 10},
            timeout=5
        )
        print(f"状态码: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ 产品总数: {data['total']}")
            
            if data['records']:
                print(f"   产品列表:")
                for rec in data['records'][:3]:
                    print(f"     - {rec.get('PORT_ID')}: {rec.get('PORT_NM')}")
                    print(f"       净值: {rec.get('SHR_NAV')} | 规模: {rec.get('AUM')}")
            
            return True
        else:
            print(f"❌ 响应: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def test_count():
    """测试 6: 统计记录数"""
    print_section("测试 6: 统计记录数")
    
    collections = ['dwd_ast_info', 'dwd_ptl_info', 'dwd_isr_institution']
    
    try:
        for coll in collections:
            resp = requests.get(
                f"{BASE_URL}/{coll}/count",
                timeout=5
            )
            
            if resp.status_code == 200:
                count = resp.json()['count']
                print(f"✅ {coll}: {count} 条")
            else:
                print(f"❌ {coll}: {resp.status_code}")
                return False
        
        return True
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def test_not_found():
    """测试 7: 404 错误处理"""
    print_section("测试 7: 404 错误处理")
    
    try:
        resp = requests.get(
            f"{BASE_URL}/nonexistent_collection",
            params={"page": 1, "pageSize": 10},
            timeout=5
        )
        print(f"状态码: {resp.status_code}")
        
        if resp.status_code == 404:
            data = resp.json()
            print(f"✅ 正确返回 404")
            print(f"   错误信息: {data.get('detail')}")
            return True
        else:
            print(f"❌ 期望 404,实际 {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def test_pagination():
    """测试 8: 分页功能"""
    print_section("测试 8: 分页功能")
    
    try:
        # 查询第 1 页
        resp1 = requests.get(
            f"{BASE_URL}/dwd_ast_info",
            params={"page": 1, "pageSize": 3},
            timeout=5
        )
        
        # 查询第 2 页
        resp2 = requests.get(
            f"{BASE_URL}/dwd_ast_info",
            params={"page": 2, "pageSize": 3},
            timeout=5
        )
        
        if resp1.status_code == 200 and resp2.status_code == 200:
            data1 = resp1.json()
            data2 = resp2.json()
            
            print(f"✅ 第 1 页: {len(data1['records'])} 条")
            print(f"✅ 第 2 页: {len(data2['records'])} 条")
            print(f"   总数: {data1['total']}")
            
            # 验证页数据不同
            if data1['records'] and data2['records']:
                id1 = data1['records'][0]['_id']
                id2 = data2['records'][0]['_id']
                if id1 != id2:
                    print(f"   ✅ 分页数据不重复")
                    return True
                else:
                    print(f"   ❌ 分页数据重复")
                    return False
            
            return True
        else:
            print(f"❌ 请求失败")
            return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def print_summary(results):
    """打印测试总结"""
    print_section("测试总结")
    
    total = len(results)
    passed = sum(1 for r in results if r)
    failed = total - passed
    
    print(f"总计: {total} 个测试")
    print(f"✅ 通过: {passed}")
    print(f"❌ 失败: {failed}")
    
    if failed == 0:
        print(f"\n🎉 所有测试通过!")
    else:
        print(f"\n⚠️  有 {failed} 个测试失败,请检查日志")

def main():
    print("ZY 数据域 API 测试工具")
    print(f"目标地址: {BASE_URL}")
    
    results = []
    
    # 执行测试
    results.append(test_health())
    results.append(test_list_collections())
    results.append(test_query_assets())
    results.append(test_query_with_filter())
    results.append(test_query_products())
    results.append(test_count())
    results.append(test_not_found())
    results.append(test_pagination())
    
    # 打印总结
    print_summary(results)
    
    # 退出码
    sys.exit(0 if all(results) else 1)

if __name__ == "__main__":
    main()
