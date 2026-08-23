# GNOSIS — Matriz V1 viva

**Última actualización:** 2026-08-23 · **Unidad:** ADR-0026 + cinco
revisiones independientes (**FAIL CRÍTICO**, **FAIL CRÍTICO
PROVISIONAL**, **reparación aceptada con cierre en hold**, **FAIL DE
ALCANCE**, **FAIL PARCIAL/ALTA**) — **F-14 sigue ABIERTO**, entregado
para una sexta revisión independiente.
Unidad anterior: ADR-0025 + cuatro addenda (FAIL PARCIAL, FAIL PARCIAL,
**FAIL CRÍTICO**, **PASS**) — F-34 **CERRADO** por la cuarta revisión,
sin hallazgos sobre el código `9c6064c` y la evidencia `f02e18e`

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

## F-14 — reparación entregada, PENDIENTE DE REVISIÓN INDEPENDIENTE

**F-14 sigue ABIERTO.** La reparación existe, está probada y tiene
evidencia; lo que no tiene todavía es una revisión independiente. Esta
tabla no mueve un hallazgo a «cerrado» por parecerlo, y menos después de
lo que costó F-34.

| Hallazgo | ADR | Fecha | Estado | Evidencia |
|---|---|---|---|---|
| **F-14** — la evidencia capturada no identifica de forma vinculante los bytes probados: `git status` es estado y nombre, nunca contenido | ADR-0026 | 2026-08-22 | reparado; **primera revisión independiente: FAIL CRÍTICO** | 36 pruebas, nueve mutantes; el vínculo probaba los extremos, no el intervalo |
| **F-14 (primera revisión)** — dos huellas iguales no demuestran estabilidad: una comprobación que cambia un fichero, lee el cambio y restaura los bytes, el tamaño y las fechas devolvía `evidence_valid: true`. Cambio transitorio (ABA) | ADR-0026 addendum 1 | 2026-08-23 | reparado | observador de escrituras (`ReadDirectoryChangesW`) armado antes de la huella previa y cerrado tras una barrera de entrega |
| **F-14 (segunda revisión)** — la barrera demuestra que se entregaron las notificaciones **generadas**, no que toda modificación generase una: una escritura por *memory mapping* no notifica nada, y una comprobación consumió bytes mutados dentro de un paquete que se certificó a sí mismo | ADR-0026 addendum 2 | 2026-08-23 | **reparado, pendiente de tercera revisión** | los inputs cubiertos dejan de ser escribibles durante las comprobaciones (`CreateFileW` con `FILE_SHARE_READ`): escritura, mapeo escribible, borrado y renombrado quedan rechazados por el sistema. 718 inputs bloqueados en 6,17 s. 65 pruebas y 3 subtests; dieciséis mutantes, ninguno sobrevive; sonda de rotura re-ejecutable (`scripts/probe_f14_boundary.py`) |

Qué hace la reparación: `probe_tree_identity()` envuelve
`content_fingerprint()` — HEAD, el parche contra él y el sha256 de cada
fichero sin seguimiento, por ruta — y la huella se toma **antes** de la
primera comprobación y **después** de la última. Ambas huellas completas
van a `SUMMARY.json`. Si difieren, o si alguna no pudo obtenerse, la
captura no es evidencia y lo dice, hayan pasado las pruebas o no. El
bundle se construye fuera del repositorio y se publica después de la
huella final, para que la evidencia no aparezca en su propia huella.

Tras la primera revisión: **el intervalo tiene su propia autoridad.**
Un observador de escrituras se arma antes de la huella previa y se cierra
después de la posterior, detrás de una barrera de entrega que demuestra
que la cola del flujo llegó. Un cambio que se deshace a sí mismo sigue
siendo un cambio (`INPUTS_MUTATED`, salida 4); un flujo que pudo perder
algo — desbordamiento, barrera no observada, mecanismo ausente — no es
«no pasó nada» (`UNOBSERVED`, salida 5). `evidence_valid` es ahora la
conjunción: extremos iguales **y** intervalo observado limpio.

Y tras la segunda: **observar no basta, porque una escritura puede
negarse a ser observada.** Una modificación hecha a través de una vista
mapeada en memoria no genera notificación alguna; reproducido, con una
comprobación consumiendo los bytes mutados y el paquete declarándose
válido. La reparación no tapa el caso: durante las comprobaciones los
inputs cubiertos **dejan de ser escribibles**. El sistema rechaza
escritura, mapeo escribible, borrado y renombrado; lo que no puede
bloquearse por adelantado —rutas que aún no existen— sigue siendo trabajo
del observador. Si algún input no puede protegerse, no se ejecuta nada
(`UNPROTECTED`, salida 6).

**Solapamiento observado con F-15…F-18, que NO se marcan reparados:**
F-15 (la primitiva existía sin usarse) — este script ya la usa, que era
la corrección sugerida, pero el hallazgo abarca la superficie de
evidencia y aquí cambió un script; F-16 (orden de captura) — la huella
previa se toma antes de todo, así que el vínculo ya no depende del orden,
pero la lista de comandos sigue igual y `git-status.stdout.txt` sigue
siendo un artefacto posterior a la suite; F-17 (tamper-evidence) —
`SUMMARY.json` ya contiene HEAD, el digest de status y las dos
identidades completas, pero **no hay hash-chain ni firma**, que es de lo
que trata F-17; F-18 (deriva de evidencia) — intacto. El addendum añade un solapamiento
más, también sin reclamar: las escrituras bajo `.git/` se **cuentan** y no
se juzgan, porque git reescribe su índice al leer el árbol; un gancho
instalado durante la captura queda fuera de esta frontera y dentro de
F-17, que sigue abierto. Tras el addendum 2 se añade un residuo más: los
atributos de un input cubierto todavía pueden cambiarse (no concede
escritura mientras el modo de compartición esté vigente, y el observador
lo ve), y la frontera entera es un mecanismo de Windows.

