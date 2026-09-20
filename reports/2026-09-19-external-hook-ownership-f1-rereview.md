# Rerevisión focalizada de F1 — external-hook-ownership

Fecha: 2026-09-19. Dictamen: **GO**.

## Alcance

Se revisó exclusivamente F1, tal como fue formulado en
`reports/2026-09-19-external-hook-ownership-coherence-audit.md:5` y `:22`:
la contradicción entre el ownership total y destructivo que ADR-031 y la entrada
Done atribuían al bloque de hooks, frente al ownership por entrada que implementan
los adapters y documenta ADR-054. No se reauditaron F2–F9. La revisión fue de
lectura; no se ejecutaron tests ni se modificó código, documentación o commits.

## Evidencia

1. **La evolución de ADR-031 reemplaza exactamente el contrato contradictorio.**
   La decisión original sigue visible: ownership completo en
   `specs/adrs/031-default-hooks-merge.md:38-54`, rechazo de preservar entradas
   desconocidas en `specs/adrs/031-default-hooks-merge.md:68-72` y pérdida de
   hand-edits en `specs/adrs/031-default-hooks-merge.md:98-101`. La nueva evolución
   limita el contrato vigente a reconciliar builtins reconocidos y preservar
   entradas externas/foreign (`specs/adrs/031-default-hooks-merge.md:181-187`),
   define `external` como ensure-present y no borrable por omisión
   (`specs/adrs/031-default-hooks-merge.md:189-194`) y declara expresamente que el
   texto anterior queda como decisión histórica, no como contrato actual
   (`specs/adrs/031-default-hooks-merge.md:194-196`). No se reescribió ni ocultó
   la historia.

2. **ADR-031 queda alineado con ADR-054, sin ampliar su semántica.** ADR-054
   establece provenance externa, equivalencia nativa, conservación de metadata
   válida más rica y de duplicados foreign
   (`specs/adrs/054-external-hook-placeholders.md:147-155`); también establece que
   omitir una declaración sólo deja de asegurarla y no autoriza borrarla
   (`specs/adrs/054-external-hook-placeholders.md:157-160`). La evolución agregada
   a ADR-031 reproduce precisamente esa frontera.

3. **El ownership vigente está implementado antes de entrar a los adapters.**
   `HookOwnership` distingue `HARNESS` de `EXTERNAL` y documenta que omitir un
   externo nunca concede autoridad de borrado (`src/lazy_harness/agents/base.py:59-67`).
   El engine marca sólo builtins como `HARNESS`, y scripts de usuario y entradas
   `external` como `EXTERNAL` (`src/lazy_harness/deploy/engine.py:418-438`).

4. **Claude reconcilia sólo ownership probado.** Las posiciones managed se
   recuperan por provenance exacta o por reconocimiento exacto de builtin
   (`src/lazy_harness/agents/claude_code.py:330-350`). Al mezclar, sólo esas
   posiciones pueden retirarse; las demás se conservan, y una declaración nativa
   equivalente desplaza la versión externa generada para retener metadata más
   rica (`src/lazy_harness/agents/claude_code.py:425-453`). Sin hooks deseados ni
   ownership previo, el planner no escribe un bloque vacío destructivo
   (`src/lazy_harness/agents/claude_code.py:1211-1216`).

5. **Codex aplica la misma frontera.** El ownership deriva de provenance y exige
   coincidencia exacta con un builtin (`src/lazy_harness/agents/codex.py:653-683`).
   El merge reemplaza o elimina sólo posiciones owned, conserva todas las demás
   y agrega un externo únicamente si no existe una identidad equivalente
   (`src/lazy_harness/agents/codex.py:699-740`). Si no hay managed, external ni
   ownership previo, no produce operación (`src/lazy_harness/agents/codex.py:1090-1099`).

6. **Copilot materializa la misma semántica mediante ownership por archivo.**
   Separa el artefacto managed del artefacto ensure-present, migra los grupos
   legacy que no puede probar como builtins y sólo retira el archivo reservado
   managed cuando deja de generarlo (`src/lazy_harness/agents/copilot.py:330-396`).
   El merge externo parte de todas las entradas instaladas, conserva multiplicidad
   durante la migración y sólo agrega identidades ausentes
   (`src/lazy_harness/agents/copilot.py:399-460`). La omisión posterior retorna sin
   operación (`src/lazy_harness/agents/copilot.py:406-408`).

7. **La entrada Done ya no contradice el contrato actual ni falsea el original.**
   `specs/backlog.md:173` califica como originales tanto el literal
   `DEFAULT_HOOKS` como los 11 tests, conserva el merge y el opt-out que motivaron
   ADR-031, y describe por separado el ownership actual de builtins y el ciclo
   ensure-present de externos. Ya no afirma clobber de hooks manuales ni ownership
   del bloque completo.

## Dictamen

La remediación elimina exactamente F1: corrige las dos superficies que el finding
nombró, conserva el texto histórico original y expresa el mismo ownership que ADR-054
y los tres adapters implementan. No introduce una afirmación funcional más amplia
que el código inspeccionado. F2–F9 quedan fuera de este dictamen.

**GO**

DONE
