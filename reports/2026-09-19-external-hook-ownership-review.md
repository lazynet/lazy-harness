# Revisión independiente: external hook ownership

Fecha: 2026-09-19. Base: `HEAD e266148508d5738125dd5a5fb7dbea00e0bf08e5`.

**NO-GO: 7 findings P2 y 2 P3. No encontré P0/P1.** Hay pérdida de
declaraciones ajenas, regresión de idempotencia y adapters que no cumplen el
contrato nuevo. Los tests enfocados pasan, pero no bastan para aprobarlo.

## Alcance y método

Revisé los 15 archivos tracked del diff completo contra HEAD, los dos informes
untracked de implementación y probe, `AGENTS.md`, el procedimiento de
verificación y las rutas relacionadas de engine, loader, adapters, trust,
snapshot y rollback. Consulté también el diseño de ownership referenciado por
el probe, en el worktree `wave-1-implementation`.

No usé subagentes. No modifiqué producción, tests ni docs; no hice commit,
push, deploy ni cambios en perfiles reales. Este informe es el único archivo
creado por la revisión. Los tests usaron sus fixtures temporales; los probes
propios y la mutación se ejecutaron en memoria, con bytecode y caché pytest
deshabilitados. No repetí la full suite ni el probe nativo de app-server.

Las líneas siguientes corresponden al worktree revisado. Distingo regresiones
del diff de comportamientos heredados que contradicen el contrato que este
cambio introduce; no atribuyo todos los problemas al código nuevo.

## Findings

### F1 — P2: el clasificador nuevo de Codex no prueba que un comando sea builtin

**Ubicación:** `src/lazy_harness/agents/codex.py:584`, `:599`, `:647`;
clasificador reutilizado en `src/lazy_harness/agents/claude_code.py:230`.

`_group_is_harness_builtin` delega en un reconocedor que acepta cualquier
tercer argumento después de `<launcher> hook`, salvo que empiece con `-`.
No consulta el registro de builtins, no valida el resto de la invocación y
acepta el marcador legacy como substring en cualquier parte del comando.

**Reproducción observada:** para un documento con el stamp legacy y un grupo
`SessionStart`, `plan_config({}, {}, existing, binary="lh")` devuelve borrado
del archivo para cada uno de estos comandos:

```text
lh hook definitely-not-a-builtin --profile p
printf lazy_harness/hooks/builtins/foreign.py
lh hook context-inject --profile p && other-tool guard
```

Los tres figuran en `dropped` como propios. También construí un envelope
versionado con `launchers=["other-tool"]` y un registro exacto para
`other-tool hook unknown`: el resultado vuelve a ser un delete. La coincidencia
con metadata editable no convierte ese comando en un builtin reconocido.

Esto invalida la defensa adicional que promete ADR-042: el stamp ya no basta
solo, pero el segundo chequeo tampoco establece lo que dice establecer. En
migración legacy puede borrar wrappers ajenos o invocaciones modificadas. La
debilidad del helper existía en Claude; su uso como prueba de ownership de
Codex es nuevo. No es una demostración de ejecución remota ni de bypass de
aprobaciones: quien edita el envelope ya puede editar ese archivo.

**Fix concreto:** reconocer la gramática completa de las invocaciones que el
engine realmente emite, con nombres del registro, aliases y migraciones
explícitas para nombres retirados. Validar la invocación legacy como argumento
ejecutable real, no como substring. Rechazar como prueba de ownership wrappers,
operadores y posiciones/eventos o campos que el generador legacy no pudo haber
emitido. Mantener foreign cualquier caso ambiguo; la provenance sigue siendo
una pista editable, no autenticación. Agregar casos negativos con las tres
formas anteriores y un envelope que inventa launcher/nombre.

### F2 — P2: los scripts de usuario se duplican en cada deploy de Codex

**Ubicación:** `src/lazy_harness/agents/codex.py:666`, `:1068`, `:709`;
contrato de entrada en `src/lazy_harness/deploy/engine.py:418`.

El engine también resuelve hooks de usuario desde `scripts`, y `hook_command`
los emite como `<python> <path>`, con el default `HookOwnership.HARNESS`.
Codex escribe esos grupos y los registra como managed. En el siguiente plan,
el chequeo all-builtin no los reconoce: los preserva como foreign y agrega de
nuevo el mismo grupo managed. Ninguna cantidad de deploys converge.

