# CLAUDE.md — Constitución operativa de GNOSIS

## Identidad

**GNOSIS** es un sistema local de ingeniería autónoma multiagente. Claude Code/Fable 5 es inicialmente el agente principal de construcción, pero **no es Gnosis**. Codex es un segundo agente prioritario para revisión adversarial, implementación alternativa y verificación.

El producto debe permanecer provider-neutral mediante adapters.

## Mandato

Trabaja de forma autónoma. Para decisiones técnicas reversibles, investiga, decide, registra un ADR y continúa. No preguntes “¿quieres que siga?”.

## Autoridad

```text
LLM intelligence != system authority
```

Los agentes proponen. El Kernel autoriza estados, gates, permisos, integración y promoción.

## Reglas absolutas

1. Ningún agente tiene autoridad absoluta.
2. Ninguna Task llega a `DONE` sin evidencia.
3. Task != session.
4. El estado crítico sobrevive a cualquier agente.
5. Todos los retries se clasifican antes de repetirse.
6. `RATE_LIMITED` != `FAIL_CODE`.
7. `FAIL_INFRA` no penaliza la calidad del agente.
8. Ningún loop es ilimitado.
9. Un reviewer no modifica lo que juzga.
10. `INDEPENDENT BEFORE INTERACTION` para decisiones críticas.
11. `EVIDENCE BEFORE CONSENSUS`.
12. Usar el mínimo número de agentes que aporte evidencia suficiente.
13. Least privilege y deny-by-default para acciones sensibles.
14. Git es parte de la arquitectura: checkpoints, worktrees, provenance, rollback.
15. Worktree != solución completa a conflictos; preparar ownership semántico.
16. Textual merge != semantic integration.
17. Contexto mínimo, suficiente, versionado y trazable.
18. Memory != Truth.
19. Project Truth, Operational State, Knowledge, Episodic y Procedural Memory son capas distintas.
20. Descubrimientos repetibles deben convertirse en test/policy/invariant/skill cuando proceda.
21. Ninguna mejora de Gnosis se promociona sin superar baseline/regression.
22. Los incidentes deben convertirse en tests.
23. Dependencias nuevas pasan Dependency Admission.
24. No ejecutar repos externos no auditados.
25. No usar credenciales de suscripción como API improvisada.
26. No hacer fallback silencioso a APIs de pago.
27. No usar `git reset --hard`, `git clean -fdx`, force-push ni borrados masivos como atajo.
28. No alterar tests para hacer pasar código roto.
29. No suprimir excepciones o gates para “terminar”.
30. La simplicidad es una propiedad de seguridad.

## Repositorios externos

`external/repositories/**` es **READ-ONLY SOURCE**.

Permitido:
- Read/Grep/Glob;
- Git metadata read-only;
- copiar un candidato a un workspace aislado para experimentos.

Prohibido:
- modificar el original;
- commit/pull/reset/clean en el original;
- instalar dentro del original si altera archivos;
- ejecutar instaladores/scripts antes de auditoría.

## Desarrollo propio

Código de Gnosis:
- `src/gnosis/`
- `tests/`
- `docs/`
- `gnosis-spec/`

Runtime mutable:
- `.gnosis/`

## Estado durable humano/agente

Mantén:

- `docs/PROJECT_STATE.md`
- `docs/NEXT_ACTIONS.md`
- `docs/DECISIONS.md`
- `docs/LEARNINGS.md`
- `docs/ASSUMPTIONS.md`

Antes de una pausa larga o compactación importante: checkpoint + estado + siguiente acción.

## Memoria

Auto-memory está habilitada.

Los subagentes definidos en `.claude/agents/` usan `memory: project` cuando la memoria acumulada aporta valor.

La memoria sólo contiene ayuda; no puede sobreescribir:
- source;
- Git;
- SPEC;
- ADR;
- tests;
- evidencia ejecutable.

Toda lección susceptible de convertirse en comportamiento productivo entra primero en `lab/learning/candidates/`.

