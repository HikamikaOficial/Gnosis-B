# GNOSIS — Catálogo completo de repositorios investigados
> **Fecha de consolidación:** 18 de agosto de 2026  
> **Objetivo:** biblioteca técnica de recursos descubiertos durante la investigación para diseñar **Gnosis**, un sistema local de ingeniería autónoma multiagente centrado inicialmente en Claude Code + Codex.  
> **Nota:** las puntuaciones son una **valoración de encaje con Gnosis**, no una nota objetiva del proyecto. Los repositorios evolucionan; antes de integrar código se debe volver a comprobar licencia, actividad, seguridad y documentación.
## Leyenda

- **Tier S** — referencia crítica / candidata a uso o disección inmediata.
- **Tier A** — muy valiosa; estudiar/testear seriamente.
- **Tier B** — cantera de mecanismos, benchmark o alternativa.
- **Tier C** — referencia secundaria, catálogo o idea de futuro.
## Resumen

- Repositorios con ficha: **126**
- Referencias ambiguas conservadas: **6**
- Grupos funcionales: **12**

# A. Orquestación, meta-harness y control plane
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [Paperclip](https://github.com/paperclipai/paperclip) | **B** | **8.9/10** | Sistema operativo para organizaciones de agentes: objetivos, organigramas, presupuestos, gobernanza, proyectos y panel de control. |
| [AWS CLI Agent Orchestrator (CAO)](https://github.com/awslabs/cli-agent-orchestrator) | **B** | **8.7/10** | Orquestador supervisor-worker para múltiples agentes CLI, incluidos Claude Code y Codex. |
| [Agent Orchestrator](https://github.com/Untrivial-ai/agent-orchestrator) | **A** | **9.3/10** | Meta-harness/IDE para gestionar muchas sesiones de agentes en paralelo mediante worktrees, branches, PR, CI y review. |
| [MetaSwarm](https://github.com/dsifry/metaswarm) | **B** | **8.9/10** | Lifecycle multiagente orientado a especificación, TDD, implementación, revisión adversarial y entrega. |
| [Codex Orchestrator](https://github.com/kingbootoshi/codex-orchestrator) | **B** | **8.1/10** | Permite que Claude Code lance, supervise y dé instrucciones a workers Codex en paralelo. |
| [Claudexor](https://github.com/razzant/claudexor) | **A** | **9.4/10** | Control plane local-first sobre Claude Code, Codex CLI y otros harnesses, con interfaz tipada, Best-of-N y revisión cruzada. |
| [Ouroboros](https://github.com/razzant/ouroboros) | **C** | **7.5/10** | Agente persistente/autoevolutivo con memoria, identidad durable, backlog y capacidad de modificar su propia implementación. |
| [Ruflo](https://github.com/ruvnet/ruflo) | **B** | **8.6/10** | Meta-harness de gran escala con swarms, numerosos agentes especializados, memoria y coordinación distribuida. |
| [Kodo](https://github.com/ikamensh/kodo) | **B** | **8.8/10** | Orquestador autónomo que dirige agentes de programación y separa implementación de testing/review. |
| [Bernstein](https://github.com/sipyourdrink-ltd/bernstein) | **S** | **9.9/10** | Orquestador determinista para agentes CLI con scheduler fuera del LLM, worktrees, quality gates, journal, replay y auditoría. |
| [OMK (Open Multi-Agent Kit)](https://github.com/dmae97/omk) | **B** | **8.8/10** | Control plane provider-neutral con DAGs, lanes, evidencia, replay y recuperación. |
| [Maestro](https://github.com/RunMaestro/Maestro) | **B** | **8.5/10** | Command center de escritorio para múltiples agentes, grupos, playbooks y worktrees. |
| [Cezar](https://github.com/open-mercato/cezar) | **S** | **10/10** | Orquestador local de agentes de programación con workflows multi-runner, worktrees aislados, queue, review gate y recuperación. |
| [Ralphex](https://github.com/umputun/ralphex) | **S** | **9.8/10** | Extended Ralph Loop: implementación autónoma, validaciones, múltiples reviewers, revisión externa Codex y ciclos de corrección. |
| [Omnigent](https://github.com/omnigent-ai/omnigent) | **A** | **9.4/10** | Meta-harness para coordinar Claude Code, Codex y otros agentes bajo una capa común con colaboración y políticas. |
| [A Fable of Codexes](https://github.com/jvogan/a-fable-of-codexes) | **A** | **9.6/10** | Conductor Claude con flotas de workers Codex, campañas, waves, squads, cross-review y aprendizaje de preferencias. |
| [Tutti](https://github.com/nutthouse/tutti) | **A** | **9.0/10** | Orquestación multiagente orientada a SDLC, artefactos, gates y registro reproducible. |
| [OpenAI Symphony](https://github.com/openai/symphony) | **S** | **9.7/10** | Engineering preview oficial de OpenAI para convertir trabajo de proyecto en ejecuciones autónomas aisladas con proof-of-work. |
| [AgentsMesh](https://github.com/AgentsMesh/AgentsMesh) | **B** | **8.9/10** | Control plane para una flota distribuida de agentes en múltiples máquinas. |
| [Agent Teams AI](https://github.com/777genius/agent-teams-ai) | **B** | **8.6/10** | Equipos de agentes con Kanban, tareas, mensajería y revisión. |
| [Operator OSS](https://github.com/iishyfishyy/operator-oss) | **B** | **8.8/10** | Cockpit local para múltiples sesiones Claude/Codex con aislamiento por worktree. |
| [Superset](https://github.com/superset-sh/superset) | **B** | **8.7/10** | IDE agentic para operar muchos workspaces/agentes en paralelo. |
| [Genesis](https://github.com/AmRitJain0442/Genesis) | **A** | **9.3/10** | Orquestador terminal orientado a Windows: Claude planifica/revisa y Codex ejecuta workers con worktrees y estado durable. |
| [Smithers](https://github.com/smithersai/smithers) | **S** | **9.8/10** | Framework de workflows de agentes con estado durable, observabilidad y time travel: rewind, fork y replay. |
| [Buildplane](https://github.com/SollanSystems/buildplane) | **A** | **9.5/10** | Diseño trust-first de control plane donde scheduler, estado, policy y verificación pertenecen al kernel y los modelos son workers acotados. |
| [Joshua Agent](https://github.com/jorgevazquez-vagojo/joshua-agent) | **A** | **9.5/10** | Control plane security-first con Claude/Codex, worktrees, políticas, evaluaciones, shadow comparisons, memoria y leases. |
| [Crewplane](https://github.com/crewplaneai/crewplane) | **B** | **8.5/10** | Control plane provider-neutral basado en workflows Markdown, blackboard state y resume/skip. |
| [VirtusLab Orca](https://github.com/VirtusLab/orca) | **S** | **9.9/10** | Workflows de desarrollo deterministas escritos en código: los agentes hacen lo cognitivo, el workflow obliga al resto. |
| [OpenView](https://github.com/iii-experimental/openview) | **B** | **8.8/10** | Control plane para agentes CLI reales con worktrees, approvals y event stream. |
| [Drover](https://github.com/cloud-shuttle/drover) | **B** | **8.8/10** | Coordinación de proyectos con tareas paralelas/dependencias y énfasis en progreso durable. |
| [Shipwright](https://github.com/sethdford/shipwright) | **B** | **8.6/10** | Delivery autónomo con pipelines, fleet operations, perfiles y métricas DORA. |
| [Agent Hive](https://github.com/tctinh/agent-hive) | **B** | **8.6/10** | Plan/approve/execute con workers aislados en worktrees y reportes persistentes. |
| [Podiom](https://github.com/Podiom/Podiom) | **B** | **8.5/10** | Workspace local para agentes Claude/Codex con identidad durable, sesiones, proyectos, tareas y scheduler. |
| [LoopTroop](https://github.com/looptroop-ai/LoopTroop) | **B** | **8.7/10** | Orquestador local con council de planificación, Beads/worktrees y retries estilo Ralph con contexto fresco. |
| [sd0x-dev-flow](https://github.com/sd0xdev/sd0x-dev-flow) | **B** | **8.4/10** | Harness layer para Claude Code con quality gates, skills, Codex brainstorming y disciplina de desarrollo. |
| [Agentic Control Stack](https://github.com/sd0xdev/agentic-control-stack) | **C** | **7.8/10** | Arquitectura educativa basada en control theory/MAPE-K aplicada a agentes. |

## Paperclip

**Repositorio:** https://github.com/paperclipai/paperclip  
**Tier:** B — **Potencial para Gnosis:** 8.9/10

**Qué es / para qué sirve.** Sistema operativo para organizaciones de agentes: objetivos, organigramas, presupuestos, gobernanza, proyectos y panel de control.

**Cómo lo usaríamos en Gnosis.** Referencia para la futura capa de misión, gobierno y UI de Gnosis; no lo usaría como kernel técnico principal.

**Fortalezas que nos interesan.** Modelo organizativo muy completo; proyectos/objetivos; gobierno; costes; experiencia visual de 'empresa de agentes'.

**Limitaciones / precauciones.** Su foco es la organización de agentes, no los contratos deterministas, proof packets o la semántica fina del lifecycle de código que Gnosis necesita.

## AWS CLI Agent Orchestrator (CAO)

**Repositorio:** https://github.com/awslabs/cli-agent-orchestrator  
**Tier:** B — **Potencial para Gnosis:** 8.7/10

**Qué es / para qué sirve.** Orquestador supervisor-worker para múltiples agentes CLI, incluidos Claude Code y Codex.

**Cómo lo usaríamos en Gnosis.** Benchmark y referencia para supervisión, sesiones y coordinación de varios CLI; especialmente útil para estudiar patrones de supervisor/workers.

**Fortalezas que nos interesan.** Multi-CLI real; tmux; supervisor; MCP; ejecución paralela; proyecto de AWS Labs.

**Limitaciones / precauciones.** El enfoque tmux/terminal y algunos supuestos Unix lo hacen menos ideal como base nativa de Gnosis en Windows.

## Agent Orchestrator

**Repositorio:** https://github.com/Untrivial-ai/agent-orchestrator  
**Tier:** A — **Potencial para Gnosis:** 9.3/10

**Qué es / para qué sirve.** Meta-harness/IDE para gestionar muchas sesiones de agentes en paralelo mediante worktrees, branches, PR, CI y review.

**Cómo lo usaríamos en Gnosis.** Referencia principal para el lifecycle issue→worker→worktree→PR→CI→review→merge y para la UX operativa.

**Fortalezas que nos interesan.** Amplia compatibilidad de agentes; worktrees; automatización de PR/review/CI; interfaz; enfoque de ingeniería real.

**Limitaciones / precauciones.** Es un sistema grande y opinado; no queremos acoplar el kernel de Gnosis a su modelo interno. Han existido issues Windows/ConPTY y propuestas abiertas de semantic merge.

## MetaSwarm

**Repositorio:** https://github.com/dsifry/metaswarm  
**Tier:** B — **Potencial para Gnosis:** 8.9/10

**Qué es / para qué sirve.** Lifecycle multiagente orientado a especificación, TDD, implementación, revisión adversarial y entrega.

**Cómo lo usaríamos en Gnosis.** Cantera de roles especializados, fases de revisión y metodología; útil para comparar contra Superpowers/Hoyeon.

**Fortalezas que nos interesan.** Muchos roles con responsabilidades separadas; spec-driven; TDD; cross-model review.

**Limitaciones / precauciones.** Puede resultar excesivamente ceremonial para tareas pequeñas; Gnosis debe hacer adaptativa la profundidad del proceso.

## Codex Orchestrator

**Repositorio:** https://github.com/kingbootoshi/codex-orchestrator  
**Tier:** B — **Potencial para Gnosis:** 8.1/10

**Qué es / para qué sirve.** Permite que Claude Code lance, supervise y dé instrucciones a workers Codex en paralelo.

**Cómo lo usaríamos en Gnosis.** Referencia específica para delegación Claude→Codex, manejo de sesiones y seguimiento de workers.

**Fortalezas que nos interesan.** Concepto simple y muy alineado con interacción Claude/Codex; paralelismo y seguimiento.

**Limitaciones / precauciones.** Más estrecho que Gnosis y muy centrado en una dirección de delegación.

## Claudexor

**Repositorio:** https://github.com/razzant/claudexor  
**Tier:** A — **Potencial para Gnosis:** 9.4/10

**Qué es / para qué sirve.** Control plane local-first sobre Claude Code, Codex CLI y otros harnesses, con interfaz tipada, Best-of-N y revisión cruzada.

**Cómo lo usaríamos en Gnosis.** Investigar a fondo su abstracción de runners, routing por capacidades, Best-of-N y gestión de cuotas/cuentas.

**Fortalezas que nos interesan.** Muy alineado con suscripciones/CLI; cross-family review; roles; mejor-de-N; control local.

**Limitaciones / precauciones.** Hay que validar cuidadosamente compatibilidad actual en Windows/WSL y no copiar mecanismos de autenticación que entren en conflicto con políticas de proveedores.

## Ouroboros

**Repositorio:** https://github.com/razzant/ouroboros  
**Tier:** C — **Potencial para Gnosis:** 7.5/10

**Qué es / para qué sirve.** Agente persistente/autoevolutivo con memoria, identidad durable, backlog y capacidad de modificar su propia implementación.

**Cómo lo usaríamos en Gnosis.** Referencia de investigación para self-review, memoria persistente y evolución; no base para V1.

**Fortalezas que nos interesan.** Explora auto-mejora, identidad, background work y versionado.

**Limitaciones / precauciones.** La autorreprogramación autónoma contradice el enfoque conservador de Gnosis: toda mejora debe evaluarse offline antes de promoción.

## Ruflo

**Repositorio:** https://github.com/ruvnet/ruflo  
**Tier:** B — **Potencial para Gnosis:** 8.6/10

**Qué es / para qué sirve.** Meta-harness de gran escala con swarms, numerosos agentes especializados, memoria y coordinación distribuida.

**Cómo lo usaríamos en Gnosis.** Estudiar topologías de swarm, coordinación y futuras extensiones distribuidas; no para V1.

**Fortalezas que nos interesan.** Gran amplitud funcional; swarms; memoria; seguridad; coordinación federada.

**Limitaciones / precauciones.** Complejidad alta y superficie de configuración enorme; riesgo de sobreingeniería para la primera versión.

## Kodo

**Repositorio:** https://github.com/ikamensh/kodo  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Orquestador autónomo que dirige agentes de programación y separa implementación de testing/review.

**Cómo lo usaríamos en Gnosis.** Comparar su ciclo planner/coder/tester/reviewer y su enfoque de ejecución desatendida.

**Fortalezas que nos interesan.** Separación de roles; autonomía; foco en verificadores independientes.

**Limitaciones / precauciones.** Algunas configuraciones dependen de APIs/modelos externos; Gnosis prioriza Claude/Codex CLI por suscripción.

## Bernstein

**Repositorio:** https://github.com/sipyourdrink-ltd/bernstein  
**Tier:** S — **Potencial para Gnosis:** 9.9/10

**Qué es / para qué sirve.** Orquestador determinista para agentes CLI con scheduler fuera del LLM, worktrees, quality gates, journal, replay y auditoría.

**Cómo lo usaríamos en Gnosis.** Una de las referencias más importantes para diseñar el kernel de Gnosis: scheduler, event journal, gates, lineage y replay.

**Fortalezas que nos interesan.** Determinismo; amplia compatibilidad CLI; auditabilidad; ejecución air-gapped; separación fuerte entre IA y coordinación.

**Limitaciones / precauciones.** No debemos copiar toda su implementación sin necesidad; interesa sobre todo su modelo de autoridad y evidencia.

## OMK (Open Multi-Agent Kit)

**Repositorio:** https://github.com/dmae97/omk  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Control plane provider-neutral con DAGs, lanes, evidencia, replay y recuperación.

**Cómo lo usaríamos en Gnosis.** Referencia para evidence gates, workflows DAG y separación de artefactos verificables.

**Fortalezas que nos interesan.** Evidence-driven; provider neutral; recuperación; reproducibilidad.

**Limitaciones / precauciones.** Solapamiento considerable con Bernstein/Smithers/Cezar; posiblemente cantera más que dependencia.

## Maestro

**Repositorio:** https://github.com/RunMaestro/Maestro  
**Tier:** B — **Potencial para Gnosis:** 8.5/10

**Qué es / para qué sirve.** Command center de escritorio para múltiples agentes, grupos, playbooks y worktrees.

**Cómo lo usaríamos en Gnosis.** Inspiración para la futura Control Room y colaboración multiagente.

**Fortalezas que nos interesan.** Interfaz visual; sesiones; playbooks; varios runtimes.

**Limitaciones / precauciones.** La UI no debe condicionar la arquitectura del kernel; fase posterior.

## Cezar

**Repositorio:** https://github.com/open-mercato/cezar  
**Tier:** S — **Potencial para Gnosis:** 10/10

**Qué es / para qué sirve.** Orquestador local de agentes de programación con workflows multi-runner, worktrees aislados, queue, review gate y recuperación.

**Cómo lo usaríamos en Gnosis.** Principal candidato para usar/testear como andamio de construcción de Gnosis. Estudiar runners por paso, workflow engine, rate-limit recovery y cockpit.

**Fortalezas que nos interesan.** Claude/Codex/OpenCode/pi; cada paso puede usar un runner diferente; CLIs autenticados localmente; worktrees; variantes; review gate.

**Limitaciones / precauciones.** No convertir Gnosis en un fork de Cezar: debemos conservar nuestro propio state machine y contratos.

## Ralphex

**Repositorio:** https://github.com/umputun/ralphex  
**Tier:** S — **Potencial para Gnosis:** 9.8/10

**Qué es / para qué sirve.** Extended Ralph Loop: implementación autónoma, validaciones, múltiples reviewers, revisión externa Codex y ciclos de corrección.

**Cómo lo usaríamos en Gnosis.** Referencia principal para el loop Claude→verificación→Codex→corrección y para circuit breakers/stalemate.

**Fortalezas que nos interesan.** Flujo muy cercano a la idea original de Gnosis; revisores especializados; iteración hasta convergencia.

**Limitaciones / precauciones.** Hay que aprender también de sus fallos reales: límites de uso/errores de infraestructura no deben convertirse en loops de rework.

## Omnigent

**Repositorio:** https://github.com/omnigent-ai/omnigent  
**Tier:** A — **Potencial para Gnosis:** 9.4/10

**Qué es / para qué sirve.** Meta-harness para coordinar Claude Code, Codex y otros agentes bajo una capa común con colaboración y políticas.

**Cómo lo usaríamos en Gnosis.** Estudiar abstracción multi-harness, revisión por otro proveedor y patterns como Polly/Debby.

**Fortalezas que nos interesan.** Heterogeneidad de runtimes; cross-provider review; sandboxes/policies; demos de conductor y debate.

**Limitaciones / precauciones.** Más plataforma general que kernel determinista; seleccionar mecanismos concretos.

## A Fable of Codexes

**Repositorio:** https://github.com/jvogan/a-fable-of-codexes  
**Tier:** A — **Potencial para Gnosis:** 9.6/10

**Qué es / para qué sirve.** Conductor Claude con flotas de workers Codex, campañas, waves, squads, cross-review y aprendizaje de preferencias.

**Cómo lo usaríamos en Gnosis.** Estudiar campañas/waves/squads, worker reports, bake-offs y memoria de ejecución.

**Fortalezas que nos interesan.** Muy buen diseño de flota; cross-model review; worktrees; campañas persistentes.

**Limitaciones / precauciones.** Su jerarquía Claude→Codex es más específica que el router agnóstico que queremos.

## Tutti

**Repositorio:** https://github.com/nutthouse/tutti  
**Tier:** A — **Potencial para Gnosis:** 9.0/10

**Qué es / para qué sirve.** Orquestación multiagente orientada a SDLC, artefactos, gates y registro reproducible.

**Cómo lo usaríamos en Gnosis.** Referencia para artefactos tipados, gates y lifecycle de ingeniería.

**Fortalezas que nos interesan.** Visión disciplinada de SDLC; reproducibilidad; roles y gates.

**Limitaciones / precauciones.** Solapa con AWF/Bernstein; probablemente inspiración, no core dependency.

## OpenAI Symphony

**Repositorio:** https://github.com/openai/symphony  
**Tier:** S — **Potencial para Gnosis:** 9.7/10

**Qué es / para qué sirve.** Engineering preview oficial de OpenAI para convertir trabajo de proyecto en ejecuciones autónomas aisladas con proof-of-work.

**Cómo lo usaríamos en Gnosis.** Referencia filosófica y técnica para 'gestionar trabajo, no agentes', aislamiento por tarea y evidencia antes de aterrizar cambios.

**Fortalezas que nos interesan.** Origen oficial OpenAI; proof-of-work; long-running work; integración con workflows de ingeniería.

**Limitaciones / precauciones.** Engineering preview, no necesariamente base estable para Gnosis V1.

## AgentsMesh

**Repositorio:** https://github.com/AgentsMesh/AgentsMesh  
**Tier:** B — **Potencial para Gnosis:** 8.9/10

**Qué es / para qué sirve.** Control plane para una flota distribuida de agentes en múltiples máquinas.

**Cómo lo usaríamos en Gnosis.** Referencia V3+ para escalar Gnosis de un PC a una granja distribuida.

**Fortalezas que nos interesan.** Pods/runners; control de flota; aislamiento; coordinación remota.

**Limitaciones / precauciones.** Demasiado para V1 local.

## Agent Teams AI

**Repositorio:** https://github.com/777genius/agent-teams-ai  
**Tier:** B — **Potencial para Gnosis:** 8.6/10

**Qué es / para qué sirve.** Equipos de agentes con Kanban, tareas, mensajería y revisión.

**Cómo lo usaríamos en Gnosis.** Inspiración para la futura organización/UX de equipos.

**Fortalezas que nos interesan.** Visual; colaboración; roles/equipos; varios runtimes.

**Limitaciones / precauciones.** No sustituye las garantías deterministas de Gnosis.

## Operator OSS

**Repositorio:** https://github.com/iishyfishyy/operator-oss  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Cockpit local para múltiples sesiones Claude/Codex con aislamiento por worktree.

**Cómo lo usaríamos en Gnosis.** Benchmark de UX, sesiones y flujos locales basados en suscripciones.

**Fortalezas que nos interesan.** Local-first; Claude/Codex; worktrees; buena experiencia operativa.

**Limitaciones / precauciones.** Más cockpit que kernel.

## Superset

**Repositorio:** https://github.com/superset-sh/superset  
**Tier:** B — **Potencial para Gnosis:** 8.7/10

**Qué es / para qué sirve.** IDE agentic para operar muchos workspaces/agentes en paralelo.

**Cómo lo usaríamos en Gnosis.** Inspiración para interfaz, diff review y gestión de muchos workers.

**Fortalezas que nos interesan.** Escala visual; workspaces; BYO agent/subscription.

**Limitaciones / precauciones.** No priorizar UI en V1.

## Genesis

**Repositorio:** https://github.com/AmRitJain0442/Genesis  
**Tier:** A — **Potencial para Gnosis:** 9.3/10

**Qué es / para qué sirve.** Orquestador terminal orientado a Windows: Claude planifica/revisa y Codex ejecuta workers con worktrees y estado durable.

**Cómo lo usaríamos en Gnosis.** Testear por ser especialmente relevante al entorno Windows/WSL de Gnosis y estudiar su estado SQLite, acceptance gates y manejo de sesiones OAuth.

**Fortalezas que nos interesan.** Windows-first; Claude+Codex; worktrees; estado durable; acceptance gates; resume/retry.

**Limitaciones / precauciones.** Más pequeño/madurez menor que Cezar; revisar seguridad y supuestos de autenticación antes de reutilizar código.

## Smithers

**Repositorio:** https://github.com/smithersai/smithers  
**Tier:** S — **Potencial para Gnosis:** 9.8/10

**Qué es / para qué sirve.** Framework de workflows de agentes con estado durable, observabilidad y time travel: rewind, fork y replay.

**Cómo lo usaríamos en Gnosis.** Referencia principal para durable workflows, checkpoints, rewind/fork y debugging temporal.

**Fortalezas que nos interesan.** Time travel real; resume tras crash; workflows multi-provider; observabilidad.

**Limitaciones / precauciones.** Determinar si usar ideas o dependencia; el kernel de Gnosis debe mantener control de sus propios contratos.

## Buildplane

**Repositorio:** https://github.com/SollanSystems/buildplane  
**Tier:** A — **Potencial para Gnosis:** 9.5/10

**Qué es / para qué sirve.** Diseño trust-first de control plane donde scheduler, estado, policy y verificación pertenecen al kernel y los modelos son workers acotados.

**Cómo lo usaríamos en Gnosis.** Referencia conceptual de primer nivel para Trust Plane, event tape y autoridad del kernel.

**Fortalezas que nos interesan.** Coincide con la filosofía central de Gnosis; event ledger; workers acotados; fail-closed.

**Limitaciones / precauciones.** Priorizar patrones/contratos sobre copiar una plataforma completa.

## Joshua Agent

**Repositorio:** https://github.com/jorgevazquez-vagojo/joshua-agent  
**Tier:** A — **Potencial para Gnosis:** 9.5/10

**Qué es / para qué sirve.** Control plane security-first con Claude/Codex, worktrees, políticas, evaluaciones, shadow comparisons, memoria y leases.

**Cómo lo usaríamos en Gnosis.** Estudiar fenced leases, reviewer read-only, shadow mode, evaluaciones y least privilege.

**Fortalezas que nos interesan.** Muy buena combinación seguridad+durabilidad+evaluación; roles de mínimo privilegio.

**Limitaciones / precauciones.** Validar madurez/estabilidad; usar como cantera de mecanismos.

## Crewplane

**Repositorio:** https://github.com/crewplaneai/crewplane  
**Tier:** B — **Potencial para Gnosis:** 8.5/10

**Qué es / para qué sirve.** Control plane provider-neutral basado en workflows Markdown, blackboard state y resume/skip.

**Cómo lo usaríamos en Gnosis.** Referencia para workflows revisables en disco y estado compartido legible.

**Fortalezas que nos interesan.** Simple; provider-neutral; reanudable; workflow como artefacto.

**Limitaciones / precauciones.** Menos garantías profundas que Bernstein/Smithers.

## VirtusLab Orca

**Repositorio:** https://github.com/VirtusLab/orca  
**Tier:** S — **Potencial para Gnosis:** 9.9/10

**Qué es / para qué sirve.** Workflows de desarrollo deterministas escritos en código: los agentes hacen lo cognitivo, el workflow obliga al resto.

**Cómo lo usaríamos en Gnosis.** Uno de los candidatos prioritarios para estudiar/testear durante la construcción de Gnosis.

**Fortalezas que nos interesan.** Workflow-as-code; resume por commits; roles planning/coding/review; evita gastar LLM en tareas deterministas.

**Limitaciones / precauciones.** Tecnología/DSL propios; debemos extraer el principio y evaluar si conviene usarlo directamente.

## OpenView

**Repositorio:** https://github.com/iii-experimental/openview  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Control plane para agentes CLI reales con worktrees, approvals y event stream.

**Cómo lo usaríamos en Gnosis.** Inspiración para Control Room, streaming de eventos y approvals.

**Fortalezas que nos interesan.** Visibilidad operativa; agentes reales; aislamiento; eventos.

**Limitaciones / precauciones.** Más capa de control/UX que núcleo.

## Drover

**Repositorio:** https://github.com/cloud-shuttle/drover  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Coordinación de proyectos con tareas paralelas/dependencias y énfasis en progreso durable.

**Cómo lo usaríamos en Gnosis.** Referencia adicional para recuperación y coordinación task-centric.

**Fortalezas que nos interesan.** Task durability; paralelismo; progreso persistente.

**Limitaciones / precauciones.** Solapa con Smithers/Beads/AWF.

## Shipwright

**Repositorio:** https://github.com/sethdford/shipwright  
**Tier:** B — **Potencial para Gnosis:** 8.6/10

**Qué es / para qué sirve.** Delivery autónomo con pipelines, fleet operations, perfiles y métricas DORA.

**Cómo lo usaríamos en Gnosis.** Referencia V3 para Delivery Profiles, fleet ops, rollback y métricas.

**Fortalezas que nos interesan.** Amplía coding→delivery; perfiles; DORA; operación de flota.

**Limitaciones / precauciones.** No necesario para núcleo V1.

## Agent Hive

**Repositorio:** https://github.com/tctinh/agent-hive  
**Tier:** B — **Potencial para Gnosis:** 8.6/10

**Qué es / para qué sirve.** Plan/approve/execute con workers aislados en worktrees y reportes persistentes.

**Cómo lo usaríamos en Gnosis.** Referencia para work cells, artefactos por tarea y revisión antes de sellar.

**Fortalezas que nos interesan.** Aislamiento; persistencia en repo; revisión; plan aprobado.

**Limitaciones / precauciones.** Solapamiento con AWF/Agent Orchestrator.

## Podiom

**Repositorio:** https://github.com/Podiom/Podiom  
**Tier:** B — **Potencial para Gnosis:** 8.5/10

**Qué es / para qué sirve.** Workspace local para agentes Claude/Codex con identidad durable, sesiones, proyectos, tareas y scheduler.

**Cómo lo usaríamos en Gnosis.** Estudiar identidad durable y UX de sesiones/proyectos.

**Fortalezas que nos interesan.** Local-first; usa logins CLI; durable agents; scheduler.

**Limitaciones / precauciones.** No tan profundo en verificación/policies como Gnosis.

## LoopTroop

**Repositorio:** https://github.com/looptroop-ai/LoopTroop  
**Tier:** B — **Potencial para Gnosis:** 8.7/10

**Qué es / para qué sirve.** Orquestador local con council de planificación, Beads/worktrees y retries estilo Ralph con contexto fresco.

**Cómo lo usaríamos en Gnosis.** Comparar planning council, fresh-context retries y gestión Beads.

**Fortalezas que nos interesan.** Integra varias ideas que nos interesan; local; GUI.

**Limitaciones / precauciones.** Evaluar si la complejidad del council aporta valor real frente a protocolos adaptativos.

## sd0x-dev-flow

**Repositorio:** https://github.com/sd0xdev/sd0x-dev-flow  
**Tier:** B — **Potencial para Gnosis:** 8.4/10

**Qué es / para qué sirve.** Harness layer para Claude Code con quality gates, skills, Codex brainstorming y disciplina de desarrollo.

**Cómo lo usaríamos en Gnosis.** Cantera de quality gates, skills y prácticas de harness engineering.

**Fortalezas que nos interesan.** Práctico; orientado a workflow real; integra revisiones/herramientas.

**Limitaciones / precauciones.** Muy ligado a un entorno/metodología específica.

## Agentic Control Stack

**Repositorio:** https://github.com/sd0xdev/agentic-control-stack  
**Tier:** C — **Potencial para Gnosis:** 7.8/10

**Qué es / para qué sirve.** Arquitectura educativa basada en control theory/MAPE-K aplicada a agentes.

**Cómo lo usaríamos en Gnosis.** Referencia conceptual para feedback loops, observación, adaptación y control.

**Fortalezas que nos interesan.** Buen vocabulario de control y feedback.

**Limitaciones / precauciones.** Más conceptual/educativo que infraestructura lista para usar.

# B. Especificación, planificación y metodología
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [GitHub Spec Kit](https://github.com/github/spec-kit) | **S** | **9.8/10** | Toolkit de Spec-Driven Development: definir qué construir y convertirlo en planificación/implementación. |
| [Superpowers](https://github.com/obra/superpowers) | **S** | **9.7/10** | Framework/metodología de skills para desarrollo agentic disciplinado, planificación, TDD, revisión y subagentes. |
| [Hoyeon](https://github.com/team-attention/hoyeon) | **A** | **9.5/10** | Harness requirements-first con StepBack, verificadores, gate keeper, risk analyst y planificación de verificación. |
| [Beads](https://github.com/gastownhall/beads) | **S** | **9.8/10** | Task/issue graph persistente y dependency-aware pensado para agentes. |
| [Gas Town](https://github.com/gastownhall/gastown) | **A** | **9.4/10** | Workspace/coordination system para operar muchos agentes usando estado persistente, mailboxes y Beads. |
| [Software Build Assurance Kit](https://github.com/kknipe2k/Software-Build-Assurance-Kit) | **B** | **8.6/10** | Kit de aseguramiento de builds para agentes: especificación, aprobación, testing, review y evidencia. |

## GitHub Spec Kit

**Repositorio:** https://github.com/github/spec-kit  
**Tier:** S — **Potencial para Gnosis:** 9.8/10

**Qué es / para qué sirve.** Toolkit de Spec-Driven Development: definir qué construir y convertirlo en planificación/implementación.

**Cómo lo usaríamos en Gnosis.** Referencia principal de la capa Specification Plane de Gnosis.

**Fortalezas que nos interesan.** Spec-first; proyecto de GitHub; metodología clara; reduce desarrollo prematuro.

**Limitaciones / precauciones.** Gnosis necesitará añadir risk, evidence y task contracts propios.

## Superpowers

**Repositorio:** https://github.com/obra/superpowers  
**Tier:** S — **Potencial para Gnosis:** 9.7/10

**Qué es / para qué sirve.** Framework/metodología de skills para desarrollo agentic disciplinado, planificación, TDD, revisión y subagentes.

**Cómo lo usaríamos en Gnosis.** Fuente principal de metodología y procedural skills; comparar cada skill mediante nuestro Skill Lab.

**Fortalezas que nos interesan.** Workflow disciplinado; TDD; revisión; skills reutilizables.

**Limitaciones / precauciones.** No instalar ciegamente todas las skills: hay que evaluarlas contra baseline.

## Hoyeon

**Repositorio:** https://github.com/team-attention/hoyeon  
**Tier:** A — **Potencial para Gnosis:** 9.5/10

**Qué es / para qué sirve.** Harness requirements-first con StepBack, verificadores, gate keeper, risk analyst y planificación de verificación.

**Cómo lo usaríamos en Gnosis.** Copiar conceptualmente StepBack/blind-spot scan y requisitos→plan→verificación.

**Fortalezas que nos interesan.** Evita scope drift; múltiples perspectivas; requirements-first.

**Limitaciones / precauciones.** No usar todos los roles siempre; Gnosis hará profundidad adaptativa.

## Beads

**Repositorio:** https://github.com/gastownhall/beads  
**Tier:** S — **Potencial para Gnosis:** 9.8/10

**Qué es / para qué sirve.** Task/issue graph persistente y dependency-aware pensado para agentes.

**Cómo lo usaríamos en Gnosis.** Referencia principal para memoria operacional: DAG, dependencias, ready/claim/close.

**Fortalezas que nos interesan.** Trabajo persistente separado de la conversación; graph de dependencias; agent-friendly.

**Limitaciones / precauciones.** Decidir si integrarlo o reimplementar un subconjunto sobre SQLite.

## Gas Town

**Repositorio:** https://github.com/gastownhall/gastown  
**Tier:** A — **Potencial para Gnosis:** 9.4/10

**Qué es / para qué sirve.** Workspace/coordination system para operar muchos agentes usando estado persistente, mailboxes y Beads.

**Cómo lo usaríamos en Gnosis.** Referencia para fleet coordination, handoffs, identities y merge queue.

**Fortalezas que nos interesan.** Escala; task ledger; handoffs; agentes desechables con trabajo durable.

**Limitaciones / precauciones.** Demasiado complejo para V1; estudiar patrones.

## Software Build Assurance Kit

**Repositorio:** https://github.com/kknipe2k/Software-Build-Assurance-Kit  
**Tier:** B — **Potencial para Gnosis:** 8.6/10

**Qué es / para qué sirve.** Kit de aseguramiento de builds para agentes: especificación, aprobación, testing, review y evidencia.

**Cómo lo usaríamos en Gnosis.** Cantera para quality gates y disciplina de proof.

**Fortalezas que nos interesan.** Foco en evidencia y assurance.

**Limitaciones / precauciones.** Solapa con nuestra Verification Plane; evaluar mecanismos concretos.

# C. Git, worktrees, paralelismo y conflictos
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [Agent Workspace Fabric (AWF)](https://github.com/dimileeh/agent-workspace-fabric) | **S** | **10/10** | Execution substrate industrial: tarea→worktree→contenedor→validación→commit→PR→CI/review→merge. |
| [Grit](https://github.com/rtk-ai/grit) | **S** | **9.7/10** | Coordinación de agentes con locking a nivel de símbolos/AST para prevenir conflictos antes de editar. |
| [Symlock](https://github.com/echoVic/symlock) | **A** | **9.3/10** | Bloqueo semántico a nivel de símbolos y prevención de conflictos entre agentes. |
| [parallel-cc](https://github.com/frankbria/parallel-cc) | **B** | **8.5/10** | Gestión paralela de Claude Code mediante worktrees y análisis de conflictos. |
| [Polywave Protocol](https://github.com/blackwell-systems/polywave-protocol) | **A** | **9.2/10** | Protocolo de coordinación paralela diseñado para minimizar conflictos mediante invariantes, estados y mensajes. |
| [Polywave](https://github.com/blackwell-systems/polywave) | **B** | **8.3/10** | Implementación orientada a Claude Code del protocolo Polywave. |
| [Polywave Go](https://github.com/blackwell-systems/polywave-go) | **B** | **8.1/10** | Motor/CLI en Go para Polywave. |

## Agent Workspace Fabric (AWF)

**Repositorio:** https://github.com/dimileeh/agent-workspace-fabric  
**Tier:** S — **Potencial para Gnosis:** 10/10

**Qué es / para qué sirve.** Execution substrate industrial: tarea→worktree→contenedor→validación→commit→PR→CI/review→merge.

**Cómo lo usaríamos en Gnosis.** Referencia principal para Git/Execution Plane y una de las arquitecturas a destripar primero.

**Fortalezas que nos interesan.** Lifecycle completo; aislamiento; profile validation; PR monitor; CI/review/base sync; preserva workspace fallido.

**Limitaciones / precauciones.** Debe integrarse conceptualmente con nuestro kernel sin delegarle toda la autoridad.

## Grit

**Repositorio:** https://github.com/rtk-ai/grit  
**Tier:** S — **Potencial para Gnosis:** 9.7/10

**Qué es / para qué sirve.** Coordinación de agentes con locking a nivel de símbolos/AST para prevenir conflictos antes de editar.

**Cómo lo usaríamos en Gnosis.** Referencia principal para Symbol Ownership y claims de funciones/clases.

**Fortalezas que nos interesan.** Permite paralelismo dentro del mismo archivo; AST-aware; claim→worktree→merge.

**Limitaciones / precauciones.** Compatibilidad de lenguajes/AST debe evaluarse; necesitamos fallback conservador.

## Symlock

**Repositorio:** https://github.com/echoVic/symlock  
**Tier:** A — **Potencial para Gnosis:** 9.3/10

**Qué es / para qué sirve.** Bloqueo semántico a nivel de símbolos y prevención de conflictos entre agentes.

**Cómo lo usaríamos en Gnosis.** Comparar con Grit para diseñar la abstracción de symbol leases/locks de Gnosis.

**Fortalezas que nos interesan.** Símbolos; claim/release; enfoque conservador de merge.

**Limitaciones / precauciones.** No asumir que semantic merge es completamente resoluble; post-merge verification seguirá siendo obligatoria.

## parallel-cc

**Repositorio:** https://github.com/frankbria/parallel-cc  
**Tier:** B — **Potencial para Gnosis:** 8.5/10

**Qué es / para qué sirve.** Gestión paralela de Claude Code mediante worktrees y análisis de conflictos.

**Cómo lo usaríamos en Gnosis.** Referencia secundaria para paralelismo, worktrees y análisis AST/conflict scoring.

**Fortalezas que nos interesan.** Práctico; worktree-centric; conflict analysis.

**Limitaciones / precauciones.** Más estrecho que la capa Git completa de Gnosis.

## Polywave Protocol

**Repositorio:** https://github.com/blackwell-systems/polywave-protocol  
**Tier:** A — **Potencial para Gnosis:** 9.2/10

**Qué es / para qué sirve.** Protocolo de coordinación paralela diseñado para minimizar conflictos mediante invariantes, estados y mensajes.

**Cómo lo usaríamos en Gnosis.** Estudiar como especificación de comunicación/ownership, no necesariamente como runtime.

**Fortalezas que nos interesan.** Implementation-agnostic; invariantes explícitas; coordinación por diseño.

**Limitaciones / precauciones.** Validar su madurez y cómo se comporta en repos grandes reales.

## Polywave

**Repositorio:** https://github.com/blackwell-systems/polywave  
**Tier:** B — **Potencial para Gnosis:** 8.3/10

**Qué es / para qué sirve.** Implementación orientada a Claude Code del protocolo Polywave.

**Cómo lo usaríamos en Gnosis.** Comparar el protocolo con una implementación real.

**Fortalezas que nos interesan.** Permite ver cómo aterriza el modelo teórico.

**Limitaciones / precauciones.** Menos central que el protocolo.

## Polywave Go

**Repositorio:** https://github.com/blackwell-systems/polywave-go  
**Tier:** B — **Potencial para Gnosis:** 8.1/10

**Qué es / para qué sirve.** Motor/CLI en Go para Polywave.

**Cómo lo usaríamos en Gnosis.** Referencia de implementación y CLI.

**Fortalezas que nos interesan.** Implementación separada del protocolo.

**Limitaciones / precauciones.** Sólo necesaria si Polywave demuestra valor en pruebas.

# D. Revisión adversarial, councils, debate y verificación cognitiva
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [Agent Arena](https://github.com/zhjai/agent-arena) | **S** | **9.8/10** | Deliberación evidence-first: propuestas independientes, claims, evidence, cross-critique, blind judge y preservación del desacuerdo. |
| [Senate](https://github.com/SebastianElvis/senate) | **A** | **9.2/10** | Protocolos de deliberación tipo parliament/court/committee/red-team con evaluaciones. |
| [LLM Council](https://github.com/sherifkozman/the-llm-council) | **B** | **8.8/10** | Framework de council con routing por rol/modo/proveedor. |
| [Agent Review Panel](https://github.com/wan-huiyan/agent-review-panel) | **B** | **8.7/10** | Panel de 4–6 revisores con posturas diferentes, debate y juez. |
| [OpenAI Codex Plugin for Claude Code](https://github.com/openai/codex-plugin-cc) | **A** | **9.3/10** | Plugin oficial para invocar Codex desde Claude Code, incluyendo review/delegation. |

## Agent Arena

**Repositorio:** https://github.com/zhjai/agent-arena  
**Tier:** S — **Potencial para Gnosis:** 9.8/10

**Qué es / para qué sirve.** Deliberación evidence-first: propuestas independientes, claims, evidence, cross-critique, blind judge y preservación del desacuerdo.

**Cómo lo usaríamos en Gnosis.** Referencia principal para el Deliberation Engine de tareas críticas.

**Fortalezas que nos interesan.** Independent-first; evidence-first; dissent preservation; reduce anchoring.

**Limitaciones / precauciones.** No usar en tareas triviales; debe estar sujeto a presupuesto y benchmarks.

## Senate

**Repositorio:** https://github.com/SebastianElvis/senate  
**Tier:** A — **Potencial para Gnosis:** 9.2/10

**Qué es / para qué sirve.** Protocolos de deliberación tipo parliament/court/committee/red-team con evaluaciones.

**Cómo lo usaríamos en Gnosis.** Cantera para Cognitive Protocol Registry y benchmarking de debates.

**Fortalezas que nos interesan.** Protocolos diferenciados; evals; court/parliament/consensus.

**Limitaciones / precauciones.** El consenso no será verdad; sólo una señal subordinada a evidencia.

## LLM Council

**Repositorio:** https://github.com/sherifkozman/the-llm-council  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Framework de council con routing por rol/modo/proveedor.

**Cómo lo usaríamos en Gnosis.** Referencia para router que elige no sólo modelo, sino rol y modo cognitivo.

**Fortalezas que nos interesan.** Roles/modes; providers plug-in; arquitectura expresiva.

**Limitaciones / precauciones.** Varios backends pueden ser API-centric; Gnosis prioriza CLI local.

## Agent Review Panel

**Repositorio:** https://github.com/wan-huiyan/agent-review-panel  
**Tier:** B — **Potencial para Gnosis:** 8.7/10

**Qué es / para qué sirve.** Panel de 4–6 revisores con posturas diferentes, debate y juez.

**Cómo lo usaríamos en Gnosis.** Inspiración para multi-stance reviews en componentes críticos.

**Fortalezas que nos interesan.** Diversidad de roles; adversarial review; juez.

**Limitaciones / precauciones.** Costoso; no usar número fijo de revisores en Gnosis.

## OpenAI Codex Plugin for Claude Code

**Repositorio:** https://github.com/openai/codex-plugin-cc  
**Tier:** A — **Potencial para Gnosis:** 9.3/10

**Qué es / para qué sirve.** Plugin oficial para invocar Codex desde Claude Code, incluyendo review/delegation.

**Cómo lo usaríamos en Gnosis.** Estudiar tanto su integración directa como sus issues de loops, usage limits y hooks.

**Fortalezas que nos interesan.** Oficial OpenAI; integración Claude↔Codex; Stop hooks/review.

**Limitaciones / precauciones.** Sus problemas reales muestran por qué Gnosis debe distinguir FAIL_CODE, RATE_LIMITED, INFRA y TIMEOUT.

# E. Routing, evaluación, skills y auto-mejora controlada
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [TwinRouterBench](https://github.com/CommonstackAI/TwinRouterBench) | **S** | **9.6/10** | Benchmark de routing de LLM a nivel de paso/decisión, incluyendo evaluación dinámica. |
| [UncommonRoute](https://github.com/CommonstackAI/UncommonRoute) | **B** | **8.4/10** | Router automático de modelos que intenta mantener calidad reduciendo coste. |
| [AgentFlow](https://github.com/lupantech/AgentFlow) | **A** | **9.1/10** | Optimización in-flow de sistemas agentic separando Planner, Executor, Verifier y Generator. |
| [Graph of Skills](https://github.com/davidliuk/graph-of-skills) | **A** | **9.1/10** | Recuperación estructurada de skills mediante grafo de dependencias/prerrequisitos. |
| [SkillFlow](https://github.com/ZhangZi-a/SkillFlow) | **A** | **9.3/10** | Benchmark/evolución de skills: extraer procedimientos reutilizables y medir su mejora en tareas futuras. |
| [Memento-Skills](https://github.com/Memento-Teams/Memento-Skills) | **B** | **8.6/10** | Sistema donde las skills son capacidades persistentes de primera clase. |
| [Awesome Agent Skills](https://github.com/VoltAgent/awesome-agent-skills) | **C** | **7.8/10** | Gran catálogo de skills para distintos agentes. |
| [plaited/agent-eval-harness](https://github.com/plaited/agent-eval-harness) | **B** | **8.5/10** | Harness de evaluación de agentes CLI con adapters, trajectories y métricas pass@k. |
| [OpenDataHub Agent Eval Harness](https://github.com/opendatahub-io/agent-eval-harness) | **B** | **8.7/10** | Evaluaciones declarativas, judges, A/B y optimización. |
| [linny006/agent-eval-harness](https://github.com/linny006/agent-eval-harness) | **C** | **7.9/10** | Benchmark de agentes sobre issues reales de GitHub. |
| [coding-agent-eval-harness](https://github.com/zackproser/coding-agent-eval-harness) | **B** | **8.3/10** | Evaluación sobre tareas históricas de Git en entornos aislados con graders ocultos y telemetría. |
| [WildClawBench](https://github.com/InternLM/WildClawBench) | **B** | **8.2/10** | Benchmark in-the-wild para agentes/harnesses. |
| [ProofAgent Harness](https://github.com/ProofAgent-ai/proofagent-harness) | **A** | **9.0/10** | Harness adversarial para evaluar comportamiento de agentes, tool use y resistencia a escenarios hostiles. |
| [AI Code Quality Framework](https://github.com/0xUXDesign/ai-code-quality-framework) | **B** | **8.5/10** | Framework de calidad para código generado por IA con Biome, Knip, Stryker, Lefthook y hooks. |
| [Test-Forge](https://github.com/manjeetsharma0796/Test-Forge) | **B** | **8.2/10** | Explora generación/evaluación de tests usando mutation testing. |
| [Canary](https://github.com/0xnyn/canary) | **B** | **8.7/10** | QA agentic que captura vídeo, screenshots, consola, red/HAR y Playwright traces. |

## TwinRouterBench

**Repositorio:** https://github.com/CommonstackAI/TwinRouterBench  
**Tier:** S — **Potencial para Gnosis:** 9.6/10

**Qué es / para qué sirve.** Benchmark de routing de LLM a nivel de paso/decisión, incluyendo evaluación dinámica.

**Cómo lo usaríamos en Gnosis.** Base metodológica para construir y evaluar el router de Gnosis.

**Fortalezas que nos interesan.** Routing evaluable; granularidad por paso; datasets/labels.

**Limitaciones / precauciones.** Sus modelos/costes no equivalen a nuestras suscripciones CLI; copiar metodología, no resultados.

## UncommonRoute

**Repositorio:** https://github.com/CommonstackAI/UncommonRoute  
**Tier:** B — **Potencial para Gnosis:** 8.4/10

**Qué es / para qué sirve.** Router automático de modelos que intenta mantener calidad reduciendo coste.

**Cómo lo usaríamos en Gnosis.** Referencia para comparar smart router vs always-strong baseline.

**Fortalezas que nos interesan.** Metodología de routing/coste; asociado a TwinRouterBench.

**Limitaciones / precauciones.** Más API-centric; métricas del proyecto no se extrapolan directamente a Gnosis.

## AgentFlow

**Repositorio:** https://github.com/lupantech/AgentFlow  
**Tier:** A — **Potencial para Gnosis:** 9.1/10

**Qué es / para qué sirve.** Optimización in-flow de sistemas agentic separando Planner, Executor, Verifier y Generator.

**Cómo lo usaríamos en Gnosis.** Referencia para Attribution Engine y evaluación modular de componentes cognitivos.

**Fortalezas que nos interesan.** Permite pensar qué componente falló en lugar de culpar genéricamente al modelo.

**Limitaciones / precauciones.** No necesitamos entrenar modelos en V1; extraer la separación y metodología.

## Graph of Skills

**Repositorio:** https://github.com/davidliuk/graph-of-skills  
**Tier:** A — **Potencial para Gnosis:** 9.1/10

**Qué es / para qué sirve.** Recuperación estructurada de skills mediante grafo de dependencias/prerrequisitos.

**Cómo lo usaríamos en Gnosis.** Referencia para Skill Router: suministrar sólo skills relevantes.

**Fortalezas que nos interesan.** Evita cargar cientos de skills; dependencias explícitas.

**Limitaciones / precauciones.** Debe combinarse con evaluación real de utilidad.

## SkillFlow

**Repositorio:** https://github.com/ZhangZi-a/SkillFlow  
**Tier:** A — **Potencial para Gnosis:** 9.3/10

**Qué es / para qué sirve.** Benchmark/evolución de skills: extraer procedimientos reutilizables y medir su mejora en tareas futuras.

**Cómo lo usaríamos en Gnosis.** Referencia principal para el Skill Laboratory de Gnosis.

**Fortalezas que nos interesan.** Skills como candidatos evaluables; evolución basada en tareas.

**Limitaciones / precauciones.** No auto-promocionar skills sin shadow/regression.

## Memento-Skills

**Repositorio:** https://github.com/Memento-Teams/Memento-Skills  
**Tier:** B — **Potencial para Gnosis:** 8.6/10

**Qué es / para qué sirve.** Sistema donde las skills son capacidades persistentes de primera clase.

**Cómo lo usaríamos en Gnosis.** Referencia para procedural memory y lifecycle de skills.

**Fortalezas que nos interesan.** Skills persistentes; composición/capacidades.

**Limitaciones / precauciones.** Solapa con SkillFlow/Graph of Skills.

## Awesome Agent Skills

**Repositorio:** https://github.com/VoltAgent/awesome-agent-skills  
**Tier:** C — **Potencial para Gnosis:** 7.8/10

**Qué es / para qué sirve.** Gran catálogo de skills para distintos agentes.

**Cómo lo usaríamos en Gnosis.** Discovery de candidatos, nunca instalación masiva.

**Fortalezas que nos interesan.** Cobertura enorme; ideas y ejemplos.

**Limitaciones / precauciones.** Cantidad no implica calidad; cada skill debe pasar benchmark.

## plaited/agent-eval-harness

**Repositorio:** https://github.com/plaited/agent-eval-harness  
**Tier:** B — **Potencial para Gnosis:** 8.5/10

**Qué es / para qué sirve.** Harness de evaluación de agentes CLI con adapters, trajectories y métricas pass@k.

**Cómo lo usaríamos en Gnosis.** Comparar con Catacomb y otros eval harnesses para diseñar AXEL/GNOSIS-BENCH.

**Fortalezas que nos interesan.** CLI eval; adapters; trayectorias.

**Limitaciones / precauciones.** No necesariamente orientado a nuestro lifecycle completo.

## OpenDataHub Agent Eval Harness

**Repositorio:** https://github.com/opendatahub-io/agent-eval-harness  
**Tier:** B — **Potencial para Gnosis:** 8.7/10

**Qué es / para qué sirve.** Evaluaciones declarativas, judges, A/B y optimización.

**Cómo lo usaríamos en Gnosis.** Referencia para eval.yaml, comparación A/B y experimentos reproducibles.

**Fortalezas que nos interesan.** Declarativo; jueces; A/B; trazabilidad.

**Limitaciones / precauciones.** Adaptar a agentes CLI y evidencia determinista.

## linny006/agent-eval-harness

**Repositorio:** https://github.com/linny006/agent-eval-harness  
**Tier:** C — **Potencial para Gnosis:** 7.9/10

**Qué es / para qué sirve.** Benchmark de agentes sobre issues reales de GitHub.

**Cómo lo usaríamos en Gnosis.** Fuente de ideas para datasets vivos.

**Fortalezas que nos interesan.** Tareas reales.

**Limitaciones / precauciones.** Menos central que nuestros benchmarks propios.

## coding-agent-eval-harness

**Repositorio:** https://github.com/zackproser/coding-agent-eval-harness  
**Tier:** B — **Potencial para Gnosis:** 8.3/10

**Qué es / para qué sirve.** Evaluación sobre tareas históricas de Git en entornos aislados con graders ocultos y telemetría.

**Cómo lo usaríamos en Gnosis.** Referencia para convertir historia Git en benchmark interno.

**Fortalezas que nos interesan.** Tareas históricas; aislamiento; graders; telemetría.

**Limitaciones / precauciones.** Integrar ideas en Gnosis-Bench, no necesariamente dependencia.

## WildClawBench

**Repositorio:** https://github.com/InternLM/WildClawBench  
**Tier:** B — **Potencial para Gnosis:** 8.2/10

**Qué es / para qué sirve.** Benchmark in-the-wild para agentes/harnesses.

**Cómo lo usaríamos en Gnosis.** Referencia externa complementaria; nuestro benchmark principal debe ser específico de nuestros repos.

**Fortalezas que nos interesan.** Tareas reales y variadas.

**Limitaciones / precauciones.** No representa necesariamente las cargas de Gnosis.

## ProofAgent Harness

**Repositorio:** https://github.com/ProofAgent-ai/proofagent-harness  
**Tier:** A — **Potencial para Gnosis:** 9.0/10

**Qué es / para qué sirve.** Harness adversarial para evaluar comportamiento de agentes, tool use y resistencia a escenarios hostiles.

**Cómo lo usaríamos en Gnosis.** Referencia para Agent Red Team Suite.

**Fortalezas que nos interesan.** Escenarios adversariales; gates; seguridad de comportamiento.

**Limitaciones / precauciones.** Usarlo como evaluación, no como runtime central.

## AI Code Quality Framework

**Repositorio:** https://github.com/0xUXDesign/ai-code-quality-framework  
**Tier:** B — **Potencial para Gnosis:** 8.5/10

**Qué es / para qué sirve.** Framework de calidad para código generado por IA con Biome, Knip, Stryker, Lefthook y hooks.

**Cómo lo usaríamos en Gnosis.** Cantera para quality gates y mutation testing.

**Fortalezas que nos interesan.** Herramientas deterministas; mutation; hooks; calidad.

**Limitaciones / precauciones.** Existe al menos un repositorio homónimo no relacionado/malicioso; usar únicamente 0xUXDesign/ai-code-quality-framework.

## Test-Forge

**Repositorio:** https://github.com/manjeetsharma0796/Test-Forge  
**Tier:** B — **Potencial para Gnosis:** 8.2/10

**Qué es / para qué sirve.** Explora generación/evaluación de tests usando mutation testing.

**Cómo lo usaríamos en Gnosis.** Referencia para medir si los tests generados por agentes detectan implementaciones rotas.

**Fortalezas que nos interesan.** Mutation-oriented; idea muy alineada con proof.

**Limitaciones / precauciones.** Proyecto más pequeño; usar principio y herramientas maduras del ecosistema para producción.

## Canary

**Repositorio:** https://github.com/0xnyn/canary  
**Tier:** B — **Potencial para Gnosis:** 8.7/10

**Qué es / para qué sirve.** QA agentic que captura vídeo, screenshots, consola, red/HAR y Playwright traces.

**Cómo lo usaríamos en Gnosis.** Futura capa de UI/E2E: descubrimiento por IA convertido en tests Playwright reproducibles.

**Fortalezas que nos interesan.** Convierte exploración AI en artefactos deterministas; evidencia rica.

**Limitaciones / precauciones.** Sólo relevante para proyectos con interfaz/web.

# F. Context engineering, code graph y blast radius
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [CodeGraph MCP](https://github.com/StarQuant/codegraph-mcp) | **A** | **9.5/10** | Índice local precomputado de símbolos, llamadas, dependencias y relaciones para agentes. |
| [Sverklo](https://github.com/sverklo/sverklo) | **S** | **9.7/10** | Memoria/inteligencia de repositorio con symbol graph, blast radius, review y decisiones ancladas a Git. |
| [Code Context Engine](https://github.com/elara-labs/code-context-engine) | **A** | **9.1/10** | Indexado local de repositorios para búsquedas agent-friendly con menor lectura/tokenización. |
| [context-mode](https://github.com/mksglu/context-mode) | **B** | **8.8/10** | Optimiza ventana de contexto, virtualiza outputs de herramientas y mantiene memoria de sesión. |
| [UltraCode (faxenoff)](https://github.com/faxenoff/ultracode) | **B** | **8.5/10** | MCP de búsqueda estructural/code graph para agentes. |
| [Sense](https://github.com/luuuc/sense) | **B** | **8.6/10** | MCP local para comprensión estructural: símbolos, relaciones, convenciones, blast radius y búsqueda semántica. |
| [code-review-graph](https://github.com/tirth8205/code-review-graph) | **B** | **8.4/10** | Code graph Tree-sitter orientado a review y contexto de blast radius. |
| [Graft](https://github.com/NanoNets/Graft) | **B** | **8.4/10** | Grafo persistente de contexto de código para agentes. |
| [Cartographer](https://github.com/kingbootoshi/cartographer) | **B** | **8.6/10** | Mapeo de repositorio con grafo/SQLite y briefs acotados para agentes. |
| [Wonk](https://github.com/etr/wonk) | **C** | **7.9/10** | Búsqueda code-aware y análisis de blast radius. |
| [roam-code](https://github.com/Cranot/roam-code) | **C** | **7.8/10** | Inteligencia local de codebase con arquitectura y blast radius. |

## CodeGraph MCP

**Repositorio:** https://github.com/StarQuant/codegraph-mcp  
**Tier:** A — **Potencial para Gnosis:** 9.5/10

**Qué es / para qué sirve.** Índice local precomputado de símbolos, llamadas, dependencias y relaciones para agentes.

**Cómo lo usaríamos en Gnosis.** Candidato a testear para el Context Plane; alimentar blast radius, context packs y symbol locks.

**Fortalezas que nos interesan.** Local; code graph; auto-sync; integración con Claude/Codex.

**Limitaciones / precauciones.** Benchmarks publicados por el proyecto deben validarse internamente.

## Sverklo

**Repositorio:** https://github.com/sverklo/sverklo  
**Tier:** S — **Potencial para Gnosis:** 9.7/10

**Qué es / para qué sirve.** Memoria/inteligencia de repositorio con symbol graph, blast radius, review y decisiones ancladas a Git.

**Cómo lo usaríamos en Gnosis.** Referencia principal para conocimiento de código versionado y análisis de impacto.

**Fortalezas que nos interesan.** Git-pinned decisions; symbol graph; blast radius; local-first.

**Limitaciones / precauciones.** Evaluar soporte de lenguajes y coste de indexado en proyectos grandes.

## Code Context Engine

**Repositorio:** https://github.com/elara-labs/code-context-engine  
**Tier:** A — **Potencial para Gnosis:** 9.1/10

**Qué es / para qué sirve.** Indexado local de repositorios para búsquedas agent-friendly con menor lectura/tokenización.

**Cómo lo usaríamos en Gnosis.** Benchmark contra CodeGraph/Sverklo para seleccionar Context Engine.

**Fortalezas que nos interesan.** Local; integra varios agentes; token-efficiency.

**Limitaciones / precauciones.** La cifra de ahorro que publica el proyecto es una afirmación propia; validar en Gnosis-Bench.

## context-mode

**Repositorio:** https://github.com/mksglu/context-mode  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Optimiza ventana de contexto, virtualiza outputs de herramientas y mantiene memoria de sesión.

**Cómo lo usaríamos en Gnosis.** Estudiar Tool Output Virtualization y compresión de contexto; sólo tras security review.

**Fortalezas que nos interesan.** Reduce context bloat; guarda outputs completos fuera del prompt; routing/hooks.

**Limitaciones / precauciones.** Se han reportado preocupaciones de seguridad/sandbox; no adoptarlo sin auditoría estricta.

## UltraCode (faxenoff)

**Repositorio:** https://github.com/faxenoff/ultracode  
**Tier:** B — **Potencial para Gnosis:** 8.5/10

**Qué es / para qué sirve.** MCP de búsqueda estructural/code graph para agentes.

**Cómo lo usaríamos en Gnosis.** Comparar precisión y soporte de lenguajes con Sverklo/CodeGraph.

**Fortalezas que nos interesan.** Structural search; graph; agent-oriented.

**Limitaciones / precauciones.** Existe otro proyecto homónimo; mantener el owner explícito.

## Sense

**Repositorio:** https://github.com/luuuc/sense  
**Tier:** B — **Potencial para Gnosis:** 8.6/10

**Qué es / para qué sirve.** MCP local para comprensión estructural: símbolos, relaciones, convenciones, blast radius y búsqueda semántica.

**Cómo lo usaríamos en Gnosis.** Benchmark alternativo para Context Compiler.

**Fortalezas que nos interesan.** Local; combinación structural+semantic.

**Limitaciones / precauciones.** Solapa con otras opciones; escoger una o componer APIs propias.

## code-review-graph

**Repositorio:** https://github.com/tirth8205/code-review-graph  
**Tier:** B — **Potencial para Gnosis:** 8.4/10

**Qué es / para qué sirve.** Code graph Tree-sitter orientado a review y contexto de blast radius.

**Cómo lo usaríamos en Gnosis.** Cantera para review-aware context selection.

**Fortalezas que nos interesan.** Tree-sitter; review-specific; token efficient.

**Limitaciones / precauciones.** Menor alcance que un Context Plane completo.

## Graft

**Repositorio:** https://github.com/NanoNets/Graft  
**Tier:** B — **Potencial para Gnosis:** 8.4/10

**Qué es / para qué sirve.** Grafo persistente de contexto de código para agentes.

**Cómo lo usaríamos en Gnosis.** Referencia de representación visible/consultable del code graph.

**Fortalezas que nos interesan.** Persistente; agent-friendly.

**Limitaciones / precauciones.** Comparar madurez y cobertura con Sverklo/CodeGraph.

## Cartographer

**Repositorio:** https://github.com/kingbootoshi/cartographer  
**Tier:** B — **Potencial para Gnosis:** 8.6/10

**Qué es / para qué sirve.** Mapeo de repositorio con grafo/SQLite y briefs acotados para agentes.

**Cómo lo usaríamos en Gnosis.** Hallazgo durante consolidación; evaluar como alternativa para Context Packs y evidence briefs.

**Fortalezas que nos interesan.** Bounded briefs; graph; SQLite; orientado a no inundar contexto.

**Limitaciones / precauciones.** No estaba en las primeras tandas; requiere evaluación comparativa.

## Wonk

**Repositorio:** https://github.com/etr/wonk  
**Tier:** C — **Potencial para Gnosis:** 7.9/10

**Qué es / para qué sirve.** Búsqueda code-aware y análisis de blast radius.

**Cómo lo usaríamos en Gnosis.** Alternativa secundaria para estudiar heurísticas de impacto.

**Fortalezas que nos interesan.** Structure-aware; impacto.

**Limitaciones / precauciones.** No aporta suficiente singularidad frente a Tier A.

## roam-code

**Repositorio:** https://github.com/Cranot/roam-code  
**Tier:** C — **Potencial para Gnosis:** 7.8/10

**Qué es / para qué sirve.** Inteligencia local de codebase con arquitectura y blast radius.

**Cómo lo usaríamos en Gnosis.** Referencia secundaria.

**Fortalezas que nos interesan.** Local; architecture awareness.

**Limitaciones / precauciones.** Redundante frente a CodeGraph/Sverklo/Sense.

# G. Memoria, sesiones y conocimiento procedural
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [AgentMemory](https://github.com/rohitg00/agentmemory) | **A** | **9.2/10** | Memoria persistente compartida para distintos coding agents. |
| [cass_memory_system](https://github.com/Dicklesworthstone/cass_memory_system) | **S** | **9.6/10** | Sistema de memoria procedural que aprende de historiales de múltiples agentes. |
| [coding_agent_session_search](https://github.com/Dicklesworthstone/coding_agent_session_search) | **A** | **9.0/10** | Búsqueda unificada en historiales de numerosos coding agents. |
| [agent-hop](https://github.com/hetpatel-11/agent-hop) | **B** | **8.3/10** | Buscar, convertir y reanudar sesiones entre agentes. |
| [Mulch](https://github.com/jayminwest/mulch) | **B** | **8.5/10** | Acumulación estructurada de expertise/procedural memory. |
| [Codevira](https://github.com/sachinshelke/codevira) | **B** | **8.7/10** | Memoria de decisiones de proyecto con integración Git y enforcement. |
| [world-model-mcp](https://github.com/SaravananJaichandar/world-model-mcp) | **A** | **9.1/10** | Knowledge graph temporal/auditable con restricciones, provenance y memoria. |
| [agent-traces](https://github.com/edwarddgao/agent-traces) | **B** | **8.4/10** | Búsqueda semántica local sobre trazas/sesiones de Claude, Codex y otros. |
| [Entire CLI](https://github.com/entireio/cli) | **B** | **8.8/10** | Captura sesiones de agentes mediante Git hooks junto con commits para trazabilidad. |
| [claude-replay](https://github.com/es617/claude-replay) | **B** | **8.3/10** | Genera replays HTML visuales de transcripts de varios coding agents. |
| [ReplayPack](https://github.com/Atomics-hub/replaypack) | **B** | **8.4/10** | Contrato de merge/done para código producido por agentes con invariantes/evidencia. |

## AgentMemory

**Repositorio:** https://github.com/rohitg00/agentmemory  
**Tier:** A — **Potencial para Gnosis:** 9.2/10

**Qué es / para qué sirve.** Memoria persistente compartida para distintos coding agents.

**Cómo lo usaríamos en Gnosis.** Comparar como backend de Knowledge/Episodic Memory entre Claude y Codex.

**Fortalezas que nos interesan.** Cross-agent; MCP/hooks/REST; persistencia.

**Limitaciones / precauciones.** La memoria nunca será autoridad; hay que versionar/provenance y detectar stale memories.

## cass_memory_system

**Repositorio:** https://github.com/Dicklesworthstone/cass_memory_system  
**Tier:** S — **Potencial para Gnosis:** 9.6/10

**Qué es / para qué sirve.** Sistema de memoria procedural que aprende de historiales de múltiples agentes.

**Cómo lo usaríamos en Gnosis.** Referencia principal para Procedural Memory y extracción de lecciones/skills.

**Fortalezas que nos interesan.** Cross-agent; aprende de sesiones; procedural knowledge.

**Limitaciones / precauciones.** Las lecciones deben pasar evaluación antes de convertirse en reglas/skills productivas.

## coding_agent_session_search

**Repositorio:** https://github.com/Dicklesworthstone/coding_agent_session_search  
**Tier:** A — **Potencial para Gnosis:** 9.0/10

**Qué es / para qué sirve.** Búsqueda unificada en historiales de numerosos coding agents.

**Cómo lo usaríamos en Gnosis.** Referencia para recuperar episodios/sesiones históricas sin mezclarlo con truth state.

**Fortalezas que nos interesan.** Muchos agentes; búsqueda local; forensics.

**Limitaciones / precauciones.** Search ≠ memory correctness; resultados deben llevar provenance.

## agent-hop

**Repositorio:** https://github.com/hetpatel-11/agent-hop  
**Tier:** B — **Potencial para Gnosis:** 8.3/10

**Qué es / para qué sirve.** Buscar, convertir y reanudar sesiones entre agentes.

**Cómo lo usaríamos en Gnosis.** Referencia para handoff/portabilidad de sesiones.

**Fortalezas que nos interesan.** Cross-agent migration/handoff.

**Limitaciones / precauciones.** Gnosis preferirá Task/Context Pack durable antes que depender de convertir conversaciones.

## Mulch

**Repositorio:** https://github.com/jayminwest/mulch  
**Tier:** B — **Potencial para Gnosis:** 8.5/10

**Qué es / para qué sirve.** Acumulación estructurada de expertise/procedural memory.

**Cómo lo usaríamos en Gnosis.** Comparar representación de expertise con cass-memory/SkillFlow.

**Fortalezas que nos interesan.** Procedural knowledge; estructurado.

**Limitaciones / precauciones.** Redundante si cass-memory + Skill Registry cubren la necesidad.

## Codevira

**Repositorio:** https://github.com/sachinshelke/codevira  
**Tier:** B — **Potencial para Gnosis:** 8.7/10

**Qué es / para qué sirve.** Memoria de decisiones de proyecto con integración Git y enforcement.

**Cómo lo usaríamos en Gnosis.** Referencia para convertir decisiones persistentes en constraints aplicables.

**Fortalezas que nos interesan.** Decision memory; Git; enforcement.

**Limitaciones / precauciones.** Gnosis debe distinguir decisión humana/ADR de memoria probabilística.

## world-model-mcp

**Repositorio:** https://github.com/SaravananJaichandar/world-model-mcp  
**Tier:** A — **Potencial para Gnosis:** 9.1/10

**Qué es / para qué sirve.** Knowledge graph temporal/auditable con restricciones, provenance y memoria.

**Cómo lo usaríamos en Gnosis.** Estudiar modelo temporal/provenance para Knowledge Memory.

**Fortalezas que nos interesan.** Temporal; provenance; constraints; audit.

**Limitaciones / precauciones.** Puede ser más complejo que lo necesario para V1.

## agent-traces

**Repositorio:** https://github.com/edwarddgao/agent-traces  
**Tier:** B — **Potencial para Gnosis:** 8.4/10

**Qué es / para qué sirve.** Búsqueda semántica local sobre trazas/sesiones de Claude, Codex y otros.

**Cómo lo usaríamos en Gnosis.** Referencia para episodic retrieval y forensics.

**Fortalezas que nos interesan.** Cross-agent traces; semantic search.

**Limitaciones / precauciones.** No sustituye un event ledger tipado.

## Entire CLI

**Repositorio:** https://github.com/entireio/cli  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Captura sesiones de agentes mediante Git hooks junto con commits para trazabilidad.

**Cómo lo usaríamos en Gnosis.** Estudiar vínculo sesión↔commit y provenance de cambios.

**Fortalezas que nos interesan.** Git-centric; searchable; conecta trabajo agentic con historia de código.

**Limitaciones / precauciones.** Gnosis necesitará granularidad de eventos/policies superior.

## claude-replay

**Repositorio:** https://github.com/es617/claude-replay  
**Tier:** B — **Potencial para Gnosis:** 8.3/10

**Qué es / para qué sirve.** Genera replays HTML visuales de transcripts de varios coding agents.

**Cómo lo usaríamos en Gnosis.** Inspiración para visualización forensic, no motor de replay determinista.

**Fortalezas que nos interesan.** Visual; multi-agent; fácil inspección.

**Limitaciones / precauciones.** Replay visual ≠ reejecución determinista.

## ReplayPack

**Repositorio:** https://github.com/Atomics-hub/replaypack  
**Tier:** B — **Potencial para Gnosis:** 8.4/10

**Qué es / para qué sirve.** Contrato de merge/done para código producido por agentes con invariantes/evidencia.

**Cómo lo usaríamos en Gnosis.** Referencia para Proof Packet y done contract.

**Fortalezas que nos interesan.** Evidence/invariants; explícitamente agent-made code.

**Limitaciones / precauciones.** Comparar con Symphony/AWF y nuestro propio contrato.

# H. Policy engine, sandbox y seguridad de agentes
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [Microsoft Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit) | **S** | **10/10** | Toolkit de gobernanza: policy engine, zero-trust identity, sandbox/reliability, Agent SRE y seguridad agentic. |
| [AgentJail](https://github.com/LuD1161/agentjail) | **S** | **9.6/10** | Control local pre-execution: cada tool call pasa por reglas/policy antes de ejecutarse. |
| [nono](https://github.com/nolabs-ai/nono) | **S** | **9.6/10** | Sandbox de bajo overhead para ejecutar agentes con mínimo privilegio. |
| [Agent Sandbox](https://github.com/mattolson/agent-sandbox) | **A** | **9.3/10** | Entorno local seguro para agentes con aislamiento de filesystem/red y secret injection controlada. |
| [Sandbox Probe](https://github.com/controlplaneio/sandbox-probe) | **S** | **9.7/10** | Prueba sistemáticamente qué puede leer/escribir/ver un proceso dentro de un sandbox. |
| [Vigils](https://github.com/duncatzat/vigils) | **A** | **9.0/10** | Control plane local con sandboxing, approvals, secrets y seguridad de herramientas/MCP. |
| [Gensee Crate](https://github.com/GenseeAI/gensee-crate) | **A** | **9.1/10** | Runtime local de workspaces desechables con policy y provenance para agentes. |
| [h5i](https://github.com/h5i-dev/h5i) | **A** | **9.4/10** | Sandbox/auditable execution con distintos niveles de aislamiento, worktrees, patches y receipts. |
| [Awesome Agent Runtime Security](https://github.com/bureado/awesome-agent-runtime-security) | **C** | **8.0/10** | Catálogo de runtime security para agentes: sandboxes, capabilities, WASM, eBPF/LSM, credenciales. |
| [Agentic AI Security Starter Kit](https://github.com/aembit/agentic-ai-security-starter-kit) | **B** | **8.3/10** | Starter kit de defensa en profundidad para sistemas agentic. |

## Microsoft Agent Governance Toolkit

**Repositorio:** https://github.com/microsoft/agent-governance-toolkit  
**Tier:** S — **Potencial para Gnosis:** 10/10

**Qué es / para qué sirve.** Toolkit de gobernanza: policy engine, zero-trust identity, sandbox/reliability, Agent SRE y seguridad agentic.

**Cómo lo usaríamos en Gnosis.** Referencia principal para Policy Plane: allow/warn/deny/escalate/transform, fail-closed y shadow evaluation.

**Fortalezas que nos interesan.** Microsoft; policy-as-code; zero trust; reliability/SRE; amplio alcance.

**Limitaciones / precauciones.** No adoptar todo el stack de golpe; usar especificación/patrones adecuados a un kernel local.

## AgentJail

**Repositorio:** https://github.com/LuD1161/agentjail  
**Tier:** S — **Potencial para Gnosis:** 9.6/10

**Qué es / para qué sirve.** Control local pre-execution: cada tool call pasa por reglas/policy antes de ejecutarse.

**Cómo lo usaríamos en Gnosis.** Referencia principal para Tool Authorization Gateway y OPA/Rego-style policy checks.

**Fortalezas que nos interesan.** Pre-tool interception; allow/approval/deny; local.

**Limitaciones / precauciones.** Integrar con nuestra taxonomía de riesgo y capabilities; evitar dependencia innecesaria si un motor más simple basta.

## nono

**Repositorio:** https://github.com/nolabs-ai/nono  
**Tier:** S — **Potencial para Gnosis:** 9.6/10

**Qué es / para qué sirve.** Sandbox de bajo overhead para ejecutar agentes con mínimo privilegio.

**Cómo lo usaríamos en Gnosis.** Candidato a testear para aislar Claude/Codex en WSL2 durante Gnosis V1/V2.

**Fortalezas que nos interesan.** Diseñado para AI agents; setup/latency bajos; least privilege.

**Limitaciones / precauciones.** Verificar límites reales con Sandbox Probe antes de confiar en él.

## Agent Sandbox

**Repositorio:** https://github.com/mattolson/agent-sandbox  
**Tier:** A — **Potencial para Gnosis:** 9.3/10

**Qué es / para qué sirve.** Entorno local seguro para agentes con aislamiento de filesystem/red y secret injection controlada.

**Cómo lo usaríamos en Gnosis.** Comparar con nono/h5i para Security Plane; estudiar proxy de secretos.

**Fortalezas que nos interesan.** Secrets fuera del contenedor; egress control; filesystem isolation.

**Limitaciones / precauciones.** Mayor complejidad operativa que un sandbox mínimo.

## Sandbox Probe

**Repositorio:** https://github.com/controlplaneio/sandbox-probe  
**Tier:** S — **Potencial para Gnosis:** 9.7/10

**Qué es / para qué sirve.** Prueba sistemáticamente qué puede leer/escribir/ver un proceso dentro de un sandbox.

**Cómo lo usaríamos en Gnosis.** Gate obligatorio para validar y detectar regresiones en los límites del sandbox de Gnosis.

**Fortalezas que nos interesan.** Convierte 'creemos que está aislado' en evidencia; regression-friendly.

**Limitaciones / precauciones.** Complementa, no sustituye, al sandbox.

## Vigils

**Repositorio:** https://github.com/duncatzat/vigils  
**Tier:** A — **Potencial para Gnosis:** 9.0/10

**Qué es / para qué sirve.** Control plane local con sandboxing, approvals, secrets y seguridad de herramientas/MCP.

**Cómo lo usaríamos en Gnosis.** Estudiar descriptor pinning, env clearing y MCP gateway.

**Fortalezas que nos interesan.** Tool/MCP drift detection; secrets; approvals; isolation.

**Limitaciones / precauciones.** Seleccionar sólo mecanismos que aporten valor sobre AgentJail/ACS.

## Gensee Crate

**Repositorio:** https://github.com/GenseeAI/gensee-crate  
**Tier:** A — **Potencial para Gnosis:** 9.1/10

**Qué es / para qué sirve.** Runtime local de workspaces desechables con policy y provenance para agentes.

**Cómo lo usaríamos en Gnosis.** Referencia para disposable workspace forks y runtime safety.

**Fortalezas que nos interesan.** Local-first; policy; provenance; Claude/Codex.

**Limitaciones / precauciones.** Solapa con AWF/h5i/nono.

## h5i

**Repositorio:** https://github.com/h5i-dev/h5i  
**Tier:** A — **Potencial para Gnosis:** 9.4/10

**Qué es / para qué sirve.** Sandbox/auditable execution con distintos niveles de aislamiento, worktrees, patches y receipts.

**Cómo lo usaríamos en Gnosis.** Testear/estudiar tiers process→container→microVM y evidence receipts.

**Fortalezas que nos interesan.** Aislamiento gradual; no credentials in sandbox; patches/receipts; worktree.

**Limitaciones / precauciones.** Durante la investigación aparecieron descripciones antiguas de h5i como verificador multi-candidato; el README actual debe tomarse como fuente de verdad y hoy enfatiza sandbox/auditable execution.

## Awesome Agent Runtime Security

**Repositorio:** https://github.com/bureado/awesome-agent-runtime-security  
**Tier:** C — **Potencial para Gnosis:** 8.0/10

**Qué es / para qué sirve.** Catálogo de runtime security para agentes: sandboxes, capabilities, WASM, eBPF/LSM, credenciales.

**Cómo lo usaríamos en Gnosis.** Biblioteca de investigación V3+.

**Fortalezas que nos interesan.** Amplio mapa de seguridad.

**Limitaciones / precauciones.** Es catálogo, no componente.

## Agentic AI Security Starter Kit

**Repositorio:** https://github.com/aembit/agentic-ai-security-starter-kit  
**Tier:** B — **Potencial para Gnosis:** 8.3/10

**Qué es / para qué sirve.** Starter kit de defensa en profundidad para sistemas agentic.

**Cómo lo usaríamos en Gnosis.** Checklist/reference para threat model y credential handling.

**Fortalezas que nos interesan.** Security-first; defense in depth.

**Limitaciones / precauciones.** Secundario frente a ACS/AgentJail/nono.

# I. Auditoría, record/replay, forensics y observabilidad
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [Reprise](https://github.com/itsshreyasbhardwaj-design/reprise) | **S** | **9.7/10** | Graba llamadas LLM/tool/MCP y permite replay offline determinista, forks y comparación de trayectorias. |
| [llmreplay](https://github.com/dmallya93/llmreplay) | **A** | **9.0/10** | VCR/time-travel para Claude/Codex y testing offline. |
| [Agent Capsule](https://github.com/quantumpipes/agent-capsule) | **S** | **9.6/10** | Recibos criptográficos tamper-evident de sesiones mediante hash chain y firmas. |
| [Catacomb](https://github.com/realkarych/catacomb) | **S** | **9.5/10** | Regression testing de agentes Claude/Codex contra baselines, con resultado apto para CI. |
| [OpenTraces](https://github.com/jayfarei/opentraces) | **S** | **9.7/10** | Evidence layer local que captura qué ven/hacen/cambian los agentes y vincula acciones con Git. |
| [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector) | **S** | **9.8/10** | Estándar vendor-neutral para recibir/procesar/exportar traces, metrics y logs. |
| [Prometheus](https://github.com/prometheus/prometheus) | **A** | **9.1/10** | Métricas, series temporales y alertas. |
| [Grafana](https://github.com/grafana/grafana) | **A** | **9.0/10** | Dashboards para métricas, logs y trazas. |
| [Agent Deck](https://github.com/asheshgoplani/agent-deck) | **B** | **8.6/10** | TUI/session manager para múltiples agentes, worktrees y sesiones remotas. |

## Reprise

**Repositorio:** https://github.com/itsshreyasbhardwaj-design/reprise  
**Tier:** S — **Potencial para Gnosis:** 9.7/10

**Qué es / para qué sirve.** Graba llamadas LLM/tool/MCP y permite replay offline determinista, forks y comparación de trayectorias.

**Cómo lo usaríamos en Gnosis.** Referencia principal para Harness Regression y Time Travel sin gastar modelos reales.

**Fortalezas que nos interesan.** Offline replay; deterministic; fork/diff; perfecto para convertir incidentes del orquestador en tests.

**Limitaciones / precauciones.** Necesitamos validar cobertura exacta de subprocess Claude/Codex y side effects.

## llmreplay

**Repositorio:** https://github.com/dmallya93/llmreplay  
**Tier:** A — **Potencial para Gnosis:** 9.0/10

**Qué es / para qué sirve.** VCR/time-travel para Claude/Codex y testing offline.

**Cómo lo usaríamos en Gnosis.** Comparar con Reprise para capturar/reproducir interacciones.

**Fortalezas que nos interesan.** Enfoque directo en coding agents; offline.

**Limitaciones / precauciones.** Posible redundancia; escoger el formato/mecanismo más estable.

## Agent Capsule

**Repositorio:** https://github.com/quantumpipes/agent-capsule  
**Tier:** S — **Potencial para Gnosis:** 9.6/10

**Qué es / para qué sirve.** Recibos criptográficos tamper-evident de sesiones mediante hash chain y firmas.

**Cómo lo usaríamos en Gnosis.** Referencia principal para Trust Plane y sellado de runs/proof packets.

**Fortalezas que nos interesan.** Verificación offline; hashes/firmas; evidencia resistente a manipulación.

**Limitaciones / precauciones.** No necesitamos criptografía en todas las rutas V1; diseñar para añadirla sin rehacer el event model.

## Catacomb

**Repositorio:** https://github.com/realkarych/catacomb  
**Tier:** S — **Potencial para Gnosis:** 9.5/10

**Qué es / para qué sirve.** Regression testing de agentes Claude/Codex contra baselines, con resultado apto para CI.

**Cómo lo usaríamos en Gnosis.** Referencia principal para Harness Regression Suite.

**Fortalezas que nos interesan.** Trata comportamiento del agente como algo testeable; CI-friendly.

**Limitaciones / precauciones.** Combinar con fake providers/replay para reducir consumo.

## OpenTraces

**Repositorio:** https://github.com/jayfarei/opentraces  
**Tier:** S — **Potencial para Gnosis:** 9.7/10

**Qué es / para qué sirve.** Evidence layer local que captura qué ven/hacen/cambian los agentes y vincula acciones con Git.

**Cómo lo usaríamos en Gnosis.** Referencia principal para Forensics Plane, trace model y context reconstruction.

**Fortalezas que nos interesan.** Claude/Codex hooks; Git attribution; trace query/slicing; OTLP.

**Limitaciones / precauciones.** Cuidar privacidad/volumen; separar raw artifacts de contexto que vuelve al modelo.

## OpenTelemetry Collector

**Repositorio:** https://github.com/open-telemetry/opentelemetry-collector  
**Tier:** S — **Potencial para Gnosis:** 9.8/10

**Qué es / para qué sirve.** Estándar vendor-neutral para recibir/procesar/exportar traces, metrics y logs.

**Cómo lo usaríamos en Gnosis.** Infraestructura estándar para telemetría de Gnosis; evitar inventar protocolo propio.

**Fortalezas que nos interesan.** Estándar; ecosistema amplio; desacopla instrumentación de backend.

**Limitaciones / precauciones.** V1 puede comenzar con event log local y añadir OTEL progresivamente.

## Prometheus

**Repositorio:** https://github.com/prometheus/prometheus  
**Tier:** A — **Potencial para Gnosis:** 9.1/10

**Qué es / para qué sirve.** Métricas, series temporales y alertas.

**Cómo lo usaríamos en Gnosis.** V2/V3 para Agent SLOs, quotas, latencias, failures y health.

**Fortalezas que nos interesan.** Estándar; alerting; maduro.

**Limitaciones / precauciones.** No necesario para prototipo mínimo local.

## Grafana

**Repositorio:** https://github.com/grafana/grafana  
**Tier:** A — **Potencial para Gnosis:** 9.0/10

**Qué es / para qué sirve.** Dashboards para métricas, logs y trazas.

**Cómo lo usaríamos en Gnosis.** Referencia/backend futuro de Control Room/Operations.

**Fortalezas que nos interesan.** Maduro; múltiples fuentes; paneles.

**Limitaciones / precauciones.** No empezar Gnosis construyendo dashboards.

## Agent Deck

**Repositorio:** https://github.com/asheshgoplani/agent-deck  
**Tier:** B — **Potencial para Gnosis:** 8.6/10

**Qué es / para qué sirve.** TUI/session manager para múltiples agentes, worktrees y sesiones remotas.

**Cómo lo usaríamos en Gnosis.** Inspiración de UX operativa para workers running/waiting/idle/error.

**Fortalezas que nos interesan.** Control rápido; sesiones; SSH; worktrees.

**Limitaciones / precauciones.** UI/reference, no kernel.

# J. CI, verificación reproducible, supply chain y resiliencia
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [Dagger](https://github.com/dagger/dagger) | **S** | **9.7/10** | Motor de pipelines programables y reproducibles para build/test/ship, ejecutables localmente o en CI. |
| [Syft](https://github.com/anchore/syft) | **A** | **9.1/10** | Generación de SBOM de imágenes/filesystems. |
| [Grype](https://github.com/anchore/grype) | **A** | **9.1/10** | Escáner de vulnerabilidades de imágenes, filesystems y SBOM. |
| [Cosign / Sigstore](https://github.com/sigstore/cosign) | **A** | **9.2/10** | Firma y verificación de artefactos/containers con transparencia. |
| [SLSA Verifier](https://github.com/slsa-framework/slsa-verifier) | **A** | **9.1/10** | Verifica provenance SLSA de builds/artefactos. |
| [Renovate](https://github.com/renovatebot/renovate) | **B** | **8.7/10** | Automatización del lifecycle de dependencias mediante PRs. |
| [Restate AI Examples](https://github.com/restatedev/ai-examples) | **B** | **8.8/10** | Ejemplos de durable execution para agentes con retries/idempotencia/suspend-resume. |
| [Dapr Agents](https://github.com/dapr/dapr-agents) | **B** | **8.6/10** | Framework de agentes stateful/resilientes/observables sobre workflows distribuidos. |
| [Chaos Mesh](https://github.com/chaos-mesh/chaos-mesh) | **C** | **8.0/10** | Chaos engineering para Kubernetes. |

## Dagger

**Repositorio:** https://github.com/dagger/dagger  
**Tier:** S — **Potencial para Gnosis:** 9.7/10

**Qué es / para qué sirve.** Motor de pipelines programables y reproducibles para build/test/ship, ejecutables localmente o en CI.

**Cómo lo usaríamos en Gnosis.** Candidato fuerte para Verification Engine portable: misma pipeline en worktree, local, CI y merge queue.

**Fortalezas que nos interesan.** Reduce divergencia local/CI; pipeline-as-code; reproducible.

**Limitaciones / precauciones.** Añade runtime/infra; medir si compensa frente a scripts simples en V1.

## Syft

**Repositorio:** https://github.com/anchore/syft  
**Tier:** A — **Potencial para Gnosis:** 9.1/10

**Qué es / para qué sirve.** Generación de SBOM de imágenes/filesystems.

**Cómo lo usaríamos en Gnosis.** Supply Chain Plane para Proof Packets de releases y dependency drift.

**Fortalezas que nos interesan.** Maduro; estándar de facto para SBOM.

**Limitaciones / precauciones.** V2/V3, no núcleo del scheduler.

## Grype

**Repositorio:** https://github.com/anchore/grype  
**Tier:** A — **Potencial para Gnosis:** 9.1/10

**Qué es / para qué sirve.** Escáner de vulnerabilidades de imágenes, filesystems y SBOM.

**Cómo lo usaríamos en Gnosis.** Gate de vulnerabilidades asociado a Syft.

**Fortalezas que nos interesan.** Integración natural con Syft; automatizable.

**Limitaciones / precauciones.** Los CVE findings requieren políticas/triage, no bloqueo ciego universal.

## Cosign / Sigstore

**Repositorio:** https://github.com/sigstore/cosign  
**Tier:** A — **Potencial para Gnosis:** 9.2/10

**Qué es / para qué sirve.** Firma y verificación de artefactos/containers con transparencia.

**Cómo lo usaríamos en Gnosis.** V3/release para firmar artefactos y proof/provenance.

**Fortalezas que nos interesan.** Ecosistema Sigstore; keyless signing; verificación.

**Limitaciones / precauciones.** No necesario para código local inicial.

## SLSA Verifier

**Repositorio:** https://github.com/slsa-framework/slsa-verifier  
**Tier:** A — **Potencial para Gnosis:** 9.1/10

**Qué es / para qué sirve.** Verifica provenance SLSA de builds/artefactos.

**Cómo lo usaríamos en Gnosis.** Supply Chain Plane para comprobar builder/repo/ref y provenance.

**Fortalezas que nos interesan.** Estándar; verificable; complementa firmas/SBOM.

**Limitaciones / precauciones.** Fase de delivery/release.

## Renovate

**Repositorio:** https://github.com/renovatebot/renovate  
**Tier:** B — **Potencial para Gnosis:** 8.7/10

**Qué es / para qué sirve.** Automatización del lifecycle de dependencias mediante PRs.

**Cómo lo usaríamos en Gnosis.** Separar dependency updates de features y alimentar Dependency Admission.

**Fortalezas que nos interesan.** Maduro; gran soporte de ecosistemas.

**Limitaciones / precauciones.** Gnosis debe añadir su propio gate de necesidad/licencia/reputación/security.

## Restate AI Examples

**Repositorio:** https://github.com/restatedev/ai-examples  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Ejemplos de durable execution para agentes con retries/idempotencia/suspend-resume.

**Cómo lo usaríamos en Gnosis.** Referencia para future durable workflow semantics.

**Fortalezas que nos interesan.** Durable execution; retries; stateful patterns.

**Limitaciones / precauciones.** Puede ser overkill frente a SQLite/event sourcing para V1.

## Dapr Agents

**Repositorio:** https://github.com/dapr/dapr-agents  
**Tier:** B — **Potencial para Gnosis:** 8.6/10

**Qué es / para qué sirve.** Framework de agentes stateful/resilientes/observables sobre workflows distribuidos.

**Cómo lo usaríamos en Gnosis.** Referencia V3 para ejecución distribuida.

**Fortalezas que nos interesan.** Resilience; state; observability; distributed.

**Limitaciones / precauciones.** Demasiado para un único PC/WSL2 inicial.

## Chaos Mesh

**Repositorio:** https://github.com/chaos-mesh/chaos-mesh  
**Tier:** C — **Potencial para Gnosis:** 8.0/10

**Qué es / para qué sirve.** Chaos engineering para Kubernetes.

**Cómo lo usaríamos en Gnosis.** Inspiración/herramienta V3 si Gnosis escala a infraestructura distribuida.

**Fortalezas que nos interesan.** Fault injection madura.

**Limitaciones / precauciones.** Kubernetes-specific; V1 puede hacer chaos tests sencillos con procesos/red/disco simulados.

# K. Comunicación, bus de agentes y colaboración
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [Murmur](https://github.com/instavm/murmur) | **A** | **9.0/10** | Bus local/MCP para que Claude Code, Codex y otros CLIs se comuniquen directamente. |

## Murmur

**Repositorio:** https://github.com/instavm/murmur  
**Tier:** A — **Potencial para Gnosis:** 9.0/10

**Qué es / para qué sirve.** Bus local/MCP para que Claude Code, Codex y otros CLIs se comuniquen directamente.

**Cómo lo usaríamos en Gnosis.** Estudiar para diseñar un Agent Message Bus tipado: ASK/ANSWER/FINDING/EVIDENCE/ESCALATE.

**Fortalezas que nos interesan.** Cross-CLI; conserva herramientas/autenticación de cada agente; local.

**Limitaciones / precauciones.** Gnosis no debe depender de chat libre; preferir mensajes estructurados y auditable.

# L. Catálogos y bibliotecas de descubrimiento
| Proyecto | Tier | Potencial Gnosis | Función principal |
|---|---:|---:|---|
| [Best of Agent Harnesses](https://github.com/RyanAlberts/best-of-Agent-Harnesses) | **B** | **8.9/10** | Catálogo curado/rankeado de agent harnesses con datos machine-readable. |
| [Awesome CLI Coding Agents](https://github.com/bradAGI/awesome-cli-coding-agents) | **B** | **8.8/10** | Catálogo amplio de coding agents y harnesses CLI. |
| [Awesome Agent Orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators) | **B** | **8.8/10** | Catálogo de orquestadores de agentes. |
| [Awesome Harness Engineering](https://github.com/ai-boost/awesome-harness-engineering) | **B** | **8.5/10** | Recursos/patrones sobre harness engineering. |
| [Awesome Agent Harness](https://github.com/Picrew/awesome-agent-harness) | **C** | **8.1/10** | Colección de recursos sobre contexto, memoria y harnesses. |

## Best of Agent Harnesses

**Repositorio:** https://github.com/RyanAlberts/best-of-Agent-Harnesses  
**Tier:** B — **Potencial para Gnosis:** 8.9/10

**Qué es / para qué sirve.** Catálogo curado/rankeado de agent harnesses con datos machine-readable.

**Cómo lo usaríamos en Gnosis.** Fuente viva para gap-specific research futuro.

**Fortalezas que nos interesan.** Descubrimiento; rankings; MCP/machine-readable.

**Limitaciones / precauciones.** No es componente de Gnosis.

## Awesome CLI Coding Agents

**Repositorio:** https://github.com/bradAGI/awesome-cli-coding-agents  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Catálogo amplio de coding agents y harnesses CLI.

**Cómo lo usaríamos en Gnosis.** Índice para detectar nuevos runtimes/adapters.

**Fortalezas que nos interesan.** Cobertura amplia; activo.

**Limitaciones / precauciones.** Lista, no evaluación profunda.

## Awesome Agent Orchestrators

**Repositorio:** https://github.com/andyrewlee/awesome-agent-orchestrators  
**Tier:** B — **Potencial para Gnosis:** 8.8/10

**Qué es / para qué sirve.** Catálogo de orquestadores de agentes.

**Cómo lo usaríamos en Gnosis.** Fuente de vigilancia para nuevas alternativas.

**Fortalezas que nos interesan.** Curación temática.

**Limitaciones / precauciones.** No sustituye verificación de cada proyecto.

## Awesome Harness Engineering

**Repositorio:** https://github.com/ai-boost/awesome-harness-engineering  
**Tier:** B — **Potencial para Gnosis:** 8.5/10

**Qué es / para qué sirve.** Recursos/patrones sobre harness engineering.

**Cómo lo usaríamos en Gnosis.** Bibliografía viva para evolucionar Gnosis.

**Fortalezas que nos interesan.** Foco específico en harnesses.

**Limitaciones / precauciones.** Catálogo, no dependencia.

## Awesome Agent Harness

**Repositorio:** https://github.com/Picrew/awesome-agent-harness  
**Tier:** C — **Potencial para Gnosis:** 8.1/10

**Qué es / para qué sirve.** Colección de recursos sobre contexto, memoria y harnesses.

**Cómo lo usaríamos en Gnosis.** Índice secundario.

**Fortalezas que nos interesan.** Amplía cobertura.

**Limitaciones / precauciones.** Redundante con otros catálogos.

# M. Referencias ambiguas, homónimos o menciones no cerradas

Estas referencias **no se borran** de la historia de investigación, pero no deben usarse ni recomendarse hasta resolver el repositorio canónico o confirmar su estado actual.

## 20x

Se mencionó como posible dashboard/routing/skills/heartbeats, pero en la consolidación no quedó asociado con suficiente seguridad a un repositorio canónico concreto.

## Agent Substrate

Mención exploratoria sobre entornos stateful de larga duración; pendiente de resolver owner/repo canónico antes de recomendar.

## Euxis

Se mencionó en relación con supply-chain/slopsquatting. No se conserva como referencia principal hasta verificar de forma inequívoca el repositorio y el alcance actual.

## Claude Context

Nombre históricamente usado por varios proyectos/herramientas de retrieval. No se incluye como recomendado sin owner canónico verificado.

## AgentPack

Se mencionó como context-pack engine, pero la referencia recuperada en la investigación no quedó suficientemente inequívoca para fijar un enlace canónico aquí.

## Agent Tower

Se discutió como patrón de debate/consensus threshold; no queda en shortlist hasta verificar la implementación actual y su compatibilidad real con Claude/Codex.

# N. Reglas de uso de este catálogo

1. **No instalar por cantidad.** Una colección enorme de agentes/skills no implica mejor rendimiento.
2. **Ideas y código no son lo mismo.** Antes de copiar código, comprobar licencia y registrar provenance.
3. **Los claims de benchmarks de cada README son hipótesis hasta que Gnosis los reproduzca.**
4. **El estado actual del README canónico prevalece sobre descripciones antiguas** encontradas durante la investigación.
5. **Discovery general queda congelado.** Se vuelve a GitHub sólo ante una carencia concreta o para vigilar releases de la shortlist.