**Reproducción observada:** tres planes consecutivos con
`HookEntry("/usr/bin/python3 /config/hooks/custom.py")`, alimentando cada plan
con su salida anterior, producen respectivamente **1, 2 y 3 grupos**. Ejecuté
la misma secuencia contra el módulo de HEAD cargado en memoria: **1, 1 y 1**.
Es una regresión de backward compatibility, no solo un input artificial: esa
es la forma que emite `hook_command` para `HookInfo.is_builtin=False`.

**Impacto:** ejecución multiplicada del hook, churn de trust y scripts
obsoletos que tampoco se retiran. El problema también afecta a consumidores
previos de `HookEntry` que entregan comandos gestionados no builtin.

**Fix concreto:** definir el ownership de los scripts de usuario en el
contrato compartido y hacerlo consistente al escribir y releer. Si se limita
el lifecycle gestionado a builtins, proyectar esos scripts como ensure-present
con deduplicación exacta y documentar su retiro; si siguen siendo gestionados,
registrar y validar su procedencia de forma explícita. No ampliar el
reconocedor hasta aceptar cualquier comando. Probar el camino completo
loader → engine → adapter, tres deploys y posterior omisión.

### F3 — P2: Claude colapsa duplicados foreign y pierde metadata

**Ubicación:** `src/lazy_harness/agents/claude_code.py:362`–`:368`.

La lista llamada `generated_entries` es la misma lista `merged[event]` a la
que se van agregando los grupos foreign. Al procesar el segundo equivalente,
el grupo generado ya se borró: el loop borra el primer foreign preservado.
Así se termina conservando solo el último duplicado.

**Reproducción observada:** dos grupos existentes con matcher `""`, comando
`other-tool session` y timeouts distintos (`10` y `45`), más un external
equivalente, terminan en un único grupo con timeout `45`. Se pierde el grupo
con timeout `10`, aunque `preserved` cuenta ambos. También afecta a duplicados
idénticos, cuya ejecución repetida puede ser intencional.

**Fix concreto:** retirar únicamente candidatos del conjunto generado
original. Resolver qué identidades externas ya están satisfechas antes de
concatenar los grupos preservados, o separar ambas listas. No buscar candidatos
para borrar entre foreign ya procesados. Probar duplicados con la **misma**
identidad que el external, incluyendo metadata distinta y segundo deploy.
El test agregado usa otro matcher y nunca ejerce esta interacción.

### F4 — P2: Claude sigue atribuyéndose grupos ajenos antes de aplicar external

**Ubicación:** `src/lazy_harness/agents/claude_code.py:343`–`:358`, `:1084`.

El nuevo ownership solo participa en deduplicación. La rama anterior de
clasificación sigue extrayendo strings `command` e ignora los demás handlers;
además se ejecuta antes de consultar las identidades externas.

**Reproducciones observadas:**

- Un grupo sin `command`, por ejemplo un handler `type="prompt"`, desaparece
  cuando se planifica otro hook. No se preserva ni se informa su pérdida.
- Un grupo con un comando builtin y un handler prompt se clasifica íntegramente
  como propio y desaparece. El prompt no participa en `all(...)`.
- Se instala `HookEntry("lh hook context-inject --profile other",
  ownership=EXTERNAL)`. En el siguiente plan se omite ese external y se conserva
  otro builtin: Claude elimina el external por su texto. Tampoco preserva la
  metadata rica de un equivalente con esa forma mientras está declarado.

Es un hueco heredado del merge de Claude, pero contradice el nuevo contrato
de `HookOwnership`, el objetivo de conservar foreign y la afirmación pública
de `docs/reference/config.md:381`. Una invocación legítima de `lh` puede ser
gestionada por el usuario o por otro instalador.

**Fix concreto:** decidir ownership sobre el grupo completo y todos sus
handlers, usando procedencia de lo gestionado y conservando explícitamente lo
emitido como external. Los handlers no reconocidos y los grupos mixed deben
permanecer íntegros. No usar `commands == []` como permiso para omitirlos.
Probar las tres secuencias, incluida la omisión posterior del external, porque
consultar solo las identidades deseadas actuales no resuelve su lifecycle.

