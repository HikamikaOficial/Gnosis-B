#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p \
  .gnosis/{runtime,workspaces,logs,traces,artifacts,state} \
  docs/{adr,research} \
  lab/learning/{candidates,promoted} \
  lab/training/{datasets,experiments,models} \
  benchmarks experiments src/gnosis \
  tests/{unit,integration,recovery,security,chaos}

REPORT="docs/research/BOOTSTRAP_REPORT.md"
{
  echo "# GNOSIS Bootstrap Report"
  echo
  echo "**Generated:** $(date -Iseconds)"
  echo "**Root:** \`$ROOT\`"
  echo
} > "$REPORT"

check_cmd () {
  if command -v "$1" >/dev/null 2>&1; then
    echo "- [x] $1 — $("$1" --version 2>&1 | head -n1 || echo installed)" >> "$REPORT"
    return 0
  else
    echo "- [ ] $1 — NOT FOUND" >> "$REPORT"
    return 1
  fi
}

HAS_GIT=0; check_cmd git && HAS_GIT=1 || true
if [[ "$HAS_GIT" == "1" && ! -d .git ]]; then
  git init >/dev/null
  git branch -M main 2>/dev/null || true
  echo "- Initialized local Git repository." >> "$REPORT"
elif [[ "$HAS_GIT" == "0" ]]; then
  echo "- [!] Git is required before repository initialization." >> "$REPORT"
fi

HAS_PY=0; check_cmd python3 && HAS_PY=1 || true
check_cmd claude || true
check_cmd codex || true
check_cmd uv || true
check_cmd docker || true

if [[ "$HAS_PY" == "1" ]]; then
  PY="$(command -v python3)"
  cat > .claude/settings.local.json <<EOF
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|PowerShell|Read|Edit|Write",
        "hooks": [
          {"type":"command","command":"$PY \"$ROOT/.claude/hooks/policy_gate.py\"","timeout":10}
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash|PowerShell|Read|Edit|Write",
        "hooks": [
          {"type":"command","command":"$PY \"$ROOT/.claude/hooks/audit_event.py\"","timeout":10}
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {"type":"command","command":"$PY \"$ROOT/.claude/hooks/session_context.py\"","timeout":10}
        ]
      }
    ]
  }
}
EOF
  echo "- [x] Local deterministic hooks configured." >> "$REPORT"
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv || true
    [[ -d .venv ]] && echo "- [x] Created .venv." >> "$REPORT"
  fi
else
  echo "- [!] Hooks not enabled because python3 was not found." >> "$REPORT"
fi

cat >> "$REPORT" <<'EOF'

## Next

1. Start Claude Code in this root.
2. Read `01_START_HERE.md`.
3. Claude audits missing tools and installs only justified dependencies from official sources.
4. Place external repositories under `external/repositories/`.
EOF

echo "GNOSIS bootstrap complete. See $REPORT"
