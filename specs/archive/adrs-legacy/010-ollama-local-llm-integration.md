# ADR-010: Integración de Ollama para tareas locales y evaluación multi-modelo

**Estado**: propuesto

**Fecha**: 2026-04-02

## Contexto

El compound loop (ADR-005) usa `claude -p --model claude-haiku-4-5` para evaluar
sesiones de forma async. Funciona bien, pero tiene limitaciones:

1. **Costo acumulativo**: ~$0.001/sesión × ~30 sesiones/día × 365 = ~$11/año solo en
   evaluación. Bajo en absoluto, pero es dinero gastado en una tarea que un modelo
   local podría resolver.

2. **Rate limits**: Haiku tiene rate limits que en picos de actividad (muchas sesiones
   cortas) pueden causar throttling del worker.

3. **Dependencia de red**: si no hay conexión, el compound loop falla silenciosamente.
   En modo avión o con internet inestable, se pierden evaluaciones.

4. **Sin benchmark de calidad**: no hay forma de comparar si Haiku es el modelo óptimo
   para esta tarea. Otros modelos (locales o API) podrían dar resultados equivalentes
   o mejores para el tipo de evaluación que hace el worker.

### Contexto técnico

Ollama está instalado en `/usr/local/bin/ollama` y se usa activamente desde
raycast-ollama (chat UI casual). No está integrado en el pipeline de gobernanza
de Claude Code.

Las tareas candidatas a modelo local son:

- **Evaluación de sesiones** (compound-loop-worker): extraer decisions, failures,
  y learnings de un resumen de sesión. Requiere seguir un schema JSON.
- **Deduplicación semántica**: comparar un learning nuevo contra los existentes
  para detectar duplicados. Hoy se hace por inyección de títulos en el prompt.
- **Embeddings locales**: nomic-embed-text para vectorización sin API externa.
  QMD ya soporta embeddings locales.
- **Clasificación/triage de learnings**: categorizar learnings por scope, urgencia,
  o relevancia sin consumir API.

## Decisión

**Integrar Ollama como backend alternativo para el compound-loop-worker, con
framework de evaluación multi-modelo para comparar resultados.**

### Arquitectura

```
compound-loop-worker (Python)
    │
    ├── --backend=api (default, actual)
    │   └── claude -p --model haiku
    │
    ├── --backend=ollama
    │   └── ollama run <model> (local)
    │
    └── --backend=eval
        ├── Corre contra TODOS los backends configurados
        ├── Misma sesión, mismo prompt
        └── Output comparativo en eval-results/
```

### Backend API (Ollama)

El worker llamará a Ollama via HTTP API (`http://localhost:11434/api/generate`)
en vez de `claude -p`. Esto permite:

- Cambiar modelo sin cambiar código (`--model qwen2.5:7b`)
- Timeout configurable (modelos locales son más lentos)
- Fallback a API si Ollama no está corriendo

### Evaluación multi-modelo

Un modo `--backend=eval` que:

1. Toma una sesión real (o un set de sesiones de referencia)
2. Corre el mismo prompt contra cada backend configurado
3. Guarda los resultados lado a lado en `eval-results/YYYY-MM-DD/`
4. Formato: un archivo por modelo con el JSON output + metadata (tiempo, tokens)

Esto permite responder: "para MIS sesiones y MIS prompts, qué modelo da mejores
resultados en extracción de decisions/failures/learnings?"

### Criterios de evaluación

Para comparar modelos, evaluar:

- **Schema compliance**: el output es JSON válido que sigue el schema?
- **Precision**: las decisiones/failures extraídas son reales o alucinadas?
- **Recall**: se perdieron decisiones/failures importantes?
- **Dedup quality**: evita generar learnings duplicados?
- **Latencia**: tiempo total de inferencia
- **Costo**: $0 local vs ~$0.001 API

### Modelos candidatos para evaluación

