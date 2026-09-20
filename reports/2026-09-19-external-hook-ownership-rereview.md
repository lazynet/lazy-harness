# Rereview independiente de external hook ownership

Fecha: 2026-09-19. Base: `HEAD e266148508d5738125dd5a5fb7dbea00e0bf08e5`.

**NO-GO: cuatro hallazgos P2. No encontré P0/P1.** La remediación resuelve
los contraejemplos originales en varios frentes, pero todavía permite borrar
declaraciones externas y multiplicar ejecuciones. Los **505 tests enfocados
aprobados** no cubren estos límites.

## Alcance y método

Leí completos el review NO-GO, el informe de implementación actualizado y el
diff actual contra HEAD: 23 archivos tracked. Revisé también el informe del
probe Codex y las rutas relacionadas de loader, engine, provenance, trust,
snapshot, rollback y documentación. Las líneas citadas corresponden al
worktree revisado.

No usé subagentes ni modifiqué producción, tests o docs. No hice commit, push,
deploy ni operaciones sobre perfiles reales. Este informe es el único archivo
escrito por la revisión, aparte de los archivos temporales que crean las
fixtures de las suites autorizadas. Los probes propios y la mutación se
ejecutaron en memoria; el probe de snapshot/rollback usó un filesystem
simulado. Se deshabilitaron bytecode y caché pytest. No corrí la full suite ni
repetí probes de los binarios nativos. Cerré con la evidencia disponible cuando
el usuario lo indicó.

## Estado de F1–F9

| Finding original | Resultado de la rereview |
| --- | --- |
| F1: gramática, registro, legacy, operadores y provenance | **Parcial; abierto por R1.** Pasan nombres reales, alias registrado, forma sin perfil y módulo legacy `.py`. Se rechazan los negativos originales con operadores separados, wrappers, extras y nombres inventados. Operadores pegados y extensiones incorrectas todavía autorizan borrado. La prueba de launcher inventado mezcla dos negativos y no demuestra lo que su nombre promete. |
| F2: scripts de usuario | **Caso original resuelto.** Loader → engine → adapter produce ownership EXTERNAL. Tres planes dan `[1, 1, 1]`, bytes estables y preservación tras omisión, en Claude, Codex y Copilot. R2 identifica otra entrada válida que no converge en Claude. |
| F3: duplicados foreign con metadata | **Caso original resuelto.** Dos grupos equivalentes con timeout 10 y 45 sobreviven íntegros a tres planes y a la omisión en Claude y Codex. R2 distingue duplicados deseados de duplicados ya instalados. |
| F4: prompt, mixed y external con texto builtin | **Casos originales resueltos; límite nuevo en R4.** Prompt-only y mixed permanecen; un external con builtin real sobrevive omisión, tanto solo como junto a otro managed. También se retira el último builtin propio. La provenance explícitamente nula reabre el borrado de externos. |
| F5: Copilot, artifact separado, omisión, snapshot/rollback | **Parcial; abierto por R3.** El formato nuevo separa artifacts, converge y conserva el external al retirar managed. Snapshot/rollback incluye ambos destinos. Falta migrar las declaraciones del artifact producido por HEAD. |
| F6: surplus y trust indices | **Resuelto en los casos reproducidos.** Desde `[A,F]` se obtiene `[A,F,B]`; con foreign intercalados y al final también se conservan sus índices y keys. `changed` identifica solo el nuevo último índice. |
| F7: eventos nativos y desconocidos | **Resuelto.** Los doce eventos nativos producen keys; `SubagentStart`, `SubagentStop` e `Interrupt` conservan labels nativos. Con hashes almacenados, el reader cuenta 12 declaraciones y cero orphaned. Solo `FutureEvent` queda ignored. |
| F8: identidad malformada | **Resuelto para el fallo original.** Matriz de 15 combinaciones: matcher/type/command con null, list, dict, int y bool. Claude conserva handlers y repara matcher sin TypeError. Seis documentos Codex inseguros se rechazan con `CodexHooksUnreadableError` que identifica `hooks.json`. R4 afecta al envelope, no a esos campos de identidad. |
| F9: mutación y builtins reales | **Guard verificado.** Quitar solo la igualdad del grupo registrado, en memoria, produce **1 failed, 3 passed**: falla la edición de comando entre dos builtins reales. Los cuatro pasan con producción intacta. Verifiqué además preservación Codex con builtin real sin registro de provenance y provenance corrupta/null/índice booleano. Persisten huecos adversariales en R1–R4. |

