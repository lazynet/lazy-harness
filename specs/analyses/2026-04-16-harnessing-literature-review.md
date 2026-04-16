# Harnessing literature review — 2026-04-16

Cross-reference de 18 artículos de LazyMind (resources) + weekly reviews W14/W15 contra el estado actual del harness lazy-claudecode/lazy-harness. Objetivo: identificar gaps accionables y validar priorización del backlog.

## Artículos revisados

| # | Artículo | Colección | Ideas clave para el harness |
|---|----------|-----------|----------------------------|
| 1 | Claude Code Ultimate Guide (FlorianBruniaux) | resources/tech/ia | Security-first mindset, TDD/SDD/BDD adaptados a IA, quiz de 274 preguntas para validar comprensión |
| 2 | The Coding Agent Harness (Julian de Angelis, MercadoLibre) | resources/tech/ia | 4 palancas (Rules, MCPs, Skills, SDD). Context rot a ~60%. Feedback loops como pilar. MercadoLibre: 20K devs, rules estandarizadas por tech |
| 3 | Advanced Context Engineering (HumanLayer/Dex Horthy) | resources/tech/ia | Frequent Intentional Compaction. Research→Plan→Implement. Mantener context utilization 40-60%. 300K LOC Rust codebase, PR aprobada en un día |
| 4 | Lessons from Building Claude Code (Anthropic) | resources/tech/ia | Progressive disclosure > cargar todo. ~20 tools es el bar actual. TodoWrite→Task Tool evolution. El modelo mejora construyendo su propio contexto |
| 5 | How To Be A World-Class Agentic Engineer (@systematicls) | resources/tech/ia | CLAUDE.md = directorio IF-ELSE. TASK_CONTRACT.md. Una sesión por contrato. Less is more. Las frontier companies incorporan buenos patrones al producto |
| 6 | 4 archivos Markdown para multi-agente | resources/tech/ia | SKILL.md + Agent.md + AGENTS.md + INSTRUCTIONS.md. "What I do NOT do" es la sección más importante. Separar rules de workflows |
| 7 | Context Engineering Is The Only Engineering | resources/tech/ia | 4 failure modes: pollution, distraction, confusion, clash. 26K líneas de contexto codificado > código. Knowledge graphs > flat files. Agente como mantenedor de contexto |
| 8 | Anatomy of a Perfect OpenClaw Setup | resources/tech/ia | AGENTS.md <300 líneas. 5 archivos con responsabilidades claras. memory/ como contexto persistente. Skills con archivos de soporte |
| 9 | The Self-Improving AI System (Agent Orchestrator) | resources/tech/ia | Orquestación > agentes individuales. CI como señal automática. 41 CI failures auto-corregidas. Plugin system con 8 slots intercambiables |
| 10 | Monorepo Engineering: 10x AI Agent | resources/tech/programacion | Skills = experiencia codificada. MCPs dan visibilidad (logs). Tooling rápido = más iteraciones = mejor output. Paquetes auto-suficientes con tests aislados |
| 11 | Claude Architect full course | resources/tech/ia | Subagentes con contexto aislado. Hooks para lógica crítica (no solo CLAUDE.md). `--print` + `--output-format stream-json` para CI/CD |
| 12 | 50 Claude Code Tips and Best Practices | resources/tech/ia | PostToolUse auto-format (#39). PreToolUse block destructive (#40). Compact hook para preservar contexto (#41). /clear entre tareas (#12). Session hygiene (#24) |
| 13 | Multi-agent workflows often fail (GitHub Blog) | resources/tech/ia | Typed schemas entre agentes. Action schemas para eliminar ambiguedad. MCP como enforcement layer |
| 14 | GSD: Most Powerful Coding Agent | resources/tech/ia | Milestones→Slices→Tasks. Context pruning con anchors. LLM/deterministic split. "Nunca resumir resúmenes" |
| 15 | Taste-Skill: High-Agency Frontend | resources/tech/herramientas | Single SKILL.md para disciplinar output. 3 parámetros configurables. Patrón reutilizable para cualquier dominio |
| 16 | Claude Subagents vs Agent Teams | resources/tech/ia | Start simple. Multi-agent solo cuando mediblemente necesario |
| 17 | How to Build a Production Grade AI Agent | resources/tech/ia | Agentes en prod requieren infra (rate limiting, session simulation), no solo prompts |
| 18 | The File System Is the New Database | resources/tech/ia | Filesystem + knowledge graph como arquitectura para agentes. AI Agent Personas requieren deep interviewing |
| W14 | Weekly Review Semana 14 | meta/weekly-reviews | Token economics (msg 30 = 31x msg 1). CLAUDE.md budget: 40K chars, MEMORY.md 200 líneas. Subagents comparten prompt cache (5 ≈ 1) |
| W15 | Weekly Review Semana 15 | meta/weekly-reviews | 5 capas de context engineering. Sweet spot 3-5 MCPs. Advisor strategy Sonnet+Opus. Agentes fallan en prod por infra no por prompts |

## Hallazgos: qué ya está bien

El harness cubre ~80% de los patrones recomendados por la literatura:

| Pattern | Implementación actual | Validado por |
|---------|----------------------|-------------|
| CLAUDE.md como router IF-ELSE | ADR-004 | #5 World-Class Agentic Engineer |
| Progressive disclosure de skills | Skills on-demand via Skill tool | #4 Lessons from Building CC |
| Memory cross-session | Compound loop + JSONL + SessionStart | #7, #8, #9 |
| Feedback loop (tests/linters) | /tdd-check gate | #2 Harness at Scale, #12 50 Tips |
| Knowledge search | QMD (BM25 + vectores, 7 colecciones) | #7 Context Engineering, W15 Karpathy |
| Profile isolation | CLAUDE_CONFIG_DIR + PreToolUse hook | Multiple |
| Hooks = garantías, CLAUDE.md = guidance | Principio de diseño documentado | #12 50 Tips, #2 Harness at Scale |
| Worktrees para aislamiento | Non-negotiable #1 | #12 50 Tips, #14 GSD |
| Session export + búsqueda histórica | Stop hook → markdown → QMD | #9 Self-Improving AI |

## Hallazgos: gaps identificados

### Alta prioridad

1. **PreToolUse security (destructive command blocking)** — Solo existe aislamiento cross-profile. Falta bloqueo de `rm -rf`, `drop table`, `git push --force` dentro del perfil. Fuentes: #12, #11, security settings article.

2. **PostToolUse auto-format** — Formato depende de que el agente recuerde correr ruff. Viola "hooks = garantías 100%". Fuente: #12 tip #39.

3. **PreCompact context injection** — Sesiones largas pierden el hilo después de compaction. No hay hook que re-inyecte contexto crítico. Context rot documentado a ~60% de utilización. Fuentes: #12 tip #41, #2, #14.

### Media prioridad

4. **CLAUDE.md triple context clash** — 3 capas de CLAUDE.md + plugins + MCP instructions generan arranque pesado. Session 2026-04-13 detectó "varias miles de tokens" de context injection. Fuentes: #7 (4 failure modes), #8 (<300 líneas).

5. **Session hygiene** — No hay guidance sobre cuándo /clear, cuándo nueva sesión, ni cuándo compactar. Fuentes: #5 (una sesión por contrato), #12 (#12, #24), #3 (40-60% utilización).

6. **MCP server count audit** — Sweet spot 3-5, actualmente sin auditar. Fuente: W15.

7. **Ollama para compound-loop** — Elimina costo de Haiku. Fuentes: W15 cost optimization cluster, legacy ADR-010.

### Baja prioridad

8-15. QMD remoto, health checks, advisor strategy, exclusiones en skills, Cowork sessions, chezmoi migration, lazy-learnings collection, eval framework, local embeddings.

## Backlog repriorizado

Ver [`specs/backlog.md`](../backlog.md) para la versión actualizada con done/pendientes, fuentes por item, y rationale de priorización.

## Tensión clave identificada

Los artículos convergen en una tensión: **más contexto vs. mejor contexto**.

- El SessionStart injection es potente pero pesado
- El CLAUDE.md triple puede generar context clash
- Anthropic dice que ~20 tools es el bar — el mismo principio aplica a context injection
- "World-Class Agentic Engineer" (#5) aboga por **no** usar harnesses complejos — las frontier companies incorporan los buenos patrones al producto base

El harness actual evita la trampa de ser un framework pesado (es mayormente hooks + skills livianos), pero el peso de arranque en tokens merece un audit.

## Recomendación de siguiente acción

1. Fixear quality gate (bloqueante — main está rojo)
2. Implementar los 3 hooks de alta prioridad (security, format, compact)
3. Auditar CLAUDE.md triple por clash y peso en tokens
