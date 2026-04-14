# Rename lazy-control-tower → lazy-claudecode — Implementation Plan

> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the repo from lazy-control-tower to lazy-claudecode, update all functional refs, archive historical docs, remove inventory, and create ADR-011.

**Architecture:** In-place rename with find-replace on functional files. Historical docs move to archive untouched. Git rename happens last after all content changes are committed.

**Tech Stack:** Bash, Markdown, Git, GitHub CLI (`gh`)

---

### Task 1: Archive historical specs and plans

**Files:**
- Move: `docs/superpowers/specs/*` → `docs/archive/specs/`
- Move: `docs/superpowers/plans/*` → `docs/archive/plans/`
- Keep: `docs/superpowers/specs/2026-04-03-rename-to-lazy-claudecode.md` (current spec, stays)

- [ ] **Step 1: Create archive directories**

```bash
mkdir -p docs/archive/specs docs/archive/plans
```

- [ ] **Step 2: Move all specs except the rename spec**

```bash
cd /Users/lazynet/repos/lazy/lazy-control-tower
for f in docs/superpowers/specs/*.md; do
  [[ "$(basename "$f")" == "2026-04-03-rename-to-lazy-claudecode.md" ]] && continue
  git mv "$f" docs/archive/specs/
done
```

- [ ] **Step 3: Move all plans except this plan**

```bash
for f in docs/superpowers/plans/*.md; do
  [[ "$(basename "$f")" == "2026-04-03-rename-to-lazy-claudecode.md" ]] && continue
  git mv "$f" docs/archive/plans/
done
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: archive historical specs and plans to docs/archive/"
```

---

### Task 2: Remove inventory

**Files:**
- Delete: `inventory/` (entire directory)

- [ ] **Step 1: Remove inventory directory**

```bash
git rm -r inventory/
```

- [ ] **Step 2: Commit**

```bash
git commit -m "refactor: remove inventory/ (no consumers, out of scope)"
```

---

### Task 3: Create ADR-011

**Files:**
- Create: `adrs/011-rename-to-lazy-claudecode.md`
- Modify: `adrs/001-alcance-control-tower.md:1` (status → superseded)
- Modify: `adrs/README.md:20-21` (update ADR-001 status, add ADR-011 row)

- [ ] **Step 1: Create ADR-011**

Create `adrs/011-rename-to-lazy-claudecode.md`:

```markdown
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
```

- [ ] **Step 2: Update ADR-001 status**

In `adrs/001-alcance-control-tower.md`, change line 3:

```
**Estado**: aceptado
```
→
```
**Estado**: reemplazado por ADR-011
```

- [ ] **Step 3: Update ADR README**

In `adrs/README.md`, change line 20:

```
| [001](001-alcance-control-tower.md) | Alcance y proposito de lazy-control-tower | aceptado |
```
→
```
| [001](001-alcance-control-tower.md) | Alcance y proposito de lazy-control-tower | reemplazado por ADR-011 |
```

Add new row after line 29 (after ADR-010):

```
| [011](011-rename-to-lazy-claudecode.md) | Rename a lazy-claudecode y redefinicion de alcance | aceptado |
```

- [ ] **Step 4: Commit**

```bash
git add adrs/
git commit -m "feat: ADR-011 rename to lazy-claudecode, supersede ADR-001"
```

---

### Task 4: Update functional refs — scripts

**Files:**
- Modify: `scripts/deploy.sh:149` — echo message
- Modify: `scripts/_env.sh:2` — comment
- Modify: `scripts/qmd/qmd-context-gen.sh:34,45-46` — collection name + path

- [ ] **Step 1: Update deploy.sh**

Line 149, change:

```bash
echo "=== lazy-control-tower deploy ==="
```
→
```bash
echo "=== lazy-claudecode deploy ==="
```

- [ ] **Step 2: Update _env.sh**

Line 2, change:

```bash
# _env.sh — Shared environment for lazy-control-tower scripts
```
→
```bash
# _env.sh — Shared environment for lazy-claudecode scripts
```

- [ ] **Step 3: Update qmd-context-gen.sh**

Line 34, change:

```python
    "lazy-control-tower": "Repo de gobernanza del entorno de desarrollo. ADRs, inventario, workflows y scripts.",
```
→
```python
    "lazy-claudecode": "Harness engineering system para Claude Code. ADRs, profiles, hooks, skills, memory pipeline y monitoring.",
```

Lines 45-46, change:

