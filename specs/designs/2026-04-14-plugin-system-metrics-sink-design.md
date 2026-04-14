# lazy-harness — Plugin system + team mode (vertical slice: metrics_sink)

## Context

Hoy `lazy-harness` asume un único usuario en una única máquina. Métricas y exports se guardan local (SQLite, filesystem), y dependencias como QMD están hardcodeadas (`knowledge/qmd.py`, `monitoring/db.py` son implementaciones concretas, no interfaces).

Martin necesita pasar a **modo equipo**: que varios devs instalen `lh`, cada uno loggee local, pero que exports/métricas converjan a un backend compartido para ver actividad agregada del equipo. A futuro (fuera de scope de este spec) eso mismo debe escalar a multi-tenant (varias compañías, cada una con su backend y plugins).

El problema de fondo no es solo "agregar un sink remoto": es que el harness no tiene un modelo de extensión. Se necesitan **extension points bien definidos** para que el sink remoto sea *un plugin*, no un caso especial cableado al core. Cinco extension points están identificados (`knowledge`, `metrics_sink`, `session_export`, `agent`, `hooks`), pero este spec ataca **solo uno end-to-end** (`metrics_sink`) como vertical slice para validar el patrón antes de replicarlo.

Outcome esperado al terminar este spec:
1. Existe un plugin system híbrido (built-in registry + entry points) con contratos estables.
2. `metrics_sink` es un plugin de primera clase con al menos dos implementaciones reales (`sqlite_local`, `http_remote`) y una composición multi-sink.
3. Cada evento de métricas lleva identidad (`user_id` = GitHub handle) y se puede rutear al backend compartido sin bloquear hooks.
4. El patrón queda documentado y testeado para replicarse después en los otros 4 extension points.

## Decisiones de diseño

| # | Decisión | Razón |
|---|---|---|
| D1 | Target inmediato es modo equipo (varios devs → backend compartido), con contratos pensados para no cerrar la puerta a multi-tenant | El dolor real hoy es el equipo; multi-tenant es futuro |
| D2 | Identidad = GitHub handle leído del entorno local (`gh` / `git config`), declarada en el profile | Estable, portable, cero infra, upgradeable a OAuth sin romper el modelo de datos |
| D3 | Plugin model **híbrido**: built-in registry para plugins oficiales, entry points de Python para plugins externos | Happy path simple y type-safe, con puerta de escape para terceros sin forkear |
| D4 | Los contratos (Protocols) viven en un módulo estable y chico, separado de implementaciones | El contrato es API pública y cambia con semver; las implementaciones se mueven libres |
| D5 | Conflicto de nombres: built-in gana, entry points deben registrar con prefijo `ext:` | Evita que un plugin externo pise un built-in silenciosamente |
| D6 | Vertical slice: este spec implementa `metrics_sink` completo. Los otros 4 extension points quedan para iteraciones posteriores | Validar el patrón con el caso más importante antes de replicarlo a ciegas |
| D7 | Resiliencia del sink: **buffer local + retry async**. El evento se persiste inmediato en SQLite local, un worker background lo empuja al sink remoto, reintenta con backoff si falla | Un hook no puede bloquear en red; el harness tiene que sentirse instantáneo |
| D8 | Un profile puede declarar **múltiples sinks en paralelo** (ej. `sqlite_local` + `http_remote`) | El buffer local no es un fallback, es siempre source of truth; el sink remoto es un mirror opcional |
| D9 | Los eventos existentes en SQLite se migran con `user_id` / `tenant_id` default (`local`, `local`) | Agregar columnas ahora es barato; hacerlo después obliga a migración forzada |
| D10 | **Default = 100% local, invariante no negociable.** Ausencia de config de sinks equivale a `sinks = ["sqlite_local"]`. Nunca implícito por entorno, nunca por paquete instalado | Modo local puro es el estado por default y tiene que ser imposible activar un remoto por accidente |
| D11 | **Opt-in doble:** activar un sink remoto requiere *nombrarlo* en `metrics.sinks` **y** declarar su bloque de config. Nombrado sin config → error al startup. Config sin nombrar → ignorada | Elimina ambigüedad; una sola fuente de verdad (el profile) decide qué corre |
| D12 | **Discovery ≠ activation.** Entry points descubiertos aparecen como "available" pero jamás se activan sin estar nombrados en el profile. Instalar un paquete nunca puede activar un sink | Previene que un `pip install` accidental mande datos a URLs no auditadas |
| D13 | **Visibilidad obligatoria.** Cualquier comando que mueva métricas imprime en stderr la lista de sinks activos + identidad. `lh doctor` tiene sección "network egress" con todas las URLs a las que el profile puede mandar datos | Un sink remoto activo no puede ser invisible; el peor bug es el plugin que exfiltra en silencio |
| D14 | **Sin kill switch global.** No hay `LH_OFFLINE` ni modo avión. Si querés local-only, usás un profile local-only. El profile es la única fuente de verdad | Una sola fuente de verdad > dos ejes de config que pueden confundirse |
| D15 | **Drain opportunistic-only.** El worker corre dentro del proceso `lh` en cada invocación (hooks + CLI). Sin daemon, sin launchd/systemd, sin cron. Forzable con `lh metrics drain` | Mantiene la filosofía del harness (corre durante hooks, no persistente). Cero lifecycle nuevo. Reversible si duele |
| D16 | **Idempotencia fuerte por `event_id` ULID** generado en creación (no en envío). El backend remoto aplica upsert-by-id | Sin esto, cualquier retry duplica filas; es la garantía que hace seguro el modelo offline-first |
| D17 | **Claim con lease** (`sink_status=sending`, `lease_until=now+60s`) para evitar que dos `lh` en paralelo manden el mismo batch. Procesos muertos dejan el lease vencer y otro reclama | Concurrencia limpia sin locks globales |
| D18 | **Backoff exponencial con reset por éxito** (1s → 5min max). Cualquier drain exitoso resetea el contador | Elimina la necesidad de detectar network change cross-platform; el primer hook después de reconectar reintenta y arranca el drain normal |
| D19 | **Sin TTL por default.** Los eventos `pending` nunca expiran. Config opcional `pending_ttl_days` en el profile para quien quiera limpiar | Purista y alineado con modo equipo: si estás 3 meses offline, a los 3 meses drenan |

