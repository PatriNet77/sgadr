# Documentación para el equipo de desarrollo

SGADR digitaliza los circuitos de alerta, demanda y respuesta ante emergencias por ENOS en la Provincia del Chaco: el **Nodo 07** (información) registra alertas y demandas de los municipios, el **Nodo 00** (recursos provinciales) las verifica y asigna áreas, el **Comité de Emergencia Provincial** autoriza, y las **áreas provinciales** ejecutan la respuesta. **Monitoreo** observa y la **Administración** gestiona cuentas.

| Documento | Para qué sirve |
|---|---|
| [arquitectura.md](arquitectura.md) | Capas, módulos, flujo de una petición, modelo de datos, concurrencia, migraciones y frontend |
| [dominio.md](dominio.md) | Reglas de negocio: roles, permisos, máquina de estados de demandas, ciclo de alertas |
| [api.md](api.md) | Referencia de la API REST (rutas, cuerpos, respuestas, errores) |
| [seguridad.md](seguridad.md) | Controles implementados, modelo de amenazas y correspondencia con ISO/IEC 27001:2022 |
| [desarrollo.md](desarrollo.md) | Entorno, pruebas, convenciones, recetas para extender el sistema, despliegue y deuda técnica |

El arranque y la configuración del correo están en el [README raíz](../README.md).

## Principios que no se negocian

1. **Solo biblioteca estándar** (Python 3.13+; JavaScript sin frameworks ni CDN). El sistema corre en servidores locales, posiblemente sin internet.
2. **El servidor es la única fuente de verdad de las reglas.** La interfaz las recibe por `/api/v1/meta` y nunca decide un permiso: solo oculta lo que el servidor igual rechazaría.
3. **Compartimentación 07/00 como control técnico**, no como convención: se aplica en servicios (proyección de campos y roles por transición), no en la interfaz.
4. **Cada cambio es atómico con su registro de auditoría** (misma transacción) y la bitácora es inmutable y encadenada.
5. **Todo error de negocio es explícito y tipado**; la API nunca filtra detalles internos.
