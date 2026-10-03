# Reglas de dominio

Fuente de verdad: `sgadr/domain.py` (tablas) y los servicios. Este documento las explica; si discrepa del código, manda el código y hay que corregir el documento.

## Roles

| Rol | Quién | Puede |
|---|---|---|
| `nodo_07` | Información | **Único punto de ingreso** de alertas y demandas; registra reportes de estado y cambios de nivel |
| `nodo_00` | Recursos provinciales | Verifica alertas municipales con APA y Policía; informa al Centro de Operaciones; verifica, eleva, asigna y cierra demandas; reasigna cuando el área agotó recursos |
| `comite` | Comité de Emergencia Provincial | Autoriza o rechaza demandas pendientes de autorización; lee la bitácora |
| `monitoreo` | Centro de Monitoreo | Solo lectura (alertas, demandas, bitácora) |
| `area` | Área provincial ejecutora | Ve solo las demandas **asignadas a su área**; inicia la respuesta, la informa o declara recursos agotados |
| `admin` | Administración del sistema | Gestiona cuentas. **No lee alertas, demandas ni bitácora** (separación de funciones) |

### Compartimentación (campos que cada rol no recibe)

| Rol | Demandas | Alertas |
|---|---|---|
| `nodo_07` | `assigned_area` | (ve todo) |
| `nodo_00` | `contact_name`, `contact_phone` | `contact_name`, `contact_phone` |
| `area` | `contact_name`, `contact_phone` | sin acceso |
| `monitoreo` | `contact_name`, `contact_phone` | `contact_name`, `contact_phone` |
| `comite` | (ve todo) | (ve todo) |
| `admin` | sin acceso | sin acceso |

Los campos **no se envían** (no vienen vacíos): `DemandService._project` y `AlertService._project` los quitan antes de serializar. Si se agrega un campo sensible, hay que decidir su visibilidad en `HIDDEN_FIELDS` / `ALERT_HIDDEN_FIELDS`; un campo nuevo sin entrada se muestra a todos.

## Demandas

Código `ENOS-AAAA-NNNN`. Se registran en estado `recibida`.

```
recibida ─▶ verificada ─▶ pendiente_autorizacion ─▶ autorizada ─▶ asignada ─▶ en_ejecucion ─▶ respondida ─▶ cerrada
   │                              │                                  │  ▲            │
   └─▶ rechazada                  └─▶ rechazada                      │  │            │
                                                                     ▼  │            ▼
                                                              recursos_agotados ◀────┘
```

| Desde | Hacia | Rol |
|---|---|---|
| recibida | verificada | nodo_00 |
| recibida | rechazada | nodo_00 |
| verificada | pendiente_autorizacion | nodo_00 |
| pendiente_autorizacion | autorizada | comite |
| pendiente_autorizacion | rechazada | comite |
| autorizada | asignada | nodo_00 |
| asignada | en_ejecucion | area |
| asignada | recursos_agotados | area |
| en_ejecucion | respondida | area |
| en_ejecucion | recursos_agotados | area |
| recursos_agotados | asignada (reasignar) | nodo_00 |
| respondida | cerrada | nodo_00 |

Estados terminales: `cerrada`, `rechazada`. Cualquier otra transición es 409 `invalid_transition`; un rol no autorizado, 403.

Datos exigidos por transición (`DemandService.transition`):

- **→ asignada**: `assigned_area`, que debe estar en `catalog.AREAS`.
- **→ respondida**: `response_detail` (10 a 4000 caracteres).
- **→ rechazada / recursos_agotados**: `note` (5 a 1000 caracteres).
- Un `area` solo puede operar demandas cuyo `assigned_area` es la suya.

Vínculo con la alerta: al registrar, si el municipio tiene una alerta **activa**, la demanda se vincula (`alert_id`) y **hereda su nivel**. Sin alerta activa, el cliente debe indicar `alert_level` (si no, 422).

Validaciones de ingreso (`NewDemand.validated`): `quantity` entero 1 a 1.000.000; teléfono con el formato `+?[0-9][0-9 ()-]{5,19}`; textos sin caracteres de control; longitudes máximas por campo.

## Alertas

Código `ALERTA-AAAA-NNNN`. Niveles: `amarillo`, `naranja`, `rojo`. Orígenes: `apa`, `municipio`.

| Origen | Estado inicial | Contacto |
|---|---|---|
| `apa` | **`activa`** (APA ya la verificó) | prohibido |
| `municipio` | `pendiente_verificacion` | nombre y teléfono obligatorios |

Estados: `pendiente_verificacion` → `activa` → `cerrada`; o `pendiente_verificacion` → `descartada`.

- **Verificación** (nodo_00): se registra por separado con APA y con Policía. Cuando ambas confirman, la alerta pasa a `activa` y arranca el reloj de reportes. Si una **no confirma**, se descarta (con `note` obligatoria). No se puede verificar dos veces con la misma fuente ni una alerta que no está pendiente.
- **Centro de Operaciones** (nodo_00): se marca como informado una vez por nivel. Un **cambio de nivel lo reinicia**.
- **Reporte de estado** (nodo_07): registra lo informado por el municipio y reinicia el plazo. Con `alert_lowered = true` cierra la alerta.
- **Cambio de nivel** (nodo_07): exige motivo (`note`), reinicia el plazo según el nuevo nivel y borra `center_informed_at`.
- **Una sola alerta vigente por municipio** (índice único parcial sobre `municipality_key`, que normaliza tildes, mayúsculas y espacios). Un segundo intento es 409 `duplicate`.

### Frecuencia de reporte

| Nivel | Cada |
|---|---|
| amarillo | 12 h |
| naranja | 6 h |
| rojo | 6 h |

(`domain.REPORT_INTERVAL`; la interfaz lo recibe en `/meta`.)

### Reportes vencidos

`ReminderWorker` ejecuta `AlertService.flag_overdue()` cada `--reminder-interval` segundos (60 por defecto). Para cada alerta activa con `next_report_due_at` vencido:

1. marca `overdue_flagged_for = next_report_due_at` (sin cambiar `version`, para no invalidar ediciones en curso),
2. escribe `alert_report_overdue` en la bitácora,
3. invoca el notificador (log + correo).

Es **idempotente por ciclo**: no vuelve a notificar el mismo vencimiento; un nuevo reporte genera un nuevo plazo y, por tanto, un nuevo aviso posible.
