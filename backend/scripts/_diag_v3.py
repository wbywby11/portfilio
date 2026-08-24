"""Diagnostic v3: full tool list and categories."""
import sys
sys.path.insert(0, r'd:\project\portfilio\portfilio-end')

from app.agent.tools import tool_registry

tools = tool_registry.get_all_tools()
print(f"Total tools: {len(tools)}\n")

# It's a list, check item type
if tools:
    print(f"Type: {type(tools[0])}")

for tool in tools:
    name = getattr(tool, 'name', str(tool))
    cat = getattr(tool, 'category', '?')
    desc = (getattr(tool, 'description', '') or '')[:80].replace('\n', ' ')
    print(f"  [{cat:12s}] {name:35s} {desc}")

print(f"\n--- Categories ---")
cats = tool_registry.get_tools_by_category()
for cat, names in sorted(cats.items()):
    print(f"  {cat}: {len(names)} tools")
    for n in names:
        print(f"    - {n}")

print(f"\n--- Scene Toolsets ---")
for scene in sorted(tool_registry.SCENE_TOOLSETS.keys()):
    ts = tool_registry.get_scene_tools(scene)
    print(f"  {scene}: {len(ts)} tools")

print(f"\n--- Toolsets ---")
for ts_name in sorted(tool_registry.TOOLSETS.keys()):
    ts = tool_registry.get_toolset(ts_name)
    print(f"  {ts_name}: {ts}")
