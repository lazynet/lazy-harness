# External hook ownership — revisión final acotada

2026-09-19. **NO-GO: dos P2; ningún P0/P1 observado en este alcance.**

Leí el rereview anterior y la remediación R1–R4, contrastándolos con el diff
actual sobre `e266148508d5738125dd5a5fb7dbea00e0bf08e5`. La revisión anterior
también fue sobre cambios sin commit: no existe un commit intermedio que permita
aislar mecánicamente aquel delta. Revisé las correcciones identificadas y sus
regresiones directas, sin exploración amplia ni subagentes.

## Hallazgos pendientes

### R3 — P2: migrar un builtin con metadata agrega una segunda ejecución

**Ubicación:** `src/lazy_harness/agents/copilot.py:498`, `:343`, `:376`.

**Reproducción ejecutada:** cargué el adapter de HEAD mediante `git show` y
`exec` en memoria. Generé su artifact con
`HookEntry("lh hook context-inject --profile p")` en `session_start`, agregué
únicamente `timeoutSec=45` al grupo instalado y pedí ese mismo builtin al
planner actual. El resultado contiene:

```text
hooks/lazy-harness.json:
  {"command":"lh hook context-inject --profile p"}
hooks/lazy-harness-external.json:
  {"command":"lh hook context-inject --profile p","timeoutSec":45}
```

Tres planes consecutivos mantienen **[2, 2, 2]** declaraciones donde había una.
La metadata vuelve foreign al grupo legacy, pero el plan también emite su
equivalente managed. Ambos archivos pertenecen al glob nativo ya documentado;
el probe demuestra la duplicación de declaraciones, sin ejecutar Copilot.
`timeoutSec` está respaldado por la evidencia nativa existente.

**Fix exacto:** reconciliar primero los grupos migrados y los externos ya
instalados; antes de emitir el artifact managed, retirar de sus candidatos
cualquier grupo cuya identidad nativa `(evento, matcher, command)` ya esté
satisfecha por aquellos. Aplicarlo también en redeploy, conservar íntegramente
metadata y duplicados foreign y no transferirles ownership. Agregar la secuencia
HEAD → metadata → migración → tres planes, verificando una sola declaración.
No resolverlo ampliando la adopción de grupos con metadata.

### R4 — P2: una versión booleana todavía concede autoridad de borrado

**Ubicación:** `src/lazy_harness/agents/claude_code.py:301`.

**Reproducción ejecutada:** generar un builtin `context-inject` con el planner,
cambiar **solo** `lh_hook_ownership.version` a `true` y planificar hooks vacíos.
El resultado escribe `"hooks": {}`. También sucede con `1.0`; con `null`, `2`,
`"1"` y `false` el documento se preserva. La comparación por igualdad acepta
`True == 1`, por lo que un envelope inválido con registros exactos sigue
autorizando retiro. No es una afirmación de bypass de autenticación.

**Fix exacto:** después de comprobar que el envelope es un dict, exigir
`type(envelope.get("version")) is int` además de igualdad con la versión
soportada; cualquier otro valor debe retornar `{}`. Mantener el sentinel legacy
exclusivamente para clave ausente. Probar versiones inválidas con `managed`
**no vacío** y un registro exacto: usar `managed=[]` no distingue este guard.

## Resultado de las reproducciones solicitadas

| Caso | Evidencia y resultado |
| --- | --- |
| R1 | Los siete negativos exactos devuelven `None` en el reconocedor y se preservan en ambos planners (14 controles). Quoted válido y legacy `.py` se reconocen. Los tests separan builtin inventado de launcher histórico registrado; ADR-042 explicita que esa historia es editable. **Cerrado.** |
| R2 | Loader → engine con external duplicado: **[1, 1, 1]**, omisión conserva uno. Probe con dos foreign equivalentes y metadata distinta: **[2, 2, 2, 2]**, incluyendo omisión, grupos intactos. **Cerrado.** |
| R3 | HEAD real produce bytes iguales al fixture HEAD-equivalent. Omitido y vigente con metadata: **[1, 1, 1]**; mixed con duplicados: **[3, 3, 3]**, íntegros. Ilegibles rechazados; snapshot + deploy + rollback restaura legacy y retira el nuevo destino. **Pendiente el P2 anterior.** |
| R4 | Ausencia conserva migración legacy; null/dict/list/int inválidos no adoptan. External builtin-shaped → null → omisión queda intacto; también con versiones inválidas y `managed=[]`. **Pendiente la validación estricta con registros presentes.** |

Los casos originales **F1–F9** mantienen su evidencia de cierre: F1 gramática y
registro; F2 scripts de usuario; F3 duplicados foreign; F4 prompt/mixed/external
builtin-shaped; F5 persistencia en formato nuevo y snapshot; F6 slots/surplus;
F7 eventos nativos/trust; F8 identidad malformada; F9 edición de grupo registrado.
Los tests seleccionados los corroboran; para la mutación F9 se conserva la
evidencia previa de **1 failed, 3 passed**, sin repetirla. Esto no convierte F5
ni F4 en garantías generales: sus límites R3/R4 siguen abiertos arriba.

## Verificación

- **65 tests enfocados aprobados**, en bloques de 33 (reproducciones), 30
  (regresiones originales) y 2 (persistencia Copilot); sin full suite.
- Ejecuciones con `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
  -p no:cacheprovider`, seleccionando casos de Codex/trust, Claude planner,
  Copilot, deploy engine y snapshot. Probes adicionales solo en memoria;
  fixtures pytest en directorios temporales.
- Único archivo escrito por esta revisión: este informe; sin cambios propios
  en producción, tests o docs, sin commit ni deploy sobre perfiles reales.
- `git diff --check`: sin diagnósticos, exit 0. Informe nuevo comprobado con
  `git diff --no-index --check -- /dev/null
  reports/2026-09-19-external-hook-ownership-final-review.md`: sin diagnósticos
  de whitespace; contenido leído de vuelta.

**NO-GO hasta corregir ambos P2.**

DONE
