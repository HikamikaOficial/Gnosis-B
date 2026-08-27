# F-17 Stage 2 (trust-plane deployment identity) evidence

Stage 1 CLOSED at `ad06b09`; Stage 2 authorized. Implementation tree at HEAD
`e648784`.

**This bundle certifies a PRIMITIVE, not an installation.** Nothing was
deployed: no `GnosisTrustedPublisher` service, no Worker account, no DPAPI
secret, no production AnchorStore or RunIdentity store, no engine/runner change,
no pipeline wiring, no unknown-`.git` enforcement, no `AnchorRecord` schema
change. The OS-real tests observe only objects that already exist — a temporary
directory, this interpreter, and an EXISTING Windows service read-only — and
leave nothing behind.

The property: **what is executed == what is measured == what is bound into
evidence.** `TrustPlaneDeploymentIdentity` is assembled entirely from real
system queries; `DesiredDeploymentConfig` supplies only WHERE to look, and
`compare_with_desired` is the single function that reads an intention at all. A
different intention over the same machine keeps the digest; a changed machine
under the same intention moves it; and no sentinel expectation value can appear
anywhere in the serialized identity.

Security descriptors are parsed from the BINARY descriptor through the Win32
accessors, never from `icacls`/`sc sdshow` text. Canonicalization normalizes
REPRESENTATION and preserves SEMANTICS: **ACE order is not sorted and no ACE is
dropped as redundant** — the declared cost is that an order-only difference
reads as drift, which fails closed, rather than as a match.

`AnchorRecord` was deliberately NOT extended: binding `deployment_digest` needs
Stage 3/6 to supply it, and an always-empty field would be a decorative field
that affects no guarantee. Recorded as a STOP, with the `gnosis.anchor.v2` path
written down for the stage that owns it.

TOCTOU is declared, not solved: hashing is DETECTION and BINDING, ACL/SID is
PREVENTION.

Directed 97 passed; fresh checkout of `e648784` 91 passed; mutation 11/11 CAUGHT
(0 survived); mypy clean over 63 source files; ruff clean on every new and
changed file; negative control and secret scan (0 findings) captured.
`gnosis.trust.anchor`'s load-time closure is UNCHANGED at 522 LOC — the
publisher's runtime trusted closure did not grow — while the Trust Plane grew to
1574 LOC, reported not absorbed.

Stage 3 NOT started. F-17 stays OPEN. See `STAGE2-RESULTS.txt`.
