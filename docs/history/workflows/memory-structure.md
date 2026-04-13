# Estructura de auto-memory por proyecto

> **Archived.** Originally from `lazy-claudecode/workflows/`. Preserved for historical context; some references may be stale.


```
~/.claude/projects/<hash>/memory/
├── MEMORY.md          # Routing document (<200 líneas). Índice + refs a archivos.
├── *.md               # Archivos temáticos referenciados desde MEMORY.md
├── decisions.jsonl    # Log episódico: decisiones con contexto y timestamp
└── failures.jsonl     # Log episódico: errores con root cause y prevención
```

## JSONL schemas

### decisions.jsonl

Cada línea es un JSON object:

```json
{"ts": "ISO-8601", "type": "decision", "summary": "...", "context": "...", "alternatives": [...], "rationale": "...", "project": "nombre-repo", "tags": [...]}
```

### failures.jsonl

Cada línea es un JSON object:

```json
{"ts": "ISO-8601", "type": "failure", "summary": "...", "root_cause": "...", "resolution": "...", "prevention": "...", "project": "nombre-repo", "tags": [...]}
```

## Reglas

- Los JSONL son **append-only**. Nunca editar ni borrar líneas existentes.
- Si el archivo no existe, crearlo al hacer el primer append.
- Los .md temáticos se actualizan (upsert). Son complementarios a los JSONL.
- MEMORY.md no referencia cada entry individual — solo apunta a los archivos.
- Rotación futura: si un JSONL supera 1000 líneas, mover las más viejas a `*-archive.jsonl`.