### F5 — P2: Copilot borra external aunque el contrato ahora prohíbe su retiro

**Ubicación:** ampliación en `src/lazy_harness/agents/base.py:59`, `:570` y
`src/lazy_harness/deploy/engine.py:433`; consumidor sin adaptar en
`src/lazy_harness/agents/copilot.py:332`–`:342`.

Copilot no inspecciona `HookEntry.ownership`: reemplaza su archivo completo o
lo borra cuando no quedan grupos. El nombre reservado del archivo no resuelve
el problema; ahora ese archivo contiene entradas con dos contratos distintos.

**Reproducción observada:** primer plan con un único external
`other-tool session`; segundo plan vacío usando el artifact anterior. Se
obtiene `WriteOp(artifact=None, relative_path="hooks/lazy-harness.json")`.
Si quedan builtins, se reescribe el archivo sin el external de todos modos.

**Fix concreto:** dar a los externos una persistencia ensure-present también
en Copilot, mediante merge o separación en un artifact persistente compatible
con su glob nativo. Si agrega destinos, incluirlos en `config_targets()` y
probar snapshot/rollback. Añadir una prueba de contrato parametrizada por
adapter para instalar → repetir → omitir external, usando un evento soportado.
No alcanza con que el Protocol estructural siga pasando. ADR-054 y la
referencia prometen esta semántica para cualquier perfil, sin excepción Copilot.

### F6 — P2: un alta de builtin desplaza innecesariamente el trust foreign

**Ubicación:** `src/lazy_harness/agents/codex.py:703`–`:707`;
promesa en `docs/reference/config.md:385`.

El surplus se inserta inmediatamente después del último slot managed, aunque
todavía haya grupos foreign por recorrer. Un alta que podría agregarse al
final cambia los índices de esos grupos sin necesidad.

**Reproducción observada:** desde `[managed A, foreign F]`, pedir `[A, B]`
produce `[A, B, F]`; `changed` es
`["session_start[1]", "session_start[2]"]`. F pasa de índice 1 a 2.
El probe establece que la clave persistida incluye ese índice: conservar el
JSON de F no conserva su aprobación. `[A, F, B]` evitaría ese desplazamiento.

**Fix concreto:** llenar los slots managed disponibles y agregar el surplus
después de recorrer todos los grupos existentes del evento. Probar F entre
managed y al final, midiendo índices/keys y labels, además del orden relativo.
Mantener diagnostics para desplazamientos inevitables al retirar grupos.

El diseño/probe contienen una contradicción: dicen insertar después del último
slot managed y también no insertar delante de foreign. Hay que corregir esa
ambigüedad junto con el código. La eliminación de un slot anterior a F sí puede
desplazarlo; no la clasifico como el mismo bug ni propongo tombstones sin probe.

### F7 — P2: los eventos nativos preservados se diagnostican como inexistentes

**Ubicación:** `src/lazy_harness/agents/codex.py:841`–`:849`, en relación con
el merge nuevo `:684`; reporte en
`src/lazy_harness/agents/codex_trust.py:207` y
`src/lazy_harness/cli/doctor_cmd.py:738`.

`trust_keys` decide si Codex conoce un evento usando la lista de eventos que
el harness genera. `SubagentStart`, `SubagentStop` e `Interrupt` están en
`CODEX_EVENT_NAMES` y en el schema observado por el probe, pero no en
`_HOOK_EVENTS`. El merge ahora conserva sus declaraciones nativas, mientras
el lector de trust las excluye.

**Reproducción observada:** los tres eventos devuelven `declared=()` y aparecen
en `ignored`. También ejercité `trust_for_profile` con lecturas de archivos
mockeadas: un `SubagentStart` presente y su hash almacenado producen
`declared=0`, `ignored_events=("SubagentStart",)` y la clave existente en
`orphaned`. Doctor afirma que Codex no entrega ese evento y que el archivo ya
no declara el handler, ambas afirmaciones falsas según el propio probe.

