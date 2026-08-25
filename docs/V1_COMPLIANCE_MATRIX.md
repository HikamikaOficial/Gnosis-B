# GNOSIS — Matriz V1 viva

**Última actualización:** 2026-08-25 · **Unidad:** ADR-0026 + once
revisiones independientes (las diez anteriores más **F-14.11 auditoría de
CLEAN sobre COMPLETE / memory-mapping**) — **F-14 CERRADO** por la
**duodécima revisión independiente (2026-08-25): APPROVED**, dentro del
contrato formal declarado.
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
| **F-14** — la evidencia no vinculaba los bytes probados (y sus derivados a lo largo de once revisiones) | ADR-0026 (+11 addenda) | 2026-08-25 | **duodécima revisión independiente: APPROVED**, dentro del contrato formal; implementación `1672a8a`, evidencia `cd6d1b5`, paquete `.gnosis/evidence/20260825T135642Z/` |

Dos de 43. F-34 ya fue marcado cerrado una vez, el 2026-08-22, y hubo que
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

## F-14 — CERRADO por la duodécima revisión independiente

**F-14 está CERRADO.** Tras diez reparaciones y una auditoría, la
**duodécima revisión independiente (2026-08-25)** devolvió **APPROVED /
CLOSE F-14** dentro del contrato formal declarado. Esta tabla mueve un
hallazgo a «cerrado» por la única regla que admite: una revisión
independiente que acepta el estado. El historial completo de las once
revisiones previas se conserva abajo, y las limitaciones y condiciones de
revalidación se preservan explícitamente y **no** se convierten en
garantías más fuertes.

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

| **F-14 (sexta revisión)** — el chequeo de reparse point miraba el *target* y nunca la *ruta* usada para alcanzarlo: una junction sobre un input cubierto se retargeteaba a otro directorio del mismo volumen con el handle del objeto abierto, y el check leía el otro directorio. Segundo defecto: `classify_observation` perdonaba cualquier evento de directorio por serlo al final, que es justo la forma que deja una junction borrada y recreada | ADR-0026 addendum 6 | 2026-08-24 | **reparado, pendiente de séptima revisión** | `reparse_in_chain()` recorre desde la unidad: la raíz y todos sus ancestros una vez, y cada componente entre la raíz y el input; un solo reparse point rechaza la captura antes de ejecutar nada (junctions declinadas, no soportadas). El clasificador sólo perdona `modified` sobre un directorio; crear, borrar o renombrar uno se juzga. 103 pruebas y 7 subtests; veinticuatro mutantes, ninguno sobrevive; sonda de diez casos en cuatro grupos |

