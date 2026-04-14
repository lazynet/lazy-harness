# QMD: Gestión de Colecciones

> **Archived.** Originally from `lazy-claudecode/workflows/`. Preserved for historical context; some references may be stale.


## Convención de nomenclatura

Patrón: `{perfil}-{repo|source}[-{area}]`

- **Prefijo de perfil**: `lazy-` (personal), `flex-` (work)
- **Fuente**: nombre corto del repo o vault
- **Área** (opcional): sufijo cuando se splitea una fuente grande

### Ejemplos

| Colección | Fuente | Qué indexa |
|---|---|---|
| `lazy-lazymind-projects` | LazyMind vault | 1-Projects (PARA) |
| `lazy-lazymind-resources` | LazyMind vault | 3-Resources (PARA) |
| `lazy-lazymind-areas` | LazyMind vault | 2-Areas (PARA) |
| `lazy-lazymind-meta` | LazyMind vault | Meta/ (sessions, templates) |
| `lazy-claudecode` | Repo | ADRs, hooks, skills, profiles del harness |
| `lazy-homelab` | Repo | Docs de lazy-ansible |
| `flex-supervielle` | Repo | Toda la consultoría |

### Reglas para agregar colecciones nuevas

1. Siempre usar el patrón `{perfil}-{repo}[-{area}]`
2. Un repo = una colección, salvo que sea muy grande (>500 archivos) y tenga áreas semánticas claras
3. Solo splitear por áreas cuando el split agrega valor de filtrado real (ej: PARA en LazyMind)
4. Incluir siempre `context` con descripción de qué contiene la colección
5. No indexar 0-Inbox (transitorio) ni 4-Archive (muerto) de LazyMind
6. Pattern por defecto: `"**/*.md"` salvo que el repo tenga otros formatos relevantes

### Qué NO hacer

- No crear colecciones por tipo de documento (adr, docs, iniciativas) dentro del mismo repo
- No duplicar paths: si una colección cubre un directorio, no crear otra que sea subdirectorio
- No usar nombres genéricos (docs, notes, stuff)

## Estrategia de actualización

Tres capas, de más frecuente a menos:

### Capa 1: Hooks (reactivo)

- **Stop hook de Claude Code**: al cerrar sesión, exporta a markdown y hace
  `qmd update --collection lazy-lazymind-meta`
- Config: `~/.claude/settings.json` → hooks.Stop
- Script fuente: `lazy-claudecode/scripts/hooks/claude-session-export.sh`

### Capa 2: Cron cada 30 minutos (cobertura)

- Script fuente: `lazy-claudecode/scripts/qmd-sync.sh`
- LaunchAgent: `lazy-claudecode/launchd/com.lazynet.qmd-sync.plist`
- Hace `qmd update` de todas las colecciones
- Log: `~/.local/share/qmd/sync.log` (auto-rotación a 1MB)

### Capa 3: Embed diario (semántico)

- Script fuente: `lazy-claudecode/scripts/qmd-embed.sh`
- LaunchAgent: `lazy-claudecode/launchd/com.lazynet.qmd-embed.plist`
- Corre a las 06:00 AM, rebuild de vectores para búsqueda semántica
- Log: `~/.local/share/qmd/embed.log`

## Despliegue

Todos los scripts y LaunchAgents viven en este repo. Se despliegan via symlinks
con el script `deploy.sh`:

```bash
# Deploy completo (scripts + LaunchAgents)
./scripts/deploy.sh

# Solo scripts
./scripts/deploy.sh scripts

# Solo LaunchAgents (macOS)
./scripts/deploy.sh launchd
```

El deploy es idempotente — se puede correr N veces sin romper nada.
En Linux (homelab), `deploy.sh launchd` se salta automáticamente.

### Estructura desplegada

```
~/.local/bin/
  claude-session-export.sh → lazy-claudecode/scripts/claude-session-export.sh
  qmd-sync.sh              → lazy-claudecode/scripts/qmd-sync.sh
  qmd-embed.sh             → lazy-claudecode/scripts/qmd-embed.sh

~/Library/LaunchAgents/  (solo macOS)
  com.lazynet.qmd-sync.plist  → lazy-claudecode/launchd/com.lazynet.qmd-sync.plist
  com.lazynet.qmd-embed.plist → lazy-claudecode/launchd/com.lazynet.qmd-embed.plist
```

## Agregar una colección nueva

```bash
# 1. Agregar la colección
qmd collection add /path/al/proyecto --name flex-nombre-mgmt

# 2. (Opcional) Agregar descripción fija en ~/.config/qmd/index.yml:
#    context:
#      "": >
#        Descripción del proyecto. <!-- auto -->

# 3. Regenerar contextos dinámicos (o esperar al próximo cron)
qmd-context-gen.sh

# 4. Generar embeddings (o esperar a las 6am)
qmd embed
```

El `<!-- auto -->` delimiter separa la parte fija (tuya) de la dinámica (auto-generada).
Todo lo antes del delimiter se preserva. Todo lo después se regenera cada 30 min
con conteo de archivos y subdirectorios.

Si no ponés descripción fija, el script genera solo la parte dinámica.

## Config

Archivo: `~/.config/qmd/index.yml`

`qmd-context-gen.sh` solo actualiza la parte dinámica de los contextos.
Nunca agrega ni remueve colecciones — eso es responsabilidad del usuario
vía `qmd collection add/remove` o editando el YAML directamente.

Pendiente migración a chezmoi.
