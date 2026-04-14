# ADR-008: SessionStart hook para inyección de contexto

**Estado**: aprobado

**Fecha**: 2026-03-31

**Depende de**: ADR-003 (arquitectura de memoria), ADR-005 (compound loop), ADR-006 (episodic memory)

## Contexto

El sistema de memoria del cerebro digital tiene un loop incompleto:

- **Cierre**: session-export + compound loop persisten decisiones, failures, y learnings (ADR-005, ADR-006, ADR-007)
- **Inicio**: no se inyecta contexto propio. El agente arranca sin saber qué pasó antes.

Hoy `/recall` existe como mecanismo manual, pero depende de que el agente o el
usuario lo invoquen. El resultado: cada sesión empieza desde cero, y el contexto
acumulado solo se recupera si alguien se acuerda de pedirlo.

El hook de superpowers (plugin externo) inyecta su sistema de skills al inicio,
demostrando que el patrón funciona. Falta un hook propio que inyecte contexto
del proyecto.

### El problema

1. Continuidad rota — no hay forma automática de saber qué se hizo la sesión anterior
2. Memoria episódica invisible — decisions.jsonl y failures.jsonl existen pero no se consultan al inicio
3. Estado git desconectado — uncommitted changes o branches pueden indicar trabajo en progreso
4. Contexto a demanda no escala — depende de disciplina humana para invocarse

## Decision

Implementar un **SessionStart hook** (`session-context.sh`) que inyecta contexto
dinámico al inicio de cada sesión. El script es read-only, lee archivos locales
directamente (sin QMD ni servicios externos), y solo incluye secciones con contenido.

### Mecanismo

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.local/bin/session-context.sh"
          }
        ]
      }
    ]
  }
}
```

### Estructura del script

```
session-context.sh
├── git_context()      — branch, último commit, uncommitted changes
├── last_session()     — última sesión exportada del proyecto
├── episodic_context() — decisions + failures recientes (JSONL)
├── compose_output()   — ensambla secciones no-vacías → JSON
└── main              — detecta proyecto, ejecuta, exit 0
```

### Contenido dinámico (solo se incluye si hay datos)

| Sección | Fuente | Qué muestra |
|---|---|---|
| Git | repo local | Branch, último commit (hash+msg), resumen de uncommitted changes (count, no lista) |
| Última sesión | claude-sessions/*.md | Fecha, mensajes, primer mensaje del usuario (qué estaba haciendo) |
| Decisiones recientes | decisions.jsonl | Últimas 3 summaries |
| Failures recientes | failures.jsonl | Últimas 3 summaries + prevention |

### Presupuesto de tokens

- Cap máximo: ~2000 chars de output
- Si se excede, trunca episodic primero (menos prioritario que continuidad)
- Si todo está vacío (proyecto nuevo), emite un oneliner

### Safety

- Read-only: no escribe ni modifica nada
- Siempre `exit 0`
- No usa `set -euo pipefail`
- Exporta PATH completo al inicio
- `|| true` en comandos que pueden fallar
- Sin dependencias externas (no QMD, no network)

## Alternativas evaluadas

### A) Inyectar todo vía CLAUDE.md
Agregar instrucciones para que el agente lea memory al inicio.
**Descartado**: es una sugerencia (~80% reliable), no determinístico.
Mismo problema que el compound loop antes de ADR-005.

### B) Usar QMD en el hook
Buscar contexto semántico relevante con `qmd search`.
**Descartado**: agrega dependencia externa + ~30ms latencia + depende de
que el índice esté actualizado. QMD queda para `/recall` (on-demand).

### C) Script con mini-scripts separados (orquestador)
Máxima modularidad, cada sección es un script independiente.
**Descartado**: overengineering. Tres archivos para mantener y deployar
cuando uno con funciones internas logra lo mismo.

### D) Script monolítico con funciones internas (elegido)
Un archivo, funciones por sección, output dinámico.
**Ventajas**:
- Un solo archivo para deployar y mantener
- Funciones internas permiten crecer (agregar secciones c/d futuras)
- Dinámico: si no hay datos, no mete ruido
- Consistente con el patrón de los Stop hooks existentes

## Consecuencias

- Se crea `scripts/session-context.sh` y se despliega a `~/.local/bin/`
- Se agrega SessionStart hook en `~/.claude/settings.json` (Capa 1, global)
- Convive con el SessionStart hook de superpowers (Claude Code ejecuta ambos)
- Cada sesión arranca con contexto de continuidad → loop de memoria cerrado
- Overhead mínimo: lectura de archivos locales, sin calls externos
- Extensible: c (knowledge) y d (estado del mundo) se pueden agregar como
  funciones opcionales sin cambiar la arquitectura

## Implementación

Ver spec: `docs/archive/specs/2026-03-31-session-start-context-hook.md`
