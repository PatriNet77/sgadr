"""Casos de uso del circuito de alertas (amarillo / naranja / rojo).

Reglas tomadas de los circuitos 1 a 3 del documento:
- APA es el camino principal: la alerta nace ACTIVA (APA es la fuente, no requiere verificación).
- Un municipio informa a través del Nodo 07: la alerta nace PENDIENTE_VERIFICACION y el
  Nodo 00 la confirma con APA y con la policía; con ambas confirmaciones pasa a ACTIVA.
  Si una verificación NO confirma, se DESCARTA (el municipio puede volver a informar).
- Una vez ACTIVA, el Nodo 00 informa al Centro de Operaciones y el Nodo 07 solicita el
  reporte de estado al municipio cada 12 h (amarillo) o 6 h (naranja y rojo).
- Si el reporte indica que la alerta bajó, se CIERRA la comunicación hasta una nueva alerta.
- Hay una sola alerta vigente por municipio: sus cambios de nivel se registran sobre ella.

Cada operación valida rol y estado, usa bloqueo optimista y registra la bitácora en la
MISMA transacción que el cambio.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

from .domain import (
    ALERT_HIDDEN_FIELDS,
    ALERT_READ_ROLES,
    REPORT_INTERVAL,
    Actor,
    AlertLevel,
    AlertSource,
    AlertState,
    ConcurrencyConflict,
    DuplicateError,
    InvalidTransition,
    NewAlert,
    NotFound,
    PermissionDenied,
    Role,
    ValidationError,
    VerificationSource,
    clean_text,
    normalize_key,
)
from .store import Store

Clock = Callable[[], datetime]
View = dict[str, Any]

_OPEN_STATES: Final = (AlertState.PENDIENTE_VERIFICACION.value, AlertState.ACTIVA.value)
_INTERNAL_FIELDS: Final = frozenset({"municipality_key", "overdue_flagged_for"})
# Lista blanca de columnas que `_save` puede modificar (los nombres se interpolan en el SQL).
_MUTABLE: Final = frozenset({
    "state", "level", "apa_verified_at", "police_verified_at", "center_informed_at",
    "activated_at", "next_report_due_at", "closed_at",
})
_VERIFY_COLUMN: Final = {
    VerificationSource.APA: "apa_verified_at",
    VerificationSource.POLICIA: "police_verified_at",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require(actor: Actor, role: Role, message: str) -> None:
    if actor.role is not role:
        raise PermissionDenied(message)


class AlertService:
    def __init__(self, store: Store, clock: Clock = _utc_now) -> None:
        self._store = store
        self._clock = clock

    # ---------- escritura ----------

    def register(self, actor: Actor, cmd: NewAlert) -> View:
        """Ingreso de una alerta (exclusivo del Nodo 07), desde APA o desde un municipio."""
        _require(actor, Role.NODO_07, "Las alertas ingresan por el Nodo 07 (desde APA o municipios).")
        data = cmd.validated()
        now = self._clock()
        from_apa = data.source is AlertSource.APA
        state = AlertState.ACTIVA if from_apa else AlertState.PENDIENTE_VERIFICACION
        stamp = now.isoformat()
        due = (now + REPORT_INTERVAL[data.level]).isoformat() if from_apa else None
        with self._store.tx() as conn:
            seq = conn.execute(
                "INSERT INTO counters (name, value) VALUES (?, 1) "
                "ON CONFLICT(name) DO UPDATE SET value = value + 1 RETURNING value",
                (f"alert-{now.year}",),
            ).fetchone()["value"]
            code = f"ALERTA-{now.year}-{seq:04d}"
            try:
                alert_id: int = conn.execute(
                    "INSERT INTO alerts (code, version, state, level, source, municipality,"
                    " municipality_key, summary, contact_name, contact_phone, apa_verified_at,"
                    " activated_at, next_report_due_at, created_by, created_at, updated_at)"
                    " VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (code, state.value, data.level.value, data.source.value, data.municipality,
                     normalize_key(data.municipality), data.summary, data.contact_name,
                     data.contact_phone, stamp if from_apa else None, stamp if from_apa else None,
                     due, actor.username, stamp, stamp),
                ).fetchone()["id"]
            except sqlite3.IntegrityError as exc:
                if "municipality_key" not in str(exc):
                    raise
                raise DuplicateError(
                    "El municipio ya tiene una alerta vigente: registre un reporte o un cambio de nivel."
                ) from exc
            self._audit(conn, now, actor, "alert_register", code, to=state.value,
                        level=data.level.value, source=data.source.value,
                        municipality=data.municipality)
        return self.get(actor, alert_id)

    def verify(
        self,
        actor: Actor,
        alert_id: int,
        source: VerificationSource,
        confirmed: bool,
        *,
        expected_version: int,
        note: str | None = None,
    ) -> View:
        """Verificación de una alerta municipal con APA o con la policía (Nodo 00)."""
        _require(actor, Role.NODO_00, "La verificación con APA y policía corresponde al Nodo 00.")
        if type(confirmed) is not bool:
            raise ValidationError("'confirmed' debe ser verdadero o falso.")
        now = self._clock()
        with self._store.tx() as conn:
            row = self._load(conn, alert_id, expected_version)
            if row["state"] != AlertState.PENDIENTE_VERIFICACION:
                raise InvalidTransition("Solo se verifican alertas pendientes de verificación.")
            column = _VERIFY_COLUMN[source]
            if row[column] is not None:
                raise InvalidTransition(f"La verificación con {source.value} ya fue registrada.")
            if not confirmed:
                note = clean_text("note", note, max_len=1000, min_len=5)
                self._save(conn, row, now, state=AlertState.DESCARTADA.value, closed_at=now.isoformat())
                self._audit(conn, now, actor, "alert_discarded", row["code"],
                            source=source.value, note=note)
            else:
                if note is not None:
                    note = clean_text("note", note, max_len=1000)
                changes: dict[str, Any] = {column: now.isoformat()}
                both = all(
                    (changes.get(c) or row[c]) is not None for c in _VERIFY_COLUMN.values()
                )
                if both:
                    changes.update(
                        state=AlertState.ACTIVA.value,
                        activated_at=now.isoformat(),
                        next_report_due_at=(now + REPORT_INTERVAL[AlertLevel(row["level"])]).isoformat(),
                    )
                self._save(conn, row, now, **changes)
                self._audit(conn, now, actor, "alert_verified", row["code"], source=source.value,
                            activated=both, note=note)
        return self.get(actor, alert_id)

    def mark_center_informed(self, actor: Actor, alert_id: int, *, expected_version: int) -> View:
        """El Nodo 00 informa al Centro de Operaciones la activación del nivel vigente."""
        _require(actor, Role.NODO_00, "Informar al Centro de Operaciones corresponde al Nodo 00.")
        now = self._clock()
        with self._store.tx() as conn:
            row = self._load(conn, alert_id, expected_version)
            self._require_active(row)
            if row["center_informed_at"] is not None:
                raise InvalidTransition("El Centro de Operaciones ya fue informado del nivel vigente.")
            self._save(conn, row, now, center_informed_at=now.isoformat())
            self._audit(conn, now, actor, "alert_center_informed", row["code"], level=row["level"])
        return self.get(actor, alert_id)

    def add_report(
        self,
        actor: Actor,
        alert_id: int,
        municipal_status: str,
        alert_lowered: bool,
        *,
        expected_version: int,
    ) -> View:
        """Reporte de estado del municipio (Nodo 07). Si la alerta bajó, se cierra la comunicación."""
        _require(actor, Role.NODO_07, "Los reportes de estado los registra el Nodo 07.")
        status = clean_text("municipal_status", municipal_status, max_len=2000, min_len=5)
        if type(alert_lowered) is not bool:
            raise ValidationError("'alert_lowered' debe ser verdadero o falso.")
        now = self._clock()
        with self._store.tx() as conn:
            row = self._load(conn, alert_id, expected_version)
            self._require_active(row)
            conn.execute(
                "INSERT INTO alert_reports (alert_id, reported_at, reported_by, municipal_status,"
                " alert_lowered, level_at_report) VALUES (?, ?, ?, ?, ?, ?)",
                (alert_id, now.isoformat(), actor.username, status, int(alert_lowered), row["level"]),
            )
            if alert_lowered:
                self._save(conn, row, now, state=AlertState.CERRADA.value,
                           closed_at=now.isoformat(), next_report_due_at=None)
            else:
                due = now + REPORT_INTERVAL[AlertLevel(row["level"])]
                self._save(conn, row, now, next_report_due_at=due.isoformat())
            self._audit(conn, now, actor, "alert_report", row["code"], lowered=alert_lowered,
                        to=AlertState.CERRADA.value if alert_lowered else row["state"])
        return self.get(actor, alert_id)

    def change_level(
        self, actor: Actor, alert_id: int, level: AlertLevel, note: str, *, expected_version: int
    ) -> View:
        """Escalada o descenso de nivel (Nodo 07). Reinicia el ciclo y exige informar de nuevo al Centro."""
        _require(actor, Role.NODO_07, "Los cambios de nivel los registra el Nodo 07.")
        if not isinstance(level, AlertLevel):
            raise ValidationError("Nivel de alerta inválido.")
        note = clean_text("note", note, max_len=1000, min_len=5)
        now = self._clock()
        with self._store.tx() as conn:
            row = self._load(conn, alert_id, expected_version)
            self._require_active(row)
            if row["level"] == level:
                raise ValidationError("El nivel indicado ya es el vigente.")
            self._save(conn, row, now, level=level.value, center_informed_at=None,
                       next_report_due_at=(now + REPORT_INTERVAL[level]).isoformat())
            self._audit(conn, now, actor, "alert_level_change", row["code"],
                        **{"from": row["level"], "to": level.value, "note": note})
        return self.get(actor, alert_id)

    def flag_overdue(self) -> list[View]:
        """Marca (una sola vez por ciclo) las alertas cuyo reporte venció y devuelve su detalle.

        Lo invoca el ReminderWorker. Es idempotente: una alerta ya marcada para el mismo
        vencimiento no se vuelve a devolver hasta que llegue un nuevo vencimiento.
        """
        now = self._clock()
        with self._store.tx() as conn:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE state = 'activa' AND next_report_due_at <= ?"
                " AND (overdue_flagged_for IS NULL OR overdue_flagged_for != next_report_due_at)"
                " ORDER BY next_report_due_at",
                (now.isoformat(),),
            ).fetchall()
            for row in rows:
                # Marca interna del sistema: no cambia `version` para no invalidar ediciones en curso.
                conn.execute("UPDATE alerts SET overdue_flagged_for = ? WHERE id = ?",
                             (row["next_report_due_at"], row["id"]))
                self._audit(conn, now, None, "alert_report_overdue", row["code"],
                            level=row["level"], due=row["next_report_due_at"])
        return [self._project(r, Role.NODO_07, now) for r in rows]

    # ---------- lectura ----------

    def get(self, actor: Actor, alert_id: int) -> View:
        self._require_reader(actor)
        rows = self._store.read("SELECT * FROM alerts WHERE id = ?", (alert_id,))
        if not rows:
            raise NotFound(f"Alerta {alert_id} inexistente.")
        view = self._project(rows[0], actor.role, self._clock())
        view["reports"] = [
            {**dict(r), "alert_lowered": bool(r["alert_lowered"])}
            for r in self._store.read(
                "SELECT reported_at, reported_by, municipal_status, alert_lowered, level_at_report"
                " FROM alert_reports WHERE alert_id = ? ORDER BY id",
                (alert_id,),
            )
        ]
        return view

    def list_alerts(
        self, actor: Actor, *, only_open: bool = True, only_overdue: bool = False
    ) -> list[View]:
        self._require_reader(actor)
        rows = self._store.read("SELECT * FROM alerts ORDER BY id DESC")
        now = self._clock()
        views = [
            self._project(r, actor.role, now)
            for r in rows
            if not only_open or r["state"] in _OPEN_STATES
        ]
        return [v for v in views if v["overdue"]] if only_overdue else views

    # ---------- internos ----------

    @staticmethod
    def _require_reader(actor: Actor) -> None:
        if actor.role not in ALERT_READ_ROLES:
            raise PermissionDenied("Su rol no tiene acceso a las alertas.")

    @staticmethod
    def _require_active(row: sqlite3.Row) -> None:
        if row["state"] != AlertState.ACTIVA:
            raise InvalidTransition("La operación requiere una alerta activa.")

    @staticmethod
    def _load(conn: sqlite3.Connection, alert_id: int, expected_version: int) -> sqlite3.Row:
        row: sqlite3.Row | None = conn.execute(
            "SELECT * FROM alerts WHERE id = ?", (alert_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"Alerta {alert_id} inexistente.")
        if row["version"] != expected_version:
            raise ConcurrencyConflict("La alerta fue modificada por otro usuario; recargue.")
        return row

    @staticmethod
    def _save(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime, **changes: Any) -> None:
        """UPDATE con bloqueo optimista; solo columnas de la lista blanca."""
        unknown = changes.keys() - _MUTABLE
        if unknown:
            raise ValueError(f"Columnas no modificables: {sorted(unknown)}")
        assignments = "".join(f"{column} = ?, " for column in changes)
        cursor = conn.execute(
            f"UPDATE alerts SET {assignments}version = version + 1, updated_at = ?"  # noqa: S608
            " WHERE id = ? AND version = ?",
            (*changes.values(), now.isoformat(), row["id"], row["version"]),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict("No se pudo aplicar la actualización de la alerta.")

    def _audit(
        self, conn: sqlite3.Connection, now: datetime, actor: Actor | None,
        action: str, code: str, **extra: Any,
    ) -> None:
        self._store.append_audit(conn, {
            "ts": now.isoformat(),
            "actor": actor.username if actor else "system",
            "role": actor.role.value if actor else "system",
            "action": action, "alert": code, **extra,
        })

    @staticmethod
    def _project(row: sqlite3.Row, role: Role, now: datetime) -> View:
        """Vista por rol: oculta contacto según compartimentación y agrega campos calculados."""
        hidden = ALERT_HIDDEN_FIELDS.get(role, frozenset())
        view: View = {
            k: row[k] for k in row.keys() if k not in hidden and k not in _INTERNAL_FIELDS
        }
        active = row["state"] == AlertState.ACTIVA
        due = datetime.fromisoformat(row["next_report_due_at"]) if row["next_report_due_at"] else None
        overdue = bool(active and due is not None and due <= now)
        view["report_interval_hours"] = (
            int(REPORT_INTERVAL[AlertLevel(row["level"])].total_seconds() // 3600) if active else None
        )
        view["overdue"] = overdue
        view["overdue_minutes"] = int((now - due).total_seconds() // 60) if overdue and due else 0
        return view