## Hallazgos abiertos

### R1 — P2: el reconocedor todavía atribuye comandos compuestos y paths no emitidos

**Ubicación:** `src/lazy_harness/hooks/loader.py:319`, `:327`, `:352`;
consumido por `src/lazy_harness/agents/codex.py:606` y
`src/lazy_harness/agents/claude_code.py:287`.

`shlex.split` no separa los operadores shell pegados a una palabra y elimina
información de quoting. La condición de cinco argumentos solo exige un perfil
no vacío. Para legacy se compara el stem del archivo, sin exigir `.py`.

**Reproducción:** un `hooks.json` con el stamp legacy exacto y un único grupo
`SessionStart`, `{"hooks":[{"type":"command","command": C}]}`. Invocar
`CodexAdapter().plan_config({}, {}, {Path("hooks.json"): raw}, binary="lh")`
produce un delete y reporta el grupo en `dropped` para cada `C` siguiente:

```text
lh hook context-inject --profile p;true
lh hook context-inject --profile p&&true
lh hook context-inject --profile p>log
lh hook context-inject --profile `true`
lh hook context-inject --profile $(true)
python /opt/lib/lazy_harness/hooks/builtins/context_inject.bak
python /opt/lib/lazy_harness/hooks/builtins/context_inject
```

El reconocedor devuelve `context-inject` en los siete casos. Los strings solo
se pasaron al planner; **no se ejecutaron como comandos**. En contraste, el
caso original con `p && other-tool guard` ahora se preserva correctamente.
La separación por espacios está ocultando el problema, no estableciendo una
gramática exacta. El impacto es pérdida de declaraciones modificadas/ajenas
durante reconciliación; no es una demostración de ejecución remota.

**Fix concreto:** validar la sintaxis shell completa contra las formas que
`hook_command` emite, preservando la distinción entre un perfil correctamente
quoted y operadores, sustituciones o redirecciones activas. Exigir en legacy
el basename completo del módulo registrado más `.py`, no solo su stem, y el
argumento ejecutable en la posición correspondiente. Mantener foreign las
formas ambiguas. Añadir los siete negativos, controles de perfiles quoted y
las formas legacy admitidas; comprobar también el efecto final del planner.

**Límite adicional de la evidencia de provenance:** con un envelope exacto
`launchers=["other-tool"]` y el comando
`other-tool hook context-inject --profile p`, el planner también borra.
El test `test_editable_provenance_does_not_authorize_an_invented_launcher_or_builtin`
de `tests/unit/test_agent_codex.py` cambia simultáneamente launcher y nombre
de builtin; pasa por el nombre desconocido. No prueba rechazo independiente
del launcher. Como el diseño admite historia de launchers editable, esto no
prueba un bypass de autenticación. Separar esos tests y corregir la promesa
de “invented launchers remain foreign” de ADR-042/informe, o implementar y
documentar una fuente independiente que realmente permita distinguirlos.

### R2 — P2: Claude acumula grupos si dos externos deseados son equivalentes

**Ubicación:** `src/lazy_harness/agents/claude_code.py:393`, `:437`, `:448`.

La lista generada puede contener varios externos con la misma identidad. Al
encontrar un foreign equivalente, el merge retira un único generado y marca
esa identidad como satisfecha. Los demás generados quedan, junto a todos los
foreign preservados. Cada plan aumenta el número de ejecuciones.

**Reproducción por la ruta real:** `load_config`, con lectura TOML simulada,
acepta esta configuración; `_hook_entries_for` produce las dos entradas:

```toml
[harness]
version = "1"
[profiles]
default = "p"
[profiles.p]
config_dir = "/virtual/claude-code"
[hooks.session_start]
scripts = []
external = ["other-tool session", "other-tool session"]
```

Al alimentar cada plan con el artifact anterior, los grupos `SessionStart`
son **`[2, 3, 4]`**. El probe directo equivalente en Codex converge a
`[1, 1, 1]`. No depende de metadata inválida ni de construir un `HookEntry`
fuera del contrato: el loader acepta esa lista.

