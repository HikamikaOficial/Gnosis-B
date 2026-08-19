#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path

def block(reason: str):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }))
    sys.exit(2)

try:
    data = json.load(sys.stdin)
except Exception:
    # Fail closed would be ideal, but a malformed hook input should not brick the environment.
    # Claude settings also contain explicit deny rules for secrets.
    sys.exit(0)

tool = data.get("tool_name", "")
inp = data.get("tool_input") or {}
cwd = Path(data.get("cwd") or os.getcwd()).resolve()
project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()

cmd = str(inp.get("command", "") or "")
norm_cmd = re.sub(r"\s+", " ", cmd.lower()).strip()

dangerous_patterns = [
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-z]*f[a-z]*d[a-z]*x\b",
    r"\bgit\s+push\b.*(--force|-f)\b",
    r"\brm\s+-rf\s+/(?:\s|$)",
    r"\brm\s+-rf\s+~(?:\s|$)",
    r"\bremove-item\b.*(?:c:\\|/)\s*(?:-recurse|-r)\b",
    r"\bformat-volume\b",
    r"\bclear-disk\b",
]
for pat in dangerous_patterns:
    if re.search(pat, norm_cmd, re.I):
        block(f"GNOSIS policy blocked destructive command: {cmd[:300]}")

# Block accidental modifications to external repository originals.
if tool in {"Write", "Edit"}:
    fp = inp.get("file_path")
    if fp:
        try:
            path = Path(fp).resolve()
            ext = (project / "external" / "repositories").resolve()
            if path == ext or ext in path.parents:
                block("GNOSIS policy: external/repositories is read-only. Copy candidate to an isolated experiment/workspace.")
        except Exception:
            pass

# Block reads of common secrets even if path-based project permission did not catch it.
if tool == "Read":
    fp = str(inp.get("file_path", "")).replace("\\", "/").lower()
    if re.search(r"(^|/)(\.env(?:\.|$)|secrets?/|credentials?/)", fp):
        block("GNOSIS policy: secret/credential file read denied.")

sys.exit(0)
