# Auditoría semántica independiente — external-hook-ownership

Fecha solicitada: 2026-09-19. Conclusión del feature: **BLOCKED**.

El contrato escrito no es coherente: ADR-031 y su entrada Done todavía declaran que el framework posee todo `settings.json.hooks` y borra hooks manuales, mientras el código actual y la evolución de ADR-054 preservan externos. F1 bloquea el cierre semántico del feature. Las pruebas seleccionadas del feature pasaron; este dictamen no afirma una regresión funcional de ownership.

Hay **9 findings: 1 high y 8 medium**. F2–F9 son deriva previa o transversal; se separan del bloqueo del feature para no atribuirle defectos ajenos. Ninguno fue corregido en esta auditoría.

## Alcance e independencia

Se leyó y ejecutó `.claude/commands/coherence-audit.md:1` (Piece B): lectura de los 59 ADR cuyo encabezado es exactamente `**Status:** accepted`, sus evoluciones y `specs/backlog.md` completo (775 líneas). Los ADR aceptados suman 7.846 líneas. Se leyó el índice y su vocabulario de estados; ADR-020 y ADR-051 están superseded y ADR-034 proposed, por lo que no se contaron como accepted. No se confundió una decisión histórica explícitamente reemplazada con una promesa vigente.

Estado auditado: worktree `external-hook-ownership`, branch `feat/external-hook-ownership`, HEAD `76edfedc48b1c78d1810100ad8fdb319a0a86657`, incluidos los cambios sin commit presentes. El árbol ya tenía 23 archivos tracked modificados y seis informes untracked. No se usaron esos informes previos de revisión para formar el dictamen.

No hubo subagentes, modificaciones a código/tests/ADRs/backlog/docs, commits, despliegues ni llamadas pagas a modelos. Las únicas escrituras deliberadas son este informe, scripts/fixtures temporales y el append de findings a memoria solicitado por el procedimiento. Los comandos de prueba pueden crear cachés normales de ejecución. No se ejecutó el gate completo de commit: no hubo commit, y este procedimiento no reemplaza la mitad determinística bajo `tests/docs/`.

Como control adicional de release se contrastó `docs/roadmap.md:46`: los items de adapters, documentos, skills y costos implementados figuran cerrados; pilotos ADR-060, rollout externo ADR-061 y habilitación PRJ ADR-062 siguen separados y abiertos (`docs/roadmap.md:71`, `:77`, `:79`, `:81`). Eso no certifica los despliegues externos. No se cortó un release.

## Findings — formato del procedimiento

```text
high | specs/adrs/031-default-hooks-merge.md:49 | ADR-031 declara ownership de todo settings.json.hooks y borrado de hooks manuales; el planner conserva grupos externos y sólo retira builtins cuya propiedad reconoce. specs/backlog.md:173 repite el contrato anterior. | Anotar la evolución de ADR-031 y corregir la entrada Done del backlog para distinguir defaults, ownership de builtins y ensure-present de externos; conservar la historia como tal.
```

```text
medium | specs/adrs/022-engram-episodic-memory.md:34 | El ADR promete eliminar el MCP de Engram al desinstalarlo y redeployar; un conjunto de servidores vacío no produce ninguna operación de borrado y conserva la entrada instalada. | Anotar que el merge MCP agrega/actualiza y requiere limpieza manual de entradas obsoletas, como ya reconoce ADR-024:35.
```

```text
medium | specs/adrs/023-graphify-code-structure.md:46 | El ADR promete eliminar el MCP de Graphify al desinstalarlo y redeployar; el merge conserva entradas antiguas cuando el servidor deja de detectarse. | Corregir la consecuencia de desinstalación con la misma limitación de limpieza manual registrada en ADR-024:35.
```

```text
medium | specs/adrs/024-mcp-server-orchestration.md:41 | La última nota de evolución dice que Codex ignora servers y que el primer traductor MCP sigue sin escribirse; Codex ya traduce servidores a config.toml. | Agregar una evolución que cierre el estado throwaway y remita al planner MCP de ADR-042, manteniendo explícito que Copilot continúa sin reclamar MCP.
```

```text
medium | specs/adrs/010-pre-compact-preservation.md:22 | El ADR afirma extracción de intents y archivos del transcript; parse_transcript busca role/content al tope y devuelve dos listas vacías para el formato anidado de Claude, por lo que esa parte del summary está ausente. | Anotar el límite actual en ADR-010 y vincular el fix pendiente del backlog, sin atribuir al hook la recuperación de tareas y archivos hasta medirla.
```

