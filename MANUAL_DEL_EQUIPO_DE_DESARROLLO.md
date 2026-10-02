# Manual del equipo de desarrollo

## 1. Propósito

Este documento define la forma correcta de preparar, levantar, validar y mantener el proyecto SGADR en entornos de desarrollo y operación. Su objetivo es asegurar consistencia, trazabilidad y ejecución segura de la aplicación entre todos los miembros del equipo.

## 2. Alcance

Este manual aplica a:

- configuración inicial del entorno de desarrollo
- preparación de la base de datos
- arranque de la aplicación
- pruebas automatizadas
- validación de correo y reportes enviados
- diagnóstico rápido de errores comunes
- mantenimiento básico del sistema

## 3. Descripción general del sistema

SGADR es una aplicación web desarrollada en Python, pensada para gestionar alertas, demandas y respuestas dentro de un contexto operativo. La solución utiliza:

- SQLite como base de datos local
- servidor WSGI nativo de Python
- interfaz web sin dependencias externas
- autenticación por usuario/contraseña
- roles y permisos diferenciados por tipo de operación
- auditoría de eventos y bitácora encadenada

La aplicación se ejecuta como un módulo Python usando el comando `python -m sgadr`.

## 4. Requisitos mínimos

### 4.1. Software

- Python 3.13 o superior
- Acceso al directorio del proyecto en el sistema local
- Consola de comandos (PowerShell, cmd o terminal bash)

### 4.2. Dependencias

El proyecto no requiere paquetes externos para funcionar en su versión base. La implementación usa solo la biblioteca estándar de Python.

## 5. Estructura del repositorio

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
README.md
DEVELOPMENT.md
MANUAL_DEL_EQUIPO_DE_DESARROLLO.md
```

## 6. Preparación del entorno local

### 6.1. Ubicación del proyecto

Ejemplo de ruta de trabajo:

```powershell
cd C:\Users\patri\OneDrive\Escritorio\Python\sgadr
```

### 6.2. Verificar versión de Python

```bash
python --version
```

Debe mostrarse Python 3.13 o superior.

## 7. Creación de la base de datos y usuario inicial

El primer arranque requiere crear la base de datos y un usuario administrador.

### Comando

```bash
python -m sgadr --db sgadr.db create-user admin --role admin
```

### Resultado esperado

Se pedirá ingresar una contraseña con 12 o más caracteres y la confirmación. Si todo es correcto, la terminal mostrará algo como:

```text
Usuario 'admin' creado.
```

### Nota importante

La base de datos SQLite se genera automáticamente en el archivo indicado por `--db`.

## 8. Arranque de la aplicación

### 8.1. Iniciar el servidor web

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443
```

### 8.2. Acceso a la interfaz

Abrir en el navegador:

```text
http://localhost:8443
```

### 8.3. Servir con TLS

Si el entorno lo requiere:

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443 --cert cert.pem --key key.pem
```

## 9. Inicio de sesión

Tras crear el usuario administrador, puede autenticarse con:

- Usuario: `admin`
- Contraseña: la ingresada al crear el usuario

## 10. Validación de la aplicación

### 10.1. Pruebas automáticas

El proyecto usa `unittest` como framework de pruebas.

Ejecutar la suite completa:

```bash
python -m unittest discover -s tests -t .
```

### 10.2. Resultado esperado

La ejecución debe terminar con un resultado del tipo:

```text
Ran 108 tests in ...
OK
```

Si aparecen errores, deben corregirse antes de entregar cambios funcionales.

## 11. Configuración de correo SMTP

La aplicación dispone de soporte para enviar avisos por correo cuando existen reportes vencidos.

### Variables de entorno

```text
SGADR_SMTP_HOST
SGADR_SMTP_PORT
SGADR_SMTP_SECURITY
SGADR_SMTP_USER
SGADR_SMTP_PASSWORD
SGADR_SMTP_FROM
SGADR_SMTP_TO
```

### Ejemplo con Gmail

```powershell
$env:SGADR_SMTP_HOST="smtp.gmail.com"
$env:SGADR_SMTP_USER="usuario@gmail.com"
$env:SGADR_SMTP_PASSWORD="contraseña_de_aplicacion"
```

### Probar la configuración SMTP

```bash
python -m sgadr test-mail
```

Si no se configura el servidor SMTP, la aplicación registra el evento sin enviar correo.

## 12. Auditoría y seguridad

El sistema incluye mecanismos de auditoría para comprobar la integridad de la bitácora encadenada.

### Verificación

```bash
python -m sgadr --db sgadr.db verify-audit
```

Resultado esperado:

- `Bitácora ÍNTEGRA.` cuando la auditoría es válida
- `ALERTA: bitácora ALTERADA.` cuando la integridad no se cumple

## 13. Procedimientos de desarrollo

### 13.1. Flujo recomendado antes de enviar cambios

1. Actualizar la rama local desde el origen.
2. Revisar que no haya archivos temporales o pruebas no deseadas.
3. Ejecutar la suite de pruebas.
4. Validar que la app arranca correctamente.
5. Confirmar que el cambio no afecta autenticación ni auditoría.
6. Registrar el cambio o problema con un resumen claro.

### 13.2. Buenas prácticas

- Mantener la base de datos bajo una ruta controlada y persistente.
- No exponer la aplicación directamente a internet sin un proxy o terminación TLS adecuada.
- No subir credenciales ni contraseñas reales al repositorio.
- Preferir pruebas automatizadas sobre cambios de lógica o autenticación.
- Mantener una separación clara entre áreas funcionales del sistema.

## 14. Diagnóstico de errores comunes

### 14.1. La página no abre

Causas posibles:

- el servidor no está corriendo
- el puerto no es el correcto
- la app se cerró por error de ejecución

Solución:

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443
```

### 14.2. Error de base de datos

Si la base no existe o está corrupta, recrearla con el comando de usuario administrador.

```bash
python -m sgadr --db sgadr.db create-user admin --role admin
```

### 14.3. Error de pruebas

Ejecutar la suite para localizar el problema:

```bash
python -m unittest discover -s tests -t .
```

### 14.4. Error de correo

Verificar variables y ejecutar:

```bash
python -m sgadr test-mail
```

## 15. Recomendaciones de operación

- Mantener un control explícito de la ruta de la base de datos por entorno.
- Documentar cualquier cambio en configuración, puerto, roles o credenciales.
- Realizar copias de seguridad de la base antes de cambios de esquema o migraciones.
- Revisar los logs de la aplicación y del servidor cuando haya fallas de arranque.

## 16. Resumen operativo

Para un entorno de trabajo estándar, el flujo básico es:

```bash
cd C:\Users\patri\OneDrive\Escritorio\Python\sgadr
python -m sgadr --db sgadr.db create-user admin --role admin
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443
python -m unittest discover -s tests -t .
```

Este conjunto de pasos garantiza la inicialización funcional del sistema y la validación básica de estabilidad antes de continuar con el desarrollo.

## 17. Conclusión

Este manual debe ser considerado la referencia base para el equipo de desarrollo. Su finalidad es mantener un procedimiento uniforme de preparación, ejecución, prueba y soporte del sistema, reduciendo errores operativos y acelerando la incorporación de nuevos integrantes al proyecto.
