# ADR-007: Cross-project learning memory

## Status

Partially implemented — 2026-04-13 (promotion pipeline activo; periodic review migrado a lazy-vault)

## Context

El sistema de memoria actual (ADR-003, ADR-006) es per-project. Cada proyecto tiene
su propia `memory/` bajo `~/.claude/projects/`. Los learnings de un proyecto no son
accesibles desde otros.

El usuario trabaja en múltiples proyectos con diferentes roles y cuentas (lazy/flex).
Necesita que el conocimiento transferible — patrones técnicos y lecciones de criterio —
fluya entre proyectos.

También necesita mantenimiento a largo plazo: un learning nuevo puede invalidar uno
viejo (desaprender) o coexistir porque aplica a un contexto diferente.

## Decision

Implementar una capa de aprendizaje cross-project con dos mecanismos:

1. **Promotion pipeline**: el compound loop (ADR-005) gana una 4ta evaluación que
   promueve learnings transferibles al vault (Meta/Learnings/) como archivos .md
   con frontmatter estructurado.

2. **Periodic review**: un agente semanal (Claude Code headless vía LaunchAgent)
   revisa los learnings existentes buscando contradicciones, duplicados y decay.
   Propone acciones pero no ejecuta — el usuario aprueba.

Los learnings se indexan en QMD como colección dedicada (`lazy-learnings`) para
búsqueda scoped. Fluyen libremente entre perfiles lazy y flex.

Adicionalmente, se estandariza el timezone de todos los scripts con `LAZY_TIMEZONE`
(default: America/Argentina/Buenos_Aires).

## Consequences

- El compound loop es más pesado (1 pregunta más + búsqueda QMD ~30ms)
- Se agrega un LaunchAgent semanal (costo: una sesión headless corta)
- Los learnings son editables en Obsidian (markdown) y buscables vía QMD
- La calidad depende de que el agente identifique bien qué es transferible
- La revisión semanal mitiga acumulación de ruido
- Deprecación explícita con cadena de reemplazo (deprecated_by)

## Implementation status

- ✅ Promotion pipeline: `compound-loop-worker.sh` evalúa sesiones con `claude -p`
  y crea archivos en `Meta/Learnings/` automáticamente (via ADR-005 v2)
- ✅ Formato de learnings con frontmatter estructurado (title, origin, scope, tags, deprecation fields)
- ✅ LAZY_TIMEZONE estandarizado en todos los scripts
- ✅ Periodic review agent semanal — migrado a `lazy-vault learnings-review` (2026-04-13).
  El script bash `scripts/learnings-review.sh` y su LaunchAgent fueron removidos de
  este repo; ahora el comando vive en `lazy-ai-tools` (package `lazy-vault`) porque
  es mantenimiento del vault, no del harness. Separation of concerns: el harness
  gobierna Claude Code, `lazy-vault` gobierna LazyMind.
- ⏳ Colección QMD dedicada `lazy-learnings` (pendiente)

## Dependencies

- ADR-003: Memory architecture (extended)
- ADR-005: Compound loop v2 (async dispatch implements the promotion pipeline)
- ADR-006: Episodic memory (unchanged, coexists)