**Fix concreto:** separar soporte de emisión del harness de reconocimiento de
eventos nativos para trust. Derivar keys de todos los eventos nativos conocidos,
usar label nativo cuando no hay alias canónico y reservar `ignored` para lo
realmente desconocido. Probar cada evento preservado y una clave almacenada.
Es deuda anterior que debe auditarse al ampliar el documento a foreign.

### F8 — P3: identity de Claude introduce TypeError para JSON con tipos incorrectos

**Ubicación:** `src/lazy_harness/agents/claude_code.py:277`, `:358`.

La identidad se consulta en un `frozenset`, pero toma `type` y `command` de
JSON sin comprobar que sean hashables. Un grupo mixed con un comando foreign
válido y otro handler con `command=[]` provoca
`TypeError: unhashable type: 'list'`, incluso sin external declarado.
La comparación contra HEAD en memoria confirma que antes devolvía un plan.

**Fix concreto:** validar tipos al construir la identidad y devolver un
sentinel no comparable para una identidad inválida, o rechazar el documento
con un error de dominio que identifique evento/grupo/handler. No convertir la
refusación segura en un traceback accidental ni descartar el grupo. Agregar
dict/list/null en los campos usados como identidad. No considero este caso
una pérdida de datos ni exijo aceptar un handler inválido.

### F9 — P3: una protección central sobrevive sin ser probada

**Ubicación:** guard en `src/lazy_harness/agents/codex.py:665`;
tests nuevos en `tests/unit/test_agent_codex.py:604`, `:636`, `:483`.

Quité **solo en memoria** la condición
`hooks[event][index] == recorded_group` y ejecuté los tests de Codex, trust,
engine y retrust: **159 passed**. La mutación elimina la protección de grupos
editados después del deploy. Un contraejemplo independiente sí la distingue:
agregar `timeoutSec=12` a un grupo previamente registrado y luego retirarlo
produce cero operaciones con el guard real, y delete con el guard mutado.

Además, los nuevos tests de ownership usan `first`, `second`, `ctx` y
`preflight` como supuestos builtins. Verifiqué que ninguno existe en
`resolve_builtin_spec`; esas expectativas afianzan F1. La aserción del segundo
plan en `:484` solo descarta deletes: pasaría si el adapter escribiera un
artifact que pierde el external.

**Fix concreto:** usar builtins reales como casos positivos y nombres inventados
como negativos. Probar modificación de matcher, comando, metadata y posición
sin actualizar el envelope, así como envelope corrupto/inventado. Afirmar el
contenido preservado tras cada plan y matar la mutación anterior. El informe
de implementación relata RED/GREEN inicial, pero el estado final y esa
narración no permiten verificar independientemente la cronología TDD de cada
cambio; el hueco medido es de cobertura, no una acusación sobre el proceso.

## Lo que sí quedó verificado y límites de la revisión

- **359 tests sin mutación aprobaron**, en dos ejecuciones enfocadas: 179 de
  Codex/trust/planner/engine/retrust y 180 de Copilot/Protocol/config/snapshot.
  No son una full suite. Los 159 del experimento mutado se solapan con los
  anteriores y no se suman como tests adicionales.
- Codex conserva íntegros grupos foreign multi-handler, con metadata y handler
  `mcp_tool`, duplicados preexistentes y eventos desconocidos. Lo comprobé
  además con un probe en memoria. El cambio de matcher de external conserva
  el antiguo y agrega el nuevo; esta modificación de los tests de retrust sí
  corresponde al nuevo contrato.
- La combinación de exactitud del registro y tipos command conserva un grupo
  editado cuando el envelope no fue actualizado. El fallo es que falta probar
  ese guard y que el reconocedor adicional acepta demasiado, no que esa
  comparación esté ausente de producción.
- La negativa ante JSON roto y contenedores con tipos incorrectos, el stamp
  legacy vacío sin autoridad para borrar, retiro de managed con foreign
  restante, launcher transition y estabilidad de segundo deploy builtin están
  cubiertos por los tests enfocados. No equiparo validación estructural con
  validación completa del schema nativo: el parser no valida todos los campos
  del handler ni detecta claves JSON duplicadas.
- `WriteOp.changed` compara grupos, no `description`. El probe existente aporta
  evidencia nativa de key/hash/status para description-only en Codex 0.155.1;
  los tests locales confirman que no se marca stale por ese cambio. No volví a
  ejecutar el binario ni afirmo aprobación real: el probe inyectó un hash
  sintético y el reader correctamente sigue diciendo `unknown`.
