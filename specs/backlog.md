# lazy-harness backlog

Issues y mejoras pendientes. Este archivo es **interno** (no se publica al sitio MkDocs); el roadmap público vive en `docs/roadmap.md` y solo contiene los temas comprometidos a alto nivel.

Última revisión: 2026-09-15 — `/coherence-audit` antes de cortar 0.67.1. Piece A 39/39 (eran 38/38; #300 sumó uno). Piece B: siete hallazgos, **todos de prosa, ningún defecto de código**. El modo de falla dominante fue nuevo y vale como regla: **una corrección de conteo aplicada a una mitad del párrafo y no a la otra** — #300 corrigió «siete» a «ocho» en el encabezado y el cuerpo de su entrada y dejó vivo un «los siete» tres párrafos más abajo. Los otros seis: el roadmap era la única de las cuatro superficies que no registraba #295 (lo llevaban el backlog, ADR-031 y el design), que es justo la mitad que `/coherence-audit` **no** cubre y por la que el no-negociable #6 la nombra aparte; `docs/how/hooks.md` se contradecía a sí misma tras #300, nombrando `~/.claude/queue/` fijo en `:175,179` y «ningún path fijo» en `:784`; ADR-008 nombraba tres paths fijos que el código resuelve desde el runtime dir del agente **global**, nunca del profile; y §Done no tenía entrada para #298 ni #300. Cerrados todos en este PR, así que **no se appendeó nada a `failures.jsonl`**: el paso 4 del comando pide un record por hallazgo *no resuelto* y no quedó ninguno. Revisión previa: 2026-09-15 — `/coherence-audit` antes de cortar 0.67.0. Piece A 38/38 (eran 31/31; #296 sumó 7). Piece B: un hallazgo alto con defecto de código —`snapshot_targets` resolviendo el agente global mientras el deploy lo resuelve por perfil, la invariante que [ADR-041](adrs/041-multi-agent-hook-contract.md) §3 declaraba y que #292 dejó incumplida al mover uno solo de los dos readers— más cinco medios y tres bajos, todos de prosa. **Cuarta reincidencia** del patrón «el PR toca `src/` y `tests/` y ningún spec»: `grep -rn '#292|#294|#295|#296|0.67.0' specs/ docs/` devolvía cero. Cerrados en #297: el defecto y su test de acuerdo (que nunca seteaba un `agent` por perfil, así que pasaba con y sin el mecanismo), el párrafo *Known exception* de ADR-041, la `Evolution` de ADR-031 con el filtro por signals, la línea de Theme 5 y la de CI en el roadmap, las dos salidas nuevas del deploy en `docs/reference/cli.md`, la tercera narrowing del gate de `CLAUDE.md`, las cinco entradas de §Done de esta release, la mudanza `monitoring/hook_signals.py` → `hooks/signal_gaps.py` y la quinta superficie del gate (`docs/roadmap.md`), que el test de coherencia contaba y no cubría. Revisión previa: 2026-09-15 — `/coherence-audit` antes de cortar 0.66.0. Piece A 31/31; Piece B, doce hallazgos. A diferencia del step 3, los dos PRs de esta release (#289, #290) **sí** tocaron `specs/` en el mismo commit — #290 anotó ADR-004, ADR-024 y ADR-032 y reescribió la decisión 4 del diseño. El modo de falla que queda es más fino y vale como regla: **la nota `Evolution` se acotó al bloque de código citado y dejó viva la prosa de *Consequences* que describe el camino de ejecución**, y el grep que encontró los tres ADRs fue por el *símbolo* removido, no por el mecanismo — así que [ADR-006](adrs/006-hooks-subprocess-json.md), que describe el contrato de hooks entero sin nombrar ese símbolo, fue el único de los cinco que no se abrió, y era el que tenía cuatro claims muertos. Cerrados en esta pasada: el bloque de status del diseño multi-agente (que se contradecía a sí mismo sobre el step 4), la sección `Evolution` de ADR-006, las notas de ADR-004/024/019/032, `[profiles.<name>].agent` sin documentar en el config reference desde 0.65.0, la sección `Hook signals` de `lh doctor` sin documentar, y la entrada faltante del step 1 en §Done. **Los doce hallazgos NO se appendearon a `failures.jsonl`** — decisión explícita, quedan para revisión humana, así que el compound loop no los va a ver. Revisión previa: 2026-09-14 — `/coherence-audit` antes de cortar 0.65.0. Piece A (los tests de `tests/docs/`) 31/31; Piece B, nueve hallazgos de drift semántico, todos del mismo modo de falla: **los tres PRs del step 3 (#282, #283, #285) tocaron cero archivos bajo `specs/`**, así que cada referencia a `deploy/engine.py` que el step 3 movió al adapter quedó colgada. Cerrados en esta pasada, más el hueco de roadmap que el audit levanta aparte: el diseño multi-agente no figuraba en `docs/roadmap.md`, §Done no tenía los steps 0 ni 3, y la *Implementation sequence* no marcaba progreso. Tercera reincidencia del patrón «PR toca `src/` y `tests/` y ningún spec» — ver la entrada del step 2 más abajo, que ya se quejaba de él. Revisión previa: 2026-09-12 — pasada de coherencia sobre `docs/` y `specs/`: cuatro ADRs (035, 037, 038, 039) estaban `proposed` con el código shippeado y se pasaron a `accepted`; nueve claims de `docs/` describían comportamiento que el código no tiene. Revisión previa: 2026-09-10 — `/coherence-audit` cruzó 34 ADRs `accepted` contra su código. Cinco items que figuraban abiertos resultaron implementados: tres desde el 2026-08-17 (PRs #167 y #168) y dos del mismo día en que se anotaron. La deriva restante quedó en `failures.jsonl` bajo el tag `coherence-audit`, para revisión humana. Revisión previa: 2026-08-17 — análisis de los tres ejes de refactor (paridad Linux, capability registry, TUI).

---

## Done

- [x] **El gate del step 4 pasó y ADR-041 quedó `accepted`** — corrido el 2026-09-15 contra el binario instalado desde el tag `v0.67.1`, nunca desde un worktree, y con el fix grepeado en site-packages antes de correrlo: el exit 0 del `uv tool install` no prueba nada, y el receipt de `uv` tenía `rev=v0.67.0` pinneado, así que un `--reinstall` pelado hubiera reinstalado la versión rota en silencio. El discriminador barato del fix es la **firma** `_log_block(decision, command, profile)`, que no puede existir sin el cambio de call site. Resultado: `PASS`, exit 0; el stdout quedó guardado como `run-0.67.1.log` al lado del script, porque el dir de la corrida (`run-f7gate178948476834223`) sólo tiene el estado generado y no preserva ni la salida ni el exit code. **El pase es compuesto y así hay que leerlo**: la corrida 1 (contra 0.66.0) falló la aserción C y sacó tres defectos (#292); la 2 (contra 0.67.0, `/tmp/step4-gate-rerun.md`) fue el **gate completo** —A, B y C1/C2/C3 pasan por `codex exec` real— y falló por la regla que ninguna corrida había mirado hasta ahí, el aislamiento del log (#300); la 3 es la reacotada a esa mitad sola, contra 0.67.1, con A/B/C explícitamente **no** recorridas. Ningún binario pasó las cuatro propiedades en una sola corrida, y #300 tocó justo los dos hooks que A y B ejercitan: que eso no los haya movido lo cubre `test_hook_log_profile_isolation.py` por el entry point real, no una cuarta corrida. **Cinco defectos de producción salieron de las corridas, todos de la misma forma** —una respuesta derivada del agente global donde la fuente es el agente del profile—: tres en #292 y dos en #300. Un sexto de esa forma, #297, lo encontró `/coherence-audit`, no una corrida. #294 y #296 caen en la misma ventana y **no** son resultados del gate: el primero salió implementando el adapter (`_planner_for` llamando `agent.name()` sobre un `@property`, con cuatro tests afirmando ese rechazo y los cuatro pasando porque los dos dobles declaraban `name()` como método), el segundo es un test flaky y un gate de formato que reproducen en `main`. El gate **discrimina**: sale 1 contra 0.67.0 y también contra un shim que arregla sólo `pre-tool-use-security`. Lo que el pase **no** cubre, dicho para que no se lea de más: son **dos** builtins aserteados y no tres —`stop-verify-guard` es migrado pero no escribe `hooks.log`, su único sink es la MetricsDB acotada por `LH_DATA_DIR`— y de los quince unmigrated se **cuentan** los ocho que escriben `hooks.log`, no se fallan: el known-gap list del script nombra siete de esos ocho y filtraron 28 líneas en la corrida que pasó. El gate vive en `/tmp/f7-gate/`, fuera del repo, así que no es reproducible por CI — vale registrarlo, no se toca acá.
- [x] **0.67.1 cortada con el alcance del fix calificado a mano** — release-please genera las notas desde el subject del commit, que dice «route hook logs to the profile the hook ran under» sin decir *cuáles*. Un review adversarial ya había falsificado esa lectura amplia, así que el calificador entró en `CHANGELOG.md` y en el body del PR —las dos mitades, porque el body es lo que termina en el GitHub Release y el changelog es lo que queda en el repo—: la ruta por profile alcanza el log de arranque de `context-inject` y el de bloqueo de `pre-tool-use-security` cuando falta la env var del adapter; los otros ocho builtins que loguean y el worker del compound loop siguen resolviendo global. PR #299, mergeado el 2026-09-15; corta 0.67.1.
- [x] **Hook logs ruteados al profile bajo el que corrió el hook** — F7 del gate del step 4: los builtins resolvían el dir de `hooks.log` desde un `get_agent("claude-code")` hardcodeado, así que un hook invocado con `--profile <p>` escribía su línea de auditoría en el dir que nombraba el agente **global** — otro profile, vivo. Cerrados los dos que tenían el profile en scope: `_log_block` de `pre-tool-use-security` vía `event.profile`, y la línea de boot de `context-inject` cargando config antes de escribir. Un review adversarial falsificó la tesis de que los unmigrated estuvieran fuera del contrato por construcción, midiendo `lh hook compound-loop --profile gate` escribiendo en el dir global bajo un profile Codex. Los ocho restantes quedan abiertos en *Ocho builtins resuelven su `hooks.log` globalmente*, más abajo en este archivo, con el alcance escrito como decisión y no como exclusión estructural. Test de integración que afirma **ausencia** además de presencia: la presencia *específica* sí detectaba el defecto —`session-context: fired` faltaba en el dir del profile, y el log de security ni existía ahí— pero una presencia *débil*, «alguna línea de context-inject está», pasaba igual gracias a `injected`, que ya resolvía por profile. La aserción de ausencia es la que cierra ese hueco. PR #300, mergeado el 2026-09-15; entra en 0.67.1.
- [x] **Gates de `CLAUDE.md`: tres fusionados en uno, dos incorporados** — verificado contra `git show 2a3226e -- CLAUDE.md`, no contra el título. Los que se fusionaron entre sí son los **tres** de respuesta única: config-derived-path, static-list-mirroring-a-directory y widening-a-type, ahora «One answer lives in one importable place; every path naming it is derived from it or audited against it». Silent-dropout entró como gate **propio** («A config schema accepting user-supplied identifiers validates them explicitly and names what it ignored») y probe-first como **cláusula** del gate de comportamiento, no fusionados entre sí. La poda fue 11742 → 10988 bytes: el archivo ya estaba bajo el tope de 12 KB, así que ganó margen, no lo recuperó. PR #298, mergeado el 2026-09-15; entra en 0.67.1.

- [x] **`uv run` sin `--frozen` descartaba el lockfile entero** — medido el 2026-09-14: un `uv run` posterior a cualquier edición bajo `src/` descarta `uv.lock` y escribe uno reducido, de 54 paquetes a 16, sin `revision = 3` y sin ningún `upload-time` (817 líneas borradas). `uv run -v` lo dice: `Ignoring existing lockfile due to mismatched dev dependencies`. Editar un fuente y correr los tests **es** el ciclo TDD de este repo, así que todo worktree acumulaba un lock degradado que el próximo commit podía arrastrar: tres agentes lo dejaron sucio en una sola sesión y ninguno lo reportó. Cerrado poniendo `--frozen` en las 14 invocaciones que prescriben las superficies de automatización (`.claude/commands/`, los dos workflows, el PR template) y sosteniéndolo con `tests/docs/test_uv_frozen_coherence.py`, que falla en las dos direcciones. `--group dev` también lo evita; declarar `[tool.uv] default-groups` **no** — medido, no supuesto. Es un defecto distinto del de `release-please` más abajo, que describe la línea de versión atrasada ensuciando el árbol *incluso con* `--frozen` vía el install editable: ese reescribe una línea, este descartaba el archivo.
- [x] **`generate_hook_config` / `generate_mcp_config` fuera del Protocol** — el step 3 los desplazó de la ruta de deploy y el step 4 los borró de la declaración. Salieron de `AgentAdapter` y del adapter nulo; sobreviven privados dentro de `ClaudeCodeAdapter` como `_generate_hook_config` / `_generate_mcp_config`, llamados desde `_plan_settings` y `_plan_mcp`. La condición de arranque se cumplió al pie de la letra: el `CodexAdapter` throwaway es el segundo implementador que valida la forma que queda, y su config —`hooks.json`, no `config.toml`— es justamente la que un `dict` no puede expresar. Identidad byte a byte de Claude Code intacta (`tests/goldens/config-deploy/` sin tocar). PR #290, mergeado el 2026-09-15; entra en 0.66.0.
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
- [x] **PreCompact context injection — el canal, no el parser** — el builtin `pre_compact.py` respalda el transcript y emite contexto por **texto plano** en stdout, que el ejecutor de `PreCompact` junta y le pasa al summariser como `newCustomInstructions`: no hay variante `hookSpecificOutput` para ese evento y un payload JSON falla la validación de schema, lo que marca el hook como fallado y descarta su salida (ADR-036 D2; esta línea decía `hookSpecificOutput.additionalContext` y era de antes de ese hallazgo). Lo que efectivamente viaja por ese canal son los tails de `decisions.jsonl` y `failures.jsonl` (`build_memory_tails`), que no leen el transcript. Los hard constraints del `CLAUDE.md` los re-inyecta Claude Code nativamente post-compact como system-reminder. **La mitad derivada del transcript —tasks y archivos— nunca funcionó, ni una vez**: hasta el 2026-09-15 esta entrada afirmaba que `pre_compact.py` «ya re-inyecta tasks (últimos user_msgs) + archivos (`file_path` de tool_use blocks)» y cerraba con «no queda gap accionable». Las dos mitades de esa frase eran falsas y se midieron falsas tres veces; el gap está abierto en *`parse_transcript` lee un shape de transcript que Claude Code no emite*, más abajo.
- [x] **PreToolUse security hook** — blocks destructive filesystem/git/sql/terraform commands + credentials reads + forced secret commits, with per-profile `allow_patterns` escape hatch (feat/security-hooks-cluster)
- [x] **PostToolUse auto-format hook** — runs `ruff format` on `.py` edits/writes fail-soft (feat/security-hooks-cluster)
- [x] **PostCompact context re-injection** — cerrado por remoción. El hook `post-compact` de ADR-020 existió con su chequeo de frescura de 5 minutos, pero [ADR-036](adrs/036-compact-hooks-use-real-channels.md) lo borró el 2026-08-18: el ejecutor de `PostCompact` solo devuelve un mensaje al usuario, así que un hook ahí no puede alcanzar al modelo. La continuidad post-compactación vive en `context-inject`, que corre en el `SessionStart` que sigue.
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
- [x] **Memory stack glue layer** — `lh memory consolidate` (propose-only distiller) + `lh memory legacy-check` + `pre-tool-use-memory-size` warning hook (ADR-030 G1/G2/G4). G7 se escribió como `lh memory cross-profile-check`; shippeó como `legacy-check` porque el traslado de la memoria al knowledge store, keyeada por remote, eliminó la divergencia entre perfiles que ese componente iba a observar.
- [x] **Metrics ingest pipeline + sinks** — session-rollup ingestion, `[metrics].sinks` with `sqlite_local` and `http_remote`, opportunistic outbox drain, `lh metrics drain` / `status` (design 2026-04-14)
- [x] **PostToolUse sync-claude** — regenerates segmented `CLAUDE.md` (head/tail/common) when a profile segment is edited; fail-soft
- [x] **Rename a lazy-harness** — repo, package (`lazy_harness`), CLI (`lh`), docs site (`lazynet.github.io/lazy-harness`)
- [x] **Docs coherence pass 2026-05-20** — `lh memory` + `lh knowledge` subcommands completos en CLI reference, hooks documentados (`pre-tool-use-memory-size`, `post-tool-use-sync-claude`), `claude-md.proposal.md` + `grades.jsonl` documentados en compound-loop how page
- [x] **Compound-loop insight capture + delta-by-index** — `★ Insight ─` blocks captured verbatim via regex pre-LLM, gate-bypass when insights present, hash-based dedup, per-session message-index cursor for delta scans (`memory/insights/.cursor.json`). 12 tests TDD. Closed both gate-out (short sessions) and tail-of-20 (long sessions) loss paths from the design [`specs/designs/2026-04-13-compound-loop-insight-capture.md`](designs/2026-04-13-compound-loop-insight-capture.md).
- [x] **Backends systemd y cron del scheduler** — ADR-013 completo. `SystemdBackend` escribe `.timer` + `.service` bajo `$XDG_CONFIG_HOME/systemd/user/` y chequea lingering; `CronBackend` escribe un bloque delimitado preservando las entradas del usuario. Traducción compartida en `scheduler/schedule.py`, que rechaza en vez de aproximar.
- [x] **`agent_dispatched` en `loop_events`** — emitido por el worker del compound-loop con modelo y `subagent_type` en `detail`, idempotente ante reproceso vía `clear_agent_dispatches`. Verificado end-to-end contra `jq` como fuente independiente: 153 dispatches en septiembre, 344 histórico, coincidencia exacta. Baseline al shippear: 150 dispatches en 873 sesiones, todos `general-purpose`.
- [x] **Reconcile y Decay del stack de memoria** — ADR-040 accepted; `lh memory decay` (marca `status: superseded`, nunca borra) y `lh memory reconcile` (schema drift determinístico, contradicciones opt-in vía `--check-contradictions`), ambos propose-only por default como `consolidate`. Dry-run al shippear: 1128 de 5954 learnings candidatos, drift real en 5 repos incluido el store del propio `lazy-harness`.
- [x] **Rightsizing del contrato del agente** — hook `pre-tool-use-memory-size` extendido a `CLAUDE.md` con umbral propio, `lh memory rightsize` (read-only, descubre por filesystem bajo `roots`, no por presencia en el store) y el skill `rightsize-claude-md`. Ejecutado sobre 7 repos el 2026-09-10: de 14/36 contratos sobre umbral a 8/36, y de esos 8 seis son decisiones deliberadas (dos `Archon` que vienen de upstream, `lazy-ai-tools` 579 bytes arriba a propósito por tres gotchas de fallo silencioso, y tres archivos con los bytes ya bajo el techo).
- [x] **`uv` viejo de Langflow anteponiéndose en el PATH** — `~/.langflow/uv/env` exportaba `PATH="$HOME/.langflow/uv:$PATH"` con un uv 0.6.17 de abril 2025 que no entiende `uv run --group` y reescribe `uv.lock` en formato viejo. Rompía el gate de docs de forma intermitente y degradó dos `uv.lock` el 2026-09-10. Deshabilitado en `~/.config/zsh/10-darwin.zsh`, persistido con `chezmoi re-add`, verificado en ambas direcciones.
- [x] **Traducción de schedule que se niega en vez de adivinar** — `scheduler/schedule.py` con `parse_cron`/`render_launchd`/`ScheduleTranslationError`; `_cron_to_calendar` y `_cron_to_interval` borrados (ADR-013 D4, PR #168, 2026-08-17). Verificado el 2026-09-10 contra las 7 formas comunes: diaria, cada N horas, semanal, mensual y cada N minutos traducen; listas y rangos levantan, porque launchd no puede expresarlos. `lh status cron` muestra el schedule real y `selftest` gana el check `units-stale`. El backlog lo listó como ALTA abierta durante tres semanas después de estar cerrado.
- [x] **`lh deploy` default hooks merge** — `DEFAULT_HOOKS` literal in `deploy/defaults.py` + `merge_with_defaults` pure function; per-event override via config.toml (`scripts = []` opts out); framework-owned `settings.json[hooks]` with backup + warning when manual entries are clobbered (ADR-031, 11 tests TDD). Also fixed `ClaudeCodeAdapter` missing `post_compact → PostCompact` mapping. Closes the 2026-04-17 partial-config drift and makes built-ins out-of-the-box.
- [x] **`stop-verify-guard` desplegado y wireado** — los cuatro pasos del gate binary-first, cerrados el 2026-09-11 en laptop y en el CT `agents`: release 0.57.1 y `uv tool install --reinstall`; `record-verify` grepeado en site-packages (`cli/metrics_cmd.py:220`) e invocable; el skill `verify-before-done` lo llama como último paso (línea 61 de los dos `SKILL.md` del profile); y recién entonces `stop-verify-guard` en `[hooks.session_stop]`, visible en el `Stop` de los cuatro `settings.json`. El guard ya no es un nag: su emisor está desplegado.
- [x] **El guard de paths secretos estaba inerte: el matcher desplegado no lo alcanzaba** — `pre-tool-use-security` inspecciona `Bash` más `Read`/`Edit`/`Write`/`NotebookEdit`, pero su entrada en `_BUILTIN_HOOKS` no declaraba `matcher`, así que heredaba el default del evento (`Bash`) y Claude Code nunca lo invocaba en un `Read`. Cerrado declarando `matcher="Bash|Read|Edit|Write|NotebookEdit"`. Lo que faltaba de verdad era la relación entre las dos puntas: cada builtin que gatea por `tool_name` ahora publica `INSPECTED_TOOLS` y lo usa en su propio gate, y `tests/unit/test_hook_matcher_coverage.py` sostiene el matcher desplegado contra ese conjunto. Verificado en ambas direcciones: sin el matcher, dos de los tres tests fallan con `matcher 'Bash' never reaches ['Edit', 'NotebookEdit', 'Read', 'Write']`. Desplegado el 2026-09-11 en las dos máquinas: release 0.57.1, `uv tool install --reinstall`, grep a site-packages y `lh deploy`. Verificado end-to-end en laptop y en el CT `agents` — un payload de `Read` contra `**/secrets/**` sale exit 2, uno a un path normal exit 0. El CT ya tenía el matcher ancho antes del fix y la laptop no: `lh deploy` lo pisaba solo donde había corrido después de chezmoi.
- [x] **`save_config` destruía config (51 claves) + tres claves de `[context_inject]` ignoradas en silencio** — read-modify-write sobre TOML crudo (`tomlkit`) en vez de completar el serializer, per D5 de [`designs/2026-08-17-capability-registry-design.md`](designs/2026-08-17-capability-registry-design.md) (commit `56429ad`, PR #167). Selftest `check_config_round_trip` registrado. Esta entrada había quedado listada como ALTA abierta pese a estar mergeada desde el 2026-08-17; el backlog no se había actualizado. Reconciliado el 2026-09-10 agregando además `tests/unit/test_config.py::test_save_config_round_trip_preserves_every_key_of_the_live_config` y `::test_context_inject_switches_survive_round_trip_against_the_live_config`, que corren el ciclo completo contra una copia del `config.toml` real de la máquina (nunca contra el archivo real) en vez de solo contra el fixture sintético `_FULL_CONFIG`.
- [x] **Ollama como backend para compound-loop** — cerrado. [ADR-033](adrs/033-llm-backend-abstraction.md) promovió la idea del legacy ADR-010 a un Protocol provider-agnostic (implementado 2026-06-11) y [ADR-039](adrs/039-role-routed-inference.md) la hizo utilizable: el ruteo pasa a ser por rol (`[llm.roles]` → `run_inference`), así el modelo local atiende trabajo barato sin quedarse también con el destilado y el grading. Vivió como MEDIA abierta con `**Resuelto:**` en su propio cuerpo; reconciliado el 2026-09-12.
- [x] **`_is_harness_owned` identificaba por texto de comando — step 0** — el clasificador matcheaba un path de builtins (`lazy_harness/hooks/builtins/`) contra comandos que `hook_command` ya había dejado de emitir, así que clasificaba **cada** hook del harness como ajeno; un segundo guard en el merge tapaba el duplicado sólo mientras las dos strings fueran byte-idénticas, lo cual deja de valer en cuanto el comando cambia de forma — y cambia en cuanto el runner toma `--profile`. Cerrado identificando por nombre canónico dentro de `lh hook <name>`, con un test que redeploya después de un cambio de formato de comando y asserta que no hay duplicado. Shippeado en 0.60.0 (`968195e`). Es el defecto que [ADR-041](adrs/041-multi-agent-hook-contract.md) describe en su Context y el que todo step posterior habría compuesto. La función se mudó a `agents/claude_code.py:191` con el step 3, junto al merge al que pertenece.
- [x] **Los tipos del contrato congelados en `agents/base.py` — step 1** — el vocabulario que todo adapter traduce: `Verdict`, `Operation`, `Signal`, `FileEdit`, `ToolCall`, `HookEvent`, `HookDecision`, `HookOutput`, `HookSupport`, `ConfigArtifact` y `WriteOp`, más `hook_events()` / `parse_hook_input()` / `format_hook_output()` sobre `AgentAdapter`. `ClaudeCodeAdapter` los implementa como pass-through y el mapeo de eventos pasa a vivir en **una** tabla en vez de dos literales, que es lo que después dejó derivar `supported_hooks()` en vez de declararlo aparte. Dos decisiones que se tomaron acá y sostienen todo lo de arriba: `HookDecision.verdict` default `None` y no `ALLOW`, así una abstención no puede leerse como aprobación — un guard que no reconoce un comando no lo aprueba —; y `HookSupport` declara un **conjunto** de verdicts en vez de un `can_block: bool`, gateado a los verdicts observados contra binarios reales, porque un verdict que el agente no honra no falla ruidosamente. Shippeado en 0.61.0 (PR #266, `30d0954`). Contra TDD estricto: `tests/unit/test_agent_contract.py`, 602 líneas, en el mismo PR — la revisión previa del diseño decía "type-check only" acá y contradecía el non-negotiable del repo.
- [x] **`lh doctor` nombra los signals que un hook necesita y el agente no entrega — prerequisito del step 4** — el gate del step 4 tiene que *observar* que `stop-verify-guard` queda inerte en un agente que no provee `GOAL_STATUS`, y nombrarlo como missing signal; sin esa línea el gate no es performable. `monitoring/hook_signals.py` —desde #295 `hooks/signal_gaps.py`, porque el deploy pasó a ser su segundo lector— cruza los signals que cada hook declara (`BuiltinHookSpec.signals`) contra los que el `TranscriptReader` del perfil sabe entregar, resolviendo los hooks desplegados por `selected_profiles` + `merge_with_defaults` — las mismas funciones que usa `deploy/engine.py`, no una relectura de `DEFAULT_HOOKS`. Un adapter sin reader no entrega ninguno: faltan todos los declarados, y ese caso no revienta. **Los dos estados de no-soporte no se colapsan**: un evento ausente de `hook_events()` significa que no se instala nada y no corre nada — espera el vocabulario de eventos del agente — y se saltea acá en vez de reportarse como signal faltante; la línea que lo cubra es el step 10. Es la línea única que el diseño le adelanta al step 4, **no** la superficie completa de `hook_events()` (verdicts honrados por evento, operaciones cubiertas por hook), que sigue en el step 10. PR #289, mergeado el 2026-09-15; entra en 0.66.0.
- [x] **Deploy de config a través del adapter — step 3, tres PRs** — el vertical slice que el diseño multi-agente pone antes del gate. `lh deploy --profile <name>` acota un deploy a un solo perfil, con el link global siguiendo al perfil default y nada más (#282); `ClaudeCodeAdapter` implementa `ConfigPlanner` — `config_targets()` nombra `settings.json` y `.claude.json`, `plan_config()` mergea y devuelve texto final (#283); y `deploy/engine.py` pasa a hacer sólo I/O: descubre, lee, planifica una vez por perfil y aplica los `WriteOp`, borrando su copia duplicada del merge — `_merge_hook_blocks`, `_is_harness_owned`, `_normalize_entry`, `_owned_binaries`, `_entry_commands` (#285). Un adapter que no satisface `ConfigPlanner` se rechaza antes de la primera escritura, no a mitad del deploy. Identidad de bytes anclada en `tests/goldens/config-deploy/`, capturada del engine **antes** del refactor: los tests de `test_config_planner.py` que cruzaban adapter contra engine quedaron tautológicos al unificarse las dos implementaciones, y un golden pre-refactor es lo único que sigue probando algo. Shippeado en 0.65.0. Deja el gate del step 4 — el `CodexAdapter` throwaway contra un perfil descartable — como lo único que falta antes de congelar el contrato y pasar ADR-041 a `accepted`.
- [x] **`TranscriptReader` de Claude Code — shippeado en el step 2** — `Signal`, `TranscriptEvent`, `TokenUsage`, `GoalStatus` y el Protocol `TranscriptReader` viven en `agents/base.py`; `ClaudeCodeAdapter.read()` los emite y su `signals()` declara las cuatro (`agents/claude_code.py:546-548`, movido
desde `:367-369` cuando el step 3 insertó los helpers de merge arriba de la clase); `_shared.transcript_reader(profile)` resuelve el reader por perfil y devuelve `None` cuando el adapter no lo implementa; y `stop_verify_guard._goal_declared` consume `Signal.GOAL_STATUS` en vez de escanear el `attachment` a mano (PR #273, 2026-09-14). Cierra el prerequisito del step 4 y deja el step 12 como lo que siempre fue: los readers de los otros agentes. Vivió como única ALTA abierta hasta el 2026-09-14 porque el PR tocó `src/` y `tests/` y ningún spec — el mismo patrón que ya habían tenido la traducción de schedule y `save_config`.
- [x] **El chequeo de coherencia del CLI no miraba flags** — el walk paraba en el primer token con `-`, así que un flag inventado en `docs/` pasaba verde. Cerrado el 2026-09-14: las dos direcciones comparten un solo `_walk_command_path`, cuyo `stop` distingue "nombre que no resuelve" de "tokens que dejaron de ser clasificables", y `find_unknown_lh_flags` resuelve cada flag contra las opciones del comando que lo precede — **strict**, que es la semántica de click (`lh status --version` es `No such option`). Medido sobre `docs/**` antes de escribirlo: 75 invocaciones con flags, 104 tokens, 38 distintos, todos long-form; strict y lax dan idéntico hoy (97 known), así que la regla correcta no cuesta ningún falso positivo. Los tres bordes que el item pedía decidir quedaron ignorados a propósito, cada uno con su test: lo que va después del `--` de click, los flags que siguen a un `<placeholder>` que frenó el walk (`lh config <feature> --init`, donde `--init` existe pero sólo en las hojas), y los flags de un comando que no resuelve, que el scan viejo ya reporta. Verificado en las dos direcciones: con `lh deploy --dry-run` reinyectado a mano el scan nuevo falla y el viejo pasa verde. Primer hallazgo del checker: `docs/how/hooks.md` documentaba `lh hooks run my_hook --event session_start`, que sale exit 2 con `No such option: --event` — `EVENT` es posicional. Aparte, el help de `--memory-dir` apuntaba al runtime dir: era un solo `_MEMORY_DIR_OPTION` compartido por seis comandos, no dos docstrings.
- [x] **El agente resuelto por perfil en el runner, el symlink global y el runtime dir — step 4, tres defectos de una misma forma** — los tres los encontró la corrida del gate del step 4 el 2026-09-15, corriendo las dos mitades y comparando bytes, porque ningún test invocaba ambas. (1) El runner resolvía `[agent].type` mientras el deploy resolvía el agente del perfil, así que un perfil con `agent = "codex"` recibía su config en forma de Codex y sus hooks contestados en el wire format de Claude Code — `systemMessage` top-level y exit 2, que `CodexAdapter` no emite. (2) `deploy_claude_symlink` resolvía `[agent].type` y recién después pedía `global_config_link()`, así que `lh deploy --profile <codex-throwaway>` repuntaba el `~/.claude` vivo a un home de Codex; `deploys_global_link` no es la guarda ahí —pasa, porque el throwaway *era* el perfil default—, la guarda es el `None` de `CodexAdapter` y el código nunca se lo preguntaba. (3) `agent_runtime_dir` caía a `~/.<agent name>` cuando la env var del adapter no estaba en el subproceso del hook y su link global era `None`, escribiendo dentro del `~/.codex` real que ese `None` existía para proteger. Cerrado resolviendo por `agent_for_profile` en los tres, con `agent_runtime_dir` tomando el `config_dir` del perfil antes de los dos fallbacks globales. PR #292, mergeado el 2026-09-15; entra en 0.67.0.
- [x] **El rechazo de un adapter sin `ConfigPlanner` nunca llegaba: `name` es property, no método** — `_planner_for` llamaba `agent.name()`, pero `AgentAdapter.name` es `@property` en el Protocol y en todos los adapters shippeados, así que la promesa del step 3 —«un adapter que no satisface `ConfigPlanner` se rechaza antes de la primera escritura»— moría con `TypeError: 'str' object is not callable`, que el `except ConfigPlannerRequiredError` de `deploy_cmd` no atrapa. El usuario veía un traceback de Click en vez del mensaje que nombra perfil y adapter. **Cuatro tests aseguraban ese rechazo y los cuatro pasaban**, porque los dos dobles declaraban `name()` como método — moldeados alrededor del call site con el bug en vez de alrededor del Protocol; todos los demás dobles de la suite usan `@property`. Cerrado corrigiendo ambos y anclando el rechazo en el sentinel `NullAdapter` shippeado, asertando los atributos estructurados del error y no un substring de su mensaje. Es el gate «un doble moldeado alrededor del call site con el bug falla igual, en silencio». PR #294, mergeado el 2026-09-15; entra en 0.67.0.
- [x] **El deploy saltea —y nombra— los hooks cuyos signals el agente del perfil no entrega** — `BuiltinHookSpec.signals` existía para impedir que un hook se instalara en un agente que no puede alimentarlo (`stop-verify-guard` en Codex corre, no encuentra goal marker, concluye que no había nada que verificar y pasa: verde porque no puede fallar), pero **ningún camino de código lo hacía cumplir**: la declaración era inerte y `collect_hook_signal_gaps` reportaba el gap sólo después de la escritura. `_hook_entries_for` ahora actúa sobre ese gap, y la regla decisoria se mudó de `monitoring/hook_signals.py` a `hooks/signal_gaps.py` en vez de re-derivarse del lado del deploy, así que `lh doctor` reporta exactamente lo que el deploy rechaza — un integration test invoca los dos comandos y asserta que concuerdan en ambas direcciones. **Cada omisión se nombra en el output antes de ser una ausencia en el artefacto** — un hook que desaparece sin anunciarse es el mismo silencio con la otra máscara — y los tests assertan ese texto, no sólo la entrada faltante. Esto convierte la fórmula de [ADR-031](adrs/031-default-hooks-merge.md) en dos etapas y narrowea un override explícito del usuario: anotado en su sección `Evolution`. Avisa además, sin bloquear, cuando un builtin `migrated=False` se despliega a un perfil cuyo agente no es Claude Code; un deploy default a un perfil Codex manda cuatro, y rechazarlos ahora dejaría ese perfil casi sin hooks — el step 5 migra los quince restantes. PR #295, mergeado el 2026-09-15; entra en 0.67.0.
- [x] **`ruff format --check` como cuarto check del gate, y el test de freshness que medía su propio runtime** — dos mitades en un PR. (a) `test_doctor_fails_when_the_drain_has_given_up_though_ingest_looks_healthy` asertaba «last enqueued 0s ago» contra una edad calculada como `now - created_ts` con las dos puntas leídas del reloj de pared y `_fmt_age` truncando la diferencia: era un presupuesto de un segundo sobre el setup del test más todo lo que `lh doctor` hace antes de llegar a la edad — 0.48s ya gastados en una máquina ociosa. Cerrado con un seam `_now()` y el `created_ts` pinneado al mismo instante congelado, de modo que la edad renderizada es 0 por construcción; despinnear cualquiera de las dos mitades lo hace fallar. (b) `ruff check` corre reglas de lint y deja el layout en paz, así que gatear sólo en él dejó driftear el formato hasta 44 archivos — un diff que sólo puede aterrizar encima del trabajo de otro. El reformat mecánico va en su propio commit (misma cuenta de tests antes y después, mismos ids) y el cuarto check entra en `/tdd-check`, `tests.yml`, el PR template y `CONTRIBUTING.md`. El conteo de cada superficie se **deriva** de los headings numerados del comando en vez de restatearse, así que un quinto check falla en cada superficie que no se puso al día. Grepear la enumeración en las dos direcciones encontró dos más: `docs/roadmap.md` nombraba `ruff` donde son dos checks, y `CONTRIBUTING.md` prescribía `uv run` sin `--frozen` porque le faltaba a `AUTOMATION_GLOBS`. PR #296, mergeado el 2026-09-15; entra en 0.67.0.
- [x] **El snapshot del deploy resolvía el agente global mientras el deploy lo resolvía por perfil** — la otra mitad de [ADR-041](adrs/041-multi-agent-hook-contract.md) §3, cuya *Known exception* pedía explícitamente que los dos readers **se movieran juntos**; #292 movió uno solo y dejó la invariante incumplida durante un release. `snapshot_targets` leía `[agent].type` una vez arriba de su loop de perfiles: con `agent = "codex"` en el perfil default reclamaba `.claude.json` y `~/.claude` —que `CodexAdapter` contesta `""` y `None`— y perdía el `hooks.json` que el deploy sí escribe, o sea un rollback que restaura o borra artefactos nunca desplegados y deja el que sí lo estaba. Cerrado pidiéndole los documentos de config al `config_targets()` del propio perfil (el mismo reader que usa `deploy_config`, lo que se lleva puesto también el `settings.json` hardcodeado) y el link global al adapter del perfil default. **El test que el docstring invocaba como garantía nunca seteaba un agente por perfil**, así que pasaba con y sin el mecanismo que decía cubrir: el override es lo único que vuelve no-vacua la aserción de acuerdo. PR #297; entra en 0.67.0.

---

## Open — Prioridad MEDIA

### `release-please` deja `uv.lock` un release atrás

**Por qué:** el bump de `uv.lock` es **inconsistente entre releases consecutivos**,
y la causa no está investigada. Medido el 2026-09-12 sobre los dos últimos:

| Release | Commit | ¿Tocó `uv.lock`? |
|---|---|---|
| v0.58.0 | `227a07b` | **no** — 4 archivos; el lock quedó diciendo 0.57.2 |
| v0.58.1 | `612f472` | **sí** — 5 archivos; el lock pasó a 0.58.1 |

Los dos releases salieron del mismo workflow y la misma config, y en los dos el
lock arrancaba en 0.57.2, así que la hipótesis obvia —que `extra-files` no lo
lista, cosa que es cierta— no explica por qué uno lo actualizó y el otro no.

La consecuencia cuando **no** lo bumpea no es el lock en sí —una línea, sin
efecto en la resolución— sino que cualquier `uv run` ensucia el árbol, incluso
con `--frozen`, porque el install editable reescribe esa línea. Eso ya costó un
`pull` con autostash en conflicto el mismo 2026-09-12.

**Acción:** primero reproducir y entender por qué difieren, mirando la versión de
la action de release-please en cada corrida. Recién después decidir si hace falta
un paso `uv lock` en el workflow. No tocar `extra-files` a ciegas: equivocarse acá
rompe releases, no docs.

### Otros dos eventos emiten JSON para un `hookEventName` que la unión no tiene

**Por qué:** la Task 1 del step 5 arregló `pre_compact`, que serializaba `hookSpecificOutput` para un evento sin variante en la unión. Cruzando la enumeración que [ADR-036](adrs/036-compact-hooks-use-real-channels.md) §Context leyó del bundle 2.1.234 contra `_HOOK_EVENTS` (`agents/claude_code.py:75-86`), quedan **dos** nombres nativos más que no figuran en esa lista: `PostCompact` y **`SessionEnd`**. El ADR nombra `PreCompact` y `PostCompact` explícitamente; que `SessionEnd` también falte no lo registró nadie.

**Fuente:** medido el 2026-09-15 contra el adapter ya arreglado, corriendo `format_hook_output` con `HookDecision(additional_context="ctx")` sobre cada evento cuyo `native_name` no está en la unión del ADR:

```
session_end   -> {"hookSpecificOutput": {"hookEventName": "SessionEnd", "additionalContext": "ctx"}}
post_compact  -> {"hookSpecificOutput": {"hookEventName": "PostCompact", "additionalContext": "ctx"}}
pre_compact   -> ctx
```

**Ninguno es una regresión viva**, y por eso es una entrada y no un fix: el builtin `post-compact` lo borró ADR-036 D1, y el canal de salida de `session-end` es log y nada más. Los dos son latentes. El mapeo de `post_compact` se mantuvo **a propósito** —«an operator may still attach their own hook to it», ADR-036 D1— así que un hook de operador que devuelva `additional_context` ahí come exactamente la falla que la Task 1 cerró, en silencio.

**Acción:** `post_compact` **no** se arregla con la misma rama de texto. ADR-036 §Context dice que su ejecutor devuelve `{userDisplayMessage}` y nada más, y que su salida llega a la terminal y nunca al modelo: lo que corresponde ahí es una **negativa**, no un canal. `session_end` hay que medirlo antes de decidir — si su ejecutor no lee stdout, la respuesta también es negarse. Las dos decisiones son distintas de la de `pre_compact` y ninguna está tomada. Precondición barata para las dos: volver a leer la unión contra un binario actual. El comentario de `claude_code.py:511-513` dice que las claves de `hookSpecificOutput` se verificaron contra **2.1.269** mientras la enumeración de variantes sigue siendo la de **2.1.234**; alguien leyó el bundle nuevo sin re-enumerar la unión.

### `parse_transcript` lee un shape de transcript que Claude Code no emite

**Por qué:** `hooks/builtins/pre_compact.py:63-64` hace `obj.get("role")` y `obj.get("content")` sobre el **tope** de cada línea del JSONL. Claude Code los anida un nivel adentro, bajo `message`: `{"type": "assistant", "message": {"role": ..., "content": [...]}, ...}`. Los dos guards que siguen (`:66` para el turno de usuario, `:69` para los `tool_use`) comparan contra el default `""`, así que ninguno matchea jamás y `parse_transcript` devuelve `([], [])` para todo transcript real. `build_summary` sobre eso da string vacío, y el summary que sale por el canal de `PreCompact` queda reducido a los tails de memoria.

**Fuente:** medido el 2026-09-15 sobre tres transcripts de producción de tres repos distintos, 3215 líneas útiles: `role` al tope = **0**, `message.role` = **1432**, y `parse_transcript` devuelve cero `user_msgs` y cero archivos en los tres. Corroborado por los artefactos, que es la medición que no depende de leer el código: los cinco `pre-compact-summary.md` del knowledge store —dos hosts de git, cinco repos, fechas de agosto y de septiembre— tienen exactamente dos encabezados, `## Recent decisions` y `## Recent failures`. Ninguno tiene `## Tasks in progress` ni `## Files worked on`.

**Por qué los tests no lo vieron:** las tres fixtures de transcript de `tests/unit/test_builtin_pre_compact.py` (`:28`, `:92`, `:232`) escriben entre las tres cuatro registros (`:30`, `:33`, `:95`, `:233`), todos `{"role": ..., "content": ...}` plano — el shape que el parser espera y que el agente no produce. Y ninguna aserción nombra `Tasks in progress` ni `Files worked on`: el test de `:60`, que es el que corre el hook entero por subprocess, solo afirma sobre los tails de memoria. Ningún test importa `parse_transcript`. Es el gate del `CLAUDE.md` en dos ejes a la vez — un doble con la forma del call site roto, y un test que pasa con y sin lo que dice cubrir.

**Acción:** leer `role`/`content` desde `obj["message"]`, y sostenerlo con una fixture derivada de un transcript real en vez de escrita a mano. Verificación en las dos direcciones, barata y obligatoria acá: con el fix, una fixture anidada produce `## Tasks in progress`; sin él, ese mismo test falla. Dos trampas que la medición deja escritas para que el fix no las descubra tarde. Primera: `message.role == "user"` **no** significa turno humano. De las 512 líneas con `role=user` en la muestra, **456 son `content: list[tool_result]`** — resultados de herramienta — y solo 47 son `str` más 9 `list[text]`. Un fix que no filtre eso convierte el 89% del canal en ruido, que es peor que el vacío de hoy. Segunda: el guard de `:66` exige `isinstance(content, str)`, y el turno humano viene en las dos formas, así que hay que cubrir `list[text]` además del `str`.

**Superficies que corrige el mismo PR.** Son tres y el gate del `CLAUDE.md` pide las tres en el mismo commit: esta entrada, el paso 3 de `docs/how/hooks.md` (corregido el 2026-09-15 por la ruta corta de docs, que describía la extracción como un hecho) y **[ADR-010](adrs/010-pre-compact-preservation.md)**, cuyo punto 2 de §Decision describe `parse_transcript` recolectando intents y archivos y cuyas §Consequences afirman que «the next session's handoff block often includes the pre-compact summary verbatim, giving the model the same file list and tasks». ADR-010 queda sin tocar acá a propósito: `specs/adrs/**` está excluido de la ruta corta de docs, así que gana su nota `Evolution` en el PR del fix, que toca `src/` y va por worktree igual.

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

**Señal determinística disponible, sin usar todavía:** `/goal <condition>` escribe sincrónicamente una entrada `{"type":"attachment","attachment":{"type":"goal_status",...}}` al transcript JSONL en el momento en que corre, así que está disponible durante el `Stop`. A diferencia de `goal_declared`, que es una clasificación LLM post-hoc del compound-loop, no requiere inferencia. Es más angosta —solo capta el uso explícito de `/goal`, no un criterio declarado en prosa— pero es exacta. Salió del trabajo de `stop-verify-guard`, ya cerrado.

**Acción:** fase 1 shippeó el 2026-09-10 — skill `verify-before-done` deployado y `[loops] inject_goal_prompt = true` aplicado; **la ventana de cuatro semanas cierra el 2026-10-08** contra el 17%. La cuarta pieza, el `Stop` hook `stop-verify-guard`, quedó deployada y wireada en las dos máquinas el 2026-09-11 (ver Done). Fase 4 queda reemplazada por `agent_dispatched`, ya en Done. Pendiente real, y único: leer la ventana cuando cierre y aplicar las kill criteria.

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

### `[hooks.*].external` no puede expresar un comando por perfil

**Por qué:** `external` es una lista global del `config.toml` y cada entrada es
un string literal que `_hook_entries_for()` en `deploy/engine.py:172` copia
**verbatim** a cada perfil (`HookEntry(command=ext.command, ...)`, el bloque comentado
"Third-party commands declared in config are emitted to every profile"), sin
expansión de paths ni de variables. Los scripts del harness sí se resuelven por
perfil, vía `hook_command(hook, profile=profile)` — `external` es la única mitad
que no. Un hook cuyo comando incluye el
directorio de config del perfil no tiene forma de expresarse ahí: una sola
entrada apuntaría al perfil equivocado en todos los demás.

Medido el 2026-09-14, al hacer que `lh deploy` pasara a ser el único dueño del
bloque `hooks` (ADR-041 step 2). El registro del hook `SessionStart` de la
integración de herdr —cuyo comando es `bash
~/.claude-<profile>/hooks/herdr-agent-state.sh session`— **salió de control de
versiones** con ese cambio: vivía hardcodeado y templateado en el snapshot de
`settings.json` que mantenía chezmoi, y al borrar ese bloque no hubo dónde
ponerlo. Es una consecuencia aceptada, no un bug de ese cambio.

El síntoma es silencioso y difiere por máquina: donde el hook ya está,
`lh deploy` lo preserva como ajeno y todo sigue andando; una máquina nueva
arranca sin él y nada avisa. Hoy el workaround es correr `herdr integration
install claude` a mano una vez por perfil, con `CLAUDE_CONFIG_DIR` apuntando al
perfil correcto.

**Acción:** una de dos, y la segunda es más barata.

1. Soporte per-profile en `external` — una key `profiles = [...]` por entrada, o
   un `[profiles.<name>.hooks.*]` que se mergee sobre el bloque global.
2. Un token de path que el deploy expanda al escribir cada perfil
   (`{profile}`, `{profile_config_dir}`). Cubre este caso y cualquier otro
   comando externo que necesite el directorio del perfil, sin tocar la forma de
   la config.

### `deploy` serializa `settings.json` con `ensure_ascii=True` y hace rebotar los bytes en cada ciclo

**Por qué:** `agents/claude_code.py:873` escribe
`json.dumps(settings, indent=2)`, y `ensure_ascii` por default es `True`, así
que todo carácter no-ASCII sale escapado (`—` → `—`). Claude Code, que
reescribe ese mismo archivo en runtime, serializa con `ensure_ascii=False`. El
merge de chezmoi que gestiona el archivo en el destino replica el formato de
Claude Code a propósito.

Resultado: las keys con prosa no-ASCII —hoy `autoMode`, que guarda
`soft_deny` y `environment` en lenguaje natural— rebotan de formato en cada
ciclo. `lh deploy` las deja escapadas, el `apply` siguiente las desescapa, y
vuelta a empezar. El contenido es idéntico en las dos puntas; lo que cambia son
los bytes.

Eso es exactamente el drift que el merge existe para evitar, y no es cosmético:
un `settings.json` con contenido igual pero bytes distintos hace que
`chezmoi update` **frene a preguntar** si sobrescribe. En un destino headless
no puede abrir `/dev/tty`, el apply entero aborta, y todo lo demás de esa
pasada se saltea en silencio — scripts incluidos. Ya pasó una vez por esta vía
y bloqueó el upgrade de una herramienta que no tenía nada que ver con el
archivo.

Medido el 2026-09-14: 11 líneas de diff por este motivo en un profile,
persistentes entre un `deploy` y el `apply` que lo sigue.

**Acción:** `ensure_ascii=False` en los **dos** call sites, que desde el step 3
viven en el adapter y ya no en el engine: `ClaudeCodeAdapter._plan_settings`
(`agents/claude_code.py:873`, `settings.json`) y `._plan_mcp` (`:900`,
`.claude.json`). Son dos funciones distintas, no una — la redacción anterior
decía "misma función" cuando ambos `json.dumps` estaban en `deploy/engine.py`.
El `.claude.json` tiene el mismo default y el mismo consumidor en runtime. Va
con worktree y test — el test es el que fija el contrato de formato, que hoy no
está cubierto en ningún lado, y los goldens de `tests/goldens/config-deploy/`
son el lugar natural para anclarlo.

### El backup de `lh migrate` colapsa dos artefactos que comparten basename

`migrate/steps/backup.py:35` escribe cada target como `dest = backup_dir / t.name`.
Dos artefactos con un mismo basename — `~/.claude-lazy/settings.json` y
`~/.claude-flex/settings.json` son el caso vivo — resuelven al mismo archivo de
backup, y el segundo pisa al primero **al escribir**, antes de que nadie intente
restaurar. El consumidor tiene la mitad simétrica del bug:
`migrate/rollback.py:39-40` hace `src = backup_dir / Path(payload["path"]).name`.

Es pérdida de datos silenciosa: el backup de la migración queda incompleto y
`lh migrate --rollback` reporta `restored` para los dos paths.

Repro, contra el paquete instalado:

```python
import json, tempfile
from pathlib import Path
from lazy_harness.migrate.rollback import apply_rollback_log

tmp = Path(tempfile.mkdtemp()); bd = tmp / "bk"; bd.mkdir()
(tmp/"lazy").mkdir(); (tmp/"flex").mkdir()
(bd/"settings.json").write_text("BACKUP-CONTENT-ONE-COPY")
(tmp/"lazy"/"settings.json").write_text("new-lazy")
(tmp/"flex"/"settings.json").write_text("new-flex")
(bd/"rollback.json").write_text(json.dumps([
    {"step":"s","kind":"restore_file","payload":{"path":str(tmp/"lazy"/"settings.json")}},
    {"step":"s","kind":"restore_file","payload":{"path":str(tmp/"flex"/"settings.json")}},
]))
apply_rollback_log(bd)
# ambos quedan en "BACKUP-CONTENT-ONE-COPY", ambos reportan restored
```

Nota relacionada del mismo archivo: `migrate/rollback.py:47` actúa solo
`if not link.exists()`, así que **nunca repunta un symlink existente**. Hoy es
correcto por accidente — su único productor, `migrate/steps/scripts_step.py:38`,
hace `unlink()` antes de registrar la op, así que el link siempre está ausente
cuando se replaya. No reusar ese op kind para un relink: `lh deploy` no lo hace,
tiene su propia rama de manifest con `_restore_symlink`, que desvincula y
revincula incondicionalmente.

**Por qué no se arregló acá:** el PR del snapshot de deploy
([decision 10](designs/2026-09-13-multi-agent-blast-radius-design.md)) reusa
`apply_rollback_log` agregándole una rama de manifest y deja la rama de
migración intacta a propósito — reescribirla cambiaría un camino que funciona
para un comando que nadie está tocando.

**Condición de arranque:** cuando se toque `lh migrate` por cualquier otro
motivo, o si aparece un caso real de migración con dos artefactos de igual
basename. El arreglo es el mismo que ya vive en `deploy/snapshot.py`: un content
path único por destino en vez de por basename.

---

---

### `pre_tool_use_security` es denylist; evaluar default-deny

**Por qué:** `should_block()` es block-if-match (`hooks/builtins/pre_tool_use_security.py:241`)
con `allow_patterns` como rescate (`:250`). Una corrida de mutation testing sobre esa
lógica dio todos los mutantes muertos y aun así siete evasiones pasaron: variación de
whitespace, reinterpretación de flags, y grafías alternativas de un path ya nombrado en
una regla. El gate nuevo de `CLAUDE.md` —*mutation testing prueba que un guard tiene
ramas, no que tiene cobertura*— cubre la **verificación**; esto es la pregunta de
**diseño** que quedó abierta detrás.

Un denylist no puede enumerar lo que no pensó. Un allowlist (default-deny) invierte la
carga: lo no previsto se bloquea en vez de pasar. El costo es real y es el motivo por el
que esto es un item y no un cambio: hoy el guard corre sobre cada `Bash`, y una lista de
permitidos tiene que cubrir el uso diario de dos perfiles sin volverse un prompt continuo
de permisos. `allow_patterns` ya existe y es el germen de esa lista.

**Acción:** medir primero, no rediseñar de entrada. Instrumentar cuántos comandos
distintos ve el hook en 72h por perfil y qué fracción cubrirían los `allow_patterns`
actuales. Si la cola es corta, el allowlist es viable y va como ADR con período de
sombra (registrar lo que *habría* bloqueado, sin bloquear). Si es larga, queda denylist y
lo que corresponde es el ataque adversarial periódico que el gate ya pide.

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

### Un `[hooks.*] scripts` explícito ignora los defaults del registry, en silencio

`_DEFAULT_ON_HOOKS` solo aplica a eventos que el `config.toml` no declara. Un perfil con `scripts = [...]` explícito congela esa lista: un builtin nuevo marcado default-on **no** aparece al actualizar.

Pasó con `pre-tool-use-git-scope` en 0.57.0 — registrado, default-on, testeado, releasado y sin correr una sola vez hasta que se agregó a mano al `config.toml`. El síntoma es indistinguible de que el hook funcione y no encuentre nada.

**Acción:** que `lh deploy` (o `lh doctor`) avise cuando un builtin default-on queda fuera de un evento declarado explícitamente. Es la diferencia entre un hook desactivado a propósito y uno olvidado.

**Segunda medición, 2026-09-11.** Auditados los seis eventos del `config.toml` del CT `agents` contra `DEFAULT_HOOKS`: faltaban `pre-tool-use-git-scope` y `session-start-preflight`. El primero estaba en el template de chezmoi desde antes — al CT le faltaba el `apply`, no el renglón. El segundo **falta en el template**, así que hoy no corre en ninguna de las dos máquinas. Nada avisó en ningún caso, que es exactamente el síntoma que este item describe.

La auditoría es tres líneas contra `DEFAULT_HOOKS` y el `config.toml`, comparando por evento e ignorando los extra deliberados (`herdr-context-gauge`, `post-tool-use-ansible-lint`). Es la forma que debería tomar el check de `lh doctor`.

## Multi-agente — items declarados, deliberadamente no cableados

Salen de [`designs/2026-09-13-multi-agent-blast-radius-design.md`](designs/2026-09-13-multi-agent-blast-radius-design.md) y de [`designs/2026-09-13-multi-agent-harness-design.md`](designs/2026-09-13-multi-agent-harness-design.md), y están acá por el gate del `CLAUDE.md`: *un `config.toml` sin una entrada puede ser una decisión y no un olvido, así que grepeá el backlog antes de cablear*. Si encontrás alguno de estos sin implementar, **no es un descuido** — leé la condición de arranque antes de tocarlo.

### Metric event v3 — dimensión `agent` y modelo de facturación plano

`MetricEvent` (`plugins/contracts.py`) no tiene dimensión `agent`, y `monitoring/pricing.py` asume precio por token. De los tres agentes del diseño, dos no se facturan así: Copilot va por asiento y Codex entra por la suscripción. Reportar un costo por token para esos dos no es aproximar, es inventar.

**Condición de arranque:** antes de que se reporte el primer costo no-Claude. No antes — es la decisión 3 del spec derivado y *no sobrevive* a los kill criteria, así que implementarla temprano es trabajo que se tira si el multi-agente muere.

### Segmentos de perfil nombrados por rol, no por filename destino

El árbol de system docs se keyea hoy por el filename de Claude (`CLAUDE.md`) a través de tres repos. `system_docs()` reemplaza a `system_doc_name()` y los segmentos pasan a nombrarse por rol.

**Condición de arranque:** con el step 8 del spec padre, en el mismo release que el rename del hook de sync (decisión 5). Tampoco sobrevive a los kill criteria.

### `lazy-ai-tools` — deuda de nomenclatura, registrada sin pagar

`ClaudeCallLog`, `StepLog.claude_calls` y varios docstrings nombran a Claude donde el concepto es "el agente". Relevado el monorepo entero: **no necesita ningún cambio** para el multi-agente.

**Condición de arranque:** ninguna. Es la decisión 8 y está explícitamente *not scheduled*. Renombrar 559 registros históricos para arreglar un nombre es justo el refactor-fuera-del-task que el `CLAUDE.md` prohíbe. Se toca solo si otra cosa ya está tocando esos archivos.

### Hooks de usuario tienen el mismo bug de duplicación que tenían los builtins

Cerrado para builtins (`_is_harness_owned` ahora identifica por nombre canónico dentro de `lh hook <name>`). La función se mudó con el merge en el step 3: vive en `agents/claude_code.py:191`, no en `deploy/engine.py`. Los hooks de usuario siguen expuestos: su comando generado es `{sys.executable} {path}`, y `sys.executable` cambia al actualizar Python — con lo cual el redeploy preserva la entrada vieja como ajena y queda duplicada.

Arreglarlo requiere que la clasificación conozca los hooks configurados, o sea cambiarle la firma a `_is_harness_owned` (`agents/claude_code.py:191`). No se hizo en el fix del step 0 para no ampliar el alcance.

**Condición de arranque:** cuando alguien reporte un hook de usuario corriendo dos veces, o junto con el step 5 (migración de los 15 builtins restantes), que ya toca esa zona.

### Ocho builtins resuelven su `hooks.log` globalmente, más el worker

Cerrado para los dos que se podían cerrar: `pre-tool-use-security` (`_log_block`, vía `event.profile`) y `context-inject` (la línea de boot, cargando config antes de escribir).

Inventario por **mecanismo**, no por grafía: diez builtins escriben `hooks.log`, dos están arreglados, ocho resuelven el directorio sin leer nunca el profile. El grep literal de `get_agent("claude-code")` encuentra siete y **pierde a `pre-compact`**, que hace lo mismo con otra expresión — la diferencia exacta que gatea el `CLAUDE.md`.

| Builtin | Sitios | Grafía |
|---|---|---|
| `session-export` | `:44` boot, `:59-60` post-config | literal + `cfg.agent.type` |
| ~~`compound-loop`~~ | cerrado — ver la actualización debajo de la tabla | — |
| `session-end` | `:89` boot, `:107-108` post-config | literal + `cfg.agent.type` |
| `pre-compact` | `:158` resolución, `:184` escritura | `cfg.agent.type if cfg is not None else "claude-code"` |
| `pre-tool-use-memory-size` | `:170` | literal |
| `pre-tool-use-read-size` | `:69` | literal |
| `post-tool-use-format` | `:67` | literal |
| `post-tool-use-ansible-lint` | `:140` | literal |

**Actualización 2026-09-15 — quedan siete.** `compound-loop` sale del inventario con su migración (task 6 del step 5): `main(event)` resuelve `agent_dir_for(cfg, event.profile)` y carga config **antes** de la primera línea de log, así que las dos grafías desaparecen juntas. Cubierto por `tests/integration/test_hook_log_profile_isolation.py`, que afirma presencia en el dir del profile y **ausencia** fuera de él. La medición de 0.67.1 que sigue más abajo no se re-corrió: es el registro de lo que se midió entonces, no un conteo vivo.

Más `knowledge/compound_loop_worker.py`, fuera del proceso del hook: el camino normal es `:98` con `cfg.agent.type` (`:100` es solo el fallback del `except`) y `:101` resuelve sin profile. Global sí, hardcodeado incondicionalmente no.

`stop-verify-guard` **no** entra: es migrado y no escribe `hooks.log`, registra en MetricsDB.

Medido por el gate de aislamiento el 2026-09-15 contra 0.67.1: **siete** de los ocho filtraron **28 líneas** fuera del dir del profile en una sola corrida. `pre-compact` no aparece en ese conteo porque el gate **nunca lo invoca** —no está en `KNOWN_GAP_HOOKS` ni tiene un `invoke`—, no porque esté arreglado ni porque cueste dispararlo: `pre_compact.py:185` escribe su línea `fired` sin condición. Sigue siendo ocho por mecanismo. El gate los imprime bajo `KNOWN GAP` en cada corrida y no los asertea, así que un `PASS` dice que los **migrados** están aislados, nunca que no filtra nada.

**Por qué no se arregló con los otros dos.** El dato existe y muere en el dispatch: `deploy/engine.py:136` emite `{binary} hook {name} --profile {profile}` para *todos* los builtins, pero `cli/hooks_cmd.py` llama `main_fn()` **sin argumentos** en la rama no-migrada. Ninguno de los ocho tiene `event` ni profile en scope — `pre-compact` incluido, que es unmigrated igual que los otros siete. Plumbearlo obliga a tocar esa rama transitoria, que el step 5 borra junto con `BuiltinHookSpec.migrated`.

Descartadas dos salidas y por qué: introspeccionar la firma de `main()` contradice el docstring de `migrated` (*un chequeo de firma leería igual hoy y mentiría apenas un `main()` migrado crezca un default*); inventar un canal por env var agrega mecanismo a un camino condenado. Una tercera, `_shared.profile_name()`, arregla el `config_dir` y **no** el adapter — resuelve el agente vía el `cfg.agent.type` global en `_shared.py:160`, o sea hereda el mismo coupled reader un nivel más abajo.

**Alcance: elegido, no estructural.** El gate del step 4 se acotó a los tres builtins migrados, y eso es legítimo — el diseño define ese gate y §12.9 del informe reconoce a los unmigrated como no probados. Lo que **no** es cierto, y este párrafo decía antes, es que los demás queden excluidos por construcción.

Los unmigrated sí se deployan a un profile no-Claude. `deploy/engine.py:204-233` (`_warn_unmigrated`) emite un warning y deliberadamente **no** los omite; su propio docstring lo dice: *«A warning rather than a refusal on purpose... A default `lh deploy` to a Codex profile ships four of these»*. `:273-276` sigue construyendo sus comandos. `PRE_RUNNER_AGENT` nombra el agente que la rama asume, no es un filtro.

Y un wire no verificado no impide efectos en disco anteriores a interpretar el payload. Medido por el review: profile `gate` de agente Codex, `CLAUDE_CONFIG_DIR` y `CODEX_HOME` ausentes, compound loop deshabilitado — `lh hook compound-loop --profile gate` sale 0 y agrega dos líneas en `~/.claude/logs/hooks.log`:

```
compound-loop: fired cwd=/private/tmp/f7-review-probe
compound-loop: disabled in config, skipping
```

O sea el riesgo real: se deployan, escriben, y en un profile cuyo agente difiere del `[agent].type` global escriben en el lugar equivocado. En un profile Claude Code el `CLAUDE_CONFIG_DIR` del subproceso tapa el bug; muerde cuando el agente difiere o cuando la env var falta.

**Dos cosas medidas que quien lo tome necesita:**

1. En `compound-loop` y `session-end` la rama `enabled = false` **retorna antes** de la re-resolución post-config. Con compound loop apagado, el 100% de lo que esos dos escriben sale del directorio de boot — arreglar la primera línea ahí no arregla nada. Igual `session-export` en no-config y config roto.
2. `compound_loop.py:67` hace `_rotate_log` sobre el archivo mal resuelto, y eso es escritura **truncante**, no append: no solo escribe en el profile equivocado, le trunca el log.

Límite que no se cierra desde adentro del hook: con `cfg is None` no existe la tabla de profiles, así que el fallback global es correcto por construcción. El docstring de `agent_dir_for` (`_shared.py:235`) ya lo dice.

**Condición de arranque:** con el step 5, que migra los quince builtins restantes a `main(event)` y borra la rama no-migrada. Postergarlo hasta ahí es una **decisión**, no una imposibilidad técnica: se podría plumbear antes, al costo de tocar la rama que ese step elimina. El riesgo que se acepta mientras tanto es el del párrafo anterior — escrituras reales en el directorio equivocado en cualquier profile cuyo agente difiera del global.

## ADR decisions pending

- ~~**Legacy ADR-010 Ollama backend**~~ — cerrado. Promovido por [ADR-033](adrs/033-llm-backend-abstraction.md) y hecho utilizable por [ADR-039](adrs/039-role-routed-inference.md) (ruteo por rol).
- **Legacy ADR-013 Proactivity levels per profile** — promover o descartar. Criterio: si agregás un tercer perfil, promoverlo; si no, descartar.
- ~~**ADR-018 implementation epic**~~ — cerrado. La implementación de ADR-018 ya había cerrado vía [ADR-025](adrs/025-doctor-features-section.md) y [ADR-026](adrs/026-config-wizards.md); el sujeto real de este item, el capability registry de [ADR-035](adrs/035-capability-registry.md), shippeó el 2026-08-17 y el ADR pasó a `accepted`. Lo que sigue abierto es su consumidor: el pane de configuración de la TUI ([`designs/2026-08-17-config-tui-design.md`](designs/2026-08-17-config-tui-design.md)).
