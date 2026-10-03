"""Casos de uso del circuito de demanda.

Cada operación valida permisos y transición, actualiza con bloqueo optimista y
registra la bitácora en la MISMA transacción: o se persiste todo o nada.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .catalog import AREAS
from .domain import (
    DEMAND_READ_ROLES,
    TERMINAL_STATES,
    TRANSITIONS,
    HIDDEN_FIELDS,
    Actor,
    AlertLevel,
    AlertState,
    ConcurrencyConflict,
    DemandState,
    InvalidTransition,
    NewDemand,
    NotFound,
    PermissionDenied,
    Role,
    ValidationError,
    clean_text,
    normalize_key,
)
from .store import Store

Clock = Callable[[], datetime]
View = dict[str, Any]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DemandService:
    def __init__(self, store: Store, clock: Clock = _utc_now) -> None:
        self._store = store
        self._clock = clock

    # ---------- escritura ----------

    def register(self, actor: Actor, cmd: NewDemand) -> View:
        """Ingreso de una demanda: exclusivo del Nodo 07."""
        if actor.role is not Role.NODO_07:
            raise PermissionDenied("La demanda ingresa siempre y exclusivamente por el Nodo 07.")
        data = cmd.validated()
        now = self._clock()
        with self._store.tx() as conn:
            # Vínculo automático con la alerta vigente del municipio: el operador no necesita
            # conocer su id y el nivel queda consistente con la fuente de verdad (la alerta).
            alert = conn.execute(
                "SELECT id, level FROM alerts WHERE municipality_key = ? AND state = ?",
                (normalize_key(data.municipality), AlertState.ACTIVA.value),
            ).fetchone()
            level = data.alert_level or (AlertLevel(alert["level"]) if alert else None)
            if level is None:
                raise ValidationError(
                    "Indique 'alert_level': el municipio no tiene una alerta activa."
                )
            alert_id = alert["id"] if alert else None
            seq = conn.execute(
                "INSERT INTO counters (name, value) VALUES (?, 1) "
                "ON CONFLICT(name) DO UPDATE SET value = value + 1 RETURNING value",
                (f"demand-{now.year}",),
            ).fetchone()["value"]
            code = f"ENOS-{now.year}-{seq:04d}"
            demand_id: int = conn.execute(
                "INSERT INTO demands (code, version, state, alert_level, alert_id, municipality,"
                " locality, resource_type, quantity, reason, contact_name, contact_phone,"
                " created_by, created_at, updated_at)"
                " VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (code, DemandState.RECIBIDA.value, level.value, alert_id, data.municipality,
                 data.locality, data.resource_type, data.quantity, data.reason,
                 data.contact_name, data.contact_phone, actor.username,
                 now.isoformat(), now.isoformat()),
            ).fetchone()["id"]
            self._store.append_audit(conn, {
                "ts": now.isoformat(), "actor": actor.username, "role": actor.role.value,
                "action": "register", "demand": code, "to": DemandState.RECIBIDA.value,
                "alert_level": level.value, "alert_id": alert_id,
            })
        return self.get(actor, demand_id)

    def transition(
        self,
        actor: Actor,
        demand_id: int,
        target: DemandState,
        *,
        expected_version: int,
        note: str | None = None,
        assigned_area: str | None = None,
        response_detail: str | None = None,
    ) -> View:
        """Avanza el estado de una demanda aplicando todas las reglas del circuito."""
        now = self._clock()
        with self._store.tx() as conn:
            row = self._fetch(conn, demand_id)
            current = DemandState(row["state"])
            allowed = TRANSITIONS.get((current, target))
            if allowed is None:
                raise InvalidTransition(f"Transición no permitida: {current} -> {target}.")
            if actor.role not in allowed:
                raise PermissionDenied(f"El rol '{actor.role}' no puede pasar a '{target}'.")
            if actor.role is Role.AREA and (actor.area is None or actor.area != row["assigned_area"]):
                raise PermissionDenied("La demanda no está asignada a su área.")
            if row["version"] != expected_version:
                raise ConcurrencyConflict("La demanda fue modificada por otro usuario; recargue.")

            area = row["assigned_area"]
            detail = row["response_detail"]
            if target is DemandState.ASIGNADA:
                area = clean_text("assigned_area", assigned_area, max_len=80)
                if area not in AREAS:
                    raise ValidationError(f"Área inexistente. Áreas válidas: {', '.join(AREAS)}.")
            if target is DemandState.RESPONDIDA:
                detail = clean_text("response_detail", response_detail, max_len=4000, min_len=10)
            if target in (DemandState.RECHAZADA, DemandState.RECURSOS_AGOTADOS):
                note = clean_text("note", note, max_len=1000, min_len=5)
            elif note is not None:
                note = clean_text("note", note, max_len=1000)

            updated = conn.execute(
                "UPDATE demands SET state = ?, version = version + 1, assigned_area = ?,"
                " response_detail = ?, updated_at = ? WHERE id = ? AND version = ?",
                (target.value, area, detail, now.isoformat(), demand_id, expected_version),
            )
            if updated.rowcount != 1:  # defensa adicional ante carreras
                raise ConcurrencyConflict("No se pudo aplicar la actualización.")
            self._store.append_audit(conn, {
                "ts": now.isoformat(), "actor": actor.username, "role": actor.role.value,
                "action": "transition", "demand": row["code"], "from": current.value,
                "to": target.value, "note": note, "assigned_area": area,
            })
        return self.get(actor, demand_id)

    # ---------- lectura ----------

    def get(self, actor: Actor, demand_id: int) -> View:
        self._require_reader(actor)
        rows = self._store.read("SELECT * FROM demands WHERE id = ?", (demand_id,))
        if not rows:
            raise NotFound(f"Demanda {demand_id} inexistente.")
        if actor.role is Role.AREA and rows[0]["assigned_area"] != actor.area:
            raise PermissionDenied("La demanda no está asignada a su área.")
        return self._project(rows[0], actor.role)

    @staticmethod
    def _require_reader(actor: Actor) -> None:
        if actor.role not in DEMAND_READ_ROLES:
            raise PermissionDenied("Su rol no tiene acceso a las demandas.")

    def list_demands(self, actor: Actor, *, only_open: bool = True) -> list[View]:
        self._require_reader(actor)
        rows = self._store.read("SELECT * FROM demands ORDER BY id DESC")
        if actor.role is Role.AREA:
            rows = [r for r in rows if r["assigned_area"] == actor.area]
        if only_open:
            rows = [r for r in rows if DemandState(r["state"]) not in TERMINAL_STATES]
        return [self._project(r, actor.role) for r in rows]

    def verify_audit(self) -> bool:
        return self._store.verify_audit_chain()

    def audit_recent(self, limit: int) -> list[dict[str, Any]]:
        return self._store.recent_audit(limit)

    # ---------- internos ----------

    @staticmethod
    def _fetch(conn: sqlite3.Connection, demand_id: int) -> sqlite3.Row:
        row: sqlite3.Row | None = conn.execute(
            "SELECT * FROM demands WHERE id = ?", (demand_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"Demanda {demand_id} inexistente.")
        return row

    @staticmethod
    def _project(row: sqlite3.Row, role: Role) -> View:
        """Proyección por rol: oculta campos según la política de compartimentación."""
        hidden = HIDDEN_FIELDS.get(role, frozenset())
        return {k: row[k] for k in row.keys() if k not in hidden}
