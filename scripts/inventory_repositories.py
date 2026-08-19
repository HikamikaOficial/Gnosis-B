#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, re, subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = PROJECT_ROOT / "resources" / "repositories.json"
STATE_DIR = PROJECT_ROOT / ".gnosis" / "state"
LOCAL_LOCATIONS = PROJECT_ROOT / "resources" / "locations.local.json"

SKIP = {".git", "node_modules", ".venv", "venv", "target", "dist", "build", "__pycache__", ".cache"}

def norm_remote(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip()
    m = re.match(r"(?:ssh://)?git@github\.com[:/](.+?)(?:\.git)?$", u, re.I)
    if m:
        return "github.com/" + m.group(1).removesuffix(".git").strip("/").lower()
    m = re.search(r"github\.com/(.+)", u, re.I)
    if m:
        tail = m.group(1).split("#",1)[0].split("?",1)[0].removesuffix(".git").strip("/")
        return "github.com/" + tail.lower()
    return None

def git_origin(path: Path) -> str | None:
    try:
        p = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            text=True, capture_output=True, timeout=5
        )
        return p.stdout.strip() if p.returncode == 0 else None
    except Exception:
        return None

def walk_repos(root: Path, max_depth=5):
    if not root.exists():
        return
    root = root.resolve()
    for cur, dirs, files in os.walk(root):
        p = Path(cur)
        depth = len(p.relative_to(root).parts)
        dirs[:] = [d for d in dirs if d not in SKIP]
        if (p / ".git").exists():
            yield p
            dirs[:] = []
        elif depth >= max_depth:
            dirs[:] = []

def default_roots():
    roots = []
    env = os.environ.get("GNOSIS_REPOSITORIES_ROOT")
    if env:
        roots.append(Path(env))
    roots += [
        PROJECT_ROOT / "external" / "repositories",
        PROJECT_ROOT / "repos",
        PROJECT_ROOT.parent / "repositories",
    ]
    return roots

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", action="append", default=[])
    ap.add_argument("--max-depth", type=int, default=5)
    args = ap.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    expected = {
        "github.com/" + r["owner_repo"].lower(): r
        for r in registry["repositories"]
    }
    roots = default_roots() + [Path(x) for x in args.root]

    unique_roots, seen = [], set()
    for x in roots:
        try:
            rp = x.expanduser().resolve()
        except Exception:
            continue
        k = str(rp).lower()
        if k not in seen:
            seen.add(k); unique_roots.append(rp)

    found = {}
    unknown = []
    for scan_root in unique_roots:
        if not scan_root.exists():
            continue
        for p in walk_repos(scan_root, args.max_depth):
            origin = git_origin(p)
            key = norm_remote(origin)
            if key in expected:
                found.setdefault(key, []).append({
                    "path": str(p),
                    "origin": origin,
                    "match": "git_remote_origin"
                })
            else:
                unknown.append({"path": str(p), "origin": origin})

    results = []
    for key, r in expected.items():
        matches = found.get(key, [])
        results.append({
            "name": r["name"],
            "tier": r["tier"],
            "github_url": r["github_url"],
            "status": "FOUND" if matches else "MISSING",
            "matches": matches,
        })

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 2,
        "project_root": str(PROJECT_ROOT),
        "scan_roots": [str(x) for x in unique_roots],
        "found": sum(x["status"] == "FOUND" for x in results),
        "missing": sum(x["status"] == "MISSING" for x in results),
        "results": results,
        "unknown_git_repositories": unknown,
    }
    (STATE_DIR / "repository_inventory.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    LOCAL_LOCATIONS.write_text(
        json.dumps({
            "schema_version": 2,
            "project_root": str(PROJECT_ROOT),
            "repositories_roots": [str(x) for x in unique_roots if x.exists()],
            "inventory": str(STATE_DIR / "repository_inventory.json"),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    report = PROJECT_ROOT / "docs" / "research" / "REPOSITORY_INVENTORY.md"
    md = [
        "# GNOSIS Repository Inventory\n\n",
        f"- Project: `{PROJECT_ROOT}`\n",
        f"- Found: **{state['found']} / {len(results)}**\n",
        f"- Missing: **{state['missing']}**\n\n",
        "## Registered S+/S/A resources\n\n",
        "| Tier | Resource | Status | Local path | GitHub |\n|---|---|---:|---|---|\n",
    ]
    for x in results:
        if str(x["tier"]).startswith("S") or str(x["tier"]).startswith("A"):
            local = x["matches"][0]["path"] if x["matches"] else "—"
            md.append(f"| {x['tier']} | {x['name']} | **{x['status']}** | `{local}` | {x['github_url']} |\n")
    md.append("\n## Missing\n\n")
    for x in results:
        if x["status"] == "MISSING":
            md.append(f"- [{x['tier']}] **{x['name']}** — {x['github_url']}\n")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("".join(md), encoding="utf-8")

    print(f"Found {state['found']}/{len(results)} registered resources.")
    print(report)

if __name__ == "__main__":
    main()