```text
medium | specs/adrs/029-engram-persist-deterministic-mirror.md:17 | El ADR deriva el proyecto con --show-toplevel; el hook usa --git-common-dir y resuelve el nombre del repositorio principal también desde worktrees. | Actualizar la derivación documentada a git rev-parse --path-format=absolute --git-common-dir y .parent.name, incluyendo el caso worktree.
```

```text
medium | specs/adrs/039-role-routed-inference.md:78 | El ADR promete una única implementación por proveedor y contabilización del gasto del compound loop; persisten dos invocaciones Claude y run_inference no escribe métricas ni atribución del distill. | Acotar las consecuencias a la resolución por rol efectivamente implementada y registrar la unificación y contabilidad pendientes, o resolverlas en un cambio separado con evidencia.
```

```text
medium | specs/adrs/039-role-routed-inference.md:46 | api_key_env promete el fallback owner-only del sink; el resolver LLM sólo consulta os.environ y retorna vacío si la variable falta, aun cuando el resolver del sink puede leer el archivo de secretos. | Documentar el requisito real de inyectar la variable en el job o registrar como pendiente el fallback prometido; no presentarlo como mecanismo compartido ya implementado.
```

```text
medium | specs/backlog.md:209 | La entrada Done atribuye el bug a que apply_patch nunca matchea Edit|Write; ADR-056 registra una prueba nativa donde ese matcher sí dispara por el alias compatible. | Corregir la explicación causal histórica del backlog y enlazar la medición de ADR-056, conservando los cambios de rename y derivación que sí ocurrieron.
```

## Evidencia por finding

### F1 — specs/adrs/031-default-hooks-merge.md:49

src/lazy_harness/agents/claude_code.py:330, :378, :430, :455 y :1216; src/lazy_harness/deploy/engine.py:421 y :439; specs/adrs/054-external-hook-placeholders.md:147. La prueba añadió un builtin a settings con foreign-manual: el externo sobrevivió; preserved lo nombró, dropped y repaired quedaron vacíos. El backup del motor se activa por repaired (src/lazy_harness/deploy/engine.py:525), no por eliminar cualquier hook manual.

### F2 — specs/adrs/022-engram-episodic-memory.md:34

src/lazy_harness/deploy/engine.py:640; src/lazy_harness/agents/claude_code.py:1253; src/lazy_harness/agents/codex.py:1132. Instalación sintética de engram y graphify seguida de servers={} en Claude y Codex: 0 operaciones, documentos idénticos, ambos MCP presentes.

### F3 — specs/adrs/023-graphify-code-structure.md:46

src/lazy_harness/knowledge/graphify.py:28 y :37; src/lazy_harness/deploy/engine.py:652; src/lazy_harness/agents/claude_code.py:1255 y :1264; src/lazy_harness/agents/codex.py:1147 y :1171. Misma reproducción de F2; la detección del binario MCP y su flag sí existen, la retracción de entradas no.

### F4 — specs/adrs/024-mcp-server-orchestration.md:41

src/lazy_harness/agents/codex.py:1041, :1060 y :1132; src/lazy_harness/agents/copilot.py:321. La llamada real a CodexAdapter.plan_config con servidores sintéticos produjo config.toml con [mcp_servers.engram] y [mcp_servers.graphify].

### F5 — specs/adrs/010-pre-compact-preservation.md:22

src/lazy_harness/hooks/builtins/pre_compact.py:34, :47 y :68; specs/backlog.md:298 y :308. Control plano: 1 intent y /tmp/audit-fixture.py, summary con Tasks in progress y Files worked on; mismos mensajes bajo message: ([], []), summary ''. No contradice el backup ni los tails de memoria, que son mecanismos independientes.

### F6 — specs/adrs/029-engram-persist-deterministic-mirror.md:17

src/lazy_harness/hooks/builtins/engram_persist.py:15 y :25. En el checkout principal ambos producen lazy-harness; en este worktree el método documentado produce external-hook-ownership y la función real devuelve lazy-harness. Es una diferencia observable de identidad, no sólo del nombre de una función.

### F7 — specs/adrs/039-role-routed-inference.md:78

src/lazy_harness/knowledge/compound_loop.py:1484; src/lazy_harness/llm/invoke.py:96; src/lazy_harness/llm/claude.py:29; src/lazy_harness/agents/claude_code.py:1028; src/lazy_harness/cli/exec_cmd.py:399 y :429. Ejecución exitosa de run_inference(distill) con transporte simulado: argv Claude con output-format text, 0 session_stats y 0 session_attribution en DB temporal. El camino agent construye output-format json por separado. No se afirma que un ingest posterior jamás pueda encontrar un transcript incidental; no se observó ni se probó tal recuperación en esta auditoría.

### F8 — specs/adrs/039-role-routed-inference.md:46

