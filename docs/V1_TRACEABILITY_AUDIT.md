# GNOSIS — Auditoría dirigida de trazabilidad V1

**Tipo:** auditoría de solo lectura · **Fecha:** 2026-08-22
**Árbol auditado:** commit `83ae84e759b63d26d19669b1447be9b501adc0a7`, tree `842039df790ef485c5d719e06b7d607a9e4b00c6`
**Estado del árbol en la auditoría:** limpio salvo dos ficheros no rastreados (`.stfolder/`, `PROJECT_REPORT.md`), ninguno de ellos código ni prueba.
**Suite en el momento de auditar:** `pytest --collect-only` → **760 tests collected**.
**Alcance:** ninguna edición, ninguna reparación, ningún commit de código. Este documento es el diagnóstico congelado **antes** de cualquier reparación.

> Este fichero es evidencia histórica. No se edita para reflejar reparaciones
> posteriores: cada hallazgo se cierra en el ADR que lo repara y en la matriz
> V1 viva, no reescribiendo este texto. Regla 14 — la historia es arquitectura.

---

## Método

Leídos íntegros `CLAUDE.md`, `PROJECT_REPORT.md`, `gnosis-spec/V1_DEFINITION_OF_DONE.md`,
`gnosis-spec/MASTER_AUTONOMOUS_BUILD_DIRECTIVE.md`, `docs/PROJECT_STATE.md` y
`docs/DECISIONS.md`.

Verificación contra código y pruebas mediante:

- inventario completo de símbolos productivos (`class`/`def` en `src/`);
- análisis de llamantes separando `src/` de `tests/` (un símbolo construido sólo
  en pruebas no es implementación productiva);
- lectura semántica de las suites, no búsqueda literal por palabra clave;
- correlación de los bundles `.gnosis/evidence/` con el historial Git;
- una única ejecución (`pytest --collect-only`, 0.47 s, solo lectura).

**Taxonomía de estados usada en todo el documento:**

| Sigla | Significado |
|---|---|
| **IA** | implementado y alcanzable |
| **II** | implementado pero inerte (mecanismo correcto, ningún llamante de producción) |
| **P** | parcial |
| **A** | ausente |
| **DI** | declarado incorrectamente en la documentación |

---

## Eje 1 — El DAG de dependencias entre tareas

### F-01 · FAIL · CRÍTICA · contrato-ausente

- **file** `src/gnosis/kernel/ordering.py`
- **symbol** `ReadyTask`, `plan_landings`
- **finding** `ReadyTask` **no es un nodo de un DAG de ejecución**. Sus campos son
  `task_id`, `base_sha`, `changed_paths`, `converged_at`. No hay aristas, ni
  referencias a otras tareas, ni predecesores. `plan_landings` ordena por
  `(base_sha != head, converged_at, task_id)` — FIFO sobre tareas **ya
  convergidas** — para decidir el orden de *aterrizaje* (integración) y calcular
  `review_still_applies`.
- **evidence** `ordering.py:29-36`, `:112-125`, `:169-176`. El propio docstring
  lo declara: *"this module's real output is not 'an order'. It is an order plus,
  for each task, whether its review is still evidence about the tree it will land
  on."*
- **confidence** ALTA
- **estado** implementado y alcanzable, **declarado incorrectamente** como
  representación de dependencias.
- **corrección sugerida** retirar `kernel/ordering.py` como respaldo del
  requisito V1 nº2 en `PROJECT_REPORT.md §5`.

### F-02 · FAIL · CRÍTICA · ausente

- **symbol** `TaskDependency` y todo el vocabulario asociado
- **finding** no existe almacenamiento del grafo, ni detección de ciclos, ni
  cálculo de readiness por dependencias satisfechas.
- **evidence**
  `grep -rn "TaskDependency|depends_on|blocked_by|predecessor|successor|topological|toposort|in_degree|DAG" src/ tests/ scripts/`
  → 1 resultado: `tests/test_claims.py:235`, un comentario sobre leases.
- **confidence** ALTA · **estado** A

### F-03 · FAIL · ALTA · ausente

- **symbol** `Project`
- **finding** cero ocurrencias de `class Project` o `project_id` en `src/`. La
  unidad durable más alta es `BriefRecord` (`brief_id` → un solo `task_id`). El
  DoD nº1 pide "durable **project**/task".
- **confidence** ALTA · **estado** A

### F-04 · FAIL · ALTA · declarado incorrectamente

- **file** `src/gnosis/director/work_queue.py`
- **symbol** `WorkQueue.claim`
- **finding** "detect ready tasks" existe únicamente como *registro presente en
  `pending/` cuyo `not_before` ya venció*. Es readiness **temporal** (backoff
  exponencial durable), no readiness por dependencias. `TaskState` no tiene
  estado `READY`.
- **evidence** `work_queue.py:148-181`; `state_machine.py:31-41`
- **confidence** ALTA · **estado** P / DI

### F-05 · FAIL · MEDIA · deriva-de-spec

- **file** `src/gnosis/kernel/state_machine.py`
- **symbol** `TaskState`
- **finding** la directiva maestra fija 14 estados core
  (`NEW, SPECIFYING, SPECIFIED, PLANNING, PLANNED, READY, CLAIMED, EXECUTING,
  VERIFYING, REVIEWING, REWORK, PROVING, INTEGRATING, DONE`). El código
  implementa 9 (`CREATED, PLANNED, IN_PROGRESS, VERIFYING, BLOCKED, ESCALATED,
  COMPLETED, FAILED, CANCELLED`). Ningún ADR ni decisión registra la reducción.