## Arquitectura

### Módulos nuevos

```
src/lazy_harness/plugins/
├── __init__.py
├── contracts.py        # Protocols: MetricsSink, (stubs para los otros 4)
├── registry.py         # Descubrimiento built-in + entry points, resolución por nombre
└── errors.py           # PluginNotFound, PluginConflict, PluginContractError

src/lazy_harness/monitoring/sinks/
├── __init__.py
├── base.py             # Helpers compartidos (event serialization, retry policy)
├── sqlite_local.py     # Built-in: el actual monitoring/db.py adaptado al Protocol
├── http_remote.py      # Built-in: POST JSON con buffer drain async
└── worker.py           # Background drainer: lee de buffer local, empuja a sinks remotos
```

### Módulos modificados

- `src/lazy_harness/monitoring/db.py` — pasa a ser *solo* el storage del buffer local; deja de ser el único "sink" y se mueve detrás del Protocol. La tabla gana columnas `user_id`, `tenant_id`, `sink_status` (pending/sent/failed).
- `src/lazy_harness/monitoring/ingest.py` — en lugar de escribir a SQLite directo, resuelve los sinks configurados desde el profile y los llama vía el contrato.
- `src/lazy_harness/core/profiles.py` — agrega campos `user_id`, `tenant_id` (opcional, default `local`), y `metrics_sinks: list[SinkConfig]`.
- `src/lazy_harness/core/config.py` — parser del nuevo bloque de config para sinks.
- `src/lazy_harness/cli/` — comando nuevo `lh metrics drain` para forzar flush del buffer manualmente (útil para tests, debugging y para cerrar sesiones limpias).

### Contratos

`plugins/contracts.py` define `MetricsSink` como Protocol con:

- `name: ClassVar[str]` — identificador único, usado en el registry.
- `write(event: MetricEvent) -> SinkWriteResult` — síncrono, rápido. `sqlite_local` escribe al buffer; `http_remote` encola para el worker y retorna immediato.
- `drain(batch_size: int) -> DrainResult` — opcional (default no-op), usado por el worker para sinks que acumulan.
- `health() -> SinkHealth` — para diagnóstico y para decidir si vale la pena intentar drain ahora.

`MetricEvent` es un dataclass frozen con los campos que hoy guarda `monitoring/db.py` + `user_id` + `tenant_id` + `schema_version`. `schema_version` es clave: los plugins externos pueden rechazar eventos de una versión futura.

### Flujo de datos

