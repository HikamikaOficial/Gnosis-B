# GNOSIS Threat Model — Seed

## Assets

- source code;
- Git history;
- credentials;
- local filesystem;
- user accounts/subscriptions;
- policy rules;
- evaluator/baseline;
- durable task state;
- proof/evidence;
- external repositories;
- generated release artifacts.

## Threat actors / inputs

- malicious or compromised repository;
- malicious README/prompt injection;
- compromised dependency;
- tool/MCP descriptor drift;
- buggy or hallucinating agent;
- stale recovered worker;
- compromised memory;
- incorrect reviewer;
- hostile generated shell command.

## Required defenses

- read-only vendor source;
- isolated workspaces;
- pre-tool policy checks;
- secret deny/masking;
- sandbox probes;
- fenced leases;
- immutable/append audit history where practical;
- reviewer read-only;
- protected evaluator;
- dependency admission;
- bounded retries/circuit breakers;
- post-integration verification.

## Security invariant

No single agent output can directly grant itself more authority.