- **evidence** `state_machine.py:31-41` vs `MASTER_AUTONOMOUS_BUILD_DIRECTIVE.md
  § State machine`; `grep -rn "TaskState" docs/adr/` no produce justificación.
- **confidence** ALTA sobre el hecho, MEDIA sobre la intención (probablemente
  heredado del baseline M0/M1 anterior al pack v0.3).

---

## Eje 2 — Escenarios de supervivencia

El informe usó grep sobre nombres de directorio y produjo **dos falsos negativos**
y **un hueco real que ese método no podía ver**.

### F-06 · El informe se equivoca: "invalid state transition" SÍ está probado

- **file** `tests/test_state_machine.py`
- **symbol** `test_illegal_transition_raises` (×2), `test_terminal_states_have_no_exits`,
  `test_illegal_transition_error_carries_allowed_next`,
  `test_terminal_state_error_reports_terminal`, `test_transition_tables_are_immutable`
- **finding** la afirmación "0 files — appears absent" es **falsa**.
- **confidence** ALTA · **verdict** PASS (la cobertura existe)

### F-07 · FAIL · ALTA · implementado pero inerte

- **files** `src/gnosis/kernel/state_machine.py`, `src/gnosis/kernel/run_store.py:104`
- **symbol** `RunStateMachine`, `RunStore.update_state`
- **finding** la cobertura de F-06 es **sólo del plano en memoria**.
  `RunStateMachine` no tiene ningún llamante en `src/` — únicamente pruebas. Y el
  plano durable no valida: `update_state` hace `meta.state = state.value` sin
  tabla de transiciones.
- **evidence** `engine.py:641` lo admite: *"PENDING->FAILED is not a legal
  transition — RunStore does not validate, so the illegal edge used to land on
  disk unchallenged (adversarial review)."* La corrección fue cambiar el
  *llamante* (usar `CANCELLED`), no cerrar el boquete.
- **confidence** ALTA · **estado** II

### F-08 · FAIL · ALTA · ausente

- **file** `src/gnosis/director/brief_record.py:90`
- **symbol** `BriefRecordStore.update`
- **finding** `for key, value in changes.items(): setattr(record, key, ...)` —
  tercer vocabulario de estados (`BriefRecordState`, 7 valores) sin tabla de
  transiciones y sin validación. Se puede escribir cualquier cadena.
- **evidence** de los tres planos de estado (`TaskState`, `RunState`,
  `BriefRecordState`), el único validado es el único que no sobrevive al proceso.
- **confidence** ALTA · **estado** A

### F-09 · El informe se equivoca: "no-diff loop" SÍ está probado

- **file** `tests/test_convergence.py`
- **symbol** `test_stalemate_after_n_unchanged_fingerprints`,
  `test_fingerprint_change_resets_the_stalemate_counter`,
  `test_gap_breaks_consecutiveness_of_recurring_fingerprints`,
  `test_done_claim_without_repo_change_is_downgraded_to_warning`,
  `test_failed_fingerprint_collection_never_counts_toward_stalemate`
- **evidence** mecanismo en `convergence.py:302-330` (`max_unchanged_rounds=3`
  sobre `git_fingerprint`).
- **confidence** ALTA · **verdict** PASS

### F-10 · PARCIAL · MEDIA · "repeated identical failure"

- **files** `tests/test_engine.py:96`, `tests/test_work_queue.py:225`,
  `tests/test_convergence.py:272`, `src/gnosis/director/supervisor.py:117-132`
- **finding** cubierto **como cota de intentos**: `test_exhausts_retries_and_fails`
  (runner que devuelve exit 1 y `"simulated failure"` idéntico las 3 veces),
  `test_a_brief_is_not_re_offered_forever`,
  `test_rounds_exhausted_is_bounded_and_typed`, `max_consecutive_parks`.
  **No cubierto**: ningún breaker keyed por *clase de fallo repetida*.
  `SupervisorPolicy` no tiene `max_same_failure`; los motivos de park son
  cadenas, no tipos.
- **confidence** ALTA · **estado** P (coincide con el hallazgo abierto nº9)

### F-11 · PASS · el resto de escenarios tiene cobertura semántica real

| Escenario | Prueba concreta |
|---|---|
| worker kill | `test_work_queue.py::TestACrashedWorkerLosesNothing`, `test_recovery.py::test_dead_process_detected_immediately_even_if_heartbeat_fresh`, `::test_pid_reuse_not_confused_with_original_owner` |
| kernel restart | `test_supervisor.py::test_backoff_survives_a_restart`, `test_claims.py::test_state_survives_reopen`, `test_scheduler.py::test_reconcile_is_idempotent_across_pumps_and_restarts` |
| stale lease | `test_lease.py::test_deposed_holder_is_denied_everywhere`, `::test_expired_lease_fails_assert_even_without_takeover`, `test_claims.py::test_sweep_reclaims_only_expired` |
| malformed JSON | `test_cli_review_adapters.py` (13 pruebas de payload), `test_supervisor.py::test_a_handler_that_returns_nonsense_is_an_invalid_output_not_a_park` |
| timeout | `test_cli_runner.py::test_timeout_kills_process`, `test_cli_review_adapters.py::test_a_timed_out_reviewer_is_invalid_output_not_a_pass` |
| rate limit | `test_failures.py::TestRateLimitHolds` (16), `test_scheduler.py::TestHoldsGateLaunches` (13) |
| reviewer disagreement | `test_convergence.py::test_uncertain_verdict_never_converges_and_stalemates_out`, `::test_verification_failure_blocks_convergence_despite_pass_verdict`, `::test_verification_flip_on_unchanged_fingerprint_requires_reproduction` |
| merge conflict | `test_integration.py::test_a_textual_conflict_is_typed_and_names_its_paths`, `::test_a_clean_merge_that_breaks_the_tree_does_not_land` |

