# ADR-0003 — M4 memory-provider selection: criteria and benchmark design

- Status: ACCEPTED (criteria; the selection itself is the M4 outcome)
- Date: 2026-08-19
- Deciders: Claude Fable 5 (autonomous)
- Inputs: `gnosis-spec/MEMORY_FABRIC.md` §Memory benchmark,
  `docs/research/MEMORY_FABRIC_STATUS.md`, `docs/M3_MEMORY_PLANE.md`,
  ADR-0001.

## Context

Phase -1 proved both engines have a working integration path (ADR-0001)
but deliberately selected no production `MemoryProvider` adapter. M4
must pick providers per role behind the existing
`gnosis.kernel.memory.MemoryProvider` contract, by benchmark, not by
README.

## Candidate matrix (per MEMORY_FABRIC.md)

Compare, against the same task set: M3 alone; ZMem alone; M3+ZMem
routed by `MemoryRouter`; optionally +structural graph (only if
Graphify/Sverklo earns entry via GNOSIS-Bench first — D-014).

## Metrics (all must be measured, none self-reported)

1. Recall precision/recall on planted-fact retrieval (exact and
   paraphrased queries; m3 measured both with FTS-only and, separately,
   with an embedding tier configured — the Phase -1 caveat).
2. Stale-memory rate: superseded/revoked facts surfacing in default
   retrieval.
3. Duplicate and contradiction rates in injected context.
4. Context tokens consumed per injection (budget discipline).
5. Retrieval latency and write overhead (cold and warm, Windows).
6. Cross-agent/cross-session continuity (the smoke test generalized).
7. Task success impact: end-to-end effect on a small fixed task suite —
   the only metric that can justify keeping a layer (MEMORY_FABRIC rule:
   a layer stays only if measurable benefit exceeds complexity/cost).

## Hard gates carried into M4

- m3: env-pinned roots only, never `--database` (L-0003); `PYTHONUTF8=1`
  pinned (L-0001); `m3 setup`/secondary-payload flow needs a dedicated
  supply-chain review before it may run.
- zmem: caller must drive supersession explicitly (no automatic
  same-label lineage — M3-milestone finding, re-confirmed on 0.1.17);
  `audit health` is the Windows health probe (L-0002).
- No memory backend mutates Task state or bypasses the Kernel/Policy
  Engine (constitution); adapters shell out via the provider contract,
  mirroring `CodegraphMcpAdapter`.

## Decision rule

A provider is adopted for a role only if it beats the
`InMemoryMemoryProvider` reference AND the null configuration (no
memory) on metric 7 without regressing metrics 2–5 beyond agreed
thresholds, with the comparison script and raw outputs committed under
`.gnosis/lab/memory/results/` as evidence.
