# lazy-harness backlog

Issues y mejoras pendientes. Este archivo es **interno** (no se publica al sitio MkDocs); el roadmap público vive en `docs/roadmap.md` y solo contiene los temas comprometidos a alto nivel.

Última revisión: 2026-04-16 — cruce de 18 artículos de LazyMind + weekly reviews W14/W15 contra el estado del harness. Análisis completo en [`specs/analyses/2026-04-16-harnessing-literature-review.md`](analyses/2026-04-16-harnessing-literature-review.md).

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

---

## Open — Prioridad ALTA

> **Cluster de hooks (ship juntos):** los items `PreToolUse security`, `PostToolUse auto-format` y `PreCompact context injection` comparten superficie (`settings.json` del profile + tests de hooks) y se diseñan + mergean como un bloque único. Un PR, tres hooks.

### PreToolUse security: destructive command blocking

**Por qué:** el harness tiene aislamiento cross-profile (flex no toca lazy) pero no bloquea comandos destructivos _dentro_ del perfil ni exfiltración de secrets. Todo pasa sin control hoy.

**Fuente:** [50 Claude Code Tips #40](lazy-lazymind-resources/tech/ia/50-claude-code-tips-and-best-practices-for-daily-use.md), [CC Security Settings 3 capas](lazy-lazymind-resources/tech/ia/claude-code-security-settings-permissions-sandbox.md), [Claude Architect full course](lazy-lazymind-resources/tech/ia/i-want-to-become-a-claude-architect-full-course.md) — todos recomiendan PreToolUse hooks con exit 2 para bloqueo duro.

**Scope de bloqueo (exit 2, no sugerencia):**

1. **Filesystem / shell destructivo:**
    - `rm -rf` (con path), `truncate`
    - `git push --force` (incluye `-f`, excepto `--force-with-lease`)
    - `git reset --hard`

2. **SQL destructivo:**
    - `drop table`, `drop database`, `truncate table`

3. **Terraform destructivo** (el flag histórico `--force` no existe en versiones modernas; los reales son):
    - `terraform destroy` (cualquier invocación)
    - `terraform apply -auto-approve` (saltea review humano)
    - `terraform apply -replace=...` (fuerza recreación)
    - `terraform state rm` y `terraform state push` (modifican state sin tocar infra visible)

4. **Lectura de archivos con credenciales** (exfiltración vía stdout / logs / transcript):
    - Matcher sobre `Bash` + comandos de lectura (`cat`, `bat`, `less`, `more`, `head`, `tail`, `grep`, `rg`, `awk`, `sed`) apuntando a:
      - `.env`, `.env.*` (allowlist `.env.example`, `.env.sample`, `.env.template`)
      - `~/.ssh/id_*`, `~/.ssh/*.pem`
      - `~/.aws/credentials`, `~/.aws/config`
      - `~/.gnupg/**`
      - `*.pem`, `*.key`, `*.p12`
      - `.netrc`, `.git-credentials`, `credentials.json`

5. **Commits de secrets (bypass deliberado de `.gitignore`):**
    - `git add -f` (o `--force`) cuyo path matchea los patterns del punto 4. `git add` normal es OK — `.gitignore` ya lo cubre.

**Fuera de scope (MVP):** bloqueo de `echo $SECRET` / `printf $TOKEN`. False positive rate alto (`echo $USER`, `echo $PATH`) y requiere allowlist por variable. Diferir a v2 si aparece evidencia de exfiltración real.

**Hook surface:** PreToolUse con matcher `Bash`, exit 2 + mensaje claro (patrón matcheado + por qué está bloqueado + cómo hacerlo explícito si es intencional, e.g. `.env.example`).

### PostToolUse auto-format (ruff)

**Por qué:** cada edit del agente debería pasar por formatter automáticamente. Hoy el formato depende de que el agente recuerde correr ruff, lo que viola el principio "hooks = garantías 100%".

**Fuente:** [50 Claude Code Tips #39](lazy-lazymind-resources/tech/ia/50-claude-code-tips-and-best-practices-for-daily-use.md) — PostToolUse hook en Edit|Write que corra el formatter automáticamente. El artículo usa Prettier; nosotros usamos ruff format.

**Acción:** PostToolUse hook con matcher `Edit|Write`, command `ruff format "$CLAUDE_FILE_PATH" 2>/dev/null || true`. El `|| true` evita que falle en archivos no-Python.

### PreCompact context injection hook

**Por qué:** en sesiones largas, compaction descarta contexto crítico (tarea actual, archivos modificados, constraints). El agente pierde el hilo. Esto es "context rot" — documentado como el degradador principal de performance a ~60% de utilización del context window.

**Fuente:** [50 Claude Code Tips #41](lazy-lazymind-resources/tech/ia/50-claude-code-tips-and-best-practices-for-daily-use.md) (Notification hook con matcher compact), [The Coding Agent Harness at Scale](lazy-lazymind-resources/tech/ia/the-coding-agent-harness-how-to-actually-make-ai-coding-agents-work-at-scale.md) (context rot a ~60%), [GSD](lazy-lazymind-resources/tech/ia/gsd-how-we-built-the-most-powerful-coding-agent.md) (context pruning with anchors — cada task arranca con context limpio).

**Acción:** Notification hook con matcher `compact` que re-inyecte: task description activa, lista de archivos modificados en la sesión, constraints hard del CLAUDE.md.

### compound-loop: insight capture + learnings lost on long sessions

**Síntoma (insight capture):** los bloques `★ Insight ─` del output style `explanatory` se pierden — gate-out en sesiones cortas, tail-of-20 en sesiones largas.

**Spec:** [`specs/designs/2026-04-13-compound-loop-insight-capture.md`](designs/2026-04-13-compound-loop-insight-capture.md)

**Síntoma (learnings lost):** sesión 4bc38694 (118 mensajes, ~3h) solo disparó extracción una vez. El worker marca `session_id` como processed con flag booleano — en sesiones largas perdés el 97% del contenido.

**Recomendación:** delta-by-index. Trackear último `message_index` procesado por session_id. Implementar juntos con insight capture (comparten mecanismo).

**Impacto:** alto — es el mecanismo principal de captura de learnings.

---

## Open — Prioridad MEDIA

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