```
hook event
   │
   ▼
ingest.record(event)
   │
   ├──► sink("sqlite_local").write()    ← síncrono, siempre, source of truth
   │
   └──► sink("http_remote").write()     ← síncrono pero no-bloqueante: encola en memoria
                │
                ▼
        worker drainer (background)
                │
                ├──► lee del buffer local (sqlite_local) los eventos `sink_status=pending`
                ├──► los manda al backend HTTP en batch
                ├──► marca `sent` o reintenta con backoff exponencial
                └──► si falla N veces, marca `failed` y emite warning (no crashea hooks)
```

Clave: el buffer local **es** `sqlite_local`. No hay buffer separado. Eso simplifica el modelo y garantiza que si el remoto está caído durante un mes, los datos siguen ahí cuando vuelva.

### Offline / reconnect (operativa del drain)

El modelo offline-first cae casi natural de las decisiones anteriores, pero hay que ser explícito sobre el lifecycle del drain:

- **Qué dispara el worker.** Cada invocación de `lh` (hook o CLI) ejecuta un paso de drain best-effort *después* de haber escrito el evento a los sinks locales. El paso de drain es corto (un batch), no bloqueante para el caller desde la óptica funcional (el evento ya está persistido), y si falla no propaga errores. Además existe `lh metrics drain` para forzar un drain completo manual.
- **No hay daemon.** El harness no corre como proceso persistente. Si el usuario abre la laptop en la oficina, hace tareas que no usan Claude Code, y la cierra, los eventos siguen `pending` hasta que: (a) vuelva a usar el agente, o (b) corra `lh metrics drain` a mano. Ese trade-off es aceptado.
- **Orden estable.** Los eventos se drenan ordenados por `event_ts` ascendente, no por `insert_ts`. El backend los indexa por `event_ts` también, así que una semana offline aparece en su lugar cronológico correcto, no apelotonada en el momento del reconnect.
- **Idempotencia end-to-end.** Cada evento lleva `event_id` ULID generado al momento de crearlo. El cliente reintenta libremente; el backend hace upsert-by-id. Test crítico: mandar el mismo batch dos veces y verificar que el segundo no crea filas nuevas.
- **Claim con lease para concurrencia.** Antes de mandar un batch, el worker marca las filas como `sink_status=sending` con `lease_until=now+60s`. Si el proceso muere mid-drain, otro `lh` posterior ve el lease vencido y reclama las filas. Dos `lh` corriendo en paralelo no se pisan.
- **Backoff exponencial, reset por éxito.** El sink remoto mantiene un contador de intentos fallidos consecutivos. Backoff 1s → 2s → 4s → ... → max 5min. Cualquier drain exitoso resetea el contador a cero. Es lo que hace fluido el caso "llego a la oficina, primer hook, reintenta, funciona, drena el resto a velocidad normal" sin necesidad de detectar network change cross-platform.
- **Staleness sin TTL por default.** Los eventos `pending` no expiran. Config opcional `metrics.pending_ttl_days` permite al usuario definir una ventana si lo necesita (default `null` = nunca).
- **`lh metrics status`.** Comando nuevo que responde en texto plano: cantidad de eventos `pending`, timestamp del más viejo, timestamp del último intento, próximo intento estimado, y estado reachable/unreachable del último intento por sink. Es la herramienta que usás antes de cerrar la laptop para confirmar que todo drenó.

### Blindajes del modo local (default no negociable)

- **Default implícito.** Si el profile no declara `metrics.sinks`, el harness se comporta exactamente como hoy: `sqlite_local` único, cero red, cero plugins remotos cargados. No hay variable de entorno ni flag que active remotos "por atrás".
- **Opt-in doble.** Activar un sink remoto requiere declararlo en `metrics.sinks` **y** en `[metrics.sinks.<nombre>]` con su config. Faltar cualquiera de los dos = error explícito al startup o config muerta, nunca fallback silencioso a un default remoto.

  ```toml
  [metrics]
  # Default si se omite: ["sqlite_local"]. Remote = opt-in explícito.
  sinks = ["sqlite_local", "http_remote"]

  [metrics.sinks.http_remote]
  url = "https://metrics.flex.internal/ingest"
  # auth, batch_size, timeout, etc.
  ```

