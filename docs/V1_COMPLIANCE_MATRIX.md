# GNOSIS — Matriz V1 viva

**Última actualización:** 2026-08-22 · **Unidad:** ADR-0025 + cuatro
addenda de revisión independiente (FAIL PARCIAL, FAIL PARCIAL,
**FAIL CRÍTICO**, **PASS**) — F-34 **CERRADO** por la cuarta revisión,
que volvió sin hallazgos sobre el código `9c6064c` y la evidencia
`f02e18e`

Esta es la matriz **viva**. `docs/V1_TRACEABILITY_AUDIT.md` es el
diagnóstico congelado del 2026-08-22 y no se edita; cada hallazgo se
cierra aquí y en el ADR que lo repara.

**Regla de esta tabla:** una fila sólo cambia cuando existe un ADR con
evidencia capturada que la respalde. Un hallazgo no se marca resuelto
porque parezca resuelto.

**IA** implementado y alcanzable · **II** implementado pero inerte ·
**P** parcial · **A** ausente · **DI** declarado incorrectamente

---

## Capacidades del Definition of Done

| # | Capacidad | Módulo | Alcanzable en producción | Veredicto | Hallazgo |
|---|---|---|---|---|---|
| 1 | proyecto/tarea durable | P — `BriefRecord`+`RunMeta` durables; sin `Project`; `TaskState` sólo en memoria | sí (orquestador) | **P / DI** | F-03 abierto |
| 2 | representar dependencias | **A** — no existe `TaskDependency` ni grafo | — | **A / DI** | F-01, F-02 abiertos |
| 3 | detectar tareas listas | P — readiness temporal (`not_before`), no por dependencias | vía `WorkQueue` (sin constructor) | **P / DI** | F-04 abierto |
| 4 | claim con lease/fencing | IA | II | **II** | F-33 abierto |
| 5 | rechazar escrituras stale | IA | II | **II** | F-33 abierto |
| 6 | worktree aislado | IA (SANDBOX_APPROX) | II | **II** | F-33 abierto |
| 7 | FakeClaude/FakeCodex en CI | P — fakes ad-hoc, sin familia reutilizable | n/a | **P** | abierto |
| 8 | adaptadores reales Claude/Codex | P — sólo Claude | no | **P / DI** | F-37 abierto |
| 9 | capturar salidas estructuradas/raw | IA | II | **II** | F-33 abierto |
| 10 | clasificar rate limits aparte | IA | II | **II** | F-33 abierto |
| 11 | salida malformada, reparación acotada | IA | II | **II** | F-33 abierto |
| 12 | timeout/cancel de subproceso | IA | II | **II** | F-33 abierto |
| 13 | verificación determinista | IA | II | **II** | F-33 abierto |
| 14 | review read-only | IA (SANDBOX_APPROX) | II | **II** | F-33 abierto |
| 15 | rework acotado | IA | II | **II** | F-33 abierto |
| 16 | proof packet | **A** — sin `ProofPacket`; `acceptance_criteria` sólo se pega al prompt | — | **A / DI** | F-36 abierto |
| 17 | **rehusar DONE sin evidencia** | **IA** — la **autoridad de estados** lo impone: `transition()` rehúsa `COMPLETED` y `complete(verification)` valida un `VerificationResult` real; `execute_task` rehúsa sin verifier antes de lanzar nada; `MalformedEvidence` hace que "no hay veredicto" sea un tipo, y `CompositeVerifier` no puede fabricar un pase ni existir vacío | **IA** — `DirectorOrchestrator.run_pending` rehúsa antes de consumir el brief | **IA** ✅ | **F-34 CERRADO** — ADR-0025 + 4 addenda; la cuarta revisión independiente (2026-08-22) devolvió **PASS** sin hallazgos en alcance sobre el código `9c6064c` y la evidencia `f02e18e`. Cerrado por la regla que este documento se dio: un hallazgo se cierra cuando una revisión independiente vuelve sin hallazgos |
| 18 | sobrevivir reinicio del kernel | IA | II | **II** | F-33 abierto |
| 19 | recuperar tras crash de worker | IA | **II** — el llamante de `sweep()` es `WorkerSupervisor`, que nada construye | **II / DI** | F-35 abierto |
| 20 | evitar bucles infinitos | P — breakers presentes; `max_briefs`/`wall_clock_s` por defecto `None`; sin "max same failure" | II | **P** | F-10 abierto |
| 21 | eventos de auditoría append | IA — hash-chain verificada | II | **II** | F-33 abierto |
| 22 | preservar integridad Git | IA | II | **II** | F-33 abierto |

**Resumen:** 1 capacidad alcanzable de extremo a extremo (nº17), 13
inertes, 5 parciales, 3 ausentes. La única fila que ha cambiado es la 17.
Que esa fila esté cerrada no hace alcanzable el sistema: las otras 21
capacidades siguen exactamente donde estaban.

> La primera versión de esta fila decía que `completion_is_evidenced` era
> "el único autorizador". No lo era: `TaskStateMachine.transition()`
> aceptaba `COMPLETED` de cualquiera. Corregido tras la revisión
> independiente de Codex (FAIL PARCIAL). La lección está en L-0044.

---

## Suite de supervivencia

Sin cambios en esta unidad. Ver `docs/V1_TRACEABILITY_AUDIT.md` §Eje 2.

| Escenario | Estado |
|---|---|
| worker kill · kernel restart · stale lease · malformed JSON · timeout · rate limit · reviewer disagreement · merge conflict | **PASS** (8 de 11) |
| repeated identical failure | **PARCIAL** — cotas de intentos sí, breaker por clase de fallo no (F-10) |
| invalid state transition | **PARCIAL** — sólo el plano en memoria; `RunStore` y `BriefRecordStore` sin validación (F-07, F-08) |
| no-diff loop | **PASS** |

