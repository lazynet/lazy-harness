# lazy-harness backlog

Issues y mejoras pendientes. Append-only — mover a done/ o tachar cuando se resuelve. Este archivo es **interno** (no se publica al sitio MkDocs); el roadmap público vive en `docs/roadmap.md` y solo contiene los temas comprometidos a alto nivel.

## Open

### compound-loop: insight capture integration

**Síntoma:** los bloques `★ Insight ─` que el output style `explanatory` genera en mensajes del assistant se pierden sistemáticamente — gate-out en sesiones cortas, tail-of-20 en sesiones largas, y reclasificación lossy del extractor LLM.

**Spec:** [`specs/designs/2026-04-13-compound-loop-insight-capture.md`](designs/2026-04-13-compound-loop-insight-capture.md) — diseño completo, test plan TDD (11 casos), secuencia de implementación.

**Comparte mecanismo** con el item de abajo (`delta-by-index`). Implementar juntos.

### compound-loop: learnings lost on long sessions

**Síntoma:** sesión 4bc38694 (2026-04-13, 118 mensajes, ~3h) solo disparó extracción de learnings una vez, a los 3min del inicio. Todos los Stop posteriores fueron skipped con `already processed <session_id>`. Los learnings del 97% restante de la sesión nunca fueron evaluados.

**Root cause:** el worker marca `session_id` como processed con un flag booleano. Fast-path suficiente para idempotencia, pero no para captura incremental — en sesiones largas perdés todo el contenido posterior a la primera extracción.

**Opciones:**
1. Trackear último `message_index` procesado por session_id. Próximo Stop evalúa solo el delta. Más complejidad, más escrituras, pero cero learnings perdidos.
2. Re-procesar si el transcript creció N mensajes desde la última extracción (ventana fija).
3. Procesar solo al Stop final de la sesión (requiere señal de "sesión cerrada" confiable — no la tenemos hoy).

**Recomendación:** (1) delta-by-index. Guardar en queue state o en memoria del proyecto el índice procesado.

**Impacto:** alto — es el mecanismo principal de captura de learnings y hoy solo funciona bien en sesiones cortas.

### quality gate: preexisting failures on main

**Síntoma:** hoy `main` viola la no-negociable #4 de `CLAUDE.md` (pre-commit gate green):

1. `tests/unit/test_version.py::test_version_is_040` — hardcoded a `"0.4.0"` pero el paquete está en `0.5.1`. El test existe para detectar drift entre `pyproject.toml` y `__init__.py`, pero drifteó él mismo porque hardcodea el valor que debería validar dinámicamente.
2. `uv run ruff check src tests` — 23 errors preexistentes. Origen desconocido hasta revisarlos uno por uno.

**Fix propuesto:**

- **test_version:** reescribir para leer ambos archivos (`pyproject.toml` y `src/lazy_harness/__init__.py`) y comparar entre sí, sin hardcodear valor esperado. release-please garantiza sync; el test valida el invariante.
- **ruff:** correr `uv run ruff check --fix src tests` para los 3 auto-fixable, luego revisar los ~20 restantes uno por uno. Si alguno es falso positivo o regla nueva que no nos aplica, editar `pyproject.toml` para excluirla con justificación en commit.

**Impacto:** **bloqueante** — cualquier PR que toque código o tests empieza con el gate rojo, lo que viola la disciplina del repo desde el primer commit. Fixear esto antes de cualquier feature work.

## Done

- [x] **PreToolUse security hook** — blocks destructive filesystem/git/sql/terraform commands + credentials reads + forced secret commits, with per-profile `allow_patterns` escape hatch (feat/security-hooks-cluster)
- [x] **PostToolUse auto-format hook** — runs `ruff format` on `.py` edits/writes fail-soft (feat/security-hooks-cluster)

### ADR decisions pending

Capturadas durante el audit de task #3 (ver `specs/adrs/README.md`). Son decisiones de arquitectura, no cleanup:

- **Legacy ADR-010 Ollama backend** — `specs/archive/adrs-legacy/010-ollama-local-llm-integration.md`. Propone backend alternativo para compound-loop-worker usando Ollama local. Decisión: ¿promover a ADR activo como alternativa configurable, o descartar formalmente? Criterio: si pensás usar Ollama en los próximos 3 meses, promoverlo; si no, descartar con nota de "revaluar cuando haya presión de costo/rate limit".
- **Legacy ADR-013 Proactivity levels per profile** — `specs/archive/adrs-legacy/013-proactivity-levels-per-profile.md`. Propone niveles (Observer/Advisor/Assistant/Partner) de autonomía configurable por perfil. Decisión: ¿vale la indirección para dos perfiles, o alcanza con las instrucciones en el `CLAUDE.md` de cada perfil? Criterio: si agregás un tercer perfil, promoverlo; si no, descartar.
- **ADR-018 implementation epic** — `specs/adrs/018-config-discoverability.md` está `accepted-deferred`. Su implementación (`lh config <feature>` + sección Features en `lh doctor`) arranca cuando aterrice el **segundo** extension point (hoy solo hay `metrics_sink`). Trigger explícito, no fecha.
