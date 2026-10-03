# SGADR: Sistema de Gestión de Alertas, Demandas y Respuestas

Python 3.13+, solo biblioteca estándar. Base SQLite, servidor WSGI propio, interfaz web sin dependencias externas (funciona sin internet).

## Puesta en marcha

```
python -m sgadr --db /var/lib/sgadr/sgadr.db create-user admin --role admin     # primer administrador
python -m sgadr --db /var/lib/sgadr/sgadr.db serve --host 0.0.0.0 --port 8443 --cert cert.pem --key key.pem
```

El resto de las cuentas se crean desde la consola web (rol `admin`, sección Usuarios): alta con contraseña temporal que la persona debe cambiar al ingresar, baja, reactivación y restablecimiento. El administrador no ve alertas, demandas ni bitácora (separación de funciones); sus acciones quedan en la bitácora encadenada, visible para Comité y Monitoreo.

## Aviso por correo de reportes vencidos

Cada reporte de estado vencido se avisa una sola vez por correo (por defecto a `centrodemonitoreochaco@gmail.com`) y queda en el log. Se configura por variables de entorno (la clave no se pasa por línea de comandos):

| Variable | Significado | Por defecto |
|---|---|---|
| `SGADR_SMTP_HOST` | Servidor SMTP (sin él, el correo queda desactivado) | |
| `SGADR_SMTP_PORT` | Puerto | 587 (starttls), 465 (ssl), 25 (none) |
| `SGADR_SMTP_SECURITY` | `starttls`, `ssl` o `none` | `starttls` |
| `SGADR_SMTP_USER` / `SGADR_SMTP_PASSWORD` | Credenciales (juntas) | |
| `SGADR_SMTP_FROM` | Remitente | el usuario SMTP |
| `SGADR_SMTP_TO` | Destinatarios separados por coma | `centrodemonitoreochaco@gmail.com` |

Ejemplo con Gmail (requiere verificación en dos pasos en la cuenta emisora y una "contraseña de aplicación"): `SGADR_SMTP_HOST=smtp.gmail.com SGADR_SMTP_USER=cuenta@gmail.com SGADR_SMTP_PASSWORD=<contraseña de aplicación>`.

Probar la configuración: `python -m sgadr test-mail`. Si el envío falla, el aviso se reintenta en cada ciclo (60 s) mientras el servicio siga activo; un reinicio descarta los pendientes. El correo no incluye datos de contacto del municipio.

## Documentación para desarrollo

Ver la carpeta [docs](docs/README.md): arquitectura, reglas de dominio, API, seguridad y guía de desarrollo.

## Pruebas

`python -m unittest discover -s tests -t .`
