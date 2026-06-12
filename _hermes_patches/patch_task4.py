"""Patch script for Task #4.2: insert gateway_notify_interval read into run_agent.py"""
import io

PATH = r"C:\Users\wangb\AppData\Local\hermes\hermes-agent\run_agent.py"

OLD = """        try:
            from hermes_cli.config import load_config as _load_agent_config
            _agent_cfg = _load_agent_config()
        except Exception:
            _agent_cfg = {}
        try:
            self._tool_guardrails = ToolCallGuardrailController(
"""

NEW = """        try:
            from hermes_cli.config import load_config as _load_agent_config
            _agent_cfg = _load_agent_config()
        except Exception:
            _agent_cfg = {}
        # --- Progress Config ---
        try:
            self.gateway_notify_interval = int(
                (_agent_cfg.get('agent', {}) or {}).get('gateway_notify_interval', 30)
            )
        except Exception:
            self.gateway_notify_interval = 30
        # --- End Progress Config ---
        try:
            self._tool_guardrails = ToolCallGuardrailController(
"""

with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    src = f.read()

if NEW.strip() in src:
    print("ALREADY_PATCHED")
elif OLD not in src:
    print("ANCHOR_NOT_FOUND")
else:
    src2 = src.replace(OLD, NEW, 1)
    with io.open(PATH, "w", encoding="utf-8", newline="") as f:
        f.write(src2)
    print("OK")
