#!/usr/bin/env python3
from __future__ import annotations
import json, shutil, subprocess, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "research" / "MEMORY_FABRIC_STATUS.md"

def run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except Exception as e:
        return 999, str(e)

def cmd_status(name, checks):
    exe = shutil.which(name)
    row = {"name":name, "found":bool(exe), "path":exe, "checks":[]}
    if exe:
        for c in checks:
            rc, out = run([exe, *c])
            row["checks"].append({"args":c,"rc":rc,"output":out[:3000]})
    return row

def main():
    m3 = cmd_status("m3", [["--version"], ["doctor"]])
    zmem = cmd_status("zmem", [["--version"], ["status","--summary-only"]])
    inv_file = ROOT / ".gnosis" / "state" / "repository_inventory.json"
    inv = json.loads(inv_file.read_text(encoding="utf-8")) if inv_file.exists() else None

    def local_for(substr):
        if not inv: return []
        out=[]
        for r in inv.get("results", []):
            if substr.lower() in r.get("github_url","").lower():
                out += [m["path"] for m in r.get("matches",[])]
        return out

    md = [
        "# GNOSIS Memory Fabric Status\n\n",
        "## Required architecture\n\n",
        "- **M3** = broad recall / cross-agent retrieval.\n",
        "- **ZMem** = trust, authority, quarantine, lineage, receipts.\n",
        "- **Graphify** = optional structural code graph after benchmark.\n",
        "- **Obsidian** = optional human-readable mirror only.\n\n",
        "## Local clones\n\n",
        f"- M3: {local_for('skynetcmd/m3-memory') or 'NOT RESOLVED'}\n",
        f"- ZMem: {local_for('zerkerlabs/zmem') or 'NOT RESOLVED'}\n",
        f"- Graphify: {local_for('Graphify-Labs/graphify') or 'NOT RESOLVED'}\n\n",
        "## CLI state\n\n",
        f"- M3: **{'FOUND' if m3['found'] else 'MISSING'}** — `{m3['path']}`\n",
        f"- ZMem: **{'FOUND' if zmem['found'] else 'MISSING'}** — `{zmem['path']}`\n\n",
    ]
    for label, data in [("M3",m3),("ZMem",zmem)]:
        if data["checks"]:
            md.append(f"### {label} checks\n\n")
            for c in data["checks"]:
                md.append(f"- `{label.lower()} {' '.join(c['args'])}` → rc={c['rc']}\n\n```text\n{c['output']}\n```\n")
    md.append("\n## Gate\n\nMemory Fabric is READY only after both primary engines are installed, connected to the active Claude/Codex environment where supported, and pass a synthetic cross-session continuity/governance smoke test.\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(md), encoding="utf-8")
    print(OUT)

if __name__ == "__main__":
    main()