src/lazy_harness/llm/invoke.py:82; src/lazy_harness/monitoring/sink_setup.py:59 y :93. Con entorno vacío y archivo sintético chmod 0600, el sink resuelve el valor de prueba y el LLM retorna ''. No se consultaron credenciales reales.

### F9 — specs/backlog.md:209

specs/adrs/056-codex-honours-claude-shaped-matchers.md:35, :39 y :47. El finding es la contradicción entre la afirmación absoluta del backlog y la evidencia nativa versionada en el ADR; no se volvió a correr el probe de Codex 0.154.0 ni se extrapoló a otra versión.

## Pares semilla obligatorios

- **ADR-008 → compound_loop*.py.** Se leyeron completos el evaluator y el worker, además del hook productor. La cola se crea en `knowledge/compound_loop.py:551`; el hook inicia un proceso separado y transmite profile en `hooks/builtins/compound_loop.py:115`; el worker vuelve a enumerar tareas en un `while` (`knowledge/compound_loop_worker.py:72`), mueve incluso las fallidas a done y usa flock (`:183`). La retención de siete días está en `:98`, en consonancia con la evolución de ADR-008:92. El distill pasa por `run_inference` (`knowledge/compound_loop.py:1484`). No se certificó el costo temporal real de una sesión ni la exclusión concurrente por prueba de carga.
- **ADR-012 → monitoring/db.py.** Módulo completo leído. El esquema crea seis tablas (`:68`); la migración incluye las columnas de ADR-061 (`:165`). Se ejecutó un upsert dos veces sobre la misma clave con input 1 y luego 9: quedó una fila con 9, sin duplicar ni conservar el valor inicial (`:253`). Se enumeraron las seis tablas con SQLite. El bloque DDL original está explícitamente marcado histórico en ADR-012:66; no se lo denunció por diferir del DDL actual.
- **ADR-023/027 → graphify.py y deploy/engine.py.** Ambos módulos completos leídos. CLI y MCP tienen probes separados (`knowledge/graphify.py:24`, `:28`); el servidor emitido es `graphify-mcp` (`:37`). El motor requiere flag más binario (`deploy/engine.py:652`) y lleva los servidores al planner (`:617`). Se observó el problema de desinstalación F2/F3, no ausencia del MCP. La ubicación de memoria de ADR-027 se contrastó con la salida real de `lh memory status`.
- **ADR-033 → llm/.** Se leyeron base, claude, openai_compat, registry, roles e invoke. El Protocol mantiene complete/default_model; la selección de proveedores está en `llm/registry.py:23`, la precedencia de roles y el shim en `llm/roles.py:39`. La evolución de ADR-033:342 remite a ADR-039 y evita denunciar el antiguo backend global como contrato vigente. Las consecuencias de ADR-039 que exceden esa implementación se registran por separado como F7/F8.

## Verificación ejecutada

Comando de tests (exit 0):

```sh
uv run --frozen pytest -q tests/unit/test_config_planner.py tests/unit/test_agent_codex.py tests/unit/test_agent_codex_trust.py tests/unit/test_agent_copilot.py tests/unit/test_deploy_config_engine.py tests/integration/test_deploy_retrust.py tests/integration/test_deploy_snapshot.py
```

Resultado: **295 passed in 1.69s**. Incluye los planners afectados, trust/re-trust y snapshots de los dos artefactos Copilot. Es evidencia de regresión local; no sustituye la carga por binarios externos.

También se ejecutó el script reproducible del apéndice con `uv run --frozen python /tmp/external-hook-audit-probes.py` (exit 0). El primer intento recibió un rechazo de filesystem al abrir la caché de uv; se repitió mediante la escalación del sandbox, sin cambiar dependencias ni esquivar el límite con otra herramienta.

Resultados observados:

| Prueba | Resultado |
|---|---|
| External add → redeploy → omit, Claude/Codex/Copilot | Una declaración; idempotente; sobrevive la omisión en los tres. |
| Claude: builtin nuevo con grupo manual existente | Manual preservado; `dropped=[]`, `repaired=[]`. |
| MCP: Engram/Graphify presentes → servers vacío | Ninguna operación en Claude/Codex; documentos y entradas conservados. |
| Codex: entrada MCP neutral → planner | `config.toml` con tablas `mcp_servers` nativas. |
| PreCompact: control plano vs mensajes anidados | Control extrae intent/archivo; formato nativo da listas y summary vacíos. |
| Engram project key desde checkout principal y worktree | Nombre canónico `lazy-harness` en ambos; la derivación del ADR diverge en el worktree. |
| Credencial sintética 0600 con entorno vacío | Sink resuelve el archivo; LLM no. |
| Inferencia exitosa con transporte Claude simulado | Segunda invocación text; sin filas de métricas ni atribución creadas por el seam. |
| SQLite upsert repetido | Una fila; último valor; seis tablas presentes. |

