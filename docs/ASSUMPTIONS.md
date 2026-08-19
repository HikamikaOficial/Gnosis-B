# GNOSIS Assumptions Register

Assumptions are not facts.

## A-001
**Assumption:** Python 3.12+ + SQLite is sufficient for the V1 local kernel.  
**Status:** PROVISIONAL  
**Reopen if:** benchmarks show concurrency/durability requirements exceed the design.

## A-002
**Assumption:** Windows host + WSL2 is the preferred target when available.  
**Status:** PROVISIONAL  
**Reopen if:** target machine constraints or filesystem/worktree benchmarks favor native Windows.

## A-003
**Assumption:** Claude/Fable as worker + Codex as independent reviewer is a strong initial pairing.  
**Status:** PROVISIONAL  
**Reopen if:** GNOSIS-Bench writer/reviewer matrix shows another direction is superior.
