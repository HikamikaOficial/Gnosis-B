"""Provider adapters: how a real agent CLI satisfies a kernel contract.

The kernel never talks to a provider. It declares a contract — a
`ReviewReport`, a `FixReport` — and an adapter here is what turns some
specific CLI's output into one. Keeping them in their own package is
what makes "provider-neutral by adapters" checkable rather than
aspirational: nothing under `kernel/` may import from here.
"""