### F-12 · FAIL · MEDIA · organización

`tests/chaos/`, `tests/recovery/`, `tests/security/`, `tests/unit/` contienen
**sólo `.gitkeep`**. Toda la cobertura vive en los 35 ficheros `tests/test_*.py`
de la raíz. El error metodológico del informe (inferir ausencia del directorio
vacío) es real y reproducible.

### F-13 · FAIL · MEDIA · ausente

Los cuatro invariantes aparecen sólo como **comentarios**: `test_engine.py:943`,
`:1316`, `test_lease.py:55`, `test_worktree.py:272`. Ningún test ni suite
nombrada por invariante.

---

## Eje 3 — `scripts/capture_evidence.py`

**Respuesta directa: no. Registrar HEAD y `git status` no permite demostrar qué
bytes de un árbol sucio pasaron las pruebas.**

### F-14 · FAIL · CRÍTICA · evidencia no vinculante

- **file** `scripts/capture_evidence.py:29-34`
- **symbol** `COMMANDS`
- **finding** `git status --porcelain` emite `XY <ruta>`: **estado y nombre, nunca
  contenido**. Dos árboles sucios distintos que modifiquen los mismos ficheros
  producen un bundle byte-idéntico. No hay hash de árbol, ni diff, ni digest de
  contenido.
- **evidence** el bundle que `PROJECT_REPORT.md` y `PROJECT_STATE.md` citan como
  prueba de "760 tests passing":
  `.gnosis/evidence/20260821T174016Z/git-head.stdout.txt` → `92fe18ab...`;
  `git-status.stdout.txt` → 4 ficheros ` M` (`supervisor.py`, `work_queue.py`,
  `test_supervisor.py`, `test_work_queue.py`). La suite corrió contra un árbol
  sucio y nada en el bundle permite recuperar esos bytes. Que coincidan con lo
  comprometido en `edec96e` es una inferencia **desde el commit**, no una prueba
  **desde la evidencia**.
- **confidence** ALTA

### F-15 · RESOLVED / STALE (histórico: FAIL / ALTA) · primitiva existente no utilizada

- **files** `scripts/capture_evidence.py` vs `src/gnosis/kernel/git_evidence.py:78`
- **symbol** `content_fingerprint`, `tamper_fingerprint`
- **finding** el repositorio ya posee exactamente la primitiva que falta:
  `content_fingerprint()` devuelve `{head_sha, branch, status_sha256,
  patch_sha256, untracked{ruta: sha256}}` — `patch_sha256` liga el árbol sucio.
  Usada en `kernel/engine.py`, `kernel/integration.py`, `adapters/cli_review.py`,
  `runner/replay_runner.py`. **`capture_evidence.py` no la importa.**
- **evidence** D-019 establece que identidad = contenido; la superficie de
  evidencia del propio proyecto es la única que sigue clavada en prosa.
- **confidence** ALTA
- **corrección sugerida** escribir `content_fingerprint(REPO)` en `SUMMARY.json`
  antes y después de la tanda.
- **status (2026-08-31 · RESOLVED / STALE)** el hallazgo era válido al escribirse
  (`capture_evidence.py` no usaba `content_fingerprint`), pero el trabajo de
  vinculación de evidencia posterior (ADR-0026 / era F-14–F-17) ya conectó la
  primitiva a la ruta de producción de captura. Cableado actual:
  `capture_evidence.py` → `run_capture(...)` →
  `probe_tree_identity(..., fingerprint=content_fingerprint)` (huella PRE antes
  del primer check y POST tras el último) → `bind_tree(pre, post)` →
  `TreeBinding.to_dict()` → `SUMMARY.json`, con la identidad de contenido
  (incluido `patch_sha256`) enlazada y fallo cerrado si los extremos difieren o
  la identidad no puede tomarse. La primitiva NO está sin usar: la consumen
  además `kernel/engine.py`, `kernel/integration.py`, `adapters/cli_review.py`,
  `runner/replay_runner.py` y `kernel/evidence_capture.py`; cubierta por
  `test_evidence_binding.py` (extremo a extremo, `patch_sha256`, `bind_tree`) y
  la suite de mutación F-14. Sin cambio de código en este cierre; F-14 y F-17
  permanecen CLOSED. La capa de captura produce evidencia vinculada, NO una
  segunda ruta de autoridad: la publicación autoritativa sigue siendo la ruta
  F-17 ya cualificada. (Deuda técnica separada, no-F-15, no-bloqueante: el
  parámetro inyectable `fingerprint=` podría dar una huella estructuralmente
  incompleta y `bind_tree` describirla como BOUND; producción fija
  `content_fingerprint` y no expone ese selector a entrada no confiable — no
  reabre F-15/F-14/F-17 y no se corrige ahora.)

### F-16 · RESOLVED / STALE (histórico: FAIL / ALTA) · orden de captura

