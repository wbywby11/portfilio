"""Verify new project API endpoints"""
import urllib.request
import json

BASE = "http://localhost:8000/api/v1"
endpoints = [
    ("Options产品列表", "/options/products"),
    ("ETF贴水默认参数", "/etf-discount/default-params"),
    ("资产列表", "/assets?limit=3"),
    ("策略模型列表", "/strategy-models?limit=2"),
    ("组合列表", "/portfolios?limit=2"),
    ("数据接入Hub", "/data-hub/connectors"),
    ("数据资产管理", "/data-assets"),
    ("语义画像域列表", "/semantic/domains"),
    ("Agent状态", "/agent/status"),
    ("汇率统计", "/fx/stats"),
    ("交易日历", "/trade-calendar?year=2026"),
]

print("=" * 60)
print("  新项目 API 端点验证")
print("=" * 60)
for name, path in endpoints:
    try:
        r = urllib.request.urlopen(BASE + path, timeout=10)
        data = json.loads(r.read().decode())
        code = data.get("code", "?")
        msg = data.get("message", "")[:40]
        print(f"  [OK {r.status}] {name:20s} code={code}  {msg}")
    except Exception as e:
        print(f"  [FAIL]    {name:20s} {str(e)[:60]}")