- El retiro delante de foreign informa labels desplazados y los tests ejercen
  stale/orphaned. Un grupo multi-handler comparte label por grupo aunque sus
  keys sean por handler; la comparación es conservadora, no una reproducción
  del hash normalizado del agente. No debe presentarse como confirmación de
  confianza ni como equivalencia exacta con cada `currentHash`.
- No se agregó sidecar ni cambió `config_targets()` en este diff. Las
  declaraciones y la provenance viajan juntas en `hooks.json`; los snapshots
  existentes capturan ese archivo y `config.toml`, y las pruebas de integración
  relacionadas aprobaron. No encontré una regresión nueva de destinos de
  snapshot/rollback. Rollback sigue siendo por archivo completo: también
  restaura el estado foreign capturado, no hace rollback por owner.
- El campo nuevo tiene default y mantiene construcción anterior de
  `HookEntry`; no se cambiaron APIs del Protocol. Eso preserva compatibilidad
  de llamada, pero no demuestra compatibilidad semántica: F2 y F5 la refutan.
  El diff no introduce dependencia de una integración externa específica;
  tener cero externos y un solo agente sigue siendo una configuración válida.
- El cambio de ADR-042 como evolución, sin reescribir historia, es apropiado.
  Sin embargo, referencia config y ADR-054 prometen preservación universal,
  duplicados intactos y lifecycle ensure-present que F3/F4/F5 contradicen.
  El resumen de ADR-042 y la referencia deben distinguir conservación de orden
  relativo de conservación de índices en altas/bajas (F6). La sustitución de
  nombres de fixtures y el ajuste histórico de ADR-056 no tienen impacto de
  runtime.
- Límite heredado adicional: `_plan_settings` de Claude sale inmediatamente si
  `hooks` está vacío (`claude_code.py:1075`), por lo que no retira el último
  builtin. La salida temprana merece una prueba de contrato al corregir su
  ownership; no la cuento como otra regresión introducida por este diff.

## Registro de verificación

```text
pytest -q -p no:cacheprovider
  tests/unit/test_agent_codex.py
  tests/unit/test_agent_codex_trust.py
  tests/unit/test_config_planner.py
  tests/unit/test_deploy_engine.py
  tests/integration/test_deploy_retrust.py
=> 179 passed in 1.18s

pytest -q -p no:cacheprovider
  tests/unit/test_agent_copilot.py
  tests/unit/test_agent_protocol.py
  tests/unit/test_config.py
  tests/integration/test_deploy_snapshot.py
=> 180 passed in 0.87s

Mutación en memoria: quitar igualdad de grupo registrado
  tests/unit/test_agent_codex.py
  tests/unit/test_agent_codex_trust.py
  tests/unit/test_deploy_engine.py
  tests/integration/test_deploy_retrust.py
=> 159 passed in 3.58s (mutación sobreviviente)

Contraejemplo independiente del guard:
  REAL: edited group retirement ops = 0
  MUTATED: edited group retirement deletes = True

Compatibilidad de scripts de usuario, tres planes:
  HEAD:     [1, 1, 1]
  WORKTREE: [1, 2, 3]
```

Las ejecuciones usaron `PYTHONDONTWRITEBYTECODE=1`; el primer bloque se lanzó
con `uv run --frozen --no-sync` y el segundo con el Python de `.venv`, sin
instalar dependencias. uv requirió el mecanismo de escalación por acceso a su
caché fuera del sandbox. Ningún fallo de sandbox se contó como fallo de tests.

Verificación de whitespace del informe: `git diff --no-index --check --
/dev/null reports/2026-09-19-external-hook-ownership-review.md`. Se usa
`--no-index` porque el informe es nuevo y no está staged; un diff ordinario
contra HEAD no inspeccionaría su contenido untracked.

**Decisión final: NO-GO hasta resolver F1–F7 y volver a ejecutar los casos
enfocados correspondientes.** No se requiere otra full suite para entender
estos hallazgos; los gates de AGENTS.md aplicarán antes de un futuro commit.

DONE