- **file** `scripts/capture_evidence.py:64-70`
- **symbol** `main()`
- **finding** los comandos se ejecutan en orden de lista: `pytest` primero (543 s
  en el bundle citado), `git-head`/`git-status` **al final**. La huella
  registrada es la del árbol **posterior** a la suite, no la del árbol contra el
  que la suite corrió. No hay captura pre/post ni comparación.
- **evidence** `captured_at` = 17:49:22 frente al sello del directorio 17:40:16.
- **confidence** ALTA
- **status (2026-08-31 · RESOLVED / STALE)** el hallazgo era válido cuando se
  escribió, pero la arquitectura de captura posterior (era F-14/F-17,
  `kernel/evidence_capture.py:run_capture`) lo superó. Secuencia de producción
  actual: (1) init de staging/scratch; (2) observador de escritura ARMADO; (3–5)
  puertas Git backend/versión, topología, resolución; (6) **identidad PRE de
  árbol/contenido (`pre = identity(repo)`, 1401)**; (7) bloqueo de entradas
  cubiertas; (8) **identidad PREPARED tras dejar las entradas no escribibles
  (1415)**; (9) chequeo de deriva de preparación — si `PRE != PREPARED` el bucle
  de comandos NO se ejecuta; (10) **comandos de cualificación (1429)**; (11)
  deriva de streams; (12) liberación del bloqueo; (13) **identidad POST (1439)**;
  (14) fin del observador; (15) `bind_tree(pre, post)`; (16) clasificación de
  observación/boundary; (17) veredicto de checks; (18) `SUMMARY.json`; (19)
  manifiesto del bundle; (20) publicación como paso separado del bundle
  completado. **Propiedad de seguridad: existe una identidad PRE de confianza
  ANTES de que se ejecute el primer comando de cualificación** (NO se requiere
  escribir `SUMMARY` antes de los comandos). Si la identidad PRE no está
  disponible, no corre ningún comando, el efecto colateral del comando está
  ausente y la captura devuelve identity-unavailable / fallo cerrado — protegido
  por `test_an_unavailable_pre_identity_runs_nothing_and_fails_closed`,
  `test_an_unavailable_post_identity_fails_closed_although_every_check_passed`,
  `test_a_capture_with_no_checks_is_refused`, `test_the_observer_is_armed_before_the_lock`
  y demostrado con un experimento controlado desechable (orden observado
  `identity, identity, command, identity`; PRE no disponible → 0 checks, sin
  efecto colateral, exit 3). La identidad de contenido y la COMPLETITUD de la
  observación del intervalo son garantías SEPARADAS: el observador está armado
  antes de PRE y activo hasta POST, y el bloqueo protege el conjunto de entradas
  durante la ejecución; el diseño NO depende solo de huellas PRE/POST iguales.
  Los transcripts parciales viven en staging antes del enlace final y NO
  constituyen un bundle publicado válido: un bundle válido requiere
  identidad/enlace + veredicto de boundary + veredicto de checks + `SUMMARY` +
  manifiesto + paso de publicación (que rehúsa sobrescribir). Sin cambio de
  código en este cierre. F-14 y F-17 permanecen CLOSED; la capa de captura
  produce un transcript de hito enlazado, NO una segunda ruta de autoridad (la
  publicación autoritativa sigue siendo la ruta F-17 cerrada). Deuda de
  aseguramiento no-bloqueante (compartida con F-15, NO-F-16): el parámetro
  inyectable `fingerprint=` podría dar snapshots estructuralmente incompletas
  pero iguales que el enlace genérico llamaría BOUND; producción fija
  `content_fingerprint` y ninguna entrada no confiable elige el proveedor — no
  reabre F-14/F-16/F-17 y no se corrige ahora. Las entradas de comando
  `git-head`/`git-status` son ahora transcript redundante; su retirada sería
  limpieza cosmética, no requerida para resolver el hallazgo.

### F-17 · FAIL · MEDIA · tamper-evidence

`SUMMARY.json` no contiene el HEAD ni el status (viven en `.txt` separados) y el
bundle no tiene hash-chain ni firma. Contraste interno: `kernel/ledger.py`
implementa un ledger append-only hash-encadenado que se re-verifica íntegro antes
de extenderse. La evidencia que sostiene las afirmaciones del proyecto es la
parte menos protegida del proyecto.

### F-18 · RESOLVED / STALE (histórico: FAIL / MEDIA) · deriva de evidencia

`PROJECT_REPORT.md` declara `Commit: edec96e` y cita `20260821T174016Z` como
"Latest evidence bundle". Ese bundle registra HEAD `92fe18a` — el commit
**anterior** — con árbol sucio. `HEAD` en la auditoría es `83ae84e`. **No existe
bundle de evidencia para `edec96e` ni para `83ae84e`.**

