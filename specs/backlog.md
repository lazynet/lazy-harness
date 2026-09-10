# lazy-harness backlog

Issues y mejoras pendientes. Este archivo es **interno** (no se publica al sitio MkDocs); el roadmap público vive en `docs/roadmap.md` y solo contiene los temas comprometidos a alto nivel.

Última revisión: 2026-08-17 — análisis de los tres ejes de refactor (paridad Linux, capability registry, TUI). Tres defectos shipping promovidos a ALTA. Revisión previa: 2026-05-20, pasada de coherencia docs↔código tras release 0.20.0. Cruce previo de 18 artículos de LazyMind + weekly reviews W14/W15: [`specs/analyses/2026-04-16-harnessing-literature-review.md`](analyses/2026-04-16-harnessing-literature-review.md).

---

## Done

- [x] **Profile isolation via CLAUDE_CONFIG_DIR** — wrapper `lcc`, aislamiento completo por perfil (ADR-009)
- [x] **CLAUDE.md como router IF-ELSE** — carga condicional de docs/ on-demand (ADR-004)
- [x] **Compound loop async** — `claude -p` headless, 100% de evaluaciones (ADR-005 v2)
- [x] **Episodic memory** — decisions.jsonl + failures.jsonl append-only (ADR-006)
- [x] **Cross-project learnings** — auto-generados en el knowledge store, bajo `learnings/` (ADR-007)
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
- [x] **Backends systemd y cron del scheduler** — ADR-013 completo. `SystemdBackend` escribe `.timer` + `.service` bajo `$XDG_CONFIG_HOME/systemd/user/` y chequea lingering; `CronBackend` escribe un bloque delimitado preservando las entradas del usuario. Traducción compartida en `scheduler/schedule.py`, que rechaza en vez de aproximar.
- [x] **Traducción de schedule que se niega en vez de adivinar** — `scheduler/schedule.py` con `parse_cron`/`render_launchd`/`ScheduleTranslationError`; `_cron_to_calendar` y `_cron_to_interval` borrados (ADR-013 D4, PR #168, 2026-08-17). Verificado el 2026-09-10 contra las 7 formas comunes: diaria, cada N horas, semanal, mensual y cada N minutos traducen; listas y rangos levantan, porque launchd no puede expresarlos. `lh status cron` muestra el schedule real y `selftest` gana el check `units-stale`. El backlog lo listó como ALTA abierta durante tres semanas después de estar cerrado.
- [x] **`lh deploy` default hooks merge** — `DEFAULT_HOOKS` literal in `deploy/defaults.py` + `merge_with_defaults` pure function; per-event override via config.toml (`scripts = []` opts out); framework-owned `settings.json[hooks]` with backup + warning when manual entries are clobbered (ADR-031, 11 tests TDD). Also fixed `ClaudeCodeAdapter` missing `post_compact → PostCompact` mapping. Closes the 2026-04-17 partial-config drift and makes built-ins out-of-the-box.

---

## Open — Prioridad ALTA

### `stop-verify-guard` está implementado pero no se puede wirear: nada emite `verify_ran`

**Por qué:** el hook mergeó el 2026-09-10 registrado en `_BUILTIN_HOOKS` y **sin** entrada en `config.toml`, a propósito. Lee `verify_ran` para decidir si bloquea, y grepeando `src/` y los skills desplegados, nada lo escribe. Wirearlo hoy no produce enforcement calibrado: produce un nag garantizado — bloquea siempre en el primer `Stop` de toda sesión que declaró goal, y pasa siempre en el segundo, sin importar si se verificó.

`specs/designs/2026-08-16-loop-engineering-plan.md:32` ya lo había decidido: *"Building the guard before the thing it guards produces a hook that blocks on a condition nothing can satisfy."* El hook se construyó igual, por una lectura del design sin el plan companion. El código es correcto y está testeado; lo que falta es el emisor.

**El emisor es la parte que no existe.** `verify-before-done` es un documento de procedimiento: describe qué verificar, pero no llama a `lh` ni escribe en `loop_events`. Un skill no puede emitir un evento por sí solo — hace falta un verbo que registre, del estilo `lh metrics record-verify`, que el procedimiento invoque como último paso.

**Hallazgo aprovechable del mismo trabajo:** `/goal <condition>` escribe sincrónicamente una entrada `{"type":"attachment","attachment":{"type":"goal_status",...}}` al transcript JSONL en el momento en que corre. Es una señal determinística disponible durante el `Stop`, a diferencia de `goal_declared`, que es una clasificación LLM post-hoc del compound-loop. Es más angosta —solo capta el uso explícito de `/goal`, no un criterio declarado en prosa— pero no requiere inferencia.

**Acción:** darle a `verify-before-done` una forma de emitir `verify_ran`, y recién entonces agregar la entrada `[hooks.session_stop]`. Hasta que eso pase, **no desplegar el hook**: el registro en `_BUILTIN_HOOKS` no lo activa, y esa inercia es la que lo mantiene inofensivo.


### `save_config` destruye config — 51 claves perdidas por escritura

`load_config` lee 14 secciones top-level; `_config_to_dict` emite 10, varias parciales. Medido contra el config vivo: se pierden `[compound_loop]`, `[memory.engram]` y `[lazynorth]` enteras, `knowledge.structure`, los 6 `[scheduler.jobs.*]`, `hooks.pre_tool_use.allow_patterns` y `profiles.<name>.lazynorth_doc`.

No causó daño visible todavía porque el único caller en producción es `lh profile`, y los wizards lo esquivan vía `wizards/_toml_merge.py`. Deja de ser esquivable en cuanto algo más escriba config. Fix elegido: read-modify-write sobre el TOML crudo, no completar el serializer. Detalle y tests en [`designs/2026-08-17-capability-registry-design.md`](designs/2026-08-17-capability-registry-design.md) D5.

### Tres claves de `[context_inject]` se ignoran en silencio

`ContextInjectConfig` declara `qmd_suggest_enabled`, `qmd_suggest_top_k` y `graphify_surface_enabled`; `hooks/builtins/context_inject.py` las lee en las líneas 779, 787 y 790; y el bloque de parseo de `load_config` no las puebla nunca. Verificado: pedir `qmd_suggest_enabled = false` carga `True`. Los tres switches están clavados en su default y no hay forma de apagarlos desde config. Se arregla junto con el round-trip.

---

## Open — Prioridad MEDIA

### `lh deploy` promete desplegar skills y no tiene código que lo haga

**Por qué:** `deploy/engine.py:1` y `deploy_cmd.py:41` declaran "profiles, hooks, skills". La palabra `skill` no aparece en ninguna otra línea de `src/` fuera de `migrate/detector.py`. Lo que existe es un bucle genérico — `for item in src_dir.iterdir(): ensure_symlink(item, target_dir / item.name)` — que symlinkea cualquier cosa que encuentre en el source del profile. Los skills funcionan por esa generalidad, no porque haya una ruta de código para ellos.

Es el mismo patrón que el gate de `auto_rebuild_on_commit`: un contrato declarado que nadie implementó, sostenido por un accidente feliz. Mientras el bucle siga siendo genérico no hay bug de comportamiento, pero el docstring no es una fuente de verdad sobre lo que el deploy sabe hacer.

**Fuente:** medido el 2026-09-10 al decidir dónde alojar un skill nuevo.

**Acción:** o el docstring se ajusta a lo que el código hace (symlinkea el contenido del profile source, sea el que sea), o `skills/` gana una ruta explícita con su propia verificación. Lo primero es más honesto y más barato. Ojo con un detalle que el bucle genérico esconde: `ensure_symlink` renombra a `.bak` cualquier target que exista como directorio real antes de symlinkearlo, así que un profile con `skills/` poblado en el destino y ausente en el source pierde el directorio entero de la vista en el próximo deploy — recuperable, pero silencioso.


### `project_key` colapsa repos sin `.git` propio en `local/lazynet`

**Por qué:** `core/project_identity.py:project_key` camina hacia arriba buscando cualquier `.git` ancestro. El home **es** un repo (`~/.git`, dotfiles), así que un directorio sin `.git` propio bajo `~` aterriza en `/Users/lazynet` y sale keyeado `local/lazynet`. Todo repo en esa situación comparte una sola identidad de memoria.

**Fuente:** detectado el 2026-09-10 al implementar `lh memory rightsize`, que por primera vez alcanza directorios sin `.git` propio. Caso concreto: `flex/apps/repo-falopa` se etiqueta `project:local/lazynet`. `memory/local/` todavía no tiene un directorio `lazynet`, así que no hay daño consumado — pero cualquier hook que escriba memoria desde uno de esos directorios lo crearía.

**Acción:** decidir si `main_repo_root` debe cortar la caminata en `$HOME` en vez de aceptarlo como raíz de repo. Toca el keying de memoria real, así que no es un cambio cosmético: revisar los dos `project_key` (`core/project_identity.py` y `hooks/builtins/_shared.py`) y verificar desde un directorio sin `.git` propio antes y después.

### Un test escribió en el knowledge store de producción

**Por qué:** `~/repos/lazy/lazy-knowledge/memory/local/` contiene un único directorio, `test_pre_compact_empty_input0`. Es un nombre de caso de pytest parametrizado, no un proyecto. Algún test resolvió el store real en vez de un `tmp_path`.

**Fuente:** visto el 2026-09-10 al verificar el fallback de `project_key`.

**Acción:** encontrar el test que lo escribe — probablemente uno de `pre_compact` que no inyecta el directorio de knowledge — y darle `tmp_path`. Después borrar el residuo. Mientras exista, cualquier recuento de proyectos en el store lo cuenta como uno más.

### Symlink roto a la era pre-rename

**Por qué:** `~/repos/lazy/.claude/CLAUDE.md` apunta a `lazy-claudecode/workspace-routers/lazy-claude.md`, un repo que ya no existe con ese nombre. Es un router de workspace que quedó colgado del rename a `lazy-harness`.

**Fuente:** salió como la única diferencia entre el `find` del filesystem (35) y lo que reporta `lh memory rightsize` (34) el 2026-09-10 — el comando lo excluye correctamente por no ser legible.

**Acción:** borrar el symlink, o reapuntarlo si ese router todavía cumple una función. Verificar primero si algo lo lee.


### Loop engineering — fases 1 a 4 sin trackear

**Por qué:** [`specs/designs/2026-08-16-loop-engineering-design.md`](designs/2026-08-16-loop-engineering-design.md) diseña cinco fases y solo la 0 shippeó (`user_prompt_goal.py` como sensor). El design nunca entró a este backlog, así que las fases restantes no tenían dónde vencer. Baseline cerrado el 2026-09-10: 17% de declaración (29/169 sesiones graduadas), medido sobre el 7.5% de las sesiones no triviales que el compound-loop llega a graduar.

**Fuente:** el design citado, sección "Phase 0 result". Medición desde `loop_events` en `metrics.db`.

**Acción:** fase 1 (skill `verify-before-done` + `[loops] inject_goal_prompt = true`) abre la ventana de cuatro semanas contra el 17%. Fase 4 (delegación) se reemplaza por el evento `agent_dispatched` de abajo, que mide la misma palanca sin depender de Herdr.

### Delegación a subagentes sin instrumentar

**Por qué:** 150 llamadas al Agent tool en 873 sesiones de septiembre (perfil lazy), todas `general-purpose`, cero `Explore`/`Plan`/`fork`. En el mismo período, 5046 invocaciones de Bash corrieron en el hilo principal. La exploración que podría delegarse a un modelo barato se paga a precio de Opus, y el output crudo queda ocupando contexto el resto de la sesión.

**Fuente:** [orchestrator-tax](lazy-lazymind-resources/tech/ia/orchestrator-tax-costos-contexto-multiagente.md) — distingue tokens (se pagan una vez) de contexto (contamina cada turno). [subagent-context-modes](lazy-lazymind-resources/tech/ia/subagent-context-modes-isolated-vs-fork.md) — worker con `fork`, verifier aislado.

**Acción:** emitir `agent_dispatched` en `loop_events` desde el compound-loop worker, con modelo y `subagent_type` en `detail`. Sin la medida no se puede saber si la práctica se adopta. Baseline: 150/873.

### Reconcile y Decay ausentes del stack de memoria

**Por qué:** 5954 learnings en el knowledge store, **el 100% en `status: active`** — nada se deprecó nunca. Agosto aportó 2959 y septiembre 1192 en diez días. `decisions.jsonl` además drifteó de schema: las líneas viejas traen `timestamp`/`fixed`/`deferred`, las nuevas `ts`/`context`/`rationale`/`alternatives`, y nada lo reconcilia.

**Fuente:** [memory-engineering-five-stage-pipeline](lazy-lazymind-resources/tech/ia/memory-engineering-five-stage-pipeline.md) — Capture, Consolidate, Retrieve, **Reconcile**, **Decay**. El stack de 5 capas del ADR-027 cubre las tres primeras.

**Acción:** ADR-040 más `lh memory decay` y `lh memory reconcile`, ambos propose-only por default como `lh memory consolidate`.

### Rightsizing de CLAUDE.md — enforcement y medición

**Por qué:** `lazy-popopen/CLAUDE.md` tiene 987 líneas y 70 KB, y es el segundo proyecto más caro del mes ($409). `lazy-ai-tools` 333, `lazy-ansible` 308, `lazy-desktop-manager` 223. El hook `pre-tool-use-memory-size` ya tiene los umbrales correctos (200 líneas / 12 KB) pero solo mira `MEMORY.md`. Se solapa con "Audit CLAUDE.md triple por context clash" de abajo: ese item mide el clash entre capas, este mide el tamaño de cada una.

**Fuente:** [fable-5-1](lazy-lazymind-resources/tech/ia/fable-5-1-liderar-agentes-guia-orquestacion.md) — <200 líneas, tres secciones. [Nuevas reglas de context engineering para Claude 5](lazy-lazymind-resources/tech/ia/nuevas-reglas-de-context-engineering-para-claude-5.md) — reglas rígidas → juicio, progressive disclosure hacia skills.

**Acción:** extender el hook a `CLAUDE.md` con umbral propio, agregar `lh memory rightsize` (read-only) y un skill que guíe la poda. Después ejecutar sobre los cuatro repos.



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

**Resuelto:** [ADR-033](adrs/033-llm-backend-abstraction.md) promovió la idea a un Protocol provider-agnostic (implementado 2026-06-11) y [ADR-039](adrs/039-role-routed-inference.md) la hace utilizable: el ruteo pasa a ser por rol, así el modelo local atiende trabajo barato sin quedarse también con el destilado y el grading.

---

## Open — Prioridad BAJA

### Falso positivo del PreToolUse de seguridad con backticks de markdown

**Por qué:** `_COMMAND_START` incluye el backtick como operador de shell — correcto para command substitution. Pero un backtick de markdown inline-code delante de un comando destructivo, incluso dentro de un heredoc citado donde el shell nunca lo interpreta, dispara igual. Escribir prosa *sobre* comandos destructivos queda bloqueado.

**Repro medido el 2026-09-10.** Contra `BLOCK_RULES`, el mismo texto pasa o se bloquea según lleve backticks: la variante sin backticks queda `allowed`, la variante con backticks alrededor del comando devuelve `Recursive delete`. El bloqueo se disparó tres veces seguidas mientras se redactaba esta misma entrada, incluida la que intentaba documentarlo.

**Por qué NO se arregla ya:** el hook falla hacia el lado seguro y el workaround (sacar los backticks) es trivial. Parsear heredocs para distinguir texto de comando no es barato, y un parser incompleto de shell es peor que el falso positivo actual — daría una falsa sensación de precisión sobre una superficie que hoy es deliberadamente conservadora.

**Acción:** ninguna por ahora. Si el falso positivo se vuelve frecuente al documentar, la salida más barata es un `allow_patterns` en el config del profile, no tocar `_COMMAND_START`.


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

- ~~**Legacy ADR-010 Ollama backend**~~ — cerrado. Promovido por [ADR-033](adrs/033-llm-backend-abstraction.md) y hecho utilizable por [ADR-039](adrs/039-role-routed-inference.md) (ruteo por rol).
- **Legacy ADR-013 Proactivity levels per profile** — promover o descartar. Criterio: si agregás un tercer perfil, promoverlo; si no, descartar.
- **ADR-018 implementation epic** — trigger cumplido 2026-08-17. El segundo extension point no es un tipo de plugin nuevo: es la unificación de los cinco que ya existen, propuesta en [ADR-035](adrs/035-capability-registry.md). El consumidor concreto que lo justifica es el pane de configuración de la TUI ([`designs/2026-08-17-config-tui-design.md`](designs/2026-08-17-config-tui-design.md)), que sin registry necesitaría seis code paths.
