# GNOSIS — Repositorios seleccionados para usar, testear o investigar
> **Fecha:** 18 de agosto de 2026  
> Esta es la shortlist operativa. No significa que todos vayan a convertirse en dependencias. La mayoría se utilizarán como **referencias de arquitectura, benchmarks o canteras de mecanismos**. Gnosis conservará un kernel propio, pequeño, determinista y modular.
## Estrategia

- **USAR/TESTEAR**: candidatos que merece la pena ejecutar pronto.
- **DESTRIPAR**: leer arquitectura y código fuente antes de diseñar el módulo equivalente.
- **BENCHMARK/COMPARAR**: enfrentarlo contra alternativas y nuestro baseline.
- **INVESTIGAR**: extraer mecanismos o contratos, sin compromiso de adopción.
- **V2/V3 / MÁS ADELANTE**: estándares/infra que no debe bloquear la V1.
## Shortlist completa

| Recurso | Acción | Prioridad | Qué queremos obtener |
|---|---|---:|---|
| [Bernstein](https://github.com/sipyourdrink-ltd/bernstein) | **DESTRIPAR** | **S** | Kernel determinista, scheduler, gates, journal, lineage y replay. |
| [VirtusLab Orca](https://github.com/VirtusLab/orca) | **TESTEAR + DESTRIPAR** | **S** | Workflow-as-code; que el código determinista obligue a review/commit/verify en vez de pedírselo al LLM. |
| [Cezar](https://github.com/open-mercato/cezar) | **USAR/TESTEAR PRIMERO** | **S** | Andamio para construir Gnosis con Claude+Codex, runners por paso, worktrees y review gate. |
| [Agent Workspace Fabric (AWF)](https://github.com/dimileeh/agent-workspace-fabric) | **DESTRIPAR** | **S** | Execution substrate industrial: worktree, container, validation, PR, CI/review, merge. |
| [Ralphex](https://github.com/umputun/ralphex) | **TESTEAR + DESTRIPAR** | **S** | Loop Claude↔Codex, reviewers especializados, rework y stalemate/circuit-breaker patterns. |
| [Smithers](https://github.com/smithersai/smithers) | **DESTRIPAR** | **S** | Durable workflows, rewind/fork/replay y time travel. |
| [Buildplane](https://github.com/SollanSystems/buildplane) | **INVESTIGAR** | **A** | Trust-first kernel/worker split, event tape y fail-closed authority. |
| [Joshua Agent](https://github.com/jorgevazquez-vagojo/joshua-agent) | **INVESTIGAR** | **A** | Fenced leases, reviewer read-only, shadow comparisons, policies y recovery. |
| [GitHub Spec Kit](https://github.com/github/spec-kit) | **USAR/ADAPTAR** | **S** | Specification Plane y spec-driven development. |
| [Superpowers](https://github.com/obra/superpowers) | **TESTEAR/ADAPTAR** | **S** | Metodología, TDD, skills y revisión; skills sólo tras evaluación. |
| [Hoyeon](https://github.com/team-attention/hoyeon) | **DESTRIPAR** | **A** | StepBack, requirements-first, blind-spot scan, risk/feasibility/verifier roles. |
| [Beads](https://github.com/gastownhall/beads) | **TESTEAR + DESTRIPAR** | **S** | Task DAG/memoria operacional persistente y dependency-aware. |
| [Gas Town](https://github.com/gastownhall/gastown) | **INVESTIGAR** | **A** | Handoffs, mailboxes, workers desechables y coordinación de flota. |
| [Grit](https://github.com/rtk-ai/grit) | **TESTEAR** | **S** | Symbol/AST ownership para prevenir conflictos en paralelo. |
| [Symlock](https://github.com/echoVic/symlock) | **COMPARAR** | **A** | Segunda implementación de symbol locking; comparar con Grit. |
| [Polywave Protocol](https://github.com/blackwell-systems/polywave-protocol) | **INVESTIGAR** | **A** | Invariantes y protocolo de coordinación paralela merge-conflict-aware. |
| [Agent Arena](https://github.com/zhjai/agent-arena) | **DESTRIPAR** | **S** | Independent-first, evidence-first, blind judge y dissent preservation. |
| [Senate](https://github.com/SebastianElvis/senate) | **BENCHMARK** | **A** | Protocolos court/parliament/red-team; sólo promover los que demuestren valor. |
| [OpenAI Codex Plugin for Claude Code](https://github.com/openai/codex-plugin-cc) | **DESTRIPAR ISSUES + CÓDIGO** | **A** | Integración oficial Claude↔Codex y, sobre todo, patrones de fallo reales. |
| [TwinRouterBench](https://github.com/CommonstackAI/TwinRouterBench) | **USAR COMO METODOLOGÍA** | **S** | Benchmark del router por paso; base para Gnosis Router Bench. |
| [AgentFlow](https://github.com/lupantech/AgentFlow) | **INVESTIGAR** | **A** | Atribución modular Planner/Executor/Verifier/Generator. |
| [SkillFlow](https://github.com/ZhangZi-a/SkillFlow) | **INVESTIGAR** | **A** | Skill Lab y promoción de skills basada en benchmark. |
| [Graph of Skills](https://github.com/davidliuk/graph-of-skills) | **INVESTIGAR** | **A** | Skill retrieval por dependencias; mínimo contexto procedural. |
| [Sverklo](https://github.com/sverklo/sverklo) | **TESTEAR** | **S** | Code graph, blast radius, decisiones git-pinned y memoria de repo. |
| [CodeGraph MCP](https://github.com/StarQuant/codegraph-mcp) | **TESTEAR** | **A** | Alternativa/ complemento para symbol graph y Context Compiler. |
| [Code Context Engine](https://github.com/elara-labs/code-context-engine) | **BENCHMARK** | **A** | Comparar selección de contexto y coste/token frente a Sverklo/CodeGraph. |
| [context-mode](https://github.com/mksglu/context-mode) | **AUDITAR, NO ADOPTAR A CIEGAS** | **B** | Tool-output virtualization/context bloat; estudiar tras security review. |
| [cass_memory_system](https://github.com/Dicklesworthstone/cass_memory_system) | **DESTRIPAR** | **S** | Procedural Memory cross-agent y extracción de lecciones. |
| [AgentMemory](https://github.com/rohitg00/agentmemory) | **BENCHMARK** | **A** | Shared Knowledge/Episodic Memory entre Claude/Codex. |
| [world-model-mcp](https://github.com/SaravananJaichandar/world-model-mcp) | **INVESTIGAR** | **A** | Memoria temporal con provenance/constraints. |
| [Microsoft Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit) | **DESTRIPAR/ADOPTAR PATRONES** | **S** | Policy Plane, fail-closed, intervention points, zero trust y Agent SRE. |
| [AgentJail](https://github.com/LuD1161/agentjail) | **TESTEAR** | **S** | Tool Authorization Gateway local con policy-as-code. |
| [nono](https://github.com/nolabs-ai/nono) | **TESTEAR** | **S** | Sandbox de mínimo privilegio para Claude/Codex en WSL2. |
| [h5i](https://github.com/h5i-dev/h5i) | **TESTEAR/COMPARAR** | **A** | Sandbox tiers, patches/receipts y ejecución auditable. |
| [Sandbox Probe](https://github.com/controlplaneio/sandbox-probe) | **USAR EN TESTS** | **S** | Medir límites reales del sandbox y detectar regresiones. |
| [Vigils](https://github.com/duncatzat/vigils) | **INVESTIGAR** | **A** | MCP descriptor pinning, env clearing y gateway de tools/secrets. |
| [Reprise](https://github.com/itsshreyasbhardwaj-design/reprise) | **TESTEAR** | **S** | Record/replay offline y forks para Harness Regression. |
| [Catacomb](https://github.com/realkarych/catacomb) | **TESTEAR** | **S** | Regression testing de agentes contra baseline. |
| [Agent Capsule](https://github.com/quantumpipes/agent-capsule) | **INVESTIGAR** | **S** | Tamper-evident receipts y sellado criptográfico de runs. |
| [OpenTraces](https://github.com/jayfarei/opentraces) | **TESTEAR** | **S** | Forensics: qué vio/hizo/cambió cada agente, Git attribution y trazas. |
| [Dagger](https://github.com/dagger/dagger) | **TESTEAR** | **S** | Verification pipeline idéntica local/CI/merge queue. |
| [Syft](https://github.com/anchore/syft) | **USAR MÁS ADELANTE** | **A** | SBOM en Supply Chain Plane. |
| [Grype](https://github.com/anchore/grype) | **USAR MÁS ADELANTE** | **A** | Vulnerability gate sobre SBOM/artefactos. |
| [Cosign](https://github.com/sigstore/cosign) | **USAR MÁS ADELANTE** | **A** | Firma/verificación de artefactos y provenance. |
| [SLSA Verifier](https://github.com/slsa-framework/slsa-verifier) | **USAR MÁS ADELANTE** | **A** | Verificación de build provenance. |
| [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector) | **ADOPTAR ESTÁNDAR** | **S** | Telemetría vendor-neutral de Gnosis. |
| [Prometheus](https://github.com/prometheus/prometheus) | **V2/V3** | **A** | Agent SLOs, métricas y alertas. |
| [Grafana](https://github.com/grafana/grafana) | **V2/V3** | **A** | Control Room/Operations dashboards. |
| [OpenAI Symphony](https://github.com/openai/symphony) | **DESTRIPAR** | **S** | Proof-of-work y filosofía de gestionar trabajo, no conversaciones. |
| [Claudexor](https://github.com/razzant/claudexor) | **BENCHMARK** | **A** | Best-of-N, cross-family review y runner abstraction. |
| [Omnigent](https://github.com/omnigent-ai/omnigent) | **BENCHMARK** | **A** | Meta-harness y cross-provider review/policies. |
| [A Fable of Codexes](https://github.com/jvogan/a-fable-of-codexes) | **DESTRIPAR** | **A** | Campaigns/waves/squads, bake-offs y worker reports. |
| [Genesis](https://github.com/AmRitJain0442/Genesis) | **TESTEAR EN WINDOWS/WSL** | **A** | Baseline Windows-first Claude+Codex, durable SQLite y worktrees. |
| [Agent Orchestrator](https://github.com/Untrivial-ai/agent-orchestrator) | **BENCHMARK** | **A** | Lifecycle real de worktrees/PR/CI/review y UX. |

# Fase 0 — Andamio para construir Gnosis

## Cezar

**Repositorio:** https://github.com/open-mercato/cezar  
**Acción:** **USAR/TESTEAR PRIMERO** — **Prioridad S**

**Motivo de selección.** Andamio para construir Gnosis con Claude+Codex, runners por paso, worktrees y review gate.

**Qué aporta.** Orquestador local de agentes de programación con workflows multi-runner, worktrees aislados, queue, review gate y recuperación.

**Qué queremos extraer/testear.** Principal candidato para usar/testear como andamio de construcción de Gnosis. Estudiar runners por paso, workflow engine, rate-limit recovery y cockpit.

**Fortalezas.** Claude/Codex/OpenCode/pi; cada paso puede usar un runner diferente; CLIs autenticados localmente; worktrees; variantes; review gate.

**Riesgos o límites.** No convertir Gnosis en un fork de Cezar: debemos conservar nuestro propio state machine y contratos.

## VirtusLab Orca

**Repositorio:** https://github.com/VirtusLab/orca  
**Acción:** **TESTEAR + DESTRIPAR** — **Prioridad S**

**Motivo de selección.** Workflow-as-code; que el código determinista obligue a review/commit/verify en vez de pedírselo al LLM.

**Qué aporta.** Workflows de desarrollo deterministas escritos en código: los agentes hacen lo cognitivo, el workflow obliga al resto.

**Qué queremos extraer/testear.** Uno de los candidatos prioritarios para estudiar/testear durante la construcción de Gnosis.

**Fortalezas.** Workflow-as-code; resume por commits; roles planning/coding/review; evita gastar LLM en tareas deterministas.

**Riesgos o límites.** Tecnología/DSL propios; debemos extraer el principio y evaluar si conviene usarlo directamente.

## Ralphex

**Repositorio:** https://github.com/umputun/ralphex  
**Acción:** **TESTEAR + DESTRIPAR** — **Prioridad S**

**Motivo de selección.** Loop Claude↔Codex, reviewers especializados, rework y stalemate/circuit-breaker patterns.

**Qué aporta.** Extended Ralph Loop: implementación autónoma, validaciones, múltiples reviewers, revisión externa Codex y ciclos de corrección.

**Qué queremos extraer/testear.** Referencia principal para el loop Claude→verificación→Codex→corrección y para circuit breakers/stalemate.

**Fortalezas.** Flujo muy cercano a la idea original de Gnosis; revisores especializados; iteración hasta convergencia.

**Riesgos o límites.** Hay que aprender también de sus fallos reales: límites de uso/errores de infraestructura no deben convertirse en loops de rework.

## Genesis

**Repositorio:** https://github.com/AmRitJain0442/Genesis  
**Acción:** **TESTEAR EN WINDOWS/WSL** — **Prioridad A**

**Motivo de selección.** Baseline Windows-first Claude+Codex, durable SQLite y worktrees.

**Qué aporta.** Orquestador terminal orientado a Windows: Claude planifica/revisa y Codex ejecuta workers con worktrees y estado durable.

**Qué queremos extraer/testear.** Testear por ser especialmente relevante al entorno Windows/WSL de Gnosis y estudiar su estado SQLite, acceptance gates y manejo de sesiones OAuth.

**Fortalezas.** Windows-first; Claude+Codex; worktrees; estado durable; acceptance gates; resume/retry.

**Riesgos o límites.** Más pequeño/madurez menor que Cezar; revisar seguridad y supuestos de autenticación antes de reutilizar código.

## Agent Orchestrator

**Repositorio:** https://github.com/Untrivial-ai/agent-orchestrator  
**Acción:** **BENCHMARK** — **Prioridad A**

**Motivo de selección.** Lifecycle real de worktrees/PR/CI/review y UX.

**Qué aporta.** Meta-harness/IDE para gestionar muchas sesiones de agentes en paralelo mediante worktrees, branches, PR, CI y review.

**Qué queremos extraer/testear.** Referencia principal para el lifecycle issue→worker→worktree→PR→CI→review→merge y para la UX operativa.

**Fortalezas.** Amplia compatibilidad de agentes; worktrees; automatización de PR/review/CI; interfaz; enfoque de ingeniería real.

**Riesgos o límites.** Es un sistema grande y opinado; no queremos acoplar el kernel de Gnosis a su modelo interno. Han existido issues Windows/ConPTY y propuestas abiertas de semantic merge.

# Fase 1 — Kernel, estado y lifecycle

## Bernstein

**Repositorio:** https://github.com/sipyourdrink-ltd/bernstein  
**Acción:** **DESTRIPAR** — **Prioridad S**

**Motivo de selección.** Kernel determinista, scheduler, gates, journal, lineage y replay.

**Qué aporta.** Orquestador determinista para agentes CLI con scheduler fuera del LLM, worktrees, quality gates, journal, replay y auditoría.

**Qué queremos extraer/testear.** Una de las referencias más importantes para diseñar el kernel de Gnosis: scheduler, event journal, gates, lineage y replay.

**Fortalezas.** Determinismo; amplia compatibilidad CLI; auditabilidad; ejecución air-gapped; separación fuerte entre IA y coordinación.

**Riesgos o límites.** No debemos copiar toda su implementación sin necesidad; interesa sobre todo su modelo de autoridad y evidencia.

## Agent Workspace Fabric (AWF)

**Repositorio:** https://github.com/dimileeh/agent-workspace-fabric  
**Acción:** **DESTRIPAR** — **Prioridad S**

**Motivo de selección.** Execution substrate industrial: worktree, container, validation, PR, CI/review, merge.

**Qué aporta.** Execution substrate industrial: tarea→worktree→contenedor→validación→commit→PR→CI/review→merge.

**Qué queremos extraer/testear.** Referencia principal para Git/Execution Plane y una de las arquitecturas a destripar primero.

**Fortalezas.** Lifecycle completo; aislamiento; profile validation; PR monitor; CI/review/base sync; preserva workspace fallido.

**Riesgos o límites.** Debe integrarse conceptualmente con nuestro kernel sin delegarle toda la autoridad.

## Smithers

**Repositorio:** https://github.com/smithersai/smithers  
**Acción:** **DESTRIPAR** — **Prioridad S**

**Motivo de selección.** Durable workflows, rewind/fork/replay y time travel.

**Qué aporta.** Framework de workflows de agentes con estado durable, observabilidad y time travel: rewind, fork y replay.

**Qué queremos extraer/testear.** Referencia principal para durable workflows, checkpoints, rewind/fork y debugging temporal.

**Fortalezas.** Time travel real; resume tras crash; workflows multi-provider; observabilidad.

**Riesgos o límites.** Determinar si usar ideas o dependencia; el kernel de Gnosis debe mantener control de sus propios contratos.

## Buildplane

**Repositorio:** https://github.com/SollanSystems/buildplane  
**Acción:** **INVESTIGAR** — **Prioridad A**

**Motivo de selección.** Trust-first kernel/worker split, event tape y fail-closed authority.

**Qué aporta.** Diseño trust-first de control plane donde scheduler, estado, policy y verificación pertenecen al kernel y los modelos son workers acotados.

**Qué queremos extraer/testear.** Referencia conceptual de primer nivel para Trust Plane, event tape y autoridad del kernel.

**Fortalezas.** Coincide con la filosofía central de Gnosis; event ledger; workers acotados; fail-closed.

**Riesgos o límites.** Priorizar patrones/contratos sobre copiar una plataforma completa.

## Joshua Agent

**Repositorio:** https://github.com/jorgevazquez-vagojo/joshua-agent  
**Acción:** **INVESTIGAR** — **Prioridad A**

**Motivo de selección.** Fenced leases, reviewer read-only, shadow comparisons, policies y recovery.

**Qué aporta.** Control plane security-first con Claude/Codex, worktrees, políticas, evaluaciones, shadow comparisons, memoria y leases.

**Qué queremos extraer/testear.** Estudiar fenced leases, reviewer read-only, shadow mode, evaluaciones y least privilege.

**Fortalezas.** Muy buena combinación seguridad+durabilidad+evaluación; roles de mínimo privilegio.

**Riesgos o límites.** Validar madurez/estabilidad; usar como cantera de mecanismos.

## Beads

**Repositorio:** https://github.com/gastownhall/beads  
**Acción:** **TESTEAR + DESTRIPAR** — **Prioridad S**

**Motivo de selección.** Task DAG/memoria operacional persistente y dependency-aware.

**Qué aporta.** Task/issue graph persistente y dependency-aware pensado para agentes.

**Qué queremos extraer/testear.** Referencia principal para memoria operacional: DAG, dependencias, ready/claim/close.

**Fortalezas.** Trabajo persistente separado de la conversación; graph de dependencias; agent-friendly.

**Riesgos o límites.** Decidir si integrarlo o reimplementar un subconjunto sobre SQLite.

## Gas Town

**Repositorio:** https://github.com/gastownhall/gastown  
**Acción:** **INVESTIGAR** — **Prioridad A**

**Motivo de selección.** Handoffs, mailboxes, workers desechables y coordinación de flota.

**Qué aporta.** Workspace/coordination system para operar muchos agentes usando estado persistente, mailboxes y Beads.

**Qué queremos extraer/testear.** Referencia para fleet coordination, handoffs, identities y merge queue.

**Fortalezas.** Escala; task ledger; handoffs; agentes desechables con trabajo durable.

**Riesgos o límites.** Demasiado complejo para V1; estudiar patrones.

## OpenAI Symphony

**Repositorio:** https://github.com/openai/symphony  
**Acción:** **DESTRIPAR** — **Prioridad S**

**Motivo de selección.** Proof-of-work y filosofía de gestionar trabajo, no conversaciones.

**Qué aporta.** Engineering preview oficial de OpenAI para convertir trabajo de proyecto en ejecuciones autónomas aisladas con proof-of-work.

**Qué queremos extraer/testear.** Referencia filosófica y técnica para 'gestionar trabajo, no agentes', aislamiento por tarea y evidencia antes de aterrizar cambios.

**Fortalezas.** Origen oficial OpenAI; proof-of-work; long-running work; integración con workflows de ingeniería.

**Riesgos o límites.** Engineering preview, no necesariamente base estable para Gnosis V1.

# Fase 2 — Spec, reasoning y routing

## GitHub Spec Kit

**Repositorio:** https://github.com/github/spec-kit  
**Acción:** **USAR/ADAPTAR** — **Prioridad S**

**Motivo de selección.** Specification Plane y spec-driven development.

**Qué aporta.** Toolkit de Spec-Driven Development: definir qué construir y convertirlo en planificación/implementación.

**Qué queremos extraer/testear.** Referencia principal de la capa Specification Plane de Gnosis.

**Fortalezas.** Spec-first; proyecto de GitHub; metodología clara; reduce desarrollo prematuro.

**Riesgos o límites.** Gnosis necesitará añadir risk, evidence y task contracts propios.

## Superpowers

**Repositorio:** https://github.com/obra/superpowers  
**Acción:** **TESTEAR/ADAPTAR** — **Prioridad S**

**Motivo de selección.** Metodología, TDD, skills y revisión; skills sólo tras evaluación.

**Qué aporta.** Framework/metodología de skills para desarrollo agentic disciplinado, planificación, TDD, revisión y subagentes.

**Qué queremos extraer/testear.** Fuente principal de metodología y procedural skills; comparar cada skill mediante nuestro Skill Lab.

**Fortalezas.** Workflow disciplinado; TDD; revisión; skills reutilizables.

**Riesgos o límites.** No instalar ciegamente todas las skills: hay que evaluarlas contra baseline.

## Hoyeon

**Repositorio:** https://github.com/team-attention/hoyeon  
**Acción:** **DESTRIPAR** — **Prioridad A**

**Motivo de selección.** StepBack, requirements-first, blind-spot scan, risk/feasibility/verifier roles.

**Qué aporta.** Harness requirements-first con StepBack, verificadores, gate keeper, risk analyst y planificación de verificación.

**Qué queremos extraer/testear.** Copiar conceptualmente StepBack/blind-spot scan y requisitos→plan→verificación.

**Fortalezas.** Evita scope drift; múltiples perspectivas; requirements-first.

**Riesgos o límites.** No usar todos los roles siempre; Gnosis hará profundidad adaptativa.

## Agent Arena

**Repositorio:** https://github.com/zhjai/agent-arena  
**Acción:** **DESTRIPAR** — **Prioridad S**

**Motivo de selección.** Independent-first, evidence-first, blind judge y dissent preservation.

**Qué aporta.** Deliberación evidence-first: propuestas independientes, claims, evidence, cross-critique, blind judge y preservación del desacuerdo.

**Qué queremos extraer/testear.** Referencia principal para el Deliberation Engine de tareas críticas.

**Fortalezas.** Independent-first; evidence-first; dissent preservation; reduce anchoring.

**Riesgos o límites.** No usar en tareas triviales; debe estar sujeto a presupuesto y benchmarks.

## Senate

**Repositorio:** https://github.com/SebastianElvis/senate  
**Acción:** **BENCHMARK** — **Prioridad A**

**Motivo de selección.** Protocolos court/parliament/red-team; sólo promover los que demuestren valor.

**Qué aporta.** Protocolos de deliberación tipo parliament/court/committee/red-team con evaluaciones.

**Qué queremos extraer/testear.** Cantera para Cognitive Protocol Registry y benchmarking de debates.

**Fortalezas.** Protocolos diferenciados; evals; court/parliament/consensus.

**Riesgos o límites.** El consenso no será verdad; sólo una señal subordinada a evidencia.

## TwinRouterBench

**Repositorio:** https://github.com/CommonstackAI/TwinRouterBench  
**Acción:** **USAR COMO METODOLOGÍA** — **Prioridad S**

**Motivo de selección.** Benchmark del router por paso; base para Gnosis Router Bench.

**Qué aporta.** Benchmark de routing de LLM a nivel de paso/decisión, incluyendo evaluación dinámica.

**Qué queremos extraer/testear.** Base metodológica para construir y evaluar el router de Gnosis.

**Fortalezas.** Routing evaluable; granularidad por paso; datasets/labels.

**Riesgos o límites.** Sus modelos/costes no equivalen a nuestras suscripciones CLI; copiar metodología, no resultados.

## AgentFlow

**Repositorio:** https://github.com/lupantech/AgentFlow  
**Acción:** **INVESTIGAR** — **Prioridad A**

**Motivo de selección.** Atribución modular Planner/Executor/Verifier/Generator.

**Qué aporta.** Optimización in-flow de sistemas agentic separando Planner, Executor, Verifier y Generator.

**Qué queremos extraer/testear.** Referencia para Attribution Engine y evaluación modular de componentes cognitivos.

**Fortalezas.** Permite pensar qué componente falló en lugar de culpar genéricamente al modelo.

**Riesgos o límites.** No necesitamos entrenar modelos en V1; extraer la separación y metodología.

## Claudexor

**Repositorio:** https://github.com/razzant/claudexor  
**Acción:** **BENCHMARK** — **Prioridad A**

**Motivo de selección.** Best-of-N, cross-family review y runner abstraction.

**Qué aporta.** Control plane local-first sobre Claude Code, Codex CLI y otros harnesses, con interfaz tipada, Best-of-N y revisión cruzada.

**Qué queremos extraer/testear.** Investigar a fondo su abstracción de runners, routing por capacidades, Best-of-N y gestión de cuotas/cuentas.

**Fortalezas.** Muy alineado con suscripciones/CLI; cross-family review; roles; mejor-de-N; control local.

**Riesgos o límites.** Hay que validar cuidadosamente compatibilidad actual en Windows/WSL y no copiar mecanismos de autenticación que entren en conflicto con políticas de proveedores.

## Omnigent

**Repositorio:** https://github.com/omnigent-ai/omnigent  
**Acción:** **BENCHMARK** — **Prioridad A**

**Motivo de selección.** Meta-harness y cross-provider review/policies.

**Qué aporta.** Meta-harness para coordinar Claude Code, Codex y otros agentes bajo una capa común con colaboración y políticas.

**Qué queremos extraer/testear.** Estudiar abstracción multi-harness, revisión por otro proveedor y patterns como Polly/Debby.

**Fortalezas.** Heterogeneidad de runtimes; cross-provider review; sandboxes/policies; demos de conductor y debate.

**Riesgos o límites.** Más plataforma general que kernel determinista; seleccionar mecanismos concretos.

## A Fable of Codexes

**Repositorio:** https://github.com/jvogan/a-fable-of-codexes  
**Acción:** **DESTRIPAR** — **Prioridad A**

**Motivo de selección.** Campaigns/waves/squads, bake-offs y worker reports.

**Qué aporta.** Conductor Claude con flotas de workers Codex, campañas, waves, squads, cross-review y aprendizaje de preferencias.

**Qué queremos extraer/testear.** Estudiar campañas/waves/squads, worker reports, bake-offs y memoria de ejecución.

**Fortalezas.** Muy buen diseño de flota; cross-model review; worktrees; campañas persistentes.

**Riesgos o límites.** Su jerarquía Claude→Codex es más específica que el router agnóstico que queremos.

## OpenAI Codex Plugin for Claude Code

**Repositorio:** https://github.com/openai/codex-plugin-cc  
**Acción:** **DESTRIPAR ISSUES + CÓDIGO** — **Prioridad A**

**Motivo de selección.** Integración oficial Claude↔Codex y, sobre todo, patrones de fallo reales.

**Qué aporta.** Plugin oficial para invocar Codex desde Claude Code, incluyendo review/delegation.

**Qué queremos extraer/testear.** Estudiar tanto su integración directa como sus issues de loops, usage limits y hooks.

**Fortalezas.** Oficial OpenAI; integración Claude↔Codex; Stop hooks/review.

**Riesgos o límites.** Sus problemas reales muestran por qué Gnosis debe distinguir FAIL_CODE, RATE_LIMITED, INFRA y TIMEOUT.

# Fase 3 — Contexto, memoria y paralelismo

## Sverklo

**Repositorio:** https://github.com/sverklo/sverklo  
**Acción:** **TESTEAR** — **Prioridad S**

**Motivo de selección.** Code graph, blast radius, decisiones git-pinned y memoria de repo.

**Qué aporta.** Memoria/inteligencia de repositorio con symbol graph, blast radius, review y decisiones ancladas a Git.

**Qué queremos extraer/testear.** Referencia principal para conocimiento de código versionado y análisis de impacto.

**Fortalezas.** Git-pinned decisions; symbol graph; blast radius; local-first.

**Riesgos o límites.** Evaluar soporte de lenguajes y coste de indexado en proyectos grandes.

## CodeGraph MCP

**Repositorio:** https://github.com/StarQuant/codegraph-mcp  
**Acción:** **TESTEAR** — **Prioridad A**

**Motivo de selección.** Alternativa/ complemento para symbol graph y Context Compiler.

**Qué aporta.** Índice local precomputado de símbolos, llamadas, dependencias y relaciones para agentes.

**Qué queremos extraer/testear.** Candidato a testear para el Context Plane; alimentar blast radius, context packs y symbol locks.

**Fortalezas.** Local; code graph; auto-sync; integración con Claude/Codex.

**Riesgos o límites.** Benchmarks publicados por el proyecto deben validarse internamente.

## Code Context Engine

**Repositorio:** https://github.com/elara-labs/code-context-engine  
**Acción:** **BENCHMARK** — **Prioridad A**

**Motivo de selección.** Comparar selección de contexto y coste/token frente a Sverklo/CodeGraph.

**Qué aporta.** Indexado local de repositorios para búsquedas agent-friendly con menor lectura/tokenización.

**Qué queremos extraer/testear.** Benchmark contra CodeGraph/Sverklo para seleccionar Context Engine.

**Fortalezas.** Local; integra varios agentes; token-efficiency.

**Riesgos o límites.** La cifra de ahorro que publica el proyecto es una afirmación propia; validar en Gnosis-Bench.

## context-mode

**Repositorio:** https://github.com/mksglu/context-mode  
**Acción:** **AUDITAR, NO ADOPTAR A CIEGAS** — **Prioridad B**

**Motivo de selección.** Tool-output virtualization/context bloat; estudiar tras security review.

**Qué aporta.** Optimiza ventana de contexto, virtualiza outputs de herramientas y mantiene memoria de sesión.

**Qué queremos extraer/testear.** Estudiar Tool Output Virtualization y compresión de contexto; sólo tras security review.

**Fortalezas.** Reduce context bloat; guarda outputs completos fuera del prompt; routing/hooks.

**Riesgos o límites.** Se han reportado preocupaciones de seguridad/sandbox; no adoptarlo sin auditoría estricta.

## cass_memory_system

**Repositorio:** https://github.com/Dicklesworthstone/cass_memory_system  
**Acción:** **DESTRIPAR** — **Prioridad S**

**Motivo de selección.** Procedural Memory cross-agent y extracción de lecciones.

**Qué aporta.** Sistema de memoria procedural que aprende de historiales de múltiples agentes.

**Qué queremos extraer/testear.** Referencia principal para Procedural Memory y extracción de lecciones/skills.

**Fortalezas.** Cross-agent; aprende de sesiones; procedural knowledge.

**Riesgos o límites.** Las lecciones deben pasar evaluación antes de convertirse en reglas/skills productivas.

## AgentMemory

**Repositorio:** https://github.com/rohitg00/agentmemory  
**Acción:** **BENCHMARK** — **Prioridad A**

**Motivo de selección.** Shared Knowledge/Episodic Memory entre Claude/Codex.

**Qué aporta.** Memoria persistente compartida para distintos coding agents.

**Qué queremos extraer/testear.** Comparar como backend de Knowledge/Episodic Memory entre Claude y Codex.

**Fortalezas.** Cross-agent; MCP/hooks/REST; persistencia.

**Riesgos o límites.** La memoria nunca será autoridad; hay que versionar/provenance y detectar stale memories.

## world-model-mcp

**Repositorio:** https://github.com/SaravananJaichandar/world-model-mcp  
**Acción:** **INVESTIGAR** — **Prioridad A**

**Motivo de selección.** Memoria temporal con provenance/constraints.

**Qué aporta.** Knowledge graph temporal/auditable con restricciones, provenance y memoria.

**Qué queremos extraer/testear.** Estudiar modelo temporal/provenance para Knowledge Memory.

**Fortalezas.** Temporal; provenance; constraints; audit.

**Riesgos o límites.** Puede ser más complejo que lo necesario para V1.

## Grit

**Repositorio:** https://github.com/rtk-ai/grit  
**Acción:** **TESTEAR** — **Prioridad S**

**Motivo de selección.** Symbol/AST ownership para prevenir conflictos en paralelo.

**Qué aporta.** Coordinación de agentes con locking a nivel de símbolos/AST para prevenir conflictos antes de editar.

**Qué queremos extraer/testear.** Referencia principal para Symbol Ownership y claims de funciones/clases.

**Fortalezas.** Permite paralelismo dentro del mismo archivo; AST-aware; claim→worktree→merge.

**Riesgos o límites.** Compatibilidad de lenguajes/AST debe evaluarse; necesitamos fallback conservador.

## Symlock

**Repositorio:** https://github.com/echoVic/symlock  
**Acción:** **COMPARAR** — **Prioridad A**

**Motivo de selección.** Segunda implementación de symbol locking; comparar con Grit.

**Qué aporta.** Bloqueo semántico a nivel de símbolos y prevención de conflictos entre agentes.

**Qué queremos extraer/testear.** Comparar con Grit para diseñar la abstracción de symbol leases/locks de Gnosis.

**Fortalezas.** Símbolos; claim/release; enfoque conservador de merge.

**Riesgos o límites.** No asumir que semantic merge es completamente resoluble; post-merge verification seguirá siendo obligatoria.

## Polywave Protocol

**Repositorio:** https://github.com/blackwell-systems/polywave-protocol  
**Acción:** **INVESTIGAR** — **Prioridad A**

**Motivo de selección.** Invariantes y protocolo de coordinación paralela merge-conflict-aware.

**Qué aporta.** Protocolo de coordinación paralela diseñado para minimizar conflictos mediante invariantes, estados y mensajes.

**Qué queremos extraer/testear.** Estudiar como especificación de comunicación/ownership, no necesariamente como runtime.

**Fortalezas.** Implementation-agnostic; invariantes explícitas; coordinación por diseño.

**Riesgos o límites.** Validar su madurez y cómo se comporta en repos grandes reales.

## SkillFlow

**Repositorio:** https://github.com/ZhangZi-a/SkillFlow  
**Acción:** **INVESTIGAR** — **Prioridad A**

**Motivo de selección.** Skill Lab y promoción de skills basada en benchmark.

**Qué aporta.** Benchmark/evolución de skills: extraer procedimientos reutilizables y medir su mejora en tareas futuras.

**Qué queremos extraer/testear.** Referencia principal para el Skill Laboratory de Gnosis.

**Fortalezas.** Skills como candidatos evaluables; evolución basada en tareas.

**Riesgos o límites.** No auto-promocionar skills sin shadow/regression.

## Graph of Skills

**Repositorio:** https://github.com/davidliuk/graph-of-skills  
**Acción:** **INVESTIGAR** — **Prioridad A**

**Motivo de selección.** Skill retrieval por dependencias; mínimo contexto procedural.

**Qué aporta.** Recuperación estructurada de skills mediante grafo de dependencias/prerrequisitos.

**Qué queremos extraer/testear.** Referencia para Skill Router: suministrar sólo skills relevantes.

**Fortalezas.** Evita cargar cientos de skills; dependencias explícitas.

**Riesgos o límites.** Debe combinarse con evaluación real de utilidad.

# Fase 4 — Seguridad, replay y prueba del propio harness

## Microsoft Agent Governance Toolkit

**Repositorio:** https://github.com/microsoft/agent-governance-toolkit  
**Acción:** **DESTRIPAR/ADOPTAR PATRONES** — **Prioridad S**

**Motivo de selección.** Policy Plane, fail-closed, intervention points, zero trust y Agent SRE.

**Qué aporta.** Toolkit de gobernanza: policy engine, zero-trust identity, sandbox/reliability, Agent SRE y seguridad agentic.

**Qué queremos extraer/testear.** Referencia principal para Policy Plane: allow/warn/deny/escalate/transform, fail-closed y shadow evaluation.

**Fortalezas.** Microsoft; policy-as-code; zero trust; reliability/SRE; amplio alcance.

**Riesgos o límites.** No adoptar todo el stack de golpe; usar especificación/patrones adecuados a un kernel local.

## AgentJail

**Repositorio:** https://github.com/LuD1161/agentjail  
**Acción:** **TESTEAR** — **Prioridad S**

**Motivo de selección.** Tool Authorization Gateway local con policy-as-code.

**Qué aporta.** Control local pre-execution: cada tool call pasa por reglas/policy antes de ejecutarse.

**Qué queremos extraer/testear.** Referencia principal para Tool Authorization Gateway y OPA/Rego-style policy checks.

**Fortalezas.** Pre-tool interception; allow/approval/deny; local.

**Riesgos o límites.** Integrar con nuestra taxonomía de riesgo y capabilities; evitar dependencia innecesaria si un motor más simple basta.

## nono

**Repositorio:** https://github.com/nolabs-ai/nono  
**Acción:** **TESTEAR** — **Prioridad S**

**Motivo de selección.** Sandbox de mínimo privilegio para Claude/Codex en WSL2.

**Qué aporta.** Sandbox de bajo overhead para ejecutar agentes con mínimo privilegio.

**Qué queremos extraer/testear.** Candidato a testear para aislar Claude/Codex en WSL2 durante Gnosis V1/V2.

**Fortalezas.** Diseñado para AI agents; setup/latency bajos; least privilege.

**Riesgos o límites.** Verificar límites reales con Sandbox Probe antes de confiar en él.

## h5i

**Repositorio:** https://github.com/h5i-dev/h5i  
**Acción:** **TESTEAR/COMPARAR** — **Prioridad A**

**Motivo de selección.** Sandbox tiers, patches/receipts y ejecución auditable.

**Qué aporta.** Sandbox/auditable execution con distintos niveles de aislamiento, worktrees, patches y receipts.

**Qué queremos extraer/testear.** Testear/estudiar tiers process→container→microVM y evidence receipts.

**Fortalezas.** Aislamiento gradual; no credentials in sandbox; patches/receipts; worktree.

**Riesgos o límites.** Durante la investigación aparecieron descripciones antiguas de h5i como verificador multi-candidato; el README actual debe tomarse como fuente de verdad y hoy enfatiza sandbox/auditable execution.

## Sandbox Probe

**Repositorio:** https://github.com/controlplaneio/sandbox-probe  
**Acción:** **USAR EN TESTS** — **Prioridad S**

**Motivo de selección.** Medir límites reales del sandbox y detectar regresiones.

**Qué aporta.** Prueba sistemáticamente qué puede leer/escribir/ver un proceso dentro de un sandbox.

**Qué queremos extraer/testear.** Gate obligatorio para validar y detectar regresiones en los límites del sandbox de Gnosis.

**Fortalezas.** Convierte 'creemos que está aislado' en evidencia; regression-friendly.

**Riesgos o límites.** Complementa, no sustituye, al sandbox.

## Vigils

**Repositorio:** https://github.com/duncatzat/vigils  
**Acción:** **INVESTIGAR** — **Prioridad A**

**Motivo de selección.** MCP descriptor pinning, env clearing y gateway de tools/secrets.

**Qué aporta.** Control plane local con sandboxing, approvals, secrets y seguridad de herramientas/MCP.

**Qué queremos extraer/testear.** Estudiar descriptor pinning, env clearing y MCP gateway.

**Fortalezas.** Tool/MCP drift detection; secrets; approvals; isolation.

**Riesgos o límites.** Seleccionar sólo mecanismos que aporten valor sobre AgentJail/ACS.

## Reprise

**Repositorio:** https://github.com/itsshreyasbhardwaj-design/reprise  
**Acción:** **TESTEAR** — **Prioridad S**

**Motivo de selección.** Record/replay offline y forks para Harness Regression.

**Qué aporta.** Graba llamadas LLM/tool/MCP y permite replay offline determinista, forks y comparación de trayectorias.

**Qué queremos extraer/testear.** Referencia principal para Harness Regression y Time Travel sin gastar modelos reales.

**Fortalezas.** Offline replay; deterministic; fork/diff; perfecto para convertir incidentes del orquestador en tests.

**Riesgos o límites.** Necesitamos validar cobertura exacta de subprocess Claude/Codex y side effects.

## Catacomb

**Repositorio:** https://github.com/realkarych/catacomb  
**Acción:** **TESTEAR** — **Prioridad S**

**Motivo de selección.** Regression testing de agentes contra baseline.

**Qué aporta.** Regression testing de agentes Claude/Codex contra baselines, con resultado apto para CI.

**Qué queremos extraer/testear.** Referencia principal para Harness Regression Suite.

**Fortalezas.** Trata comportamiento del agente como algo testeable; CI-friendly.

**Riesgos o límites.** Combinar con fake providers/replay para reducir consumo.

## Agent Capsule

**Repositorio:** https://github.com/quantumpipes/agent-capsule  
**Acción:** **INVESTIGAR** — **Prioridad S**

**Motivo de selección.** Tamper-evident receipts y sellado criptográfico de runs.

**Qué aporta.** Recibos criptográficos tamper-evident de sesiones mediante hash chain y firmas.

**Qué queremos extraer/testear.** Referencia principal para Trust Plane y sellado de runs/proof packets.

**Fortalezas.** Verificación offline; hashes/firmas; evidencia resistente a manipulación.

**Riesgos o límites.** No necesitamos criptografía en todas las rutas V1; diseñar para añadirla sin rehacer el event model.

## OpenTraces

**Repositorio:** https://github.com/jayfarei/opentraces  
**Acción:** **TESTEAR** — **Prioridad S**

**Motivo de selección.** Forensics: qué vio/hizo/cambió cada agente, Git attribution y trazas.

**Qué aporta.** Evidence layer local que captura qué ven/hacen/cambian los agentes y vincula acciones con Git.

**Qué queremos extraer/testear.** Referencia principal para Forensics Plane, trace model y context reconstruction.

**Fortalezas.** Claude/Codex hooks; Git attribution; trace query/slicing; OTLP.

**Riesgos o límites.** Cuidar privacidad/volumen; separar raw artifacts de contexto que vuelve al modelo.

## Dagger

**Repositorio:** https://github.com/dagger/dagger  
**Acción:** **TESTEAR** — **Prioridad S**

**Motivo de selección.** Verification pipeline idéntica local/CI/merge queue.

**Qué aporta.** Motor de pipelines programables y reproducibles para build/test/ship, ejecutables localmente o en CI.

**Qué queremos extraer/testear.** Candidato fuerte para Verification Engine portable: misma pipeline en worktree, local, CI y merge queue.

**Fortalezas.** Reduce divergencia local/CI; pipeline-as-code; reproducible.

**Riesgos o límites.** Añade runtime/infra; medir si compensa frente a scripts simples en V1.

# Fase 5 — Supply chain y observabilidad

## Syft

**Repositorio:** https://github.com/anchore/syft  
**Acción:** **USAR MÁS ADELANTE** — **Prioridad A**

**Motivo de selección.** SBOM en Supply Chain Plane.

**Qué aporta.** Generación de SBOM de imágenes/filesystems.

**Qué queremos extraer/testear.** Supply Chain Plane para Proof Packets de releases y dependency drift.

**Fortalezas.** Maduro; estándar de facto para SBOM.

**Riesgos o límites.** V2/V3, no núcleo del scheduler.

## Grype

**Repositorio:** https://github.com/anchore/grype  
**Acción:** **USAR MÁS ADELANTE** — **Prioridad A**

**Motivo de selección.** Vulnerability gate sobre SBOM/artefactos.

**Qué aporta.** Escáner de vulnerabilidades de imágenes, filesystems y SBOM.

**Qué queremos extraer/testear.** Gate de vulnerabilidades asociado a Syft.

**Fortalezas.** Integración natural con Syft; automatizable.

**Riesgos o límites.** Los CVE findings requieren políticas/triage, no bloqueo ciego universal.

## Cosign

**Repositorio:** https://github.com/sigstore/cosign  
**Acción:** **USAR MÁS ADELANTE** — **Prioridad A**

**Motivo de selección.** Firma/verificación de artefactos y provenance.

## SLSA Verifier

**Repositorio:** https://github.com/slsa-framework/slsa-verifier  
**Acción:** **USAR MÁS ADELANTE** — **Prioridad A**

**Motivo de selección.** Verificación de build provenance.

**Qué aporta.** Verifica provenance SLSA de builds/artefactos.

**Qué queremos extraer/testear.** Supply Chain Plane para comprobar builder/repo/ref y provenance.

**Fortalezas.** Estándar; verificable; complementa firmas/SBOM.

**Riesgos o límites.** Fase de delivery/release.

## OpenTelemetry Collector

**Repositorio:** https://github.com/open-telemetry/opentelemetry-collector  
**Acción:** **ADOPTAR ESTÁNDAR** — **Prioridad S**

**Motivo de selección.** Telemetría vendor-neutral de Gnosis.

**Qué aporta.** Estándar vendor-neutral para recibir/procesar/exportar traces, metrics y logs.

**Qué queremos extraer/testear.** Infraestructura estándar para telemetría de Gnosis; evitar inventar protocolo propio.

**Fortalezas.** Estándar; ecosistema amplio; desacopla instrumentación de backend.

**Riesgos o límites.** V1 puede comenzar con event log local y añadir OTEL progresivamente.

## Prometheus

**Repositorio:** https://github.com/prometheus/prometheus  
**Acción:** **V2/V3** — **Prioridad A**

**Motivo de selección.** Agent SLOs, métricas y alertas.

**Qué aporta.** Métricas, series temporales y alertas.

**Qué queremos extraer/testear.** V2/V3 para Agent SLOs, quotas, latencias, failures y health.

**Fortalezas.** Estándar; alerting; maduro.

**Riesgos o límites.** No necesario para prototipo mínimo local.

## Grafana

**Repositorio:** https://github.com/grafana/grafana  
**Acción:** **V2/V3** — **Prioridad A**

**Motivo de selección.** Control Room/Operations dashboards.

**Qué aporta.** Dashboards para métricas, logs y trazas.

**Qué queremos extraer/testear.** Referencia/backend futuro de Control Room/Operations.

**Fortalezas.** Maduro; múltiples fuentes; paneles.

**Riesgos o límites.** No empezar Gnosis construyendo dashboards.

# Orden recomendado de trabajo inmediato

1. **Cezar** — instalar/testear como andamio de construcción con Claude Code + Codex.
2. **Bernstein + Orca + AWF** — leer en paralelo para diseñar contratos del kernel, workflow-as-code y lifecycle Git.
3. **Ralphex + codex-plugin-cc** — modelar corrección/review y taxonomía de fallos reales.
4. **Beads + Smithers** — decidir modelo durable de Task DAG, checkpoints y recovery.
5. **Microsoft Agent Governance + AgentJail + nono + Sandbox Probe** — cerrar Policy/Sandbox Contract antes de autonomía amplia.
6. **Spec Kit + Hoyeon + Superpowers** — definir Specification/Planning Contract.
7. **Sverklo/CodeGraph + cass-memory** — prototipar Context/Memory sin convertir memoria en autoridad.
8. **Reprise/Catacomb/OpenTraces** — que Gnosis pueda reproducir y testear sus propios fallos desde temprano.

# Qué NO haremos

- No convertiremos Gnosis en un fork gigantesco de un solo proyecto.
- No instalaremos todos los repositorios simultáneamente.
- No permitiremos que un agente sea a la vez worker, juez y autoridad de merge.
- No aceptaremos benchmarks de README sin reproducirlos cuando la decisión sea importante.
- No usaremos autenticación de suscripción mediante proxies no oficiales: los adapters deben invocar los CLIs oficiales autenticados por el usuario.
- No introduciremos V2/V3 (fleet, dashboards, supply-chain completa, councils grandes) antes de demostrar que la V1 sobrevive a crashes, limits, retries y reanudación.

# Resultado buscado

La shortlist no pretende ensamblar 50 dependencias. Pretende permitir que Gnosis combine los mejores **principios probados**: kernel determinista, workflow durable, trabajo aislado, evidencia, revisión independiente, contexto mínimo, memoria con provenance, policies fail-closed, replay, evaluación y mejora sólo tras superar un baseline.
