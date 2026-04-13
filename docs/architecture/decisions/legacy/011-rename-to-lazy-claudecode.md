# ADR-011: Rename to lazy-claudecode

**Estado**: aceptado
**Supersede**: ADR-001

**Fecha**: 2026-04-03

## Contexto

lazy-control-tower fue creado como repo de gobernanza del entorno de desarrollo (ADR-001).
En la práctica, 8 de 10 ADRs, todos los scripts, hooks, profiles y skills son específicos
de Claude Code. El repo es un harness engineering system, no un control tower genérico.

## Decision

Renombrar a `lazy-claudecode`. El nuevo propósito:

> lazy-claudecode es el harness engineering system del setup de Claude Code de lazynet.
> Contiene profiles, hooks, skills, memory pipeline, CLI tools y monitoring — la capa
> de software que hace que Claude Code funcione como yo quiero.

### In scope

- Profiles (CLAUDE.md, settings.json por cuenta)
- Hooks (SessionStart, Stop, compound-loop, session-export)
- Skills (recall-cowork, futuros skills)
- CLI tools (lcc, lcc-admin)
- Monitoring (lcc-status, pricing, token stats)
- Memory pipeline (compound-loop-worker, learnings-review, session-context)
- QMD integration (context-gen, colecciones para datos de CC)
- LaunchAgents del harness
- ADRs sobre decisiones de arquitectura de Claude Code
- Deploy system (deploy.sh)
- Workspace routers

### Out of scope

- Dotfiles y configs de herramientas (chezmoi)
- Conocimiento personal (LazyMind/Obsidian)
- Gobernanza general de herramientas (futuro repo)

## Alternativas evaluadas

### A) Split en dos repos (CC + tools)
Separar Claude Code de herramientas genéricas.
**Descartado**: QMD, monitoring, LaunchAgents existen para servir al harness. Splitear
crea dependencia circular y duplica deploy.

### B) Rename sin redefinir alcance
Solo cambiar el nombre.
**Descartado**: el propósito original de ADR-001 ya no aplica. Renombrar sin redefinir
deja el repo sin norte claro.

### C) Rename + redefinir alcance (elegido)
Nuevo nombre refleja contenido real. Nuevo propósito como harness engineering system.
`inventory/` se elimina (sin consumidores). Docs históricos se archivan.

## Consecuencias

- ADR-001 queda supersedido por este ADR
- Refs funcionales actualizadas (scripts, profiles, skills, workflows, CLAUDE.md)
- QMD collection renombrada
- lcc / lcc-admin se mantienen (acronimo funciona para ambos nombres)
- Docs historicos en docs/archive/ conservan el nombre viejo
