---
name: replay-fingerprint-self-reference
description: GNOSIS record/replay keys the cassette on workspace_fingerprint(cwd), which the recorded agent itself mutates — so multi-call recordings of a file-editing agent cannot replay
metadata:
  type: project
---

`src/gnosis/runner/replay_runner.py` builds its `CallSpec` key from `workspace_fingerprint(cwd)` (HEAD, branch, sha256 of `git status --porcelain`). `cwd` is the same tree the recorded Claude Code agent writes into.

Two consequences that recur whenever this design is touched:

1. **Self-referential key.** Replay reproduces only stdout/stderr, never the agent's repository edits. So call N+1's fingerprint at record time reflects call N's edits, but at replay time it does not — every recording with more than one call against a repo-mutating agent breaks at call 2.
2. **`status --porcelain` is a file LIST, not content.** Editing an already-dirty tracked file leaves the fingerprint unchanged, so two materially different trees collide on one cassette key.

**Why:** ADR-0014 sells the fingerprint as the thing that stops "replaying a recording made against a different tree". It only stops the coarse case, and it creates a worse one.

**How to apply:** any future claim that a GNOSIS run is "deterministically replayable" must be tested with a runner that actually mutates the workspace. `tests/test_replay_runner.py::_ScriptedRunner` writes only to stdout/stderr paths outside the repo, which is why the existing end-to-end test passes despite the defect. Demand that test before accepting the claim.

Related: [[adr-evidence-lines-unverified]]
