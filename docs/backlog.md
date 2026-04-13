# lazy-harness backlog

Issues y mejoras pendientes. Append-only — mover a done/ o tachar cuando se resuelve.

## Open

### compound-loop: learnings lost on long sessions

**Síntoma:** sesión 4bc38694 (2026-04-13, 118 mensajes, ~3h) solo disparó extracción de learnings una vez, a los 3min del inicio. Todos los Stop posteriores fueron skipped con `already processed <session_id>`. Los learnings del 97% restante de la sesión nunca fueron evaluados.

**Root cause:** el worker marca `session_id` como processed con un flag booleano. Fast-path suficiente para idempotencia, pero no para captura incremental — en sesiones largas perdés todo el contenido posterior a la primera extracción.

**Opciones:**
1. Trackear último `message_index` procesado por session_id. Próximo Stop evalúa solo el delta. Más complejidad, más escrituras, pero cero learnings perdidos.
2. Re-procesar si el transcript creció N mensajes desde la última extracción (ventana fija).
3. Procesar solo al Stop final de la sesión (requiere señal de "sesión cerrada" confiable — no la tenemos hoy).

**Recomendación:** (1) delta-by-index. Guardar en queue state o en memoria del proyecto el índice procesado.

**Impacto:** alto — es el mecanismo principal de captura de learnings y hoy solo funciona bien en sesiones cortas.
