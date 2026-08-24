"""Diagnostic v2: proper tool registry inspection."""
import sys
sys.path.insert(0, r'd:\project\portfilio\portfilio-end')

from app.agent.tools import tool_registry

# Check actual API
print("ToolRegistry methods:", [m for m in dir(tool_registry) if not m.startswith('_')])
print()

# Try common methods
if hasattr(tool_registry, 'tools'):
    tools = tool_registry.tools
    print(f"Registered tools: {len(tools)}")
    for name, tool in sorted(tools.items()):
        print(f"  [{tool.category}] {name} - {tool.description[:60]}...")
elif hasattr(tool_registry, 'get_all_tools'):
    tools = tool_registry.get_all_tools()
    print(f"get_all_tools: {len(tools)}")
elif hasattr(tool_registry, 'registered_tools'):
    tools = tool_registry.registered_tools
    print(f"registered_tools: {len(tools)}")

# Check scene toolsets
print()
if hasattr(tool_registry, 'SCENE_TOOLSETS'):
    print("SCENE_TOOLSETS:", list(tool_registry.SCENE_TOOLSETS.keys()))
if hasattr(tool_registry, 'TOOLSETS'):
    print("TOOLSETS:", list(tool_registry.TOOLSETS.keys()))