- **Discovery ≠ activation.** El registry descubre entry points al startup y los expone en `lh plugins list` como "available". Un plugin descubierto pero no nombrado en el profile nunca se instancia, nunca recibe eventos, nunca abre socket. Test explícito de esta invariante.
- **Visibilidad.** Al arrancar cualquier comando que mueva métricas se imprime en stderr:

  ```
  metrics sinks active: sqlite_local, http_remote → https://metrics.flex.internal/ingest
  identity: martin (source: gh)
  ```

  Se puede silenciar con `--quiet`, pero en ese caso se loggea al logfile del harness igual (nunca queda fuera del rastro).
- **`lh doctor` audita egress.** Sección nueva "network egress" que lista todas las URLs a las que el profile actual puede mandar datos. Permite auditar de un vistazo si un profile está "limpio" antes de usarlo en un contexto sensible (cliente, demo pública, etc.).
- **Sin kill switch global.** No existe `LH_OFFLINE` ni modo avión. Si querés local-only, usás un profile local-only. Una sola fuente de verdad.

### Registry y resolución

`plugins/registry.py` expone:

- `register_builtin(protocol_type, plugin_class)` — llamado al import time por cada sink built-in.
- `discover_entry_points(group: str)` — llamado una sola vez al startup, carga plugins de `[project.entry-points."lazy_harness.metrics_sink"]`. Los nombres se prefijan con `ext:` automáticamente si no lo tienen.
- `resolve(protocol_type, name) -> Plugin` — busca primero built-in, después entry points. Error claro si no encuentra o si hay conflicto.
- `list_available(protocol_type) -> list[PluginInfo]` — para `lh plugins list` (no en este spec, pero el registry lo soporta desde ya).

### Identidad

`core/profiles.py` resuelve `user_id` en este orden:

1. Valor explícito en el profile (`user_id: martin`).
2. `gh api user --jq .login` si `gh` está disponible y autenticado.
3. `git config user.email` parseado (fallback débil).
4. `$USER@$HOSTNAME` (último recurso, marca el evento como `identity_source: implicit`).

El `user_id` se cachea en el profile al primer resolve exitoso para no depender de `gh` en cada hook.

## Archivos críticos a tocar

- `src/lazy_harness/plugins/contracts.py` — **nuevo**, define `MetricsSink`, `MetricEvent`, stubs de los otros 4.
- `src/lazy_harness/plugins/registry.py` — **nuevo**, discovery híbrido.
- `src/lazy_harness/plugins/errors.py` — **nuevo**.
- `src/lazy_harness/monitoring/sinks/sqlite_local.py` — **nuevo**, adapta `db.py` actual al Protocol.
- `src/lazy_harness/monitoring/sinks/http_remote.py` — **nuevo**.
- `src/lazy_harness/monitoring/sinks/worker.py` — **nuevo**, drainer background.
- `src/lazy_harness/monitoring/db.py` — **modificado**, agrega columnas `user_id`/`tenant_id`/`sink_status` + migración idempotente al startup.
- `src/lazy_harness/monitoring/ingest.py` — **modificado**, rutea vía registry en vez de escribir directo.
- `src/lazy_harness/core/profiles.py` — **modificado**, nuevos campos + resolver de identidad.
- `src/lazy_harness/core/config.py` — **modificado**, parser del bloque `metrics_sinks`.
- `src/lazy_harness/cli/metrics.py` (o donde viva hoy) — **modificado**, nuevo subcomando `drain`.
- `tests/` — mirror 1:1 de todo lo anterior.

### Reutilización

- `monitoring/db.py` actual tiene toda la lógica de SQLite schema + upsert por message id — eso se mueve a `sinks/sqlite_local.py` casi verbatim, no se reescribe.
- `monitoring/pricing.py` no se toca: vive antes del sink, calcula tokens/costo y el resultado ya forma parte del `MetricEvent`.
- `core/paths.py` ya resuelve rutas por profile; el sink SQLite usa eso sin cambios.

## Fuera de scope (iteraciones futuras, no en este spec)

- Los otros 4 extension points (`knowledge`, `session_export`, `agent`, `hooks`). Cada uno tendrá su propio brainstorm/spec/plan replicando el patrón que valide este slice.
- Backend HTTP real. Este spec implementa el cliente (`http_remote`) y lo testea contra un servidor de juguete (fixture de `pytest-httpserver` o similar). Diseñar la API del backend compartido es otro proyecto.
- OAuth / tokens / auth fuerte. `user_id` viaja en claro en el body del request. Modo equipo asume red confiable (VPN, LAN, o HTTPS con shared secret simple). Para multi-tenant real (C) habrá que agregar auth.
- UI para ver métricas del equipo agregadas. El sink remoto empuja datos; consumirlos es otro problema.
- Comando `lh plugins list` / `lh plugins doctor`. El registry lo soporta, pero el CLI queda para después.