Se leyó el merge Codex de `agents/codex.py:480`, `:515`, `:653`, `:686`, `:1065`: parseo conservador, provenance por posición/grupo, slots managed y preservación de extranjeros. Se leyó el split y migración Copilot en `agents/copilot.py:307`, `:338`, `:400`, `:479`; ambos archivos son targets. El motor asigna EXTERNAL a scripts de usuario y a external (`deploy/engine.py:421`, `:439`). Esto concuerda con ADR-042:200, ADR-047 (evolución de ownership) y ADR-054:147 en los caminos inspeccionados y probados.

No se volvió a probar el runtime de Codex/Copilot ni se modificó su trust. La afirmación de neutralidad de `description` en ADR-042:231 es evidencia de un probe anterior, no un experimento ejecutado aquí. F9 compara dos afirmaciones documentales contra la medición versionada que ADR-056 registra; no se presenta como un nuevo probe de matcher. Ninguna prueba leyó secretos reales ni envió solicitudes a un proveedor.

## Cobertura de lectura de todos los ADR accepted

Cada fila resume la afirmación central leída, incluyendo las notas de evolución. “Lectura” no significa certificación exhaustiva de implementación: la comparación con código es por spot-check, como exige el procedimiento. “Contraste” identifica las ampliaciones concretas y los pares semilla discutidos arriba. Los estados históricos reemplazados por una evolución explícita no generan un finding automático.

