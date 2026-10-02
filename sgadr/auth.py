"""Autenticación: usuarios, sesiones con token opaco y bloqueo por intentos fallidos.

Decisiones de seguridad:
- El token de sesión es aleatorio (256 bits) y solo se persiste su SHA-256.
- Un usuario inexistente consume el mismo costo de scrypt que uno real y devuelve
  el mismo error genérico: no permite enumerar cuentas ni medir tiempos.
- El bloqueo es temporal (no permanente) para que un atacante no pueda dejar fuera
  de servicio a los operadores durante una emergencia.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from .catalog import AREAS
from .domain import (
    Actor,
    AuthenticationError,
    NotFound,
    PermissionDenied,
    Role,
    ValidationError,
    clean_text,
)
from .security import hash_password, verify_password
from .store import Store

log = logging.getLogger("sgadr.auth")

Clock = Callable[[], datetime]

_USERNAME: Final = re.compile(r"^[a-z0-9._-]{3,32}$")
_MAX_PASSWORD_LEN: Final = 256
_GENERIC_FAILURE: Final = "Credenciales inválidas o cuenta bloqueada."

_dummy_hash: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _burn_time(password: str) -> None:
    """Iguala el costo de verificación cuando no hay hash real contra el cual comparar."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_urlsafe(16))
    verify_password(password, _dummy_hash)


@dataclass(frozen=True, slots=True)
class Session:
    token: str
    expires_at: datetime
    actor: Actor