**Fix concreto:** deduplicar únicamente los externos generados por identidad
nativa antes del merge y, cuando un grupo instalado satisface esa identidad,
retirar todos sus candidatos generados. Concatenar después todos los foreign
originales sin colapsarlos. Probar loader → engine → Claude con dos entradas
equivalentes, tres planes y omisión, además de los duplicados foreign con
metadata distinta que ya quedaron corregidos.

### R3 — P2: Copilot no migra los externos del artifact anterior

**Ubicación:** `src/lazy_harness/agents/copilot.py:349`, `:355`, `:357`, `:368`.

El nuevo planner trata `hooks/lazy-harness.json` como exclusivamente managed,
pero HEAD colocaba allí también los externos y scripts de usuario. Solo lee
el contenido del nuevo `hooks/lazy-harness-external.json` para conservarlos.
El nombre reservado no convierte retrospectivamente el archivo anterior en
un archivo que contiene únicamente builtins.

**Reproducción:** cargué el módulo Copilot de HEAD mediante `git show` y
`exec` exclusivamente en memoria. Su planner recibió un external
`other-tool session` y produjo `hooks/lazy-harness.json`. El planner actual,
con ese artifact como existing y hooks vacíos, devuelve:

```text
WriteOp(relative_path="hooks/lazy-harness.json", artifact=None)
Estado resultante: ningún artifact, ningún external.
```

Si el external sigue declarado, se copia desde el modelo deseado al nuevo
artifact, pero no desde el grupo instalado: agregando `timeoutSec=45` al
grupo legacy, esa metadata desaparece al migrar. El problema de omisión de F5
permanece para instalaciones que actualizan desde HEAD; separar archivos solo
lo resuelve para instalaciones ya escritas por la remediación.

**Fix concreto:** introducir una migración explícita del archivo anterior
antes de reemplazarlo o retirarlo. Conservar o trasladar íntegros los grupos
que no puedan probarse managed, sus duplicados y metadata, incluso si ya no
aparecen en desired. Reconciliar los dos destinos en el mismo plan sin
duplicar ejecución. Ante un legacy ilegible, rechazar el plan sin borrarlo.
Probar HEAD → nuevo planner con external omitido, external vigente con
metadata, mezcla con builtins y rollback de la migración.

**Lo que sí pasó:** en formato nuevo, instalar managed + external, repetir y
omitir conserva únicamente el artifact external. Ejecuté `snapshot_targets`,
`take_snapshot` y `apply_rollback_log` reales con operaciones de filesystem
simuladas: ambos destinos entran al manifest y se restauran exactamente,
tanto inicialmente presentes como inicialmente ausentes. Los tests de
integración de snapshot y rollback también aprobaron; el test Copilot nuevo
por sí solo verifica pertenencia a targets, no una migración desde HEAD.

### R4 — P2: provenance nula de Claude reactiva la adopción legacy y borra externos

**Ubicación:** `src/lazy_harness/agents/claude_code.py:298`, `:299`, `:332`.

`settings.get("lh_hook_ownership")` confunde campo ausente con campo presente
cuyo valor es null. Ambos retornan el sentinel que activa la clasificación
legacy por texto builtin. Un envelope explícitamente malformado debería
reducir autoridad, no conceder permiso para adoptar y retirar grupos ajenos.

**Reproducción desde una salida actual:** instalar solo
`HookEntry("lh hook context-inject --profile p", ownership=EXTERNAL)` en
Claude. Su envelope lleva `managed=[]`. Cambiar exclusivamente
`lh_hook_ownership` a null, sin tocar el grupo, y planificar hooks vacíos.
El resultado escribe `"hooks": {}`: el external se elimina. Con envelope
`{}` o con `{"version":1,"managed":[]}`, ese mismo grupo se preserva.

**Fix concreto:** distinguir presencia de la clave de su valor. Retornar el
sentinel legacy únicamente cuando `_HOOK_OWNERSHIP_KEY not in settings`;
para null o cualquier forma/version inválida retornar cero posiciones propias
o un error de dominio que preserve el documento. Añadir la secuencia real
external → envelope null → omisión y controles con absent/dict/list/int/null.
No es el TypeError de F8: los handlers son válidos y el efecto es borrado.