| **F-14 (séptima revisión)** — tres sitios daban por hecho que los ficheros ignorados por Git quedaban fuera de la frontera (`content_fingerprint` no los enumera, `covered_paths` no los añadía, `classify_observation` perdonaba lo que `git check-ignore` aceptase). Juntos equivalían a «ignorado ⇒ no puede afectar al resultado», que es falso: un `.env`, una config local, una base de datos o el propio `.venv` son inputs reales. Reproducido: un check leyó `MALICIOUS` de un fichero ignorado y el paquete se declaró `CLEAN` / `evidence_valid: true` / `all_passed: true` | ADR-0026 addendum 7 | 2026-08-24 | **reparado, pendiente de octava revisión** | tres clases declaradas: **INPUT** por defecto (todo lo que git enumera, ignorados incluidos: cubierto, bloqueado, identificado), **OUTPUT** declarado (los checks escriben ahí), **OUT_OF_SCOPE** declarado (sin reclamación; cualquier evento allí es violación). `git check-ignore` deja de consultarse. Medido: 2.944 inputs en 2,3 s frente a 90.237 y 1.218 s si se expanden los clones anidados. 118 pruebas y 19 subtests; veinticinco mutantes, ninguno sobrevive |
| **F-14 (octava revisión)** — la revisión tomó el riesgo residual nº3 que yo mismo había escrito y lo convirtió en el hallazgo: un input ignorado quedaba **cubierto, bloqueado e identificado por objeto**, y sus **bytes** no estaban en ninguna parte de la evidencia. Identidad de objeto (`FILE_ID_INFO`: *qué* fichero), estabilidad temporal (el cerrojo: *no cambió mientras corrían los checks*) e identidad criptográfica de contenido (*qué había dentro*) son tres garantías distintas, y tener dos se leía como tenerlas las tres. Casi 2.000 de los 2.958 inputs eran `.venv`: el intérprete y las herramientas que produjeron el resultado, dentro de la frontera por objeto y fuera por contenido | ADR-0026 addendum 8 | 2026-08-25 | **reparado, pendiente de novena revisión** | cada input se hashea **a través del handle que lo sostiene** (`SetFilePointerEx` + `ReadFile`, no una segunda apertura por ruta): `content_digests`, `content_digest` — deliberadamente distinto de `identity_digest` — e invariante `fully_bound` (`locked == len(content_digests)`) afirmada en el productor y re-comprobada en el consumidor con un fallo propio. `input-manifest.json` en el paquete para que un tercero **re-derive** la afirmación desde los ficheros. `.venv` se queda como INPUT y se ata como todo lo demás (opción A, medida: 2.958 ficheros / 99,4 MB en 2,39 s en caliente); una clase TOOLCHAIN con provenance por versiones nominales habría sido más maquinaria para una garantía más débil. **OUT_OF_SCOPE se elimina del código**, no se vacía: el modelo «demostrar que ningún check puede leerlo» se probó y falló (un handle de directorio con `FILE_SHARE_NONE` bloquea *listar* y **no** bloquea abrir por ruta los ficheros de dentro), así que se paga el precio medido — 88.424 ficheros y 2,4 GB, 1.170 s de hash en frío. Lo que ya existe bajo una raíz OUTPUT al empezar se hashea en `outputs_at_start`, de modo que un fichero plantado ahí y leído por un check queda nombrado. 127 pruebas; veintinueve mutantes, ninguno sobrevive. Captura `.gnosis/evidence/20260825T011601Z/` sobre `de74053`: **90.245 inputs** bloqueados, identificados y hasheados (`fully_bound` true), `identity_digest ec4dbb5c…` distinto de `content_digest 55d64f5b…`, frontera CLEAN, `evidence_valid` true, salida 0; muestra de 301 entradas del manifest re-derivada 301/301 |
| **F-14 (novena revisión)** — **NTFS Alternate Data Streams**. Un path no es un flujo de bytes: en NTFS es `::$DATA` más cualquier número de streams con nombre, cada uno abrible como `path:name`, cada uno legible por un check, y ninguno visible para `git ls-files`, para `Path.read_bytes` ni para un handle sobre el stream principal. Reproducido antes de tocar código: con `probe.txt::$DATA` intacto y `probe.txt:gnosis-f14` pasando de `ALLOW` a `DENY`, el check leyó bytes distintos y los dos paquetes salieron con `identity_digest` y `content_digest` **idénticos**, ambos `evidence_valid: true`. Medido además: el handle sobre el stream principal dejaba el stream con nombre **escribible y borrable**, y los directorios también llevan streams | ADR-0026 addendum 9 | 2026-08-25 | **reparado, pendiente de décima revisión** | opción **A**: cada stream con nombre de cada INPUT —y de cada directorio, incluida la raíz— recibe su propio handle, su propia identidad y su propio digest leído a través de ese handle. La identidad es `owner-id:file-id:nombre:longitud` porque `FILE_ID_INFO` devuelve el MISMO id para todos los streams de un fichero; sólo el digest separa dos contenidos de igual longitud, y hay una prueba que lo demuestra. Enumeración con `FindFirstStreamW`; un path cuyos streams no se pueden enumerar es **refusal**, nunca un encogimiento de hombros. Ningún share mode impide **crear** un stream nuevo (medido, incluido `FILE_SHARE_NONE`), así que hay un segundo detector independiente del observador: el inventario se toma con la frontera levantada y otra vez tras los checks, y cualquier stream que aparezca, desaparezca o cambie de longitud es `STREAMS_MUTATED`, salida 8. El disco se recorre para los 83 directorios que no contienen ningún input. `outputs_at_start` hashea también los streams preexistentes. 148 pruebas; treinta y cinco mutantes, ninguno sobrevive. Captura `.gnosis/evidence/20260825T043839Z/` sobre `42f461b`: 90.261 inputs, **0 streams con nombre** en este árbol (ítem 8: ningún falso positivo), `identity_digest eb7af0e4…`, `content_digest 3568d3ef…`, frontera CLEAN, `evidence_valid` true, salida 0 |
| **F-14 (décima revisión, F-14.10)** — **ABA de named streams sobre directorios**. Un stream con nombre creado y borrado sobre un **directorio** durante el intervalo deja los dos inventarios idénticos; el cerrojo no puede pre-abrir un stream que aún no existe; y el observador perdonaba el único evento que un directorio produce, `modified <dir>`, porque un movimiento de entradas produce lo mismo. Reproducido antes de tocar código contra `git archive 8dd621c`, por `run_capture`: `pkg:secret` (y un stream sobre la **raíz** del repo) creado→leído→borrado, el check leyó `ALLOW`, frontera **CLEAN**, `evidence_valid: true`, salida 0 | ADR-0026 addendum 10 | 2026-08-25 | **reparado, pendiente de undécima revisión** | el observador pide ahora los filtros de stream (`0x200|0x400|0x800`) y mapea las acciones 6/7/8; un `added_stream`/`removed_stream` sobre cualquier ruta cubierta es `STREAMS_MUTATED` (salida 8). Medido: un `added_stream` distingue el stream de un movimiento de entradas (que no produce acción de stream), y **leer** un stream produce `modified_stream` —así que esa acción no es violación; el capture lee cada stream bloqueado para hashearlo, y un **escritura** sobre un stream presente al bloquear está prohibida por el cerrojo—. Los streams propios de la **raíz** son invisibles a su propio watch recursivo, así que un segundo watch **no recursivo sobre el padre** los cubre, filtrado a la entrada de la raíz y con su propia barrera; si no hay padre observable, la observación es INCOMPLETA (fail-closed), no CLEAN. El USN journal registra el ABA (`STREAM_CHANGE`, append-only) pero exige handle de volumen con privilegios de admin, así que corrobora y no se usa como dependencia. `fully_identified`/`fully_bound` se documentan explícitamente como propiedades del **snapshot**, no del intervalo (`scope_note` en el paquete). 156 pruebas; cuarenta mutantes, ninguno sobrevive |
| **F-14 (undécima revisión, F-14.11)** — auditoría de `CLEAN over COMPLETE observation`: ¿existe una ventana temporal sin observar entre el inicio real del boundary y el final real de la captura, en especial vía **memory mapping** creado antes del boundary? **No se halló bypass nuevo.** Medido en NTFS real: una escritura por *mapping* cambia los bytes al instante y `ReadDirectoryChangesW` no notifica nada (ni siquiera en `FlushViewOfFile`), así que la observación no es la defensa; lo es el cerrojo, que **falla cerrado** ante cualquier *mapping* escribible vivo (`ERROR_SHARING_VIOLATION`), bajo todos los share modes, en fichero y en named stream, y no permite crear uno nuevo mientras sostiene el input; `run_capture` con un *mapping* vivo → UNPROTECTED, salida 6, sin ejecutar checks. COW coexiste pero no toca el fichero | ADR-0026 addendum 11 | 2026-08-25 | **auditado, pendiente de duodécima revisión** | única alteración productiva: `complete_note` en el paquete (honestidad; ninguna lógica resultó defectuosa). Lifecycle confirmado en el código: watch armado ANTES del boundary; barrera ordenada drenada ANTES de aceptar CLEAN → sin start-race ni end-race. Overflow / watch caído / padre inobservable → UNOBSERVED, nunca CLEAN. Invariante `modified_stream` demostrada: un stream bloqueado no admite sobrescritura, truncado, borrado, segundo handle escribible ni *mapping*. `COMPLETE` definido formalmente como «ningún evento del mecanismo soportado se perdió», separado de `fully_identified`/`fully_bound` (propiedades del snapshot). 166 pruebas; cuarenta y dos mutantes, ninguno sobrevive |
| **F-14 (duodécima revisión) — CIERRE** | ADR-0026 (cierre) | 2026-08-25 | **APPROVED / CLOSE F-14** | la revisión independiente acepta: `fully_identified`/`fully_bound` son propiedades del **snapshot** (no del intervalo); `COMPLETE` se limita al mecanismo de observación soportado; no hay ventana sin observar entre el armado de los watchers y la barrera final; overflow / observer failure / unavailable observer / unwatchable parent **fallan cerrado**; el parent watcher cubre la raíz y el ruido de hermanos está probado; el directory ADS ABA queda cubierto dentro de una observación COMPLETE; el escenario memory-mapped se probó en Windows/NTFS real y un *mapping* escribible no puede modificar el objeto con el lock adquirido; los streams bajo lock son inmutables por las rutas medidas; la tolerancia de `modified_stream` se acepta **condicionada a revalidación** si cambia la plataforma o aparece una nueva ruta de escritura; las limitaciones restantes quedan declaradas y no se elevan a garantías. Implementación `1672a8a`, evidencia `cd6d1b5`, paquete `.gnosis/evidence/20260825T135642Z/`. 166 pruebas, 1040 en suite completa, 42 mutantes 0 supervivientes, mypy limpio, Ruff baseline, frontera CLEAN, `evidence_valid=true` |

