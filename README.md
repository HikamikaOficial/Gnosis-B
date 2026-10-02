# Gnosis

Gnosis is a local, autonomous AI software-engineering system. Its
architecture is **kernel-authoritative** and **provider-neutral at the
adapter boundary**: the kernel — not any language model — authorizes state
transitions, gates,
permissions, integration, and promotion. Agents (used during development
and review) only *propose*; the kernel decides. See `CLAUDE.md` for the
full engineering constitution.

This README is a first-contact overview. The authoritative, live project
state lives in `docs/PROJECT_STATE.md`; the architecture and every design
decision are recorded as ADRs under `docs/adr/`.

## Current status

Gnosis is under active development and has advanced well beyond its
original M0/M1 bootstrap. Current surfaces include a hardened kernel, a
governed execution pipeline, a multi-worker plane (durable queue, budget,
cross-task ordering), review convergence and result integration,
multi-credential rotation, and a qualified Trust Plane / Publisher
boundary (F-17). For the exact, up-to-date status see
`docs/PROJECT_STATE.md`. Historical milestones (M0/M1) are recorded in the
project state and the early ADRs; they no longer describe the whole
system.

## Architecture (overview)

Detail lives in the ADRs; this is orientation only.

- **Kernel** (`src/gnosis/kernel/`) — canonical hashing and a chained,
  append-only ledger (ADR-0004); a fenced lease plane (ADR-0005) and
  two-plane claims with engine fencing (ADR-0006); durable run store and
  state machines; a **fail-closed policy / authority** gate (ADR-0011,
  ADR-0013); a typed failure taxonomy (ADR-0012); evidence capture and
  redaction.
- **Director orchestration** (`src/gnosis/director/`) — a durable
  `DirectorBrief` inbox/outbox convention, a governed pipeline (ADR-0017),
  a multi-worker queue with per-brief budget and cross-task ordering
  (ADR-0019, ADR-0020), and worker supervision/backoff (ADR-0022).
- **Adapters** (`src/gnosis/adapters/`) — the review-convergence loop
  (ADR-0008, ADR-0015) and result integration onto a shared branch
  (ADR-0018).
- **Credentials** (`src/gnosis/kernel/credentials.py`) — multi-credential
  rotation (ADR-0024).
- **Trust Plane, Publisher and provisioning** (`src/gnosis/trust/`,
  `src/gnosis/provision/`) — an authoritative-publication boundary with
  evidence/provenance binding (ADR-0025–ADR-0029), the composed trust path
  (ADR-0028), and provisioning that realizes the OS boundaries (ADR-0030).

The **Director** is a local orchestration component, not a language
model: typed `DirectorBrief` JSON files drive the kernel through the
policy gate. Gnosis has no third-party Python runtime package
dependencies — the core package uses the standard library
(`dependencies = []`) — and it embeds no provider SDK. Provider-backed
execution is mediated through adapters, not an in-process SDK. The
currently wired execution path uses `ClaudeCodeCLIRunner`
(`src/gnosis/runner/claude_cli_runner.py`), which invokes a locally
installed `claude` CLI; that executable and its provider access are
therefore operational dependencies for that execution capability. The
kernel and orchestration core (ledger, claims, lease, policy/authority,
run store, queue) run without invoking a provider; producing new agent
work does not. Codex is used as development/review tooling and is not
wired into the runtime execution path. "Provider-neutral" here describes
the adapter/interface boundary, not the absence of provider-specific
tooling in the shipped execution path. A ChatGPT / MCP Director
transport exists in the tree only as an **unimplemented placeholder**
(`src/gnosis/transport/mcp_transport.py`).

## Trust / security model

Later work introduced a Worker ↔ Publisher trust boundary: a dedicated,
de-privileged Worker runs agent work, and only a restricted Publisher can
produce an authoritative publication, bound to tamper-evident evidence.
**F-14 is CLOSED and F-17 is CLOSED** (closure record: `docs/adr/ADR-0031-f17-closed.md`).
The qualified claim, in ADR-0031's own words, is that *under the
documented Windows / Git 2.55.x files-backend / Python-runtime /
deployment contract, a compromised dedicated Worker cannot cause an
authoritative historical-evidence publication that the trusted plane did
not authorize*, and relevant unsupported or ambiguous conditions fail
closed. This is a
**production-equivalent qualification under that contract** — not a
claim of a live production deployment. See ADR-0031 for the exact boundary
and the formal non-claims.