- **status (2026-08-31 · RESOLVED / STALE)** el defecto era una **deriva
  documental / de procedencia** (una cita humana equivocada), NO una falla de
  integridad de evidencia en tiempo de ejecución: el bundle citado
  (`.gnosis/evidence/20260821T174016Z/`) se auto-identificaba correctamente
  (`SUMMARY.json` y `git-head.stdout.txt` registran el commit real `92fe18a`); el
  elemento incorrecto era la cita del informe. El estado autoritativo **rastreado**
  ya no exhibe el defecto: se verificó que **todas las 49 referencias a bundles de
  evidencia en la documentación rastreada existen (49/49, 0 faltantes)**, la
  documentación de cierre de F-17 cita el estado cualificado de forma consistente
  (ADR-0031 → `06cdf00` ↔ el bundle rastreado cuyo README registra el árbol
  cualificado `06cdf00` ↔ raíz `f27a5f8a…`), y los bundles registran su propia
  identidad real (cualquier deriva es DETECTABLE). **Distinción de alcance:** F-18
  NO es la deriva de árbol en tiempo de ejecución (cerrada por F-14: observador →
  PRE → entradas bloqueadas → PREPARED → comandos → POST → veredicto de
  binding/boundary) NI la integridad de publicación autoritativa (cerrada por
  F-17: separación candidato/autoritativo, raíz autoritativa denegada al Worker,
  RunIdentity de confianza, recomputación del digest del bundle en el chokepoint
  `build_anchor_record`, autorización del Publisher, Anchor V2, watermark durable,
  binding de despliegue). **verify→publish:** no queda ventana de deriva
  explotable por T2 en la ruta autoritativa F-17 — la construcción del ancla
  recomputa/liga la identidad del bundle en el chokepoint de confianza y el Worker
  no puede mutar la raíz de evidencia autoritativa (sin ampliar la afirmación a
  Administrator/SYSTEM ni a compromiso del plano de confianza). **Post-publicación:**
  la garantía es **tamper-evidence / binding de contenido**, no inmutabilidad
  física perpetua — una modificación posterior de bytes cambia la identidad de
  contenido y es detectable frente al digest/raíz registrado (sin PKI/autenticidad
  externa). **Residual (honesto, no reabre F-18):** el artefacto históricamente
  nombrado `PROJECT_REPORT.md` sigue existiendo como archivo **no rastreado,
  preexistente y fuera de alcance**, y aún contiene la cita obsoleta; no es estado
  autoritativo rastreado y su disposición queda para el operador (no se edita, no
  se borra, no se añade en este cierre). Sin cambio de código/tests/scripts/
  evidencia. F-14 y F-17 permanecen CLOSED. Deuda de aseguramiento no-bloqueante
  (opcional, no requerida): un chequeo de que las rutas de bundles citadas por la
  documentación rastreada existen (hoy 0 faltantes) y, donde exista un esquema de
  cita legible por máquina, validar el commit/árbol declarado contra la identidad
  registrada por el bundle.

---

## Eje 4 — Deriva documental

| # | file | Contradicción | Verificación | sev |
|---|---|---|---|---|
| F-19 | `docs/PROJECT_STATE.md` "## Suite status" | histórico (FAIL/ALTA): "164 unit/contract tests + 3 memory-fabric" (=167) presentado como *Suite status* actual | **RESOLVED 2026-08-31 (docs-only)**: la sección se reemplazó por un checkpoint cualificado (F-17 final, árbol `06cdf00`, 1510 passed / 1 skipped / 291 subtests / exit 0; 1511 collected; ref. ADR-0031 + `.gnosis/evidence/20260831T025855Z-f17-final-qualification/`). **Causa raíz**: un conteo estático de fase temprana quedó embebido en un documento de estado de vida larga y se presentó indefinidamente como actual. **Remedio durable**: redacción checkpoint-cualificada referenciada a evidencia en vez de un número vivo sin fecha. Consecuencia: documental/auditabilidad; sin defecto de seguridad en runtime | ALTA → RESOLVED |
| F-20 | `docs/PROJECT_STATE.md:106` | "mypy strict clean (47 files)" | evidencia propia: `no issues found in 55 source files`; `find src -name "*.py"` → 55 | MEDIA |
| F-21 | `docs/PROJECT_STATE.md:5` | `Last update: 2026-08-20` | el cuerpo documenta trabajo del 2026-08-21 (deuda de revisión, L-0042) | BAJA |
| F-22 | `docs/PROJECT_STATE.md:307` | "Codex login pending (human-only step)" | contradice sus propios gates `[x] Codex CLI installed (0.148.0) and authenticated` y `NEXT_ACTIONS:1` "codex login DONE" | ALTA |
| F-23 | `docs/PROJECT_STATE.md:283-286` | "real code lives in `gnosis/`, `src/gnosis/` (currently an empty scaffold)" | **falso**: no existe `gnosis/` en la raíz; los 55 módulos y 13 669 líneas están en `src/gnosis/`. Resuelto por ADR-0002 | ALTA |
| F-24 | `docs/PROJECT_STATE.md:300` | gate `[ ] Kernel implementation (Phase 1 continuation) begins after archaeology` sin marcar | ADR-0004…0024 completados | MEDIA |
| F-25 | `docs/NEXT_ACTIONS.md:1` vs `:38` | "Both review debts are now paid; no unreviewed unit remains" vs, en el mismo fichero, "REVIEW DEBT: PAID, with a weaker channel… Codex rate-limited, reset 2026-09-20" | contradicción interna | ALTA |
| F-26 | `docs/NEXT_ACTIONS.md:22` | "the **seventeen** findings the reviews left open" | `PROJECT_REPORT §8` y el propio bloque (2 tachados) dicen **15** | MEDIA |
| F-27 | `README.md` | describe M0/M1: "ChatGPT is the Director", "Python 3.10+ stdlib", `python -m unittest discover`. No menciona policy engine, claims, convergencia, integración, cola, supervisor ni credenciales | es el primer documento que lee un revisor externo | ALTA |
| F-28 | `PROJECT_REPORT.md` (raíz, no rastreado) y `docs/PROJECT_REPORT.md` (rastreado) | duplicado byte-idéntico; la copia que el operador edita no es la versionada | riesgo de divergencia silenciosa | MEDIA |
| F-29 | `docs/DECISIONS.md` D-035 | declara `credentials/child_honours_the_binding = PROMPT_ONLY` | el código (`policy.py`) y el test de pin exacto lo fijan en **IGNORED**; `PROJECT_REPORT §4` dice IGNORED | ALTA |
| F-30 | `PROJECT_REPORT.md §2` | "33 modules in `src/gnosis/`" | 55 ficheros `.py` (las 13 669 líneas sí coinciden) | BAJA |
| F-31 | `PROJECT_REPORT.md §11` | "`EnforcementMatrix.verify()` exists but no probes are registered" | impreciso: `tests/test_policy.py:557` registra una probe real. Lo cierto: **ninguna fila HARD tiene probe, y no hay probes en producción** | MEDIA |
| F-32 | `docs/PROJECT_STATE.md:6` | `Phase: 1 — Kernel hardening` | ya se ha trabajado en Fases 2, 3, 4 y 8 de la directiva | MEDIA |

