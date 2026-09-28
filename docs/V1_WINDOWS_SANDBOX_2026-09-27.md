# Native Worker sandbox qualification

Status: IN PROGRESS. This does not close V1 acceptance.

The installed 3a1dc6e project run requested workspace-write, but native Codex
0.148.0 recorded a read-only sandbox in both implementation and correction
sessions. No implementation was produced. The independent Claude review rejected
the missing implementation and tests; the dependent task remained waiting.

The Worker configuration file was absent. Its worktree ACL allowed Modify, so
the write refusal was not explained by the worktree ACL. A non-inference
`debug prompt-input` probe reproduced read-only. Selecting
`windows.sandbox="elevated"` in the otherwise equivalent probe yielded
workspace-write with a restricted filesystem and network. Therefore the trusted
native execution command now selects that implementation explicitly. It retains
workspace-write, approval_policy=never and official ChatGPT authentication.
It does not request unrestricted execution or suppress sandbox setup failures.

Evidence lives in the original workspace under
`.gnosis/evidence/v1-install-director-candidate-20260927/`:

- `worker-permission-context.json`: effective read-only implementation sessions.
- `workspace-config-diagnostic.json`: absent config and observed repository ACLs.
- `worker-sandbox-probe-result.json`: baseline non-inference reproduction.
- `worker-elevated-sandbox-context.json`: restricted writable workspace context.
- `worker-sandbox-write-probe.json`: actual isolated write probe, when completed.

Directed validation: 15 provider-execution tests passed; 47 execution-port,
composition and Worker-review tests passed. Actual sandbox execution and updated
release qualification remain required before deployment.

There is a separate fixture placement defect: its linked Git metadata lives
inside protected supervisor state and is unreadable to the Worker. Preserve the
failed project and its history. Do not relax protected-state ACLs to solve this;
qualify a separate owned repository location with read-only Worker metadata
access before another end-to-end project run.

## Follow-up qualification — 2026-09-28

The elevated implementation failed setup refresh because the workspace belonged
to the Director. Granting ownership in a disposable experiment allowed setup,
but the additional sandbox account could not traverse existing protected roots.
No production ACLs were broadened. The documented `unelevated` implementation
uses a restricted token of the existing Worker; with Worker workspace ownership,
the measured Python runtime successfully wrote/read the assigned directory.
The boundary probe also confirmed the exact cwd and rejected writing a marker
in the separate Worker output area. See `worker-sandbox-boundary-probe.json`.

The candidate therefore explicitly selects `windows.sandbox="unelevated"`.
This is a deliberate compatibility choice, not an automatic runtime downgrade.
It retains restricted-token filesystem isolation; network isolation is weaker
than the separate-account/firewall implementation. No unrestricted option is used.

Production preparation now creates a fresh directory through the existing
contained Worker executor, before Git checks it out. This avoids privileged
ownership transfer and introduces no SeRestorePrivilege requirement. Existing
worktrees are not chowned or reset. Provenance stays in protected Director state.
Preparation failure leaves no branch or successful provenance record. A separate
live probe qualifies this exact creation path; deployment is still pending.

Official reference: https://learn.chatgpt.com/docs/windows/windows-sandbox
