# Guía de desarrollo

## Requisitos y entorno

- Python **3.13 o 3.14**. **Sin dependencias de ejecución**: no agregar paquetes a `sgadr/`.
- Node.js solo para validar sintaxis del frontend (`node --check`); no hay paso de build.
- Herramientas opcionales de desarrollo (no van al servidor): `mypy`.

```
git clone <repositorio> && cd sgadr
python -m unittest discover -s tests -t .        # 108 pruebas, ~3 s
python -m mypy --strict sgadr tests              # debe terminar sin errores
for f in $(find sgadr/web/js -name '*.js'); do node --check "$f"; done
```

Servidor de desarrollo con una base temporal:

```
export SGADR_DB=/tmp/sgadr-dev.db
python -m sgadr create-user admin --role admin      # pide la contraseña por teclado
python -m sgadr serve --port 8080                   # http://127.0.0.1:8080
```

## Convenciones de código

- **Tipado estricto**: toda función con anotaciones; `mypy --strict` limpio es condición de integración.
- **Comentarios** que explican *por qué* (decisión de seguridad, regla del circuito), no *qué*.
- Errores de negocio como subclases de `DomainError` y con mensaje en español pensado para la persona que opera. Nunca devolver `str(exc)` de un error técnico.
- Textos de interfaz en español rioplatense, oración con mayúscula inicial, sin `→`, sin mayúsculas sostenidas. Una acción se llama igual en el botón, el formulario y el aviso (`labels.js`).
- Frontend: **jamás `innerHTML`**, ni `eval`, ni atributos `style` en línea ni `onclick=` en HTML. Usar `h()` y `style.setProperty`.
- Fechas: siempre UTC ISO 8601 en la base y en la API; la interfaz formatea para `es-AR`.

## Pruebas

| Archivo | Cubre |
|---|---|
| `test_service.py` | Demandas, seguridad de contraseñas, bitácora a nivel de servicio |
| `test_api.py` | Autenticación, permisos por rol, validación, endurecimiento HTTP |
| `test_alerts.py` | Alertas, vencimientos, recordatorios, migración desde la v1 |
| `test_accounts.py` | Administración de cuentas, clave temporal, separación de funciones |
| `test_mailer.py` | Configuración SMTP, contenido, reintentos y envío real contra un SMTP local |
| `test_web.py` | Estáticos, CSP, traversal, `/meta` |

`tests/support.py` provee lo común:

- `FakeClock`: reloj controlable (`advance`). **Los servicios reciben el reloj por constructor**; no usar `datetime.now()` directo.
- `ApiTestCase`: aplicación completa en memoria con un usuario por rol (`USERS`), `call()` (cliente WSGI sin red), `login()` y `step()`.
- `setUpModule`/`tearDownModule`: reducen el costo de scrypt **solo en pruebas**. Todo módulo que cree cuentas debe importarlos (`from .support import setUpModule, tearDownModule`); si no, la suite se vuelve lenta.

Criterios para una prueba nueva:

1. Una regla de negocio nueva requiere al menos una prueba de **camino feliz**, una de **rol no autorizado** y una de **dato inválido o estado incorrecto**.
2. Los cambios de datos verifican también la **entrada de bitácora** y que `verify_audit()` siga siendo `True`.
3. Antes de dar por buena una prueba de seguridad, romper el control a propósito y confirmar que la prueba falla (mutación manual). Así se detectó una prueba de verificación de alertas que no protegía nada.

## Recetas

### Agregar un endpoint

1. Si implica una regla, agregarla en el **servicio** (con rol, validación, transacción y bitácora), no en `api.py`.
2. En `api.py`: handler que valida con `_expect_keys`, arma el comando y llama al servicio; registrar la ruta en `self._routes`.
3. Si debe poder usarse con clave temporal, agregarlo a `_pre_change_handlers` (por defecto **no**).
4. Pruebas (ver criterios) y actualizar `docs/api.md`.

### Agregar un estado o una transición de demanda