### F-29b · PASS · la matriz de refuerzo del informe es correcta

Verificada fila a fila contra `tests/test_policy.py::test_gnosis_matrix_is_pinned_exactly`:
20 filas, **6 HARD / 5 SANDBOX_APPROX / 2 PROMPT_ONLY / 7 IGNORED**. El recuento
del informe es exacto. La única discrepancia doc↔código es D-035 (F-29).

---

## Eje 5 — Requisitos V1 y contratos frente a símbolos productivos

### F-33 · FAIL · CRÍTICA · implementado pero inerte

- **file** `src/gnosis/director/pipeline.py`
- **symbol** `GovernedPipeline`
- **finding** 0 construcciones en `src/`, 1 en `tests/`. Es el **único** camino
  que exige `verifier` y `policy` como parámetros obligatorios y el único que
  refuerza independencia implementador≠revisor.
- **evidence** `pipeline.py:129-130`, `:173-180`; no hay `__main__`, `main()` ni
  `argparse` en todo `src/gnosis/`, ni `[project.scripts]` en `pyproject.toml`.
- **confidence** ALTA · **estado** II

### F-34 · FAIL · CRÍTICA · INVALID DONE alcanzable — no figura entre los 15 hallazgos abiertos

- **files** `src/gnosis/kernel/engine.py:457`, `:976`;
  `src/gnosis/director/orchestrator.py:53-125`
- **symbols** `TaskEngine.execute_task`, `DirectorOrchestrator.run_pending`
- **finding** el gate "no DONE sin evidencia" está **condicionado** a
  `authority is not None`:

  ```python
  # engine.py:457
  if authority is not None:
      if verifier is None:
          raise ValueError("a WorkAuthority-governed task requires a verifier: ...")

  # engine.py:976 — sin authority, sin verifier:
  verification_passed = verification_result.passed if verification_result else True
  task_sm.transition(TaskState.COMPLETED if verification_passed else TaskState.FAILED)
  ```

  `DirectorOrchestrator` — el que D-018 designa como *"the path real briefs
  travel"* — tiene `authority: WorkAuthority | None = None` por defecto y
  `run_pending(verifier: Verifier | None = None)` por defecto. Existe
  `require_policy` como opt-in fail-closed; **no existe `require_verifier` ni
  `require_authority`**.
- **failure scenario** alcanzable y concreto:

  ```
  DirectorOrchestrator(director_root, run_store, repo_path).run_pending()
  → TaskEngine.execute_task(verifier=None, authority=None)
  → el CLI devuelve exit 0
  → verification_passed = True        (sin verificador alguno)
  → TaskState.COMPLETED
  → EngineerReport(status=ReportStatus.COMPLETED)
  ```

  Un `DONE` sin ninguna evidencia. Viola la regla constitucional 2 y el requisito
  V1 nº17, en el camino por defecto del punto de entrada que la documentación
  designa como de producción.
- **confidence** ALTA
- **verificación sugerida** un test que construya el orquestador por defecto y
  afirme que **no** puede producir `ReportStatus.COMPLETED`; después, exigir
  evidencia en el punto más bajo que autoriza `COMPLETED`.

### F-35 · FAIL · ALTA · inerte en cadena (patrón L-0033 repetido)

- **file** `src/gnosis/director/supervisor.py:212`
- **symbol** `WorkerSupervisor.run` → `WorkAuthority.sweep()`
- **finding** la revisión independiente encontró que `WorkAuthority.sweep()` no
  tenía llamante de producción (L-0036) y toda reclamación por caducidad era
  inerte. La reparación colocó el llamante en `WorkerSupervisor.run`. Pero
  `grep -rn "WorkerSupervisor(" src/` → 1 resultado: `supervisor.py:178`, dentro
  de un **comentario** de su propio docstring. `WorkerSupervisor` no se construye
  en ninguna parte de `src/`.
- **evidence** el arreglo de "nada lo llama" fue añadir un llamante que nada
  alcanza — exactamente L-0033, que el propio proyecto redactó. El requisito V1
  nº19 está declarado *"implemented — repaired 2026-08-21, was inert"*; sigue
  inerte a nivel de programa.
- **confidence** ALTA · **estado** II / DI

### F-36 · FAIL · ALTA · ausente

- **symbol** `ProofPacket`
- **finding** sin símbolo productivo. `acceptance_criteria` existe en
  `DirectorBrief` pero sus únicos consumidores concatenan la lista al prompt
  (`orchestrator.py:289-290`, `pipeline.py:798-799`); nunca se mapea a evidencia
  ni se comprueba. El requisito V1 nº16 se declara implementado citando
  `scripts/capture_evidence.py`, que es una herramienta de CI **del repositorio
  GNOSIS**, no un artefacto por tarea.
