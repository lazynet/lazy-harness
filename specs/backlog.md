# lazy-harness backlog

Issues y mejoras pendientes. Este archivo es **interno** (no se publica al sitio MkDocs); el roadmap público vive en `docs/roadmap.md` y solo contiene los temas comprometidos a alto nivel.

Última revisión: 2026-05-20 — pasada de coherencia docs↔código tras release 0.20.0. Cruce previo de 18 artículos de LazyMind + weekly reviews W14/W15: [`specs/analyses/2026-04-16-harnessing-literature-review.md`](analyses/2026-04-16-harnessing-literature-review.md).

---

## Done

- [x] **Profile isolation via CLAUDE_CONFIG_DIR** — wrapper `lcc`, aislamiento completo por perfil (ADR-009)
- [x] **CLAUDE.md como router IF-ELSE** — carga condicional de docs/ on-demand (ADR-004)
- [x] **Compound loop async** — `claude -p` headless, 100% de evaluaciones (ADR-005 v2)
- [x] **Episodic memory** — decisions.jsonl + failures.jsonl append-only (ADR-006)
- [x] **Cross-project learnings** — auto-generados en Meta/Learnings/ (ADR-007)
- [x] **SessionStart context injection** — git state, LazyNorth, última sesión, decisiones recientes (ADR-008)
- [x] **QMD knowledge search** — 7 colecciones, BM25 + vectores, sync cada 30min, embed diario
- [x] **Session export** — Stop hook exporta a markdown + QMD indexa (incluyendo repos con guiones)
- [x] **Worktrees para todo cambio** — non-negotiable #1, `/new-worktree` + `/cleanup-worktree`
- [x] **Strict TDD con /tdd-check** — pytest + ruff + mkdocs build como gate pre-commit
- [x] **Rename completo a lazy-claudecode** — repo, scripts, docs, vault, QMD
- [x] **Learnings review semanal** — domingos 10:00, output en `Meta/Weekly-Reviews/LR-YYYY-WNN.md`
- [x] **Dedup semántico de learnings** — inyección de títulos existentes al prompt de evaluación
- [x] **lcc-status monitoring dashboard**
- [x] **Zsh completions** — deployment via `deploy.sh completions`
- [x] **Skill /audit-harness** — auditoría integral del harness en paralelo
- [x] **recall-cowork skill** — búsqueda QMD desde Cowork via Desktop Commander
- [x] **Quality gate verde en main** — test_version dinámico + ruff clean (PR #20, release 0.6.4)
- [x] **PreCompact context injection** — el builtin `pre_compact.py` ya re-inyecta tasks (últimos user_msgs) + archivos (`file_path` de tool_use blocks) vía `hookSpecificOutput.additionalContext`. Los hard constraints del CLAUDE.md los re-inyecta Claude Code nativamente post-compact como system-reminder. No queda gap accionable.
- [x] **PreToolUse security hook** — blocks destructive filesystem/git/sql/terraform commands + credentials reads + forced secret commits, with per-profile `allow_patterns` escape hatch (feat/security-hooks-cluster)
- [x] **PostToolUse auto-format hook** — runs `ruff format` on `.py` edits/writes fail-soft (feat/security-hooks-cluster)
- [x] **PostCompact context re-injection** — `post-compact` hook re-emits the `pre-compact` summary into the live post-compaction window with a 5-minute freshness check (ADR-020, design 2026-04-22)
- [x] **SessionEnd handoff freshness** — `session-end` hook + `lh knowledge handoff-now` bypass the Stop-hook gates so `handoff.md` reflects the session's final state (ADR-019)
- [x] **Async response grading** — compound-loop returns `grade` field per session; poor grades escalate to PRJ.md. Output in `memory/grades.jsonl` (ADR-021)
- [x] **claude-md proposals via compound-loop** — worker stages rule proposals in `memory/claude-md.proposal.md`; `context-inject` surfaces them in next SessionStart under `## Proposals to review` for human merge
- [x] **Engram as episodic memory backend** — wrapper `memory/engram.py`, `[memory.engram]` config, MCP deploy gating (ADR-022)
- [x] **engram-persist hook** — deterministic cursor-based mirror of decisions/failures.jsonl → Engram on every Stop event (ADR-029, design 2026-05-04)
- [x] **Graphify as code-structure index** — wrapper `knowledge/graphify.py`, `[knowledge.structure]` config (ADR-023)
- [x] **MCP server orchestration via `lh deploy`** — single seam writes `mcpServers` to each profile's `settings.json` from detected tools (ADR-024)
- [x] **`lh doctor` Features section** — `features.py` helper + Features section listing qmd/engram/graphify with state, version, pin; engram-persist row reads metrics jsonl (ADR-025)
- [x] **`lh config <feature> --init` wizards** — Click group + `wizards/` package with TOML deep-merge for `[memory]` and `[knowledge]` (ADR-026)
- [x] **Memory stack 5-layer canonical vocabulary** — names the user-facing layer model that ADR-016/022/023/024 produced (ADR-027)
- [x] **Configurable session classification rules** — `[[knowledge.classify_rules]]` typed config; defaults reproduce historical behaviour (ADR-028)
- [x] **Memory stack glue layer** — `lh memory consolidate` (propose-only distiller) + `lh memory cross-profile-check` + `pre-tool-use-memory-size` warning hook (ADR-030 G1/G2/G4)
- [x] **Metrics ingest pipeline + sinks** — session-rollup ingestion, `[metrics].sinks` with `sqlite_local` and `http_remote`, opportunistic outbox drain, `lh metrics drain` / `status` (design 2026-04-14)
- [x] **PostToolUse sync-claude** — regenerates segmented `CLAUDE.md` (head/tail/common) when a profile segment is edited; fail-soft
- [x] **Rename a lazy-harness** — repo, package (`lazy_harness`), CLI (`lh`), docs site (`lazynet.github.io/lazy-harness`)
- [x] **Docs coherence pass 2026-05-20** — `lh memory` + `lh knowledge` subcommands completos en CLI reference, hooks documentados (`pre-tool-use-memory-size`, `post-tool-use-sync-claude`), `claude-md.proposal.md` + `grades.jsonl` documentados en compound-loop how page
- [x] **Compound-loop insight capture + delta-by-index** — `★ Insight ─` blocks captured verbatim via regex pre-LLM, gate-bypass when insights present, hash-based dedup, per-session message-index cursor for delta scans (`memory/insights/.cursor.json`). 12 tests TDD. Closed both gate-out (short sessions) and tail-of-20 (long sessions) loss paths from the design [`specs/designs/2026-04-13-compound-loop-insight-capture.md`](designs/2026-04-13-compound-loop-insight-capture.md).

---

## Open — Prioridad ALTA

_(empty — insight capture + delta-by-index shipped 2026-05-20)_

---

## Open — Prioridad MEDIA

### `lh deploy` — merge hook defaults instead of total overwrite

**Síntoma:** `deploy/engine.py` hace `settings["hooks"] = agent_hooks`, sobrescribiendo el bloque completo con solo lo declarado en `config.toml`. Si un profile existente tenía hooks estáticos en `settings.json` (desplegados por migrate, deploys viejos, o ediciones manuales), al agregar cualquier bloque `[hooks.*]` al `config.toml` se pierden todos los demás silenciosamente.

**Caso real (2026-04-17):** pegar `[hooks.pre_tool_use]` + `[hooks.post_tool_use]` en un `config.toml` que no tenía ningún bloque `[hooks.*]` barrió `SessionStart` (context-inject), `Stop` (session-export + compound-loop), y `PreCompact` (pre-compact) del settings.json. Hubo que redeclararlos manualmente. Peor: reveló que `session-end` del PR #22 nunca había llegado al settings.json de este profile — drift silencioso pre-existente.

**Acción (Opción A — elegida):** definir un set `DEFAULT_HOOKS` en código (probablemente `src/lazy_harness/deploy/defaults.py`) mergeado con los bloques de `config.toml`. Override explícito vía `scripts = []` para desactivar un default, o `enabled = false` — decisión de sintaxis a cerrar en el design spec.

**Decisiones pendientes del spec:**
1. Shape del default: lista de scripts per event, o dict `event → scripts`?
2. Cómo desactivar: `scripts = []` (implícito) vs `enabled = false` (explícito)?
3. Adopción cuando un default nuevo se agrega en un release posterior: opt-in automático al hacer `lh deploy`, o requiere acción del user?
4. Dónde vive la lista: Python literal vs TOML embedido en el paquete (para que `lh config show-defaults` pueda imprimirlo sin importar código)?

**Impacto:** footgun serio para cualquier user que tenga profiles pre-existentes y quiera adoptar features nuevas. Onboarding del cluster de security hooks fue el primer caso que lo expuso — el próximo feature que agregue hooks va a pegarle a todos de nuevo si no se arregla.

### Audit CLAUDE.md triple por context clash

**Por qué:** el harness carga 3 capas de CLAUDE.md (global `~/.claude-lazy/CLAUDE.md` + workspace `~/repos/lazy/.claude/CLAUDE.md` + repo `CLAUDE.md`) más plugins + MCP instructions + deferred tools. Session del 2026-04-13 detectó "context injection bastante pesado (~varias miles de tokens)".

**Fuente:** [Context Engineering Is The Only Engineering](lazy-lazymind-resources/tech/ia/context-engineering-is-the-only-engineering-that-matters.md) — 4 failure modes: pollution, distraction, confusion, **clash** (CLAUDE.md dice X pero otro layer dice Y). [Anatomy of a Perfect OpenClaw Setup](lazy-lazymind-resources/tech/ia/anatomy-of-a-perfect-openclaw-setup.md) — AGENTS.md <300 líneas, más que eso degrada adherencia.

**Acción:** medir tokens totales de context injection al inicio de sesión. Identificar contradicciones y redundancias entre las 3 capas. Consolidar o eliminar duplicados.

### Session hygiene guidance

**Por qué:** no hay reglas explícitas sobre cuándo empezar sesión nueva, cuándo compactar, ni cuándo hacer /clear. Las sesiones largas degradan calidad sin que el usuario lo note.

**Fuente:** [World-Class Agentic Engineer](lazy-lazymind-resources/tech/ia/how-to-be-a-world-class-agentic-engineer.md) — una sesión por contrato, sesiones de 24h generan context bloat. [50 Claude Code Tips #12, #24](lazy-lazymind-resources/tech/ia/50-claude-code-tips-and-best-practices-for-daily-use.md) — /clear entre tareas, después de 2 correcciones sobre lo mismo empezar de cero. [Advanced Context Engineering](lazy-lazymind-resources/tech/ia/advanced-context-engineering-for-coding-agents.md) — mantener utilización en 40-60%.

**Acción:** agregar guidance al CLAUDE.md del profile o crear skill Research→Plan→Implement con compaction entre fases.

### MCP server count audit

**Por qué:** cada MCP server agrega tool schemas al context window. Sweet spot: 3-5 servers activos.

**Fuente:** [W15 weekly review](lazy-lazymind-meta/weekly-reviews/wr-2026-w15.md) — "limitar MCP servers activos a 3-5 (actualmente sin auditar cuántos hay cargados)".

**Acción:** auditar cuántos MCPs están activos por perfil. Desactivar los que no se usen frecuentemente.

### Ollama como backend para compound-loop

**Por qué:** el compound-loop-worker usa Haiku via `claude -p`. Ollama eliminaría ese costo ($0). W15 identifica cost optimization como cluster temático emergente.

**Fuente:** [W15 review](lazy-lazymind-meta/weekly-reviews/wr-2026-w15.md) — advisor strategy y cost optimization. Legacy [ADR-010](specs/archive/adrs-legacy/010-ollama-local-llm-integration.md) propone este backend.

**Decisión pendiente:** promover ADR-010 legacy a ADR activo o descartar. Criterio: evaluar cuando homelab esté estable.

---

## Open — Prioridad BAJA

### QMD MCP server en homelab (remoto, shared)

Dar acceso a QMD desde cualquier máquina de la red. Útil pero no urgente — hoy QMD funciona local.

### Knowledge system health checks

**Fuente:** [Context Engineering](lazy-lazymind-resources/tech/ia/context-engineering-is-the-only-engineering-that-matters.md) y artículos de Karpathy (W15) — linting semanal de la wiki, detección de notas huérfanas, links rotos, frontmatter incompleto, contradictions.

Script semanal tipo "vault health check". El agente como mantenedor de contexto.

### Advisor strategy POC (Sonnet+Opus)

**Fuente:** [W15 review](lazy-lazymind-meta/weekly-reviews/wr-2026-w15.md) — Sonnet ejecuta + Opus advisa = calidad near-Opus a 11-85% menos costo.

POC: usar Sonnet para ejecución y Opus solo para planning/review.

### "What I do NOT do" en skills

**Fuente:** [4 archivos Markdown para multi-agente](lazy-lazymind-resources/tech/ia/4-archivos-markdown-para-sistemas-multi-agente.md) — la sección de exclusiones es la más importante para prevenir scope creep en agentes.

Agregar secciones de exclusión explícitas a skills con scope ambiguo.

### Sesiones de Cowork no capturadas

Limitación arquitectural de Cowork (no tiene Stop hook). El recall-cowork skill mitiga parcialmente. Nice-to-have.

### Migrar configs Capa 1 a chezmoi

Infraestructura operativa, no mejora de harnessing. Ningún artículo valida que esto mueva la aguja. Diferir.

### Colección QMD dedicada lazy-learnings (ADR-007)

Optimización incremental del sistema existente. Diferir.

### Framework evaluación multi-modelo (ADR-010)

R&D puro. Diferir hasta tener caso de uso concreto.

### Embeddings locales con nomic-embed-text (ADR-010)

Dedup semántico ya funciona con inyección de títulos. Diferir.

---

## ADR decisions pending

- **Legacy ADR-010 Ollama backend** — promover a ADR activo o descartar. Criterio: si pensás usar Ollama en los próximos 3 meses, promoverlo; si no, descartar con nota de "revaluar cuando haya presión de costo/rate limit".
- **Legacy ADR-013 Proactivity levels per profile** — promover o descartar. Criterio: si agregás un tercer perfil, promoverlo; si no, descartar.
- **ADR-018 implementation epic** — `accepted-deferred`. Trigger: cuando aterrice el segundo extension point (hoy solo hay `metrics_sink`).
