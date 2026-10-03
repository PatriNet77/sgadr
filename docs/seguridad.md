# Seguridad

Documento para quien desarrolla, revisa o audita. Describe lo que **está implementado** y lo que **queda fuera** (a cargo de la infraestructura o pendiente). No es una declaración de aplicabilidad ISO; sirve de insumo para ella.

## Activos y amenazas

| Activo | Amenaza principal | Control |
|---|---|---|
| Datos de contacto de municipios | Fuga hacia roles que no los necesitan | Proyección de campos por rol en el servidor |
| Circuito de autorización | Saltear al Comité o al Nodo 00 | Tabla `TRANSITIONS` verificada en servicio; la UI no decide |
| Cuentas | Fuerza bruta, enumeración, robo de sesión | Scrypt, bloqueo temporal, mensaje genérico, token hasheado, expiración |
| Bitácora | Alteración para ocultar acciones | Triggers + cadena SHA-256 + verificación desde la interfaz |
| Disponibilidad en emergencia | Denegación por bloqueo de cuentas o clientes lentos | Bloqueo temporal (5 min), timeout de conexión (15 s), límite de cuerpo |
| Integridad de datos | Doble edición simultánea | Bloqueo optimista con `expected_version` |
| Navegador del operador | XSS | Sin `innerHTML`, CSP sin scripts/estilos en línea, token en `sessionStorage` |

## Controles implementados

**Autenticación y cuentas** (`auth.py`, `security.py`)
- Contraseñas con `scrypt` (N=2¹⁵, r=8, p=1, sal de 16 bytes), parámetros embebidos en el hash para poder migrar costos. Mínimo 12 caracteres, máximo 256.
- Token de sesión aleatorio de 256 bits; en la base solo se guarda su SHA-256. Vence a las 8 horas. Un cambio de contraseña cierra las demás sesiones; una baja o restablecimiento cierra todas las de la cuenta.
- 5 intentos fallidos bloquean la cuenta 5 minutos. Usuario inexistente, cuenta inactiva, bloqueada y clave incorrecta devuelven **el mismo error y el mismo costo de cómputo** (hash simulado), por lo que no se puede enumerar cuentas ni medir tiempos.
- Altas y restablecimientos entregan una **clave temporal** que la persona debe cambiar antes de operar (el servidor bloquea el resto de la API).
- Nunca queda el sistema sin una cuenta `admin` activa; el administrador no puede darse de baja ni restablecerse a sí mismo.

**Autorización** (`domain.py`, servicios)
- Roles fijos; la regla se aplica en los servicios, no en `api.py` (`_require_admin`, `_require_reader`, `TRANSITIONS`).
- Separación de funciones: quien administra cuentas no lee ni modifica el contenido operativo, y no puede leer la bitácora donde quedan sus propios actos.
- Un `area` solo accede a demandas asignadas a su área.

**Entrada y salida** (`api.py`, `domain.py`)
- Esquemas estrictos por ruta: claves desconocidas se rechazan (evita *mass assignment*).
- `clean_text` normaliza, limita longitud y rechaza caracteres de control; teléfonos por expresión regular acotada; enums validados contra su tipo.
- SQL parametrizado en todo el código (la única interpolación es el nombre de columnas en `AlertService._save`, tomadas de una lista blanca).
- Los errores no filtran detalles internos; el 500 es genérico y la traza queda en el log.

**Transporte y cabeceras**
- TLS ≥ 1.2 con `--cert/--key`; en ese caso se envía HSTS.
- Todas las respuestas: `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` (API), `Server: sgadr` (sin versión de Python).
- Estáticos con `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'`.