**F-14 está demostrado sobre:** Windows, volumen local, tipo `fixed`,
filesystem `NTFS`. Y sobre nada más. **ReFS es una extensión candidata
pendiente de validación real**, no una garantía actual: se rechaza con un
motivo que dice explícitamente que nadie ha ejecutado la frontera ahí.
Cualquier otro entorno se rechaza antes de tomar un solo handle, en lugar
de suponerse equivalente.

## Hallazgos abiertos

F-01, F-02, F-03, F-04, F-05, F-07, F-08, F-10, F-12, F-13,
F-15, F-16, F-17, F-18, F-19…F-32, F-33, F-35, F-36, F-37, F-38, F-39,
F-40. (**F-14 ya no está aquí: CERRADO 2026-08-25.**)

**Recuento, para que ningún documento vivo lo repita mal:** el diagnóstico
congelado tiene **43 elementos** (F-01…F-42 más F-29b). De ellos **6 son
PASS** y no son defectos (F-06, F-09, F-11, F-29b, F-41, F-42), **2 están
cerrados** (F-34 y ahora F-14) y **35 siguen abiertos** — los enumerados
arriba, ya **sin** F-14, que la duodécima revisión independiente cerró el
2026-08-25. Historial del recuento, porque ha estado mal varias veces: una
versión dijo 41, contando los PASS y F-34 como trabajo; otra dijo
"1 cerrado (F-34)" antes de que la tercera revisión lo reabriera; otra
dijo "0 cerrados y 37 abiertos", correcto mientras F-34 estuvo reabierto;
y durante once revisiones F-14 estuvo reparado pero abierto. El recuento
vivo es **6 PASS · 2 cerrados · 35 abiertos**.

Ninguno de los 36 se ha tocado en ninguna de las cuatro pasadas de F-34.
ADR-0026 toca exactamente uno de ellos, F-14, y lo deja abierto. Los 15
hallazgos abiertos de las revisiones anteriores (`PROJECT_REPORT.md §8`)
siguen igual.
