# V1 real deployment preparation

Status: preparation only; no account, service, ACL, authentication or installation
was changed. Source/tests remain frozen for regression session 18197.

## Verified inputs

Read-only observation is saved at
`.gnosis/evidence/v1-deployment-preflight-20260927/preflight.json`.
The current process is DESKTOP-VTQPQVL/nicol, not elevated. Python base runtime is
the existing uv CPython 3.12 Windows installation. Official native Codex is present
(codex-cli 0.148.0), SHA256
`2ad2cf8a732da68b8f141634f92db1a03016c5faf533a7225fbc0fb740130410`.
Proposed dedicated account `gnosis-v1w0927` and service
`GnosisAgentBV1Publisher` do not exist at observation time. Recheck before creation;
these names are not ownership evidence. Existing gnosis-wrk56 and Gnosis Control
resources are outside this preparation and must not be repurposed.

## Confirmed implementation gap in qualification bootstrap

`Provisioner.codex_runtime_src` copies the native bundle inside the measured
runtime before ACLs and deployment observation. `bind_codex_runtime` requires
`providers/codex/codex.exe` in that exact tree. However,
`scripts/stage2cb.py::Stage2CBConfig` and `make_base_provision` do not carry that
source through to Provisioner. The historical B1 driver also emits deterministic
execution and a no-op verifier. Running it unchanged would not validate real V1.

After the frozen suite ends, add an explicit trusted provider-bundle input to
the bootstrap, preserving all existing defaults and gates. Verify through the
filesystem-backed dry provisioning path that the native bundle is copied before
measurement, and reject a missing executable. Do not side-copy it after measuring
or modify observer/qualification rules to accept absent files.

### Native package layout mismatch confirmed

The installed native distribution is package-layout version 1. Its root contains
`codex-package.json` declaring entrypoint `bin/codex.exe`, resources directory
`codex-resources`, and path directory `codex-path`. Actual files are:

- bin/codex.exe
- bin/codex-code-mode-host.exe
- codex-path/rg.exe
- codex-resources/codex-command-runner.exe
- codex-resources/codex-windows-sandbox-setup.exe

Current Provisioner checks `<codex_runtime_src>/codex.exe`, and bind_codex_runtime
expects `providers/codex/codex.exe`. Passing only the bin directory satisfies
those checks but omits the package descriptor and Windows sandbox/search helpers.
That is not a complete deployment of this installed version. Update the provider
staging/binding to preserve the vendor package layout and resolve its validated
native entrypoint within the measured tree. Do not flatten the package or disable
the sandbox to compensate for missing helpers. Add coverage for the real layout
and absent/escaping descriptor entries after regression 18197 completes.

The historical Stage2CBOrchestrator always rolls back in finally. Retain it as a
disposable qualification harness. A usable persistent V1 installation needs an
explicit install/verify/uninstall lifecycle consuming the same provisioners and
ownership journal, with a proper generated Worker password protected by existing
DPAPI handling; do not adopt the historical harness's default test password.

## Required real qualification flow

1. Pin the final source snapshot, runtime and native provider bundle; prepare a
   separate disposable Git project with two dependent tasks and a meaningful
   deterministic verifier. Select provider-backed Codex execution and explicit
   integration through the canonical configuration writer.
2. Install a new dedicated deployment using existing F-17 and composed provisioners,
   their ownership journal and fresh measurements. This requires Windows elevation;
   never substitute the current medium-integrity token or reuse unknown residue.
3. Establish ChatGPT login in the dedicated Worker's own Windows profile, then
   verify authentication from that account. The adapter must not inherit the
   Director's login. No credential copy, paid API key, alternate auth method or
   sandbox weakening is part of this plan.
4. Run the canonical project CLI against the deployed application. Preserve raw
   provider output, observed Worker identity, fresh deployment identity, review,
   verifier, proof, Publisher anchor and final Git changes.
5. Exercise interruption and recovery with the real Worker/service and repeat the
   final evidence checks. Stop and classify infrastructure/auth/quota failures
   accurately. Retain resumable work; do not call an infrastructure refusal success.

Official authentication guidance confirms `codex login`, `codex login status`
and optional device-code login for remote environments:
[OpenAI authentication documentation](https://learn.chatgpt.com/docs/auth).
The installed CLI help confirms `--device-auth`. A browser/device-code sign-in
would require the account holder's interaction; it has not been started. This
remains ChatGPT subscription authentication. General alternatives described in
the documentation do not override this project's authentication constraint.

## Next action

Poll regression 18197 without restarting. Implement and test the bootstrap
connection after it is terminal, then prepare concrete deployment inputs before
requesting any necessary user interaction for elevation/login. No current claim
of real-provider or service qualification is made.