## Verificación

### Tests unitarios (TDD estricto, repo rule)

- `tests/plugins/test_contracts.py` — `MetricEvent` es frozen, `schema_version` existe, serialización JSON roundtrip.
- `tests/plugins/test_registry.py` — built-in se registra al import, entry points se descubren con prefijo `ext:`, conflict entre dos externos con el mismo nombre levanta `PluginConflict`, built-in gana sobre externo con mismo nombre.
- `tests/monitoring/sinks/test_sqlite_local.py` — escribe evento, roundtrip, `sink_status=pending` por default, migración idempotente sobre DB existente sin columnas nuevas.
- `tests/monitoring/sinks/test_http_remote.py` — encola y retorna rápido, worker hace POST batch, backoff en fallo, marca `failed` tras N reintentos, nunca levanta excepción al caller.
- `tests/monitoring/sinks/test_worker.py` — drenar buffer en orden, respeta batch_size, para limpio en shutdown sin perder eventos en vuelo.
- `tests/core/test_profiles_identity.py` — resolve order (explicit → gh → git → implicit), caching en profile, flag `identity_source` correcta.
- `tests/monitoring/test_ingest.py` — un evento se escribe a todos los sinks configurados, un sink que levanta excepción no tumba al resto.
- `tests/monitoring/test_default_local.py` — profile sin bloque `metrics` → se activa solo `sqlite_local`, ningún plugin remoto se instancia, cero network I/O verificado con monkeypatch.
- `tests/plugins/test_discovery_not_activation.py` — instalar un entry point externo + profile que no lo nombra → el plugin no se inicializa ni recibe eventos (verificable con counters internos).
- `tests/monitoring/test_opt_in_doble.py` — sink nombrado sin bloque de config → error claro al startup. Bloque de config sin estar nombrado → ignorado, warning opcional.
- `tests/monitoring/test_offline_reconnect.py` — simular backend caído durante N eventos, verificar `sink_status=pending`, levantar backend fake, correr un hook → drena en orden por `event_ts`, resetea backoff, marca `sent`.
- `tests/monitoring/test_idempotency.py` — mandar el mismo batch dos veces al backend fake, verificar que la segunda vez no crea filas nuevas (upsert por `event_id`).
- `tests/monitoring/test_lease.py` — dos workers concurrentes sobre la misma DB local, verificar que cada fila se envía exactamente una vez y que un lease vencido se reclama.
- `tests/cli/test_metrics_status.py` — salida de `lh metrics status` con 0 pending, con N pending, con backend unreachable.

### End-to-end

1. **Modo local puro (regresión).** Profile sin `metrics_sinks` → comportamiento idéntico al actual, `monitoring.db` sigue funcionando, dashboards existentes intactos. Ejercido con `lh selftest` (existente) + sesión real de Claude Code.
2. **Modo equipo con backend fake.** Profile con `[sqlite_local, http_remote]`, levantar `pytest-httpserver` como backend, correr un hook sintético, verificar que (a) el evento aparece en SQLite inmediato con `sink_status=pending`, (b) tras `lh metrics drain` aparece marcado `sent`, (c) el backend fake recibió el JSON con `user_id` correcto.
3. **Modo equipo con backend caído.** Mismo profile, sin levantar el servidor fake. Verificar que los hooks corren sin latencia percibida (test con timer), los eventos quedan `pending`, y `lh metrics drain` reintenta y falla con warning pero sin crashear.
4. **Identity flow.** Borrar `user_id` cacheado, correr con `gh` disponible → se cachea el handle. Desinstalar `gh` simulado, borrar cache → cae a git config. Sin git → cae a `$USER@host` con `identity_source=implicit`.
5. **Entry point discovery.** Crear un paquete de test `lh-metrics-test-sink` con un entry point, instalarlo en el venv de tests, verificar que `registry.list_available()` lo muestra como `ext:test_sink`.

### Checks del repo

- `uv run pytest` verde, output pristine.
- `uv run ruff check src tests` limpio.
- `uv run mkdocs build --strict` (no se tocan docs en este spec, debe seguir buildeando).
- Migración de DB existente: correr el harness contra una SQLite pre-spec, verificar que arranca sin errores y los datos viejos quedan con `user_id=local`, `tenant_id=local`.
