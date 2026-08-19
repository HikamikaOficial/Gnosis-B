#!/usr/bin/env python3
import os, sys
from pathlib import Path

root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
parts = []
for rel in ["docs/PROJECT_STATE.md", "docs/NEXT_ACTIONS.md"]:
    p = root / rel
    if p.exists():
        txt = p.read_text(encoding="utf-8", errors="replace")
        parts.append(f"\n--- {rel} ---\n{txt[:12000]}")
print("GNOSIS durable session context:" + "".join(parts))
