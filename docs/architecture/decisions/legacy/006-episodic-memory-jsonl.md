# ADR-006: Episodic memory con JSONL append-only

**Estado**: aprobado

**Fecha**: 2026-03-30

**Depende de**: ADR-003 (arquitectura de memoria), ADR-005 (compound loop)

## Contexto

ADR-003 define MEMORY.md como routing document + archivos temáticos .md para
la auto-memory de cada proyecto. Esto cubre bien la memoria semántica (hechos,
preferencias, arquitectura) pero no captura la dimensión temporal:

- **Cuándo** se tomó una decisión (y si sigue vigente)
- **Qué falló** y cómo se resolvió (para no repetir errores)
- **Qué alternativas** se evaluaron (para entender por qué se eligió X sobre Y)

MEMORY.md es un estado puntual — se sobrescribe. Los archivos .md temáticos son
narrativos. Ninguno es bueno para queries temporales ("¿cuándo fue la última vez
que tocamos auth?") ni para análisis de patrones ("¿qué tipo de errores se repiten?").

El artículo "The File System Is the New Database" propone JSONL como formato ideal
para logs episódicos:

- **Append-only**: nunca se pierde un registro. Cada línea es un evento atómico.
- **Parseable**: scripts pueden filtrar, agregar, analizar sin LLM.
- **Indexable**: QMD puede indexar JSONL con BM25 y semántica.
- **Git-friendly**: appends son diffs limpios, sin conflictos de merge.

El artículo "Agentic Memory: A Detailed Breakdown" confirma que la memoria
episódica (logs de acciones pasadas con contexto) es lo que permite few-shot
learning: el agente recupera episodios similares antes de decidir cómo actuar.

## Decision

Agregar dos archivos JSONL a la estructura de auto-memory por proyecto:

```
~/.claude/projects/<hash>/memory/
├── MEMORY.md          # routing document (ya existe, ADR-003)
├── architecture.md    # decisiones de arquitectura (ya definido)
├── patterns.md        # patrones confirmados (ya definido)
├── decisions.jsonl    # NEW: log episódico de decisiones
└── failures.jsonl     # NEW: log episódico de errores y resoluciones
```

### Schema: decisions.jsonl

Cada línea es un JSON object con:

```json
{
  "ts": "2026-03-30T14:22:00-03:00",
  "type": "decision",
  "summary": "Usar JSONL para episodic memory en vez de SQLite",
  "context": "Evaluando opciones de storage para memoria episódica",
  "alternatives": ["SQLite + FTS5", "Markdown con frontmatter", "JSONL append-only"],
  "rationale": "JSONL es append-only, git-friendly, parseable sin deps, indexable por QMD",
  "project": "lazy-claudecode",
  "tags": ["memory", "architecture"]
}
```

### Schema: failures.jsonl

```json
{
  "ts": "2026-03-30T15:00:00-03:00",
  "type": "failure",
  "summary": "Hook de Stop falló por set -euo pipefail en script",
  "root_cause": "xargs sin input retorna exit 1 con set -e activo",
  "resolution": "Quitar set -e, agregar || true, terminar con exit 0 explícito",
  "prevention": "Nunca usar set -e en hooks de Claude Code",
  "project": "lazy-claudecode",
  "tags": ["hooks", "bash"]
}
```

### Flujo de escritura

El compound loop (ADR-005) es el trigger principal:

1. Stop hook ejecuta `compound-loop.sh`
2. El agente evalúa la sesión
3. Si hay decisión → append a `decisions.jsonl`
4. Si hay error prevenible → append a `failures.jsonl`
5. Si hay patrón recurrente → actualizar MEMORY.md o .md temático

Los JSONL son append-only. Los .md se actualizan (upsert). Son complementarios.

### Flujo de lectura

- **Agente al iniciar sesión**: MEMORY.md routea a los .md temáticos (como hoy).
  Los JSONL NO se cargan automáticamente — solo se consultan cuando es relevante.
- **Script de análisis** (futuro): parsear JSONL para detectar patrones de errores
  recurrentes, decisiones que se revisitaron, etc.
- **QMD**: indexar JSONL para búsqueda semántica de decisiones pasadas.
- **/recall**: puede buscar en JSONL vía QMD para responder "cuándo decidimos X".

### JSONL vs alternativas

| Criterio | JSONL | SQLite | Markdown |
|---|---|---|---|
| Append-only | Nativo | Requiere INSERT | Requiere parse + write |
| Git-friendly | Excelente (line diffs) | Binario (no diffable) | Bueno pero verbose |
| Parseable sin deps | Sí (json stdlib) | No (sqlite3 lib) | No (YAML parser) |
| QMD indexable | Sí | No (sin adapter) | Sí |
| Human-readable | Razonable | No | Excelente |
| Query complejo | Requiere jq/script | Nativo (SQL) | Requiere dataview/script |

JSONL gana para el caso de uso: append-only logs consultados ocasionalmente.
Si en el futuro se necesitan queries complejas (joins, aggregations), se puede
exportar JSONL → SQLite como paso de build.

## Alternativas evaluadas

### A) Todo en MEMORY.md narrativo
Agregar decisiones y errores como secciones de texto en MEMORY.md.
**Descartado**: MEMORY.md debe ser <200 líneas. Un log episódico lo infla rápido.
Además, el formato narrativo dificulta queries temporales y programáticas.

### B) SQLite + FTS5 (como Engram)
Base de datos relacional con full-text search.
**Descartado**: agrega dependencia binaria, no es git-friendly, overkill para
un solo usuario. Engram sigue siendo candidato futuro (ADR-003) pero no para
este caso de uso específico.

### C) JSONL append-only (elegido)
**Ventajas**: zero deps, git-friendly, parseable, QMD-indexable, append-only
by design.

### D) Archivos .md individuales por episodio (KN-fecha-slug.md)
El diseño original de "knowledge notes" del vault.
**Descartado**: demasiados archivos para el volumen esperado (1-3 entries/día).
JSONL consolida todo en un archivo por tipo, más manejable.

## Consecuencias

- Se crean `decisions.jsonl` y `failures.jsonl` en la estructura de auto-memory
- El compound loop (ADR-005) los usa como targets de escritura
- MEMORY.md se actualiza para referenciar los JSONL cuando aplique
- QMD puede indexar JSONL (configurar colección si es necesario)
- Se puede construir un script `memory-report.sh` que parsee JSONL y genere
  un reporte de patrones (frecuencia de tags, decisiones revisitadas, etc.)
- Si el volumen crece (>1000 líneas), implementar rotación: mover entries
  antiguas a un archivo `decisions-archive.jsonl` y mantener solo los últimos
  90 días en el principal

## Implementación

Ver spec: `docs/archive/specs/2026-03-30-episodic-memory-jsonl.md`
