# API REST v1

Base: `/api/v1`. JSON UTF-8. Autenticación: `Authorization: Bearer <token>` (sin cookies, por lo que no aplica CSRF). Las respuestas llevan `Cache-Control: no-store` y cabeceras de seguridad.

## Convenciones

- Cuerpos: `Content-Type: application/json` obligatorio (415 si no), `Content-Length` obligatorio (411), máximo 64 KiB (413). Debe ser un objeto.
- **Esquema estricto**: faltan claves → 422 `Faltan campos`; sobran claves → 422 `Campos no permitidos`.
- **Bloqueo optimista**: las operaciones sobre un registro existente exigen `expected_version` (entero ≥ 1; no se aceptan booleanos ni decimales). Todas las respuestas de registro incluyen `version`.
- Errores: `{"error": {"code": "...", "message": "..."}}`.

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `bad_request` / `domain_error` | JSON inválido, cuerpo vacío o incompleto |
| 401 | `unauthenticated` | Sin token, token inválido/vencido, credenciales incorrectas o cuenta bloqueada (mensaje genérico) |
| 403 | `permission_denied` | Rol sin permiso sobre la acción o el recurso |
| 403 | `password_change_required` | Cuenta con clave temporal intentando operar |
| 404 | `not_found` | Recurso o ruta inexistente |
| 405 / 411 / 413 / 415 | `method_not_allowed` / `length_required` / `payload_too_large` / `unsupported_media_type` | Protocolo |
| 409 | `invalid_transition` | Transición o paso no permitido en el estado actual |
| 409 | `concurrency_conflict` | `expected_version` desactualizada |
| 409 | `duplicate` | Alerta vigente ya existente en el municipio |
| 422 | `validation_error` | Datos inválidos |
| 500 | `internal_error` | Error no controlado (detalle solo en el log) |

## Sesión y cuenta

| Método y ruta | Rol | Cuerpo | Respuesta |
|---|---|---|---|
| `GET /healthz` (sin prefijo, pública) | cualquiera | | `{"status":"ok"}` |
| `POST /login` | pública | `username`, `password` | `token`, `expires_at`, `username`, `role`, `must_change_password` |
| `POST /logout` | autenticado | | `{"status":"ok"}` |
| `GET /me` | autenticado | | `username`, `role`, `area`, `must_change_password`, `server_time` |
| `GET /meta` | autenticado | | `server_time`, `report_interval_hours`, `demand_transitions` (`from`, `to`, `roles`), `areas`, `roles`, `resources` (`name`, `suggested_area`), `municipalities` |
| `POST /password` | autenticado | `current_password`, `new_password` | `{"status":"ok"}`; cierra las demás sesiones |

Sesión de 8 horas. 5 intentos fallidos bloquean la cuenta 5 minutos (temporal, para que un atacante no deje fuera a los operadores en plena emergencia). El login de un usuario inexistente consume el mismo tiempo que uno real.

## Demandas

| Método y ruta | Rol | Notas |
|---|---|---|
| `GET /demands?all=0\|1` | todos salvo `admin` | `all=1` incluye cerradas y rechazadas. `area` ve solo las suyas |
| `POST /demands` | `nodo_07` | `municipality`, `locality`, `resource_type`, `quantity`, `reason`, `contact_name`, `contact_phone`, opcional `alert_level`. 201 |
| `GET /demands/{id}` | todos salvo `admin` | |
| `POST /demands/{id}/transition` | según tabla de transiciones | `target`, `expected_version`; opcionales `note`, `assigned_area`, `response_detail` |

## Alertas

Sin acceso para `area` y `admin`.

| Método y ruta | Rol | Cuerpo |
|---|---|---|
| `GET /alerts?all=0\|1&overdue=0\|1` | lectura | `all=1` incluye cerradas/descartadas; `overdue=1` solo con reporte vencido |
| `POST /alerts` | `nodo_07` | `level`, `source`, `municipality`, `summary`; `contact_name` y `contact_phone` obligatorios si `source=municipio`, prohibidos si `apa`. 201 |
| `GET /alerts/{id}` | lectura | Incluye `reports` |
| `POST /alerts/{id}/verify` | `nodo_00` | `source` (`apa`/`policia`), `confirmed` (bool), `expected_version`, opcional `note` (obligatoria si `confirmed=false`) |
| `POST /alerts/{id}/center-informed` | `nodo_00` | `expected_version` |
| `POST /alerts/{id}/reports` | `nodo_07` | `municipal_status`, `alert_lowered` (bool), `expected_version` |
| `POST /alerts/{id}/level` | `nodo_07` | `level`, `note`, `expected_version` |

Campos calculados en las alertas: `report_interval_hours`, `overdue` y `overdue_minutes`.

## Bitácora

Solo `comite` y `monitoreo`.

| Método y ruta | Respuesta |
|---|---|
| `GET /audit?limit=N` | `items`: `seq`, `hash` (12 primeros caracteres), `entry` (JSON del evento). `limit` entre 1 y 500, 100 por defecto |
| `GET /audit/verify` | `{"valid": true\|false}` recalculando toda la cadena |

Acciones registradas (`entry.action`): `register`, `transition`, `alert_register`, `alert_verified`, `alert_discarded`, `alert_center_informed`, `alert_report`, `alert_level_change`, `alert_report_overdue`, `login`, `login_failed`, `logout`, `user_created`, `user_deactivated`, `user_reactivated`, `password_reset`, `password_changed`.

## Administración de cuentas

Solo `admin`.

| Método y ruta | Cuerpo | Notas |
|---|---|---|
| `GET /users` | | `username`, `role`, `area`, `active`, `created_at`, `locked`, `must_change_password`. Nunca hashes |
| `POST /users` | `username`, `temporary_password`, `role`, opcional `area` | Usuario: `[a-z0-9._-]{3,32}`. `area` obligatoria (y válida) para el rol `area`, prohibida para los demás. Clave de al menos 12 caracteres. Queda con `must_change_password`. 201 |
| `POST /users/{username}/active` | `active` (bool) | No se puede dar de baja a uno mismo ni a la última cuenta `admin` activa. La baja revoca sus sesiones; reactivar desbloquea |
| `POST /users/{username}/password` | `temporary_password` | Revoca sesiones, desbloquea y exige cambio. No sobre la propia cuenta |

## Archivos estáticos

`GET /` y `GET /static/…` sirven `sgadr/web/` (extensiones `html`, `css`, `js`, `svg`, `png`, `ico`). Se rechazan rutas con `..`, barras invertidas, bytes nulos, archivos ocultos y enlaces simbólicos que salgan de la raíz. Responden con `ETag` y 304.