| Modelo | Params | Fortaleza esperada | Riesgo |
|--------|--------|-------------------|--------|
| Haiku 4.5 (baseline) | API | Schema compliance probado | Costo, red |
| Qwen 2.5 7B | 7B | Buen structured output, rápido | Recall en sesiones complejas |
| Llama 3.1 8B | 8B | General purpose, amplio contexto | JSON parsing inconsistente |
| Phi-3 Mini | 3.8B | Ultra-rápido, bueno en clasificación | Puede fallar en extracción larga |
| DeepSeek-R1 8B | 8B | Reasoning fuerte | Lento, verbose |
| Gemma 2 9B | 9B | Instruction following | No probado en structured output |

### Configuración

Archivo `config/llm-backends.yml`:

```yaml
backends:
  api-haiku:
    type: api
    command: "claude -p --model claude-haiku-4-5-20251001"
    timeout: 30

  ollama-qwen:
    type: ollama
    model: "qwen2.5:7b"
    url: "http://localhost:11434"
    timeout: 120

  ollama-llama:
    type: ollama
    model: "llama3.1:8b"
    url: "http://localhost:11434"
    timeout: 120

default: api-haiku

eval_set:
  - ollama-qwen
  - ollama-llama
  - api-haiku
```

### Embeddings locales

Para deduplicación semántica de learnings, usar `nomic-embed-text` via Ollama:

```bash
ollama pull nomic-embed-text
```

Esto permite calcular similitud coseno entre un learning nuevo y los existentes
sin depender de API externa. Integrable como paso pre-evaluación en el worker.

## Alternativas evaluadas

### A) Migrar todo a Ollama — descartado

Reemplazar Haiku por un modelo local sin comparación previa.

**Descartado**: sin benchmark no sabemos si la calidad es aceptable para nuestro
use case específico. El structured output de modelos 7-8B es inconsistente según
el prompt.

### B) Usar Ollama solo para embeddings — demasiado conservador

Limitar Ollama a embeddings (nomic-embed-text) y mantener Haiku para todo lo demás.

**Descartado como scope completo**: es un buen primer paso, pero no aprovecha el
potencial de evaluación multi-modelo. Se incluye como parte de la solución.

### C) Framework de eval + backend configurable (elegido)

Backend configurable con modo de evaluación comparativa. Permite empezar con Haiku
(probado), evaluar alternativas con datos reales, y migrar con evidencia.

### D) OpenAI-compatible API genérica — considerado para futuro

Usar la API compatible de Ollama (`/v1/chat/completions`) para abstraer el backend.
Permitiría agregar otros providers (Groq, Together, local vLLM) con el mismo código.

**No descartado**: se puede implementar después si hay necesidad de más providers.
Por ahora Ollama HTTP API directo es más simple.

## Consecuencias

- **compound-loop-worker** se extiende con flag `--backend` y soporte para Ollama HTTP API
- **config/llm-backends.yml** nuevo archivo de configuración de backends
- **eval-results/** nuevo directorio para resultados de evaluación comparativa
- **Ollama debe estar corriendo** para usar backend local. El worker debe manejar
  el caso de Ollama no disponible (fallback a API o skip con warning)
- **inventory/claude-code.md** se actualiza con Ollama como dependencia opcional
- **No se cambia el default**: Haiku sigue siendo el backend por defecto hasta que
  la evaluación demuestre que un modelo local es equivalente o mejor
- **Embeddings locales** se pueden integrar independientemente del cambio de backend

## Plan de implementación

1. Agregar Ollama al inventory y documentación
2. Crear `config/llm-backends.yml` con backends iniciales
3. Extender compound-loop-worker con `--backend` flag
4. Implementar cliente Ollama HTTP en el worker
5. Implementar modo `--backend=eval` con output comparativo
6. Correr eval con 20+ sesiones reales y documentar resultados
7. Si un modelo local es aceptable, cambiar el default
8. Integrar nomic-embed-text para dedup semántico
