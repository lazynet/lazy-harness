# ADR-013: Niveles de proactividad por perfil

**Estado**: pendiente

**Fecha**: 2026-04-05

**Depende de**: ADR-009 (profile isolation), ADR-008 (SessionStart hook)

## Contexto

Hoy ambos perfiles (lazy/flex) tienen el mismo nivel de autonomía del agente.
En la práctica, el contexto personal (lazy) tolera más acción autónoma que el
laboral (flex), donde hay equipo, CI/CD, y procesos de review.

Inspiración: el sistema de proactividad de Cole Medin (AI Second Brain) con 4 niveles
configurables: Observer, Advisor, Assistant, Partner.

## Decisión

Pendiente. Evaluar implementar niveles de proactividad como config por perfil.

### Niveles propuestos

| Nivel | Comportamiento | Profile natural |
|-------|---------------|-----------------|
| **Observer** | Solo notifica. No sugiere acciones. | — |
| **Advisor** | Sugiere + prepara borradores. No ejecuta. | flex |
| **Assistant** | Auto-organiza tareas internas. Pregunta antes de acciones externas. | lazy |
| **Partner** | Actúa en low-risk solo. Escala solo high-risk. | lazy (futuro) |

### Mecanismo de implementación

Opción A: campo en `settings.json`
```json
{ "proactivity": "assistant" }
```

Opción B: sección en CLAUDE.md del perfil con instrucciones de comportamiento.

El SessionStart hook leería la config y la traduciría a instrucciones específicas
inyectadas como `additionalContext`.

## Alternativas

- **No hacer nada**: el CLAUDE.md del perfil ya tiene instrucciones implícitas de comportamiento. Funciona, pero no es explícito ni configurable.
- **Solo dos niveles** (conservative/autonomous): más simple, cubre el 80% del caso lazy vs flex.
- **Cuatro niveles completos**: más granular, pero puede ser overengineering para dos perfiles.

## Tradeoffs

- Complejidad: agregar un nivel de indirección para algo que hoy se resuelve con prosa en CLAUDE.md.
- Valor: la diferencia real entre lazy y flex ya está en las instrucciones. Formalizar ayuda si hay más perfiles.
- Riesgo: nivel Partner en flex podría causar acciones no deseadas en repos de equipo.

## Próximos pasos

- Definir qué acciones concretas cambian por nivel (lista exhaustiva)
- Implementar como spike en lazy profile primero
- Evaluar si la granularidad de 4 niveles se justifica o alcanza con 2