| **F-14 (tercera revisión)** — la reparación se acepta y el cierre queda en hold: faltaba atar el handle protegido al objeto identificado, la ventana de adquisición de ~700 cerrojos no estaba cubierta, y la garantía se extrapolaba a cualquier volumen | ADR-0026 addendum 3 | 2026-08-23 | **reparado, pendiente de cuarta revisión** | sección escribible sin handle de archivo rechazada en cuatro formas (error 32); `FILE_ID_INFO` por handle + verificación de ruta final + rechazo de reparse points; identidad **posterior** al bloqueo (`PREPARATION_DRIFT`, salida 7); capacidades de volumen en lista blanca (`fixed` + NTFS; ReFS retirado en el addendum 4). 733 inputs bloqueados e identificados en 0,45 s. 84 pruebas y 7 subtests; veinte mutantes, ninguno sobrevive; sonda de nueve casos |

| **F-14 (cuarta revisión)** — sin hallazgo nuevo contra la arquitectura: el dominio **aceptado** por el código (`NTFS` + `ReFS`) era más ancho que el **demostrado** (`NTFS`). Ninguna ejecución real sobre ReFS, ningún paquete de evidencia lo menciona, y las dos pruebas que lo nombraban sólo lo admitían como alternativa en una aserción que siempre resolvía por NTFS | ADR-0026 addendum 4 | 2026-08-23 | **reparado, pendiente de revisión final** | `_SUPPORTED_FILESYSTEMS = {"NTFS"}`; ReFS pasa a `_CANDIDATE_FILESYSTEMS` y se rechaza con motivo propio antes de abrir un solo input; 87 pruebas y 7 subtests; veintiún mutantes, ninguno sobrevive (MF21 reintroduce ReFS y la suite se pone roja) |

| **F-14 (quinta revisión)** — ruta fail-open: un input cubierto de tipo directorio (gitlink de submódulo) se reabría con `FILE_FLAG_BACKUP_SEMANTICS`, contaba como handle bloqueado y **nunca se identificaba**, así que un resultado podía declarar `enforced=true` sosteniendo un objeto que no sabía nombrar — contra la garantía publicada por el propio módulo | ADR-0026 addendum 5 | 2026-08-23 | **reparado, pendiente de sexta revisión** | los inputs cubiertos de tipo directorio se rechazan **antes** de abrirlos (submódulos declinados, no soportados); no queda ninguna ruta que añada un handle sin identificarlo; invariante `locked == identified` afirmado en el productor y re-comprobado en el consumidor, y registrado como `protection.fully_identified`; todo objeto identificado debe estar en el volumen sondeado por `VolumeSerialNumber` (cierra el reparse point en un ancestro). 94 pruebas y 7 subtests; veintidós mutantes, ninguno sobrevive |

**F-14 está demostrado sobre:** Windows, volumen local, tipo `fixed`,
filesystem `NTFS`. Y sobre nada más. **ReFS es una extensión candidata
pendiente de validación real**, no una garantía actual: se rechaza con un
motivo que dice explícitamente que nadie ha ejecutado la frontera ahí.
Cualquier otro entorno se rechaza antes de tomar un solo handle, en lugar
de suponerse equivalente.

## Hallazgos abiertos

F-01, F-02, F-03, F-04, F-05, F-07, F-08, F-10, F-12, F-13, **F-14**,
F-15, F-16, F-17, F-18, F-19…F-32, F-33, F-35, F-36, F-37, F-38, F-39,
F-40.

**Recuento, para que ningún documento vivo lo repita mal:** el diagnóstico
congelado tiene **43 elementos** (F-01…F-42 más F-29b). De ellos **6 son
PASS** y no son defectos (F-06, F-09, F-11, F-29b, F-41, F-42), **1 está
cerrado** (F-34) y **36 siguen abiertos** — exactamente los enumerados
arriba, F-14 incluido: reparado en ADR-0026 y **no** cerrado, porque
ninguna revisión independiente lo ha visto todavía. El recuento no cambia
en esta unidad. Historial del recuento, porque ha estado mal dos veces: una
versión dijo 41, contando los PASS y F-34 como trabajo; otra dijo
"1 cerrado (F-34)" antes de que la tercera revisión lo reabriera; otra
dijo "0 cerrados y 37 abiertos", correcto mientras F-34 estuvo reabierto.
El recuento vivo es **6 PASS · 1 cerrado · 36 abiertos**.

Ninguno de los 36 se ha tocado en ninguna de las cuatro pasadas de F-34.
ADR-0026 toca exactamente uno de ellos, F-14, y lo deja abierto. Los 15
hallazgos abiertos de las revisiones anteriores (`PROJECT_REPORT.md §8`)
siguen igual.
