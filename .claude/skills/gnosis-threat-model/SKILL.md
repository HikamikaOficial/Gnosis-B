---
name: gnosis-threat-model
description: Threat-model a GNOSIS component, adapter, tool, sandbox or workflow before granting autonomy.
---

Consider:
- malicious repository instructions;
- prompt injection through files/tool output;
- secret exfiltration;
- filesystem escape;
- network egress;
- dependency compromise/slopsquatting;
- stale lease writes;
- evaluator tampering;
- policy bypass;
- MCP/tool drift;
- destructive Git;
- reviewer self-modification.

Produce threats, preconditions, impact, mitigations, tests and residual risk.
