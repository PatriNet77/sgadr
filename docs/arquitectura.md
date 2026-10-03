# Arquitectura

## Vista general

```
Navegador (ES modules, sin build)            Servidor local (un proceso)
┌────────────────────────────┐   HTTPS/JSON  ┌──────────────────────────────────────────────┐
│ web/js: views, store, api  │ ───────────▶  │ server.py  ThreadedWSGIServer (+TLS ≥ 1.2)   │
│ sondeo cada 15 s           │               │   └ api.py  Api (WSGI): rutas, validación    │
└────────────────────────────┘               │        ├ service.py  DemandService            │
                                             │        ├ alerts.py   AlertService             │
                                             │        └ auth.py     AuthService              │
                                             │             └ store.py  Store (SQLite, WAL)   │
                                             │ reminders.py  ReminderWorker (hilo)           │
                                             │   └ mailer.py EmailNotifier (SMTP)            │
                                             └──────────────────────────────────────────────┘
```

Un solo proceso, una sola base SQLite. La concurrencia la resuelve `Store`; no hay estado compartido fuera de la base, salvo la cola de correos pendientes del notificador (en memoria).

## Módulos (`sgadr/`)

| Módulo | Responsabilidad | Depende de |
|---|---|---|
| `domain.py` | Enums (roles, estados, niveles), tabla `TRANSITIONS`, campos ocultos por rol, errores, `Actor`, validación (`clean_text`, `NewAlert`, `NewDemand`). **Puro: sin I/O.** | nada |
| `catalog.py` | Catálogos: áreas, tipos de recurso (con área sugerida) y municipios | nada |
| `store.py` | Conexión SQLite, migraciones, transacciones, bitácora encadenada | `domain` |
| `security.py` | Hash de contraseñas (scrypt) | nada |
| `service.py` | Demandas: registro, transiciones, lectura proyectada por rol | `domain`, `store`, `catalog` |
| `alerts.py` | Alertas: registro, verificación, reportes, cambio de nivel, vencimientos | `domain`, `store` |
| `auth.py` | Cuentas, sesiones, bloqueo por intentos, administración de usuarios | `domain`, `security`, `store` |
| `api.py` | HTTP/JSON: enrutado, límites, mapeo de errores, cabeceras de seguridad | servicios |
| `static.py` | Archivos estáticos de `web/` con CSP estricta y ETag | nada |
| `server.py` | Servidor WSGI multihilo con TLS opcional | `api` |
| `reminders.py` | Hilo que detecta reportes vencidos y notifica una vez por ciclo | `alerts` |
| `mailer.py` | Notificador por correo (SMTP, STARTTLS/SSL, reintentos) | nada |
| `app.py` | Ensamblado del grafo de dependencias (`build_app`) | todos |
| `__main__.py` | CLI: `serve`, `create-user`, `deactivate-user`, `verify-audit`, `test-mail` | `app` |

Regla de dependencias: `domain` y `catalog` no importan nada del paquete; los servicios no conocen HTTP; `api` no contiene reglas de negocio (solo traduce y valida el formato). Si una regla aparece en `api.py`, está mal ubicada.

## Flujo de una petición

1. `Api.__call__` decide si es estático (`/` o `/static/…`) o API.
2. `_dispatch` resuelve la ruta (404/405), extrae el token `Bearer` y llama a `AuthService.authenticate`.
3. Si la cuenta tiene clave temporal, solo se permiten `/me`, `/logout` y `/password` (403 `password_change_required` en el resto).
4. El handler valida el cuerpo (`_expect_keys` rechaza claves desconocidas; `Request.json` exige `application/json`, `Content-Length` y máximo 64 KiB) y arma el comando de dominio.
5. El servicio verifica el rol, valida, y ejecuta **una transacción** (`Store.tx`) que modifica los datos **y** agrega la entrada de bitácora.
6. Toda `DomainError` se mapea a HTTP en `_ERROR_MAP`; cualquier otra excepción es un 500 genérico y se registra con traza en el log.

## Modelo de datos (SQLite, `PRAGMA user_version` = 3)

