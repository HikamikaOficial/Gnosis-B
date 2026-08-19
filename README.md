# Gnosis, M0 Bootstrap Kernel

Gnosis is an autonomous AI software-engineering system. ChatGPT is the
Director/Architect; Claude Code is the Principal Engineer. See CLAUDE.md
for the full engineering constitution.

This is the M0 bootstrap kernel: the smallest reliable substrate the rest
of Gnosis (memory, councils, Night Cycle, worktrees, replay,
self-improvement) will be built on top of. It intentionally does none of
those things yet, it establishes typed contracts, durable state, an
auditable task/run lifecycle, a Claude Code CLI runner, deterministic
verification, git evidence capture, secrets redaction, and a swappable
Director transport.

## Layout

    gnosis/
      contracts/   DirectorBrief, EngineerReport: typed, validated, round-trippable
      kernel/       ids, state machines, ledger, run store, redaction,
                    verification, git evidence, and the TaskEngine that
                    wires it all together
      runner/       Claude Code CLI subprocess runner, retry policy,
                    crash/restart detection and recovery
      transport/    DirectorTransport interface plus manual (file-based)
                    and MCP-placeholder implementations

    runs/          durable run directories (gitignored; one per run)
    tests/         unittest suite for every kernel primitive

## Design notes

- No Anthropic API billing, no Agent SDK. gnosis/runner/claude_cli_runner.py
  shells out to the locally installed `claude` CLI in -p/--print mode,
  exactly as a human operator would.
- Everything is a file. No database, a run's entire state (meta,
  heartbeat, append-only ledger, raw stdout/stderr, verification result,
  git evidence) lives under runs/<run_id>/. Restarting the kernel process
  is always safe.
- No infinite retries. RetryPolicy.max_attempts is required and finite;
  execute_with_retry cannot loop forever.
- Redaction boundary. Raw stdout/stderr capture is stored verbatim
  (immutable evidence). Anything derived from it that crosses into the
  ledger, a report, or a transport must go through kernel.redaction.redact.
- Director transport is abstracted. ManualDirectorTransport (JSON files on
  disk) is wired up today. McpDirectorTransport is a same-interface
  placeholder for a future ChatGPT MCP integration, swap one for the other
  without touching kernel code.

## Running the tests

    python -m unittest discover -s tests -t . -v

No external dependencies are required, everything is Python 3.10+ stdlib.
One test (TestRealClaudeCliSmoke) is skipped automatically if the `claude`
CLI is not installed on the machine running the suite.

## Known M0 limitations

See the M0 Engineer Report for the full list. Highlights: the ledger's
append-only guarantee is API-level, not filesystem-level; TaskEngine is a
single-task lifecycle, not a multi-task scheduler; MCP transport is
unimplemented by design; run concurrency (multiple engines writing the
same run's ledger from different threads/processes) is out of scope.
