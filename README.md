# SGADR

Sistema de Gestión de Alertas, Demandas y Respuestas.

## Descripción

SGADR es una aplicación web desarrollada en Python para gestionar alertas, demandas y respuestas dentro de un contexto operativo. El sistema usa SQLite como base de datos local, un servidor WSGI propio y una interfaz web sin dependencias externas.

Está diseñado para operar en entornos controlados, con baja complejidad de despliegue y sin requerir internet para el funcionamiento básico del sistema.

## Objetivo

Centralizar la gestión operativa de alertas y demandas, mantener trazabilidad de las acciones, apoyar la auditoría y permitir la separación funcional entre roles administrativos y operativos.

## Requisitos

- Python 3.13 o superior
- Sistema operativo compatible con Python
- Acceso al directorio del proyecto
- SQLite disponible por medio de la biblioteca estándar de Python

## Estructura del proyecto

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

## Primer arranque

Desde la raíz del proyecto:

```bash
python -m sgadr --db sgadr.db create-user admin --role admin
```

Este comando crea la base de datos SQLite y registra el primer usuario administrador. Se pedirá una contraseña con mínimo 12 caracteres.

## Inicio del servicio

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443
```

La aplicación queda disponible en:

```text
http://localhost:8443
```

También puede ejecutarse con TLS:

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443 --cert cert.pem --key key.pem
```

## Credenciales iniciales

Tras la creación del primer usuario administrador, se puede iniciar sesión con:

- Usuario: admin
- Contraseña: la ingresada durante la creación del usuario

## Pruebas

El proyecto usa unittest como framework de pruebas.

```bash
python -m unittest discover -s tests -t .
```

Se recomienda ejecutar esta validación antes de entregar cambios funcionales.

## Configuración del correo de avisos

Cuando existen reportes vencidos, el sistema puede enviar avisos por correo. La configuración se realiza con variables de entorno.

| Variable | Descripción | Valor sugerido |
|---|---|---|
| `SGADR_SMTP_HOST` | Servidor SMTP | `smtp.gmail.com` |
| `SGADR_SMTP_PORT` | Puerto del servidor | `587`, `465` o `25` |
| `SGADR_SMTP_SECURITY` | Seguridad SMTP | `starttls`, `ssl` o `none` |
| `SGADR_SMTP_USER` | Usuario SMTP | cuenta emisora |
| `SGADR_SMTP_PASSWORD` | Contraseña de aplicación o clave SMTP | secreto |
| `SGADR_SMTP_FROM` | Remitente del correo | usuario SMTP |
| `SGADR_SMTP_TO` | Destinatarios | correo o lista separada por coma |

Ejemplo con Gmail:

```bash
SGADR_SMTP_HOST=smtp.gmail.com SGADR_SMTP_USER=cuenta@gmail.com SGADR_SMTP_PASSWORD=<contraseña de aplicación>
```

Prueba rápida de correo:

```bash
python -m sgadr test-mail
```

## Auditoría

La aplicación incorpora verificación de integridad de la bitácora encadenada.

```bash
python -m sgadr --db sgadr.db verify-audit
```

## Mantenimiento recomendado

- Mantener la base de datos en una ruta persistente y conocida.
- Ejecutar pruebas antes de consolidar cambios.
- Revisar logs si el servicio falla al iniciar.
- No exponer la aplicación sin control de acceso ni TLS si está fuera del entorno local.

## Solución rápida de problemas

### La página no abre

Verificar que el servidor está levantado y que el puerto es correcto:

```bash
python -m sgadr --db sgadr.db serve --host 0.0.0.0 --port 8443
```

### La base de datos no existe

```bash
python -m sgadr --db sgadr.db create-user admin --role admin
```

### Las pruebas fallan

```bash
python -m unittest discover -s tests -t .
```

## Documentación complementaria

- [DEVELOPMENT.md](DEVELOPMENT.md)
- [DOCUMENTACION_EQUIPO.md](DOCUMENTACION_EQUIPO.md)
- [MANUAL_DEL_EQUIPO_DE_DESARROLLO.md](MANUAL_DEL_EQUIPO_DE_DESARROLLO.md)

## Resumen

SGADR está preparado para funcionar como sistema de gestión local y operativo, con foco en confiabilidad, auditoría y simplicidad de implementación. La documentación técnica complementaria del repositorio contiene detalles adicionales para desarrollo y mantenimiento del equipo.