---

## Los cuatro invariantes

| Invariante | Suite nombrada | Estado |
|---|---|---|
| NO LOST WORK | **A** | implicado en muchas pruebas, ninguna nombrada |
| **NO INVALID DONE** | **presente** — `tests/test_no_invalid_done.py` (82 pruebas, 39 subtests) y `tests/test_state_machine.py` (27 pruebas, 18 subtests), de las cuales 12 son `TestCompletedIsEvidenceGated`; recuento verificado en esta unidad, las cifras anteriores (28/15 y 21/9) eran de la primera pasada | primera suite nombrada por un invariante (ADR-0025). Cubre la autorización de `COMPLETED` en la autoridad de estados, en el motor, en el compuesto de verificadores y en el pipeline; **no** cubre pérdida de trabajo ni bucles |
| NO STALE WRITE | **A** | implicado; mecánicamente sólido |
| NO INFINITE LOOP | **A** | breakers presentes con defaults apagados |

F-13 (ninguna suite nombrada por invariante) queda **parcialmente**
atendido como efecto colateral: existe una de las cuatro. Las otras tres
siguen abiertas y F-13 no se declara cerrado.

---

## Hallazgos cerrados

| Hallazgo | ADR | Cerrado | Veredicto que lo cierra |
|---|---|---|---|
| **F-34** — `COMPLETED` sin evidencia | ADR-0025 (+4 addenda) | 2026-08-22 | **cuarta revisión independiente: PASS**, sin hallazgos en alcance; código `9c6064c`, evidencia `f02e18e` |

Uno de 43. F-34 ya fue marcado cerrado una vez, el 2026-08-22, y hubo que
retirarlo de esta sección cuando tres revisiones independientes
consecutivas encontraron un lector nuevo del mismo campo. Vuelve ahora
por el único motivo que esta tabla admite: una revisión independiente que
no encontró nada. El historial completo de los cuatro intentos se
conserva abajo sin reescribir.

## F-34 — historial de reparación (cerrado en la cuarta revisión)

| Hallazgo | ADR | Fecha | Evidencia |
|---|---|---|---|
| **F-34** — `COMPLETED` sin evidencia alcanzable desde el punto de entrada por defecto | ADR-0025 | 2026-08-22 | `.gnosis/evidence/20260822T005432Z/` (781 passed, árbol limpio en `29d3666`) |
| **F-34 (cierre incompleto)** — la autoridad de estados seguía admitiendo `VERIFYING → COMPLETED` sin evidencia; hallado por Codex, FAIL PARCIAL | ADR-0025 addendum | 2026-08-22 | `.gnosis/evidence/20260822T142519Z/` (800 passed, árbol limpio en `6c4859a`; dos mutantes capturados) |
| **F-34 (segunda revisión)** — `state`/`completion_evidence` eran atributos públicos, y el informe imprimía `PASSED` para un `VerificationResult(passed=1)` que la autoridad acababa de rechazar; FAIL PARCIAL | ADR-0025 addendum 2 | 2026-08-22 | `.gnosis/evidence/20260822T162729Z/` (822 passed, árbol limpio en `1591aa7`; seis mutantes capturados) |
| **F-34 (tercera revisión)** — `CompositeVerifier` lavaba evidencia MALFORMED (`all(r.passed …)` → `passed=True`) y un compuesto vacío pasaba con `all([])`; los tres lectores diferidos seguían vivos; **FAIL CRÍTICO** | ADR-0025 addendum 3 | 2026-08-22 | `.gnosis/evidence/20260822T181937Z/` (874 passed, árbol limpio en `9c6064c`; nueve mutantes capturados) |
| **F-34 (cuarta revisión)** — las dos reproducciones críticas fallan cerradas, `CompositeVerifier` con un miembro `passed=1` produce `MalformedEvidence` y el motor termina FAILED/PARTIAL registrando el problema, el compuesto vacío lanza `EmptyCompositeError`, y no queda lector productivo de `.passed` que decida fuera de `verification_verdict()`; **PASS, sin hallazgos** | ADR-0025 addendum 4 | 2026-08-22 | revisada sobre código `9c6064c` y evidencia `f02e18e`; 249 pruebas y 39 subtests dirigidos verificados por el revisor; el bundle registra 874 pruebas, 60 subtests, mypy limpio y ruff en baseline |

## Hallazgos abiertos

F-01, F-02, F-03, F-04, F-05, F-07, F-08, F-10, F-12, F-13, F-14, F-15,
F-16, F-17, F-18, F-19…F-32, F-33, F-35, F-36, F-37, F-38, F-39, F-40.

**Recuento, para que ningún documento vivo lo repita mal:** el diagnóstico
congelado tiene **43 elementos** (F-01…F-42 más F-29b). De ellos **6 son
PASS** y no son defectos (F-06, F-09, F-11, F-29b, F-41, F-42), **1 está
cerrado** (F-34) y **36 siguen abiertos** — exactamente los enumerados
arriba. Historial del recuento, porque ha estado mal dos veces: una
versión dijo 41, contando los PASS y F-34 como trabajo; otra dijo
"1 cerrado (F-34)" antes de que la tercera revisión lo reabriera; otra
dijo "0 cerrados y 37 abiertos", correcto mientras F-34 estuvo reabierto.
El recuento vivo es **6 PASS · 1 cerrado · 36 abiertos**.

Ninguno de los 36 se ha tocado en ninguna de las cuatro pasadas de F-34.
Los 15 hallazgos abiertos de las revisiones anteriores
(`PROJECT_REPORT.md §8`) tampoco.