```python
    "lazy-control-tower": os.path.expanduser(
        "~/repos/lazy/lazy-control-tower"
```
→
```python
    "lazy-claudecode": os.path.expanduser(
        "~/repos/lazy/lazy-claudecode"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy.sh scripts/_env.sh scripts/qmd/qmd-context-gen.sh
git commit -m "refactor: update script refs to lazy-claudecode"
```

---

### Task 5: Update functional refs — profiles and routers

**Files:**
- Modify: `profiles/lazy/CLAUDE.md:77` — conditional ref
- Modify: `profiles/lazy/docs/repos.md:7,18,27` — tree, convention, table
- Modify: `profiles/lazy/docs/governance.md` — full rewrite (title, structure, ADR list)
- Modify: `workspace-routers/lazy-claude.md:8` — conditional ref

- [ ] **Step 1: Update profiles/lazy/CLAUDE.md**

Line 77, change:

```
- Si trabajás en lazy-control-tower → leé `docs/governance.md`
```
→
```
- Si trabajás en lazy-claudecode → leé `docs/governance.md`
```

- [ ] **Step 2: Update profiles/lazy/docs/repos.md**

Line 7, change:

```
├── lazy-control-tower/  # gobernanza: ADRs, inventario, workflows
```
→
```
├── lazy-claudecode/     # harness engineering: profiles, hooks, skills, monitoring
```

Line 18, change:

```
- Decisiones de infraestructura se documentan como ADR en `lazy-control-tower/`.
```
→
```
- Decisiones de Claude Code se documentan como ADR en `lazy-claudecode/`.
```

Line 27, change:

```
| lazy-control-tower | github.com/lazynet/lazy-control-tower | — |
```
→
```
| lazy-claudecode | github.com/lazynet/lazy-claudecode | — |
```

- [ ] **Step 3: Rewrite profiles/lazy/docs/governance.md**

Replace full content with:

```markdown
# Governance — lazy-claudecode

## Qué es

Harness engineering system para Claude Code. Contiene profiles, hooks, skills,
memory pipeline, CLI tools y monitoring.

## Estructura

```
adrs/              — Architecture Decision Records
config/            — Configs de herramientas (profiles.example)
docs/              — Specs activos + archive histórico
launchd/           — LaunchAgents del harness (macOS)
profiles/          — CLAUDE.md y settings.json por perfil (lazy, flex)
scripts/           — CLI tools, hooks, monitoring, QMD
skills/            — Skills de Claude Code
workflows/         — Procedimientos operacionales
workspace-routers/ — CLAUDE.md livianos por workspace
```

## Cómo hacer cambios

- Decisiones importantes: crear ADR en `adrs/` antes de implementar.
- Scripts nuevos: agregar en `scripts/`, deploy con `./scripts/deploy.sh scripts`.
- Profiles: editar en `profiles/`, deploy con `./scripts/deploy.sh profiles`.
- LaunchAgents: agregar en `launchd/`, deploy con `./scripts/deploy.sh launchd`.

## ADRs vigentes

- ADR-001: Alcance original (supersedido por ADR-011)
- ADR-002: Setup multi-cuenta — supersedido por ADR-009
- ADR-003: Arquitectura de memoria
- ADR-004: CLAUDE.md como router con progressive disclosure
- ADR-005: Compound loop enforcement vía Stop hook
- ADR-006: Episodic memory con JSONL append-only
- ADR-007: Cross-project learning memory
- ADR-008: SessionStart hook para inyección de contexto
- ADR-009: Profile isolation via CLAUDE_CONFIG_DIR
- ADR-010: Integración de Ollama (propuesto)
- ADR-011: Rename a lazy-claudecode y redefinición de alcance
```

- [ ] **Step 4: Update workspace-routers/lazy-claude.md**

Line 8, change:

```
- Si trabajás en lazy-control-tower → leé `docs/governance.md`
```
→
```
- Si trabajás en lazy-claudecode → leé `docs/governance.md`
```

- [ ] **Step 5: Commit**

```bash
git add profiles/ workspace-routers/
git commit -m "refactor: update profile and router refs to lazy-claudecode"
```

---

### Task 6: Update functional refs — skills and workflows

**Files:**
- Modify: `skills/recall-cowork/SKILL.md:64,74` — QMD collection name
- Modify: `profiles/lazy/commands/recall.md:37` — QMD collection name
- Modify: `workflows/qmd-collections.md:19,47` — collection name and script refs

- [ ] **Step 1: Update skills/recall-cowork/SKILL.md**

Line 64, change:

