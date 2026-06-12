"""Verify DSML/tool_call filtering patterns."""
import re, sys
sys.path.insert(0, r"d:\portfilio-end")
from app.agent.core.agent import InvestmentAgent

agent = InvestmentAgent.__new__(InvestmentAgent)

BAR = chr(0xFF5C)  # full-width bar
LT = chr(60)
GT = chr(62)
SL = chr(47)

# Test 1: DSML full-width
dsml_fw = "Analysis.\n" + LT + BAR + "DSML" + BAR + "tool_calls" + GT + "\ncall\n" + LT + SL + BAR + "DSML" + BAR + "tool_calls" + GT + "\nMore."
r1 = agent._strip_dsml_tags(dsml_fw)
print("Test 1 - DSML full-width strip:", "DSML" not in r1, repr(r1[:80]))

# Test 2: Bare JSON tool call
t2 = 'Text.\n{"name":"calc","arguments":{"x":1}}\nEnd.'
r2 = agent._strip_dsml_tags(t2)
print("Test 2 - Bare JSON strip:", '"name"' not in r2, repr(r2[:80]))

# Test 3: Orphan merged tag
t3 = "Content." + LT + SL + "tasktool_call" + GT
r3 = agent._strip_dsml_tags(t3)
print("Test 3 - Orphan tag strip:", "tool_call" not in r3, repr(r3[:80]))

# Test 4: Normal text should pass through
t4 = "This is a normal analysis about portfolio risk."
r4 = agent._strip_dsml_tags(t4)
print("Test 4 - Normal text preserved:", r4 == t4)

# Test 5: Mixed content
dsml_block = LT + BAR + "DSML" + BAR + "invoke" + GT + "stuff" + LT + SL + BAR + "DSML" + BAR + "invoke" + GT
t5 = "Good analysis.\n" + dsml_block + "\nConclusion here."
r5 = agent._strip_dsml_tags(t5)
print("Test 5 - Mixed strip:", "DSML" not in r5 and "Good analysis" in r5 and "Conclusion" in r5)

# Test 6: _TOOL_CALL_TAG_PATTERN detection
detect_cases = [
    LT + BAR + "DSML" + BAR + "tool_calls" + GT,
    '{"name": "x", "arguments": {}}',
    LT + "tool_call" + GT,
]
print("\nTool intent detection:")
for case in detect_cases:
    hit = bool(InvestmentAgent._TOOL_CALL_TAG_PATTERN.search(case))
    print("  Detected:", hit, repr(case[:50]))

print("\nAll tests completed!")
