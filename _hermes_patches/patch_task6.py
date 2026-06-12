"""Patch script for Task #6: gateway server.py - add _emit_progress and enhance status_callback."""
import io

PATH = r"C:\Users\wangb\AppData\Local\hermes\hermes-agent\tui_gateway\server.py"

# ---- Anchor 1: add _emit_progress helper after _emit() ----
OLD1 = """def _emit(event: str, sid: str, payload: dict | None = None):
    params = {"type": event, "session_id": sid}
    if payload is not None:
        params["payload"] = payload
    write_json({"jsonrpc": "2.0", "method": "event", "params": params})


def _status_update(sid: str, kind: str, text: str | None = None):
"""

NEW1 = """def _emit(event: str, sid: str, payload: dict | None = None):
    params = {"type": event, "session_id": sid}
    if payload is not None:
        params["payload"] = payload
    write_json({"jsonrpc": "2.0", "method": "event", "params": params})


# --- Progress Heartbeat ---
def _emit_progress(sid: str, message: str, data: dict):
    \"\"\"Push progress update to connected client via the JSON-RPC event channel.\"\"\"
    from datetime import datetime
    payload = {
        "type": "progress",
        "message": message,
        "data": data,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        _emit("agent_progress", sid, payload)
    except Exception:
        pass
    try:
        logger.info("[progress] %s", message)
    except Exception:
        pass
# --- End Progress Heartbeat ---


def _status_update(sid: str, kind: str, text: str | None = None):
"""

# ---- Anchor 2: enhance status_callback - convert lambda into a function ----
OLD2 = """        status_callback=lambda kind, text=None: _status_update(
            sid, str(kind), None if text is None else str(text)
        ),
"""

NEW2 = """        # --- Progress Event Handling ---
        status_callback=(lambda _sid=sid: _build_status_cb(_sid))(),
        # --- End Progress Event Handling ---
"""

# ---- Anchor 3: define _build_status_cb just before _agent_cbs ----
OLD3 = """def _agent_cbs(sid: str) -> dict:
    return dict(
"""

NEW3 = """# --- Progress Event Handling ---
def _build_status_cb(sid: str):
    \"\"\"Construct a status callback that intercepts progress/complete events
    while preserving the original status.update behaviour for all other kinds.
    \"\"\"
    def _status_cb(event_type, data=None):
        # --- Progress Event Handling ---
        try:
            if event_type == "progress" and isinstance(data, dict):
                msg = (
                    f"\u23f3 {float(data.get('elapsed_seconds', 0) or 0):.0f}s elapsed \u2014 "
                    f"iteration {data.get('iteration', '?')}/{data.get('max_iterations', '?')} \u2014 "
                    f"tokens: {data.get('tokens_used', '?')}"
                )
                _emit_progress(sid, msg, data)
                return
            if event_type == "complete" and isinstance(data, dict):
                msg = (
                    f"\u2705 Done: {data.get('total_iterations', '?')} iterations, "
                    f"{float(data.get('total_elapsed_seconds', 0) or 0):.0f}s, "
                    f"{data.get('total_tokens_used', '?')} tokens"
                )
                _emit_progress(sid, msg, data)
                return
        except Exception:
            pass
        # --- End Progress Event Handling ---
        # Fallback: preserve original lifecycle/warn semantics.
        try:
            _status_update(
                sid, str(event_type), None if data is None else str(data)
            )
        except Exception:
            pass
    return _status_cb
# --- End Progress Event Handling ---


def _agent_cbs(sid: str) -> dict:
    return dict(
"""

with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    src = f.read()

results = []
for label, OLD, NEW in [("emit_progress", OLD1, NEW1), ("build_status_cb", OLD3, NEW3), ("status_cb_swap", OLD2, NEW2)]:
    if NEW.strip() in src:
        results.append(f"{label}: ALREADY_PATCHED")
        continue
    if OLD not in src:
        results.append(f"{label}: ANCHOR_NOT_FOUND")
        continue
    if src.count(OLD) > 1:
        results.append(f"{label}: ANCHOR_NOT_UNIQUE ({src.count(OLD)})")
        continue
    src = src.replace(OLD, NEW, 1)
    results.append(f"{label}: OK")

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(src)

for r in results:
    print(r)
