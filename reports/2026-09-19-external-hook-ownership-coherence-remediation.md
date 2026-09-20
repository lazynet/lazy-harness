# Remediación de coherencia — external hook ownership F1

Fecha: 2026-09-19
Fuente: `reports/2026-09-19-external-hook-ownership-coherence-audit.md`
Resultado: **DONE**

## Alcance

Esta remediación corrige únicamente F1. Los findings F2–F9 del audit quedan sin
cambios.

## Cambios

- `specs/adrs/031-default-hooks-merge.md` agrega una evolución fechada
  2026-09-19. Conserva el merge de defaults y las decisiones originales como
  historia, pero reemplaza su vigencia semántica: el bloque nativo completo ya
  no es propiedad del framework. Cada adapter reconoce las entries de builtins
  que pertenecen al harness, reconcilia sólo esas y preserva entries externas o
  foreign.
- La misma evolución enlaza ADR-054 y explicita el lifecycle ensure-present de
  hooks externos declarados. Omitir una declaración deja de asegurar presencia,
  pero no transfiere ownership ni autoriza borrado.
- `specs/backlog.md` corrige sólo la entrada Done de `lh deploy` default hooks
  merge. Mantiene el cierre histórico del incidente, el override por evento y
  el fix de `post_compact`, y actualiza la descripción de defaults, ownership de
  builtins y externos ensure-present.

## Verificación

- `git diff --check`: exit 0, sin output.
- `uv run --frozen --group docs mkdocs build --strict`: exit 0;
  documentación construida en 0.78 segundos. Material for MkDocs emitió sólo su
  aviso upstream sobre MkDocs 2.0; no hubo errores ni warnings de contenido,
  links o navegación.

No se modificó código ni tests, no se abrió ningún subagente y no se creó ningún
commit.