| ADR y fuente | Afirmación central | Tratamiento |
|---|---|---|
| [001](../specs/adrs/001-hybrid-architecture.md) (`specs/adrs/001-hybrid-architecture.md:1`) | Separación framework/configuración personal y propiedad de los datos. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [002](../specs/adrs/002-python-uv-distribution.md) (`specs/adrs/002-python-uv-distribution.md:1`) | Distribución Python 3.11+ mediante uv; no compilación como requisito. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [003](../specs/adrs/003-toml-config-format.md) (`specs/adrs/003-toml-config-format.md:1`) | TOML, defaults tipados, loader y persistencia de configuración. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [004](../specs/adrs/004-agent-adapter-pattern.md) (`specs/adrs/004-agent-adapter-pattern.md:1`) | Protocol de adapters como frontera de diferencias entre agentes. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [005](../specs/adrs/005-xdg-first-paths.md) (`specs/adrs/005-xdg-first-paths.md:1`) | Precedencia de entorno/XDG/defaults en resolución de rutas. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [006](../specs/adrs/006-hooks-subprocess-json.md) (`specs/adrs/006-hooks-subprocess-json.md:1`) | Hooks subprocess con JSON y políticas de salida según evento. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [007](../specs/adrs/007-parallel-bootstrap-migration.md) (`specs/adrs/007-parallel-bootstrap-migration.md:1`) | Migración en paralelo con rollback y corte después de verificar. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [008](../specs/adrs/008-compound-loop-async-worker.md) (`specs/adrs/008-compound-loop-async-worker.md:1`) | Productor rápido, cola de archivos, worker con flock, gates y retención de siete días. | Contraste de caminos seleccionados |
| [009](../specs/adrs/009-profile-symlink-deploy.md) (`specs/adrs/009-profile-symlink-deploy.md:1`) | Deploy de contenido por symlinks; separación fuente y runtime. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [010](../specs/adrs/010-pre-compact-preservation.md) (`specs/adrs/010-pre-compact-preservation.md:1`) | Backup PreCompact, extracción de tareas/archivos y emisión de contexto. | Contraste; F5 |
| [011](../specs/adrs/011-session-export-and-classification.md) (`specs/adrs/011-session-export-and-classification.md:1`) | Export JSONL a Markdown clasificado; escritura atómica y artefactos incrementales. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [012](../specs/adrs/012-sqlite-monitoring.md) (`specs/adrs/012-sqlite-monitoring.md:1`) | SQLite local, upsert idempotente, vistas y evolución de tablas. | Contraste de caminos seleccionados |
| [013](../specs/adrs/013-scheduler-unified-backends.md) (`specs/adrs/013-scheduler-unified-backends.md:1`) | Scheduler común sobre launchd, systemd y cron. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [014](../specs/adrs/014-migration-engine-rollback.md) (`specs/adrs/014-migration-engine-rollback.md:1`) | Migración detect/plan/execute con rollback y dry-run. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [015](../specs/adrs/015-strict-tdd-workflow.md) (`specs/adrs/015-strict-tdd-workflow.md:1`) | TDD estricto como regla del workflow. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [016](../specs/adrs/016-knowledge-dir-qmd-optional.md) (`specs/adrs/016-knowledge-dir-qmd-optional.md:1`) | Knowledge en Markdown y QMD opcional por detección de binario. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [017](../specs/adrs/017-selftest-as-health-check.md) (`specs/adrs/017-selftest-as-health-check.md:1`) | Selftest de salud/configuración de la instalación, separado de pytest. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [018](../specs/adrs/018-config-discoverability.md) (`specs/adrs/018-config-discoverability.md:1`) | Descubrimiento con doctor y wizards opt-in, sin wizard automático de upgrade. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [019](../specs/adrs/019-handoff-session-end-freshness.md) (`specs/adrs/019-handoff-session-end-freshness.md:1`) | SessionEnd y handoff-now fuerzan cola y evitan gates de debounce/growth. | Contraste de caminos seleccionados |
| [021](../specs/adrs/021-async-response-grading.md) (`specs/adrs/021-async-response-grading.md:1`) | Grading en la evaluación asíncrona y escalación condicional al PRJ. | Contraste de caminos seleccionados |
| [022](../specs/adrs/022-engram-episodic-memory.md) (`specs/adrs/022-engram-episodic-memory.md:1`) | Engram opcional, flag más binario, MCP y ciclo de desinstalación. | Contraste; F2 |
| [023](../specs/adrs/023-graphify-code-structure.md) (`specs/adrs/023-graphify-code-structure.md:1`) | Graphify como índice estructural opcional y MCP mediante binario separado. | Contraste; F3 |
| [024](../specs/adrs/024-mcp-server-orchestration.md) (`specs/adrs/024-mcp-server-orchestration.md:1`) | Orquestación MCP por deploy y traducción/merge nativo por adapter. | Contraste; F4 |
| [025](../specs/adrs/025-doctor-features-section.md) (`specs/adrs/025-doctor-features-section.md:1`) | Doctor presenta disponibilidad, versión y pin de las herramientas. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [026](../specs/adrs/026-config-wizards.md) (`specs/adrs/026-config-wizards.md:1`) | Wizards memory/knowledge con merge de configuración. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [027](../specs/adrs/027-memory-stack-overview.md) (`specs/adrs/027-memory-stack-overview.md:1`) | Cinco capas de memoria con roles diferentes; memoria canónica por remote. | Contraste de caminos seleccionados |
| [028](../specs/adrs/028-classify-rules-configurable.md) (`specs/adrs/028-classify-rules-configurable.md:1`) | Clasificación por reglas configurables conservando los defaults. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [029](../specs/adrs/029-engram-persist-deterministic-mirror.md) (`specs/adrs/029-engram-persist-deterministic-mirror.md:1`) | Espejo Engram determinístico con cursor e identidad de proyecto. | Contraste; F6 |
| [030](../specs/adrs/030-memory-stack-glue-layer.md) (`specs/adrs/030-memory-stack-glue-layer.md:1`) | Conexión entre capas de memoria: descubrimiento, freshness y consistencia. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [031](../specs/adrs/031-default-hooks-merge.md) (`specs/adrs/031-default-hooks-merge.md:1`) | Defaults por evento y overrides explícitos; claims de ownership del bloque hooks. | Contraste; F1 |
| [032](../specs/adrs/032-agent-adapter-completeness.md) (`specs/adrs/032-agent-adapter-completeness.md:1`) | Rutas, sesiones, MCP y documentos delegados al adapter. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [033](../specs/adrs/033-llm-backend-abstraction.md) (`specs/adrs/033-llm-backend-abstraction.md:1`) | Protocol de inferencia independiente del agente; proveedores locales/remotos. | Contraste de caminos seleccionados |
| [035](../specs/adrs/035-capability-registry.md) (`specs/adrs/035-capability-registry.md:1`) | Registro enumerable de capacidades, cardinalidad y dependencia externa. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [036](../specs/adrs/036-compact-hooks-use-real-channels.md) (`specs/adrs/036-compact-hooks-use-real-channels.md:1`) | PreCompact usa texto plano; PostCompact no tiene el canal supuesto al modelo. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [037](../specs/adrs/037-metric-event-v2-host-and-workload.md) (`specs/adrs/037-metric-event-v2-host-and-workload.md:1`) | Host y workload como dimensiones de métricas y atribución de sesiones. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [038](../specs/adrs/038-exec-envelope-cost-provenance.md) (`specs/adrs/038-exec-envelope-cost-provenance.md:1`) | Envelope exec con procedencia del costo y errores tipados, incluso timeout. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [039](../specs/adrs/039-role-routed-inference.md) (`specs/adrs/039-role-routed-inference.md:1`) | Routing por roles, dos frontends y promesas de secretos/contabilidad. | Contraste; F7/F8 |
| [040](../specs/adrs/040-memory-reconcile-and-decay.md) (`specs/adrs/040-memory-reconcile-and-decay.md:1`) | Reconcile/decay separados: reportar contradicciones y superseder sin borrar. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [041](../specs/adrs/041-multi-agent-hook-contract.md) (`specs/adrs/041-multi-agent-hook-contract.md:1`) | Runner con profile, contratos de eventos/señales y omisiones explícitas. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [042](../specs/adrs/042-multi-file-config-planning.md) (`specs/adrs/042-multi-file-config-planning.md:1`) | Plan multiarchivo, rechazo por cambio concurrente y ownership Codex por grupo. | Contraste de caminos seleccionados |
| [043](../specs/adrs/043-system-docs-by-role.md) (`specs/adrs/043-system-docs-by-role.md:1`) | Destinos de system docs como lista y segmentos por rol; migración cerrada por ADR-055. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [044](../specs/adrs/044-codex-native-edit-path.md) (`specs/adrs/044-codex-native-edit-path.md:1`) | Normalización del edit nativo Codex; límites del edit por shell y del trust inferido. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [045](../specs/adrs/045-credential-boundary.md) (`specs/adrs/045-credential-boundary.md:1`) | Credenciales por perfil; rechazo de archivo ilegible y límites de diagnóstico. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [046](../specs/adrs/046-delete-is-not-an-edit.md) (`specs/adrs/046-delete-is-not-an-edit.md:1`) | Deletes separados de edits y guards evaluando todos los paths. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [047](../specs/adrs/047-copilot-adapter.md) (`specs/adrs/047-copilot-adapter.md:1`) | Adapter Copilot medido; artefactos managed/external y migración conservadora. | Contraste de caminos seleccionados |
| [048](../specs/adrs/048-codex-rollout-streams.md) (`specs/adrs/048-codex-rollout-streams.md:1`) | Reader de rollout Codex distingue las dos corrientes de eventos. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [049](../specs/adrs/049-permission-bypass-intent.md) (`specs/adrs/049-permission-bypass-intent.md:1`) | Permission bypass is a declared intent, not a forwarded flag. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [050](../specs/adrs/050-metric-event-v3-agent-and-billing-model.md) (`specs/adrs/050-metric-event-v3-agent-and-billing-model.md:1`) | Agent y billing_model como dimensiones de métricas; evolución posterior de costos. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [052](../specs/adrs/052-profile-assets-per-agent.md) (`specs/adrs/052-profile-assets-per-agent.md:1`) | Assets por capas root/shared/agent con ledger de links. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [053](../specs/adrs/053-transcript-reader-carries-metering.md) (`specs/adrs/053-transcript-reader-carries-metering.md:1`) | TranscriptReader transporta modelo, dedup y cache para ingest multiagente. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [054](../specs/adrs/054-external-hook-placeholders.md) (`specs/adrs/054-external-hook-placeholders.md:1`) | Placeholders por perfil; externos y scripts de usuario tienen ciclo ensure-present. | Contraste de caminos seleccionados |
| [055](../specs/adrs/055-segment-rename-and-the-agent-segment.md) (`specs/adrs/055-segment-rename-and-the-agent-segment.md:1`) | Migración de segmentos y propiedad del documento ensamblado. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [056](../specs/adrs/056-codex-honours-claude-shaped-matchers.md) (`specs/adrs/056-codex-honours-claude-shaped-matchers.md:1`) | Matchers Codex evaluados por regex/alias; evidencia nativa y límites del gate. | Contraste; F9 (backlog) |
| [057](../specs/adrs/057-codex-last-refresh-is-not-liveness.md) (`specs/adrs/057-codex-last-refresh-is-not-liveness.md:1`) | last_refresh informa antigüedad, no vigencia de autenticación. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [058](../specs/adrs/058-keychain-mdat-is-operator-only.md) (`specs/adrs/058-keychain-mdat-is-operator-only.md:1`) | Keychain mdat queda como evidencia operativa; el hook no invoca security. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [059](../specs/adrs/059-portable-skills-native-commands-agents.md) (`specs/adrs/059-portable-skills-native-commands-agents.md:1`) | Proyección de skills portables, colisiones y ledger; commands/agents siguen nativos. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [060](../specs/adrs/060-agents-md-is-the-portable-repository-contract.md) (`specs/adrs/060-agents-md-is-the-portable-repository-contract.md:1`) | AGENTS.md único contrato; pilotos y probes antes de migrar la flota. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [061](../specs/adrs/061-billed-cost-and-api-equivalent-cost-are-separate.md) (`specs/adrs/061-billed-cost-and-api-equivalent-cost-are-separate.md:1`) | Costo facturado y equivalente API separados; unknown permanece explícito. | Lectura y contraste con evoluciones posteriores; sin certificación exhaustiva |
| [062](../specs/adrs/062-session-end-publishes-bounded-project-state.md) (`specs/adrs/062-session-end-publishes-bounded-project-state.md:1`) | Publicación opt-in y acotada de estado PRJ, con destino único y provenance. | Contraste de caminos seleccionados |