## Baseline, documentación y límites

- Para cada adapter por separado, un único perfil sin externos y con defaults
  del engine dio tres planes byte-estables. Al pedir retiro completo, se
  retiraron los grupos managed emitidos. El diff no exige ninguna integración
  externa ni múltiples agentes para funcionar.
- No encontré una regresión adicional del loader al resolver scripts,
  builtins o aliases. Su nueva función de reconocimiento concentra R1. La
  matriz de F2 ejercitó el script real resuelto, con acceso a su path simulado,
  sin ensanchar el reconocedor para tratar Python arbitrario como builtin.
- La evolución de ADR-042 y la referencia config ahora explican correctamente
  surplus al final y desplazamientos inevitables al retirar slots. R1 todavía
  contradice su promesa de gramática exacta. ADR-047/054 documentan la
  separación Copilot, pero omiten la migración que R3 demuestra necesaria.
  La garantía general de ensure-present tampoco se cumple ante R2/R4.
- El campo `lh_hook_ownership` de Claude agrega una superficie distinta del
  envelope Codex. Los tests locales prueban su serialización; no volví a
  verificar su aceptación con el parser del binario Claude. Tampoco ejecuté
  Copilot para validar el segundo archivo: la compatibilidad del glob descansa
  en la evidencia nativa previa, no en este rereview.
- Los cambios históricos de ADR-056 y las sustituciones de nombres en fixtures
  no presentan una regresión de runtime. Aprobaron las suites seleccionadas de
  coherencia de referencia, citas, índice ADR y hooks. Esos checks no prueban
  las afirmaciones de comportamiento que contradicen R1–R4.
- Trust se verificó mediante keys y el reader del harness, con hashes
  sintéticos. El resultado correcto sigue siendo `unknown`, nunca una
  afirmación de aprobación real. Snapshot/rollback continúa operando por
  archivo completo, incluido el estado foreign capturado.
- No afirmo haber reconstruido la cronología TDD. La rereview sí confirma de
  forma independiente que la mutación específica de F9 ahora muere.

## Registro de verificación

Todas las suites se ejecutaron con:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

Primer bloque:

```text
tests/unit/test_agent_codex.py
tests/unit/test_agent_codex_trust.py
tests/unit/test_config_planner.py
tests/unit/test_agent_copilot.py
tests/unit/test_deploy_engine.py
tests/unit/test_deploy_config_engine.py
tests/unit/test_agent_protocol.py
tests/unit/test_config.py
tests/integration/test_deploy_snapshot.py
tests/integration/test_deploy_retrust.py
=> 417 passed in 2.03s
```

Segundo bloque:

```text
tests/unit/test_hook_loader.py
tests/unit/test_agent_claude.py
tests/unit/test_deploy_snapshot.py
tests/docs/test_config_reference_coherence.py
tests/docs/test_adr_citation_coherence.py
tests/docs/test_adr_index_coherence.py
tests/docs/test_hooks_doc_coherence.py
=> 88 passed in 0.30s
```

Mutación en memoria de `_owned_positions`, quitando únicamente
`and hooks[event][index] == recorded_group`:

```text
test_edited_or_moved_recorded_group_is_preserved_as_foreign
=> 1 failed, 3 passed in 0.10s
=> falla [command], tests/unit/test_agent_codex.py:795
=> pytest exit 1; mutación detectada
```

La función original se restauró en memoria en `finally`; ningún archivo fue
mutado. Los cuatro casos sin mutación forman parte de los 417 aprobados, no
se suman otra vez al total de 505. Los probes propios son evidencia adicional
descrita arriba y no se cuentan como tests pytest.

Verificación de whitespace del informe nuevo:

```text
git diff --no-index --check -- /dev/null reports/2026-09-19-external-hook-ownership-rereview.md
```

Se usa `--no-index` porque un diff ordinario no inspecciona el contenido
untracked. Resultado: sin salida ni diagnósticos de whitespace; exit 1 por la
diferencia entre `/dev/null` y el archivo nuevo en modo no-index. No se invoca
el gate pre-commit completo: no habrá commit y el
usuario excluyó explícitamente la full suite.

**Decisión final: NO-GO hasta corregir R1–R4 y verificar sus reproducciones.**

DONE