1. `DemandState` y `TRANSITIONS` en `domain.py` (rol incluido).
2. Si exige datos extra, validarlos en `DemandService.transition`.
3. Interfaz: `DEMAND_STATES`, `ACTION_LABELS` en `labels.js`; si es parte del tramo principal, `PIPELINE`. Las acciones disponibles salen de `/meta`, no se codifican.
4. La columna `state` de `demands` no tiene `CHECK` sobre los valores: validar en el servicio y cubrirlo con pruebas.
5. Actualizar `docs/dominio.md`.

### Agregar un rol

1. `Role` en `domain.py`; decidir su lugar en `DEMAND_READ_ROLES`, `ALERT_READ_ROLES`, `HIDDEN_FIELDS`, `ALERT_HIDDEN_FIELDS` y `TRANSITIONS`.
2. Auditoría: agregar o no el rol a quienes leen la bitácora (`api.py`, `_audit_list` y `_verify_audit`).
3. Interfaz: `ROLES` en `labels.js` (nombre y pestañas) y su color en `app.css` (`[data-role="..."]`).
4. Agregar un usuario del rol a `USERS` en `tests/support.py` y pruebas de qué **no** puede hacer.

### Agregar una migración de base

1. Agregar `_V4` (el siguiente número) al final de `_MIGRATIONS` en `store.py`. **No editar versiones anteriores.**
2. Escribirla compatible con datos existentes (`ALTER TABLE … ADD COLUMN` con valor por defecto, índices `IF NOT EXISTS`).
3. Prueba de actualización desde la versión anterior con datos reales (ver `test_upgrade_from_v1_preserves_existing_data`).
4. Hacer copia de la base antes de desplegar; no hay migración inversa.

### Agregar un canal de notificación

Un notificador es un `Callable[[dict], None]` (opcionalmente con `flush()` para reintentos). Implementarlo, sumarlo a la `ChainedNotifier` de `__main__._serve` y agregar sus variables de entorno a la configuración. Un canal que falla no debe afectar a los demás ni frenar al worker (la cadena ya lo garantiza). No incluir datos de contacto del municipio en canales no controlados.

### Agregar una vista

1. Archivo en `web/js/views/`, con `renderX(container)`; si tiene buscador o filtros, usar `mountView` y reconstruir solo las filas cuando cambie la firma de datos.
2. Registrar en `VIEWS` de `main.js`, en `TABS` y en las pestañas del rol (`labels.js`).
3. Los datos entran en `state` (`store.js`); si se necesitan nuevas llamadas, sumarlas a `refresh()` respetando el rol.
4. Verificar en navegador: foco del teclado, modo oscuro, 390 px de ancho, consola sin errores (CSP).

## Despliegue

1. Copiar el paquete `sgadr/` al servidor; Python 3.13+. No hay instalación de dependencias.
2. Crear el usuario del servicio y el directorio de datos (solo ese usuario). Crear la primera cuenta `admin` con la CLI.
3. Servicio (ejemplo systemd): `ExecStart=python3 -m sgadr --db /var/lib/sgadr/sgadr.db serve --host 0.0.0.0 --port 8443 --cert … --key …`, con `EnvironmentFile=` para `SGADR_SMTP_*` (permisos `0600`).
4. Probar el correo con `python -m sgadr test-mail` y la integridad con `verify-audit`.
5. Programar la copia de respaldo y la restauración de prueba.

## Versión en la nube (futuro)

Hoy `Store` mezcla SQL y conexión. Para pasar a PostgreSQL conviene extraer una interfaz de repositorio detrás de `Store` (`tx`, `read`, `append_audit`) antes de tocar los servicios; las migraciones y los índices parciales tienen equivalente directo. El frontend y la API no cambian.

## Deuda técnica y mejoras previstas

| Tema | Detalle |
|---|---|
| Respaldo y recuperación | Copia automática con verificación de bitácora al restaurar |
| Historial por demanda | Endpoint que devuelva los cambios de estado de una demanda (hoy solo en la bitácora general) |
| Límite en `POST /password` | Contar intentos fallidos de la clave actual |
| Correos pendientes durables | Persistir la cola para sobrevivir a reinicios |
| Exportación externa del hash | Anclar periódicamente el último hash de la bitácora fuera del servidor |
| Pruebas de interfaz | Hoy se verifican manualmente con navegador; automatizar el recorrido por rol |
| Catálogos editables | Áreas, recursos y municipios están en `catalog.py`; moverlos a la base con consola |
