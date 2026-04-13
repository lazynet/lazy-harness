# ADR-002: Setup multi-cuenta Claude Code (personal / work)

**Estado**: supersedido por ADR-009

**Fecha**: 2026-03-28

## Contexto

Uso Claude Code tanto para proyectos personales (`~/repos/lazy/`) como laborales
(`~/repos/flex/`). Cada contexto tiene identidad distinta (Martin Vago@lazyt vs Martin Vago@flexibility),
reglas distintas, y potencialmente cuenta/API key distinta.

Hoy todo vive en `~/.claude/` sin separacion. El CLAUDE.md actual menciona un setup
multi-cuenta aspiracional (wrapper script en `~/bin/claude`, directorio `~/.claude-flex/`)
pero nada de eso existe.

> **ACTUALIZACIÓN 2026-04-01**: `CLAUDE_CONFIG_DIR` fue verificado como funcional en
> Claude Code v2.1.89. Auth se aísla por directorio. Sesiones paralelas con cuentas
> distintas son posibles. Ver ADR-009 para la nueva decisión.

### Restricciones tecnicas de Claude Code (verificado 2026-03-28)

**Jerarquia de settings** (mayor a menor prioridad):
1. Managed (enterprise, read-only)
2. CLI args (`--model`, `--permission-mode`, etc.)
3. Local: `<proyecto>/.claude/settings.local.json` (gitignored)
4. Project: `<proyecto>/.claude/settings.json` (versionado)
5. User: `~/.claude/settings.json`

**CLAUDE.md se concatena** desde multiples fuentes (todos se aplican, no se pisan):
- `~/.claude/CLAUDE.md` (user-level, siempre carga)
- `CLAUDE.md` en raiz del proyecto
- `.claude/CLAUDE.md` en raiz del proyecto

**Hooks se mergean** desde todos los niveles. Los de user + project + local corren todos.

~~**NO existe** `CLAUDE_CONFIG_DIR` ni forma nativa de apuntar `~/.claude/` a otro directorio.~~
**CORREGIDO**: `CLAUDE_CONFIG_DIR` funciona desde v2.1.89+ (verificado 2026-04-01).

**Autenticacion**: Claude Code autentica por sesion. Para usar cuentas distintas
(personal vs work) con suscripcion claude.ai, el flujo es `claude auth logout && claude auth login`.
No existe `claude auth switch` (verificado 2026-03-31). Para API keys, se puede usar
`ANTHROPIC_API_KEY` via direnv.

~~**Sesiones paralelas con cuentas distintas son imposibles con suscripcion**~~ **CORREGIDO**: posibles via `CLAUDE_CONFIG_DIR` (verificado 2026-04-01).
Contexto original (2026-04-01):
El token OAuth se guarda en macOS Keychain bajo `Claude Code-credentials` → clave `claudeAiOauth`.
Es estado global por usuario del sistema. No hay aislamiento por proceso ni por directorio.
Swapear el keychain entry afecta todas las sesiones activas simultaneamente.
Alternativas evaluadas y descartadas:
- Swap de token en keychain: funciona para switch secuencial, rompe sesiones paralelas.
- `CLAUDE_CONFIG_DIR`: no existe, feature request abierto.
- Dos usuarios macOS: viable tecnicamente, inaceptable en UX.
- **Unica solucion real para paralelismo**: API keys via `ANTHROPIC_API_KEY` + direnv.
  Requiere tener API keys (pago por uso), no aplica con suscripcion pura.

## Decision

Usar la **jerarquia nativa de Claude Code** (user → project → local) para separar
perfiles, en vez de hackear symlinks o directorios alternativos.

### Arquitectura de 3 capas

```
Capa 1: USER-LEVEL (~/.claude/)
├── CLAUDE.md           → identidad base, reglas globales, estilo, prohibiciones
├── settings.json       → permisos globales, plugins compartidos, MCP servers comunes
└── (hooks globales definidos en settings.json)

Capa 2: PROJECT-LEVEL (~/repos/lazy/.claude/ y ~/repos/flex/.claude/)
├── CLAUDE.md           → identidad de perfil, contexto especifico, repos relacionados
├── settings.json       → permisos adicionales, hooks de perfil, MCP servers de perfil
└── .envrc (direnv)     → ANTHROPIC_API_KEY del perfil correspondiente

Capa 3: REPO-LEVEL (~/repos/lazy/<proyecto>/.claude/ o ~/repos/flex/<proyecto>/.claude/)
├── CLAUDE.md           → contexto del proyecto especifico
├── settings.json       → permisos del proyecto
└── settings.local.json → overrides locales (gitignored)
```

### Que va en cada capa

**Capa 1 — User (`~/.claude/`)**: lo que aplica SIEMPRE, sin importar contexto.
- Reglas de estilo (español casual, codigo en ingles)
- Prohibiciones universales (no generar tests/docs sin pedir, no refactors sueltos)
- Stack global (Python, TypeScript, Bash, Docker)
- Plugins compartidos (claude-md-management, github, etc.)
- Hooks globales: logging, safety checks

**Capa 2 — Profile (`~/repos/lazy/.claude/` y `~/repos/flex/.claude/`)**: lo que
diferencia personal de work.
- Identidad git (lazynet vs martin.vago@flexibility)
- Arquitectura de repos de ese perfil
- MCP servers especificos (ej: Jira solo en flex, homelab solo en lazy)
- Hooks de perfil: ej. en flex, hook que valida que no se commitee a repos personales
- API key via direnv + `.envrc`

