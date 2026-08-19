# GNOSIS Construction Autonomy Policy

## Agent should NOT ask human for

- reversible implementation choices;
- naming/style choices;
- whether to run tests;
- whether to repair a failing test caused by its change;
- whether to inspect a local repo;
- whether to create an ADR;
- whether to continue to the next defined gate;
- which of two technically comparable reversible approaches to choose.

## Agent should decide using

1. evidence;
2. project principles;
3. risk;
4. reversibility;
5. simplicity;
6. benchmark if material.

## Actions that must not be silently executed

- public publishing/deployment;
- payments/cloud spend;
- destructive operations on personal/external data;
- credential rotation;
- force push/destructive Git;
- global security weakening;
- installing/running HIGH/CRITICAL untrusted external code without isolation;
- production DB migrations with irreversible effects.

If one action is blocked, continue every other safe task.