| Tabla | Contenido y claves |
|---|---|
| `counters` | Secuencias anuales de códigos (`demand-AAAA`, `alert-AAAA`) |
| `demands` | Demanda: `code` único (`ENOS-AAAA-NNNN`), `version` (bloqueo optimista), `state`, `alert_level`, `alert_id`, contacto, `assigned_area`, `response_detail` |
| `alerts` | Alerta: `code` (`ALERTA-AAAA-NNNN`), `state`, `level`, `source`, `municipality_key` (normalizado), verificaciones (`apa_verified_at`, `police_verified_at`), `center_informed_at`, `next_report_due_at`, `overdue_flagged_for` |
| `alert_reports` | Reportes de estado de cada alerta |
| `users` | Cuenta: hash scrypt, rol, área, `active`, `failed_attempts`, `locked_until`, `must_change_password` |
| `sessions` | Solo el SHA-256 del token, con vencimiento |
| `audit_log` | `seq`, `prev_hash`, `payload` (JSON), `hash`. Triggers abortan `UPDATE` y `DELETE` |

Índice único parcial `uq_alert_live_municipality`: **una sola alerta vigente por municipio** (la garantiza la base, no solo el código). Todas las tablas son `STRICT` y con `CHECK` en estados y niveles.

### Migraciones

`store._MIGRATIONS` es una tupla de scripts SQL; el índice `i` lleva a la versión `i+1`. Cada una corre en una transacción junto con `PRAGMA user_version`. Reglas:

- **Solo se agregan al final; nunca se edita una ya publicada.**
- Una base más nueva que el software se rechaza (no se degrada).
- Una migración que falla revierte y cierra la conexión.
- Las pruebas cubren la actualización desde una base real de versión anterior (`test_alerts.py`).

### Concurrencia

- Una conexión compartida por todos los hilos, con `RLock` que serializa lecturas y escrituras.
- Escrituras con `BEGIN IMMEDIATE`; WAL y `busy_timeout = 5000`.
- **Bloqueo optimista**: las modificaciones exigen `expected_version`; si cambió, 409 `concurrency_conflict`. La interfaz lo informa y recarga.
- Los códigos se generan dentro de la misma transacción que inserta (sin huecos ni duplicados).

### Bitácora encadenada

`hash = SHA-256(prev_hash + payload)`. `verify_audit_chain` recorre la tabla y recalcula. Los triggers impiden alterar filas por SQL; la cadena detecta además inserciones intermedias o la edición de archivos de base. Los eventos de sistema (vencimientos) se registran con actor `system`.

## Frontend (`sgadr/web/`)

Módulos ES nativos, sin empaquetado. Se sirve desde `static.py` con CSP `default-src 'self'`: **no hay scripts ni estilos en línea**, y por eso el estilo dinámico va por CSSOM (`style.setProperty`).

| Archivo | Rol |
|---|---|
| `js/main.js` | Arranque, ciclo de sondeo (15 s) y reloj (1 s), flujo de clave temporal |
| `js/store.js` | Estado compartido, `refresh()` (llamadas simultáneas se reúnen en una), desfase con la hora del servidor |
| `js/api.js` | Cliente REST, token en `sessionStorage`, `ApiError` (status 0 = sin conexión) |
| `js/rules.js` | Reglas derivadas de `/meta` y de los datos (transiciones del rol, alerta activa, urgencia) |
| `js/labels.js` | Vocabulario de la interfaz y roles/pestañas |
| `js/ui.js` | `modal` con formulario, `act`/`press` (acción + aviso + recarga + manejo de conflicto) |
| `js/dom.js` | `h()` constructor DOM: **nunca `innerHTML`**; todo texto entra como nodo de texto |
| `js/clocks.js` | "Reloj del reporte" calculado con hora del servidor |
| `js/drawer.js` | Panel de detalle; reconstruye solo si cambia `tipo:id:versión` |
| `js/views/*` | Una vista por sección (`board`, `alerts`, `demands`, `audit`, `users`, `login`, `account`) |

Decisiones de interfaz que conviene no romper:

- Las vistas con buscador se montan **una vez** (`mountView`) y solo se reemplazan las filas, para no perder el foco al escribir.
- Se compara una firma de datos antes de reconstruir listas.
- El nivel de alerta usa tres barras además del color (no depende solo del color).
- Respeta `prefers-color-scheme`, `prefers-reduced-motion` y funciona hasta 390 px de ancho.
