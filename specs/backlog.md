# lazy-harness backlog

Issues y mejoras pendientes. Este archivo es **interno** (no se publica al sitio MkDocs); el roadmap público vive en `docs/roadmap.md` y solo contiene los temas comprometidos a alto nivel.

Última revisión: 2026-09-16 — `/coherence-audit` antes de cortar 0.67.3. Piece A 39/39 al abrir, 43/43 al cerrar (dos archivos nuevos en `tests/docs/`, dos tests cada uno). Piece B: cinco hallazgos, **todos de prosa, ningún defecto de código**; el barrido de identificadores sobre los ADRs `accepted` volvió limpio una vez descartados los falsos positivos. El modo de falla dominante ya va por la **quinta reincidencia**, pero medido con precisión es más fino de lo que se venía anotando: de las ocho PRs desde #328, **siete sí tocaron `specs/`** (#330, #331, #332, #333, #334, #335, #336 — la única que no es #329), con un conteo de archivos bajo `specs/` de 5, 1, 4, 1, 5, 1 y 7 respectivamente. El patrón no es «el PR no toca specs», es **«el PR anota el ADR o el gate que cambió y no se anota a sí mismo en el ledger»**, y §Done es la superficie donde eso se ve: de las ocho, **sólo #330 le agregó entradas** —dos— y **ninguna de las dos la nombra**, que es exactamente por qué el PR más alto de §Done seguía siendo #328. #336 también editó este archivo (29 líneas) pero sólo una entrada de §Open, nunca §Done; las otras seis no lo tocaron. Medido igual por número de PR: `grep -rn '#329'` … `'#336'` fuera de `specs/archive/` devolvía cero para **siete de las ocho**, y la única excepción (#330, en ADR-041:227) la escribió otra PR. **Este párrafo ya se corrigió una vez**: la primera escritura decía «seis» y omitía a #333 de la lista, con el diffstat de #333 a la vista — el modo de falla que el propio header registra, una corrección de conteo aplicada a una mitad y no a la otra, esta vez en la escritura y no en la corrección. Los otros cuatro hallazgos: el log de revisiones salteaba la pasada del 2026-09-16 que cortó 0.67.2 y produjo #332/#333/#334; `isolation-gate.sh:247` nombraba «the known-gap set» como derivado seis líneas después de que su propio header lo declarara sin fuente; el shim `core/sync_claude.py` citaba ADR-031 por un rename que vive en [ADR-032](adrs/032-agent-adapter-completeness.md):136; y la entrada del falso positivo con backticks tenía un repro anterior a #335. **Dos correcciones al parte que originó esta pasada**, las dos medidas: los ADRs `accepted` son **39**, no 40 (41 archivos, uno `superseded-by: 036` y uno `proposed`), y los items sin entrada son **nueve**, no ocho — las ocho PRs más la release `v0.67.2`. Los dos hallazgos que son claims sobre el código quedan sostenidos por tests nuevos en `tests/docs/`, los dos rojos antes del arreglo; los otros tres son entradas narrativas de §Done y del log de revisiones, sin nada mecánico que afirmar. Un hallazgo **nuevo**, que no salió del audit, salió de correr el gate F7 para verificar el hallazgo 3 — y **sí se cierra acá**, con su diagnóstico corregido en revisión: no era «el gate sale 1 contra 0.67.2» sino que **el preflight del gate validaba el binario contra un PATH distinto del que les da a sus hijos**, así que la invocación por defecto no medía nada y reportaba 44 fallas que parecían una regresión de producción. Fabricó ese falso hallazgo **dos veces**, en las dos direcciones: un `PASS` tranquilizador el 2026-09-15 (esas corridas pasaban path absoluto) y un `FAIL` alarmante el 2026-09-16 (esta pasada, sin argumento). La primera versión de esta entrada compró la segunda lectura y registró un defecto de producción inexistente; ver §Done. Revisión previa: 2026-09-16 — `/coherence-audit` antes de cortar 0.67.2. Catorce hallazgos según el body de #332, repartidos por blast radius en tres PRs: #332 (seis, los que describen la migración de hooks), #333 (uno, `resolve_binary`) y #334 (nueve, sobre cinco ADRs `accepted`). **Los conteos de los tres bodies no cierran**: 6 + 1 + 9 = 16 contra los «fourteen» que declara #332, y los tres alcances son disjuntos por construcción — se anota como está medido en vez de elegir un número. Última revisión: 2026-09-15 — `/coherence-audit` antes de cortar 0.67.1. Piece A 39/39 (eran 38/38; #300 sumó uno). Piece B: siete hallazgos, **todos de prosa, ningún defecto de código**. El modo de falla dominante fue nuevo y vale como regla: **una corrección de conteo aplicada a una mitad del párrafo y no a la otra** — #300 corrigió «siete» a «ocho» en el encabezado y el cuerpo de su entrada y dejó vivo un «los siete» tres párrafos más abajo. Los otros seis: el roadmap era la única de las cuatro superficies que no registraba #295 (lo llevaban el backlog, ADR-031 y el design), que es justo la mitad que `/coherence-audit` **no** cubre y por la que el no-negociable #6 la nombra aparte; `docs/how/hooks.md` se contradecía a sí misma tras #300, nombrando `~/.claude/queue/` fijo en `:175,179` y «ningún path fijo» en `:784`; ADR-008 nombraba tres paths fijos que el código resuelve desde el runtime dir del agente **global**, nunca del profile; y §Done no tenía entrada para #298 ni #300. Cerrados todos en este PR, así que **no se appendeó nada a `failures.jsonl`**: el paso 4 del comando pide un record por hallazgo *no resuelto* y no quedó ninguno. Revisión previa: 2026-09-15 — `/coherence-audit` antes de cortar 0.67.0. Piece A 38/38 (eran 31/31; #296 sumó 7). Piece B: un hallazgo alto con defecto de código —`snapshot_targets` resolviendo el agente global mientras el deploy lo resuelve por perfil, la invariante que [ADR-041](adrs/041-multi-agent-hook-contract.md) §3 declaraba y que #292 dejó incumplida al mover uno solo de los dos readers— más cinco medios y tres bajos, todos de prosa. **Cuarta reincidencia** del patrón «el PR toca `src/` y `tests/` y ningún spec»: `grep -rn '#292|#294|#295|#296|0.67.0' specs/ docs/` devolvía cero. Cerrados en #297: el defecto y su test de acuerdo (que nunca seteaba un `agent` por perfil, así que pasaba con y sin el mecanismo), el párrafo *Known exception* de ADR-041, la `Evolution` de ADR-031 con el filtro por signals, la línea de Theme 5 y la de CI en el roadmap, las dos salidas nuevas del deploy en `docs/reference/cli.md`, la tercera narrowing del gate de `CLAUDE.md`, las cinco entradas de §Done de esta release, la mudanza `monitoring/hook_signals.py` → `hooks/signal_gaps.py` y la quinta superficie del gate (`docs/roadmap.md`), que el test de coherencia contaba y no cubría. Revisión previa: 2026-09-15 — `/coherence-audit` antes de cortar 0.66.0. Piece A 31/31; Piece B, doce hallazgos. A diferencia del step 3, los dos PRs de esta release (#289, #290) **sí** tocaron `specs/` en el mismo commit — #290 anotó ADR-004, ADR-024 y ADR-032 y reescribió la decisión 4 del diseño. El modo de falla que queda es más fino y vale como regla: **la nota `Evolution` se acotó al bloque de código citado y dejó viva la prosa de *Consequences* que describe el camino de ejecución**, y el grep que encontró los tres ADRs fue por el *símbolo* removido, no por el mecanismo — así que [ADR-006](adrs/006-hooks-subprocess-json.md), que describe el contrato de hooks entero sin nombrar ese símbolo, fue el único de los cinco que no se abrió, y era el que tenía cuatro claims muertos. Cerrados en esta pasada: el bloque de status del diseño multi-agente (que se contradecía a sí mismo sobre el step 4), la sección `Evolution` de ADR-006, las notas de ADR-004/024/019/032, `[profiles.<name>].agent` sin documentar en el config reference desde 0.65.0, la sección `Hook signals` de `lh doctor` sin documentar, y la entrada faltante del step 1 en §Done. **Los doce hallazgos NO se appendearon a `failures.jsonl`** — decisión explícita, quedan para revisión humana, así que el compound loop no los va a ver. Revisión previa: 2026-09-14 — `/coherence-audit` antes de cortar 0.65.0. Piece A (los tests de `tests/docs/`) 31/31; Piece B, nueve hallazgos de drift semántico, todos del mismo modo de falla: **los tres PRs del step 3 (#282, #283, #285) tocaron cero archivos bajo `specs/`**, así que cada referencia a `deploy/engine.py` que el step 3 movió al adapter quedó colgada. Cerrados en esta pasada, más el hueco de roadmap que el audit levanta aparte: el diseño multi-agente no figuraba en `docs/roadmap.md`, §Done no tenía los steps 0 ni 3, y la *Implementation sequence* no marcaba progreso. Tercera reincidencia del patrón «PR toca `src/` y `tests/` y ningún spec» — ver la entrada del step 2 más abajo, que ya se quejaba de él. Revisión previa: 2026-09-12 — pasada de coherencia sobre `docs/` y `specs/`: cuatro ADRs (035, 037, 038, 039) estaban `proposed` con el código shippeado y se pasaron a `accepted`; nueve claims de `docs/` describían comportamiento que el código no tiene. Revisión previa: 2026-09-10 — `/coherence-audit` cruzó 34 ADRs `accepted` contra su código. Cinco items que figuraban abiertos resultaron implementados: tres desde el 2026-08-17 (PRs #167 y #168) y dos del mismo día en que se anotaron. La deriva restante quedó en `failures.jsonl` bajo el tag `coherence-audit`, para revisión humana. Revisión previa: 2026-08-17 — análisis de los tres ejes de refactor (paridad Linux, capability registry, TUI).

