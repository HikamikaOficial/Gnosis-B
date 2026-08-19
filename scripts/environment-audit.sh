#!/usr/bin/env bash
set +e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT="docs/research/ENVIRONMENT_AUDIT_AUTOMATED.md"

{
  echo "# Automated Environment Audit"
  echo
  echo "Generated: $(date -Iseconds)"
  echo "Root: $ROOT"
  echo
  for c in git python3 uv claude codex docker node npm; do
    if command -v "$c" >/dev/null 2>&1; then
      echo "- $c: $("$c" --version 2>&1 | head -n1)"
    else
      echo "- $c: NOT FOUND"
    fi
  done
  echo
  echo "## Git"
  git status --short --branch 2>&1
  git rev-parse --show-toplevel 2>&1
  echo
  echo "## External repository count"
  if [[ -d external/repositories ]]; then
    count=$(find external/repositories -type d -name .git 2>/dev/null | wc -l)
    echo "- Git repositories discovered: $count"
  fi
} > "$OUT"

echo "Wrote $OUT"