class AuthService:
    def __init__(
        self,
        store: Store,
        clock: Clock = _utc_now,
        *,
        session_ttl: timedelta = timedelta(hours=8),
        max_attempts: int = 5,
        lock_duration: timedelta = timedelta(minutes=5),
    ) -> None:
        self._store = store
        self._clock = clock
        self._ttl = session_ttl
        self._max_attempts = max_attempts
        self._lock_duration = lock_duration

    # ---------- administración de usuarios ----------
    # La línea de comandos (en el servidor) crea el primer administrador; después las altas, bajas
    # y restablecimientos se hacen desde la consola con el rol 'admin' (métodos con `actor`).

    def create_user(
        self, username: str, password: str, role: Role, area: str | None = None,
        *, by: str = "cli", temporary: bool = False,
    ) -> None:
        if not isinstance(username, str) or not _USERNAME.fullmatch(username):
            raise ValidationError("Usuario inválido: 3 a 32 caracteres [a-z 0-9 . _ -].")
        if role is Role.AREA:
            area = clean_text("area", area, max_len=80)
            if area not in AREAS:
                raise ValidationError(f"Área inexistente. Áreas válidas: {', '.join(AREAS)}.")
        elif area is not None:
            raise ValidationError("Solo el rol 'area' admite un área asociada.")
        try:
            pwd_hash = hash_password(password)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        now = self._clock()
        with self._store.tx() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, area, created_at,"
                    " must_change_password) VALUES (?, ?, ?, ?, ?, ?)",
                    (username, pwd_hash, role.value, area, now.isoformat(), int(temporary)),
                )
            except sqlite3.IntegrityError as exc:
                raise ValidationError("El usuario ya existe.") from exc
            self._store.append_audit(conn, {
                "ts": now.isoformat(), "action": "user_created", "user": username,
                "role": role.value, "area": area, "by": by,
            })

    def deactivate_user(self, username: str, *, by: str = "cli") -> None:
        """Baja lógica: inhabilita el usuario y revoca todas sus sesiones."""
        now = self._clock()
        with self._store.tx() as conn:
            updated = conn.execute(
                "UPDATE users SET active = 0 WHERE username = ? AND active = 1", (username,)
            )
            if updated.rowcount != 1:
                raise ValidationError("Usuario inexistente o ya inactivo.")
            conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
            self._store.append_audit(conn, {
                "ts": now.isoformat(), "action": "user_deactivated", "user": username, "by": by,
            })

    # --- operaciones del rol 'admin' (la regla se aplica aquí, no solo en la API) ---

    @staticmethod
    def _require_admin(actor: Actor) -> None:
        if actor.role is not Role.ADMIN:
            raise PermissionDenied("Solo la administración del sistema gestiona cuentas.")

    def list_users(self, actor: Actor) -> list[dict[str, object]]:
        self._require_admin(actor)
        now = self._clock()
        rows = self._store.read(
            "SELECT username, role, area, active, locked_until, must_change_password, created_at"
            " FROM users ORDER BY username"
        )
        return [
            {
                "username": r["username"], "role": r["role"], "area": r["area"],
                "active": bool(r["active"]), "created_at": r["created_at"],
                "locked": bool(r["locked_until"] and datetime.fromisoformat(r["locked_until"]) > now),
                "must_change_password": bool(r["must_change_password"]),
            }
            for r in rows
        ]

    def admin_create_user(
        self, actor: Actor, username: str, temporary_password: str, role: Role, area: str | None,
    ) -> None:
        """Alta con clave temporal: la persona debe cambiarla en su primer ingreso."""
        self._require_admin(actor)
        self.create_user(username, temporary_password, role, area, by=actor.username, temporary=True)

    def admin_set_active(self, actor: Actor, username: str, active: bool) -> None:
        self._require_admin(actor)
        if not active:
            if username == actor.username:
                raise ValidationError("No puede dar de baja su propia cuenta.")
            self._ensure_other_admin(username)
            self.deactivate_user(username, by=actor.username)
            return
        now = self._clock()
        with self._store.tx() as conn:
            updated = conn.execute(
                "UPDATE users SET active = 1, failed_attempts = 0, locked_until = NULL"
                " WHERE username = ? AND active = 0", (username,),
            )
            if updated.rowcount != 1:
                raise ValidationError("Usuario inexistente o ya activo.")
            self._store.append_audit(conn, {
                "ts": now.isoformat(), "action": "user_reactivated", "user": username, "by": actor.username,
            })

    def admin_reset_password(self, actor: Actor, username: str, temporary_password: str) -> None:
        """Asigna una clave temporal, desbloquea la cuenta y revoca sus sesiones."""
        self._require_admin(actor)
        if username == actor.username:
            raise ValidationError("Cambie su propia clave desde 'Cambiar mi contraseña'.")
        try:
            pwd_hash = hash_password(temporary_password)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        now = self._clock()
        with self._store.tx() as conn:
            updated = conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 1, failed_attempts = 0,"
                " locked_until = NULL WHERE username = ?", (pwd_hash, username),
            )
            if updated.rowcount != 1:
                raise NotFound("Usuario inexistente.")
            conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
            self._store.append_audit(conn, {
                "ts": now.isoformat(), "action": "password_reset", "user": username, "by": actor.username,
            })

    def _ensure_other_admin(self, username: str) -> None:
        """Nunca debe quedar el sistema sin un administrador activo."""
        rows = self._store.read(
            "SELECT username FROM users WHERE role = ? AND active = 1 AND username <> ?",
            (Role.ADMIN.value, username),
        )
        target = self._store.read("SELECT role FROM users WHERE username = ?", (username,))
        if target and target[0]["role"] == Role.ADMIN.value and not rows:
            raise ValidationError("Debe quedar al menos una cuenta administradora activa.")

    def change_password(self, actor: Actor, token: str, current: object, new: object) -> None:
        """Cambio propio: exige la clave actual y cierra las demás sesiones de la persona."""
        if not (isinstance(current, str) and isinstance(new, str)):
            raise ValidationError("Se requieren la contraseña actual y la nueva.")
        if len(new) > _MAX_PASSWORD_LEN:
            raise ValidationError("La contraseña nueva es demasiado larga.")
        rows = self._store.read("SELECT password_hash FROM users WHERE username = ?", (actor.username,))
        if not rows or not verify_password(current, rows[0]["password_hash"]):
            raise ValidationError("La contraseña actual no es correcta.")
        if new == current:
            raise ValidationError("La contraseña nueva debe ser distinta de la actual.")
        try:
            pwd_hash = hash_password(new)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        now = self._clock()
        with self._store.tx() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE username = ?",
                (pwd_hash, actor.username),
            )
            conn.execute(
                "DELETE FROM sessions WHERE username = ? AND token_hash <> ?",
                (actor.username, _hash_token(token)),
            )
            self._store.append_audit(conn, {
                "ts": now.isoformat(), "action": "password_changed", "user": actor.username,
            })

    # ---------- sesiones ----------

    def login(self, username: object, password: object) -> Session:
        now = self._clock()
        row: sqlite3.Row | None = None
        if isinstance(username, str):
            rows = self._store.read("SELECT * FROM users WHERE username = ?", (username,))
            row = rows[0] if rows else None
        valid_input = isinstance(password, str) and 0 < len(password) <= _MAX_PASSWORD_LEN
        locked = bool(
            row and row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > now
        )

        verified = False
        if row is not None and row["active"] and not locked and valid_input:
            verified = verify_password(str(password), row["password_hash"])
        else:
            _burn_time(password if valid_input else "x")  # type: ignore[arg-type]

        if not verified:
            self._register_failure(row, locked, now)
            raise AuthenticationError(_GENERIC_FAILURE)

        assert row is not None  # verified implica usuario existente
        token = secrets.token_urlsafe(32)
        expires = now + self._ttl
        with self._store.tx() as conn:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE username = ?",
                (row["username"],),
            )
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
            conn.execute(
                "INSERT INTO sessions (token_hash, username, created_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (_hash_token(token), row["username"], now.isoformat(), expires.isoformat()),
            )
            self._store.append_audit(conn, {
                "ts": now.isoformat(), "action": "login", "user": row["username"],
            })
        return Session(token, expires, Actor(
            row["username"], Role(row["role"]), row["area"], bool(row["must_change_password"])))

    def authenticate(self, token: str) -> Actor:
        """Resuelve el token a un actor vigente o lanza AuthenticationError."""
        rows = self._store.read(
            "SELECT s.expires_at, u.username, u.role, u.area, u.active, u.must_change_password"
            " FROM sessions s JOIN users u ON u.username = s.username"
            " WHERE s.token_hash = ?",
            (_hash_token(token),),
        )
        if (
            not rows
            or not rows[0]["active"]
            or datetime.fromisoformat(rows[0]["expires_at"]) <= self._clock()
        ):
            raise AuthenticationError("Sesión inválida o vencida.")
        r = rows[0]
        return Actor(r["username"], Role(r["role"]), r["area"], bool(r["must_change_password"]))

    def logout(self, token: str) -> None:
        now = self._clock()
        with self._store.tx() as conn:
            row = conn.execute(
                "SELECT username FROM sessions WHERE token_hash = ?", (_hash_token(token),)
            ).fetchone()
            if row is None:
                return
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))
            self._store.append_audit(conn, {
                "ts": now.isoformat(), "action": "logout", "user": row["username"],
            })

    # ---------- internos ----------

    def _register_failure(
        self, row: sqlite3.Row | None, was_locked: bool, now: datetime
    ) -> None:
        if row is None:
            # Usuario inexistente: solo log técnico (no se persiste, evita inflar la bitácora).
            log.warning("Intento de acceso con usuario inexistente.")
            return
        if was_locked:
            return  # no se extiende el bloqueo ni se registran intentos durante el mismo
        attempts = row["failed_attempts"] + 1
        locked_until = None
        if attempts >= self._max_attempts:
            locked_until = (now + self._lock_duration).isoformat()
            attempts = 0
        with self._store.tx() as conn:
            conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE username = ?",
                (attempts, locked_until, row["username"]),
            )
            self._store.append_audit(conn, {
                "ts": now.isoformat(), "action": "login_failed", "user": row["username"],
                "locked": locked_until is not None,
            })
