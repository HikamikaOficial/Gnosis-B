#!/usr/bin/env python3
import json, os, sys, time, hashlib
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
log = root / ".gnosis" / "runtime" / "hook-events.jsonl"
log.parent.mkdir(parents=True, exist_ok=True)

tool_input = data.get("tool_input") or {}
safe_input = {}
for k, v in tool_input.items():
    if k in {"content", "new_string", "old_string"}:
        text = str(v)
        safe_input[k + "_sha256"] = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        safe_input[k + "_length"] = len(text)
    else:
        safe_input[k] = v

event = {
    "ts": time.time(),
    "hook_event_name": data.get("hook_event_name"),
    "session_id": data.get("session_id"),
    "tool_name": data.get("tool_name"),
    "tool_use_id": data.get("tool_use_id"),
    "cwd": data.get("cwd"),
    "tool_input": safe_input,
}
with log.open("a", encoding="utf-8") as f:
    f.write(json.dumps(event, ensure_ascii=False) + "\n")
sys.exit(0)
