# Gnosis

Gnosis is an autonomous AI software-engineering system. ChatGPT is the
Director/Architect; Claude Code is the Principal Engineer. See CLAUDE.md
for the full engineering constitution.

M0 established the bootstrap kernel: typed contracts, durable state, an
auditable task/run lifecycle, a Claude Code CLI runner, deterministic
verification, git evidence capture, secrets redaction, and a swappable
Director transport. M1 hardened it for real operation: concurrency-safe
run state, PID/start-time-aware crash detection, a durable Director
inbox/outbox protocol, and isolated Git worktree primitives. Milestone
evidence (commit hashes) lives in `.gnosis/state/baselines.json`.

## Layout

    src/gnosis/
      contracts/   DirectorBrief, EngineerReport: typed, validated, round-trippable
      kernel/       ids, state machines, ledger, run store, redaction,
                    verification, git evidence, worktree primitives, atomic
                    writes, cross-process file locking, and the TaskEngine
                    that wires it all together
      runner/       Claude Code CLI subprocess runner, retry policy, PID/
                    start-time process liveness, crash/restart detection
      transport/    DirectorTransport interface plus manual (file-based)
                    and MCP-placeholder implementations
      director/     durable Director inbox/outbox: brief ingestion,
                    dedup, lifecycle persistence, orchestration onto
                    TaskEngine

    .gnosis/
      state/baselines.json       milestone evidence (commit hashes)
      director/{inbox,processed,rejected,outbox,escalations}/
      worktrees/                 isolated per-task Git worktrees

    runs/          durable run directories (gitignored; one per run)
    tests/         unittest suite for every kernel primitive
    docs/          milestone research docs (e.g. M2 candidate comparison)

## Design notes

- No Anthropic API billing, no Agent SDK. src/gnosis/runner/claude_cli_runner.py
  shells out to the locally installed `claude` CLI in -p/--print mode,
  exactly as a human operator would.
- Everything is a file. No database, a run's entire state (meta,
  heartbeat, append-only ledger, raw stdout/stderr, verification result,
  git evidence) lives under runs/<run_id>/. Restarting the kernel process
  is always safe.
- Single-writer, structurally enforced. Every mutable resource (a run's
  meta.json, a run's ledger) has exactly one lock file (kernel.file_lock);
  concurrent writers serialize through it rather than racing. meta.json and
  heartbeat.json are written via write-then-os.replace (kernel.atomic_io),
  so a reader never observes a torn write.
- No infinite retries. RetryPolicy.max_attempts is required and finite;
  execute_with_retry cannot loop forever.
- Crash detection does not trust a bare PID. RecoveryManager combines
  heartbeat staleness with a PID + process-start-time fingerprint
  (runner.liveness), so a run is not mistaken for alive just because its
  old PID was reused by an unrelated process.
- Redaction boundary. Raw stdout/stderr capture is stored verbatim
  (immutable evidence). Anything derived from it that crosses into the
  ledger, a report, or a transport must go through kernel.redaction.redact.
- Director transport is abstracted and now has a real durable protocol.
  src/gnosis/director/ ingests DirectorBrief JSON files dropped in
  .gnosis/director/inbox/, deduplicates by brief_id, executes via
  TaskEngine, and writes EngineerReports to outbox/ (and escalations/ when
  a report demands escalation). McpDirectorTransport remains a
  same-interface placeholder for a future ChatGPT MCP integration.
- Worktrees are a primitive, not a scheduler. src/gnosis/kernel/worktree.py
  creates/removes isolated `gnosis/<task_id>` branches under
  .gnosis/worktrees/. No parallel task scheduling is wired on top of it yet
  (explicit Director decision: run state safety comes first).

## Running the tests

    python -m unittest discover -s tests -t . -v

No external dependencies are required, everything is Python 3.10+ stdlib.
One test (TestRealClaudeCliSmoke) is skipped automatically if the `claude`
CLI is not installed on the machine running the suite.

## Known limitations

See the M0/M1 Engineer Reports for the full list. Highlights: TaskEngine is
still a single-task lifecycle, not a multi-task scheduler (deliberately, a
concurrency-safe run store was the M1 prerequisite for that); the Director
inbox's exclusive-claim check is best-effort under an assumed single
orchestrator process, not yet safe for multiple orchestrator processes;
MCP transport remains unimplemented by design pending a Director-level MCP
architecture decision.
