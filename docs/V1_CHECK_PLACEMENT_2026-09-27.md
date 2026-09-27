# Verification orchestration placement — 2026-09-27

Full regression at 06d1d0f exposed an architecture violation: check execution and
recovery orchestration lived in gnosis.trust and imported application dependencies
outside the qualified trust closure. The trust-boundary guard correctly rejected it.

Move these two new modules to gnosis.director beside trusted_runner and execution.
They consume the existing WorkerLauncher and sealed LaunchSpec; they do not add
an authority primitive or change publication decisions. Worker identity transition,
job containment, bounded retained outputs, attempt locking, and crash recovery
behavior are unchanged. Production composition imports the Director implementation.

The deterministic deployment closure now measures these modules and the check
protocol as application code, outside the publisher trust closure. Both remain
protected by the existing composed application identity check. No trust allowlist,
policy, evaluator, baseline, or acceptance rule is modified. Test imports follow
the relocated implementation; their assertions remain unchanged.

Validation: full-source strict typing passes (104 modules). Targeted trust-boundary,
execution, recovery, composition and packaging results are recorded separately in
.gnosis/evidence/v1-verifier-isolation-20260927/director-check-boundary.xml in the
original checkout. Full candidate qualification and real deployment remain pending.
