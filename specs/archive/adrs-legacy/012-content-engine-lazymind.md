# ADR-012: Content Engine para LazyMind

**Estado**: pendiente

**Fecha**: 2026-04-05

**Depende de**: ADR-003 (arquitectura de memoria)

## Contexto

LazyMind funciona como second brain pero la ingesta de contenido externo es manual.
Un content engine automatizaría la curación de fuentes relevantes (RSS, GitHub trending, HN)
y escribiría digests filtrados directamente en el vault de Obsidian.

Inspiración: el "Content Engine" de Cole Medin (AI Second Brain), que agrega noticias,
hace triaje automático, y sugiere contenido basado en intereses del usuario.

## Decisión

Pendiente. Evaluar:

1. **Pipeline**: LaunchAgent periódico → Python script que scrapea fuentes → filtra por intereses → escribe digest en vault
2. **Fuentes candidatas**: RSS feeds de AI/infra, GitHub trending, Hacker News, YouTube channels
3. **Filtro**: keywords + scoring por relevancia (Claude Code, infra, AI engineering, homelab)
4. **Output**: nota diaria/semanal en `Meta/Digests/` del vault, indexable por QMD

## Alternativas a evaluar

- **Python puro**: requests + feedparser, filtro por keywords, sin LLM. Barato, pero filtro tosco.
- **Python + LLM local (Ollama)**: scoring de relevancia con modelo local. Mejor filtro, sin costo API.
- **Python + Claude Haiku**: scoring con Haiku para triaje. ~$0.05/run, mejor calidad.

## Tradeoffs

- Scope creep: esto es un proyecto nuevo, no parte del harness. Evaluar si va en lazy-claudecode o repo separado.
- Overlap con QMD: si QMD ya indexa el vault, el engine solo necesita escribir ahí.
- Mantenimiento: fuentes cambian, feeds se rompen. Necesita ser robusto a fallas.

## Próximos pasos

- Spike corto: script mínimo que lea 2-3 RSS feeds y escriba un .md en el vault
- Evaluar si justifica repo propio o módulo dentro de lazy-claudecode
