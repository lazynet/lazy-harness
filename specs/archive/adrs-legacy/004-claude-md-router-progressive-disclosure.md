# ADR-004: CLAUDE.md como router con progressive disclosure

**Estado**: aprobado

**Fecha**: 2026-03-30

**Depende de**: ADR-002 (setup multi-cuenta)

## Contexto

ADR-002 define una arquitectura de 3 capas para CLAUDE.md (user → profile → repo).
Los profiles actuales (`profiles/lazy/CLAUDE.md` y `profiles/flex/CLAUDE.md`) son
documentos monolíticos de ~40 líneas que mezclan identidad, convenciones, repos, y
conocimiento en un solo archivo.

Esto funciona hoy porque el contexto es pequeño. Pero escala mal:

1. **Context pollution**: Todo el contenido se carga en toda sesión, aunque solo
   una fracción sea relevante para la tarea actual.
2. **Atención degradada**: Los LLMs pierden fidelidad con instrucciones largas.
   Estudios empíricos (Boris Cherny, Anthropic Folder Method) muestran que
   CLAUDE.md > 200 líneas degrada la adherencia a reglas al final del archivo.
3. **Mantenimiento rígido**: Agregar contexto nuevo (ej: reglas de lazy-vault,
   convenciones de homelab) obliga a inflar el archivo o inventar prioridades.

Múltiples fuentes del vault convergen en la misma solución:

- **Boris Cherny (5-Layer Stack)**: CLAUDE.md como routing document, no enciclopedia.
- **"World-Class Agentic Engineer"**: CLAUDE.md como IF-ELSE directory que apunta a
  archivos temáticos según contexto.
- **"Context Engineering Is The Only Engineering That Matters"**: Progressive disclosure
  en 3 niveles (routing → module → data).
- **"Anthropic Folder Method"**: Skills efectivos tienen SKILL.md como orquestador
  con archivos separados por concern.

## Decision

Refactorizar los CLAUDE.md de profile (Capa 2) como **routers IF-ELSE** que apuntan
a documentos temáticos, en vez de contener instrucciones inline.

### Estructura propuesta

```
profiles/lazy/
├── CLAUDE.md              # Router: identidad + reglas condicionales (~50 líneas)
├── docs/
│   ├── repos.md           # Arquitectura de repos, convenciones de naming
│   ├── tooling.md         # Stack: uv, chezmoi, QMD, lazy-ai-tools
│   ├── homelab.md         # Proxmox, Forgejo, Ansible, network
│   ├── vault.md           # LazyMind: estructura, taxonomía, maintenance
│   └── governance.md      # Control tower: ADRs, deploy, workflows
├── commands/
│   └── recall.md
└── settings.json
```

```
profiles/flex/
├── CLAUDE.md              # Router: identidad + reglas condicionales (~30 líneas)
├── docs/
│   ├── repos.md           # Repos Flex, convenciones del equipo
│   ├── team.md            # Estructura del equipo, procesos de review
│   └── restrictions.md    # Barreras de seguridad cross-profile
└── settings.json
```

### Router pattern

El CLAUDE.md de profile se convierte en un router que carga contexto on-demand:

```markdown
# Contexto personal — lazynet

Identidad git: lazynet. GitHub: github.com/lazynet.
Libertad total para experimentar. No hay code review obligatorio.

## Contexto condicional

- Si trabajás en un repo bajo `~/repos/lazy/`: leé `docs/repos.md`
- Si trabajás con infraestructura o ansible: leé `docs/homelab.md`
- Si trabajás con el vault de Obsidian o vault-maintenance: leé `docs/vault.md`
- Si trabajás en lazy-claudecode: leé `docs/governance.md`
- Si necesitás instalar o configurar herramientas: leé `docs/tooling.md`

## Reglas universales del perfil

(solo las que aplican SIEMPRE, ~10 líneas)
```

### Progressive disclosure en 3 niveles

| Nivel | Qué contiene | Cuándo se carga | Tamaño |
|---|---|---|---|
| Routing | Identidad, reglas IF-ELSE | Siempre (auto) | <50 líneas |
| Module | docs/*.md temáticos | Cuando el agente lo necesita | 40-100 líneas c/u |
| Data | Archivos específicos del repo | Cuando el agente navega | Variable |

El agente decide qué cargar basándose en el routing. No se carga todo upfront.

### Compatibilidad con Claude Code

Claude Code carga `CLAUDE.md` y `.claude/CLAUDE.md` automáticamente.
Los docs/ temáticos NO se cargan automáticamente — el agente los lee bajo demanda
usando Read tool cuando el router se lo indica.

Esto es compatible con la mecánica actual. No requiere features nuevos de Claude Code.

## Alternativas evaluadas

### A) Mantener monolítico y confiar en el tamaño actual
Funciona hoy (~40 líneas por profile). Pero bloquea el crecimiento: cada nuevo
dominio (homelab docs, vault rules, team processes) infla el archivo.
**Descartado**: no escala.

### B) @import directives
Algunos frameworks soportan `@docs/repos.md` para incluir archivos automáticamente.
Claude Code no soporta esto nativamente en CLAUDE.md.
**Descartado**: requeriría un preprocesador custom.

### C) Router IF-ELSE con docs/ temáticos (elegido)
El agente lee las instrucciones condicionales y carga solo lo relevante.
**Ventajas**:
- Cero dependencias nuevas
- Compatible con Claude Code actual
- Cada doc es testeable independientemente
- Agregar contexto nuevo = agregar un archivo + una línea en el router
- Reduce context pollution a lo estrictamente necesario

### D) Todo en skills/
Mover cada dominio de conocimiento a un skill separado.
**Descartado parcialmente**: los skills se invocan explícitamente (/nombre).
El contexto de profile debe cargarse automáticamente sin invocación manual.
Los skills complementan pero no reemplazan el router.

## Consecuencias

- Los profiles/lazy/CLAUDE.md y profiles/flex/CLAUDE.md se refactorizan como routers
- Se crean carpetas docs/ en cada profile con archivos temáticos
- El contenido actual de cada CLAUDE.md se distribuye en los docs/ correspondientes
- deploy.sh sigue desplegando todo profiles/ como symlinks — no cambia
- Los archivos docs/ se versionan en git junto con el profile
- El tamaño del CLAUDE.md cargado automáticamente baja de ~40 líneas a <50 (routing only)
- El contexto total disponible sube (más docs temáticos) sin penalidad de context window
- Patrón replicable: si mañana hay un perfil "homelab", se crea con la misma estructura

## Implementación

Ver spec: `docs/archive/specs/2026-03-30-claude-md-router-migration.md`