```
El path aparece en los resultados de búsqueda (ej: `qmd://lazy-control-tower/adrs/003-arquitectura-memoria-claude.md`). Usar la parte después del `://collection/`.
```
→
```
El path aparece en los resultados de búsqueda (ej: `qmd://lazy-claudecode/adrs/003-arquitectura-memoria-claude.md`). Usar la parte después del `://collection/`.
```

Line 74, change:

```
| `lazy-control-tower` | ADRs, workflows, inventario de gobernanza |
```
→
```
| `lazy-claudecode` | ADRs, hooks, skills, profiles del harness |
```

- [ ] **Step 2: Update profiles/lazy/commands/recall.md**

Line 37, change:

```
| `lazy-control-tower` | ADRs, workflows, inventario |
```
→
```
| `lazy-claudecode` | ADRs, hooks, skills, profiles del harness |
```

- [ ] **Step 3: Update workflows/qmd-collections.md**

Line 19, change:

```
| `lazy-control-tower` | Repo | ADRs, workflows, inventario |
```
→
```
| `lazy-claudecode` | Repo | ADRs, hooks, skills, profiles del harness |
```

Line 47, change:

```
- Script fuente: `control-tower/scripts/claude-session-export.sh`
```
→
```
- Script fuente: `lazy-claudecode/scripts/hooks/claude-session-export.sh`
```

- [ ] **Step 4: Commit**

```bash
git add skills/ profiles/lazy/commands/ workflows/
git commit -m "refactor: update skill, command, and workflow refs to lazy-claudecode"
```

---

### Task 7: Update active ADR refs

**Files:**
- Modify: `adrs/004-claude-md-router-progressive-disclosure.md:82`
- Modify: `adrs/006-episodic-memory-jsonl.md:60,75`

- [ ] **Step 1: Update ADR-004**

Line 82, change:

```
- Si trabajás en lazy-control-tower: leé `docs/governance.md`
```
→
```
- Si trabajás en lazy-claudecode: leé `docs/governance.md`
```

- [ ] **Step 2: Update ADR-006**

Line 60, change:

```json
  "project": "lazy-control-tower",
```
→
```json
  "project": "lazy-claudecode",
```

Line 75, change:

```json
  "project": "lazy-control-tower",
```
→
```json
  "project": "lazy-claudecode",
```

- [ ] **Step 3: Commit**

```bash
git add adrs/
git commit -m "refactor: update active ADR refs to lazy-claudecode"
```

---

### Task 8: Update root CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` — full rewrite to reflect new identity

- [ ] **Step 1: Rewrite CLAUDE.md**

Replace full content with:

