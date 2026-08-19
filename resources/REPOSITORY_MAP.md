# GNOSIS — Resource Registry (v0.3)

**Project root (Nicol):** `C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi`  
**External repositories root:** `C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories`  
**Registered resources:** **130** = 126 original + 4 Memory Fabric additions.

## Resolution rule

Claude MUST resolve a local repository by `git remote get-url origin` first. Folder names are only a fallback. If a repo is missing, its canonical GitHub URL below is the source reference and Claude may clone it into `external\repositories` when it is actually needed.

# A. Orquestación, meta-harness y control plane

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **Paperclip** | **B** | [paperclipai/paperclip](https://github.com/paperclipai/paperclip) | Sistema operativo para organizaciones de agentes: objetivos, organigramas, presupuestos, gobernanza, proyectos y panel de control. |
| **AWS CLI Agent Orchestrator (CAO)** | **B** | [awslabs/cli-agent-orchestrator](https://github.com/awslabs/cli-agent-orchestrator) | Orquestador supervisor-worker para múltiples agentes CLI, incluidos Claude Code y Codex. |
| **Agent Orchestrator** | **A** | [Untrivial-ai/agent-orchestrator](https://github.com/Untrivial-ai/agent-orchestrator) | Meta-harness/IDE para gestionar muchas sesiones de agentes en paralelo mediante worktrees, branches, PR, CI y review. |
| **MetaSwarm** | **B** | [dsifry/metaswarm](https://github.com/dsifry/metaswarm) | Lifecycle multiagente orientado a especificación, TDD, implementación, revisión adversarial y entrega. |
| **Codex Orchestrator** | **B** | [kingbootoshi/codex-orchestrator](https://github.com/kingbootoshi/codex-orchestrator) | Permite que Claude Code lance, supervise y dé instrucciones a workers Codex en paralelo. |
| **Claudexor** | **A** | [razzant/claudexor](https://github.com/razzant/claudexor) | Control plane local-first sobre Claude Code, Codex CLI y otros harnesses, con interfaz tipada, Best-of-N y revisión cruzada. |
| **Ouroboros** | **C** | [razzant/ouroboros](https://github.com/razzant/ouroboros) | Agente persistente/autoevolutivo con memoria, identidad durable, backlog y capacidad de modificar su propia implementación. |
| **Ruflo** | **B** | [ruvnet/ruflo](https://github.com/ruvnet/ruflo) | Meta-harness de gran escala con swarms, numerosos agentes especializados, memoria y coordinación distribuida. |
| **Kodo** | **B** | [ikamensh/kodo](https://github.com/ikamensh/kodo) | Orquestador autónomo que dirige agentes de programación y separa implementación de testing/review. |
| **Bernstein** | **S** | [sipyourdrink-ltd/bernstein](https://github.com/sipyourdrink-ltd/bernstein) | Orquestador determinista para agentes CLI con scheduler fuera del LLM, worktrees, quality gates, journal, replay y auditoría. |
| **OMK (Open Multi-Agent Kit)** | **B** | [dmae97/omk](https://github.com/dmae97/omk) | Control plane provider-neutral con DAGs, lanes, evidencia, replay y recuperación. |
| **Maestro** | **B** | [RunMaestro/Maestro](https://github.com/RunMaestro/Maestro) | Command center de escritorio para múltiples agentes, grupos, playbooks y worktrees. |
| **Cezar** | **S** | [open-mercato/cezar](https://github.com/open-mercato/cezar) | Orquestador local de agentes de programación con workflows multi-runner, worktrees aislados, queue, review gate y recuperación. |
| **Ralphex** | **S** | [umputun/ralphex](https://github.com/umputun/ralphex) | Extended Ralph Loop: implementación autónoma, validaciones, múltiples reviewers, revisión externa Codex y ciclos de corrección. |
| **Omnigent** | **A** | [omnigent-ai/omnigent](https://github.com/omnigent-ai/omnigent) | Meta-harness para coordinar Claude Code, Codex y otros agentes bajo una capa común con colaboración y políticas. |
| **A Fable of Codexes** | **A** | [jvogan/a-fable-of-codexes](https://github.com/jvogan/a-fable-of-codexes) | Conductor Claude con flotas de workers Codex, campañas, waves, squads, cross-review y aprendizaje de preferencias. |
| **Tutti** | **A** | [nutthouse/tutti](https://github.com/nutthouse/tutti) | Orquestación multiagente orientada a SDLC, artefactos, gates y registro reproducible. |
| **OpenAI Symphony** | **S** | [openai/symphony](https://github.com/openai/symphony) | Engineering preview oficial de OpenAI para convertir trabajo de proyecto en ejecuciones autónomas aisladas con proof-of-work. |
| **AgentsMesh** | **B** | [AgentsMesh/AgentsMesh](https://github.com/AgentsMesh/AgentsMesh) | Control plane para una flota distribuida de agentes en múltiples máquinas. |
| **Agent Teams AI** | **B** | [777genius/agent-teams-ai](https://github.com/777genius/agent-teams-ai) | Equipos de agentes con Kanban, tareas, mensajería y revisión. |
| **Operator OSS** | **B** | [iishyfishyy/operator-oss](https://github.com/iishyfishyy/operator-oss) | Cockpit local para múltiples sesiones Claude/Codex con aislamiento por worktree. |
| **Superset** | **B** | [superset-sh/superset](https://github.com/superset-sh/superset) | IDE agentic para operar muchos workspaces/agentes en paralelo. |
| **Genesis** | **A** | [AmRitJain0442/Genesis](https://github.com/AmRitJain0442/Genesis) | Orquestador terminal orientado a Windows: Claude planifica/revisa y Codex ejecuta workers con worktrees y estado durable. |
| **Smithers** | **S** | [smithersai/smithers](https://github.com/smithersai/smithers) | Framework de workflows de agentes con estado durable, observabilidad y time travel: rewind, fork y replay. |
| **Buildplane** | **A** | [SollanSystems/buildplane](https://github.com/SollanSystems/buildplane) | Diseño trust-first de control plane donde scheduler, estado, policy y verificación pertenecen al kernel y los modelos son workers acotados. |
| **Joshua Agent** | **A** | [jorgevazquez-vagojo/joshua-agent](https://github.com/jorgevazquez-vagojo/joshua-agent) | Control plane security-first con Claude/Codex, worktrees, políticas, evaluaciones, shadow comparisons, memoria y leases. |
| **Crewplane** | **B** | [crewplaneai/crewplane](https://github.com/crewplaneai/crewplane) | Control plane provider-neutral basado en workflows Markdown, blackboard state y resume/skip. |
| **VirtusLab Orca** | **S** | [VirtusLab/orca](https://github.com/VirtusLab/orca) | Workflows de desarrollo deterministas escritos en código: los agentes hacen lo cognitivo, el workflow obliga al resto. |
| **OpenView** | **B** | [iii-experimental/openview](https://github.com/iii-experimental/openview) | Control plane para agentes CLI reales con worktrees, approvals y event stream. |
| **Drover** | **B** | [cloud-shuttle/drover](https://github.com/cloud-shuttle/drover) | Coordinación de proyectos con tareas paralelas/dependencias y énfasis en progreso durable. |
| **Shipwright** | **B** | [sethdford/shipwright](https://github.com/sethdford/shipwright) | Delivery autónomo con pipelines, fleet operations, perfiles y métricas DORA. |
| **Agent Hive** | **B** | [tctinh/agent-hive](https://github.com/tctinh/agent-hive) | Plan/approve/execute con workers aislados en worktrees y reportes persistentes. |
| **Podiom** | **B** | [Podiom/Podiom](https://github.com/Podiom/Podiom) | Workspace local para agentes Claude/Codex con identidad durable, sesiones, proyectos, tareas y scheduler. |
| **LoopTroop** | **B** | [looptroop-ai/LoopTroop](https://github.com/looptroop-ai/LoopTroop) | Orquestador local con council de planificación, Beads/worktrees y retries estilo Ralph con contexto fresco. |
| **sd0x-dev-flow** | **B** | [sd0xdev/sd0x-dev-flow](https://github.com/sd0xdev/sd0x-dev-flow) | Harness layer para Claude Code con quality gates, skills, Codex brainstorming y disciplina de desarrollo. |
| **Agentic Control Stack** | **C** | [sd0xdev/agentic-control-stack](https://github.com/sd0xdev/agentic-control-stack) | Arquitectura educativa basada en control theory/MAPE-K aplicada a agentes. |

# B. Especificación, planificación y metodología

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **GitHub Spec Kit** | **S** | [github/spec-kit](https://github.com/github/spec-kit) | Toolkit de Spec-Driven Development: definir qué construir y convertirlo en planificación/implementación. |
| **Superpowers** | **S** | [obra/superpowers](https://github.com/obra/superpowers) | Framework/metodología de skills para desarrollo agentic disciplinado, planificación, TDD, revisión y subagentes. |
| **Hoyeon** | **A** | [team-attention/hoyeon](https://github.com/team-attention/hoyeon) | Harness requirements-first con StepBack, verificadores, gate keeper, risk analyst y planificación de verificación. |
| **Beads** | **S** | [gastownhall/beads](https://github.com/gastownhall/beads) | Task/issue graph persistente y dependency-aware pensado para agentes. |
| **Gas Town** | **A** | [gastownhall/gastown](https://github.com/gastownhall/gastown) | Workspace/coordination system para operar muchos agentes usando estado persistente, mailboxes y Beads. |
| **Software Build Assurance Kit** | **B** | [kknipe2k/Software-Build-Assurance-Kit](https://github.com/kknipe2k/Software-Build-Assurance-Kit) | Kit de aseguramiento de builds para agentes: especificación, aprobación, testing, review y evidencia. |

# C. Git, worktrees, paralelismo y conflictos

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **Agent Workspace Fabric (AWF)** | **S** | [dimileeh/agent-workspace-fabric](https://github.com/dimileeh/agent-workspace-fabric) | Execution substrate industrial: tarea→worktree→contenedor→validación→commit→PR→CI/review→merge. |
| **Grit** | **S** | [rtk-ai/grit](https://github.com/rtk-ai/grit) | Coordinación de agentes con locking a nivel de símbolos/AST para prevenir conflictos antes de editar. |
| **Symlock** | **A** | [echoVic/symlock](https://github.com/echoVic/symlock) | Bloqueo semántico a nivel de símbolos y prevención de conflictos entre agentes. |
| **parallel-cc** | **B** | [frankbria/parallel-cc](https://github.com/frankbria/parallel-cc) | Gestión paralela de Claude Code mediante worktrees y análisis de conflictos. |
| **Polywave Protocol** | **A** | [blackwell-systems/polywave-protocol](https://github.com/blackwell-systems/polywave-protocol) | Protocolo de coordinación paralela diseñado para minimizar conflictos mediante invariantes, estados y mensajes. |
| **Polywave** | **B** | [blackwell-systems/polywave](https://github.com/blackwell-systems/polywave) | Implementación orientada a Claude Code del protocolo Polywave. |
| **Polywave Go** | **B** | [blackwell-systems/polywave-go](https://github.com/blackwell-systems/polywave-go) | Motor/CLI en Go para Polywave. |

# D. Revisión adversarial, councils, debate y verificación cognitiva

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **Agent Arena** | **S** | [zhjai/agent-arena](https://github.com/zhjai/agent-arena) | Deliberación evidence-first: propuestas independientes, claims, evidence, cross-critique, blind judge y preservación del desacuerdo. |
| **Senate** | **A** | [SebastianElvis/senate](https://github.com/SebastianElvis/senate) | Protocolos de deliberación tipo parliament/court/committee/red-team con evaluaciones. |
| **LLM Council** | **B** | [sherifkozman/the-llm-council](https://github.com/sherifkozman/the-llm-council) | Framework de council con routing por rol/modo/proveedor. |
| **Agent Review Panel** | **B** | [wan-huiyan/agent-review-panel](https://github.com/wan-huiyan/agent-review-panel) | Panel de 4–6 revisores con posturas diferentes, debate y juez. |
| **OpenAI Codex Plugin for Claude Code** | **A** | [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) | Plugin oficial para invocar Codex desde Claude Code, incluyendo review/delegation. |

# E. Routing, evaluación, skills y auto-mejora controlada

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **TwinRouterBench** | **S** | [CommonstackAI/TwinRouterBench](https://github.com/CommonstackAI/TwinRouterBench) | Benchmark de routing de LLM a nivel de paso/decisión, incluyendo evaluación dinámica. |
| **UncommonRoute** | **B** | [CommonstackAI/UncommonRoute](https://github.com/CommonstackAI/UncommonRoute) | Router automático de modelos que intenta mantener calidad reduciendo coste. |
| **AgentFlow** | **A** | [lupantech/AgentFlow](https://github.com/lupantech/AgentFlow) | Optimización in-flow de sistemas agentic separando Planner, Executor, Verifier y Generator. |
| **Graph of Skills** | **A** | [davidliuk/graph-of-skills](https://github.com/davidliuk/graph-of-skills) | Recuperación estructurada de skills mediante grafo de dependencias/prerrequisitos. |
| **SkillFlow** | **A** | [ZhangZi-a/SkillFlow](https://github.com/ZhangZi-a/SkillFlow) | Benchmark/evolución de skills: extraer procedimientos reutilizables y medir su mejora en tareas futuras. |
| **Memento-Skills** | **B** | [Memento-Teams/Memento-Skills](https://github.com/Memento-Teams/Memento-Skills) | Sistema donde las skills son capacidades persistentes de primera clase. |
| **Awesome Agent Skills** | **C** | [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) | Gran catálogo de skills para distintos agentes. |
| **plaited/agent-eval-harness** | **B** | [plaited/agent-eval-harness](https://github.com/plaited/agent-eval-harness) | Harness de evaluación de agentes CLI con adapters, trajectories y métricas pass@k. |
| **OpenDataHub Agent Eval Harness** | **B** | [opendatahub-io/agent-eval-harness](https://github.com/opendatahub-io/agent-eval-harness) | Evaluaciones declarativas, judges, A/B y optimización. |
| **linny006/agent-eval-harness** | **C** | [linny006/agent-eval-harness](https://github.com/linny006/agent-eval-harness) | Benchmark de agentes sobre issues reales de GitHub. |
| **coding-agent-eval-harness** | **B** | [zackproser/coding-agent-eval-harness](https://github.com/zackproser/coding-agent-eval-harness) | Evaluación sobre tareas históricas de Git en entornos aislados con graders ocultos y telemetría. |
| **WildClawBench** | **B** | [InternLM/WildClawBench](https://github.com/InternLM/WildClawBench) | Benchmark in-the-wild para agentes/harnesses. |
| **ProofAgent Harness** | **A** | [ProofAgent-ai/proofagent-harness](https://github.com/ProofAgent-ai/proofagent-harness) | Harness adversarial para evaluar comportamiento de agentes, tool use y resistencia a escenarios hostiles. |
| **AI Code Quality Framework** | **B** | [0xUXDesign/ai-code-quality-framework](https://github.com/0xUXDesign/ai-code-quality-framework) | Framework de calidad para código generado por IA con Biome, Knip, Stryker, Lefthook y hooks. |
| **Test-Forge** | **B** | [manjeetsharma0796/Test-Forge](https://github.com/manjeetsharma0796/Test-Forge) | Explora generación/evaluación de tests usando mutation testing. |
| **Canary** | **B** | [0xnyn/canary](https://github.com/0xnyn/canary) | QA agentic que captura vídeo, screenshots, consola, red/HAR y Playwright traces. |

# F. Context engineering, code graph y blast radius

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **CodeGraph MCP** | **A** | [StarQuant/codegraph-mcp](https://github.com/StarQuant/codegraph-mcp) | Índice local precomputado de símbolos, llamadas, dependencias y relaciones para agentes. |
| **Sverklo** | **S** | [sverklo/sverklo](https://github.com/sverklo/sverklo) | Memoria/inteligencia de repositorio con symbol graph, blast radius, review y decisiones ancladas a Git. |
| **Code Context Engine** | **A** | [elara-labs/code-context-engine](https://github.com/elara-labs/code-context-engine) | Indexado local de repositorios para búsquedas agent-friendly con menor lectura/tokenización. |
| **context-mode** | **B** | [mksglu/context-mode](https://github.com/mksglu/context-mode) | Optimiza ventana de contexto, virtualiza outputs de herramientas y mantiene memoria de sesión. |
| **UltraCode (faxenoff)** | **B** | [faxenoff/ultracode](https://github.com/faxenoff/ultracode) | MCP de búsqueda estructural/code graph para agentes. |
| **Sense** | **B** | [luuuc/sense](https://github.com/luuuc/sense) | MCP local para comprensión estructural: símbolos, relaciones, convenciones, blast radius y búsqueda semántica. |
| **code-review-graph** | **B** | [tirth8205/code-review-graph](https://github.com/tirth8205/code-review-graph) | Code graph Tree-sitter orientado a review y contexto de blast radius. |
| **Graft** | **B** | [NanoNets/Graft](https://github.com/NanoNets/Graft) | Grafo persistente de contexto de código para agentes. |
| **Cartographer** | **B** | [kingbootoshi/cartographer](https://github.com/kingbootoshi/cartographer) | Mapeo de repositorio con grafo/SQLite y briefs acotados para agentes. |
| **Wonk** | **C** | [etr/wonk](https://github.com/etr/wonk) | Búsqueda code-aware y análisis de blast radius. |
| **roam-code** | **C** | [Cranot/roam-code](https://github.com/Cranot/roam-code) | Inteligencia local de codebase con arquitectura y blast radius. |

# G. Memoria, sesiones y conocimiento procedural

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **AgentMemory** | **A** | [rohitg00/agentmemory](https://github.com/rohitg00/agentmemory) | Memoria persistente compartida para distintos coding agents. |
| **cass_memory_system** | **S** | [Dicklesworthstone/cass_memory_system](https://github.com/Dicklesworthstone/cass_memory_system) | Sistema de memoria procedural que aprende de historiales de múltiples agentes. |
| **coding_agent_session_search** | **A** | [Dicklesworthstone/coding_agent_session_search](https://github.com/Dicklesworthstone/coding_agent_session_search) | Búsqueda unificada en historiales de numerosos coding agents. |
| **agent-hop** | **B** | [hetpatel-11/agent-hop](https://github.com/hetpatel-11/agent-hop) | Buscar, convertir y reanudar sesiones entre agentes. |
| **Mulch** | **B** | [jayminwest/mulch](https://github.com/jayminwest/mulch) | Acumulación estructurada de expertise/procedural memory. |
| **Codevira** | **B** | [sachinshelke/codevira](https://github.com/sachinshelke/codevira) | Memoria de decisiones de proyecto con integración Git y enforcement. |
| **world-model-mcp** | **A** | [SaravananJaichandar/world-model-mcp](https://github.com/SaravananJaichandar/world-model-mcp) | Knowledge graph temporal/auditable con restricciones, provenance y memoria. |
| **agent-traces** | **B** | [edwarddgao/agent-traces](https://github.com/edwarddgao/agent-traces) | Búsqueda semántica local sobre trazas/sesiones de Claude, Codex y otros. |
| **Entire CLI** | **B** | [entireio/cli](https://github.com/entireio/cli) | Captura sesiones de agentes mediante Git hooks junto con commits para trazabilidad. |
| **claude-replay** | **B** | [es617/claude-replay](https://github.com/es617/claude-replay) | Genera replays HTML visuales de transcripts de varios coding agents. |
| **ReplayPack** | **B** | [Atomics-hub/replaypack](https://github.com/Atomics-hub/replaypack) | Contrato de merge/done para código producido por agentes con invariantes/evidencia. |

# H. Policy engine, sandbox y seguridad de agentes

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **Microsoft Agent Governance Toolkit** | **S** | [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit) | Toolkit de gobernanza: policy engine, zero-trust identity, sandbox/reliability, Agent SRE y seguridad agentic. |
| **AgentJail** | **S** | [LuD1161/agentjail](https://github.com/LuD1161/agentjail) | Control local pre-execution: cada tool call pasa por reglas/policy antes de ejecutarse. |
| **nono** | **S** | [nolabs-ai/nono](https://github.com/nolabs-ai/nono) | Sandbox de bajo overhead para ejecutar agentes con mínimo privilegio. |
| **Agent Sandbox** | **A** | [mattolson/agent-sandbox](https://github.com/mattolson/agent-sandbox) | Entorno local seguro para agentes con aislamiento de filesystem/red y secret injection controlada. |
| **Sandbox Probe** | **S** | [controlplaneio/sandbox-probe](https://github.com/controlplaneio/sandbox-probe) | Prueba sistemáticamente qué puede leer/escribir/ver un proceso dentro de un sandbox. |
| **Vigils** | **A** | [duncatzat/vigils](https://github.com/duncatzat/vigils) | Control plane local con sandboxing, approvals, secrets y seguridad de herramientas/MCP. |
| **Gensee Crate** | **A** | [GenseeAI/gensee-crate](https://github.com/GenseeAI/gensee-crate) | Runtime local de workspaces desechables con policy y provenance para agentes. |
| **h5i** | **A** | [h5i-dev/h5i](https://github.com/h5i-dev/h5i) | Sandbox/auditable execution con distintos niveles de aislamiento, worktrees, patches y receipts. |
| **Awesome Agent Runtime Security** | **C** | [bureado/awesome-agent-runtime-security](https://github.com/bureado/awesome-agent-runtime-security) | Catálogo de runtime security para agentes: sandboxes, capabilities, WASM, eBPF/LSM, credenciales. |
| **Agentic AI Security Starter Kit** | **B** | [aembit/agentic-ai-security-starter-kit](https://github.com/aembit/agentic-ai-security-starter-kit) | Starter kit de defensa en profundidad para sistemas agentic. |

# I. Auditoría, record/replay, forensics y observabilidad

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **Reprise** | **S** | [itsshreyasbhardwaj-design/reprise](https://github.com/itsshreyasbhardwaj-design/reprise) | Graba llamadas LLM/tool/MCP y permite replay offline determinista, forks y comparación de trayectorias. |
| **llmreplay** | **A** | [dmallya93/llmreplay](https://github.com/dmallya93/llmreplay) | VCR/time-travel para Claude/Codex y testing offline. |
| **Agent Capsule** | **S** | [quantumpipes/agent-capsule](https://github.com/quantumpipes/agent-capsule) | Recibos criptográficos tamper-evident de sesiones mediante hash chain y firmas. |
| **Catacomb** | **S** | [realkarych/catacomb](https://github.com/realkarych/catacomb) | Regression testing de agentes Claude/Codex contra baselines, con resultado apto para CI. |
| **OpenTraces** | **S** | [jayfarei/opentraces](https://github.com/jayfarei/opentraces) | Evidence layer local que captura qué ven/hacen/cambian los agentes y vincula acciones con Git. |
| **OpenTelemetry Collector** | **S** | [open-telemetry/opentelemetry-collector](https://github.com/open-telemetry/opentelemetry-collector) | Estándar vendor-neutral para recibir/procesar/exportar traces, metrics y logs. |
| **Prometheus** | **A** | [prometheus/prometheus](https://github.com/prometheus/prometheus) | Métricas, series temporales y alertas. |
| **Grafana** | **A** | [grafana/grafana](https://github.com/grafana/grafana) | Dashboards para métricas, logs y trazas. |
| **Agent Deck** | **B** | [asheshgoplani/agent-deck](https://github.com/asheshgoplani/agent-deck) | TUI/session manager para múltiples agentes, worktrees y sesiones remotas. |

# J. CI, verificación reproducible, supply chain y resiliencia

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **Dagger** | **S** | [dagger/dagger](https://github.com/dagger/dagger) | Motor de pipelines programables y reproducibles para build/test/ship, ejecutables localmente o en CI. |
| **Syft** | **A** | [anchore/syft](https://github.com/anchore/syft) | Generación de SBOM de imágenes/filesystems. |
| **Grype** | **A** | [anchore/grype](https://github.com/anchore/grype) | Escáner de vulnerabilidades de imágenes, filesystems y SBOM. |
| **Cosign / Sigstore** | **A** | [sigstore/cosign](https://github.com/sigstore/cosign) | Firma y verificación de artefactos/containers con transparencia. |
| **SLSA Verifier** | **A** | [slsa-framework/slsa-verifier](https://github.com/slsa-framework/slsa-verifier) | Verifica provenance SLSA de builds/artefactos. |
| **Renovate** | **B** | [renovatebot/renovate](https://github.com/renovatebot/renovate) | Automatización del lifecycle de dependencias mediante PRs. |
| **Restate AI Examples** | **B** | [restatedev/ai-examples](https://github.com/restatedev/ai-examples) | Ejemplos de durable execution para agentes con retries/idempotencia/suspend-resume. |
| **Dapr Agents** | **B** | [dapr/dapr-agents](https://github.com/dapr/dapr-agents) | Framework de agentes stateful/resilientes/observables sobre workflows distribuidos. |
| **Chaos Mesh** | **C** | [chaos-mesh/chaos-mesh](https://github.com/chaos-mesh/chaos-mesh) | Chaos engineering para Kubernetes. |

# K. Comunicación, bus de agentes y colaboración

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **Murmur** | **A** | [instavm/murmur](https://github.com/instavm/murmur) | Bus local/MCP para que Claude Code, Codex y otros CLIs se comuniquen directamente. |

# L. Catálogos y bibliotecas de descubrimiento

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **Best of Agent Harnesses** | **B** | [RyanAlberts/best-of-Agent-Harnesses](https://github.com/RyanAlberts/best-of-Agent-Harnesses) | Catálogo curado/rankeado de agent harnesses con datos machine-readable. |
| **Awesome CLI Coding Agents** | **B** | [bradAGI/awesome-cli-coding-agents](https://github.com/bradAGI/awesome-cli-coding-agents) | Catálogo amplio de coding agents y harnesses CLI. |
| **Awesome Agent Orchestrators** | **B** | [andyrewlee/awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators) | Catálogo de orquestadores de agentes. |
| **Awesome Harness Engineering** | **B** | [ai-boost/awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering) | Recursos/patrones sobre harness engineering. |
| **Awesome Agent Harness** | **C** | [Picrew/awesome-agent-harness](https://github.com/Picrew/awesome-agent-harness) | Colección de recursos sobre contexto, memoria y harnesses. |

# M. GNOSIS Memory Fabric additions

| Resource | Tier | GitHub | Purpose |
|---|---:|---|---|
| **ZMem** | **S+** | [zerkerlabs/zmem](https://github.com/zerkerlabs/zmem) | Local-first governed/verifiable agent memory: trust, authority, quarantine, lineage, revocation and receipts. |
| **M3 Memory** | **S+** | [skynetcmd/m3-memory](https://github.com/skynetcmd/m3-memory) | Local-first shared memory for coding agents with hybrid retrieval, chat/session capture and MCP integration. |
| **Graphify** | **A+ OPTIONAL** | [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) | Queryable knowledge graph over code/docs/media; candidate structural-memory/code-intelligence backend. |
| **Obsidian Mind** | **B OPTIONAL** | [breferrari/obsidian-mind](https://github.com/breferrari/obsidian-mind) | Obsidian-vault based persistent agent memory; candidate for a human-readable knowledge mirror, never runtime authority. |

