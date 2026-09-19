# Next-session prompt — land and roll out Wave 1

Copy the block below into a fresh session.

```text
Retomá lazy-harness desde el worktree
/Users/lazynet/repos/lazy/lazy-harness/.worktrees/wave-1-implementation,
branch feat/wave-1-implementation.

Leé AGENTS.md; CLAUDE.md fue eliminado deliberadamente y con aprobación
explícita porque Claude Code 2.1.278 pierde los imports de un CLAUDE.md padre
cuando arranca desde subdirectorios. No restaures el archivo ni reviertas esa
decisión sin evidencia nueva de un binario instalado.

Estado verificado al cerrar la sesión del 2026-09-19:

- HEAD: e9f87b6 docs: record proposal queue drain
- implementación principal: 2dc5553 feat: implement wave 1 design
- commits previos integrados: 53f7305, e01d68f, 123778c, 75cf439
- worktree limpio, branch sin upstream
- gate final sobre el árbol implementado: 5104 tests; Ruff lint y format;
  MkDocs strict; git diff --check, todo verde
- cola de memory proposals: 0 pending; 11 rejected con autorización explícita
- reporte canónico:
  reports/2026-09-19-wave-1-implementation-audit-remediation.md

Objetivo de esta iteración: aterrizar Wave 1 en main y completar sólo el rollout
binary-first que queda desbloqueado por merge/release. Orquestá agentes Codex o
Claude para reviews independientes; no uses Hermes. No cambies la cuenta activa
de gh.

Orden obligatorio:

1. Compará la branch con main y revisá los commits, sin rehacer el design ni la
   auditoría. Si main avanzó, integralo de forma no destructiva y repetí el gate
   proporcional al cambio.
2. Push de feat/wave-1-implementation, abrí PR con el reporte como evidencia y
   esperá checks. Corregí sólo findings concretos. Mergeá según el workflow del
   repo; no uses --no-verify ni cambies la cuenta gh.
3. Esperá el release de release-please. No hagas bump manual ni tag manual.
4. Cumplí la regla binary-first: instalá la release, confirmá en site-packages
   que contiene project_state, repo_instructions y deploy/skills nuevos, y recién
   después desplegá profiles/config.
5. Ejecutá el probe instalado de ADR-059 en ambas direcciones con
   codex debug prompt-input: una skill proyectada por la release aparece y, tras
   retirar sólo el link owned y redeployar, desaparece. No borres skills de
   usuario ni adoptes entries sin ledger. Restaurá el estado desplegado esperado
   al terminar.
6. Verificá que GitHub cierre las dos alertas Dependabot de anyio después del
   merge. Si siguen abiertas, registrá la evidencia exacta; no fuerces cambios
   adicionales en uv.lock sin una alerta concreta.
7. Reauditá queue/done retention con una corrida real y confirmá que lh status
   queue sigue mostrando Done total. No borres manualmente históricos fuera de
   la política implementada.
8. Escribí un reporte de rollout y dejá el árbol limpio.

No mezcles en esta iteración:

- los pilotos ADR-060 de lazy-ai-tools y dotfiles ni su ventana de siete días;
- receiver/backfill/Grafana de ADR-061;
- archival y opt-in de PRJ-LazyHarness de ADR-062;
- el bug histórico de pre_compact con mensajes Claude anidados, ya abierto en
  specs/backlog.md.

Esos cuatro son lanes separados. Si el rollout binary-first termina limpio,
proponé cuál sigue con sus tradeoffs, pero no lo ejecutes sin ampliar el scope.

Criterios de cierre:

- PR mergeado y release publicada sin bump/tag manual;
- release instalada y contenido verificado desde site-packages;
- probe Codex de skill proyectada pasa aparición y desaparición;
- profiles quedan desplegados desde el binario publicado;
- Dependabot queda cerrado o documentado con evidencia externa actual;
- queue retention validada por comportamiento;
- reporte final commiteado y worktree limpio.
```