```markdown
# lazy-claudecode

Harness engineering system para el setup de Claude Code de lazynet.
Profiles, hooks, skills, memory pipeline, CLI tools y monitoring.

## Estructura

```
adrs/              — Architecture Decision Records
config/            — Configs de herramientas (profiles.example para lcc)
docs/              — Specs activos + docs/archive/ para históricos
launchd/           — LaunchAgents del harness (macOS)
profiles/          — CLAUDE.md y settings.json por perfil → ~/.claude-<name>/
workspace-routers/ — CLAUDE.md livianos para ~/repos/{lazy,flex}/.claude/
scripts/           — Scripts de automatización (se despliegan vía symlink)
skills/            — Skills para Claude Code (symlinks a ~/.claude-<name>/skills/)
workflows/         — Procedimientos operacionales
```

## Convenciones de este repo

- Toda decisión importante se documenta como ADR antes de implementar.
- Los scripts son la fuente única de verdad — se despliegan a `~/.local/bin/` con `./scripts/deploy.sh`.
- Los profiles se despliegan a `~/.claude-{lazy,flex}/` como symlinks (via CLAUDE_CONFIG_DIR).
- No mezclar concerns: configs en chezmoi, conocimiento en LazyMind, harness acá.

## Deploy

```bash
./scripts/deploy.sh           # todo: scripts + launchd + profiles + routers
./scripts/deploy.sh scripts   # solo scripts → ~/.local/bin/
./scripts/deploy.sh launchd   # solo LaunchAgents (macOS)
./scripts/deploy.sh profiles  # solo CLAUDE.md/settings.json → ~/.claude-<name>/
./scripts/deploy.sh routers   # solo workspace routers → ~/repos/<name>/.claude/
```

## Workspace routers

Los routers en `workspace-routers/` son CLAUDE.md livianos que se despliegan a `~/repos/{lazy,flex}/.claude/CLAUDE.md`. Su función es cargar el contexto condicional (`docs/`) según el repo donde se trabaja, sin repetir las reglas universales del perfil.

Mapeo: `lazy-claude.md` → `~/repos/lazy/.claude/CLAUDE.md`, `flex-claude.md` → `~/repos/flex/.claude/CLAUDE.md`.

## Crear un nuevo perfil

1. `lcc-admin init` (si es la primera vez) o editar `~/.config/lcc/profiles`
2. Crear directorio del perfil: `profiles/<nombre>/` con `CLAUDE.md`, `settings.json`, `docs/`
3. `deploy.sh profiles` para crear symlinks a `~/.claude-<nombre>/`
4. `CLAUDE_CONFIG_DIR=~/.claude-<nombre> claude auth login` para autenticar

## ADRs vigentes

- ADR-001: Alcance original — supersedido por ADR-011
- ADR-002: Setup multi-cuenta Claude Code — supersedido por ADR-009
- ADR-003: Arquitectura de memoria para Claude Code
- ADR-004: CLAUDE.md como router con progressive disclosure
- ADR-005: Compound loop enforcement vía Stop hook
- ADR-006: Episodic memory con JSONL append-only
- ADR-007: Cross-project learning memory
- ADR-008: SessionStart hook para inyección de contexto
- ADR-009: Profile isolation via CLAUDE_CONFIG_DIR (supersede ADR-002)
- ADR-010: Integración de Ollama para tareas locales y evaluación multi-modelo
- ADR-011: Rename a lazy-claudecode y redefinición de alcance

## Git workflow

Trunk-based development con worktrees para aislamiento cuando hace falta.

**Commits directos a main** (default):
- Cambios chicos: fixes, actualizaciones de docs, ajustes de config
- Un commit por unidad lógica de cambio. No acumular cambios sin commitear.
- Formato: `tipo: descripción corta` (conventional commits)
- Push después de cada commit o grupo de commits relacionados

**Worktrees para aislamiento** (cuando el cambio lo justifica):
- Features multi-archivo que pueden romper algo mientras se desarrollan
- Refactors que tocan muchos scripts a la vez
- Crear con: `git worktree add ../lcc-<branch> -b <branch>`
- Merge a main cuando esté listo. Borrar worktree después.

**Al cerrar sesión**: commitear y pushear todo el trabajo pendiente. No dejar cambios sin commitear entre sesiones.

## Al trabajar en este repo

- Si modificás un script, corré `deploy.sh scripts` para verificar que el symlink sigue funcionando.
- Si modificás un profile, corré `deploy.sh profiles`.
- Si una decisión cambia, actualizá o deprecá el ADR correspondiente — no editar silenciosamente.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "refactor: rewrite CLAUDE.md for lazy-claudecode identity"
```

---

### Task 9: Git rename — directory and GitHub repo

**Precondition:** All content changes are committed. Working tree is clean.

- [ ] **Step 1: Rename local directory**

```bash
cd /Users/lazynet/repos/lazy
mv lazy-control-tower lazy-claudecode
cd lazy-claudecode
```

- [ ] **Step 2: Push all commits**

```bash
git push
```

- [ ] **Step 3: Rename repo on GitHub**

```bash
gh repo rename lazy-claudecode
```

- [ ] **Step 4: Update git remote (GitHub redirects, but clean is better)**

```bash
git remote set-url origin git@github.com:lazynet/lazy-claudecode.git
```

- [ ] **Step 5: Verify**

```bash
git remote -v
git status
```

---

### Task 10: Post-rename — QMD and memory migration

- [ ] **Step 1: Regenerate QMD index**

```bash
qmd-context-gen.sh
```

This will regenerate `~/.config/qmd/index.yml` with the new collection name and path.

- [ ] **Step 2: Reindex QMD collection**

```bash
qmd reindex --collection lazy-claudecode
```

- [ ] **Step 3: Copy auto-memory to new project path**

```bash
OLD_MEM="$HOME/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-control-tower/memory"
NEW_MEM="$HOME/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory"
mkdir -p "$NEW_MEM"
cp -a "$OLD_MEM"/* "$NEW_MEM"/
```

- [ ] **Step 4: Update external ref in lazy-ai-tools**

```bash
cd /Users/lazynet/repos/lazy/lazy-ai-tools
grep -r "lazy-control-tower" README.md
```

If found, replace `lazy-control-tower` → `lazy-claudecode` and commit.

- [ ] **Step 5: Run deploy to verify symlinks**

```bash
cd /Users/lazynet/repos/lazy/lazy-claudecode
./scripts/deploy.sh
```

Verify all symlinks point to the new path.

- [ ] **Step 6: Verify recall skill finds the new collection**

```bash
qmd search "ADR" --collection lazy-claudecode
```

Expected: results from the renamed collection.