- **evidence** la directiva exige "map acceptance criteria to evidence" y "a
  ProofPacket is mandatory for DONE".
- **confidence** ALTA · **estado** A / DI

### F-37 · FAIL · ALTA · parcial

- **file** `src/gnosis/adapters/`
- **symbol** adaptador Codex
- **finding** cero referencias a Codex como binario o adaptador en `src/` (las 20
  coincidencias de "Codex" son comentarios que citan revisiones).
  `ClaudeCodeCLIRunner.build_argv` emite dialecto Claude Code (`-p`,
  `--output-format`, `--permission-mode`, `--mcp-config`). `binary` es
  parametrizable, el argv no. `codex exec --sandbox read-only --json` no es
  alcanzable.
- **evidence** `claude_cli_runner.py:146-172`
- **confidence** ALTA · **estado** P / DI — las revisiones de Codex que sostienen
  la calidad del proyecto se ejecutaron **fuera** de GNOSIS.

### F-38 · UNCERTAIN · BAJA · acoplamiento

- **file** `src/gnosis/kernel/engine.py:21`, `:416`
- **finding** D-021 se cumple en su letra (`grep "from ..adapters"
  src/gnosis/kernel/` → vacío), pero el kernel importa e instancia por defecto
  `ClaudeCodeCLIRunner`, específico de proveedor, desde `runner/`. La neutralidad
  es inyectable, no estructural.
- **confidence** ALTA sobre el hecho, BAJA sobre su gravedad.

### F-39 · FAIL · MEDIA · contratos obligatorios

`MASTER_AUTONOMOUS_BUILD_DIRECTIVE.md § Core contracts` exige 20 modelos
versionados y tipados.

| Estado | Contratos |
|---|---|
| **Presentes con ese nombre (4)** | `Lease`, `Finding`, `PolicyDecision`, `MemoryRecord` |
| **Equivalente funcional, otro nombre (7)** | `LedgerEvent`≈Event · `ExecutionResult`≈AgentResult · `VerificationResult`≈VerificationRun · `ReviewReport`≈Review · `WorktreeHandle`≈Workspace · `FailureClassification`≈Failure · `CompactContext`≈ContextPack (parcial) |
| **Ausentes sin equivalente (9)** | `Project` · `Task` · `TaskDependency` · `TransitionRequest` · `AgentInvocation` · `ProofPacket` · `Artifact` · `SkillCandidate` · `EvalRun` |

### F-40 · FAIL · MEDIA · subsistemas completamente inertes

874 líneas sin ningún consumidor en `src/`:

| file | líneas | consumidores en `src/` |
|---|---|---|
| `kernel/memory.py` + `memory_reference.py` + `memory_router.py` | 599 | 0 (sólo un comentario en `engine.py:286`) |
| `kernel/code_intelligence_adapters.py` (`CodegraphMcpAdapter`) | 191 | 0 |
| `transport/` (`DirectorTransport`, `Manual`, `Mcp`) | 84 | 0 |

Igualmente sin construcción en `src/`: `TaskScheduler`, `CredentialPool`,
`WorkQueue`, `WorkIntegrator`, `IntentJournal`, `drain()`. Existen como
parámetros de `GovernedPipeline`/`WorkerSupervisor`, que a su vez nadie
construye — la inercia es transitiva.

### F-41 · PASS · ledger append-only

`kernel/ledger.py`: hash-chain con `prev_hash`, verificación completa de la
cadena antes de extenderla, ledgers legacy pre-chain legibles pero que rechazan
appends. Requisito V1 nº21 correcto. **confidence** ALTA.

### F-42 · PASS · integridad Git

`reset --hard` aparece únicamente como cadena de texto devuelta al operador
(`integration.py:639`), nunca ejecutada. `worktree remove --force` está
provenance-gated. Sin force-push ni `clean -fdx`. Requisito V1 nº22 correcto.
**confidence** ALTA.

---

## Matriz corregida de cumplimiento V1

**IA** implementado y alcanzable · **II** implementado pero inerte · **P** parcial · **A** ausente · **DI** declarado incorrectamente

### Capacidades del Definition of Done

