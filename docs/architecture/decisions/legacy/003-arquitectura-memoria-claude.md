# ADR-003: Arquitectura de memoria para Claude Code

**Estado**: aceptado

**Fecha**: 2026-03-29

**Depende de**: ADR-002 (setup multi-cuenta)

## Contexto

Claude Code pierde todo el contexto entre sesiones. Cada conversacion arranca de cero:
hay que re-explicar arquitecturas, decisiones, preferencias, y estado del proyecto.
Con 50+ sesiones por semana, el costo de re-contextualizacion es enorme.

El problema tiene dos dimensiones:

1. **Memoria de agente**: que Claude recuerde decisiones, patrones, y preferencias
   entre sesiones sin que yo tenga que repetirlas.
2. **Memoria de conocimiento**: que Claude pueda acceder a mi base de conocimiento
   (LazyMind) para buscar articulos, notas, y aprendizajes previos relevantes
   al trabajo actual.

Ademas, segun ADR-002, hay dos perfiles (personal/work) con contextos distintos.
La memoria debe respetar esa separacion sin duplicar conocimiento compartido.

### Taxonomia de memoria (del analisis en LazyMind)

| Tipo | Que almacena | Persistencia | Ejemplo |
|---|---|---|---|
| Corto plazo | Conversacion actual | Volatil (sesion) | Ventana de contexto |
| Episodica | Historial de sesiones | Permanente | "Ayer arreglamos el bug de auth" |
| Semantica | Hechos, preferencias, arquitectura | Permanente | "Prefiero named exports en TS" |
| Procedimental | Workflows, reglas de estilo | Permanente | "Tests van antes de commit" |

### Estado actual

- **Auto-memory de Claude Code**: existe en `~/.claude/projects/<hash>/memory/`.
  Se genera automaticamente. No lo estoy usando activamente ni curando.
- **CLAUDE.md**: funciona como memoria procedimental (reglas, estilo, prohibiciones).
  Pero mezcla Capa 1 y Capa 2 (ver ADR-002).
- **LazyMind**: vault con 30+ articulos sobre Claude Code, memoria, workflows.
  No esta conectado a Claude Code como fuente de busqueda.
- **QMD**: skill instalado en `~/.claude/skills/qmd`. Motor de busqueda hibrida.
  No esta configurado para indexar el vault ni las sesiones.
- **Hooks**: no hay hooks de memoria. No se persiste nada al cerrar sesion.

## Decision

Implementar memoria en 4 capas que se alinean con la jerarquia del ADR-002,
mas una capa transversal de conocimiento.

### Capa 1: Memoria procedimental global (CLAUDE.md user-level)

Ya existe. Es `~/.claude/CLAUDE.md`. Contiene reglas, estilo, prohibiciones, stack.
Se lee en toda sesion. Gestionado por chezmoi.