---

## Done

- [x] **El preflight del gate F7 validaba el binario contra un PATH distinto del que les da a sus hijos, y por eso fabricó dos hallazgos falsos** — `LH_BIN="${1:-lh}"` (`:162`) defaulteaba a un **nombre pelado**, y el preflight de `:163` lo validaba con `command -v` contra el PATH del **padre**, donde `~/.local/bin` existe. Pero `invoke()` corre cada hook con `env -i` y `PATH=$CHILD_PATH`, que es `/usr/bin:/bin` (`:220`), donde `lh` **no está**. Medido directo: `env -i PATH=/usr/bin:/bin lh --version` → **exit 127, `env: lh: No such file or directory`**; con el path absoluto, exit 0. Y `invoke()` manda los dos streams a `/dev/null` (`:476`) y hace `return 0` **incondicional** (`:478`), así que ese 127 es invisible. Resultado: **cada invocación era un no-op silencioso**, las 44 aserciones fallaban con `no entry written anywhere the gate watches`, y la sección 11 —«nada se movió fuera del config dir del profile invocado»— pasaba entera **porque no corrió nada**, no porque nada se escapara.

    **Los dos exit codes, medidos contra el binario 0.67.2 instalado, antes del fix:** sin argumento → `EXIT=1`, `FAIL — 44 assertion(s) failed`; con `"$(command -v lh)"` → `EXIT=0`, `PASS`, mismo scope (11 asserted, 7 skipped, 18 registered). El binario y el árbol son idénticos en las dos corridas: lo único que cambia es la forma del argumento.

    **Fabricó el mismo hallazgo falso dos veces.** La primera fue al revés: el handoff del 2026-09-15 reportó `PASS` exit 0 contra 0.67.2 porque esas corridas pasaban path absoluto, así que el gate parecía sano. La segunda fue el 2026-09-16, cuando esta misma pasada lo corrió sin argumento y lo registró como «el gate F7 sale 1 contra el binario 0.67.2 instalado» — un defecto de producción que no existía. Las dos lecturas salían del mismo `:162`.

    **Producción está sana, y la prueba es el propio gate**: con el fix, la invocación por defecto (nombre pelado, sin argumento) contra `lh 0.67.2` instalado sale `EXIT=0`, `PASS`, `binary: /Users/lazynet/.local/bin/lh (lazy-harness, version 0.67.2)` — el routing por profile funciona.

    **El fix**: `:162-163` resuelve el argumento con `command -v` y **exige un path absoluto**, con `exit 2` y un diagnóstico que nombra el mecanismo si no resuelve. Un nombre pelado se absolutiza; un path **relativo** —que `command -v` acepta y devuelve tal cual, y que el hijo pierde porque hace `cd`— ahora se rechaza. Ese es exactamente el hazard que el gate F8 ya guardaba (`./fake-translate-mapped.sh` relativo → exit 2) y que F7 nunca había cerrado.

    **Medición antes/después con el mismo stub** (un `lh` de shell que appendea una línea por invocación, con el path del marcador horneado en el archivo — `env -i` le borra cualquier env var, y ese fue un falso negativo propio en el camino): **0 invocaciones de hook llegaban al binario antes, 88 después**. El gate sigue saliendo 1 contra el stub, que es correcto: un stub no escribe evidencia.

    **Tests**: cuatro en `tests/integration/test_f7_gate_binary_resolution.py`, sobre el script real, **0.01s cada uno**. Cubren la **resolución sola** y no el gate entero, a propósito y dicho: correr el gate completo contra el stub cuesta ~17s, veinte veces el test más lento de la suite (0.80s). Acotan la corrida con `F7_GATE_ROOT` apuntando a un archivo, así el script sale 2 pocas líneas después del bloque del binario y nunca llega ni al read del registry ni a una invocación. El par que carga el peso es *relative* y *bare*: nada no-absoluto pasa, y un nombre pelado sí — juntos dicen que el pelado se absolutizó, porque una respuesta absoluta es la única forma de pasar el guard. Fase roja real: el caso *relative* fallaba nombrando el error de `F7_GATE_ROOT`, que es la prueba de que el argumento había sido aceptado.