## Repository layout

    src/gnosis/     production source; import namespace `gnosis` (ADR-0002)
      contracts/    typed, validated, round-trippable DirectorBrief / EngineerReport
      kernel/       hashing, ledger, lease/claims, run store, policy/authority,
                    evidence capture, redaction, failure taxonomy
      director/     durable brief inbox/outbox, governed pipeline, work queue,
                    ordering, supervision
      runner/       Claude Code CLI subprocess runner, retry, liveness, recovery, replay
      adapters/     review convergence + result integration
      transport/    DirectorTransport interface (manual file transport; MCP placeholder)
      trust/        Trust Plane, Publisher, run identity, deployment identity
      provision/    provisioning that realizes the OS deployment boundaries

    tests/          the test suite
    docs/           project state, ADRs, audit
    docs/adr/       architecture decision records (ADR-0001 … ADR-0031)
    .gnosis/        runtime-mutable state (director inbox/outbox, worktrees, evidence)

The canonical filesystem source layout is `src/gnosis/`; the Python import
namespace is `gnosis` (ADR-0002). There is no root production `gnosis/`
tree.

## Requirements

- **Python >= 3.12** (declared in `pyproject.toml`). The Trust Plane is
  qualified on CPython 3.12.x; a version merely permitted by the
  constraint is not automatically a qualified runtime.
- **Runtime dependencies: none** — the production runtime is stdlib-only
  (`pyproject.toml` declares `dependencies = []`; the CLI runner shells
  out to a locally installed `claude` CLI rather than using any SDK or
  billed API).
- **Development / testing tooling** (third-party, declared under the
  `dev` optional-dependencies): `pytest`, `pytest-asyncio`, `ruff`,
  `mypy`.

## Installation

Gnosis is a `src`-layout package built with `hatchling`. For development,
either install it editable into a virtual environment
(`pip install -e ".[dev]"`) or run it with `uv` without a persistent
install (see below). No third-party packages are needed to import and run
the `gnosis` runtime itself.

## Quick start

The Director consumes typed briefs from a durable inbox: drop a
`DirectorBrief` JSON file into `.gnosis/director/inbox/`; it is claimed
(deduplicated by `brief_id`), executed through the kernel via the
`TaskEngine`, and an `EngineerReport` is written to
`.gnosis/director/outbox/` (or `.gnosis/director/escalations/` when a
report demands escalation). See `src/gnosis/director/` for the exact
convention.

## Testing / qualification

The canonical test runner is **pytest** (configured in `pyproject.toml`
with `pythonpath = ["src"]`). For example, without a persistent install:

    uv run --no-project --with pytest --with pytest-asyncio pytest

The tests are authored as `unittest.TestCase` classes and run under
pytest. The latest qualified full-suite result is checkpoint-qualified —
see `docs/PROJECT_STATE.md` and `docs/adr/ADR-0031-f17-closed.md` for the
current qualified checkpoint and its evidence bundle. (This README
intentionally does not hardcode a test count.)

## Documentation

- `docs/PROJECT_STATE.md` — live, detailed project status.
- `docs/adr/` — architecture decision records (ADR-0001 … ADR-0031).
- `docs/adr/ADR-0031-f17-closed.md` — the F-17 trust-boundary closure and
  its qualified claim / non-claims.
- `docs/V1_TRACEABILITY_AUDIT.md` — the V1 traceability audit register.
- `CLAUDE.md` — the engineering constitution and operating rules.

## Known boundaries / non-claims

- The Trust Plane qualification is **contract-bounded** (Windows;
  Git 2.55.x `files` ref backend; a qualified CPython 3.12 runtime and
  deployment shape). It does not imply arbitrary future platform, Git,
  Python, or provider compatibility. See ADR-0031 for the exact contract
  and the formal non-claims.
- The MCP / ChatGPT Director transport is unimplemented (placeholder).
- Gnosis is provider-neutral at the adapter/interface boundary and embeds
  no provider SDK as a Python runtime dependency; provider-backed execution
  is mediated through adapters/external tools, and the currently wired
  execution path uses the local `claude` CLI.