**No cambia** respecto a ADR-002. Pero se le agrega:
- Instrucciones de como usar la memoria ("al inicio de sesion, consultar MEMORY.md
  del proyecto; al cerrar, persistir decisiones clave")
- Referencia a QMD como herramienta de busqueda en el vault

### Capa 2: Memoria de perfil (project-level .claude/)

Vive en `~/repos/lazy/.claude/` y `~/repos/flex/.claude/`.

Contiene MEMORY.md de perfil: decisiones recurrentes del contexto personal vs work.
Ejemplo personal: "en repos lazy, siempre commitear con conventional commits".
Ejemplo work: "en Flex, PRs requieren al menos 1 approval antes de merge".

**Generacion**: manual + sugerencias del agente via compound loop (ver abajo).
**Consumo**: Claude Code lo lee automaticamente como project-level CLAUDE.md.

### Capa 3: Memoria de proyecto (auto-memory nativa)

Ya existe en `~/.claude/projects/<hash>/memory/`. Claude Code la gestiona.

**Estructura recomendada** (basada en el articulo "Claude + Obsidian"):
```
~/.claude/projects/<hash>/memory/
├── MEMORY.md        # routing document, <200 lineas, siempre en contexto
├── architecture.md  # decisiones de arquitectura del proyecto
├── patterns.md      # patrones confirmados del codebase
├── debugging.md     # soluciones a problemas recurrentes
└── preferences.md   # preferencias especificas del proyecto
```

MEMORY.md es el indice — no un dump. Si crece mas de 200 lineas, hay que
extraer a archivos tematicos y linkear.

**Generacion**: auto-memory de Claude Code + instrucciones en CLAUDE.md para
que el agente persista activamente ("Update your MEMORY.md so this doesn't
happen again").
**Consumo**: automatico, Claude Code lo carga al iniciar sesion en ese proyecto.

### Capa transversal: LazyMind como knowledge graph

LazyMind es la base de conocimiento personal. Contiene articulos procesados,
notas de aprendizaje, daily notes, y reflexiones. Es unica — no se duplica
por perfil. Pero se consulta diferente segun contexto.

**Acceso via QMD MCP server**:
```json
{
  "mcpServers": {
    "qmd": {
      "command": "qmd",
      "args": ["mcp"],
      "env": {
        "HOME": "/Users/lazynet"
      }
    }
  }
}
```

QMD se configura en `~/.claude/settings.json` (Capa 1, user-level) porque
el vault es compartido entre perfiles. Los CLAUDE.md de perfil (Capa 2)
especifican QUE buscar y COMO filtrar segun contexto.

**Colecciones QMD** (una por area del vault):
- `articles`: articulos procesados de ReadItLater
- `projects`: notas de proyectos activos
- `dailies`: daily notes con reflexiones y decisiones
- `sessions`: sesiones de Claude Code exportadas (ver hooks)

**Busqueda hibrida**: BM25 para keywords exactas (80% de los casos),
semantica para conceptos sin match exacto, hybrid para queries complejas.

### Generacion de memoria: hooks y compound loop

**Hook post-sesion** (en `~/.claude/settings.json`, global):
Al cerrar sesion, exportar conversacion como markdown limpio e indexar en QMD.

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "~/.local/bin/claude-session-export.sh",
        "description": "Export session to markdown and index in QMD"
      }
    ]
  }
}
```

El script `claude-session-export.sh`:
1. Parsea el JSONL de la sesion → markdown limpio (solo user messages + decisions)
2. Guarda en `~/LazyMind/sessions/YYYY-MM-DD-<hash>.md`
3. Ejecuta `qmd update` para reindexar

**Compound loop** (instruccion en CLAUDE.md):
Al finalizar una tarea significativa, el agente debe:
1. Registrar que se resolvio y que patron emergio
2. Actualizar MEMORY.md del proyecto si el aprendizaje es recurrente
3. Si el aprendizaje aplica a nivel de perfil → sugerir update al CLAUDE.md de Capa 2

Esto no es automatico — es una instruccion en CLAUDE.md que el agente sigue (~80%).
Para garantizar que se ejecute, se puede reforzar con un hook PreToolUse en `git commit`
que recuerde al agente persistir antes de commitear.

### Recall: cargar contexto al iniciar sesion

**Skill /recall** (basado en el patron de Artem Zhutov):
Un skill en `.claude/skills/` que ofrece 3 modos:
- `temporal`: que sesiones hubo ayer/esta semana en este proyecto
- `topic`: busqueda BM25/semantica en QMD sobre un tema
- `graph`: visualizacion interactiva de sesiones y archivos tocados

Se invoca manualmente (`/recall yesterday`, `/recall topic auth migration`)
o se puede automatizar en un hook SessionStart para cargar contexto minimo.

### Diagrama completo

```
┌──────────────────────────────────────────────────────────┐
│ LazyMind (Obsidian vault) — Knowledge Graph transversal  │
│ Acceso: QMD MCP server (user-level settings)             │
│ Busqueda: BM25 + semantica + hybrid                      │
├──────────────────────────────────────────────────────────┤
│ Capa 3: Memoria de proyecto (auto-memory)                │
│ ~/.claude/projects/<hash>/memory/MEMORY.md               │
│ Generacion: auto + compound loop                         │
├──────────────────────────────────────────────────────────┤
│ Capa 2: Memoria de perfil                                │
│ ~/repos/lazy/.claude/MEMORY.md (personal)                │
│ ~/repos/flex/.claude/MEMORY.md (work)                    │
├──────────────────────────────────────────────────────────┤
│ Capa 1: Memoria procedimental global                     │
│ ~/.claude/CLAUDE.md (reglas, estilo, instrucciones)      │
└──────────────────────────────────────────────────────────┘
     ↑ Stop hook: export → QMD index
     ↑ Compound loop: persist → MEMORY.md / CLAUDE.md
     ↓ SessionStart / /recall: load context from QMD
