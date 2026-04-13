# ADR-005: Compound loop enforcement vía Stop hook

**Estado**: aprobado

**Fecha**: 2026-03-30

**Depende de**: ADR-003 (arquitectura de memoria)

## Contexto

ADR-003 define un "compound loop" para que el agente persista aprendizajes al final
de tareas significativas: registrar qué se resolvió, actualizar MEMORY.md, y sugerir
updates al CLAUDE.md de perfil si aplica.

Hoy esto es una **instrucción en CLAUDE.md** — una sugerencia que el agente sigue
~80% del tiempo. El 20% restante se pierde silenciosamente: decisiones no persistidas,
patrones no registrados, errores que se repiten.

El artículo "50 Claude Code Tips" lo dice directo:

> "CLAUDE.md contains suggestions (~80% reliability); hooks provide guarantees (100% execution)."

Los artículos de Compound Engineering (gstack vs CE) y "Memory as a Harness"
confirman que el compound step post-tarea es el multiplicador de valor más grande
de un sistema de agentes — y que debe ser determinístico, no sugerido.

### El problema con la implementación actual

1. El agente decide si hay algo que persistir → subjetivo, se salta con frecuencia
2. No hay log de CUÁNDO se evaluó y qué se decidió → sin auditoría
3. En sesiones largas con muchas tareas, el compound loop se olvida → recency bias
4. En `--no-interactive` (cron), el compound loop es invisible → se pierde 100%

## Decision

Implementar el compound loop como un **Stop hook que despacha evaluación async**
al cerrar cada sesión de Claude Code.

### Mecanismo

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.local/bin/compound-loop.sh",
            "description": "Queue async session evaluation"
          }
        ]
      }
    ]
  }
}
```

El Stop hook **no puede comunicarse con el agente** — el agente ya terminó
cuando el hook corre. Por eso el hook actúa como dispatcher:

1. `compound-loop.sh` (Stop hook) encola una tarea en `~/.claude/queue/`
   con metadata de la sesión (cwd, session JSONL path, timestamp)
2. Lanza `compound-loop-worker.sh` en background vía `nohup`
3. Sale con `exit 0` inmediatamente (no bloquea el cierre)

El worker:
1. Toma lock exclusivo (`mkdir` atómico, portable en macOS/Linux)
2. Extrae resumen de la sesión del JSONL (últimos 20 mensajes)
3. Llama `claude -p --model claude-haiku-4-5-20251001` con prompt estructurado
4. Parsea el JSON de salida y escribe:
   - `decisions.jsonl` — decisiones arquitectónicas (ADR-006)
   - `failures.jsonl` — errores prevenibles (ADR-006)
   - `Meta/Learnings/*.md` — learnings transferibles (ADR-007)
5. Mueve la tarea a `done/` y libera el lock

### Comportamiento por modo

| Modo | Qué hace el hook | Qué pasa después |
|---|---|---|
| Interactivo | Encola tarea, lanza worker | Worker evalúa async (~20s), learnings disponibles para review |
| `--no-interactive` | Encola tarea, lanza worker | Igual — el worker corre independiente |
| Sesión trivial | Encola tarea | Worker evalúa, haiku responde `{"decisions":[],...}`, nada se escribe |

### Integración con episodic memory (ADR-006) y cross-project learning (ADR-007)

El worker escribe en `decisions.jsonl` y `failures.jsonl` (ADR-006) y crea
archivos de learnings transferibles en `Meta/Learnings/` (ADR-007).
Todo automático, sin intervención del agente de sesión.

### Safety

- El hook SIEMPRE termina con `exit 0` (no bloquea el cierre)
- El worker usa lock exclusivo (no hay escrituras concurrentes)
- Si `claude -p` falla, el worker loguea y sigue con la siguiente tarea
- Logs en `~/.claude/logs/compound-loop.log` para auditoría
- Queue en `~/.claude/queue/` con tareas completadas en `done/`

## Alternativas evaluadas

### A) Solo instrucción en CLAUDE.md (estado actual pre-ADR)
~80% reliable. El 20% perdido es exactamente el valor que compone.
**Descartado**: no es determinístico.

### B) PreToolUse hook en `git commit`
Evaluar antes de cada commit si hay algo que persistir.
**Descartado parcialmente**: solo cubre sesiones que commitean. Muchas
sesiones de investigación, refactoring, o debugging no terminan en commit.

### C) Stop hook con prompt inyectado (implementación v1, reemplazada)
El hook imprime texto que el agente procesa antes de cerrar.
**Descubrimiento**: los Stop hooks corren DESPUÉS de que el agente terminó.
El output del hook no llega al agente — se pierde silenciosamente.
Esto invalida el approach original. Ver gotcha en PRJ-ClaudeCode.

### D) Stop hook como async dispatcher + `claude -p` headless (elegido)
El hook encola una tarea y lanza un worker background que invoca
`claude -p` con el resumen de la sesión.
**Ventajas**:
- 100% determinístico (el hook siempre corre, el worker siempre evalúa)
- Cero latencia al cierre (worker es async, no bloquea)
- Queue permite acumular evaluaciones si hay cierres rápidos
- Haiku como evaluador es barato (~$0.001 por sesión)
- Learnings disponibles para el humano antes de la siguiente sesión
- Compatible con `--no-interactive`

**Tradeoff vs v1**: hay un LLM call extra por sesión, pero es haiku y
corre en background. El beneficio (100% de evaluaciones efectivas vs 0%
con v1) justifica ampliamente el costo.

## Consecuencias

- Se crean `scripts/compound-loop.sh` (dispatcher) y `scripts/compound-loop-worker.sh` (evaluador)
- Se despliegan a `~/.local/bin/` vía symlinks
- Se agrega Stop hook en `~/.claude/settings.json` (Capa 1, global)
- Cada sesión se evalúa async → 100% coverage
- Costo por sesión: ~$0.001 (haiku) + ~20s background
- Queue en `~/.claude/queue/`, logs en `~/.claude/logs/compound-loop.log`
- Las sesiones de cron (`--no-interactive`) también persisten learnings
- Se puede medir: revisar JSONL diffs + `Meta/Learnings/` para frecuencia de persistencia

## Historial

- **v1 (2026-03-30)**: Stop hook con prompt inyectado. Descubierto que el output
  de Stop hooks no llega al agente — 0% de evaluaciones efectivas.
- **v2 (2026-03-31)**: Reescrito como async dispatcher + worker con `claude -p`.
  100% de evaluaciones efectivas.
- **v3 (2026-04-02)**: Fix de 4 bugs que causaban ~100x consumo esperado de tokens
  (76M tokens/día en Haiku). Cambios:
  - Lock: `mkdir` reemplazado por `lockf` (macOS native, race-free)
  - Meta-loop: `--bare` flag en `claude -p` (previene hooks y reduce prompt ~15K→2K)
  - Filtros: `is_interactive_session()` (primera línea JSONL = `permission-mode`),
    `MIN_USER_CHARS=200`, skip de subagents y sesiones headless
  - Dedup: failures.jsonl y decisions.jsonl incluidos en prompt de dedup
  - Nota: sesiones `--no-interactive` (cron) ya no se evalúan por el filtro estructural.
  Ver spec: `docs/archive/specs/2026-04-02-compound-loop-fix.md`
