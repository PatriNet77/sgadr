# Documentación para el equipo de desarrollo

## 1. Objetivo del proyecto

SGADR es una aplicación de gestión de alertas, demandas y respuestas para uso interno, con base SQLite, servidor WSGI propio y interfaz web sin dependencias externas.

## 2. Requisitos

- Python 3.13 o superior
- Sistema operativo compatible con Python
- Acceso local a la carpeta del proyecto
- No requiere paquetes adicionales ni internet para funcionar en el entorno base

## 3. Estructura principal del proyecto

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

tests/
    test_accounts.py
    test_alerts.py
    test_api.py
    test_mailer.py
    test_service.py
    test_web.py
```

## 4. Primer arranque

Desde la raíz del proyecto:

```bash
cd C:\Users\patri\OneDrive\Escritorio\Python\sgadr
```

Crear la base de datos inicial y el usuario administrador:

```bash
python -m sgadr --db sgadr.db create-user admin --role admin
```

Se pedirá ingresar una contraseña con mínimo 12 caracteres. Una vez creada la cuenta, la base de datos queda inicializada.

## 5. Levantar la aplicación

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443
```

La aplicación queda disponible en:

```text
http://localhost:8443
```

Si se usan certificados TLS:

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443 --cert cert.pem --key key.pem
```

## 6. Credenciales por defecto

Tras la creación del primer usuario administrador, se puede iniciar sesión con:

- Usuario: `admin`
- Contraseña: la configurada durante la creación del usuario

## 7. Pruebas

El proyecto usa `unittest`, no `pytest`.

Ejecutar la suite completa:

```bash
python -m unittest discover -s tests -t .
```

Resultado esperado:

```text
Ran 108 tests in ...
OK
```

## 8. Configuración de correo

La aplicación puede avisar por correo cuando hay reportes vencidos. Las variables de entorno soportadas son:

```text
SGADR_SMTP_HOST
SGADR_SMTP_PORT
SGADR_SMTP_SECURITY
SGADR_SMTP_USER
SGADR_SMTP_PASSWORD
SGADR_SMTP_FROM
SGADR_SMTP_TO
```

Uso de ejemplo con Gmail:

```bash
set SGADR_SMTP_HOST=smtp.gmail.com
set SGADR_SMTP_USER=usuario@gmail.com
set SGADR_SMTP_PASSWORD=contraseña_de_aplicacion
```

Probar la configuración de correo:

```bash
python -m sgadr test-mail
```

Si no hay configuración SMTP, la aplicación registra la alerta solo en log y no envía correo.

## 9. Mantenimiento y buenas prácticas

- Mantener la base de datos en una ruta conocida y persistente.
- No exponer la app directamente a internet sin un proxy inverso o TLS apropiado.
- Revisar los logs del servidor para detectar errores de inicio o SMTP.
- Ejecutar la suite de pruebas antes de entregar cambios.
- Mantener la base de datos y los archivos de configuración dentro del entorno de despliegue.

## 10. Solución rápida de problemas

### La página no abre

Verificar que el servidor esté levantado y que el puerto sea el correcto:

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443
```

### Las pruebas fallan

Ejecutar:

```bash
python -m unittest discover -s tests -t .
```

### Error de correo

Comprobar que las variables SMTP están bien definidas y probar con:

```bash
python -m sgadr test-mail
```

## 11. Recomendación de flujo de trabajo

1. Crear la base de datos inicial.
2. Arrancar la aplicación localmente.
3. Ejecutar pruebas antes de confirmar cambios.
4. Validar correo si el módulo de alertas vencidas se modifica.
5. Registrar cualquier cambio de configuración o entorno relevante en el repositorio.