**Capa 3 — Repo**: contexto ultra-especifico del proyecto.
- PRD, tech stack particular, convenciones del proyecto
- Permisos granulares (ej: allow cargo test solo en lazent)
- `settings.local.json` para overrides que no van a git

### Autenticacion con direnv

```bash
# ~/repos/lazy/.envrc
export ANTHROPIC_API_KEY="sk-ant-personal-..."

# ~/repos/flex/.envrc
export ANTHROPIC_API_KEY="sk-ant-flex-..."
```

direnv carga la key correcta automaticamente al entrar al directorio.
chezmoi gestiona los `.envrc` como templates (la key real viene de secrets).

### Conocimiento compartido con etiquetas

El conocimiento es unico (una sola persona), pero se aplica diferente segun contexto.
Esto se resuelve en la Capa 2 del CLAUDE.md:

```markdown
# ~/repos/lazy/.claude/CLAUDE.md
## Contexto personal
- Proyectos: lazent, lazy-ai-tools, lazy-homelab, dotfiles
- Identidad git: lazynet
- Libertad total para experimentar, romper cosas, iterar rapido
- Conocimiento aplicable: todo (infra, AI, dev, PKM)
```

```markdown
# ~/repos/flex/.claude/CLAUDE.md
## Contexto laboral — Flexibility
- Identidad git: martin.vago@flexibility
- Aplican estandares de equipo, code review, CI/CD corporativo
- Conocimiento aplicable: arquitectura, liderazgo tecnico, AI aplicada
- NO mencionar proyectos personales ni infraestructura del homelab
```

### Hooks: globales vs perfil

**Globales** (en `~/.claude/settings.json`):
```json
{
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "echo \"Profile: $(basename $(dirname $PWD))\"",
        "description": "Log active profile on session start"
      }
    ]
  }
}
```

**De perfil** (en `~/repos/flex/.claude/settings.json`):
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "type": "command",
        "command": "if echo \"$TOOL_INPUT\" | grep -q '/repos/lazy/'; then echo 'DENY: no tocar repos personales desde contexto work'; exit 2; fi",
        "toolName": "Bash",
        "description": "Prevent cross-profile repo access"
      }
    ]
  }
}
```

## Alternativas evaluadas

### A) Wrapper script con symlinks
Un script `~/bin/claude` que detecta CWD y cambia el symlink `~/.claude` → `~/.claude-personal/`
o `~/.claude-flex/` antes de lanzar el binario real.

**Descartado**:
- Race condition si corren dos sesiones simultaneas en perfiles distintos
- Fragil: cualquier proceso que toque `~/.claude/` mientras se swapea puede romper
- Reimplementa algo que Claude Code ya resuelve con su jerarquia de settings
- Claude es un binario de ~200MB, no es wrappeable trivialmente

### B) CLAUDE_CONFIG_DIR (env var)
Setear una variable de entorno para que Claude Code use un directorio distinto.

**Descartado**: no existe. Es un feature request abierto en el repo de Claude Code.
Si lo implementan en el futuro, se podria migrar. Pero hoy no es opcion.

### C) Jerarquia nativa user → project → local (elegido)
Aprovechar que Claude Code ya mergea CLAUDE.md de multiples fuentes y aplica settings
en cascada. Poner lo general en user-level, lo de perfil en project-level.

**Ventajas**:
- Cero hacks. Usa el mecanismo oficial
- Sin race conditions (cada sesion lee su propio project-level)
- Chezmoi puede gestionar user-level, git gestiona project-level
- Escala a N perfiles sin complejidad adicional

### D) Todo en user-level con hooks de deteccion
Un CwdChanged hook que detecta si estas en lazy/ o flex/ y ajusta comportamiento.

**Descartado parcialmente**: los hooks no pueden cambiar settings en runtime. Sirven
para validacion (ej: prevenir cross-profile access) pero no para cargar configs distintas.
Se incorpora como complemento de la opcion C, no como alternativa.

## Consecuencias

- `~/.claude/CLAUDE.md` se limpia: solo reglas universales, sin mencion de perfiles
- Se crean `~/repos/lazy/.claude/` y `~/repos/flex/.claude/` con CLAUDE.md y settings
  especificos de cada perfil
- Se instala direnv y se configuran `.envrc` en cada raiz de perfil para API keys
- chezmoi gestiona: `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `.envrc` templates
- git gestiona: `.claude/` dentro de cada repo de proyecto (Capa 3)
- La seccion "Identidades Claude Code" del CLAUDE.md actual se elimina (era aspiracional)
- Si en el futuro se implementa `CLAUDE_CONFIG_DIR`, se puede simplificar, pero la
  arquitectura actual funciona sin el

## Implementacion (orden sugerido)

1. **ADR aprobado** → este documento
2. **Instalar direnv** si no esta (`brew install direnv`)
3. **Refactorizar `~/.claude/CLAUDE.md`** → solo Capa 1 (universal)
4. **Crear `~/repos/lazy/.claude/`** → CLAUDE.md + settings.json de perfil personal
5. **Crear `~/repos/flex/.claude/`** → CLAUDE.md + settings.json de perfil work
6. **Configurar `.envrc`** en cada raiz con API key correspondiente
7. **Agregar hooks de perfil** segun necesidad
8. **Migrar a chezmoi** los archivos de Capa 1 y los templates de .envrc
