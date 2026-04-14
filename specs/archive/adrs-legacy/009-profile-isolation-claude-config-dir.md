# ADR-009: Profile isolation via CLAUDE_CONFIG_DIR

**Estado**: aceptado

**Fecha**: 2026-04-01

**Supersede**: ADR-002 (setup multi-cuenta con jerarquía nativa)

## Contexto

ADR-002 resolvió la separación de configuración entre perfiles (personal/work) usando
la jerarquía nativa de Claude Code: user → project → local. Funcionó para CLAUDE.md
y settings, pero dejó un problema sin resolver: **aislamiento de auth**.

Con la arquitectura de capas, ambos perfiles comparten `~/.claude/` y por tanto el
mismo token OAuth en el macOS Keychain. No es posible tener sesiones paralelas con
cuentas distintas, ni asegurar que el perfil correcto esté autenticado al abrir
una sesión.

### Discovery: CLAUDE_CONFIG_DIR está implementado

Verificado en Claude Code v2.1.89+: la variable de entorno `CLAUDE_CONFIG_DIR` existe
y funciona. Al setearla, Claude Code usa ese directorio como su `~/.claude/` completo:
auth, settings, plugins, sesiones, queue — todo aislado.

```bash
# Verificación directa
CLAUDE_CONFIG_DIR=/tmp/test claude config list
# → "Not logged in" (instancia completamente nueva, sin auth)
```

ADR-002 documentó `CLAUDE_CONFIG_DIR` como "feature request abierto, no implementado".
Esa información era incorrecta al momento de redactar ADR-009 — ya estaba disponible.

### Referencia externa: CCS (ccs.kaitran.ca)

CCS (Claude Code Switch) usa un patrón similar: mantiene instancias aisladas en
`~/.ccs/instances/[profile]/`, cada una con su propio CLAUDE_CONFIG_DIR. Es una
herramienta completa con routing de modelos y UI. Confirma que el patrón es viable
en producción.

## Decision

**Full isolation via CLAUDE_CONFIG_DIR + wrapper script genérico (`lcc`).**

En vez de un único `~/.claude/` compartido, cada perfil tiene su propio directorio
aislado. Un wrapper detecta el CWD y setea `CLAUDE_CONFIG_DIR` antes de lanzar Claude.

### Estructura de directorios

```
~/.claude-lazy/     ← perfil personal (auth, settings, plugins, sessions, queue)
~/.claude-flex/     ← perfil work (ídem, completamente separado)
~/.claude           ← symlink → ~/.claude-lazy (compat con third-party tools)
```

### Wrapper: lcc (LazyClaudeCode)

```bash
# ~/.local/bin/lcc
#!/usr/bin/env bash
set -euo pipefail

# Lee ~/.config/lcc/profiles: mapeo CWD-prefix → CLAUDE_CONFIG_DIR
PROFILE_DIR=$(lcc-detect-profile "$PWD")
export CLAUDE_CONFIG_DIR="$PROFILE_DIR"
exec claude "$@"
```

El archivo de configuración `~/.config/lcc/profiles` mapea prefijos de path a perfiles:

```
/Users/lazynet/repos/lazy   ~/.claude-lazy
/Users/lazynet/repos/flex   ~/.claude-flex
```

La detección es longest-prefix-match: el path más específico que sea prefijo del CWD gana.
Si ninguno matchea, usa `~/.claude-lazy` como default.

### Qué vive en cada CLAUDE_CONFIG_DIR

Cada directorio de perfil es self-contained:
- `auth` / credentials (OAuth token propio por perfil)
- `settings.json` (hooks, permisos, plugins, MCP servers del perfil)
- `CLAUDE.md` de nivel user para ese perfil
- Sessions y queue propios

### QMD como nexo de conocimiento

QMD indexa ambos mundos (lazy + flex) y es el punto de acceso compartido al
conocimiento acumulado. No requiere aislamiento: el conocimiento es de la persona,
no del perfil.

### Hook scripts: path portable

Los scripts que referencian `~/.claude/` se actualizan para usar:

```bash
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
```

Así funcionan tanto con `lcc` (que setea `CLAUDE_CONFIG_DIR`) como con `claude` directo.

## Alternativas evaluadas

### A) Jerarquía nativa (ADR-002) — descartado para auth isolation

Funciona para separación de config y CLAUDE.md, pero no resuelve el aislamiento de
auth. Ambos perfiles comparten el mismo token OAuth.

**Descartado como solución completa**. Los conceptos de separación por capas siguen
siendo válidos dentro de cada perfil.

### B) CCS tool — descartado

Herramienta completa con routing de modelos, UI de switching, y gestión de instancias.

**Descartado**: agrega dependencia npm que no necesito, el routing de modelos es
funcionalidad que no uso, y es overengineering para dos perfiles. El patrón central
(CLAUDE_CONFIG_DIR por instancia) sí se adopta.

### C) Raw CLAUDE_CONFIG_DIR por repo via direnv — descartado

Setear `CLAUDE_CONFIG_DIR` en cada `.envrc` de cada repo directamente.

**Descartado**: requiere configuración manual en cada repo, sin auto-detección.
Verbose y propenso a olvidos. El wrapper centraliza esto.

### D) Full isolation via CLAUDE_CONFIG_DIR + wrapper (elegido)

Transparente para el usuario: se usa `lcc` en lugar de `claude`, el resto es
automático. Cero deps externos, configuración centralizada en un archivo, extensible
a N perfiles.

## Consecuencias

- **ADR-002 supersedido**: la jerarquía de 3 capas queda reemplazada por aislamiento
  completo. Los workspace routers (`~/repos/lazy/.claude/CLAUDE.md`) pasan a ser
  loaders condicionales ligeros, no la fuente principal de config del perfil.

- **deploy.sh actualizado**: targets cambian de `~/.claude/` a `~/.claude-<nombre>/`
  según el perfil. Cada perfil tiene su propio deploy.

- **settings.json por perfil es self-contained**: hooks, permisos, plugins y MCP
  servers van todos en `~/.claude-<nombre>/settings.json`. Ya no dependen del merge
  de capas.

- **Email-check SessionStart hook eliminado**: el hook que verificaba la cuenta activa
  via `claude auth status` pierde sentido. Con CLAUDE_CONFIG_DIR, la auth está
  garantizada por el directorio — no hace falta checkearla en runtime.

- **Hook scripts portables**: todos los scripts que referencian `~/.claude/` usan
  `${CLAUDE_CONFIG_DIR:-$HOME/.claude}` para funcionar en cualquier contexto.

- **`~/.claude` como symlink**: apunta a `~/.claude-lazy` (default). Herramientas de
  terceros que hardcodean `~/.claude/` siguen funcionando.

- **lcc en PATH**: `~/.local/bin/lcc` es el entrypoint recomendado. `claude` directo
  sigue disponible para casos donde se quiere control explícito del directorio.
