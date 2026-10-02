# SGADR - Documentación para el equipo de desarrollo

## 1. Introducción

SGADR es una aplicación web para la gestión de alertas, demandas y respuestas dentro de un contexto operativo regional. Está desarrollada en Python puro, sin dependencias externas de frontend ni librerías adicionales, y utiliza SQLite como almacenamiento persistente.

La aplicación se ejecuta como un módulo Python y expone una interfaz web local con un servidor WSGI propio. El proyecto está pensado para funcionar en entornos controlados, con bajo consumo de recursos y sin necesidad de internet para la capa principal.

## 2. Requisitos del entorno

### Python

- Python 3.13+
- Compatibilidad con la biblioteca estándar únicamente

### Sistema operativo

- Windows, Linux o macOS

### Archivos necesarios

- Código fuente del proyecto
- Base de datos SQLite
- Certificados TLS opcionales si se desea servir por HTTPS

## 3. Estructura del proyecto

```text
sgadr/
    __init__.py
    __main__.py
    alerts.py
    api.py
    app.py
    auth.py
    catalog.py
    domain.py
    mailer.py
    reminders.py
    security.py
    server.py
    service.py
    static.py
    store.py
    web/
        index.html
        css/
        js/

tests/
    __init__.py
    support.py
    test_accounts.py
    test_alerts.py
    test_api.py
    test_mailer.py
    test_service.py
    test_web.py
```

## 4. Flujo de arranque

### 4.1. Crear la base de datos inicial

Ejecutar:

```bash
python -m sgadr --db sgadr.db create-user admin --role admin
```

Esto crea la base SQLite y registra al primer usuario administrador. Se pedirá la contraseña en la consola y se requiere una longitud mínima de 12 caracteres.

### 4.2. Iniciar la aplicación

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443
```

La aplicación queda disponible en:

```text
http://localhost:8443
```

Si se desea servir con TLS:

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443 --cert cert.pem --key key.pem
```

## 5. Datos de acceso

Tras el primer registro, se puede iniciar sesión con:

- Usuario: `admin`
- Contraseña: la configurada durante la creación del usuario

## 6. Red de acceso y puertos

Por defecto, la aplicación usa el puerto 8443 para desarrollo local.

- HTTP: 8443
- HTTPS: 8443 con certificados TLS

## 7. Ejecución de pruebas

El proyecto usa `unittest` como sistema principal de pruebas.

Comando:

```bash
python -m unittest discover -s tests -t .
```

Verificación esperada:

```text
Ran 108 tests in ...
OK
```

## 8. Configuración de correo

La aplicación puede emitir avisos por correo cuando hay reportes vencidos. Las variables de entorno soportadas son:

```text
SGADR_SMTP_HOST
SGADR_SMTP_PORT
SGADR_SMTP_SECURITY
SGADR_SMTP_USER
SGADR_SMTP_PASSWORD
SGADR_SMTP_FROM
SGADR_SMTP_TO
```

### Ejemplo de configuración

En PowerShell:

```powershell
$env:SGADR_SMTP_HOST="smtp.gmail.com"
$env:SGADR_SMTP_USER="usuario@gmail.com"
$env:SGADR_SMTP_PASSWORD="contraseña_de_aplicacion"
```

### Probar correo

```bash
python -m sgadr test-mail
```

Si la configuración SMTP no está presente, el sistema solo registra la situación sin intentar enviar correos.

## 9. Funciones principales del sistema

### Autenticación y usuarios

- Alta de usuarios
- Bajas y reactivaciones
- Asignación de roles
- Cambio de contraseña
- Control de sesiones

### Alertas y demandas

- Registro y seguimiento de alertas
- Gestión de demandas y respuestas
- Categorización por áreas y roles
- Control de estados y auditoría

### Bitácora y auditoría

La aplicación incorpora mecanismos de validación de la bitácora encadenada y verificación de integridad. El módulo `verify-audit` puede ejecutarse para comprobar si la bitácora fue alterada.

Comando:

```bash
python -m sgadr --db sgadr.db verify-audit
```

## 10. Mantenimiento recomendado

- Mantener una copia persistente de la base de datos SQLite.
- Hacer respaldo de la configuración y entorno antes de cambios importantes.
- Ejecutar la suite de pruebas antes de cada entrega o merge.
- Revisar logs del servidor cuando haya fallas de arranque o acceso.
- Usar roles y permisos con cuidado para no afectar la separación funcional del sistema.

## 11. Solución de problemas habituales

### El navegador no abre la app

Verificar que el servidor esté levantado:

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443
```

Luego abrir:

```text
http://localhost:8443
```

### La base de datos no existe

Crearla de nuevo con:

```bash
python -m sgadr --db sgadr.db create-user admin --role admin
```

### Las pruebas fallan

Ejecutar:

```bash
python -m unittest discover -s tests -t .
```

### El correo no se envía

Verificar las variables de entorno y ejecutar:

```bash
python -m sgadr test-mail
```

## 12. Recomendaciones de desarrollo

1. Mantener los cambios pequeños y verificables.
2. Ejecutar pruebas cada vez que se modifique lógica de negocio o autenticación.
3. No introducir dependencias externas si no son absolutas necesarias.
4. Documentar cualquier cambio de estructura de base o flujo de usuarios.
5. Probar siempre tanto la capa de negocio como la interfaz web cuando haya cambios funcionales.

## 13. Resumen operativo

Para un nuevo integrante del equipo, el flujo habitual es:

```bash
cd C:\Users\patri\OneDrive\Escritorio\Python\sgadr
python -m sgadr --db sgadr.db create-user admin --role admin
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443
python -m unittest discover -s tests -t .
```

Con esto la aplicación queda operativa, se crea la base inicial y se puede validar que la funcionalidad principal sigue funcionando.