```

## Alternativas evaluadas

### A) Engram (binario Go + SQLite + MCP)
Sistema de memoria agnóstico con scope personal/project, búsqueda FTS5,
y git sync para compartir memorias entre máquinas.

**Evaluado positivamente pero diferido**: Engram es sólido y portable, pero
agrega una dependencia externa (binario Go, SQLite) cuando auto-memory + QMD
ya cubren el caso de uso. Se puede adoptar más adelante si la auto-memory
nativa resulta insuficiente. Ventaja principal: git sync para compartir
memoria entre Mac y homelab.

### B) Mem0 (cloud/self-hosted, vector + graph)
Capa de memoria inteligente con niveles user/session/agent y motor de
actualización automática.

**Descartado**: requiere enviar datos a servers externos o montar infraestructura
self-hosted. Overkill para un solo usuario. La separación user/project
se resuelve más simple con la jerarquía nativa de Claude Code.

### C) Auto-memory nativa + QMD + hooks (elegido)
Combinar lo que Claude Code ya tiene (auto-memory por proyecto) con QMD
como motor de búsqueda del vault, y hooks para automatizar la persistencia.

**Ventajas**:
- Cero dependencias nuevas (QMD ya está instalado como skill)
- Todo local, nada sale de la máquina
- Se alinea con la jerarquía del ADR-002
- Escala naturalmente: más proyectos = más memory dirs automáticos
- LazyMind como fuente de verdad de conocimiento, no duplicada

### D) Solo CLAUDE.md + MEMORY.md manuales
Sin QMD, sin hooks. Solo archivos que el usuario mantiene a mano.

**Descartado**: no escala. Con 50+ sesiones/semana, la memoria se pierde
inevitablemente. Los hooks automatizan lo tedioso.

## Consecuencias

- Se configura QMD MCP server en `~/.claude/settings.json` (Capa 1)
- Se crean colecciones QMD para el vault: articles, projects, dailies, sessions
- Se escribe `claude-session-export.sh` y se agrega como Stop hook global
- Se agregan instrucciones de compound loop al CLAUDE.md de Capa 1
- Se estructura auto-memory por proyecto con MEMORY.md como routing document
- Se crea/adapta skill /recall para buscar contexto previo
- LazyMind se mantiene como fuente unica de conocimiento — no se duplica por perfil
- Engram queda como candidato futuro para sync entre Mac y homelab
- QMD MCP server puede correr remoto en el homelab en el futuro (el vault
  ya se sincroniza via iCloud/git; QMD indexa y expone via MCP sobre la red)
- PRJ-ClaudeCode en LazyMind se depreca (la gobernanza está en lazy-claudecode)

## Implementacion (orden sugerido)

1. **ADR aprobado** → este documento
2. **Configurar QMD**: crear colecciones, indexar vault, agregar MCP server
3. **Escribir claude-session-export.sh**: parser JSONL → markdown + qmd update
4. **Agregar Stop hook** en `~/.claude/settings.json`
5. **Agregar instrucciones de compound loop** al CLAUDE.md de Capa 1
6. **Estructurar auto-memory** de proyectos activos (MEMORY.md + archivos temáticos)
7. **Crear/adaptar skill /recall** con modos temporal, topic, graph
8. **Iterar**: después de 2 semanas, evaluar si la memoria mejora la continuidad.
   Si no, evaluar Engram como siguiente paso.

## Referencias (articulos en LazyMind)

- "Memoria persistente para Agentes" — analisis comparativo Engram/QMD/Mem0/Letta
- "Grep Is Dead: How I Made Claude Code Actually Remember Things" — QMD + /recall
- "Claude + Obsidian: The Memory Stack That Compounds" — arquitectura 3 capas
- "50 Claude Code Tips and Best Practices" — hooks, CLAUDE.md vs hooks (80% vs 100%)
- "Two Powerful Claude Code Plugins: gstack vs CE" — compound engineering loop