| # | Capacidad | Informe dice | Módulo | Alcanzable en producción | Veredicto |
|---|---|---|---|---|---|
| 1 | proyecto/tarea durable | implemented | P — `BriefRecord`+`RunMeta` durables; sin `Project`; `TaskState` sólo en memoria | sí (orquestador) | **P / DI** |
| 2 | representar dependencias | implemented (`ordering.py`) | **A** — no existe `TaskDependency` ni grafo | — | **A / DI** (F-01, F-02) |
| 3 | detectar tareas listas | implemented | P — readiness temporal (`not_before`), no por dependencias | vía `WorkQueue` (sin constructor) | **P / DI** (F-04) |
| 4 | claim con lease/fencing | implemented | IA | II — sólo si el caller inyecta `WorkAuthority`; nadie lo hace | **II** |
| 5 | rechazar escrituras stale | HARD | IA — `_GuardedRunStore` re-prueba propiedad | II | **II** |
| 6 | worktree aislado | SANDBOX_APPROX | IA | II | **II** |
| 7 | FakeClaude/FakeCodex en CI | implemented | P — fakes ad-hoc por fichero; sin familia reutilizable | n/a | **P** |
| 8 | adaptadores reales Claude/Codex | implemented | P — sólo Claude; argv específico de proveedor | no | **P / DI** (F-37) |
| 9 | capturar salidas estructuradas/raw | implemented | IA | II | **II** |
| 10 | clasificar rate limits aparte | implemented | IA | II | **II** |
| 11 | salida malformada con reparación acotada | implemented | IA | II | **II** |
| 12 | timeout/cancel de subproceso | implemented | IA | II | **II** |
| 13 | verificación determinista | implemented | IA | II | **II** |
| 14 | review read-only | SANDBOX_APPROX | IA | II | **II** |
| 15 | rework acotado | implemented | IA | II | **II** |
| 16 | proof packet | implemented (`capture_evidence.py`) | **A** — sin `ProofPacket` | — | **A / DI** (F-36) |
| 17 | rehusar DONE sin evidencia | implemented | **P + defecto** — gate condicionado a `authority is not None` | **el fallo sí es alcanzable** | **P / DI** (F-34) |
| 18 | sobrevivir reinicio del kernel | implemented | IA | II | **II** |
| 19 | recuperar tras crash de worker | implemented — *repaired, was inert* | IA | **II** — el llamante de `sweep()` es `WorkerSupervisor`, que nada construye | **II / DI** (F-35) |
| 20 | evitar bucles infinitos | implemented | P — breakers existen; `max_briefs` y `wall_clock_s` por defecto `None`; sin "max same failure" | II | **P** |
| 21 | eventos de auditoría append | implemented | IA — hash-chain verificada | II | **II** |
| 22 | preservar integridad Git | implemented | IA | II | **II** |

### Suite de supervivencia

| Escenario | Informe dice | Realidad verificada | Veredicto |
|---|---|---|---|
| worker kill | ~10 ficheros | cobertura real y semántica | **PASS** |
| kernel restart | ~8 ficheros | cobertura real | **PASS** |
| stale lease | ~4 ficheros | cobertura real, incl. contención con hilos | **PASS** |
| repeated identical failure | **0 — absent** | cotas de intentos sí; breaker por clase de fallo no | **PARCIAL** — informe incorrecto |
| no-diff loop | **0 — absent** | 5 pruebas de stalemate sobre fingerprint del repo | **PASS** — informe **falso** |
| malformed JSON | ~6 ficheros | 13 pruebas de payload + invalid-output del supervisor | **PASS** |
| timeout | ~49 ficheros | `test_timeout_kills_process`, revisor con timeout | **PASS** |
| rate limit simulation | ~13 ficheros | 29 pruebas entre `failures`/`scheduler` | **PASS** |
| reviewer disagreement | ~6 ficheros | verdicts UNCERTAIN, conflicto verificación↔verdict, findings bloqueantes | **PASS** |
| merge conflict | ~5 ficheros | conflicto textual tipado + merge limpio que rompe el árbol | **PASS** |
| invalid state transition | **0 — absent** | 5 pruebas sobre el plano **en memoria**; cero validación en los dos planos **durables** | **PARCIAL** — informe **falso en la dirección contraria** |

### Los cuatro invariantes

| Invariante | Suite nombrada | Estado real |
|---|---|---|
| NO LOST WORK | **A** | implicado; 1 comentario (`test_worktree.py:272`) |
| NO INVALID DONE | **A** | implicado; 1 comentario — y F-34 demuestra que es violable por el camino por defecto |
| NO STALE WRITE | **A** | implicado; 2 comentarios; mecánicamente sólido |
| NO INFINITE LOOP | **A** | implicado; breakers presentes con defaults apagados |

---

## Conclusión del diagnóstico

Las tres sospechas de la revisión externa se confirman, con matices que cambian
su prioridad:

1. **El DAG no existe** (F-01…F-04). Los requisitos V1 nº2 y nº3 no tienen
   implementación; `ordering.py` resuelve un problema distinto (orden de
   aterrizaje post-convergencia).
2. **Los escenarios "ausentes" no lo estaban**, pero el hueco real es peor y
   estaba oculto: la validación de transiciones existe sólo en el plano que no
   sobrevive al proceso (F-07, F-08).
3. **La evidencia no liga criptográficamente** (F-14…F-18), y el proyecto ya
   posee la primitiva correcta sin usarla.
4. **Deriva documental** (F-19…F-32): 14 contradicciones, dos internas a un mismo
   fichero, y un README que describe un proyecto de hace veinte ADRs.
5. **Hallazgo nuevo, no listado entre los 15 abiertos: F-34** — el punto de
   entrada por defecto puede emitir `COMPLETED` sin ninguna evidencia. Violación
   directa de la regla constitucional 2 por el camino que la documentación
   designa como de producción. Prioridad máxima, por encima del punto de entrada
   ausente.

**Patrón transversal:** el proyecto tiene el mecanismo correcto casi siempre, y
casi nunca tiene quien lo invoque. De 22 capacidades V1, 13 son *implementadas
pero inertes* — correctas como módulo, inalcanzables como programa. El propio
proyecto nombró esto (L-0033, L-0036, Directiva 9) y F-35 muestra que la última
reparación volvió a caer en él.

---

## Orden de reparación acordada con dirección (2026-08-22)

Unidad de trabajo en curso: **exclusivamente F-34**. No se reparan F-01…F-33 ni
F-35…F-42 en esta unidad. Este documento se congela como diagnóstico previo a esa
reparación.