## Backlog y alcance del dictamen

El backlog completo se revisó con especial atención a Done vs Open y a las condiciones de arranque. F1 afecta Done en `specs/backlog.md:173`; F9 afecta la explicación causal de `:209`. La falla PreCompact ya figura abierta (`:298`), así que F5 denuncia el ADR que sigue prometiéndola, no el estado del backlog. Las limitaciones de concurrencia de memoria continúan documentadas (`:526`); no se declararon resueltas por encontrar escrituras atómicas.

Las notas históricas de la etapa throwaway, cuando están expresamente fechadas como medición pasada, no prueban por sí solas que haya trabajo aún pendiente. En particular no se usaron las mediciones antiguas de ADR-043:211 para negar la tabla `launches` actual: esa tabla se verificó ejecutando SQLite, y el backlog registra su implementación en `:194` y sus lectores en `:203`.

**Criterio de desbloqueo del feature:** revisión humana de ADR-031 y de su entrada Done para expresar la misma propiedad de hooks que implementan el código y ADR-054. Esta auditoría no autoriza editar esas superficies. F2–F9 requieren seguimiento separado y no constituyen evidencia de que este feature los haya introducido. Un gate de release global debe conservarlos visibles; este informe no certifica que no exista otra deriva fuera de los spot-checks.