- [x] **Gate F8: qué builtins quedan inertes cuando el payload lo parsea el adapter de Codex** — la opción 1 que el entry del gate F7 dejó abierta, ahora en `specs/gates/f8/`. F7 dice en su propio header que **no** mide la traducción; este es ese segundo gate. **Inerte no es ausente, y ahí está el punto**: `hooks/signal_gaps.py` omite `session-export` y `stop-context-rotate` bajo Codex y el deploy **nombra** cada omisión — eso es un gap declarado y visible. Un builtin inerte es lo contrario: deployea, se cablea, corre, sale 0 y no aplica nada; verde porque no puede fallar. Alcance **derivado, nunca tipeado**: cada nombre que devuelve `list_builtin_hooks()`, partido por `BuiltinHookSpec.operations`, con un payload por operación declarada a través de los dos adapters shippeados, comparando `native_name`, `operation`, `edits` y `reads`. Por operación y no por hook porque `pre-tool-use-security` declara tres y «qué operación representa a este hook» no tiene respuesta en el registry. Inertes los cinco: `post-tool-use-format`, `pre-tool-use-read-size`, `pre-tool-use-memory-size`, `post-tool-use-sync-claude` y `post-tool-use-ansible-lint`. Vivos: `pre-tool-use-git-scope` (Codex mapea `Bash`) y `pre-tool-use-security`. **El gate corrigió la cuenta que lo encargó.** El backlog sostenía que los cinco fallan por **dos** mecanismos y que ensanchar `CodexAdapter._TOOL_OPERATIONS` reviviría a los dos que gatean en `operation`: es cierto sobre dónde retorna *primero* cada hook y falso sobre lo que sigue. Medido **corriendo los hooks, no leyéndolos**, el gate de operación es el primero de **dos**, los cinco necesitan la estructura, y `fake-translate-operations-only.sh` —que emula exactamente ese cambio— **pasa**: el fix del mapeo es un no-op, no un fix parcial, y le entrega un gate verde a quien lo shippee por la misma razón por la que ya estaba verde. Falla en las dos direcciones contra una expectativa checkeada en el repo, y la cobertura sale 2 **antes** de alimentar un solo payload si un builtin se cae de toda lane o una entrada esperada quedó vieja — un nombre que nunca se alimenta no puede fallar. Discriminación medida y no predicha: cuatro traductores, uno de los cuales falsificó la predicción, más tres roturas a mano, cada una restaurada **a mano** y nunca con `git checkout`. Precondición **abierta y dicha en el header del gate**: la prueba del dialecto real de Codex para un edit, en un `codex-evidence.md`, no está hecha — intentada el 2026-09-16 contra `codex-cli 0.154.0` con un `CODEX_HOME` descartable, rechazada por tool policy antes de que corriera `codex exec`. Las dos mitades de cada comparación son objetos Python, lo que es sólido para la pregunta que se hace y no dice **nada** sobre el binario. PR #336, mergeado el 2026-09-16; sin release todavía.
- [x] **Las reglas del denylist de seguridad matchean sólo en posición de comando** — doce de las catorce `BLOCK_RULES` matcheaban su token en **cualquier** parte del string del comando: escribir una oración que apenas nombrara un comando destructivo salía 2. Medido tres veces, y el caso más filoso **no tenía heredoc** —un argumento citado a una herramienta que escribe texto en un pane—, así que un fix acotado a cuerpos de heredoc no lo hubiera prevenido. El discriminador no fue una decisión de diseño nueva: `_COMMAND_START` ya existía en `pre_tool_use_security.py`, con el comentario que explica por qué, aplicado a **una regla de catorce** (`rm`), y la matriz de tests ya había ratificado el principio para esa una. Hacían falta **dos** piezas y no una: anclar dice dónde *empieza* un comando, y sacar el newline de las siete clases de argumento dice dónde *terminan* sus argumentos — el fixture del heredoc seguía fallando con el ancla sola, bajo otra regla, porque `cat` sí está en posición de comando ahí y `[^|;&]*` excluía pipes y punto y coma pero no newlines. `sql` queda exento a propósito y con un property test que lo nombra: el token de borrado de tabla nunca es el ejecutable, es el argumento de uno (`psql -c "…"`), así que anclarlo borraría la regla en vez de acotarla; el costo —prosa que lo nombra sigue rechazada— está documentado en `docs/how/hooks.md`, y bloqueó dos escrituras de esta misma entrada el 2026-09-16. **Mutación, 44 casos por el mismo harness contra `main` y contra la rama**: falsos positivos 13 → 4, escapes 3 → 4. **Nueve falsos positivos eliminados, ninguno introducido.** El único escape net-new —el token sentado después de un `echo` dentro de una sustitución de comando— se cierra sólo agregando `echo` a la lista de wrappers, lo que bloquearía `echo 'rm -rf /tmp'`, un caso que la suite existente afirma que debe **permitirse**; el trade lo fuerza la suite, no se eligió alrededor de ella. El primer corte del fix dejaba pasar **cuatro** cosas que `main` sí atajaba (indentación, `bash -lc`, `python3 -c`, `eval`); las encontró la corrida de mutación y hoy son casos de regresión con el comentario de dónde salieron. Ablación pieza por pieza, restaurando por write-back del texto en memoria y nunca con `git checkout`: seis de siete cargaban peso, y la séptima no tenía test capaz de distinguirla —lo que realmente ataja `os.system("…")` es el operador `(` más la comilla opcional— así que se borró en vez de taparla con un test escrito a medida. El harness de ablación tenía un bug propio que vale registrar: dos ablaciones remueven exactamente siete bytes cada una y CPython valida un `.pyc` por (mtime-segundos, tamaño), así que corridas back-to-back dentro del mismo segundo ejecutaban en silencio el bytecode de la anterior. PR #335, mergeado el 2026-09-16; sin release todavía.
- [x] **Nueve claims a la deriva en cinco ADRs `accepted`** — salidos de `/coherence-audit` Piece B, re-verificados uno por uno antes de editar. La clasificación no se decidió por el estado actual de los archivos sino con `git log -S`, comparando **cuándo llegó el código contra cuándo se tipeó la prosa** — una distinción que no se ve desde ninguno de los dos archivos y que dio vuelta la clasificación esperada dos veces. Bullet de `Evolution` (el doc tenía razón cuando se escribió, el código se movió): ADR-031:102 `post-compact` —el builtin **sí** existió, lo agregó `64fff7e` (#34, ADR-020) y lo borró ADR-036 el 2026-08-18 porque `PostCompact` sólo devuelve un mensaje de display—, ADR-031:38-40 el literal de `DEFAULT_HOOKS` —computado en import por `_derive_default_hooks()` desde #184—, ADR-033:89 el bloque del Protocol de `llm/base.py`, y ADR-023:20 `graphify mcp`. Corregidos **en el lugar** (el claim nunca describió código shippeado): ADR-031:128-131 «la omisión se imprime» —tipeado el 2026-09-15 en #297 cuando el filtro silencioso `_SYSTEM_DOC_HOOKS` estaba en `src/` desde el 2026-05-29 (#88), o sea sobre-afirmado el día que se escribió—, ADR-012:41 «no-op vía `INSERT OR IGNORE`» —`ingest.py` llama `upsert_stats` desde el primer pipeline, un día antes de que el ADR aterrizara en `specs/`, y un overwrite no es un no-op—, ADR-033:121 el argv de `ClaudeBackend` —que nunca describió ningún estado shippeado— y ADR-035:71 «derivado de `_BUILTIN_HOOKS`», que contradecía el propio header `**Implemented:**` del ADR. No reproducidos: **ninguno**, los nueve reprodujeron. Cada identificador de la prosa nueva se grepeó de vuelta contra `src/` y resuelve; la única excepción es `userDisplayMessage`, que es la forma del payload de Claude Code y no un símbolo nuestro, así que el texto lo atribuye al hallazgo de ADR-036 en vez de nombrarlo como símbolo del framework. PR #334, mergeado el 2026-09-16; sin release todavía.
- [x] **El guard de recursión de `resolve_binary` se registró como un orden, no como un filtro** — hallazgo de `/coherence-audit` Piece B contra el gate «prosa que nombra un mecanismo se grepea contra el código, en las dos direcciones»: ADR-004:50, el docstring del Protocol `AgentAdapter.resolve_binary` y el de `ClaudeCodeAdapter.resolve_binary` afirmaban los tres un guard de recursión **que no existe**. `claude_code.py` prefiere el dir del version manager y después devuelve `shutil.which("claude")` **sin filtrar**, y `cli/run_cmd.py:101` hace exec de ese resultado, así que un `claude` en PATH que envuelva `lh run` es una fork bomb. **Aceptado en vez de filtrado**, por dos medidas y no por gusto: el filtro obvio rompe instalaciones reales —`~/.local/bin/lh` y `~/.local/bin/claude` viven en el **mismo** directorio, que es el layout de `uv tool install` que el gate de este repo exige, así que saltear candidatos en el dir del entrypoint rechazaría el binario genuino y dejaría `LaunchError("binary-not-found")` en cualquier máquina sin `~/.local/share/claude/versions`—; y la recursión no es alcanzable en una instalación real, porque necesita el version dir ausente **y** un wrapper ejecutable en PATH, y la única re-entrada que existe es un alias de zsh que `shutil.which` no puede ver. Las variantes del filtro sin el falso positivo no atajan nada: comparar realpath contra el `lh` corriendo pierde un shim que *llama* a lh, y olfatear el cuerpo buscando `lh run` es TOCTOU y falla contra un wrapper compilado. Dos tests, los dos plantando un shim **real** en PATH en vez de stubbear `shutil.which` —un stub contesta antes de que se compare ningún path, así que no ejercitaría el guard—, y el segundo pinnea el riesgo aceptado: cerrarlo más adelante significa cambiar un test que afirma que está abierto. Fase roja a mano, porque los dos pinnean comportamiento existente. PR #333, mergeado el 2026-09-16; sin release todavía.
- [x] **0.67.2 cortada — el step 5 entero en una release** — release-please la cortó desde #303 el 2026-09-16, tag `v0.67.2`. Lleva las migraciones de builtins al contrato `HookEvent` (#309→#327), el colapso del flag de migración y su segundo dispatch (#330), los fixes de resolución por profile de los readers de queue y métricas (#313) y del timeout de exec disparado sobre el progreso del agente y no sobre un reloj de pared (#321), el gate de cobertura de matchers keyado en operaciones declaradas y no en texto del fuente (#320), la serialización del contexto de `PreCompact` como texto plano (#305), y siete entradas de `Documentation` que incluyen #329, #331 y #332. **El no-negociable 6 se cumplió**: `/coherence-audit` corrió antes del corte y su salida son #332 y sus dos PRs hermanas, #333 y #334 — estas dos mergeadas después del corte, así que van a la próxima release.
- [x] **Seis claims de ADRs y gates que las migraciones del step 5 dejaron viejos** — Piece B del `/coherence-audit` corrido antes de cortar 0.67.2, no-negociable 6. La pasada dio catorce hallazgos según el body de esta PR y se repartieron por blast radius; estos seis son los que describen **la migración misma**, porque 0.67.2 es la release que la shippea y sus propios documentos no deberían describir el mundo anterior a ella. Dos altos en ADR-006 —«true today for the migrated three, and step 5 is the remaining fifteen» con los dieciocho ya migrados, y «sólo `context-inject` y el block log de `pre-tool-use-security` leen el profile»— y uno en ADR-008:29-41, cuya nota de paths llamaba trabajo abierto a un routing que cerró en #314→#328. Tres medios: ADR-006:92-93 (`pre-tool-use-git-scope` «sigue saliendo 2 directo», cuando devuelve `HookDecision` desde #326), `specs/adrs/README.md:53` (la fila de ADR-041 describía un known-gap set derivado del flag borrado) y `specs/gates/f7/report.md:4` (el párrafo que declara congelado al resto del archivo hacía su propio claim en presente). **Cada hallazgo se re-midió acá antes de tocar una línea**, no se transcribió del reporte, y eso produjo una corrección al reporte mismo: citaba `tests/unit/hooks/test_builtin_registry.py:52`, que es una línea en blanco — la prosa ahora cita el test **por nombre**, porque un número de línea a la deriva es justo el modo de falla que este audit existe para atajar. Los cuerpos de ADR se tratan como registro histórico: ADR-008 conserva lo que decía y **por qué**, con el cierre appendeado, y sólo las superficies vivas se corrigieron en el lugar. Cada identificador de la prosa nueva se grepeó de vuelta contra `src/` (`agent_dir_for` 16, `agent_for_profile` 10, `agent_runtime_dir` 10, `HookEvent` 27, `HookDecision` 23): nada inventado. Los hallazgos originales se appendearon a `failures.jsonl` con el tag `coherence-audit` (505 → 507). PR #332, mergeado el 2026-09-16; entra en 0.67.2.
- [x] **`CLAUDE.md` podado moviendo la evidencia de los gates al ledger de incidentes** — estaba en 11510 bytes contra un techo de 12000: **490 bytes de margen, menos de dos gates**. Pasado el techo el archivo se ignora entero y en silencio, así que los 23 gates se hubieran perdido de una sola vez. Quedó en **10303 bytes / 52 líneas**, ~1697 de margen, unos seis gates a la densidad actual. Ningún gate removido, ningún check removido: `specs/incidents.md:3` ya declaraba el corte —«`CLAUDE.md` carries the check — the thing to run. This file carries the evidence.»— y los gates habían derivado cargando prosa de evidencia que el ledger ya tenía textual, así que la poda **restaura el contrato declarado** en vez de recortarlo. Verificado en las dos direcciones: 23 gates antes, 23 después, en el mismo orden, 1:1 contra las 23 secciones de `specs/incidents.md`, cero sin par de ningún lado, y cada cláusula removida grepeada contra el ledger y confirmada presente. El único hecho genuinamente ausente del destino —que `specs/adrs/README.md` es el índice y define el vocabulario de Status— se agregó al árbol de `specs/workflow/layout.md`. PR #331, mergeado el 2026-09-16; entra en 0.67.2.
- [x] **Ningún builtin resuelve su agente globalmente** — cerrado el inventario completo *Ocho builtins resuelven su `hooks.log` globalmente, más el worker*. Las diez resoluciones globales salieron una por commit con las migraciones del step 5 (#314→#328), y la última, `pre-tool-use-memory-size`, en #327. **Medido por mecanismo, no por grafía**: `test_no_builtin_resolves_its_agent_globally` (`tests/unit/hooks/test_builtin_contract.py`) camina el AST de cada módulo de `builtins/` y falla ante cualquier `ast.Call` a `get_agent`, en las dos formas —`get_agent(...)` y `registry.get_agent(...)`—; un grep de `get_agent("claude-code")` encontraba siete de diez y perdía `engram_persist.py` y `pre_compact.py`, que lo escribían `get_agent(cfg.agent.type if cfg is not None else "claude-code")`. Hoy da `{}`. El test **nació verde**, así que su fase roja se hizo a mano: reintroducida la llamada en `post_tool_use_format.py`, el test nombró archivo y línea (`{'post_tool_use_format.py': [32]}`), y se removió a mano — nunca `git checkout`, que se hubiera llevado la implementación sin commitear. `_shared.py` queda excluido a propósito: su único `get_agent` es la degradación sin-config documentada de `agent_dir_for`. El worker (`knowledge/compound_loop_worker.py:107`) **no** cierra y no es un olvido: resuelve global sólo en la rama `not profile`, que es «nadie dijo» y tiene que resolver como `agent_runtime_dir` — con profile en mano llama `agent_dir_for`. `profile_name()` tampoco se borra: sobreviven cuatro llamadas en tres módulos no-builtin, y la de `hooks/runner.py:resolve_profile` es comportamiento vivo, no compatibilidad —los dos entry points declaran `--profile` con `default=None` y `cli/doctor_cmd.py` llama `resolve_profile(None)` directo. Su docstring ahora los nombra. Tasks 19, 20 y 21 del step 5. PR #330, mergeado el 2026-09-16; entra en 0.67.2 — la misma PR cerró la **task 20** (`execute_hook` dispatcha en `hook.is_builtin` y ya no en `BuiltinHookSpec.migrated`) y la **19**, que borró el campo, `PRE_RUNNER_AGENT`, `builtin_migrated()`, la rama de import-and-call de `cli/hooks_cmd.py`, `deploy/engine._warn_unmigrated` y `tests/unit/test_deploy_unmigrated_hooks.py` — que venía skippeándose sola desde la última migración y era los cuatro skips de la suite. La fase roja de la task 20 sólo existe registrando un spec con `migrated=False` a mano: todo builtin shippeado lo traía en `True`, así que un test que camina `list_builtin_hooks()` pasa antes tan fácil como después y no cubre nada — queda al lado como pin de regresión y etiquetado como tal. `isolation-gate.sh` derivaba sus dos sets de `builtin_migrated()`; sin flag no hay set de gaps, así que en vez de dejar un bloque permanentemente vacío el script pasó a afirmar **cobertura**: las dos lanes más `SKIPPED_HOOKS` deben dar cuenta de cada nombre que devuelve `list_builtin_hooks()`, y cualquiera de las dos fallas sale 2 antes de correr nada.
- [x] **Dos claims a la deriva en `docs/how/hooks.md`** — corregidos contra el código como está hoy. `stop-verify-guard`: la página decía que rechazar el deploy de un hook cuyas señales declaradas el agente no puede entregar es «un mecanismo separado que todavía no existe», y `_report_omitted` (`deploy/engine.py:173`, llamado desde `_hook_entries_for` en `:267`) hace exactamente eso por profile e imprime `· <hook> omitted in '<profile>': agent '<agent>' does not deliver <signals>`, resuelto desde `gaps_for_profile`. La prosa corregida nombra el mecanismo y conserva el fallback en runtime donde sigue aplicando: `builtin_signals` devuelve el set vacío para cualquier cosa fuera del registry, así que un hook de usuario se instala igual y sólo puede abstenerse de bloquear. `pre-tool-use-memory-size`: ya no es sólo MEMORY.md — `CLAUDE.md` tiene su propio par de umbrales (`CLAUDE_MD_MAX_LINES = 200` / `CLAUDE_MD_MAX_BYTES = 12_000`), su propio gate de path (`_is_claude_md_path`) y su propio remedio apuntando a `lh memory rightsize`; `load_claude_md_thresholds` lee `[hooks.pre_tool_use]` fail-soft mientras el par de MEMORY.md sigue hardcodeado. La fila `pre_tool_use` de la tabla resumen decía lo mismo viejo y se arregló también. **Reportado y no cambiado**: el docstring de `load_claude_md_thresholds` y el comentario de `CLAUDE_MD_MAX_*` describen el override como «per profile», pero `config_file()` resuelve un único `config.toml` compartido desde `config_dir()` — un valor para todos los profiles. Los docs dicen lo correcto; los comentarios del fuente siguen diciendo «per profile». PR #329, mergeado el 2026-09-16; entra en 0.67.2.
- [x] **El gate F7 dejó de suprimir la evidencia que mide — opción 2, y la entrada del backlog estaba mal en dos puntos** — el gate corría **un** profile throwaway con `agent = "codex"` y le daba a todos los hooks un payload de Claude Code; desde el step 5 el parseo pasa por el adapter del profile invocado, así que los hooks que gatean en `operation is MODIFY_FILE` se abstenían y la sección 10 leía «no escribió nada» como fuga. Cerrado con la **opción 2**: dos lanes, `agent = "codex"` para los builtins que no declaran `operations` y `agent = "claude-code"` con `config_dir` propio para los que sí, derivados de `BuiltinHookSpec.operations` — el único read privado del script, mismo keying que `tests/unit/test_hook_matcher_coverage.py:82` (#320). La divergencia global-vs-profile se conserva en las dos: el adapter en la codex, el `config_dir` en la claude. **La entrada estaba equivocada en dos puntos y los dos cambian el arreglo.** Primero, decía «esos cinco sí tienen sink bajo el agent runtime dir, a diferencia de `stop-verify-guard`» y es **falso para los seis**: `user-prompt-goal` sinkea a la MetricsDB vía `resolve_db_path()` (`user_prompt_goal.py:73`) —el motivo textual de `stop-verify-guard`—, `herdr-context-gauge` y `stop-context-rotate` a un stamp bajo `tempfile.gettempdir()` (`herdr_context_gauge.py:123`, `stop_context_rotate.py:48`), `session-start-preflight` no escribe nada y contesta por stdout, y `post-tool-use-sync-claude` —migrado en #324, después de que se escribiera la entrada— lo dice en su propio docstring. Van a `SKIPPED_HOOKS` con el criterio ya documentado del gate, no como excepción al contrato; las dos resoluciones que sí valen quedan abiertas arriba, en canales que F7 no mira. Segundo, «los cinco hooks que leen `tool`» es más ancho que el defecto: Codex mapea `Bash -> RUN_COMMAND`, así que `pre-tool-use-security` **pasa** bajo el adapter codex. **Corrección 2026-09-15, medida contra el set completo:** «sólo los `post-tool-use-*` caen» también es falso — caen cinco, y `pre-tool-use-read-size` y `pre-tool-use-memory-size` están entre ellos. El inventario medido está en *El gate F7 mide aislamiento de directorios y no traducción de wire format*, abajo. Conteos: **28 aserciones falladas antes** (siete hooks × dos escenarios × dos modos; eran 20 cuando se escribió la entrada, #323 y #324 sumaron dos hooks), **0 después**, 36 aserciones en verde. Los dos fixtures dan sus verdicts opuestos —`fake-lh-fixed.sh` exit 0, `fake-lh-security-only.sh` exit 1— y eso **no alcanzaba como prueba**: los dos ya los daban contra el gate roto, porque `fake-lh.sh` logueaba una línea por hook en todo payload y era estructuralmente ciego a un hook que se abstiene. Ahora emula la abstención del adapter, y con eso el fixture *fixed* falla 12 aserciones contra el gate viejo — la mitad adapter del defecto, aislada de la mitad no-sink por aritmética. Sección 11d nueva, que es lo que dos profiles vivos habilitan: «escribió bajo un profile» y «escribió bajo **el** profile invocado» eran indistinguibles con uno solo; `profiles.default` nombra la lane codex a propósito y un shim que resuelve el default en vez de `--profile` la dispara. La opción 1 —medir la traducción— queda abierta arriba como gate propio. Cerrado en `fix/f7-gate-measures-isolation-only`.
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
- [x] **Registro de los diez hallazgos del audit de código 2026-09-16** — `specs/codebase-audit-2026-09-16.md` (razonamiento interno, no `docs/`, por `specs/workflow/layout.md`) documenta F1–F10; F1/F2 (Alta) entran en este archivo como nueva sección `## Open — Prioridad ALTA` sin fix propuesto (va en una tanda aparte); F3/F5/F6/F7/F9 (Media) en Prioridad MEDIA, cada uno atribuido a la prueba del audit y no re-verificado en el PR; F10 (Baja) en Prioridad BAJA. F4 y F1 se re-verificaron a mano contra `HEAD` antes de archivarse. F8 (el launcher esquivando `agent_for_profile`) no es fila nueva — se pliega como evidencia medida al item ya abierto de `docs/roadmap.md` ("Make agent selection per profile throughout"), que la lane paralela de #342 estaba trabajando. Los dos strings que demuestran los bypasses del guard de seguridad (F1) se redactaron a descripción de mecanismo antes de stagear el archivo — `grep -rn` de los dos strings sobre el árbol da cero. PR #340, mergeado el 2026-09-16; entra en 0.68.0.
- [x] **Multi-file config planning — step 7, ADR-042** — [ADR-042](adrs/042-multi-file-config-planning.md) registra las decisiones. `plan_config` ya devolvía varios targets, pero los deletes eran alcanzables solo desde el motor y no desde ningún adapter, y el abort por mtime/size estaba ausente (`grep 'st_mtime\|st_size'` sobre `deploy/` y `agents/` no daba nada). Se agregó el abort — el engine graba `(st_mtime_ns, st_size)` de cada target al leer, incluidos los que no existen, y levanta `ConfigTargetChangedError` para todo el plan si algo se movió entre planificar y aplicar — más `CodexAdapter` escribiendo `[mcp_servers.<id>]` en el propio `config.toml` de Codex (mergeado con tomlkit, sin tocar `[projects.*]`) y el retiro de `hooks.json` cuando corresponde. `config_targets()` de `CodexAdapter` se ensanchó; `deploy/engine.py` y `deploy/snapshot.py` heredan el ensanche sin re-listar paths propios. PR #341, mergeado el 2026-09-16; entra en 0.68.0.
- [x] **El agente resuelto por perfil en todo el árbol — step 6** — los dos readers de `deploy/`, el launcher (`agents/launch.py:65`, ahora `agent_for_profile(cfg, resolution.name)`) y los readers de hook/worker/CLI resuelven el agente por perfil; `Capability` ganó un campo `per_profile` reportado por `lh doctor`. Lo que queda, medido el 2026-09-16 (`grep -rn "get_agent(" src/ | grep -v hooks/builtins`): cinco sitios siguen leyendo `cfg.agent.type`. `cli/memory_cmd.py:250` y `knowledge/compound_loop_worker.py:115` están detrás de un chequeo explícito de "no hay perfil resuelto" (`if not profile:` / `resolve_profile(None)` vacío) antes de caer al global. `monitoring/statusline.py:44` comparte la misma forma de fallback (`cfg.agent.type if cfg is not None else "claude-code"`) pero su función no recibe parámetro de perfil en absoluto, así que ahí no hay una rama de "sin perfil" — es el único camino. `cli/profile_cmd.py:308` y `cli/doctor_cmd.py:474` leen `cfg.agent.type` sin ternario ni rama de perfil. Si eso cierra el step 6 o es el alcance remanente queda para revisión humana — ver [ADR-041](adrs/041-multi-agent-hook-contract.md) §3. PR #342, mergeado el 2026-09-16; entra en 0.68.0.
- [x] **`system_docs()` reemplaza `system_doc_name()` — step 8, ADR-043** — [ADR-043](adrs/043-system-docs-by-role.md) registra la decisión. El método del Protocol pasa de nombrar un único archivo de sistema a devolver los documentos del agente por rol, lo que un adapter con más de un archivo de sistema necesita. `agents/base.py`, `agents/claude_code.py`, `agents/codex.py` y `agents/registry.py` migran; `core/sync_agent_md.py` resuelve el nombre por rol en vez de uno fijo. PR #344, mergeado el 2026-09-16; entra en 0.68.0.
- [x] **La tabla `launches` — el numerador que el ratio del kill-criteria necesitaba** — la tabla append-only del diseño (`:281-335`, `entry ∈ 'run' | 'exec'`) no existía; `grep -rn "CREATE TABLE launches" .` sólo matcheaba el bloque SQL del propio diseño. `monitoring/launches.py:record_launch` es el único write path de los dos launchers, fail-soft por construcción (incluido el `ValueError` de un `entry` desconocido), escrito después de toda validación y de la desviación por `--dry-run` (`cli/run_cmd.py` antes de `os.execvpe`, `cli/exec_cmd.py` antes del spawn y después del rechazo de prompt vacío). `MetricsDB.launch_to_session_ratio(days=...)` implementa la mitad de lectura que el diseño (`:1035-1056`) daba por no-computable: la falta era la del numerador, no la de la medición, así que el helper devuelve `ratio: None` sin denominador — nunca un cero fabricado — con las dos mitades cortadas al mismo instante para no dividir una acumulación contra una ventana. `docs/architecture/overview.md:166` declaraba un schema de una sola tabla, falso desde `session_attribution`; corregido a las seis. 11 tests nuevos; mutation check borrando cada llamada a `record_launch` a mano. PR #346, mergeado el 2026-09-16; entra en 0.69.0.
- [x] **`CodexAdapter` para real — step 9, ADR-044, y cuatro fixes en vez de dos** — el evidence (`specs/designs/codex-evidence.md`) cerró el dialecto de edición de Codex: elige de forma no determinística entre `Bash` con un heredoc de python y su `apply_patch` nativo, que llega con `tool_name: "apply_patch"` y el blob de patch bajo `tool_input.command` — la misma clave que usa `Bash`. El evidence nombraba dos fixes necesarios; shippearlos encontró un tercero y un cuarto: `_TOOL_OPERATIONS["apply_patch"] = MODIFY_FILE`, `"apply_patch"` en `_shared.EDIT_TOOLS` (una sola respuesta importable, asertada por identidad y no por igualdad — antes cuatro copias), `_parse_patch` armando `FileEdit`s desde el blob, y `pre_tool_use_memory_size._projected_text`, que ramifica por nombre de tool y se quedaba mudo con los otros tres puestos — un cuarto gate que la tabla de reconciliación del evidence no nombraba. Decisiones: `ToolCall.command` queda sin setear para `apply_patch` (el blob es contenido de edición, no algo a ejecutar); una sección `*** Delete File:` no produce ningún `FileEdit` (ver entrada nueva de Prioridad MEDIA); `pre-tool-use-read-size` queda deliberadamente sin ensanchar (gatea `READ_FILE`, no edits); y `lh doctor` reporta dos estados donde Codex tiene tres — `untrusted`, `unknown` y entries huérfanas, nunca `trusted`, porque leer `trusted_hash` de vuelta sólo prueba que se guardó un hash, no que siga vigente. **Techo medido, no implícito:** el path `Bash` es estructuralmente no-gateable como edit — `tool_input` es un script de shell arbitrario sin path que extraer — así que un adapter completamente arreglado gatea sólo la mitad de los edits de Codex; ADR-044 lo registra como consecuencia, no como TODO. El gate F8 se re-midió, no se predijo: cuatro builtins salen de `EXPECTED_INERT` y `fake-translate-operations-only.sh` pasa de exit 0 a exit 1. 4029 passed (baseline 3970 en `7169ccc`). PR #348, mergeado el 2026-09-16; entra en 0.69.0.
- [x] **F1 cerrado — el guard de seguridad evalúa por segmento de shell y las reglas de git matchean a través de opciones globales reconocidas** — `should_block` ahora evalúa por segmento (`;`, `&&`, `||`, `&` bare, newline), así que un `allow_pattern` sólo rescata el segmento que matchea; y las reglas de git matchean a través de opciones globales reconocidas (`-C`, `-c`, `--git-dir=`, `--work-tree=`, `--no-pager`) vía `_normalise_git_globals`. Límites conocidos registrados en la entrada nueva de Prioridad MEDIA. PR #347, mergeado el 2026-09-16; entra en 0.69.0.
- [x] **Los cinco builtins inertes bajo Codex ya no lo están, y la mitad que falta es estructural** — el probe contra `codex-cli 0.154.0` (2026-09-16, seis corridas, `specs/designs/codex-evidence.md`) cerró el dialecto: Codex elige de forma no determinística entre `Bash` con un heredoc de python y su `apply_patch` nativo, que llega con `tool_name: "apply_patch"` y el blob de patch bajo `tool_input.command` — la misma clave que usa `Bash`. Hicieron falta **cuatro** arreglos, no dos: la entrada en `_TOOL_OPERATIONS`, `"apply_patch"` en `_shared.EDIT_TOOLS` (una sola respuesta importable, antes cuatro copias), el parser del blob a `FileEdit`, y `_projected_text` de `pre-tool-use-memory-size`, que ramifica por nombre de tool y se quedaba mudo con los otros tres puestos — un cuarto gate que la tabla de reconciliación del evidence no nombra. El gate F8 ahora alimenta cada pierna con su propio dialecto y cuatro builtins salieron de `EXPECTED_INERT`; `fake-translate-operations-only.sh` pasó de exit 0 a exit 1, que es la prueba de que el parser es la parte que carga. **Techo medido:** el path `Bash` es estructuralmente no-gateable como edit — `tool_input` es un script de shell arbitrario sin path que extraer — así que un adapter completamente arreglado gatea la mitad de los edits de Codex. ADR-044 lo registra como consecuencia, no como TODO. `pre-tool-use-read-size` sigue inerte a propósito: gatea `READ_FILE` sobre `tool.reads`, y el dialecto de lectura de Codex no lo tocó ningún probe. Probado el 2026-09-16 (probes 5-8): no hay dialecto de lectura que gatear bajo Codex — ver la entrada de §Done más abajo. PR #348, mergeado el 2026-09-16; entra en 0.69.0.
- [x] **`pre-tool-use-read-size` sigue inerte bajo Codex, pero ahora es un límite de diseño medido, no un hueco de evidencia** — probe 7 (`specs/designs/codex-evidence.md`, 2026-09-16, `codex-cli 0.154.0`, modelo `gpt-5.6-sol`) pidió una lectura nativa y Codex disparó un único `PreToolUse` con `tool_name: list_mcp_resources`, `tool_input` vacío, y respondió que no hay lector de archivos de texto nativo en la sesión — 0.154.0 no tiene tool de lectura nativa; las lecturas van por `Bash` (`cat`/`sed`/`rg`), el mismo path estructuralmente no-gateable que ADR-044 ya registra para los edits (nota Evolution, 2026-09-16). `pre-tool-use-read-size` gatea `Operation.READ_FILE` sobre `tool.reads`: no hay dialecto de lectura que ensanchar bajo Codex, así que el hook queda inerte por diseño y no por un mapeo faltante en `_TOOL_OPERATIONS`. Sin código para shippear — se cierra la entrada de Prioridad MEDIA que esperaba esta probe, no como fix sino como límite confirmado. Cerrado en la rama `docs/codex-evidence-probes-5-8`, 2026-09-16.

---

## Open — Prioridad ALTA

### F2 — La caída de credenciales de perfil preserva la cuenta heredada

**Por qué:** medido por la auditoría del 2026-09-16 con una probe mockeada, no re-verificado en esta pasada. `core/secrets.py:82` y `agents/launch.py:76`: el launch copia el environment heredado completo; un archivo de secreto ausente **o** con error de lectura lo devuelve sin modificar. Una probe mockeada con el archivo de la cuenta B ilegible preservó el `CLAUDE_CODE_OAUTH_TOKEN` de la cuenta A. El comportamiento es intencional y está cubierto por `tests/unit/core/test_secrets.py:141` — la auditoría lo marca como riesgo arquitectural (disponibilidad por encima de identidad de cuenta), no como test faltante.

**Registrado sin fix en esta entrada** — igual que F1, el arreglo va en una tanda propia.

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

### F4 — El dry-run de `lh metrics ingest` igual dispara delivery remoto

**Por qué:** re-verificado hoy. `cli/metrics_cmd.py:50-66`: `dry_run` sólo cambia el DB a `:memory:` (`:52`); los sinks configurados se construyen igual, `ingest_all` corre igual, y por cada `HttpRemoteSink` el comando llama `sink.drain(batch_size=0)` (`:64`) sin ninguna guarda de `dry_run`, adentro de un `except Exception: pass` pelado (`:65-66`) que además silencia un POST remoto fallido. Con un sink HTTP habilitado, un "dry run" transmite metadata (usuario, tenant, profile, project, session, host — `monitoring/ingest.py:205`) y actualiza el colector remoto. El help de la flag promete sólo "no database writes".

**Fuente:** hallazgo F4 de `specs/codebase-audit-2026-09-16.md`, re-verificado a mano el 2026-09-16 leyendo `metrics_cmd.py` directo.

**Acción:** cortar la construcción/drain de sinks remotos cuando `dry_run=True`, y no tapar el POST fallido con un `except` pelado.

### F3 — El ack de delivery del outbox no identifica la versión del payload reclamado

**Por qué:** medido por la auditoría del 2026-09-16 con una reproducción en SQLite en memoria, no re-verificado en esta pasada. `monitoring/db.py:466` y `:542`: reencolar un payload cambiado reemplaza su contenido y vuelve la fila a `pending`; `outbox_mark_sent` reconoce delivery usando sólo `sink_name` + `event_id`, sin versión. Secuencia reproducida: worker reclama v1 → ingest reemplaza con v2 → worker acknowledgea v1 → la DB queda con v2 en estado `sent`. Una request vieja exitosa puede suprimir la entrega de datos más nuevos, porque el claim transaccional no protege el ack posterior.

**Fuente:** hallazgo F3 de `specs/codebase-audit-2026-09-16.md`.

### F5 — Retry y lease del outbox de métricas chocan con la ejecución real

**Por qué:** medido por la auditoría del 2026-09-16 con una probe en memoria, no re-verificado en esta pasada. `monitoring/sinks/worker.py:44` y `db.py:712`: cada drain limpia los timestamps de retry pendientes antes de reclamar trabajo — un evento demorado 300s queda elegible de inmediato. Los workers además reclaman un batch entero bajo un lease único de 60s y mandan requests secuenciales, con 50 requests por default y timeout de 5s (`sink_setup.py:153`). Invocaciones frecuentes anulan el backoff exponencial; un batch lento puede exceder el lease y otro worker reclama entregas sin terminar. La idempotencia del receiver puede acotar duplicados, no eliminar tráfico redundante ni acks stale.

**Fuente:** hallazgo F5 de `specs/codebase-audit-2026-09-16.md`.

### F6 — El `.envrc` generado interpola paths sin escapar shell

**Por qué:** medido por la auditoría del 2026-09-16 con una probe de rendering puro, no re-verificado en esta pasada. `core/envrc.py:35`: el generador envuelve el path en comillas dobles sin escapar sustituciones de comando ni comillas embebidas. Un segmento de path configurado que contenga `$(...)` o backticks se emite tal cual dentro de la línea `export` entre comillas dobles, y al sourcear el archivo esa sustitución se evalúa en vez de preservarse como string literal. La explotación requiere control sobre el path configurado y ejecución del archivo generado — la CLI ya exige `direnv allow` antes de aplicar un `.envrc` actualizado (`cli/profile_cmd.py:280`).

**Fuente:** hallazgo F6 de `specs/codebase-audit-2026-09-16.md`.

### F7 — Los locks del compound-loop worker no cubren la persistencia compartida de memoria

**Por qué:** medido por la auditoría del 2026-09-16 por inspección de fuente, no reproducido contra un fallo real de filesystem. `knowledge/compound_loop_worker.py:139` y `compound_loop.py:919`: los workers lockean su cola por-perfil, pero los destinos de memoria pueden converger en el mismo directorio de proyecto del knowledge store (`core/memory_store.py:43`). Las escrituras usan un `.tmp` determinístico; las actualizaciones de propuesta leen el documento existente, concatenan y reemplazan sin lock de destino (`compound_loop.py:1071`). Dos workers de distinto perfil procesando el mismo proyecto pueden pisarse cambios o colisionar en el temporal — el reemplazo atómico evita visibilidad parcial, no serializa escrituras concurrentes. Es una race derivada del código fuente, no una falla de filesystem reproducida.

**Fuente:** hallazgo F7 de `specs/codebase-audit-2026-09-16.md`.

### F9 — Tres funciones de orquestación concentran la complejidad del repo

**Por qué:** medido por la auditoría del 2026-09-16 con un heurístico de screening (conteo de branches/booleanos/handlers/generators vía AST, explícitamente no una métrica de complejidad cognitiva estandarizada), no re-verificado en esta pasada.

| Función | Líneas físicas | AST branch score* |
|---|---:|---:|
| `hooks/builtins/context_inject.py:main:729` | 181 | 44 |
| `monitoring/views/overview.py:render:32` | 174 | 37 |
| `cli/exec_cmd.py:319` | 171 | 35 |

Cada una mezcla responsabilidades no relacionadas: recolección de contexto y rendering; inspección de DB/filesystem/scheduler y presentación; o planificación de launch, manejo de proceso, billing y serialización de resultado. `overview.render` además trae todas las estadísticas históricas a memoria antes de agregar (`overview.py:65`, `db.py:400`) — el costo de memoria y procesamiento crece con el historial retenido.

**Fuente:** hallazgo F9 de `specs/codebase-audit-2026-09-16.md`.

### El guard de git normaliza un set fijo de opciones globales

**Por qué:** `_normalise_git_globals` (cierre de F1, #347) sólo despoja un juego reconocido de opciones globales (`-C`, `-c`, `--git-dir=`, `--work-tree=`, `--no-pager`), y sólo una por pasada. Una opción que toma argumento repetida inmediatamente contra sí misma puede parsearse mal y dejar el subcomando real sin alcanzar, así que la regla se abstiene en vez de bloquear — valores distintos pasados de forma normal (por ejemplo dos `-C` a targets distintos) no lo sufren. Una opción global fuera de ese set reconocido también hace abstener a las reglas de git, igual que antes del fix.

**Fuente:** PR #347, sección "Known limits" — atacado el guard terminado con variantes realistas, no fixeado por estar fuera del alcance de esa lane.

**Acción:** ninguna propuesta en esta entrada.

### Falso positivo del hook de seguridad con backticks en el argumento de otro comando

**Por qué:** el `pre_tool_use_security` desplegado interpreta cualquier backtick como operador de command substitution, sin distinguir el que abre shell real del que sólo aparece dentro de un argumento citado de otro comando. Bloqueó una llamada a `gh pr create --body` cuyo texto citaba, entre backticks de markdown, un comando destructivo mencionado como prosa — evaluó esa cita como si fuera una invocación de git real, no el contenido de un PR body.

**Fuente:** surgido dos veces durante la lane de #347, al redactar el body de su propio PR. Mecanismo emparentado con *Falso positivo del PreToolUse de seguridad con backticks de markdown* (Prioridad BAJA), pero disparado dentro del argumento de otro comando, no de un heredoc.

**Acción:** ninguna propuesta en esta entrada — mecanismo registrado, sin repro (regla de repo público).

### `pre_tool_use_security.FILE_TOOLS` no incluye `apply_patch`

**Por qué:** `INSPECTED_TOOLS` de `pre_tool_use_security.py:219` es `COMMAND_TOOLS | FILE_TOOLS`, y `FILE_TOOLS` no tiene `apply_patch` — su rama `modify_file` sobrevive la traducción de #348 (el gate F8 lo registra) pero el propio gate de nombre de tool del hook lo sigue perdiendo. El gate de cobertura de matchers ya es agent-aware, así que agregarlo no exige `apply_patch` en el matcher de Claude Code. `pre_tool_use_git_scope.py` no necesita nada — `INSPECTED_TOOLS = frozenset({"Bash"})` ya alcanza los `Bash` de Codex; se deja constancia para que la omisión se lea como decisión y no como olvido.

**Fuente:** #348, follow-ups 1 y 2.

**Acción:** ninguna propuesta en esta entrada — otra lane es dueña de `pre_tool_use_security.py`.

### `FileEdit` no puede expresar un delete

**Por qué:** `FileEdit` tiene `is_create` y ningún equivalente para un delete; un `*** Delete File:` de `apply_patch` no produce ningún `FileEdit`, así que todo lector ve el path como si siguiera ahí. `post-tool-use-sync-claude` es el lector concreto que pierde un segmento de system-doc borrado.

**Medido 2026-09-16 (probe 6, `specs/designs/codex-evidence.md`): la grafía ya está confirmada, y el bloqueo de esta entrada quedó atrás.** Un delete de `apply_patch` llega como un blob de una sola sección, header literal `*** Delete File: <abs path>`, sin diff body debajo. Ensanchar el tipo sigue siendo el fix honesto; ahora es una cuestión de diseño y no de evidencia faltante. Auditar antes de tocar `FileEdit`: `_parse_patch` (`agents/codex.py`), que arma los `FileEdit`s desde el blob y tiene que emitir el caso nuevo; `post-tool-use-sync-claude`, el lector concreto que hoy pierde el segmento borrado; y cualquier otro consumidor de `tool.edits`. El ensanche se hace en su propio ADR — el próximo número libre es **046** — no en esta entrada.

**Fuente:** #348, follow-up 3; grafía medida en probe 6 (2026-09-16, `docs/codex-evidence-probes-5-8`).

**Acción:** abrir ADR-046 para el ensanche de `FileEdit`, auditando cada lector de `tool.edits` antes de tocar el tipo.

### `lh deploy` no imprime la instrucción de re-trust

**Por qué:** el diseño (`specs/designs/2026-09-13-multi-agent-harness-design.md:831`) dice que `lh deploy` imprime la instrucción de re-trust cada vez que cambia una declaración de hook; hoy `lh doctor` reporta el estado (`untrusted`/`unknown`) pero `deploy` no imprime nada en el momento del cambio.

**Fuente:** #348, follow-up 5.

**Acción:** ninguna propuesta en esta entrada.

### Trust de capa proyecto de Codex

**Por qué:** el diseño (`:730-746`) deja alcanzable y silencioso el estado "deployed, hook-trusted, and still not running" en la capa de proyecto de `~/.codex/config.toml` (`[projects.*]`). Si el harness alguna vez escribe hooks de capa proyecto, `lh doctor` va a necesitar leer esa sección para no reportar un trust que no aplica.

**Fuente:** #348, follow-up 6.

**Acción:** ninguna propuesta en esta entrada — el harness no escribe `[projects.*]` hoy.

### Nada muestra los contadores de `launches` a un humano

**Por qué:** `MetricsDB.launch_counts` y `launch_to_session_ratio` (#346) no tienen ningún consumidor visible — ni CLI ni línea de `lh doctor`. `docs/reference/cli.md:572` documenta `lh metrics loops` sobre `loop_events`; `lh metrics launches` (o una línea de doctor) es la forma obvia, pero el diseño no nombra ningún subcomando y #346 no inventó uno.

**Fuente:** #346, follow-up 1.

**Acción:** ninguna propuesta en esta entrada.

---

## Open — Prioridad BAJA

### Falso positivo del PreToolUse de seguridad con backticks de markdown

**Por qué:** `_COMMAND_START` incluye el backtick como operador de shell — correcto para command substitution. Pero un backtick de markdown inline-code delante de un comando destructivo, incluso dentro de un heredoc citado donde el shell nunca lo interpreta, dispara igual. Escribir prosa *sobre* comandos destructivos queda bloqueado.

**Repro medido el 2026-09-10.** Contra `BLOCK_RULES`, el mismo texto pasa o se bloquea según lleve backticks: la variante sin backticks queda `allowed`, la variante con backticks alrededor del comando devuelve `Recursive delete`. El bloqueo se disparó tres veces seguidas mientras se redactaba esta misma entrada, incluida la que intentaba documentarlo.

**Re-medido el 2026-09-16, después de #335 — sigue vigente y NO es una regresión de esa PR.** #335 ancló doce de las catorce `BLOCK_RULES` en `_COMMAND_START`, y midió este caso en las dos ramas antes de asumir nada: un cuerpo de heredoc que nombra el borrado **sin** backticks queda `allowed` tanto en `main` (798016c) como en la rama, y **con** backticks de markdown queda **BLOCKED** en las dos. Idéntico, porque `rm` era justamente la única regla que ya traía el ancla. Lo que rechaza esa oración es el **backtick**, que es command substitution genuina y pertenece a la clase de operadores — no la falta de ancla. #335 lo dejó afuera a propósito y registró los cuatro falsos positivos que sobreviven como medidos y no como supuestos. La recomendación de abajo no cambia.

**Por qué NO se arregla ya:** el hook falla hacia el lado seguro y el workaround (sacar los backticks) es trivial. Parsear heredocs para distinguir texto de comando no es barato, y un parser incompleto de shell es peor que el falso positivo actual — daría una falsa sensación de precisión sobre una superficie que hoy es deliberadamente conservadora.

**Acción:** ninguna por ahora. Si el falso positivo se vuelve frecuente al documentar, la salida más barata es un `allow_patterns` en el config del profile, no tocar `_COMMAND_START`.

### F10 — `PluginRegistry` no tiene un solo caller en `src/`

**Por qué:** re-verificado hoy. `plugins/registry.py:24`: `grep -rn "PluginRegistry" src/` devuelve dos resultados — la propia definición de la clase y un comentario en `plugins/builtins.py:131` que afirma que "`PluginRegistry` still resolves the implementation classes". La construcción de sinks en runtime instancia built-ins directamente y rechaza sinks de extensión (`monitoring/sink_setup.py:134`); el registry no participa en ningún camino real. El repo mantiene y testea una abstracción de extensión que el runtime no usa, con un comentario que afirma lo contrario.

**Fuente:** hallazgo F10 de `specs/codebase-audit-2026-09-16.md`, re-verificado a mano el 2026-09-16 con el mismo grep.

**Acción:** remover o diferir `PluginRegistry` hasta que haya un consumidor real, y corregir el comentario de `builtins.py:131` en cualquier caso.

### El shim `core/sync_claude.py` no tiene un solo importador

**Qué es:** un módulo de compatibilidad de once líneas que re-exporta `SyncError`, `SyncResult`, `sync_profiles` y `render_agent_md as render_claude_md` desde `core/sync_agent_md.py`, con un docstring que promete que «will be removed in a future release». El rename está en [ADR-032](adrs/032-agent-adapter-completeness.md):136, bajo el heading `### \`core/sync_claude.py\` rename`; el docstring citaba **ADR-031**, que es `default-hooks-merge` y no menciona el rename en ningún lado. Corregido el 2026-09-16 y sostenido por `tests/docs/test_adr_citation_coherence.py`, que **deriva** el número del ADR que carga la sección en vez de tipearlo: si la sección se muda, el test sigue a la sección.

**Medido el 2026-09-16:** `grep -rn "sync_claude" src/ tests/` devuelve siete líneas y **ninguna es un import de este módulo**. Cinco son nombres de identificadores de test (`test_sync_claude_hook_excluded_for_null_agent`, `test_sync_claude_hook_included_for_claude_agent`, `_sync_claude_payload` y dos más en `tests/integration/test_hook_log_profile_isolation.py`), y el resto se refiere al builtin `post-tool-use-sync-claude` o a `profile_sync_claude_md`. Cero importadores dentro del repo.

**Por qué NO se borra ya:** es un cambio con su propio blast radius y merece su propia PR. Borrarlo pide tres cosas que este repo ya aprendió a no dar por sentadas: confirmar que ningún profile desplegado ni script de chezmoi lo importa por path —el grep de este repo no ve `~/.config/` ni `~/.claude*`, así que «cero importadores» es una medición *del repo*, no del sistema—; decidir si la promesa del docstring cuenta como contrato público, dado que el paquete no declara `__all__` ni una política de deprecación escrita; y elegir el tipo de commit que release-please va a clasificar bien (`feat!` o `chore`, nunca `fix`).

**Acción:** borrarlo en una PR propia, con el grep contra los profiles desplegados hecho **antes** y no después.


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

**Shippeado parcialmente el 2026-09-16 ([ADR-043](adrs/043-system-docs-by-role.md)).** La mitad del paquete Python está: `system_docs() -> list[Path]`, los cuatro call sites, los segmentos por rol (`head.md` / `_common/common.md` / `_common/<agent>.md` / `tail.md`), un documento renderizado a cada destino, y el trigger set del hook de sync derivado de los roles en vez de listado. El layout legacy sigue renderizando detrás de un diagnóstico, que es la ventana de migración.

Queda pendiente, y **no es olvido**:

- **El rename de chezmoi.** Los ocho archivos planos de `dotfiles/dot_config/lazy-harness/profiles/` siguen con nombres `CLAUDE.*`. Mientras no se renombren, el header generado sigue nombrándolos —correctamente, porque es el layout que se lee— y el fallback sigue vivo. El fallback sale con ese rename, no antes.
- **El rename del hook** (`post_tool_use_sync_claude` → `post_tool_use_sync_system_doc`, `lh profile sync-claude-md` → `lh profile sync-system-doc`) y el párrafo del system doc deployado que documenta su trigger. Van juntos con el rename de chezmoi: el gate pide que la prosa y el mecanismo se muevan en el mismo cambio, y ese párrafo lo lee una persona que actúa sobre él.
- **Los asset segments de la decisión 10.** Viven en `deploy/engine.py:deploy_profiles`, que linkea cada entrada del source dir como un symlink opaco (`:188`). La mitad del assembler sola escribiría el documento en `<profile>/<agent>/`, o sea en `~/.claude-<p>/<agent>/CLAUDE.md`, donde el agente no lo lee. Media agreement es peor que ninguna.

**Sobre los kill criteria:** medido el 2026-09-16, no dispararon **y no podían**. El instrumento es la tabla `launches` de la decisión 1 del spec derivado, y `grep -rn 'launches' src/lazy_harness/ --include='*.py'` devuelve un solo hit, el docstring de `agents/launch.py`. El reloj arranca en el step 9 (un `CodexAdapter` real) y `agents/codex.py:1` sigue diciendo "the throwaway that runs step 4's contract gate". No hay evidencia en ninguna dirección, que no es lo mismo que "los criterios se cumplen".

### `lazy-ai-tools` — deuda de nomenclatura, registrada sin pagar

`ClaudeCallLog`, `StepLog.claude_calls` y varios docstrings nombran a Claude donde el concepto es "el agente". Relevado el monorepo entero: **no necesita ningún cambio** para el multi-agente.

**Condición de arranque:** ninguna. Es la decisión 8 y está explícitamente *not scheduled*. Renombrar 559 registros históricos para arreglar un nombre es justo el refactor-fuera-del-task que el `CLAUDE.md` prohíbe. Se toca solo si otra cosa ya está tocando esos archivos.

### Hooks de usuario tienen el mismo bug de duplicación que tenían los builtins

Cerrado para builtins (`_is_harness_owned` ahora identifica por nombre canónico dentro de `lh hook <name>`). La función se mudó con el merge en el step 3: vive en `agents/claude_code.py:191`, no en `deploy/engine.py`. Los hooks de usuario siguen expuestos: su comando generado es `{sys.executable} {path}`, y `sys.executable` cambia al actualizar Python — con lo cual el redeploy preserva la entrada vieja como ajena y queda duplicada.

Arreglarlo requiere que la clasificación conozca los hooks configurados, o sea cambiarle la firma a `_is_harness_owned` (`agents/claude_code.py:191`). No se hizo en el fix del step 0 para no ampliar el alcance.

**Condición de arranque:** cuando alguien reporte un hook de usuario corriendo dos veces, o junto con el step 5 (migración de los 15 builtins restantes), que ya toca esa zona.

### El preflight de auth lee un nombre de archivo de Claude Code y no se lo pregunta al adapter

**Por qué:** `hooks/builtins/session_start_preflight.py:_credentials_path` arma `<agent dir>/.credentials.json`. El directorio ya sale per-profile —la Task 9 del step 5 cerró esa mitad, `agent_dir_for(cfg, event.profile)`— pero el **nombre del archivo** sigue escrito a mano en el builtin, y es el de Claude Code. Otro agente guarda sus credenciales en otro archivo, en otro formato, o directamente en un keychain sin archivo que leer.

El resultado no es un error: es un `unknown`. `check_auth` devuelve `("auth", "unknown", "could not read the credentials file")` para cualquier cosa que no pueda abrir, que es exactamente la degradación correcta para un archivo corrupto y exactamente la equivocada para un agente que nunca tuvo ese archivo. Las dos situaciones quedan indistinguibles en la consola, y la segunda no se arregla loguéandose de nuevo.

**Fuente:** medido el 2026-09-15. `AgentAdapter` (`agents/base.py:480-505`) declara `global_config_link()`, `mcp_config_file()`, `session_dirs()` y `system_doc_name()` — el patrón "este agente guarda X acá" ya existe y tiene cuatro instancias. Ninguna es para credenciales. `grep -rn "\.credentials\.json" src/` devuelve **un solo** call site en todo el árbol, y es este builtin.

**Confirmado en vivo el 2026-09-16 — no es sólo el caso hipotético de un adapter no-Claude, es este mismo agente en macOS ahora mismo.** El profile `lazy` (este mismo checkout) tenía `claude auth login` corrido con éxito hoy: el keychain (`security find-generic-password -l "Claude Code-credentials-49ae4d6b"`, el sufijo es el sha256 de `config_dir` en hex) muestra `mdat` = `20260916124629Z`. `~/.claude-lazy/.credentials.json` quedó con mtime del 2026-09-08 — nunca se reescribió — con `refreshTokenExpiresAt` vencido. `check_auth` (`:89-128`) lee sólo ese archivo y devuelve **`fail`**, no `unknown`: el archivo abre, parsea, y tiene un shape válido, así que ninguna rama de degradación de `check_auth` aplica — el JSON simplemente quedó viejo. El preflight de esta misma sesión lo reportó así (`auth [FAIL] — refresh token expired 33 h ago`) mientras el login real, en el keychain, estaba sano. macOS guarda la credencial viva en el keychain y deja un archivo espejo que nada re-sincroniza; el caso ya registrado arriba (adapter no-Claude → `unknown`) sigue siendo real, pero no es el que ocurre hoy — el que ocurre hoy es un `fail` falso sobre el agente Claude Code mismo, en la plataforma donde este repo corre. El costo es el que el propio docstring de `check_auth` anticipa: un falso `fail` entrena al lector a ignorar el bloque entero.

Lo que sí existe es el principio, escrito en otro lado: `agents/launch.py:77-79` dice «the agent's credential is one global variable and its stored credentials live inside `config_dir`, so a second profile backed by a second account would otherwise authenticate as the first — silently». O sea, el launcher ya trata la ubicación de credenciales como algo que cuelga del `config_dir` del profile — que es exactamente lo que la Task 9 le hizo al preflight. Lo que falta es que el *nombre* salga del adapter en vez del builtin.

**Acción:** un método en el adapter —`credentials_file() -> str | None`— y que `None` sea una respuesta de primera clase, no un archivo faltante. Con `None` el check tiene que decir que **no puede hablar por ese agente**, que es un estado distinto de `unknown`; si se colapsan, el preflight reporta lo mismo para un login roto que para un agente cuyo login no sabe mirar. Precondición barata: leer dónde deja las credenciales cada adapter shippeado antes de fijar la firma — el gate del `CLAUDE.md` sobre adapters de binarios externos pide las probes primero, no durante la implementación.

**Alcance: separado a propósito.** La Task 9 arregló la resolución per-profile y **no** esto, porque son dos cambios distintos con dos tests distintos: el primero se mide con dos profiles del mismo agente y verdicts opuestos, el segundo necesita un profile de otro agente. Meterlos en el mismo PR hubiera hecho que el golden de byte-identity cubriera uno de los dos y no el otro.

### Dos hooks resuelven el profile de verdad y F7 no tiene canal para verlo

**Por qué:** `session-start-preflight` y `post-tool-use-sync-claude` están en `SKIPPED_HOOKS` del
gate F7 y el motivo es correcto pero incómodo: **no escriben nada bajo el agent runtime dir**, así
que ese gate no tiene sitio donde observarlos. Su resolución per-profile igual existe y es
load-bearing en los dos casos.

- `session-start-preflight` toma la mitad *directorio* de `agent_dir_for` para **leer**
  `.credentials.json` (`session_start_preflight.py:220`) y contesta por stdout (`:242`). Un
  preflight que resuelve global reportaría un login sano para un profile que la sesión no corre —
  exactamente la falla que el check existe para agarrar.
- `post-tool-use-sync-claude` toma la mitad *adapter* — resuelta per-profile en `agent_dir_for`
  (`post_tool_use_sync_claude.py:114`) — y se la pasa a `sync_profiles`, que lee `system_docs()`
  internamente y escribe cada destino que declara (`core/sync_agent_md.py:194`). Resolverlo
  global escribiría el archivo de contrato de un agente en un profile que corre otro.

**Fuente:** medido el 2026-09-15 leyendo los sinks, no de una corrida vacía: `grep -n "hooks.log"`
devuelve cero en los dos módulos, y el docstring de sync-claude lo dice él mismo — *«The directory
half is unused: this hook writes nothing under the agent's runtime dir»*.

**Acción:** dos aserciones en canales que F7 no mira — el stdout del preflight (dos profiles con
un `.credentials.json` plantado en uno solo y verdicts opuestos) y el árbol de segmentos de
sync-claude (dos profiles con `system_docs()` distinto). Ninguno pertenece a F7: meterlos ahí
volvería a ser el problema que la opción 2 acaba de resolver.

## ADR decisions pending

- ~~**Legacy ADR-010 Ollama backend**~~ — cerrado. Promovido por [ADR-033](adrs/033-llm-backend-abstraction.md) y hecho utilizable por [ADR-039](adrs/039-role-routed-inference.md) (ruteo por rol).
- **Legacy ADR-013 Proactivity levels per profile** — promover o descartar. Criterio: si agregás un tercer perfil, promoverlo; si no, descartar.
- ~~**ADR-018 implementation epic**~~ — cerrado. La implementación de ADR-018 ya había cerrado vía [ADR-025](adrs/025-doctor-features-section.md) y [ADR-026](adrs/026-config-wizards.md); el sujeto real de este item, el capability registry de [ADR-035](adrs/035-capability-registry.md), shippeó el 2026-08-17 y el ADR pasó a `accepted`. Lo que sigue abierto es su consumidor: el pane de configuración de la TUI ([`designs/2026-08-17-config-tui-design.md`](designs/2026-08-17-config-tui-design.md)).