**Datos y archivos**
- El archivo de base se crea con permisos `0600` **antes** de abrirse.
- Los estáticos se sirven solo desde `web/`: se bloquean `..`, `\`, bytes nulos, archivos ocultos y enlaces simbólicos que escapen.

**Trazabilidad** (`store.py`)
- Bitácora inmutable (triggers) y encadenada (SHA-256). Cada acción de negocio y de cuentas se registra en la misma transacción que el cambio. No se registran contraseñas ni tokens (hay una prueba que lo verifica).
- Los intentos de ingreso con usuario inexistente van solo al log técnico (no inflan la bitácora).

**Correo** (`mailer.py`)
- Credenciales SMTP solo por variables de entorno; `repr` de la configuración oculta la clave.
- STARTTLS/SSL con verificación de certificado; no se envían credenciales sin cifrado.
- Remitente y destinatarios validados (sin saltos de línea); asunto y cuerpo saneados contra inyección de cabeceras.
- El correo **no incluye datos de contacto** del municipio.

## Correspondencia con ISO/IEC 27001:2022 (Anexo A)

| Control | Cómo lo cubre el sistema | Alcance |
|---|---|---|
| A.5.3 Segregación de funciones | Rol `admin` sin acceso operativo; Comité autoriza lo que Nodo 00 solicita | Aplicación |
| A.5.15 / A.5.18 Control y derechos de acceso | Roles, `TRANSITIONS`, proyección de campos, alta/baja desde consola | Aplicación |
| A.5.16 Gestión de identidades | Cuentas individuales, baja lógica con revocación de sesiones | Aplicación |
| A.5.17 / A.8.5 Información de autenticación y autenticación segura | Scrypt, clave temporal, bloqueo, sesiones con vencimiento. **Sin segundo factor** (decisión del proyecto) | Aplicación |
| A.8.2 Derechos de acceso privilegiado | Un solo rol privilegiado, acotado a cuentas, auditado | Aplicación |
| A.8.3 Restricción de acceso a la información | Compartimentación 07/00 | Aplicación |
| A.8.15 Registro | Bitácora inmutable y encadenada; log técnico | Aplicación |
| A.8.16 Actividades de seguimiento | Reportes vencidos notificados; verificación de integridad de bitácora | Aplicación |
| A.8.24 Criptografía | TLS ≥ 1.2, scrypt, SHA-256 | Aplicación y despliegue |
| A.8.26 / A.8.28 Requisitos de seguridad y codificación segura | Validación estricta, SQL parametrizado, CSP, sin `innerHTML` | Aplicación |
| A.8.29 Pruebas de seguridad | Pruebas de permisos, inyección de cabeceras, traversal, bloqueo, auditoría | Aplicación |
| A.8.9 Gestión de la configuración | Configuración por entorno; migraciones versionadas | Aplicación |
| A.8.13 Copias de respaldo | **No implementado** (ver pendientes) | Infraestructura |
| A.8.20 / A.8.22 Seguridad y segregación de redes | Fuera del alcance de la aplicación | Infraestructura |

## Responsabilidades del despliegue (no las resuelve el código)

1. **Copias de respaldo** de la base (`sqlite3 .backup` o copia en frío con el servicio detenido) y prueba periódica de restauración con `python -m sgadr verify-audit`.
2. **Exposición**: el servidor integrado es multihilo y suficiente para uso institucional interno. Para exposición más amplia, usar un proxy inverso con TLS (nginx, Apache) y limitar por IP; la aplicación no limita intentos por origen, solo por cuenta.
3. **Secretos**: guardar `SGADR_SMTP_PASSWORD` en un archivo de entorno con permisos `0600` del servicio (por ejemplo `EnvironmentFile` de systemd), no en el repositorio ni en la línea de comandos.
4. **Permisos del sistema**: ejecutar con un usuario sin privilegios dueño exclusivo del directorio de la base.
5. **Reloj**: los vencimientos dependen de la hora del servidor; mantenerla sincronizada (NTP). La interfaz usa la hora del servidor, no la del equipo.
6. **Cuenta emisora de correo**: dedicada, con verificación en dos pasos y contraseña de aplicación.

## Limitaciones conocidas

- Sin segundo factor de autenticación (descartado por el equipo; hay que dejarlo registrado en el análisis de riesgos).
- `POST /password` no tiene límite propio de intentos con la clave actual; exige una sesión válida.
- La cola de correos pendientes vive en memoria: un reinicio la pierde (el vencimiento sigue en la bitácora y el log).
- Un solo proceso y una sola conexión SQLite: suficiente para decenas de operadores; no hay alta disponibilidad.
- La bitácora detecta alteraciones pero no las previene frente a quien tenga acceso al archivo y pueda reescribir **toda** la cadena; para ese caso conviene exportar periódicamente el último `hash` a un lugar externo.
