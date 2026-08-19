#!/usr/bin/env python3
"""Clone registered reference repositories into external/repositories.

Registry-driven (resources/repositories.json), tier-filtered, shallow by
default. Never touches an existing clone beyond reading its origin; the
originals stay READ-ONLY SOURCE per CLAUDE.md.

Usage:
    python scripts/clone_tier_repositories.py [--tiers S+,S] [--deep name ...]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "resources" / "repositories.json"
DEST = ROOT / "external" / "repositories"
REPORT = ROOT / ".gnosis" / "state" / "clone_report.json"

# Repositories we must not copy at all, with the evidence for why.
DENYLIST = {
    "https://github.com/Dicklesworthstone/cass_memory_system": (
        "LICENSE rider explicitly bars Anthropic-affiliated use, copying, "
        "benchmarking or analysis; see "
        ".gnosis/lab/memory/results/cass_memory_system/LICENSE_FINDING.md"
    ),
}

CLONE_TIMEOUT_S = 600


def repo_dir_name(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def existing_origin(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    p = subprocess.run(
        ["git", "-C", str(path), "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=30,
    )
    return p.stdout.strip() if p.returncode == 0 else None


def clone_one(entry: dict, deep: bool) -> dict:
    url = entry["github_url"]
    name = entry.get("name", url)
    target = DEST / repo_dir_name(url)
    result = {"name": name, "tier": entry.get("tier"), "url": url,
              "target": str(target), "shallow": not deep}

    if url in DENYLIST:
        result["status"] = "SKIPPED_LICENSE"
        result["detail"] = DENYLIST[url]
        return result

    origin = existing_origin(target)
    if origin is not None:
        if origin.rstrip("/").removesuffix(".git") == url.rstrip("/").removesuffix(".git"):
            head = subprocess.run(
                ["git", "-C", str(target), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()
            result["status"] = "ALREADY_PRESENT"
            result["head"] = head
        else:
            result["status"] = "ORIGIN_MISMATCH"
            result["detail"] = f"existing origin: {origin}"
        return result
    if target.exists():
        result["status"] = "DIR_EXISTS_NOT_GIT"
        return result

    argv = ["git", "clone", "--quiet"]
    if not deep:
        argv += ["--depth", "1"]
    argv += [url, str(target)]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=CLONE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        result["status"] = "TIMEOUT"
        return result
    if p.returncode == 0:
        head = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        result["status"] = "CLONED"
        result["head"] = head
    else:
        result["status"] = "CLONE_FAILED"
        result["detail"] = (p.stderr or p.stdout).strip()[:500]
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="S+,S",
                    help="comma-separated tier prefixes to include")
    ap.add_argument("--include", nargs="*", default=[],
                    help="extra repo names to include regardless of tier")
    ap.add_argument("--deep", nargs="*", default=[],
                    help="repo names to clone with full history")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    selected = [
        r for r in data["repositories"]
        if any(r.get("tier", "").startswith(t) for t in tiers)
        or r.get("name") in args.include
    ]
    DEST.mkdir(parents=True, exist_ok=True)

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(clone_one, r, r.get("name") in args.deep): r for r in selected}
        for fut in as_completed(futs):
            res = fut.result()
            results.append(res)
            print(f"{res['status']:<20} {res['tier']:<12} {res['name']}")

    results.sort(key=lambda r: (r["status"], r["name"]))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(
        {"schema_version": 1, "tiers_requested": tiers, "results": results},
        indent=2), encoding="utf-8")
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"\nreport: {REPORT}\ncounts: {json.dumps(counts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