## Uso de subagentes

Delega proactivamente cuando:
- la investigación contaminaría el contexto principal;
- se necesita opinión independiente;
- security/evidence review debe ser read-only;
- se comparan alternativas;
- una tarea puede ejecutarse de forma paralela sin conflicto.

No generes swarms por espectáculo.

## Claude + Codex

Usa Codex de forma independiente cuando aporte valor real:
- revisión adversarial;
- segunda implementación;
- bug hypothesis;
- architecture critique;
- validation.

Preferencia para reviewer:

```text
codex exec --sandbox read-only --json ...
```

Para worker, sólo dentro de workspace aislado y con permisos explícitos.

No asumir simetría de calidad Claude↔Codex. Registrar resultados.

## Failure taxonomy

Usa tipos explícitos:

```text
PASS
FAIL_CODE
FAIL_TEST
FAIL_REVIEW
FAIL_SECURITY
FAIL_ARCHITECTURE
FAIL_PERFORMANCE
FAIL_POLICY
FAIL_INFRA
RATE_LIMITED
TIMEOUT
AGENT_CRASH
INVALID_AGENT_OUTPUT
STALEMATE
STALE_LEASE
MERGE_CONFLICT
CONTEXT_ERROR
DEPENDENCY_ERROR
NEEDS_HUMAN
```

## Circuit breakers

Cada loop debe tener:
- max attempts;
- max same failure;
- max no-diff rounds;
- max review rounds;
- wall-time/budget;
- invalid-output limit.

Cuando no hay nueva evidencia: `STALEMATE`, cambia estrategia o aparca.

## Ingeniería

Preferencias iniciales salvo ADR contrario:
- Python 3.12+;
- `uv`;
- typed code;
- asyncio;
- SQLite para V1;
- pytest;
- ruff;
- mypy;
- Git CLI;
- JSON/JSONL para interchange;
- OpenTelemetry-compatible event model.

Evita frameworks pesados sin evidencia de necesidad.

## Definition of done

“Funciona” requiere prueba.

Cada milestone crítico:
1. implement;
2. unit/integration tests;
3. self-review;
4. independent review cuando aporte valor;
5. reparar findings verdaderos;
6. rerun;
7. proof/evidence;
8. checkpoint;
9. actualizar estado.

## Seguridad

No leer/mostrar secretos.
No ejecutar código externo desconocido sin aislamiento.
No elevar privilegios salvo necesidad real.
No publicar/deploy/pagar/borrar datos externos automáticamente.
Las acciones irreversibles se preparan pero no se ejecutan sin autoridad superior.

## Fin de sesión

No abandones trabajo en estado ambiguo.

Actualiza `PROJECT_STATE` y `NEXT_ACTIONS`, registra tests y commits y deja el próximo comando/paso exacto.

# GNOSIS v0.3 — Nicol workstation and Memory Fabric

## Canonical machine paths

Project:
`C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi`

External resources:
`C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories`

All 126 researched repositories plus new Memory Fabric resources are indexed in:
- `resources/repositories.json`
- `resources/REPOSITORY_MAP.md`

Never ask for a repository link that exists in the registry. Resolve local clone by Git origin; if missing and materially needed, use the canonical URL.

## Required Memory Fabric

Primary:
- M3: https://github.com/skynetcmd/m3-memory
- ZMem: https://github.com/zerkerlabs/zmem

Optional after benchmark:
- Graphify: https://github.com/Graphify-Labs/graphify
- Obsidian Mind: https://github.com/breferrari/obsidian-mind

M3 is broad recall. ZMem is governance/trust. Do not blindly dual-write. Memory passes truth/freshness/policy checks before context injection.

Claude auto-memory is convenience, not truth.

No memory backend may directly mutate Task state or bypass the Kernel/Policy Engine.

Before substantial implementation, Memory Fabric must pass the smoke test in `gnosis-spec/MEMORY_INSTALL_AND_VALIDATION.md`.
