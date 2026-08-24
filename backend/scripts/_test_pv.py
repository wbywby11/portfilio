"""临时诊断脚本：检查 param_versions 数据流"""
import asyncio
import motor.motor_asyncio

async def main():
    client = motor.motor_asyncio.AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['portfolio_system']
    
    # 1. 检查模型总数
    model_count = await db['strategy_models'].count_documents({})
    print(f"=== 策略模型总数: {model_count} ===")
    
    # 2. 列出最新5个模型
    models = await db['strategy_models'].find().sort('created_at', -1).limit(5).to_list(5)
    for m in models:
        mid = str(m['_id'])
        name = m.get('name', '?')
        tpl = m.get('template_code', '?')
        print(f"  [{mid}] {name} (template={tpl})")
    
    # 3. 检查 param_versions
    pv_count = await db['strategy_param_versions'].count_documents({})
    print(f"\n=== 参数版本总数: {pv_count} ===")
    
    if pv_count > 0:
        pvs = await db['strategy_param_versions'].find().sort('created_at', -1).limit(10).to_list(10)
        for pv in pvs:
            mid = pv.get('model_id', '?')
            ver = pv.get('version', '?')
            summary = pv.get('change_summary', '(无)')
            created = pv.get('created_at', '?')
            print(f"  model_id={mid} v{ver} | {summary} | {created}")
    else:
        print("  (没有任何参数版本记录)")
    
    # 4. 对第一个模型尝试调用 service
    if models:
        first_model_id = str(models[0]['_id'])
        print(f"\n=== 测试 service.list_param_versions(model_id={first_model_id}) ===")
        try:
            from app.services.param_version_service import ParamVersionService
            svc = ParamVersionService()
            rows = await svc.list_param_versions(first_model_id, limit=5)
            print(f"  返回 {len(rows)} 条:")
            for r in rows:
                print(f"    id={r.get('_id')} v={r.get('version')} summary={r.get('change_summary')} bt_count={r.get('backtest_count', '?')}")
        except Exception as e:
            print(f"  ERROR: {e}")
    
    client.close()

asyncio.run(main())