## Persistencia append-only e integridad

`lh memory status` se ejecutó y señaló el store `/Users/lazynet/repos/lazy/lazy-knowledge/memory/github.com/lazynet/lazy-harness`. Se leyó `docs/how/memory-compound.md` y se respetó el schema del procedimiento, concordante con `knowledge/compound_loop.py:1043`.

Se agregaron **9 registros** a `/Users/lazynet/repos/lazy/lazy-knowledge/memory/github.com/lazynet/lazy-harness/failures.jsonl`, mediante apertura `O_APPEND`, sin modificar registros anteriores. Fecha de persistencia UTC: `2026-09-20T00:42:49+00:00` (2026-09-19 en America/Argentina/Buenos_Aires). El campo project es `external-hook-ownership`, el basename del worktree que exige el procedimiento; todos tienen type failure, tags coherence-audit y resolución pendiente de edición documental revisada por un humano.

Comprobación de efecto: **785 → 794 líneas**, **783902 → 790553 bytes**. El prefijo original se comparó byte a byte y quedó idéntico (SHA-256 `9720d4a87816c55b93b361bfb911b448f8f4c7a5b1e0d9651d9a43b0935e5514`). Las nueve líneas nuevas se parsearon y se contrastaron con los objetos preparados. El consumidor real `collect_existing_failures` pudo leer las nueve summaries; no se imprimió contenido de registros previos.

La comparación final del manifiesto dio **0 archivos tracked alterados por la auditoría**. No se editó ningún informe preexistente. El informe presente es nuevo. Resultado final: **BLOCKED** por F1; auditoría y persistencia completadas.

Fingerprint del diff tracked respecto de HEAD antes de escribir el informe: SHA-256 `9bf6263aa68e41511366e39f7a72e39fc8f4e9e406e38eb3de13bbaab74bd3ee`. La verificación final compara hashes de todos los archivos tracked con el manifiesto tomado antes de las escrituras de auditoría; no equivale a reconstruir un árbol limpio ni a descartar los cambios previos del usuario.

## Apéndice — reproducción aislada

Este script usa los módulos del worktree, fixtures temporales y un transporte simulado para la inferencia. El path del checkout principal en la prueba de identidad corresponde a esta ejecución; fuera de este entorno debe ajustarse al checkout principal real.

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib,json,os,subprocess
from lazy_harness.agents.base import HookEntry,HookOwnership
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.agents.codex import CodexAdapter
from lazy_harness.agents.copilot import CopilotAdapter
from lazy_harness.core.config import Config
from lazy_harness.hooks.builtins.pre_compact import parse_transcript,build_summary
from lazy_harness.hooks.builtins.engram_persist import _resolve_project_key
from lazy_harness.llm.invoke import _resolve_api_key,run_inference
from lazy_harness.monitoring.sink_setup import _resolve_remote
from lazy_harness.monitoring.db import MetricsDB

