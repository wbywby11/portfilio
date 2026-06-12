"""验证 DSML 正则修复：同时匹配全角 ｜ 和 ASCII | 竖线"""
import re
import sys
sys.path.insert(0, r"d:\portfilio-end")

from app.agent.core.llm_client import LLMClient
from app.agent.core.agent import InvestmentAgent

# === 测试用例 ===
# 1. 全角竖线（原始格式）
TEST_FW = '''<｜DSML｜tool_calls>
<｜DSML｜invoke name="data_query">
<｜DSML｜parameter name="query" string="true">SELECT ISR_NM FROM dwd_isr_institution</｜DSML｜parameter>
</｜DSML｜invoke>
</｜DSML｜tool_calls>'''

# 2. ASCII竖线（LLM有时输出的格式）
TEST_ASCII = '''< | DSML | tool_calls>
< | DSML | invoke name="data_query">
< | DSML | parameter name="query" string="true">SELECT ISR_NM FROM dwd_isr_institution</｜DSML | parameter>
</ | DSML | invoke>
</ | DSML | tool_calls>'''

# 3. 混合竖线
TEST_MIXED = '''<｜DSML|tool_calls>
<|DSML｜invoke name="data_query">
< | DSML | parameter name="query" string="true">SELECT ISR_NM FROM dwd_isr_institution</｜DSML | parameter>
</ | DSML | invoke>
</｜DSML|tool_calls>'''

print("=" * 60)
print("  DSML 正则修复验证")
print("=" * 60)

# 测试 _DSML_TOOL_CALL_PATTERN
for name, test in [("全角", TEST_FW), ("ASCII", TEST_ASCII), ("混合", TEST_MIXED)]:
    matches = LLMClient._DSML_TOOL_CALL_PATTERN.findall(test)
    print(f"\n[{name}] _DSML_TOOL_CALL_PATTERN: {'✓ 匹配' if matches else '✗ 未匹配'} (found {len(matches)} blocks)")

# 测试 _DSML_INVOKE_PATTERN
for name, test in [("全角", TEST_FW), ("ASCII", TEST_ASCII), ("混合", TEST_MIXED)]:
    matches = LLMClient._DSML_INVOKE_PATTERN.findall(test)
    print(f"[{name}] _DSML_INVOKE_PATTERN: {'✓ 匹配' if matches else '✗ 未匹配'} (found {len(matches)} invokes)")
    for func_name, params in matches:
        print(f"      → function: {func_name}")

# 测试 _DSML_PARAM_PATTERN
for name, test in [("全角", TEST_FW), ("ASCII", TEST_ASCII), ("混合", TEST_MIXED)]:
    matches = LLMClient._DSML_PARAM_PATTERN.findall(test)
    print(f"[{name}] _DSML_PARAM_PATTERN: {'✓ 匹配' if matches else '✗ 未匹配'} (found {len(matches)} params)")
    for param_name, string_flag, value in matches:
        print(f"      → param: {param_name} (string={string_flag}) = {value[:50]}...")

# 测试 _parse_dsml_tool_calls
print("\n--- 完整解析测试 ---")
# 模拟 soft_tools 解析
class FakeLLM(LLMClient):
    def __init__(self):
        pass

fake = FakeLLM()
for name, test in [("全角", TEST_FW), ("ASCII", TEST_ASCII), ("混合", TEST_MIXED)]:
    result = fake._parse_dsml_tool_calls(test)
    print(f"[{name}] _parse_dsml_tool_calls: {'✓ 成功' if result else '✗ 失败'} ({len(result)} tool calls)")
    for tc in result:
        print(f"      → {tc['function']['name']}")

# 测试 agent._strip_dsml_tags
print("\n--- 清洗测试 ---")
class FakeAgent(InvestmentAgent):
    def __init__(self):
        pass

fake_agent = FakeAgent()
for name, test in [("全角", TEST_FW), ("ASCII", TEST_ASCII), ("混合", TEST_MIXED)]:
    content_with_prefix = "分析结果如下:\n\n" + test + "\n\n以上是分析结果。"
    cleaned = fake_agent._strip_dsml_tags(content_with_prefix)
    has_dsml = "DSML" in cleaned
    print(f"[{name}] _strip_dsml_tags: {'✗ DSML残留' if has_dsml else '✓ DSML已清除'}")
    print(f"      → 清理后: {cleaned[:60]}...")

print("\n" + "=" * 60)
print("  验证完成")
print("=" * 60)
