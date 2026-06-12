"""Patch script for Task #5: Progress heartbeat init + token tracking + heartbeat,
and Task #5.5 progress complete after loop. (Task #7 metadata persistence appended at same site.)
"""
import io

PATH = r"C:\Users\wangb\AppData\Local\hermes\hermes-agent\run_agent.py"

# ---- Anchor 1: before the while loop (init block) ----
OLD1 = """                _ext_prefetch_cache = self._memory_manager.prefetch_all(_query) or \"\"
            except Exception:
                pass

        while (api_call_count < self.max_iterations and self.iteration_budget.remaining > 0) or self._budget_grace_call:
"""

NEW1 = """                _ext_prefetch_cache = self._memory_manager.prefetch_all(_query) or \"\"
            except Exception:
                pass

        # --- Progress Heartbeat Init ---
        import time as _time_mod
        _loop_start_time = _time_mod.time()
        _last_progress_push = _loop_start_time
        _progress_interval = getattr(self, 'gateway_notify_interval', 30)
        self._total_tokens_used = 0
        # --- End Progress Heartbeat Init ---

        while (api_call_count < self.max_iterations and self.iteration_budget.remaining > 0) or self._budget_grace_call:
"""

# ---- Anchor 2: inside response.usage block, right after existing token accounting ----
# We pick a stable line that uniquely appears once in the file.
OLD2 = """                        self.session_cache_write_tokens += canonical_usage.cache_write_tokens
                        self.session_reasoning_tokens += canonical_usage.reasoning_tokens
"""

NEW2 = """                        self.session_cache_write_tokens += canonical_usage.cache_write_tokens
                        self.session_reasoning_tokens += canonical_usage.reasoning_tokens

                        # --- Token Tracking ---
                        try:
                            if hasattr(response, 'usage') and response.usage:
                                _iter_tokens = getattr(response.usage, 'total_tokens', 0)
                                self._total_tokens_used = getattr(self, '_total_tokens_used', 0) + _iter_tokens
                        except Exception:
                            pass
                        # --- End Token Tracking ---

                        # --- Progress Heartbeat ---
                        try:
                            _now = _time_mod.time()
                            if _now - _last_progress_push >= _progress_interval:
                                _elapsed = _now - _loop_start_time
                                _progress_data = {
                                    "event": "agent:loop_progress",
                                    "iteration": api_call_count,
                                    "max_iterations": self.max_iterations,
                                    "elapsed_seconds": round(_elapsed, 1),
                                    "tokens_used": getattr(self, '_total_tokens_used', 0),
                                    "budget_remaining": self.iteration_budget.remaining,
                                    "status": "running",
                                }
                                if hasattr(self, 'status_callback') and self.status_callback:
                                    try:
                                        self.status_callback("progress", _progress_data)
                                    except Exception:
                                        pass
                                _last_progress_push = _now
                        except Exception:
                            pass
                        # --- End Progress Heartbeat ---

                        # --- Iteration Metadata Persistence ---
                        try:
                            if api_call_count % 5 == 0 or api_call_count == 1:
                                _meta_record = {
                                    "type": "iteration_checkpoint",
                                    "iteration": api_call_count,
                                    "timestamp": __import__('datetime').datetime.now().isoformat(),
                                    "elapsed_seconds": round(_time_mod.time() - _loop_start_time, 1),
                                    "tokens_used_cumulative": getattr(self, '_total_tokens_used', 0),
                                    "budget_remaining": self.iteration_budget.remaining,
                                }
                                try:
                                    if hasattr(self, '_append_to_session_jsonl'):
                                        self._append_to_session_jsonl(_meta_record)
                                    elif hasattr(self, 'session_file') and self.session_file:
                                        import json as _json_mod
                                        with open(self.session_file, 'a', encoding='utf-8') as _sf:
                                            _sf.write(_json_mod.dumps(_meta_record, ensure_ascii=False) + '\\n')
                                    elif hasattr(self, 'session_path') and getattr(self, 'session_path', None):
                                        import json as _json_mod
                                        with open(self.session_path, 'a', encoding='utf-8') as _sf:
                                            _sf.write(_json_mod.dumps(_meta_record, ensure_ascii=False) + '\\n')
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        # --- End Iteration Metadata Persistence ---
"""

# ---- Anchor 3: after the while loop (progress complete) ----
OLD3 = """                    messages.append({\"role\": \"assistant\", \"content\": final_response})
                    break
        
        if final_response is None and (
            api_call_count >= self.max_iterations
            or self.iteration_budget.remaining <= 0
        ):
"""

NEW3 = """                    messages.append({\"role\": \"assistant\", \"content\": final_response})
                    break
        
        # --- Progress Complete ---
        try:
            _exit_reason = "completed"
            if api_call_count >= self.max_iterations:
                _exit_reason = "max_iterations"
            elif self.iteration_budget.remaining <= 0:
                _exit_reason = "budget_exhausted"
            _final_data = {
                "event": "agent:loop_complete",
                "total_iterations": api_call_count,
                "total_elapsed_seconds": round(_time_mod.time() - _loop_start_time, 1),
                "total_tokens_used": getattr(self, '_total_tokens_used', 0),
                "exit_reason": _exit_reason,
            }
            if hasattr(self, 'status_callback') and self.status_callback:
                try:
                    self.status_callback("complete", _final_data)
                except Exception:
                    pass
        except Exception:
            pass
        # --- End Progress Complete ---

        if final_response is None and (
            api_call_count >= self.max_iterations
            or self.iteration_budget.remaining <= 0
        ):
"""

with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    src = f.read()

results = []
for label, OLD, NEW in [("init", OLD1, NEW1), ("heartbeat", OLD2, NEW2), ("complete", OLD3, NEW3)]:
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