def apply(adapter,hooks,existing,servers=None):
    result=dict(existing)
    ops=adapter.plan_config(hooks,servers or {},result)
    for op in ops:
        if op.artifact is None: result.pop(op.relative_path,None)
        else: result[op.relative_path]=op.artifact.content
    return result,ops

with TemporaryDirectory(prefix='coherence-audit-') as td:
    root=Path(td)
    for adapter in (ClaudeCodeAdapter(),CodexAdapter(),CopilotAdapter()):
        entries={'session_start':[HookEntry(command='foreign-tool --session',ownership=HookOwnership.EXTERNAL)]}
        first,_=apply(adapter,entries,{})
        second,_=apply(adapter,entries,first)
        omitted,_=apply(adapter,{},second)
        assert first==second==omitted
        print('external_roundtrip',adapter.name,'one declaration; idempotent; survives omission')
    foreign={'matcher':'','hooks':[{'type':'command','command':'foreign-manual'}]}
    first={Path('settings.json'):json.dumps({'hooks':{'SessionStart':[foreign]}})}
    new,ops=apply(ClaudeCodeAdapter(),{'session_start':[HookEntry(command='lh hook context-inject --profile test')]},first)
    assert foreign in json.loads(new[Path('settings.json')])['hooks']['SessionStart']
    print('ADR031 foreign survives',ops[0].preserved,'dropped=',ops[0].dropped,'repaired=',ops[0].repaired)
    servers={'engram':{'command':'engram','args':['mcp']},'graphify':{'command':'graphify-mcp','args':[]}}
    for adapter in (ClaudeCodeAdapter(),CodexAdapter()):
        first,_=apply(adapter,{}, {},servers)
        omitted,ops=apply(adapter,{},first,{})
        assert omitted==first
        print('MCP uninstall',adapter.name,'no removal',len(ops),'ops')
    codex,_=apply(CodexAdapter(),{}, {},servers)
    assert '[mcp_servers.engram]' in codex[Path('config.toml')]
    print('ADR024 codex MCP translates config.toml')
    messages=[{'role':'user','content':'Please edit the audit fixture file now.'},{'role':'assistant','content':[{'type':'tool_use','input':{'file_path':'/tmp/audit-fixture.py'}}]}]
    for kind,records in [('flat',messages),('native',[{'type':m['role'],'message':m} for m in messages])]:
        p=root/f'{kind}.jsonl';p.write_text(''.join(json.dumps(r)+'\n' for r in records))
        parsed=parse_transcript(p)
        print('ADR010',kind,parsed,'summary=',repr(build_summary(*parsed)))
        assert bool(parsed[0]) == (kind=='flat')
    for cwd in (Path.cwd(),Path('/Users/lazynet/repos/lazy/lazy-harness')):
        old=Path(subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=cwd,text=True).strip()).name
        print('ADR029',cwd.name,'documented=',old,'actual=',_resolve_project_key(cwd))
    dummy=root/'secrets.env';dummy.write_text('AUDIT_TEST_API_KEY=dummy-audit-value\n');dummy.chmod(0o600)
    with patch.dict(os.environ,{},clear=True),patch('lazy_harness.monitoring.sink_setup.metrics_secrets_file',return_value=dummy):
        sink=_resolve_remote('http_remote',{'url_env':'AUDIT_TEST_API_KEY'}, {})
        llm=_resolve_api_key('','AUDIT_TEST_API_KEY')
        assert sink[0]=='dummy-audit-value' and llm==''
        print('ADR039 secrets fallback sink=True inference=False (synthetic value)')
    db=MetricsDB(root/'metrics.db')
    cfg=Config();cfg.monitoring.db=str(root/'metrics.db')
    with patch('lazy_harness.llm.claude.subprocess.run',return_value=subprocess.CompletedProcess([],0,'{}','')) as spawn:
        result=run_inference('synthetic audit prompt',role='distill',cfg=cfg,timeout=1)
        assert result.success
        print('ADR039 successful inference argv=',spawn.call_args.args[0])
    print('ADR039 metrics',len(db.query_stats()),'stats rows;',len(db.attribution_map()),'attribution rows')
    row={'session':'audit','date':'2026-09-19','model':'test','input':1}
    db.upsert_stats([row]);row['input']=9;db.upsert_stats([row]);rows=db.query_stats()
    assert len(rows)==1 and rows[0]['input']==9
    tables=[r[0] for r in db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print('ADR012 upsert overwrite idempotent; tables=',tables)
    db.close()
print('ALL PROBES PASSED')
```
