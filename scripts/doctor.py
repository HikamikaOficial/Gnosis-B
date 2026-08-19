#!/usr/bin/env python3
from __future__ import annotations
import json, os, platform, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "research" / "WORKSTATION_DOCTOR.md"
STATE = ROOT / ".gnosis" / "state" / "workstation_doctor.json"

def run(cmd, timeout=12):
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except Exception as e:
        return 999, str(e)

def tool(name, args=("--version",)):
    exe = shutil.which(name)
    if not exe:
        return {"status":"MISSING","path":None,"version":None}
    rc, out = run([exe, *args])
    return {"status":"FOUND","path":exe,"version":out.splitlines()[0] if out else f"rc={rc}"}

def parse_ver(s):
    if not s: return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s)
    return tuple(map(int, m.groups())) if m else None

def main():
    tools = {x: tool(x) for x in [
        "git","python","python3","uv","claude","codex","docker","node","npm","rg"
    ]}
    issues, ok = [], []

    if tools["git"]["status"] == "MISSING":
        issues.append(("BLOCKER","Git missing. Install Git for Windows before autonomous work."))
    if tools["claude"]["status"] == "MISSING":
        issues.append(("BLOCKER","Claude Code missing."))
    else:
        v = parse_ver(tools["claude"]["version"])
        if v and v < (2,1,203):
            issues.append(("HIGH",f"Claude Code {tools['claude']['version']} is older than 2.1.203; update before Ultracode."))
        else:
            ok.append(f"Claude Code: {tools['claude']['version']}")
    if tools["codex"]["status"] == "MISSING":
        issues.append(("HIGH","Codex CLI missing: independent Codex review unavailable."))
    else:
        ok.append(f"Codex CLI: {tools['codex']['version']}")
    if tools["uv"]["status"] == "MISSING":
        issues.append(("MEDIUM","uv missing; install for fast isolated Python tooling."))
    if tools["docker"]["status"] == "MISSING":
        issues.append(("LOW","Docker missing; not a Phase-1 blocker, useful later for sandbox/integration."))

    # Memory CLIs
    for memtool, label in [("m3","M3 Memory"),("zmem","ZMem")]:
        info = tool(memtool)
        tools[memtool] = info
        if info["status"] == "MISSING":
            issues.append(("HIGH", f"{label} CLI not installed yet; Memory Fabric is not ready."))
        else:
            ok.append(f"{label}: {info['version']}")

    result = {
        "schema_version": 2,
        "root": str(ROOT),
        "platform": platform.platform(),
        "tools": tools,
        "issues": [{"severity":s,"message":m} for s,m in issues],
        "strengths": ok,
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    md = ["# GNOSIS Workstation Doctor\n\n", f"- Root: `{ROOT}`\n", f"- Platform: `{result['platform']}`\n\n"]
    md.append("## Tools\n\n| Tool | Status | Version |\n|---|---:|---|\n")
    for n, i in tools.items():
        md.append(f"| {n} | {i['status']} | `{i['version'] or '—'}` |\n")
    md.append("\n## Issues\n\n")
    for s,m in issues:
        md.append(f"- **{s}** — {m}\n")
    if not issues:
        md.append("- ✅ No automated issue detected.\n")
    md.append("\n## Ready items\n\n")
    for x in ok:
        md.append(f"- ✅ {x}\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(md), encoding="utf-8")
    print(OUT)

if __name__ == "__main__":
    main()
