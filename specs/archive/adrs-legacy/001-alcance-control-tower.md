# ADR-001: Alcance y proposito de lazy-control-tower

**Estado**: reemplazado por ADR-011

**Fecha**: 2026-03-28

## Contexto

Tengo un entorno de trabajo distribuido en multiples herramientas (neovim, zellij,
yazi, obsidian, claude, chezmoi, scripts) que corre en multiples OS (macOS, Arch Linux)
y multiples perfiles (personal, work). Las configuraciones ya viven en un repo de
dotfiles gestionado por chezmoi (`~/repos/lazy/dotfiles`). El conocimiento vive en
un vault de Obsidian (LazyMind).

Lo que falta es un lugar para **gobernar** todo esto: decidir que herramientas uso,
por que, como se conectan entre si, y como operar sobre el conjunto.

## Decision

`lazy-control-tower` es el repo de gobernanza. Su responsabilidad es:

1. **Decidir** — ADRs para cada decision sobre herramientas, estructura, configuracion
2. **Inventariar** — registro vivo de que herramientas uso, donde vive cada config, estado
3. **Definir workflows** — procedimientos documentados para tareas recurrentes
4. **Orquestar** — scripts que operan sobre los repos de dotfiles, vault, y herramientas

NO es responsabilidad de este repo:

- Almacenar dotfiles o configuraciones (eso es chezmoi en `~/repos/lazy/dotfiles`)
- Almacenar conocimiento o notas (eso es LazyMind en Obsidian)
- Ejecutar operaciones sin un workflow definido y aprobado previamente

## Alternativas evaluadas

### A) Todo en el repo de chezmoi
Meter ADRs, inventario, y scripts junto con los dotfiles.
**Descartado**: mezcla concerns. Chezmoi es para configuracion declarativa, no para
documentacion de decisiones ni orquestacion.

### B) Todo en Obsidian
Documentar decisiones y workflows como notas en el vault.
**Descartado**: Obsidian es para conocimiento personal y PKM. Las decisiones de
infraestructura necesitan versionado con git, no un vault de notas. Ademas, los
scripts de orquestacion no tienen lugar en Obsidian.

### C) Repo separado de gobernanza (elegido)
Separacion clara: chezmoi para configs, Obsidian para conocimiento, control-tower
para decisiones y orquestacion.
**Ventaja**: cada repo tiene un proposito unico. Se puede clonar el control-tower
en cualquier maquina sin arrastrar configs.

## Consecuencias

- Toda decision sobre herramientas se registra como ADR antes de implementarse
- El inventario se mantiene actualizado cuando se agrega o quita una herramienta
- No se ejecutan cambios masivos sin workflow documentado
- Los scripts de orquestacion referencian repos externos por path, no los contienen
- El conocimiento derivado (aprendizajes, reflexiones) va a LazyMind, no aca